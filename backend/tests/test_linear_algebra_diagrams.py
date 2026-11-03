"""Phase 1: 高等代数几何表示层。"""

from __future__ import annotations

import asyncio

import linear_algebra as la
import research_diagrams as rd


def _subspace(ambient=3, dimension=2, kind="linear", offset=None, basis=None):
    if offset is None:
        offset = [0.0] * ambient
    if basis is None:
        basis = [[1.0 if i == j else 0.0 for j in range(ambient)]
                 for i in range(dimension)]
    return {
        "visual": "subspace",
        "domain": "real",
        "ambient": ambient,
        "title": "测试子空间",
        "subspace": {
            "dimension": dimension,
            "kind": kind,
            "offset": offset,
            "basis": basis,
        },
    }


def _build(raw):
    return la.build_linear_diagram({"type": "geometry3d", "linear": raw})


def test_subspace_dimensions_build_geometry():
    expected = {0: "point", 1: "segment", 2: "plane", 3: "vector"}
    for dimension in range(4):
        diagram = _build(_subspace(3, dimension))
        assert diagram is not None
        assert diagram["type"] == "geometry3d"
        kinds = {shape["kind"] for shape in diagram["shapes"]}
        assert expected[dimension] in kinds


def test_affine_subspace_keeps_origin_offset():
    diagram = _build(_subspace(
        3, 2, kind="affine", offset=[1, 2, 3],
        basis=[[1, 0, 0], [0, 1, 0]],
    ))
    assert diagram is not None
    points = [shape for shape in diagram["shapes"] if shape["kind"] == "point"]
    assert any(abs(shape["x"] - 1) < 1e-9
               and abs(shape["y"] - 2) < 1e-9
               and abs(shape["z"] - 3) < 1e-9 for shape in points)
    assert diagram["linear"]["subspace"]["kind"] == "affine"


def test_linear_subspace_rejects_nonzero_offset():
    assert _build(_subspace(
        3, 2, kind="linear", offset=[1, 0, 0],
    )) is None


def test_subspace_rejects_bad_dimension_and_dependent_basis():
    assert _build(_subspace(3, 4)) is None
    assert _build({
        "visual": "subspace", "domain": "real", "ambient": 3,
        "subspace": {
            "dimension": 2, "kind": "linear",
            "offset": [0, 0, 0],
            "basis": [[1, 0, 0], [2, 0, 0]],
        },
    }) is None


def test_linear_map_builds_kernel_and_image():
    diagram = _build({
        "visual": "linear_map", "domain": "real", "ambient": 2,
        "matrix": [[1, 0], [0, 0]],
    })
    assert diagram is not None
    labels = " ".join(str(shape.get("label", "")) for shape in diagram["shapes"])
    assert "ker T" in labels
    assert "Im T" in labels
    assert any("rank" in note["text"] for note in diagram["annotations"])


def test_determinant_builds_parallelogram_and_volume():
    area = _build({
        "visual": "determinant", "domain": "real", "ambient": 2,
        "vectors": [[2, 0], [0, 3]],
    })
    assert area is not None
    assert any(shape["kind"] == "polygon" for shape in area["shapes"])
    assert any("det = 6" in note["text"] for note in area["annotations"])

    volume = _build({
        "visual": "determinant", "domain": "real", "ambient": 3,
        "vectors": [[1, 0, 0], [0, 1, 0], [0, 0, 1]],
    })
    assert volume is not None
    assert len([shape for shape in volume["shapes"]
                if shape["kind"] == "segment"]) >= 12


def test_eigen_symmetric_builds_real_axes():
    diagram = _build({
        "visual": "eigen", "domain": "real", "ambient": 2,
        "matrix": [[2, 1], [1, 2]],
    })
    assert diagram is not None
    assert any(shape["kind"] == "vector" for shape in diagram["shapes"])
    assert any("λ" in note["text"] for note in diagram["annotations"])


def test_system_unique_solution():
    diagram = _build({
        "visual": "system", "domain": "real", "ambient": 2,
        "equations": [[1, 1, 3], [1, -1, 1]],
    })
    assert diagram is not None
    assert any(shape["kind"] == "point" for shape in diagram["shapes"])


def test_prepare_diagram_preserves_linear_metadata():
    raw = {
        "type": "geometry3d",
        "title": "R^3 的坐标平面",
        "linear": _subspace(3, 2),
        "nodes": [], "edges": [], "shapes": [], "annotations": [],
    }
    diagram = rd.prepare_diagram(raw)
    assert diagram is not None
    assert diagram["type"] == "geometry3d"
    assert diagram["linear"]["subspace"]["dimension"] == 2
    assert any(shape["kind"] == "plane" for shape in diagram["shapes"])


def test_prepare_two_dimensional_subspace():
    raw = {
        "type": "plot2d",
        "linear": _subspace(2, 2),
        "nodes": [], "edges": [], "shapes": [], "annotations": [],
    }
    diagram = rd.prepare_diagram(raw)
    assert diagram is not None
    assert diagram["type"] == "plot2d"
    assert any(shape["kind"] == "vector" for shape in diagram["shapes"])


def test_three_dimensional_plane_intersection():
    diagram = _build({
        "visual": "system", "domain": "real", "ambient": 3,
        "equations": [[1, 0, 0, 0], [0, 1, 0, 0]],
    })
    assert diagram is not None
    assert any(shape.get("label") == "交线" for shape in diagram["shapes"])


def test_taxonomy_prefers_three_dimensional_linear_algebra():
    from diagram_taxonomy import choose_visual
    assert choose_visual("解释 R^3 中由两个向量张成的子空间").kind == "geometry3d"


def test_looks_linear_and_plan_linear(monkeypatch):
    assert la.looks_linear("解释 R^3 中由 e1,e2 张成的子空间")
    assert not la.looks_linear("y=x^2 的切线")

    async def fake_stream(system, user, role="main", **kwargs):
        yield (
            '{"visual":"subspace","domain":"real","ambient":3,'
            '"subspace":{"dimension":2,"kind":"linear","offset":[0,0,0],'
            '"basis":[[1,0,0],[0,1,0]],"label":"span(e1,e2)"}}'
        )

    monkeypatch.setattr(la.llm, "is_configured", lambda role="main", **k: True)
    monkeypatch.setattr(la.llm, "stream_chat", fake_stream)
    diagram = asyncio.run(la.plan_linear("R^3 的二维子空间", "解释"))
    assert diagram is not None
    assert diagram["linear"]["subspace"]["dimension"] == 2


def test_plan_diagram_auto_prefers_linear(monkeypatch):
    sentinel = {"type": "geometry3d", "shapes": [{"kind": "point", "x": 0, "y": 0, "z": 0}]}

    async def fake_linear(question, before, role="main"):
        return sentinel

    async def legacy(*args, **kwargs):
        raise AssertionError("linear route should win")

    monkeypatch.setattr(la, "looks_linear", lambda question: True)
    monkeypatch.setattr(la, "plan_linear", fake_linear)
    monkeypatch.setattr(rd, "plan_diagram", legacy)
    got = asyncio.run(rd.plan_diagram_auto(
        "R^3 的子空间图解", "解释", [], "", strict=False))
    assert got is sentinel
