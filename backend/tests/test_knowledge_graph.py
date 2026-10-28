"""knowledge_graph:CSV 加载、图校验与拓扑排序。"""
from __future__ import annotations

from pathlib import Path

import pytest

from knowledge_graph import KnowledgeGraphError, load_graph

HEADER = "id,name,chapter,difficulty,prerequisites\n"


def _write(tmp_path: Path, rows: str, *, encoding: str = "utf-8",
           header: str = HEADER) -> Path:
    path = tmp_path / "points.csv"
    path.write_text(header + rows, encoding=encoding)
    return path


def test_loads_points_with_semicolon_prerequisites(tmp_path):
    path = _write(
        tmp_path,
        "a,集合与映射,函数与极限,1,\n"
        "b,初等函数,函数与极限,2,a\n"
        "c,数列极限,函数与极限,3,a;b\n",
    )
    graph = load_graph(path)

    assert list(graph.points) == ["a", "b", "c"]
    assert graph.points["c"].name == "数列极限"
    assert graph.points["c"].chapter == "函数与极限"
    assert graph.points["c"].difficulty == 3
    assert graph.points["c"].prerequisites == ("a", "b")
    assert graph.points["a"].prerequisites == ()


def test_accepts_utf8_bom(tmp_path):
    path = _write(
        tmp_path,
        "a,集合与映射,函数与极限,1,\n",
        encoding="utf-8-sig",
    )
    assert load_graph(path).points["a"].name == "集合与映射"


def test_rejects_duplicate_id(tmp_path):
    path = _write(
        tmp_path,
        "a,集合与映射,函数与极限,1,\n"
        "a,初等函数,函数与极限,2,\n",
    )
    with pytest.raises(KnowledgeGraphError, match="重复"):
        load_graph(path)


def test_rejects_missing_prerequisite(tmp_path):
    path = _write(
        tmp_path,
        "a,集合与映射,函数与极限,1,ghost\n",
    )
    with pytest.raises(KnowledgeGraphError, match="不存在"):
        load_graph(path)


def test_rejects_self_dependency(tmp_path):
    path = _write(
        tmp_path,
        "a,集合与映射,函数与极限,1,a\n",
    )
    with pytest.raises(KnowledgeGraphError, match="自身"):
        load_graph(path)


@pytest.mark.parametrize("difficulty", ["0", "6", "x", ""])
def test_rejects_invalid_difficulty(tmp_path, difficulty):
    path = _write(
        tmp_path,
        f"a,集合与映射,函数与极限,{difficulty},\n",
    )
    with pytest.raises(KnowledgeGraphError, match="难度"):
        load_graph(path)


def test_rejects_missing_column(tmp_path):
    path = _write(
        tmp_path,
        "a,集合与映射,函数与极限,1,\n",
        header="id,name,chapter,difficulty\n",
    )
    with pytest.raises(KnowledgeGraphError, match="缺少列"):
        load_graph(path)


def test_rejects_empty_dataset(tmp_path):
    path = _write(tmp_path, "")
    with pytest.raises(KnowledgeGraphError, match="没有知识点"):
        load_graph(path)


def test_rejects_cycle(tmp_path):
    path = _write(
        tmp_path,
        "a,集合与映射,函数与极限,1,b\n"
        "b,初等函数,函数与极限,2,a\n",
    )
    with pytest.raises(KnowledgeGraphError, match="循环"):
        load_graph(path)


def test_topological_order_puts_prerequisites_first(tmp_path):
    path = _write(
        tmp_path,
        "a,集合与映射,函数与极限,1,\n"
        "b,初等函数,函数与极限,2,a\n"
        "c,数列极限,函数与极限,3,a\n"
        "d,函数极限,函数与极限,3,b;c\n",
    )
    order = load_graph(path).topological_order()

    assert sorted(order) == ["a", "b", "c", "d"]
    assert order.index("a") < order.index("b") < order.index("d")
    assert order.index("a") < order.index("c") < order.index("d")


def test_descendant_count_and_direct_dependents(tmp_path):
    path = _write(
        tmp_path,
        "a,集合与映射,函数与极限,1,\n"
        "b,初等函数,函数与极限,2,a\n"
        "c,数列极限,函数与极限,3,a\n"
        "d,函数极限,函数与极限,3,b;c\n",
    )
    graph = load_graph(path)

    assert graph.direct_dependents("a") == ("b", "c")
    assert graph.direct_dependents("d") == ()
    assert graph.descendant_count("a") == 3  # b, c, d
    assert graph.descendant_count("b") == 1  # d
    assert graph.descendant_count("d") == 0


def test_bundled_dataset_is_valid_and_has_about_80_points():
    """项目自带的《高等数学》上册知识图谱:结构完整且无环。"""
    path = (Path(__file__).resolve().parent.parent
            / "knowledge_graph" / "data" / "knowledge_points.csv")
    graph = load_graph(path)

    assert 75 <= len(graph.points) <= 90
    order = graph.topological_order()
    position = {pid: i for i, pid in enumerate(order)}
    for point in graph.points.values():
        for prereq in point.prerequisites:
            assert position[prereq] < position[point.id]
