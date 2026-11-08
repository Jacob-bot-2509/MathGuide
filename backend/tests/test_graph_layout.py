"""graph_layout:NetworkX 分层布局的确定性、分层正确性与间距。"""
from __future__ import annotations

from knowledge_graph import KnowledgeGraph, KnowledgePoint, load_graph
from graph_layout import layout_points


def _graph() -> KnowledgeGraph:
    points = {}
    for pid, prereqs in [
        ("a", ()), ("b", ("a",)), ("c", ("a",)), ("d", ("b", "c")), ("e", ("b",)),
    ]:
        points[pid] = KnowledgePoint(pid, f"点{pid}", "章", 2, prereqs)
    return KnowledgeGraph(points)


def test_levels_follow_longest_path():
    layout = layout_points(_graph())
    assert layout["a"]["level"] == 0
    assert layout["b"]["level"] == 1
    assert layout["c"]["level"] == 1
    assert layout["d"]["level"] == 2
    assert layout["e"]["level"] == 2


def test_prerequisites_are_left_of_dependents():
    layout = layout_points(_graph())
    assert layout["a"]["x"] < layout["b"]["x"] < layout["d"]["x"]
    assert layout["a"]["x"] < layout["c"]["x"] < layout["d"]["x"]


def test_layout_is_deterministic():
    graph = _graph()
    assert layout_points(graph) == layout_points(graph)


def test_nodes_in_same_level_do_not_overlap():
    layout = layout_points(_graph())
    ys = sorted(layout[pid]["y"] for pid in ("b", "c"))
    assert ys[0] != ys[1]
    assert abs(ys[1] - ys[0]) >= 50


def test_real_knowledge_graph_layout():
    layout = layout_points(load_graph())
    assert len(layout) == 80
    # 前置必须严格在左侧
    graph = load_graph()
    for point in graph.points.values():
        for prereq in point.prerequisites:
            assert layout[prereq]["x"] < layout[point.id]["x"], point.id


def test_isolated_node_still_has_position():
    graph = KnowledgeGraph({"solo": KnowledgePoint("solo", "孤立", "章", 1, ())})
    layout = layout_points(graph)
    assert layout["solo"]["level"] == 0
    assert isinstance(layout["solo"]["x"], int)
