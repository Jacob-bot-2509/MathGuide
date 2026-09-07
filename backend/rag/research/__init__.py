"""
深度搜索编排(执行表 P1):研究型提问 → 查询改写 → 多源并发搜索 → 合并排序。

对外接口:
    expand_query(question) → 检索词列表(中→英术语映射 + 英文词提取;
        接入 LLM 后此函数替换为模型查询改写,签名不变)
    deep_search(question, top_k) → SearchOutcome(≤15s,单源失败不影响整体)

来源:arXiv / Semantic Scholar / OpenAlex / StackExchange(外网,各自超时熔断)
+ 内部知识库。Semantic Scholar 可配 MG_S2_API_KEY(免费申请)走专属配额;
OpenAlex 可配 MG_CONTACT_MAIL 进礼貌池;受限网络下被限流的源自动跳过。
"""
import asyncio
import re
import time

from rag import route
from rag import search as kb_search
from rag.index import STOPWORDS, _bigrams

from . import rank, sources
from .types import SearchHit, SearchOutcome

__all__ = ["expand_query", "deep_search", "SearchHit", "SearchOutcome"]

# 中文术语 → 英文检索词(查询改写用;LLM 接入后可由模型改写替换,规则层保持离线可用)
ZH2EN = {
    "泰勒展开": "taylor expansion", "泰勒": "taylor series", "麦克劳林": "maclaurin series",
    "极限": "limit", "导数": "derivative", "微分": "differential", "积分": "integral",
    "级数": "series", "收敛": "convergence", "黎曼猜想": "riemann hypothesis", "黎曼": "riemann",
    "微分方程": "differential equation", "常微分": "ordinary differential equation",
    "偏微分": "partial differential equation",
    "线性代数": "linear algebra", "矩阵": "matrix", "行列式": "determinant",
    "特征值": "eigenvalue", "特征向量": "eigenvector",
    "概率": "probability", "正态分布": "normal distribution", "期望": "expectation",
    "方差": "variance", "大数定律": "law of large numbers", "中心极限定理": "central limit theorem",
    "复变": "complex analysis", "留数": "residue", "解析函数": "analytic function",
    "拓扑": "topology", "紧致": "compact", "同胚": "homeomorphism",
    "傅里叶": "fourier", "中值定理": "mean value theorem",
    "拉格朗日": "lagrange", "柯西": "cauchy", "曲率": "curvature",
}

MAX_TERMS = 6


def expand_query(question: str) -> list[str]:
    """从问句提取检索词:剥离研究意图词 → 中文术语映射英文 → 英文词提取"""
    t = question.lower()
    for m in sorted(route.RESEARCH_MARKERS, key=len, reverse=True):
        t = t.replace(m, " ")
    terms: list[str] = []
    for zh, en in sorted(ZH2EN.items(), key=lambda kv: -len(kv[0])):
        if zh.lower() in t:
            terms.append(en)
            t = t.replace(zh.lower(), " ")
    terms += [tok for tok in re.findall(r"[a-z][a-z-]{2,}", t) if tok not in STOPWORDS]
    seen: set[str] = set()
    out: list[str] = []
    for term in terms:
        if term not in seen:
            seen.add(term)
            out.append(term)
    return out[:MAX_TERMS]


async def deep_search(question: str, top_k: int = 3, timeout: float = 15.0) -> SearchOutcome:
    terms = expand_query(question)
    outcome = SearchOutcome(question=question, terms=terms)
    query = " ".join(terms)
    started = time.perf_counter()

    # 内部知识库(同步、必然成功)
    internal = [
        SearchHit("知识库", c.title, c.text[:400], "", 0, "", 0)
        for c, _s in kb_search(question, top_k=3)
    ]
    outcome.sources["知识库"] = len(internal)
    outcome.hits.extend(internal)

    async def run(name: str, fn) -> None:
        try:
            hs = await asyncio.wait_for(fn(query), timeout=max(timeout - 2, 5))
            outcome.hits.extend(hs)
            outcome.sources[name] = len(hs)
        except Exception as exc:  # noqa: BLE001 单源失败只记录,不影响其他源
            outcome.errors.append(f"{name}:{type(exc).__name__}")

    await asyncio.gather(
        run("arXiv", sources.search_arxiv),
        run("SemanticScholar", sources.search_semantic_scholar),
        run("OpenAlex", sources.search_openalex),
        run("StackExchange", sources.search_stackexchange),
    )

    outcome.elapsed = round(time.perf_counter() - started, 2)
    outcome.hits = rank.rank(outcome.hits, terms, question, top_k)
    return outcome
