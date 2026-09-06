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


def _dir_stamp() -> tuple[int, float]:
    """(文件数, 最新 mtime) 签名:与上次不同即视为知识库有变化"""
    files = [p for p in KNOWLEDGE_DIR.glob("*") if p.suffix in (".md", ".txt")]
    mtimes = [p.stat().st_mtime for p in files]
    return len(files), (max(mtimes) if mtimes else 0.0)


def init() -> None:
    """装载知识库并构建索引(启动时调用)"""
    global _index, _embedder, _stamp
    _embedder = embed.Embedder() if embed.is_configured() else None
    _index = KnowledgeIndex(load_knowledge(KNOWLEDGE_DIR), _embedder)
    _stamp = _dir_stamp()


def search(query: str, top_k: int = 3) -> list[tuple[Chunk, float]]:
    """检索相关片段;知识库文件有增删改时自动重建索引后返回"""
    global _index, _stamp
    assert _index is not None, "rag.init() 未调用"
    if _dir_stamp() != _stamp:
        _index = KnowledgeIndex(load_knowledge(KNOWLEDGE_DIR), _embedder)
        _stamp = _dir_stamp()
    return _index.search(query, top_k)


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
        "难度(基础/进阶/竞赛)由你自己按问题措辞判断,并在开头用一行标明。",
        "",
        "以下是从知识库检索到的参考资料,请优先依据它们回答;"
        "资料不足以回答时,可结合自身数学知识补充,并注明「以下内容超出知识库,仅供参考」。"
        "如果用户只是寒暄、闲聊或一般陈述(不是数学问题),请自然友好地回应,"
        "不要套用解题框架,也不要输出难度判定。",
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
