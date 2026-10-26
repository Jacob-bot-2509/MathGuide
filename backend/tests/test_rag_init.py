"""rag.init:embedding 冷启动失败必须降级关键词检索,不能拖垮后端启动。"""
from __future__ import annotations

import rag
from rag import documents
from rag.index import KnowledgeIndex


class FailingEmbedder:
    def embed_chunks(self, chunks):
        raise RuntimeError("embedding service down")

    def embed_query(self, text):
        raise RuntimeError("embedding service down")


class _NoopThread:
    def __init__(self, *args, **kwargs):
        pass

    def start(self):
        pass


def _write_knowledge(base):
    base.mkdir()
    (base / "limits.md").write_text(
        "---\n"
        "title: 函数极限\n"
        "title_en: Limits\n"
        "keywords: [\"极限\", \"limit\"]\n"
        "category: analysis\n"
        "---\n\n"
        "## 定义\n"
        "极限的定义: $\\lim_{x\\to 0} x = 0$。\n",
        encoding="utf-8",
    )


def test_init_falls_back_when_index_embedding_fails(tmp_path, monkeypatch):
    knowledge = tmp_path / "knowledge"
    _write_knowledge(knowledge)
    monkeypatch.setattr(rag, "KNOWLEDGE_DIR", knowledge)
    monkeypatch.setattr(rag.embed, "is_configured", lambda: True)
    monkeypatch.setattr(rag.embed, "Embedder", lambda: FailingEmbedder())
    monkeypatch.setattr(rag.threading, "Thread", _NoopThread)

    old = (rag._index, rag._embedder, rag._stamp, rag._terms)
    try:
        rag._index = None
        rag._embedder = None
        rag._stamp = None
        rag._terms = frozenset()

        rag.init()  # 不抛异常就是本用例的核心断言

        assert rag._embedder is not None  # 配置仍在,但索引已降级
        assert rag.search("极限", 1)
        assert "极限" in rag.terms()
    finally:
        rag._index, rag._embedder, rag._stamp, rag._terms = old


def test_init_without_embedding_config_uses_keyword_index(tmp_path, monkeypatch):
    knowledge = tmp_path / "knowledge"
    _write_knowledge(knowledge)
    monkeypatch.setattr(rag, "KNOWLEDGE_DIR", knowledge)
    monkeypatch.setattr(rag.embed, "is_configured", lambda: False)

    old = (rag._index, rag._embedder, rag._stamp, rag._terms)
    try:
        rag.init()
        assert rag._embedder is None
        assert rag.search("limit", 1)
    finally:
        rag._index, rag._embedder, rag._stamp, rag._terms = old


def test_knowledge_index_propagates_embedding_failure(tmp_path):
    knowledge = tmp_path / "knowledge"
    _write_knowledge(knowledge)
    chunks = documents.load_knowledge(knowledge)
    try:
        KnowledgeIndex(chunks, FailingEmbedder())
    except RuntimeError as exc:
        assert "embedding" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("KnowledgeIndex 应把 embedding 失败抛给调用方")


def test_init_falls_back_to_empty_index_when_knowledge_unreadable(tmp_path, monkeypatch):
    """连关键词索引都装不起来时,用空索引启动;绝不把异常放给 uvicorn。"""
    monkeypatch.setattr(rag, "KNOWLEDGE_DIR", tmp_path / "missing")
    monkeypatch.setattr(rag.embed, "is_configured", lambda: False)

    def boom(base):
        raise RuntimeError("knowledge dir unreadable")

    monkeypatch.setattr(rag, "load_knowledge", boom)

    old = (rag._index, rag._embedder, rag._stamp, rag._terms)
    try:
        rag.init()
        assert rag.search("任意问题", 1) == []
        assert rag.terms() == frozenset()
    finally:
        rag._index, rag._embedder, rag._stamp, rag._terms = old
