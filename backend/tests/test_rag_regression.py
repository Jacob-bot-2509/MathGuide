"""RAG 检索排序回归(golden)。

为什么需要:检索排序是本项目的核心卖点(v1.25.0 的发布内容就是"排序与召回"),但此前
只有 `test_rag_diversity.py` 覆盖"文档级多样性"一个维度,权重一改就只能靠离线跑
`course-50` 才发现退化。

这里用 `tests/fixtures/rag/` 的 12 个固定切片,锁定当前参数下的 top-k 顺序:

    W_KEYWORD=5.0  W_TITLE=2.0  W_SECTION=1.5  W_BODY=1.0  MIN_SCORE=1.5
    + 正文 bigram 的 IDF 加权 + 章节标题权重

**embedding 关闭**(只走关键词 + bigram),所以不联网、不受时间影响,结果可复现。
改权重/门限会直接让本文件变红 —— 那是刻意的:必须同时更新 golden 并在 PR 里
说明"为什么这次排序变化是对的"。
"""
from __future__ import annotations

from pathlib import Path

from rag.documents import load_knowledge
from rag.index import MIN_SCORE, KnowledgeIndex

FIXTURES = Path(__file__).parent / "fixtures" / "rag"

# query -> 期望 top-3 的切片 id;不足 3 条表示命中本来就不够(不拿无关片段凑数)
GOLDEN = {
    "泰勒公式": ["taylor#1", "taylor#2", "integral#1"],
    "拉格朗日余项": ["taylor#2", "mean_value#1", "taylor#1"],
    "夹逼定理": ["limits#2", "mean_value#1", "limits#1"],
    "牛顿-莱布尼茨公式": ["integral#1", "integral#2", "taylor#1"],
    "矩阵的秩": ["matrix_rank#1", "matrix_rank#2"],
    "级数收敛判别": ["series#2", "series#1"],
    "柯西中值定理": ["mean_value#2", "mean_value#1", "limits#2"],
}


def _index() -> KnowledgeIndex:
    chunks = load_knowledge(FIXTURES)
    assert len(chunks) == 12, f"语料被改动(期望 12 个切片,实际 {len(chunks)})"
    return KnowledgeIndex(chunks, None)


def test_golden_ranking() -> None:
    index = _index()
    for query, expected in GOLDEN.items():
        got = [chunk.id for chunk, _score in index.search(query, 3)]
        assert got == expected, f"{query}:期望 {expected},实际 {got}"


def test_scores_are_descending_and_above_threshold() -> None:
    index = _index()
    for query in GOLDEN:
        scores = [score for _chunk, score in index.search(query, 3)]
        assert scores == sorted(scores, reverse=True), f"{query} 分数不是降序:{scores}"
        assert scores[0] >= MIN_SCORE, f"{query} 首条低于 MIN_SCORE:{scores[0]}"


def test_unrelated_query_returns_nothing() -> None:
    """低于门限就返回空:宁可不答,也不要拿无关资料给错误结论背书。"""
    assert _index().search("量子纠缠退相干", 3) == []


def test_ranking_is_stable_across_rebuilds() -> None:
    """同一语料重建两次顺序一致(字典/集合遍历顺序不该泄漏到排序结果)。"""
    first = [chunk.id for chunk, _score in _index().search("泰勒公式", 3)]
    second = [chunk.id for chunk, _score in _index().search("泰勒公式", 3)]
    assert first == second


def test_taylor_section_beats_neighbouring_concepts() -> None:
    """章节标题命中要压过"只是提到该词"的邻章:泰勒公式问句不该被中值定理抢走。"""
    hits = _index().search("泰勒公式", 1)
    assert hits and hits[0][0].title == "泰勒公式"
