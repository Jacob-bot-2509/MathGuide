"""
RAG 检索增强生成:知识库加载 → 检索 → prompt 组装。

对外接口:
    init()              启动时装载知识目录并建索引
    search(query, k)    返回 [(Chunk, score)] 相关片段
    build_system(chunks, cmd, zh)  组装模型 system prompt(检索知识 + 指令 + 格式约束)

知识库热更新:knowledge/ 目录内容变化(增删改文档)后,下次检索自动重建索引,
开发期无需重启后端。embedding 模式(配置 MG_EMBED_*)下重建会复用磁盘缓存。
"""
from pathlib import Path

from .documents import Chunk, load_knowledge
from .index import KnowledgeIndex
from . import embed, llm

KNOWLEDGE_DIR = Path(__file__).resolve().parent.parent / "knowledge"

_index: KnowledgeIndex | None = None
_embedder: embed.Embedder | None = None
_stamp: tuple[int, float] | None = None
_terms: frozenset[str] = frozenset()


def _dir_stamp() -> tuple[int, float]:
    """(文件数, 最新 mtime) 签名:与上次不同即视为知识库有变化"""
    files = [p for p in KNOWLEDGE_DIR.glob("*") if p.suffix in (".md", ".txt")]
    mtimes = [p.stat().st_mtime for p in files]
    return len(files), (max(mtimes) if mtimes else 0.0)


def init() -> None:
    """装载知识库并构建索引(启动时调用)"""
    global _index, _embedder, _stamp, _terms
    _embedder = embed.Embedder() if embed.is_configured() else None
    _index = KnowledgeIndex(load_knowledge(KNOWLEDGE_DIR), _embedder)
    _stamp = _dir_stamp()
    _terms = _collect_terms()


def search(query: str, top_k: int = 3) -> list[tuple[Chunk, float]]:
    """检索相关片段;知识库文件有增删改时自动重建索引后返回"""
    global _index, _stamp, _terms
    assert _index is not None, "rag.init() 未调用"
    if _dir_stamp() != _stamp:
        _index = KnowledgeIndex(load_knowledge(KNOWLEDGE_DIR), _embedder)
        _stamp = _dir_stamp()
        _terms = _collect_terms()
    return _index.search(query, top_k)


def terms() -> frozenset[str]:
    """知识库全部触发词(用于聊天层判断「是否确切数学问题」)"""
    return _terms


def _collect_terms() -> frozenset[str]:
    chunks = load_knowledge(KNOWLEDGE_DIR)
    return frozenset(kw for c in chunks for kw in c.keywords)


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


__all__ = ["init", "search", "build_system", "llm", "embed", "Chunk"]
