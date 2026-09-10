"""
问题路由(执行表 P0):决定一条输入走哪条应答链路。

四路(chat.py 的线上链路与 tools/eval_route.py 的评测共用 decide,不各写一份):
    research   → 跨论文库深度搜索(P1/P2 管线)
    knowledge  → 知识库直答(检索命中,零成本快答)
    framework  → 未命中知识库但确属数学题 → 方法论框架
    chat       → 寒暄/闲聊/一般对话 → 会话大脑

判定顺序:研究意图 → 知识命中 → 数学题 → 会话。
研究意图优先于知识命中:「泰勒展开的最新研究进展」虽命中知识库,仍应走搜索 ——
调用方应先判研究意图,再决定要不要付检索开销(见 chat.py 的顺序说明)。

接入 LLM 后,可在此追加模型意图判断作为第二道保险(规则层保持离线可用)。
"""
import re

RESEARCH = "research"
KNOWLEDGE = "knowledge"
FRAMEWORK = "framework"
CHAT = "chat"

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


def decide(question: str, has_chunks: bool, is_math: bool) -> str:
    """唯一裁决入口:返回 RESEARCH / KNOWLEDGE / FRAMEWORK / CHAT。

    has_chunks = 知识库是否检索到内容(要付检索成本,由调用方决定何时算);
    is_math    = 是否确切数学题(依赖知识库词表,见 rag.is_math_question)。
    两者都由调用方传入:本模块保持零依赖,不被 rag 反向依赖。"""
    if is_research_intent(question):
        return RESEARCH
    if has_chunks:
        return KNOWLEDGE
    return FRAMEWORK if is_math else CHAT
