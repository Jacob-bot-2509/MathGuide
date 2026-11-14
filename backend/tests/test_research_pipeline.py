"""深度搜索编排(rag/research/__init__):查询改写、多源并发、范围过滤、缓存与精排。

这个文件补的是"编排层"——它坏了的表现不是报错,而是**静默返回空/漏源/串结果**,
所以断言集中在:哪些源被调用、失败源是否只记名不中断、缓存键是否含范围、
LLM 改写失败是否回退规则版、精排是否只在有外源结果时发生。
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

import rag.research as research
from rag.research.types import KB_SOURCE, SearchHit


@pytest.fixture(autouse=True)
def _clean_state(monkeypatch):
    """deep_search 写模块级缓存,不还原会串到下一条用例(同题命中上一条的假结果)。"""
    research._cache.clear()
    monkeypatch.setattr(research.llm, "is_configured", lambda role="main": False)
    # 排序规则由 test_research.py 单独覆盖;这里关心编排,原样透传便于断言命中集合
    monkeypatch.setattr(research.rank, "rank", lambda hits, terms, question, top_k=3: hits)
    yield
    research._cache.clear()


def _hit(source: str, title: str) -> SearchHit:
    return SearchHit(source=source, title=title, snippet=title, year=2024)


def _patch_sources(monkeypatch, table: dict[str, object]) -> list[str]:
    """把注册表里的源换成假实现,并记录调用顺序。"""
    calls: list[str] = []

    def make(name: str, result, record: bool):
        async def fake(query):
            if record:
                calls.append(name)
            if isinstance(result, Exception):
                raise result
            return list(result)  # type: ignore[arg-type]

        return fake

    for name in research.SOURCE_FNS:
        monkeypatch.setitem(research.SOURCE_FNS, name,
                            make(name, table.get(name, []), name in table))
    return calls


def _patch_kb(monkeypatch, chunks: list[str]) -> list[str]:
    calls: list[str] = []

    def fake_kb(question, k):
        calls.append(question)
        return [(SimpleNamespace(title=c, text=c), 1.0) for c in chunks]

    monkeypatch.setattr(research, "kb_search", fake_kb)
    return calls


def test_cache_key_includes_scope_and_normalizes_question():
    # 同一问题换了平台必须重新检索,否则用户勾选会被静默忽略
    assert research._cache_key("  泰勒展开  ", 3, None) == "3|all|泰勒展开"
    assert research._cache_key("q", 2, ["zbMATH", "arXiv"]) == "2|arXiv,zbMATH|q"
    assert research._cache_key("q", 2, []) == "2|all|q"


def test_deep_search_merges_sources_and_counts_each(monkeypatch):
    _patch_sources(monkeypatch, {
        "arXiv": [_hit("arXiv", "taylor expansion")],
        "zbMATH": [_hit("zbMATH", "taylor series remainder")],
    })
    _patch_kb(monkeypatch, ["泰勒展开的定义"])

    out = asyncio.run(research.deep_search("泰勒展开", top_k=5))

    assert out.question == "泰勒展开"
    assert out.terms == ["taylor expansion"]
    assert out.sources[KB_SOURCE] == 1
    assert out.sources["arXiv"] == 1
    assert out.sources["zbMATH"] == 1
    assert out.sources["StackExchange"] == 0   # 没命中也要如实记 0,前端才画得出空源
    assert {h.source for h in out.hits} == {KB_SOURCE, "arXiv", "zbMATH"}
    assert out.errors == []
    assert out.elapsed >= 0


def test_single_source_failure_is_recorded_not_fatal(monkeypatch):
    """单源超时/挂掉只记名,不能让整轮深度搜索失败——这是它和普通检索的关键差别。"""
    _patch_sources(monkeypatch, {
        "arXiv": RuntimeError("boom"),
        "Semantic Scholar": [_hit("Semantic Scholar", "taylor expansion")],
    })
    _patch_kb(monkeypatch, [])

    out = asyncio.run(research.deep_search("taylor expansion", top_k=5))

    assert out.errors == ["arXiv"]
    assert {h.source for h in out.hits} == {"Semantic Scholar"}
    assert out.sources[KB_SOURCE] == 0


def test_scope_limits_which_sources_are_called(monkeypatch):
    calls = _patch_sources(monkeypatch, {"zbMATH": [_hit("zbMATH", "taylor expansion")]})
    kb_calls = _patch_kb(monkeypatch, ["不应被调用"])

    out = asyncio.run(research.deep_search("taylor expansion", scope=["zbMATH"]))

    assert calls == ["zbMATH"]          # 未勾选的源一个请求都不发
    assert kb_calls == []               # 未勾选知识库也不查
    assert KB_SOURCE not in out.sources
    assert [h.source for h in out.hits] == ["zbMATH"]


def test_all_invalid_scope_falls_back_to_everything(monkeypatch):
    """前端传来全是脏名字时要退回全平台,而不是给用户一个空结果。"""
    calls = _patch_sources(monkeypatch, {"arXiv": [_hit("arXiv", "taylor expansion")]})
    kb_calls = _patch_kb(monkeypatch, ["知识库命中"])

    out = asyncio.run(research.deep_search("taylor expansion", scope=["bogus", "NotASource"]))

    assert "arXiv" in calls
    assert kb_calls == ["taylor expansion"]
    assert KB_SOURCE in out.sources

def test_cache_hit_returns_same_outcome_without_touching_sources(monkeypatch):
    calls = _patch_sources(monkeypatch, {"arXiv": [_hit("arXiv", "taylor expansion")]})
    _patch_kb(monkeypatch, [])

    first = asyncio.run(research.deep_search("taylor expansion"))
    second = asyncio.run(research.deep_search("taylor expansion"))

    assert calls == ["arXiv"]           # 第二次直接命中缓存
    assert second is first


def test_cache_key_separates_different_scope(monkeypatch):
    calls = _patch_sources(monkeypatch, {
        "arXiv": [_hit("arXiv", "taylor expansion")],
        "zbMATH": [_hit("zbMATH", "taylor expansion")],
    })
    _patch_kb(monkeypatch, [])

    asyncio.run(research.deep_search("taylor expansion", scope=["arXiv"]))
    asyncio.run(research.deep_search("taylor expansion", scope=["zbMATH"]))

    assert calls == ["arXiv", "zbMATH"]


def test_expired_cache_entry_is_refetched(monkeypatch):
    calls = _patch_sources(monkeypatch, {"arXiv": [_hit("arXiv", "taylor expansion")]})
    _patch_kb(monkeypatch, [])

    asyncio.run(research.deep_search("taylor expansion"))
    key = research._cache_key("taylor expansion", 3, None)
    stamp, outcome = research._cache[key]
    research._cache[key] = (stamp - research._CACHE_TTL - 1, outcome)

    asyncio.run(research.deep_search("taylor expansion"))

    assert calls == ["arXiv", "arXiv"]  # 过期必须重新检索


def test_cache_evicts_oldest_entry_when_over_capacity(monkeypatch):
    _patch_sources(monkeypatch, {"arXiv": [_hit("arXiv", "taylor expansion")]})
    _patch_kb(monkeypatch, [])
    monkeypatch.setattr(research, "_CACHE_MAX", 2)

    asyncio.run(research.deep_search("question one"))
    asyncio.run(research.deep_search("question two"))
    asyncio.run(research.deep_search("question three"))

    assert len(research._cache) == 2
    assert research._cache_key("question one", 3, None) not in research._cache
def test_llm_rewritten_terms_take_precedence(monkeypatch):
    _patch_sources(monkeypatch, {})
    _patch_kb(monkeypatch, [])
    monkeypatch.setattr(research.llm, "is_configured", lambda role="main": True)

    async def fake_expand(question, timeout=6.0):
        return ["taylor series", "remainder"]

    monkeypatch.setattr(research, "_llm_expand_terms", fake_expand)

    out = asyncio.run(research.deep_search("泰勒展开的余项怎么估"))

    assert out.terms == ["taylor series", "remainder"]


def test_rule_terms_used_when_llm_returns_none(monkeypatch):
    _patch_sources(monkeypatch, {})
    _patch_kb(monkeypatch, [])
    monkeypatch.setattr(research.llm, "is_configured", lambda role="main": True)

    async def no_terms(question, timeout=6.0):
        return None

    monkeypatch.setattr(research, "_llm_expand_terms", no_terms)

    out = asyncio.run(research.deep_search("泰勒展开"))

    assert out.terms == research.expand_query("泰勒展开") == ["taylor expansion"]


def test_llm_expand_parses_delimiters_and_caps_length(monkeypatch):
    pieces = ["taylor series, limits、", "integral\nconvergence; derivative ",
              "riemann hypothesis, topology, eigenvalue, matrix, residue"]

    async def fake_stream(system, question, role="main", fallback=True):
        for p in pieces:
            yield p

    monkeypatch.setattr(research.llm, "stream_chat", fake_stream)

    terms = asyncio.run(research._llm_expand_terms("什么样的研究问题"))

    assert terms[0] == "taylor series"
    assert "limits" in terms and "integral" in terms
    assert len(terms) <= research.MAX_TERMS
    assert all(2 <= len(t) <= 60 for t in terms)


def test_llm_expand_drops_too_short_and_too_long_terms(monkeypatch):
    async def fake_stream(system, question, role="main", fallback=True):
        yield "a, " + "x" * 61 + ", good term"

    monkeypatch.setattr(research.llm, "stream_chat", fake_stream)

    assert asyncio.run(research._llm_expand_terms("q")) == ["good term"]


def test_llm_expand_stops_collecting_after_200_chars(monkeypatch):
    """模型不收口时会一直吐;必须在 200 字处截断,否则一个提问能把预算吃光。"""
    fed: list[str] = []

    async def fake_stream(system, question, role="main", fallback=True):
        for i in range(50):
            fed.append(str(i))
            yield f"term number {i}, "

    monkeypatch.setattr(research.llm, "stream_chat", fake_stream)

    asyncio.run(research._llm_expand_terms("q"))

    assert len(fed) < 50
def test_rerank_only_runs_when_external_hits_present(monkeypatch):
    """纯知识库命中不需要精排(浪费一次模型调用),有外源命中才值得。"""
    _patch_sources(monkeypatch, {"arXiv": [_hit("arXiv", "taylor expansion")]})
    _patch_kb(monkeypatch, ["泰勒展开"])
    monkeypatch.setattr(research.llm, "is_configured", lambda role="main": True)
    calls: list[int] = []

    async def fake_rerank(question, hits, timeout=10.0):
        calls.append(len(hits))
        return hits

    monkeypatch.setattr(research.rerank, "rerank", fake_rerank)

    asyncio.run(research.deep_search("taylor expansion", scope=["arXiv"]))

    assert calls == [1]


def test_rerank_skipped_for_kb_only_results(monkeypatch):
    _patch_sources(monkeypatch, {})
    _patch_kb(monkeypatch, ["泰勒展开"])
    monkeypatch.setattr(research.llm, "is_configured", lambda role="main": True)
    calls: list[int] = []

    async def fake_rerank(question, hits, timeout=10.0):
        calls.append(len(hits))
        return hits

    monkeypatch.setattr(research.rerank, "rerank", fake_rerank)

    asyncio.run(research.deep_search("泰勒展开", scope=[KB_SOURCE]))

    assert calls == []


def test_kb_snippet_is_truncated_to_400_chars(monkeypatch):
    """知识库片段直接进引用区,超长会撑爆前端卡片。"""
    _patch_sources(monkeypatch, {})
    monkeypatch.setattr(research, "kb_search",
                        lambda q, k: [(SimpleNamespace(title="t", text="x" * 900), 1.0)])

    out = asyncio.run(research.deep_search("q", scope=[KB_SOURCE]))

    assert len(out.hits) == 1
    assert len(out.hits[0].snippet) == 400



def test_llm_expand_returns_none_on_model_failure(monkeypatch):
    async def boom(system, question, role="main", fallback=True):
        raise RuntimeError("upstream 429")
        yield ""

    monkeypatch.setattr(research.llm, "stream_chat", boom)

    assert asyncio.run(research._llm_expand_terms("q")) is None

