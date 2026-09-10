"""
深度搜索结果排序(执行表 P1):合并去重 → 相关度/权威性/时效加权 → 多样性约束。

打分规则(确定性,LLM 重排将在接入模型后叠加):
    score = 主题词命中×3 + 原始问句 bigram 重合×1
          + 来源权重 + 引用数权威性 + 时效加成
"""
import re

from rag.index import STOPWORDS, _bigrams

from .types import SearchHit

SOURCE_WEIGHT = {
    "arXiv": 1.0,
    "Semantic Scholar": 1.2,
    "zbMATH": 1.3,  # 数学专业库 + 同行评论,MSC 分类保证对口
    "StackExchange": 0.9,
    "知识库": 2.0,  # 内部库最贴合课程体系,权重最高
}
PER_SOURCE_CAP = 2  # 多样性:单一来源最多贡献 2 条


def _norm_title(title: str) -> str:
    return re.sub(r"[^\w一-鿿]+", "", title.lower())


def dedup(hits: list[SearchHit]) -> list[SearchHit]:
    seen: set[str] = set()
    out: list[SearchHit] = []
    for h in hits:
        key = _norm_title(h.title)
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(h)
    return out


def score_hit(h: SearchHit, terms: list[str], q_grams: set[str]) -> float:
    text = f"{h.title} {h.snippet}".lower()
    s = 0.0
    for t in terms:
        if t and t not in STOPWORDS and t in text:
            s += 3.0
    s += 1.0 * len(q_grams & _bigrams(text))
    s += SOURCE_WEIGHT.get(h.source, 1.0)
    s += min(h.citations, 50) * 0.02  # 权威性(引用数,封顶贡献 1.0)
    if h.year and h.year >= 2018:
        s += 0.3  # 时效加成
    return s


def rank(hits: list[SearchHit], terms: list[str], question: str, top_k: int = 3) -> list[SearchHit]:
    """合并去重 → 打分排序 → 多样性(top_k 内单源 ≤ PER_SOURCE_CAP)"""
    q_grams = _bigrams(question)
    unique = dedup(hits)
    for h in unique:
        h.score = round(score_hit(h, terms, q_grams), 2)
    unique.sort(key=lambda h: -h.score)

    picked: list[SearchHit] = []
    per_source: dict[str, int] = {}
    for h in unique:
        if h.score <= 1.0:  # 低相关不进结果(宁缺毋滥)
            continue
        if per_source.get(h.source, 0) >= PER_SOURCE_CAP:
            continue
        picked.append(h)
        per_source[h.source] = per_source.get(h.source, 0) + 1
        if len(picked) >= top_k:
            break
    return picked
