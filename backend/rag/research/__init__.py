"""
深度搜索编排(执行表 P1):研究型提问 → 查询改写 → 多源并发搜索 → 合并排序。

对外接口:
    expand_query(question) → 检索词列表(中→英术语映射 + 英文词提取;
        接入 LLM 后此函数替换为模型查询改写,签名不变)
    deep_search(question, top_k) → SearchOutcome(≤15s,单源失败不影响整体)

来源:arXiv / Semantic Scholar / OpenAlex / StackExchange / zbMATH Open(外网,各自超时熔断)
+ 内部知识库。Semantic Scholar 可配 MG_S2_API_KEY(免费申请)走专属配额;
OpenAlex 可配 MG_CONTACT_MAIL 进礼貌池;zbMATH Open 免 key(数学专业库);
受限网络下被限流的源自动跳过。
"""
import asyncio
import re
import time

from rag import llm, route
from rag import search as kb_search
from rag.index import STOPWORDS

from . import rank, rerank, sources, synthesize
from .types import KB_SOURCE, SearchHit, SearchOutcome

__all__ = ["expand_query", "deep_search", "rerank", "synthesize",
           "SearchHit", "SearchOutcome"]

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
    "数论": "number theory", "素数": "prime number", "同余": "congruence",
    "费马小定理": "fermat's little theorem", "欧拉函数": "euler totient function", "丢番图": "diophantine",
    "复变": "complex analysis", "留数": "residue", "解析函数": "analytic function",
    "拓扑": "topology", "紧致": "compact", "同胚": "homeomorphism",
    "傅里叶": "fourier", "中值定理": "mean value theorem",
    "拉格朗日": "lagrange", "柯西": "cauchy", "曲率": "curvature",
}

MAX_TERMS = 6
DEFAULT_TIMEOUT = 15.0   # 一轮深度搜索的总预算(秒);评测脚本引用此常量,不另抄一份

# 深度搜索源注册表:键 = SearchHit.source(前端勾选框、来源统计、引用区同一口径);
# 顺序即展示顺序。KB_SOURCE 为内部知识库,由编排层直连 rag.search,不走适配器。
SOURCE_FNS = {
    "arXiv": sources.search_arxiv,
    "zbMATH": sources.search_zbmath,
    "Semantic Scholar": sources.search_semantic_scholar,
    "OpenAlex": sources.search_openalex,
    "StackExchange": sources.search_stackexchange,
}
ALL_SOURCES = (KB_SOURCE, *SOURCE_FNS)

# 结果缓存:同一研究问题 TTL 内重复查询直接复用,降低外部源限流风险(演示期同题重问常见)
_cache: dict[str, tuple[float, SearchOutcome]] = {}
_CACHE_TTL = 300.0   # 秒
_CACHE_MAX = 64


def _cache_key(question: str, top_k: int, scope: list[str] | None) -> str:
    """范围(勾选的平台)参与缓存键:换了平台的同题必须重新检索"""
    tag = "all" if not scope else ",".join(sorted(scope))
    return f"{top_k}|{tag}|{question.strip().lower()}"


def expand_query(question: str) -> list[str]:
    """规则版查询改写:剥离研究意图词 → 中文术语映射英文 → 英文词提取。
    LLM 可用时被 _llm_expand_terms 取代(见 deep_search),此函数保留作离线兜底。"""
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


def _query_for(name: str, terms: list[str], question: str) -> str:
    """按源构造检索串(实测差异极大,同一串喂给所有源会大面积 0 命中):
    - arXiv:引号内多词 = 精确短语匹配 → 必须展开成 all:"词" OR all:"词";
    - zbMATH / StackExchange:全文检索,词越多要求全中 → 只取最相关的前 1~2 个;
    - Semantic Scholar / OpenAlex:语义与全文混合,可吃下完整术语串。"""
    t = [x for x in terms if x] or [question]
    if name == "arXiv":
        return " OR ".join(f'all:"{x}"' for x in t[:3])
    if name == "zbMATH":
        return " ".join(t[:2])
    if name == "StackExchange":
        return t[0]
    return " ".join(t)


async def _llm_expand_terms(question: str, timeout: float = 6.0) -> list[str] | None:
    """LLM 查询改写:把口语化研究提问拆成高质量英文检索词(最多 6 个)。
    失败/超时返回 None,由规则版 expand_query 兜底,离线可用性不受影响"""
    system = (
        "你是学术检索助手。把用户的研究问题改写成最多 6 个英文检索关键词或短语,"
        "用逗号分隔,只输出关键词本身,不要任何解释。"
    )

    async def collect() -> list[str]:
        parts: list[str] = []
        async for delta in llm.stream_chat(system, question, role="main", fallback=False):
            parts.append(delta)
            if sum(len(p) for p in parts) >= 200:
                break
        text = "".join(parts).strip()
        terms = [t.strip() for t in re.split(r"[,、;\n]", text) if t.strip()]
        return [t for t in terms if 2 <= len(t) <= 60][:MAX_TERMS]

    try:
        terms = await asyncio.wait_for(collect(), timeout=timeout)
        if terms:
            print(f"[research] LLM 改写: {terms}")
        return terms
    except Exception:  # noqa: BLE001 改写失败不影响主链路,规则版兜底
        return None


async def deep_search(question: str, top_k: int = 3, timeout: float = DEFAULT_TIMEOUT,
                      scope: list[str] | None = None) -> SearchOutcome:
    """scope = 本轮要检索的平台名列表(取自 SOURCE_FNS / KB_SOURCE);
    None 或空 = 全平台。未知名字忽略(白名单外的一律不认,防前端脏数据)"""
    chosen: set[str] | None = None
    if scope:
        picked = {s for s in scope if s in ALL_SOURCES}
        chosen = picked or None  # 勾选全非法 → 退回全平台,不让用户拿到空结果
    key = _cache_key(question, top_k, sorted(chosen) if chosen else None)
    now = time.monotonic()
    hit = _cache.get(key)
    if hit and now - hit[0] < _CACHE_TTL:
        print(f"[research] 缓存命中: {question[:24]}")
        return hit[1]
    started = time.perf_counter()
    # 查询改写:LLM 可用时优先(口语化提问拆词更全),失败回退规则版
    terms = await _llm_expand_terms(question) if llm.is_configured("main") else None
    if not terms:
        terms = expand_query(question)
    outcome = SearchOutcome(question=question, terms=terms)
    query = " ".join(terms)

    # 内部知识库(同步实现,含可能数十秒的 embedding 请求 → 挪出事件循环,
    # 否则会冻住整个后端的所有并发请求)
    if chosen is None or KB_SOURCE in chosen:
        kb_hits = await asyncio.to_thread(kb_search, question, 3)
        internal = [
            SearchHit(KB_SOURCE, c.title, c.text[:400], "", 0, "", 0)
            for c, _s in kb_hits
        ]
        outcome.sources[KB_SOURCE] = len(internal)
        outcome.hits.extend(internal)

    async def run(name: str, fn, budget: float) -> None:
        try:
            hs = await asyncio.wait_for(fn(_query_for(name, terms, question)), timeout=budget)
            outcome.hits.extend(hs)
            outcome.sources[name] = len(hs)
        except Exception as exc:  # noqa: BLE001 单源失败只记录,不影响其他源
            # errors 存来源名(给用户看的话术),细节打日志(给排查用)
            outcome.errors.append(name)
            print(f"[research] {name} 不可达(已跳过): {type(exc).__name__} {exc}")

    # 源搜索预算:LLM 配置时给精排留 6s,总预算仍 ≤ timeout(默认 15s)
    src_budget = max((timeout - 6) if llm.is_configured() else (timeout - 2), 5)
    # 按勾选范围并发(未勾选的源一个请求都不发:省时,也省对方配额);
    # 源名统一取注册表键,与 SearchHit.source 同口径(前端勾选框/引用区一致)
    await asyncio.gather(*[
        run(name, fn, src_budget)
        for name, fn in SOURCE_FNS.items()
        if chosen is None or name in chosen
    ])

    outcome.hits = rank.rank(outcome.hits, terms, question, top_k)
    # P2b:LLM 精排(配置了模型且含外源结果时;纯知识库命中无需精排,
    # 失败自动回退规则排序)
    if (outcome.hits and llm.is_configured()
            and any(h.source != KB_SOURCE for h in outcome.hits)):
        outcome.hits = await rerank.rerank(question, outcome.hits, timeout=10.0)
    outcome.elapsed = round(time.perf_counter() - started, 2)
    # 存入缓存(超容逐出最旧一条,简单 LRU)
    _cache[key] = (time.monotonic(), outcome)
    if len(_cache) > _CACHE_MAX:
        _cache.pop(next(iter(_cache)))
    return outcome
