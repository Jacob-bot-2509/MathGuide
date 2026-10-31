"""论文窗口动作规划:检索词落页、批注增改删校验。"""
from __future__ import annotations

import asyncio
import json

import research_actions as ra


def _hit(text: str = "The reader keeps annotations and restores the last page.",
         page: int = 2) -> dict:
    return {"pageStart": page, "pageEnd": page, "text": text,
            "snippet": text[:80]}


def _stub_corpus(monkeypatch, annotations=None, hits=None):
    monkeypatch.setattr(ra.rc, "get_live_doc", lambda uid, doc: {"id": doc, "pages": 10})
    monkeypatch.setattr(ra.rc, "list_doc_annotations", lambda uid, doc: annotations or [])
    monkeypatch.setattr(ra.rc, "find_passages",
                        lambda uid, doc, q, top_k=3: hits if hits is not None else [_hit()])


def test_quote_around_prefers_single_sentence():
    text = ("Opening context sentence. The optimal temperature was 37 C with "
            "activity 2.4 times baseline. A third sentence should not be included.")
    quote = ra._quote_around(text, "optimal temperature", 180)
    assert "optimal temperature" in quote
    assert len(quote) <= 180
    assert "third sentence" not in quote


def test_plan_actions_resolves_local_pages_and_annotations(monkeypatch):
    monkeypatch.setattr(ra.llm, "is_configured", lambda role="main": True)

    async def fake_stream(system, user, **kwargs):
        yield json.dumps({
            "searches": ["reading progress"],
            "annotate": [{
                "query": "reader keeps annotations",
                "note": "论文重点:批注与页码恢复",
                "color": "cyan",
            }],
            "update": [{"annotationId": "a1", "note": "更新后的批注", "color": "green"}],
            "delete": ["a1", "not-mine"],
        })

    monkeypatch.setattr(ra.llm, "stream_chat", fake_stream)
    _stub_corpus(monkeypatch, annotations=[{
        "id": "a1", "page": 1, "quote": "old", "note": "old note", "color": "yellow",
    }])

    actions = asyncio.run(ra.plan_actions(
        "u", "d1", "批注一下并高亮，同时修改并删除旧批注", excerpts=[]))
    kinds = [a["type"] for a in actions]
    assert kinds.count("updateAnnotation") == 1
    assert kinds.count("deleteAnnotation") == 1
    assert all(a.get("id") == "a1" for a in actions if a["type"].endswith("Annotation"))
    annotate = next(a for a in actions if a["type"] == "annotate")
    assert annotate["page"] == 2
    assert "reader keeps annotations" in annotate["quote"]
    assert annotate["color"] == "cyan"
    update = next(a for a in actions if a["type"] == "updateAnnotation")
    assert update["note"] == "更新后的批注"
    highlights = [a for a in actions if a["type"] == "highlight"]
    assert highlights and highlights[0]["page"] == 2


def test_plan_actions_requires_explicit_write_intent(monkeypatch):
    """用户没说要批注/修改/删除时,模型不能自行写入或删除。"""
    monkeypatch.setattr(ra.llm, "is_configured", lambda role="main": True)

    async def fake_stream(system, user, **kwargs):
        yield json.dumps({
            "searches": ["reading progress"],
            "annotate": [{"query": "reader keeps annotations", "note": "x"}],
            "update": [{"annotationId": "a1", "note": "x"}],
            "delete": ["a1"],
        })

    monkeypatch.setattr(ra.llm, "stream_chat", fake_stream)
    _stub_corpus(monkeypatch, annotations=[{"id": "a1", "page": 1}])

    actions = asyncio.run(ra.plan_actions(
        "u", "d1", "这一段讲了什么", excerpts=[]))
    assert [a["type"] for a in actions] == ["highlight"]


def test_plan_actions_rejects_out_of_range_page(monkeypatch):
    monkeypatch.setattr(ra.llm, "is_configured", lambda role="main", **k: False)
    _stub_corpus(monkeypatch, hits=[_hit(page=99)])

    actions = asyncio.run(ra.plan_actions(
        "u", "d1", "结论在哪一页", excerpts=[]))
    assert actions == []


def test_plan_actions_falls_back_to_local_location(monkeypatch):
    monkeypatch.setattr(ra.llm, "is_configured", lambda role="main": False)
    _stub_corpus(monkeypatch, hits=[
        _hit("Structure is generated once and cached by content hash.", 3)])

    actions = asyncio.run(ra.plan_actions(
        "u", "d1", "结论在哪一页", excerpts=[]))
    assert actions == [{
        "type": "highlight",
        "page": 3,
        "quote": "Structure is generated once and cached by content hash.",
        "query": "结论在哪一页",
    }]


def test_plan_actions_ignores_bad_json(monkeypatch):
    monkeypatch.setattr(ra.llm, "is_configured", lambda role="main": True)

    async def fake_stream(system, user, **kwargs):
        yield "不是 JSON"

    monkeypatch.setattr(ra.llm, "stream_chat", fake_stream)
    _stub_corpus(monkeypatch)

    actions = asyncio.run(ra.plan_actions("u", "d1", "这一段", excerpts=[]))
    assert [a["type"] for a in actions] == ["highlight"]
