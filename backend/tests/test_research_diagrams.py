"""图解标记流:跨 chunk 剥离、锚点、schema 白名单。"""
from __future__ import annotations

import asyncio
import json

import research_diagrams as rd
from research_diagrams import (
    MarkerStream,
    diagram_event,
    plan_diagram,
    validate_diagram,
)


def _marker(kind: str = "relation") -> str:
    return f"[[MG_DIAGRAM:{kind}]]"


def test_marker_split_across_chunks():
    stream = MarkerStream("r1")
    assert stream.feed("前[[MG_DIA") == "前"
    assert stream.feed("GRAM:relation]]后") == "后"
    markers = stream.drain()
    assert len(markers) == 1
    assert markers[0].kind == "relation"
    assert markers[0].anchor_index == 1


def test_multiple_markers_have_stable_ids():
    stream = MarkerStream("r2")
    assert stream.feed("A" + _marker("flow") + "B" + _marker("tree")) == "AB"
    markers = stream.drain()
    assert [m.kind for m in markers] == ["flow", "tree"]
    assert [m.anchor_id for m in markers] == ["r2-1", "r2-2"]


def test_incomplete_marker_is_stripped_at_finish():
    stream = MarkerStream("r3")
    assert stream.feed("可见[[MG_DIAGRAM:relation") == "可见"
    assert stream.finish() == ""
    assert stream.drain() == []


def test_validate_relation_and_limits():
    spec = validate_diagram({
        "type": "relation",
        "nodes": [{"id": "a", "label": "A"}, {"id": "b", "label": "B"}],
        "edges": [{"from": "a", "to": "b", "label": "推出"}],
    })
    assert spec and spec["type"] == "relation" and len(spec["nodes"]) == 2

    assert validate_diagram({"type": "script"}) is None
    assert validate_diagram({
        "type": "relation",
        "nodes": [{"id": str(i), "label": "x"} for i in range(41)],
    }) is None
    assert validate_diagram({
        "type": "geometry2d",
        "shapes": [{"kind": "<script>", "x": 1, "y": 2}],
    }) is None


def test_diagram_event_frame():
    spec = validate_diagram({
        "type": "flow",
        "nodes": [{"id": "a", "label": "A"}],
    })
    frame = diagram_event(spec, "r4", "r4-1", 3)
    assert frame.startswith("data: ")
    assert '"mg_event": "diagram"' in frame
    assert '"anchorIndex": 3' in frame


def test_plan_diagram_uses_answer_context(monkeypatch):
    seen: dict[str, str] = {}
    monkeypatch.setattr(rd.llm, "is_configured", lambda role="main": True)

    async def fake_stream(system, user, **kwargs):
        seen["system"] = system
        seen["user"] = user
        yield "```json\n" + json.dumps({
            "type": "relation",
            "nodes": [{"id": "a", "label": "A"}, {"id": "b", "label": "B"}],
            "edges": [{"from": "a", "to": "b"}],
        }) + "\n```"

    monkeypatch.setattr(rd.llm, "stream_chat", fake_stream)
    result = asyncio.run(plan_diagram(
        "为什么 A 推出 B", "前面解释 A", [{"section": "S", "text": "资料"}],
        "relation"))
    assert result and result["type"] == "relation"
    assert "为什么 A 推出 B" in seen["user"]
    assert "前面解释 A" in seen["user"]
    assert "资料" in seen["user"]


def test_plan_diagram_rejects_bad_model_output(monkeypatch):
    monkeypatch.setattr(rd.llm, "is_configured", lambda role="main": True)

    async def bad(system, user, **kwargs):
        yield "不是 JSON"

    monkeypatch.setattr(rd.llm, "stream_chat", bad)
    assert asyncio.run(plan_diagram("q", "a", [], "flow")) is None


def test_plan_diagram_without_llm(monkeypatch):
    monkeypatch.setattr(rd.llm, "is_configured", lambda role="main": False)
    assert asyncio.run(plan_diagram("q", "a", [], "tree")) is None


def test_plan_endpoint_returns_diagram(monkeypatch):
    from starlette.applications import Starlette
    from starlette.routing import Route
    from starlette.testclient import TestClient

    monkeypatch.setattr(rd, "require_auth", lambda request: {"uid": "u-dia"})
    monkeypatch.setattr(rd, "_diagram_limiter", rd.SlidingWindowLimiter(20, 60))

    async def fake_plan(question, before, excerpts, kind, role="main"):
        return {"type": "flow", "nodes": [{"id": "a", "label": "A"}],
                "edges": [], "shapes": [], "annotations": []}

    monkeypatch.setattr(rd, "plan_diagram", fake_plan)
    app = Starlette(routes=[Route("/api/research/diagrams/plan",
                                  rd.plan_endpoint, methods=["POST"])])
    client = TestClient(app)
    res = client.post("/api/research/diagrams/plan",
                      json={"question": "怎么理解", "answer": "解释"})
    assert res.status_code == 200, res.text
    assert res.json()["diagram"]["type"] == "flow"


def test_plan_endpoint_requires_question(monkeypatch):
    from starlette.applications import Starlette
    from starlette.routing import Route
    from starlette.testclient import TestClient

    monkeypatch.setattr(rd, "require_auth", lambda request: {"uid": "u-dia"})
    monkeypatch.setattr(rd, "_diagram_limiter", rd.SlidingWindowLimiter(20, 60))
    app = Starlette(routes=[Route("/api/research/diagrams/plan",
                                  rd.plan_endpoint, methods=["POST"])])
    client = TestClient(app)
    res = client.post("/api/research/diagrams/plan", json={"answer": "解释"})
    assert res.status_code == 400
