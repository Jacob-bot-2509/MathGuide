"""
问题路由(执行表 P0):决定一条数学输入走哪条应答链路。

- "simple"   → 知识库直答 / 方法论框架(现有链路,零成本快答);
- "research" → 跨论文库深度搜索(P1 起的 rag/search 管线;当前为占位分支)。

判定顺序(与 chat.py 协作):
    闲聊(chat.py _chitchat_kind)→ research 意图标记 → 知识库命中 → 数学题 → 其余按闲聊。
研究意图优先于知识命中:「泰勒展开的最新研究进展」虽命中知识库,仍应走搜索。

接入 LLM 后,可在此追加模型意图判断作为第二道保险(规则层保持离线可用)。
"""
import re

# 研究型意图标记(中英;收录"找文献/查研究现状"类措辞,保持精确避免误伤)
RESEARCH_MARKERS = (
    "最新研究", "研究进展", "研究现状", "研究前沿", "前沿", "最新成果", "文献", "论文",
    "综述", "相关工作", "学术动态", "有哪些成果", "进展如何", "发展现状", "最新论文",
    "state of the art", "sota", "recent research", "recent papers", "latest research",
    "latest papers", "literature", "survey", "related work", "research progress",
)

_RESEARCH_RE = re.compile("|".join(re.escape(m) for m in RESEARCH_MARKERS), re.IGNORECASE)


def is_research_intent(text: str) -> bool:
    """是否属于研究型提问(需要跨论文库搜索佐证)"""
    return bool(_RESEARCH_RE.search(text))


def classify(question: str, chunks: list) -> str:
    """在已排除闲聊的前提下,判断走简单应答还是深度搜索。

    chunks 为 rag.search 的命中列表(可能为空)。
    """
    if is_research_intent(question):
        return "research"
    return "simple"
