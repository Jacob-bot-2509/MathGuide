"""rag/__init__ 的降级与索引重建分支。

这个文件的承诺是「检索失败一律降级,不阻断后端」;缺的 26 行正是这些降级:
embedding 构造失败、预热失败、知识库文件在 glob 与 stat 之间消失、
以及知识库变更后的重建(含重建失败再降级)。写错的后果是**后端起不来**,
或者知识库更新后永远检索到旧内容。
"""
from __future__ import annotations

import types

import pytest

import rag


class FakeIndex:
    def __init__(self, chunks=None):
        self.calls: list[tuple[str, int, float | None]] = []
        self.chunks = chunks or []

    def search(self, query, top_k, vector_only_min=None):
        self.calls.append((query, top_k, vector_only_min))
        return [(f"chunk-{i}", 0.9) for i in range(min(top_k, len(self.chunks) or 1))]


@pytest.fixture(autouse=True)
def _restore_rag_globals():
    """init() 会写模块级全局;测完必须还原,否则会污染后续测试文件。"""
    saved = (rag._index, rag._embedder, rag._stamp, rag._terms)
    yield
    rag._index, rag._embedder, rag._stamp, rag._terms = saved


class FakeDir:
    def __init__(self, files):
        self._files = files

    def glob(self, _pattern):
        return list(self._files)


class _File:
    suffix = ".md"

    def __init__(self, mtime=None):
        self._mtime = mtime

    def stat(self):
        if self._mtime is None:
            raise OSError("file vanished between glob and stat")
        return types.SimpleNamespace(st_mtime=self._mtime)


def test_dir_stamp_skips_files_that_disappear(monkeypatch):
    monkeypatch.setattr(rag, "KNOWLEDGE_DIR", FakeDir([_File(100.0), _File(None)]))

    # 文件数按 glob 结果算(2),小时取存活文件的 mtime;不因一次竞态抛异常
    assert rag._dir_stamp() == (2, 100.0)


def test_dir_stamp_without_files_is_zero(monkeypatch):
    monkeypatch.setattr(rag, "KNOWLEDGE_DIR", FakeDir([]))
    assert rag._dir_stamp() == (0, 0.0)


def test_init_falls_back_to_keyword_mode_when_embedder_construction_fails(monkeypatch):
    def boom():
        raise RuntimeError("embedding service unreachable")

    monkeypatch.setattr(rag.embed, "is_configured", lambda: True)
    monkeypatch.setattr(rag.embed, "Embedder", boom)
    monkeypatch.setattr(rag, "_load_index", lambda _embedder: FakeIndex())
    monkeypatch.setattr(rag, "_collect_terms", lambda _index: frozenset({"极限"}))
    monkeypatch.setattr(rag, "_dir_stamp", lambda: (1, 1.0))

    rag.init()

    assert rag._embedder is None      # 降级为关键词模式
    assert rag._index is not None     # 索引照样装载,后端能起
    assert rag._terms == frozenset({"极限"})


def test_warm_embedder_swallows_failures(monkeypatch):
    class BadEmbedder:
        def embed_query(self, _text):
            raise RuntimeError("cold start")

    monkeypatch.setattr(rag, "_embedder", BadEmbedder())
    rag._warm_embedder()              # 不能抛:预热失败不影响启动与检索

    calls = []

    class GoodEmbedder:
        def embed_query(self, text):
            calls.append(text)
            return [0.1, 0.2]

    monkeypatch.setattr(rag, "_embedder", GoodEmbedder())
    rag._warm_embedder()
    assert calls == ["预热"]


def test_search_rebuilds_when_knowledge_changes(monkeypatch):
    old_index = FakeIndex()
    new_index = FakeIndex(["a", "b", "c"])
    monkeypatch.setattr(rag, "_index", old_index)
    monkeypatch.setattr(rag, "_stamp", (1, 1.0))
    monkeypatch.setattr(rag, "_dir_stamp", lambda: (2, 2.0))     # 目录变了
    monkeypatch.setattr(rag, "_load_index", lambda _embedder: new_index)
    monkeypatch.setattr(rag, "_collect_terms", lambda _index: frozenset())
    monkeypatch.setattr(rag, "is_math_question", lambda _q: False)

    result = rag.search("什么是极限", top_k=2)

    assert len(result) == 2
    assert new_index.calls == [("什么是极限", 2, None)]
    assert rag._stamp == (2, 2.0)     # 重建后时间戳更新,不会每次都重建


def test_search_falls_back_when_rebuild_fails(monkeypatch):
    monkeypatch.setattr(rag, "_index", FakeIndex())
    monkeypatch.setattr(rag, "_stamp", (1, 1.0))
    monkeypatch.setattr(rag, "_dir_stamp", lambda: (2, 2.0))

    def boom(_embedder):
        raise RuntimeError("knowledge dir unreadable")

    fallback = FakeIndex(["x"])
    monkeypatch.setattr(rag, "_load_index", boom)
    monkeypatch.setattr(rag, "_load_index_or_empty", lambda: fallback)
    monkeypatch.setattr(rag, "_collect_terms", lambda _index: frozenset())
    monkeypatch.setattr(rag, "is_math_question", lambda _q: False)

    result = rag.search("极限")

    assert len(result) == 1           # 用空索引兜住,检索链路不断
    assert fallback.calls


def test_search_uses_lower_vector_floor_for_math_questions(monkeypatch):
    index = FakeIndex(["a"])
    monkeypatch.setattr(rag, "_index", index)
    monkeypatch.setattr(rag, "_stamp", (1, 1.0))
    monkeypatch.setattr(rag, "_dir_stamp", lambda: (1, 1.0))
    monkeypatch.setattr(rag, "is_math_question", lambda _q: True)

    rag.search("求下列极限")

    assert index.calls[0][2] == rag.MATH_VECTOR_ONLY_MIN
