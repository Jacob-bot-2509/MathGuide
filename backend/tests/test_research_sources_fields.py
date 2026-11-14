"""深度搜索源适配器:字段归一化、重试口径与「单源失败不影响其余」。

为什么不合并进 test_research_sources.py:那个文件测的是检索来源的接口层
(sources/info、来源白名单一类),本文件专门盯 rag/research/sources.py 里
五个外部源的字段映射与容灾 —— 断言的是"外部返回脏数据时,进库的那条
SearchHit 长什么样"和"哪个源挂了,错误落在哪",而不是"没抛异常"。
"""
from __future__ import annotations

import asyncio
import threading
import urllib.error

import pytest

from rag.research import sources as src


def _run(coro):
    return asyncio.run(coro)


def _fake_json(text: str):
    """把 _http_get_async 换掉:外部源只关心解析,不该真发请求。"""
    async def _get(url, timeout, headers=None):
        return text
    return _get


def _http_error(code: int) -> urllib.error.HTTPError:
    return urllib.error.HTTPError("https://example.org", code, "err", {}, None)


# ---------------------------------------------------------------------------
# 重试与取字节
# ---------------------------------------------------------------------------

def test_is_retryable_only_retries_rate_limit_and_server_errors():
    """4xx 里只重试 408/425/429,其余立刻放弃。

    对 403/404 重试是纯浪费配额,还会把"没有这篇"拖成 3 次请求。
    """
    assert src._is_retryable(_http_error(429)) is True
    assert src._is_retryable(_http_error(408)) is True
    assert src._is_retryable(_http_error(425)) is True
    assert src._is_retryable(_http_error(500)) is True
    assert src._is_retryable(_http_error(503)) is True
    assert src._is_retryable(_http_error(404)) is False
    assert src._is_retryable(_http_error(400)) is False
    # 非 HTTPError(超时/连接重置/JSON 坏)一律值得再试一次
    assert src._is_retryable(TimeoutError("timeout")) is True


def test_retry_exhausts_then_raises_last_error(monkeypatch):
    """重试次数用完后抛出最后一次的异常,由编排层记入 errors。"""
    monkeypatch.setattr(src, "BACKOFF_BASE", 0)
    calls: list[int] = []

    async def always_fail():
        calls.append(1)
        raise TimeoutError("upstream down")

    with pytest.raises(TimeoutError):
        _run(src._retry(always_fail, retries=2))
    assert len(calls) == 3          # 首次 + 2 次重试


def test_retry_stops_immediately_on_non_retryable(monkeypatch):
    """403/404 不重试:一次就抛,调用方少等 4.5 秒。"""
    monkeypatch.setattr(src, "BACKOFF_BASE", 0)
    calls: list[int] = []

    async def forbidden():
        calls.append(1)
        raise _http_error(403)

    with pytest.raises(urllib.error.HTTPError):
        _run(src._retry(forbidden, retries=2))
    assert len(calls) == 1


def test_retry_succeeds_after_one_transient_failure(monkeypatch):
    monkeypatch.setattr(src, "BACKOFF_BASE", 0)
    calls: list[int] = []

    async def flaky():
        calls.append(1)
        if len(calls) == 1:
            raise TimeoutError("first try timed out")
        return ["hit"]

    assert _run(src._retry(flaky, retries=2)) == ["hit"]
    assert len(calls) == 2


class _FakeResponse:
    """urllib 响应的最小替身:read/close/上下文管理三个动作都要被记录。"""

    def __init__(self, payload: bytes, *, fail_on_close: int = 0):
        self._payload = payload
        self._fail_on_close = fail_on_close   # 第 N 次 close 抛错(0 = 不抛)
        self.closed = 0

    def read(self, size: int = -1) -> bytes:
        return self._payload[:size]

    def close(self) -> None:
        self.closed += 1
        if self._fail_on_close and self.closed >= self._fail_on_close:
            raise OSError("connection already half-closed")

    def __enter__(self):
        return self

    def __exit__(self, *exc) -> None:
        self.close()


def test_http_get_returns_body_and_unregisters_inflight(monkeypatch):
    """正常路径:返回解码后的正文,在途登记必须清空(finally 不能漏)。"""
    resp = _FakeResponse(b"hello body")
    monkeypatch.setattr(src.urllib.request, "urlopen", lambda req, timeout: resp)

    token = object()
    src._cancel_flags[token] = threading.Event()
    ctx = src._cancel_token.set(token)
    try:
        assert src._http_get("https://example.org/x", 3.0) == "hello body"
        assert token not in src._inflight
        assert resp.closed >= 1        # with 块关闭 + finally 再关一次
    finally:
        src._cancel_token.reset(ctx)
        src._cancel_flags.pop(token, None)


def test_http_get_rejects_oversized_body(monkeypatch):
    """超限响应必须拒绝,不能把外部源的几 MB 数据塞进内存/日志。"""
    big = _FakeResponse(b"x" * (src.MAX_RESPONSE_BYTES + 1))
    monkeypatch.setattr(src.urllib.request, "urlopen", lambda req, timeout: big)
    with pytest.raises(ValueError):
        src._http_get("https://example.org/big", 3.0)


def test_http_get_aborts_when_cancelled_before_request(monkeypatch):
    """外层已取消:连请求都不发(省下线程与对方配额)。"""
    opened: list[str] = []
    monkeypatch.setattr(src.urllib.request, "urlopen",
                        lambda req, timeout: opened.append("x") or _FakeResponse(b""))
    token = object()
    flag = threading.Event()
    flag.set()
    src._cancel_flags[token] = flag
    ctx = src._cancel_token.set(token)
    try:
        with pytest.raises(RuntimeError):
            src._http_get("https://example.org/x", 3.0)
        assert opened == []
    finally:
        src._cancel_token.reset(ctx)
        src._cancel_flags.pop(token, None)


def test_http_get_aborts_when_cancelled_after_response_opened(monkeypatch):
    """响应已打开但已取消:关闭连接并抛错,别让线程白读完整个 body。"""
    token = object()
    flag = threading.Event()
    resp = _FakeResponse(b"payload")

    def opener(req, timeout):
        flag.set()          # 模拟"打开响应之后"才发生取消
        return resp

    monkeypatch.setattr(src.urllib.request, "urlopen", opener)
    src._cancel_flags[token] = flag
    ctx = src._cancel_token.set(token)
    try:
        with pytest.raises(RuntimeError):
            src._http_get("https://example.org/x", 3.0)
        assert resp.closed >= 1
        assert token not in src._inflight
    finally:
        src._cancel_token.reset(ctx)
        src._cancel_flags.pop(token, None)


def test_http_get_survives_close_on_half_open_connection(monkeypatch):
    """已半关闭的连接二次 close() 会抛:finally 里必须吞掉,否则一次正常请求变 500。"""
    resp = _FakeResponse(b"ok", fail_on_close=2)   # 第 1 次(with 块)正常,第 2 次抛
    monkeypatch.setattr(src.urllib.request, "urlopen", lambda req, timeout: resp)
    assert src._http_get("https://example.org/x", 3.0) == "ok"
    assert resp.closed == 2


def test_http_get_async_closes_inflight_response_from_event_loop(monkeypatch):
    """协程被取消时从事件循环线程关闭在途响应,唤醒阻塞中的 read()。

    线程池里的 read 不知情,不关闭就会一直占到超时。
    """
    closed: list[int] = []

    class Inflight:
        def close(self):
            closed.append(1)
            raise OSError("already closed")   # 重复关闭必须被吞掉

    def fake_get(url, timeout, headers=None):
        token = src._cancel_token.get()
        assert token is not None            # token 由 _http_get_async 注入
        with src._inflight_lock:
            src._inflight[token] = Inflight()
        return "body"

    monkeypatch.setattr(src, "_http_get", fake_get)
    assert _run(src._http_get_async("https://example.org/x", 3.0)) == "body"
    assert closed == [1]
    assert src._inflight == {}
    assert src._cancel_flags == {}


def test_http_get_async_is_cancellable_under_real_thread(monkeypatch):
    """_http_get_async 用线程执行同步 GET:返回值透传,token 不残留。

    盯住"取消机制不污染后续请求":contextvar 必须 reset、登记表必须清空。
    """
    monkeypatch.setattr(src.urllib.request, "urlopen",
                        lambda req, timeout: _FakeResponse("正文".encode()))
    assert _run(src._http_get_async("https://example.org/x", 3.0)) == "正文"
    assert src._cancel_token.get() is None
    assert src._cancel_flags == {}


# ---------------------------------------------------------------------------
# 五个源的字段归一化
# ---------------------------------------------------------------------------

ARXIV_XML = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <title>Spectral gaps in
      trapped ions</title>
    <summary>We study gaps.</summary>
    <author><name>A. Author</name></author>
    <author><name>B. Author</name></author>
    <published>2024-05-01T00:00:00Z</published>
    <id>https://arxiv.org/abs/2405.00001</id>
  </entry>
  <entry><summary>entry without a title must be dropped</summary></entry>
  <entry>
    <title>Bad year entry</title>
    <summary>year is not numeric</summary>
    <published>unknown-date</published>
  </entry>
</feed>"""


def test_search_arxiv_normalizes_entries_and_drops_titleless(monkeypatch):
    """标题折行要压平、作者逗号连接、年份取前 4 位;无标题条目丢弃。

    无标题条目进列表就是一行空白,用户点了也打不开。
    """
    monkeypatch.setattr(src, "_http_get_async", _fake_json(ARXIV_XML))
    hits = _run(src.search_arxiv('all:"spectral gaps"'))
    assert len(hits) == 2
    first = hits[0]
    assert first.source == "arXiv"
    # arXiv 的 title 会折行,只压掉换行不压多空格,所以按空白归一后比较
    assert " ".join(first.title.split()) == "Spectral gaps in trapped ions"
    assert first.authors == "A. Author, B. Author"
    assert first.year == 2024
    assert first.url == "https://arxiv.org/abs/2405.00001"
    assert first.snippet == "We study gaps."
    # 年份不是数字 → 0(不是异常,也不是 None)
    assert hits[1].year == 0
    assert hits[1].authors == ""


def test_search_semantic_scholar_normalizes_missing_fields(monkeypatch):
    """缺字段/类型错的返回值要归一成空串与 0,并跳过无标题行。

    Semantic Scholar 公共池的 year/citationCount 常为 null;
    直接 int(None) 会让整源报错,用户平白少一个来源。
    """
    payload = """{"data": [
      {"title": "Paper A", "abstract": null, "year": null,
       "authors": [{"name": "A. One"}, {"noname": 1}, {"name": "B. Two"}],
       "url": null, "citationCount": null},
      {"abstract": "no title row"},
      {"title": "Paper B", "year": 2021, "citationCount": 7,
       "authors": [], "url": "https://example.org/b"}
    ]}"""
    captured: dict = {}

    async def fake_get(url, timeout, headers=None):
        captured["headers"] = headers
        return payload

    monkeypatch.setattr(src, "_http_get_async", fake_get)
    monkeypatch.delenv("MG_S2_API_KEY", raising=False)
    hits = _run(src.search_semantic_scholar("spectral gaps"))
    assert [h.title for h in hits] == ["Paper A", "Paper B"]
    assert hits[0].source == "Semantic Scholar"
    assert hits[0].snippet == ""
    # 只过滤"不是 dict"的作者项;dict 缺 name 时留一个空位(现状如此,不在此断言里美化)
    assert hits[0].authors == "A. One, , B. Two"
    assert hits[0].year == 0 and hits[0].citations == 0 and hits[0].url == ""
    assert hits[1].year == 2021 and hits[1].citations == 7
    assert captured["headers"] is None       # 没配 key 就不带 x-api-key

    monkeypatch.setenv("MG_S2_API_KEY", "secret-key")
    _run(src.search_semantic_scholar("spectral gaps"))
    assert captured["headers"] == {"x-api-key": "secret-key"}


def test_search_openalex_rebuilds_abstract_and_prefixes_bare_doi(monkeypatch):
    """OpenAlex 倒排索引摘要要还原成句子,裸 DOI 要补 https://doi.org/。

    倒排索引直接透传等于给用户看 JSON;裸 DOI 进 url 字段,前端当链接会打不开。
    """
    payload = """{"results": [
      {"display_name": "Paper A",
       "abstract_inverted_index": {"Spectral": [0], "gaps": [1], "matter": [2]},
       "authorships": [{"author": {"display_name": "A. One"}}, "dirty", {"noauthor": 1}],
       "doi": "10.1234/abc", "publication_year": 2019, "cited_by_count": 42},
      {"display_name": "Paper B", "doi": "https://doi.org/10.1/b"},
      {"no_display_name": true}
    ]}"""
    seen: list[str] = []

    async def fake_get(url, timeout, headers=None):
        seen.append(url)
        return payload

    monkeypatch.setattr(src, "_http_get_async", fake_get)
    monkeypatch.delenv("MG_CONTACT_MAIL", raising=False)
    hits = _run(src.search_openalex("spectral gaps"))
    assert [h.title for h in hits] == ["Paper A", "Paper B"]
    assert hits[0].snippet == "Spectral gaps matter"
    assert hits[0].authors == "A. One"
    assert hits[0].url == "https://doi.org/10.1234/abc"
    assert hits[0].year == 2019 and hits[0].citations == 42
    assert hits[1].url == "https://doi.org/10.1/b"   # 已是完整 URL 不重复加前缀
    assert "mailto" not in seen[0]

    monkeypatch.setenv("MG_CONTACT_MAIL", "me@example.org")
    _run(src.search_openalex("spectral gaps"))
    assert "mailto=me%40example.org" in seen[1]


def test_search_zbmath_prefers_review_text_and_appends_msc(monkeypatch):
    """zbMATH:同行评论优先于作者摘要,再退到出处;MSC 分类附在末尾。

    评论是数学库唯一的独家信号,退化成"出处"就把最专业的那句话丢了。
    """
    payload = """{"result": [
      {"title": {"title": "Modular forms"},
       "contributors": {"authors": [{"name": "A. One"}, {"name": "B. Two"}, "dirty"]},
       "editorial_contributions": [
          {"contribution_type": "summary", "text": "author abstract"},
          {"contribution_type": "review", "text": "reviewer verdict"}
       ],
       "source": {"source": "Acta Math."},
       "msc": [{"code": "11F03", "text": "Modular forms"}],
       "year": 1998, "zbmath_url": "https://zbmath.org/1"},
      {"title": {"title": "zbMATH Open Web Interface contents unavailable"}},
      {"title": {"title": "Only source"},
       "contributors": "not-a-dict",
       "source": {"source": "Invent. Math."},
       "year": "unknown"},
      {"title": {"title": "No contributions"},
       "editorial_contributions": ["dirty"], "year": 2001}
    ]}"""
    monkeypatch.setattr(src, "_http_get_async", _fake_json(payload))
    hits = _run(src.search_zbmath("modular forms"))
    assert [h.title for h in hits] == ["Modular forms", "Only source", "No contributions"]
    assert hits[0].source == "zbMATH"
    assert hits[0].snippet == "reviewer verdict〔MSC 11F03:Modular forms〕"
    assert hits[0].authors == "A. One, B. Two"
    assert hits[0].year == 1998 and hits[0].url == "https://zbmath.org/1"
    # contributors 类型错 → authors 空;摘要退到出处
    assert hits[1].authors == "" and hits[1].snippet == "Invent. Math."
    assert hits[1].year == 0
    assert hits[2].snippet == "" and hits[2].year == 2001


def test_search_stackexchange_builds_quality_snippet(monkeypatch):
    """StackExchange:评分/回答数进摘要;坏 creation_date 退成 1970 而不是炸掉。"""
    payload = """{"items": [
      {"title": "How to prove convergence", "score": 12, "answer_count": 3,
       "is_answered": true, "creation_date": 1700000000,
       "link": "https://math.stackexchange.com/q/1"},
      {"title": "Bad timestamp", "creation_date": "yesterday"},
      {"score": 1}
    ]}"""
    monkeypatch.setattr(src, "_http_get_async", _fake_json(payload))
    hits = _run(src.search_stackexchange("convergence"))
    assert len(hits) == 2
    assert hits[0].source == "StackExchange"
    assert hits[0].snippet == "评分 12 · 回答 3 · 已解决 True"
    assert hits[0].year == 2023
    assert hits[0].url == "https://math.stackexchange.com/q/1"
    assert hits[1].year == 1970
    assert hits[1].authors == "" and hits[1].url == ""


# ---------------------------------------------------------------------------
# 聚合层:单源失败不影响其余 / 空结果
# ---------------------------------------------------------------------------

@pytest.fixture()
def fresh_research_cache():
    """编排层有 5 分钟结果缓存,不清会把上一条用例的结果带进来。"""
    from rag import research

    research._cache.clear()
    yield research
    research._cache.clear()


def test_one_source_failure_is_isolated_from_the_others(fresh_research_cache, monkeypatch):
    """arXiv 挂了(超时/限流)→ 只记进 errors,OpenAlex 的命中照常返回。

    这是多源检索最要紧的一条:一个源抖动就让整轮 0 结果,
    用户会以为"没人研究过这个问题"。
    """
    research = fresh_research_cache
    monkeypatch.setattr(research.llm, "is_configured", lambda *a, **k: False)
    monkeypatch.setattr(src, "BACKOFF_BASE", 0)   # 不真等指数退避

    async def flaky_get(url, timeout, headers=None):
        if "arxiv.org" in url:
            raise TimeoutError("arxiv timeout")
        return """{"results": [{"display_name": "Spectral gaps matter",
                   "doi": "10.1234/abc", "publication_year": 2019,
                   "cited_by_count": 5}]}"""

    monkeypatch.setattr(src, "_http_get_async", flaky_get)
    outcome = asyncio.run(research.deep_search(
        "spectral gaps in trapped ions", top_k=3, scope=["arXiv", "OpenAlex"]))
    assert outcome.errors == ["arXiv"]
    assert outcome.sources == {"OpenAlex": 1}
    assert [h.title for h in outcome.hits] == ["Spectral gaps matter"]
    assert outcome.hits[0].source == "OpenAlex"
    assert outcome.elapsed >= 0


def test_all_sources_failing_yields_empty_outcome_without_raising(
        fresh_research_cache, monkeypatch):
    """所有源都不可达:返回空结果 + 全量 errors,而不是抛异常。

    前端据此显示"这些来源暂时不可用";抛异常会变成 500 页面。
    """
    research = fresh_research_cache
    monkeypatch.setattr(research.llm, "is_configured", lambda *a, **k: False)
    monkeypatch.setattr(src, "BACKOFF_BASE", 0)

    async def dead_get(url, timeout, headers=None):
        raise OSError("network unreachable")

    monkeypatch.setattr(src, "_http_get_async", dead_get)
    outcome = asyncio.run(research.deep_search(
        "another unique question", top_k=3,
        scope=["arXiv", "OpenAlex", "zbMATH", "StackExchange"]))
    assert outcome.hits == []
    assert outcome.sources == {}
    # 顺序取决于并发完成先后,故只断言集合与条数
    assert sorted(outcome.errors) == ["OpenAlex", "StackExchange", "arXiv", "zbMATH"]


def test_sources_returning_no_rows_are_counted_as_zero(fresh_research_cache, monkeypatch):
    """源可达但 0 命中:计数为 0、不进 errors(与"源挂了"必须区分)。"""
    research = fresh_research_cache
    monkeypatch.setattr(research.llm, "is_configured", lambda *a, **k: False)

    async def empty_get(url, timeout, headers=None):
        return '{"items": [{"score": 1}]}'   # 无标题 → 0 条

    monkeypatch.setattr(src, "_http_get_async", empty_get)
    outcome = asyncio.run(research.deep_search(
        "yet another question", top_k=3, scope=["StackExchange"]))
    assert outcome.sources == {"StackExchange": 0}
    assert outcome.errors == []
    assert outcome.hits == []




