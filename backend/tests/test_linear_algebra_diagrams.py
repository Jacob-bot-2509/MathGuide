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


def test_orthogonal_projection_keeps_residual():
    diagram = _build({
        "visual": "inner_product", "operation": "projection",
        "domain": "real", "ambient": 3,
        "vector": [1, 2, 3],
        "subspace": {
            "dimension": 2, "kind": "linear", "offset": [0, 0, 0],
            "basis": [[1, 0, 0], [0, 1, 0]],
        },
    })
    assert diagram is not None
    vectors = [shape for shape in diagram["shapes"] if shape["kind"] == "vector"]
    assert len(vectors) >= 3
    assert any(shape.get("label") == "proj_S v" for shape in vectors)


def test_orthogonal_complement_in_three_dimensions():
    diagram = _build({
        "visual": "inner_product", "operation": "orthogonal_complement",
        "domain": "real", "ambient": 3,
        "subspace": {
            "dimension": 2, "kind": "linear", "offset": [0, 0, 0],
            "basis": [[1, 0, 0], [0, 1, 0]],
        },
    })
    assert diagram is not None
    labels = " ".join(str(shape.get("label", "")) for shape in diagram["shapes"])
    assert "S" in labels and "S⊥" in labels


def test_gram_schmidt_builds_orthogonal_vectors():
    diagram = _build({
        "visual": "inner_product", "operation": "gram_schmidt",
        "domain": "real", "ambient": 2,
        "vectors": [[1, 1], [1, 0]],
    })
    assert diagram is not None
    assert len([shape for shape in diagram["shapes"]
                if shape["kind"] == "vector"]) == 2


def test_quadratic_form_ellipse_and_signature():
    diagram = _build({
        "visual": "quadratic_form", "domain": "real", "ambient": 2,
        "matrix": [[1, 0], [0, 4]], "level": 1,
    })
    assert diagram is not None
    assert any(shape["kind"] == "curve" for shape in diagram["shapes"])
    assert any("signature = (2, 0, 0)" in note["text"]
               for note in diagram["annotations"])


def test_quadratic_form_three_dimensional_surface():
    diagram = _build({
        "visual": "quadratic_form", "domain": "real", "ambient": 3,
        "matrix": [[1, 0, 0], [0, 1, 0], [0, 0, 1]], "level": 1,
    })
    assert diagram is not None
    surface = next(shape for shape in diagram["shapes"]
                   if shape["kind"] == "surface")
    assert surface["rows"] == 31 and surface["cols"] == 31
    assert len(surface["points"]) == 31 * 31


def test_quadratic_form_rejects_asymmetric_matrix():
    assert _build({
        "visual": "quadratic_form", "domain": "real", "ambient": 2,
        "matrix": [[1, 2], [0, 1]], "level": 1,
    }) is None


def test_bilinear_forms_symmetric_and_alternating():
    symmetric = _build({
        "visual": "bilinear_form", "domain": "real", "ambient": 2,
        "matrix": [[1, 0], [0, 2]],
    })
    assert symmetric is not None
    assert any(shape["kind"] == "curve" for shape in symmetric["shapes"])

    alternating = _build({
        "visual": "bilinear_form", "domain": "real", "ambient": 2,
        "matrix": [[0, 1], [-1, 0]],
    })
    assert alternating is not None
    assert any(shape["kind"] == "polygon" for shape in alternating["shapes"])


def test_prepare_quadratic_surface_keeps_linear_metadata():
    raw = {
        "type": "geometry3d",
        "linear": {
            "visual": "quadratic_form", "domain": "real", "ambient": 3,
            "matrix": [[1, 0, 0], [0, 1, 0], [0, 0, 1]], "level": 1,
        },
        "nodes": [], "edges": [], "shapes": [], "annotations": [],
    }
    diagram = rd.prepare_diagram(raw)
    assert diagram is not None
    assert diagram["linear"]["visual"] == "quadratic_form"
    assert any(shape["kind"] == "surface" for shape in diagram["shapes"])


def test_unitary_complex_plane_keeps_circle_and_vectors():
    diagram = _build({
        "visual": "unitary", "domain": "complex", "ambient": 1,
        "matrix": [[[0, 1]]],
        "vector": [[1, 0]],
    })
    assert diagram is not None
    assert diagram["type"] == "plot2d"
    assert any(shape["kind"] == "curve" for shape in diagram["shapes"])
    assert any(shape.get("label") == "Uz" for shape in diagram["shapes"])
    assert diagram["linear"]["projection"]["kind"] == "complex_to_real"


def test_unitary_c2_projection_is_labelled():
    diagram = _build({
        "visual": "unitary", "domain": "complex", "ambient": 2,
        "matrix": [
            [[1, 0], [0, 0]],
            [[0, 0], [1, 0]],
        ],
        "vector": [[1, 0], [0, 0]],
        "projection": {"kind": "r4_to_3d", "note": "C² 实四维投影到 R³"},
    })
    assert diagram is not None
    assert diagram["type"] == "geometry3d"
    assert diagram["linear"]["projection"]["kind"] == "r4_to_3d"
    assert any(note["text"] == "C² 实四维投影到 R³"
               for note in diagram["annotations"])


def test_unitary_rejects_non_unitary_matrix():
    assert _build({
        "visual": "unitary", "domain": "complex", "ambient": 1,
        "matrix": [[[2, 0]]],
        "vector": [[1, 0]],
    }) is None


def test_symplectic_plane_area_and_isotropic_lines():
    diagram = _build({
        "visual": "symplectic", "domain": "real", "ambient": 2,
        "matrix": [[0, 1], [-1, 0]],
    })
    assert diagram is not None
    assert diagram["type"] == "plot2d"
    assert any(shape["kind"] == "polygon" for shape in diagram["shapes"])
    assert any("各向同性" in str(shape.get("label", ""))
               for shape in diagram["shapes"])


def test_symplectic_r4_projection_is_labelled():
    matrix = [
        [0, 0, 1, 0],
        [0, 0, 0, 1],
        [-1, 0, 0, 0],
        [0, -1, 0, 0],
    ]
    diagram = _build({
        "visual": "symplectic", "domain": "real", "ambient": 4,
        "matrix": matrix,
        "projection": {"kind": "r4_to_3d", "note": "R⁴ 辛基投影到 R³"},
    })
    assert diagram is not None
    assert diagram["type"] == "geometry3d"
    assert diagram["linear"]["projection"]["kind"] == "r4_to_3d"
    assert any("R⁴ 辛基投影" in note["text"]
               for note in diagram["annotations"])


def test_taxonomy_prefers_symplectic_geometry():
    from diagram_taxonomy import choose_visual
    assert choose_visual("解释 R^4 中的辛空间与辛变换").kind == "geometry3d"


def test_affine_transform_builds_source_and_image():
    diagram = _build({
        "visual": "affine", "operation": "transform",
        "domain": "real", "ambient": 2,
        "matrix": [[1, 1], [0, 1]], "translation": [1, 2],
    })
    assert diagram is not None
    assert len([shape for shape in diagram["shapes"]
                if shape["kind"] == "polygon"]) == 2


def test_affine_subspace_keeps_offset():
    diagram = _build({
        "visual": "affine", "operation": "subspace",
        "domain": "real", "ambient": 2,
        "subspace": {
            "dimension": 1, "kind": "affine", "offset": [1, 2],
            "basis": [[1, 0]],
        },
    })
    assert diagram is not None
    assert any(shape.get("label") == "b" for shape in diagram["shapes"])


def test_projective_line_at_infinity():
    diagram = _build({
        "visual": "projective", "operation": "line_at_infinity",
        "domain": "real", "ambient": 2,
    })
    assert diagram is not None
    assert any(shape.get("label") == "无穷远线" for shape in diagram["shapes"])
    assert any(shape.get("label") == "∞" for shape in diagram["shapes"])


def test_projective_transform_and_cross_ratio():
    transform = _build({
        "visual": "projective", "operation": "transform",
        "domain": "real", "ambient": 2,
        "matrix": [[1, 0, 0], [0, 1, 0], [0, 0, 1]],
    })
    assert transform is not None
    assert len([shape for shape in transform["shapes"]
                if shape["kind"] == "polygon"]) == 2

    ratio = _build({
        "visual": "projective", "operation": "cross_ratio",
        "domain": "real", "ambient": 2,
        "points": [[0, 0], [1, 0], [2, 0], [3, 0]],
    })
    assert ratio is not None
    assert any("交比" in note["text"] for note in ratio["annotations"])


def test_svd_ellipse_axes_and_condition():
    diagram = _build({
        "visual": "svd", "domain": "real", "ambient": 2,
        "operation": "condition", "matrix": [[2, 0], [0, 0.5]],
    })
    assert diagram is not None
    curves = [shape for shape in diagram["shapes"] if shape["kind"] == "curve"]
    assert len(curves) == 2
    assert any("cond" in note["text"] for note in diagram["annotations"])
    assert any(shape.get("label") == "σ1" for shape in diagram["shapes"])


def test_svd_three_dimensional_surface():
    diagram = _build({
        "visual": "svd", "domain": "real", "ambient": 3,
        "matrix": [[2, 0, 0], [0, 1, 0], [0, 0, 0.5]],
    })
    assert diagram is not None
    assert any(shape["kind"] == "surface" for shape in diagram["shapes"])


def test_taxonomy_prefers_svd_and_affine():
    from diagram_taxonomy import choose_visual
    assert choose_visual("用图解释 SVD 奇异值分解").kind in ("geometry2d", "geometry3d")
    assert choose_visual("用图解释仿射变换").kind in ("geometry2d", "geometry3d")


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
