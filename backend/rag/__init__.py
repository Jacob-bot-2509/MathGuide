"""
RAG 检索增强生成:知识库加载 → 检索 → prompt 组装。

对外接口:
    init()              启动时装载知识目录并建索引
    search(query, k)    返回 [(Chunk, score)] 相关片段
    build_system(chunks, cmd, zh)  组装模型 system prompt(检索知识 + 指令 + 格式约束)

知识库热更新:knowledge/ 目录内容变化(增删改文档)后,下次检索自动重建索引,
开发期无需重启后端。embedding 模式(配置 MG_EMBED_*)下重建会复用磁盘缓存。
"""
import re
import threading
from pathlib import Path

from .documents import Chunk, load_knowledge
from .index import KnowledgeIndex
from . import embed, llm, route

KNOWLEDGE_DIR = Path(__file__).resolve().parent.parent / "knowledge"

_index: KnowledgeIndex | None = None
_embedder: embed.Embedder | None = None
_stamp: tuple[int, float] | None = None
_terms: frozenset[str] = frozenset()
_rebuild_lock = threading.Lock()  # 索引重建串行化(检索已移出事件循环,防并发重建竞争)


def _dir_stamp() -> tuple[int, float]:
    """(文件数, 最新 mtime) 签名:与上次不同即视为知识库有变化"""
    files = [p for p in KNOWLEDGE_DIR.glob("*") if p.suffix in (".md", ".txt")]
    mtimes = [p.stat().st_mtime for p in files]
    return len(files), (max(mtimes) if mtimes else 0.0)


def init() -> None:
    """装载知识库并构建索引(启动时调用);
    embedding 服务不可用时降级为关键词模式,不让后端起不来"""
    global _index, _embedder, _stamp, _terms
    if embed.is_configured():
        try:
            _embedder = embed.Embedder()
        except Exception as exc:  # noqa: BLE001
            print(f"[rag] embedding 初始化失败,降级为关键词检索: {exc}")
            _embedder = None
    else:
        _embedder = None
    _index = KnowledgeIndex(load_knowledge(KNOWLEDGE_DIR), _embedder)
    _stamp = _dir_stamp()
    _terms = _collect_terms(_index)
    if _embedder is not None:
        threading.Thread(target=_warm_embedder, daemon=True, name="embed-warmup").start()


def _warm_embedder() -> None:
    """后台预热 embedding 连接:服务端冷启动实测可达 40s+(之后 0.2s),
    放在启动期后台完成,避免用户第一个问题被冷启动卡住"""
    try:
        assert _embedder is not None
        _embedder.embed_query("预热")
        print("[rag] embedding 预热完成")
    except Exception as exc:  # noqa: BLE001 预热失败不影响启动与检索(查询侧仍有降级)
        print(f"[rag] embedding 预热失败(不影响启动): {exc}")


def search(query: str, top_k: int = 3) -> list[tuple[Chunk, float]]:
    """检索相关片段;知识库文件有增删改时自动重建索引后返回。
    重建时 embedding 失败同样降级关键词模式,检索链路永不因向量服务崩断。
    注意:本函数为同步实现,异步调用方须用 asyncio.to_thread 包裹,
    否则 embedding 请求(可能数十秒)会阻塞事件循环、冻住整个后端"""
    global _index, _stamp, _terms
    assert _index is not None, "rag.init() 未调用"
    if _dir_stamp() != _stamp:
        with _rebuild_lock:
            if _dir_stamp() != _stamp:  # 双检:并发进入时只重建一次
                try:
                    _index = KnowledgeIndex(load_knowledge(KNOWLEDGE_DIR), _embedder)
                except Exception as exc:  # noqa: BLE001
                    print(f"[rag] 索引重建失败,降级为关键词模式: {exc}")
                    _index = KnowledgeIndex(load_knowledge(KNOWLEDGE_DIR), None)
                _stamp = _dir_stamp()
                _terms = _collect_terms(_index)
    return _index.search(query, top_k)


def terms() -> frozenset[str]:
    """知识库全部触发词(用于聊天层判断「是否确切数学问题」)"""
    return _terms


# 确切数学问题的措辞标记(与知识库触发词共同判定;命中才走答题框架)
MATH_EXTRA_WORDS = (
    "求", "证明", "计算", "求解", "求导", "求证", "这道", "这题", "例题", "题目", "公式", "定理", "数学",
    "怎么做", "怎么算", "如何求", "如何证",
    "solve", "prove", "compute", "evaluate", "show that", "theorem", "equation", "problem", "math",
)

# (词表, 已编译正则):词表是知识库触发词的并集,基本不变,
# 缓存后每次请求不再把上百个词重新编译成正则
_math_re_cache: tuple[frozenset[str], re.Pattern] | None = None


def _compile_math_re(terms: frozenset[str]) -> re.Pattern:
    """CJK 子串匹配,英文按词边界;裸「求」加否定回溯,排除「请求/要求」这类日常用词"""
    all_terms = set(terms) | set(MATH_EXTRA_WORDS)
    zh = sorted((t for t in all_terms if not t.isascii()), key=len, reverse=True)
    en = sorted((t for t in all_terms if t.isascii() and len(t) >= 3), key=len, reverse=True)
    zh_parts = [re.escape(t) if t != "求" else r"(?<![请要])求" for t in zh]
    pattern = "|".join(zh_parts + [r"\b" + re.escape(t) + r"\b" for t in en])
    return re.compile(pattern, re.IGNORECASE)


def is_math_question(text: str) -> bool:
    """是否确切数学问题:知识库触发词(terms)与题目措辞任一命中"""
    global _math_re_cache
    if _math_re_cache is None or _math_re_cache[0] is not _terms:
        _math_re_cache = (_terms, _compile_math_re(_terms))
    return bool(_math_re_cache[1].search(text))


def _collect_terms(index: KnowledgeIndex) -> frozenset[str]:
    """触发词取自已装载的索引:再调一次 load_knowledge 会把整个知识库解析第二遍
    (含 frontmatter 与切片),启动与每次热点重建都要白付这份开销"""
    return frozenset(kw for c in index.chunks for kw in c.keywords)


def build_system(chunks: list[tuple[Chunk, float]], cmd: str | None, zh: bool = True) -> str:
    """组装 system prompt:检索到的知识片段 + 角色约束 + 指令语义(回答语言跟随提问语言)"""
    lang = (
        "请用简体中文回答,先给严谨的专业表述,再给形象化理解"
        if zh
        else "Answer in the user's language (English), giving a rigorous explanation first, then intuition"
    )
    parts = [
        f"你是 MathGuide,一个高等数学学习与研究助手。{lang},"
        "公式用 LaTeX(行内 $...$,块级 $$...$$)。"
        "回答要有人的温度:语气自然、亲切、不做作,像一位耐心的学长学姐。"
        "对寒暄、闲聊、倾诉等一般对话,像正常人一样回应,不要总把话题拽回数学;"
        "只有用户明确在问数学问题时,才给出专业解答。",
        "解答数学题时:先给出完整解答过程,末尾另起一段「**参考思路**」,"
        "总结本题的解题思路与关键步骤(为什么这么想、可否推广);"
        "一次提问包含若干道题时,逐题给出解答,每题的参考思路紧随该题。",
        "",
        "以下是从知识库检索到的参考资料,请优先依据它们回答;"
        "资料不足以回答时,可结合自身数学知识补充,并注明「以下内容超出知识库,仅供参考」。",
        "",
    ]
    if cmd:
        parts.append(f"用户使用了指令「{cmd}」,请按该指令的功能形态组织回答。")
        parts.append("")
    for i, (c, score) in enumerate(chunks, 1):
        parts.append(f"【资料{i}】{c.title} · {c.section}(相关度 {score:.1f})")
        parts.append(c.text)
        parts.append("")
    return "\n".join(parts).strip()


from . import research  # noqa: E402,F401 深度搜索编排(P1);置于文件末尾,依赖上方 search 等已定义

__all__ = ["init", "search", "build_system", "terms", "is_math_question",
           "llm", "embed", "route", "research", "Chunk"]
