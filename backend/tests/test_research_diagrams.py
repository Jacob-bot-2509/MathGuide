"""图解标记流:跨 chunk 剥离、锚点、schema 白名单。"""
from __future__ import annotations

from research_diagrams import MarkerStream, diagram_event, validate_diagram


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
