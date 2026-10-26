"""research:排序去重、精排解析、查询构造、重试策略与 HTTPS/响应上限。"""
from __future__ import annotations

import asyncio
import threading
import urllib.error

import pytest

from rag.research import _query_for, expand_query, rank, rerank, sources
from rag.research.types import KB_SOURCE, SearchHit


def test_dedup_normalizes_titles():
    hits = [
        SearchHit("arXiv", "Hello World"),
        SearchHit("OpenAlex", "hello-world"),
        SearchHit("arXiv", "Other"),
    ]
    assert [h.title for h in rank.dedup(hits)] == ["Hello World", "Other"]


def test_rank_respects_top_k_and_per_source_cap():
    hits = [SearchHit("arXiv", f"taylor expansion {i}", "taylor expansion") for i in range(5)]
    picked = rank.rank(hits, ["taylor"], "taylor expansion", top_k=3)
    assert len(picked) == 2  # 单源上限 2


def test_rank_drops_low_relevance():
    hits = [
        SearchHit("arXiv", "unrelated", "nothing"),
        SearchHit(KB_SOURCE, "极限", "极限的定义"),
    ]
    picked = rank.rank(hits, ["极限"], "极限", top_k=3)
    assert [h.source for h in picked] == [KB_SOURCE]


def test_rerank_parse_object_and_list():
    assert rerank._parse('{"1": 88, "2": 12}', 2) == [88.0, 12.0]
    assert rerank._parse('[{"id": 1, "score": 88}, {"id": 2, "score": 12}]', 2) == [88.0, 12.0]
    assert rerank._parse("[90, 10]", 2) == [90.0, 10.0]
    assert rerank._parse('noise {"1": 100} noise', 2) == [100.0, 50.0]


def test_rerank_parse_malformed_raises():
    with pytest.raises(ValueError):
        rerank._parse("not json", 2)


def test_expand_query_maps_chinese_terms():
    terms = expand_query("泰勒展开的最新研究进展")
    assert terms == ["taylor expansion"]


def test_expand_query_extracts_english_terms():
    terms = expand_query("recent research on limits and convergence")
    assert "limits" in terms
    assert "convergence" in terms
    assert "on" not in terms


def test_query_for_per_source_syntax():
    terms = ["a", "b", "c", "d"]
    assert _query_for("arXiv", terms, "q") == 'all:"a" OR all:"b" OR all:"c"'
    assert _query_for("zbMATH", terms, "q") == "a b"
    assert _query_for("StackExchange", terms, "q") == "a"
    assert _query_for("Semantic Scholar", terms, "q") == "a b c d"
    assert _query_for("arXiv", [], "fallback") == 'all:"fallback"'


def test_arxiv_uses_https(monkeypatch):
    captured: list[str] = []

    def fake_get(url, timeout, headers=None):
        captured.append(url)
        return '<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom"></feed>'

    monkeypatch.setattr(sources, "_http_get", fake_get)
    assert asyncio.run(sources.search_arxiv("all:\"x\"")) == []
    assert captured and captured[0].startswith("https://export.arxiv.org/")


def test_retry_does_not_retry_4xx(monkeypatch):
    monkeypatch.setattr(sources, "BACKOFF_BASE", 0)
    calls = []

    async def failing():
        calls.append(1)
        raise urllib.error.HTTPError("https://x", 404, "not found", None, None)

    with pytest.raises(urllib.error.HTTPError):
        asyncio.run(sources._retry(failing, retries=2))
    assert len(calls) == 1


def test_retry_retries_5xx(monkeypatch):
    monkeypatch.setattr(sources, "BACKOFF_BASE", 0)
    calls = []

    async def failing():
        calls.append(1)
        raise urllib.error.HTTPError("https://x", 503, "unavailable", None, None)

    with pytest.raises(urllib.error.HTTPError):
        asyncio.run(sources._retry(failing, retries=2))
    assert len(calls) == 3


def test_http_get_rejects_oversized_response(monkeypatch):
    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self, n=-1):
            return b"abcdef"

    monkeypatch.setattr(sources.urllib.request, "urlopen", lambda *a, **k: FakeResponse())
    monkeypatch.setattr(sources, "MAX_RESPONSE_BYTES", 3)
    with pytest.raises(ValueError):
        sources._http_get("https://example.invalid", 1)


def test_async_http_get_closes_inflight_response_on_cancel(monkeypatch):
    """wait_for 取消时,线程里的阻塞 read 应被 close() 唤醒,而不是空转到超时。"""
    class BlockingResponse:
        def __init__(self):
            self.started = threading.Event()
            self.released = threading.Event()
            self.closed = False

        def read(self, n=-1):
            self.started.set()
            self.released.wait(2)
            if self.closed:
                raise ValueError("response closed")
            return b""

        def close(self):
            self.closed = True
            self.released.set()

        def __enter__(self):
            return self

        def __exit__(self, *args):
            self.close()

    resp = BlockingResponse()
    monkeypatch.setattr(sources.urllib.request, "urlopen", lambda *a, **k: resp)

    async def run():
        task = asyncio.create_task(
            sources._http_get_async("https://example.invalid", 5))
        assert await asyncio.to_thread(resp.started.wait, 1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert resp.closed

    asyncio.run(run())
