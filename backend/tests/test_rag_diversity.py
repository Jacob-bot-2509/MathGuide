"""rag.index:跨主题检索的文档级多样性,以及单主题不被稀释。"""
from __future__ import annotations

from rag.documents import Chunk
from rag.index import KnowledgeIndex


def _chunk(cid: str, title: str, keyword: str, text: str = "") -> Chunk:
    return Chunk(cid, title, title, "节", text or f"{keyword} {keyword}", [keyword], "analysis")


def _index() -> KnowledgeIndex:
    return KnowledgeIndex([
        _chunk("a1", "Doc A", "alpha"),
        _chunk("a2", "Doc A", "alpha"),
        _chunk("a3", "Doc A", "alpha"),
        _chunk("a4", "Doc A", "alpha"),
        _chunk("b1", "Doc B", "beta"),
        _chunk("b2", "Doc B", "beta"),
    ], None)


def test_cross_topic_query_keeps_two_documents_in_top_k():
    hits = _index().search("alpha beta", 3)
    titles = [chunk.title for chunk, _ in hits]
    assert "Doc A" in titles and "Doc B" in titles, titles
    assert titles.count("Doc A") <= 2


def test_single_topic_query_keeps_original_ranking():
    hits = _index().search("alpha", 3)
    assert [chunk.title for chunk, _ in hits] == ["Doc A", "Doc A", "Doc A"]


def test_diversity_does_not_change_top_one():
    hits = _index().search("alpha beta", 1)
    assert len(hits) == 1
    assert hits[0][0].title == "Doc A"
