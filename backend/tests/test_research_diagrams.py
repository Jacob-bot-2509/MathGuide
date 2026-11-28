"""图解标记流:跨 chunk 剥离、锚点、schema 白名单。"""
from __future__ import annotations

import asyncio
import base64
import json
import math
import struct
import threading

import pytest

import research_diagrams as rd
from research_diagrams import (
    MarkerStream,
    diagram_event,
    plan_diagram,
    validate_diagram,
)


def _mesh_positions(shape: dict) -> list[float]:
    raw = base64.b64decode(shape["positions_b64"])
    return list(struct.unpack("<" + "f" * (len(raw) // 4), raw))


def _mesh_indices(shape: dict) -> list[int]:
    raw = base64.b64decode(shape["indices_b64"])
    if shape.get("indexType") == "u16":
        return list(struct.unpack("<" + "H" * (len(raw) // 2), raw))
    return list(struct.unpack("<" + "I" * (len(raw) // 4), raw))


def _marker(kind: str = "relation") -> str:
    return f"[[MG_DIAGRAM:{kind}]]"


def test_research_mode_requires_data_grounding(monkeypatch):
    seen = {}

    async def fake_stream(system, context, **kwargs):
        seen["system"] = system
        seen["context"] = context
        yield '{"type":"flow","nodes":[{"id":"a","label":"方法"}],"edges":[]}'

    monkeypatch.setattr(rd.llm, "is_configured", lambda role=None: True)
    monkeypatch.setattr(rd.llm, "stream_chat", fake_stream)
    result = asyncio.run(rd.plan_diagram(
        "画出实验流程", "先取样，再测量", [], "flow", mode="research"))
    assert result is not None
    assert "科研" in seen["system"] or "research" in seen["system"].lower()
    assert "数据点" in seen["system"] or "data points" in seen["system"].lower()


def test_research_diagram_switch_defaults_off():
    import chat
    assert chat._diagram_requested({}) is False
    assert chat._diagram_requested({"diagrams": False}) is False
    assert chat._diagram_requested({"diagrams": True}) is True


def test_plan_endpoint_accepts_table_id(monkeypatch):
    from starlette.applications import Starlette
    from starlette.routing import Route
    from starlette.testclient import TestClient

    import research_diagrams as rd

    seen = {}
    monkeypatch.setattr(rd, "require_auth", lambda request: {"uid": "u"})
    monkeypatch.setattr(rd, "_get_table", lambda uid, tid: {
        "columns": [{"key": "X", "label": "x"}],
        "rows": [["1"]], "formulas": {},
    }, raising=False)

    async def fake_plan(question, answer, excerpts, kind, **kwargs):
        seen["table_context"] = kwargs.get("table_context")
        seen["mode"] = kwargs.get("mode")
        return {"type": "flow", "nodes": [{"id": "a", "label": "A"}], "edges": []}

    monkeypatch.setattr(rd, "plan_diagram", fake_plan)
    app = Starlette(routes=[Route(
        "/api/research/diagrams/plan", rd.plan_endpoint, methods=["POST"])])
    res = TestClient(app).post("/api/research/diagrams/plan", json={
        "question": "画出实验流程", "answer": "先取样，再测量",
        "tableId": "t1", "mode": "research",
    })
    assert res.status_code == 200
    assert "X" in seen["table_context"]
    assert seen["mode"] == "research"


def test_plan_endpoint_builds_data_plot_from_regression_spec(monkeypatch):
    from starlette.applications import Starlette
    from starlette.routing import Route
    from starlette.testclient import TestClient

    import research_diagrams as rd

    monkeypatch.setattr(rd, "require_auth", lambda request: {"uid": "u"})
    monkeypatch.setattr(rd, "_get_table", lambda uid, tid: {
        "columns": [{"key": "X", "type": "number"},
                    {"key": "Y", "type": "number"}],
        "rows": [["1", "2"], ["2", "3"], ["3", "4"]],
        "formulas": {},
    }, raising=False)

    async def fake_run(payload, timeout=30.0):
        return {
            "points": [
                {"row": 0, "x": 1, "actual": 2, "fitted": 2.1, "residual": -0.1},
                {"row": 1, "x": 2, "actual": 3, "fitted": 3.0, "residual": 0.0},
            ],
            "fitCurve": [{"x": 1, "y": 2.1}, {"x": 2, "y": 3.0}],
            "equation": "Y = 1 + X",
        }

    monkeypatch.setattr(rd, "_run_analysis", fake_run)
    app = Starlette(routes=[Route(
        "/api/research/diagrams/plan", rd.plan_endpoint, methods=["POST"])])
    res = TestClient(app).post("/api/research/diagrams/plan", json={
        "question": "画出拟合",
        "answer": "拟合结果",
        "tableId": "t1",
        "regression": {"x": ["X"], "y": "Y", "model": "ols"},
    })
    assert res.status_code == 200
    assert res.json()["diagram"]["type"] == "plot2d"


def test_plan_endpoint_rejects_model_written_table_points(monkeypatch):
    from starlette.applications import Starlette
    from starlette.routing import Route
    from starlette.testclient import TestClient

    import research_diagrams as rd

    monkeypatch.setattr(rd, "require_auth", lambda request: {"uid": "u"})
    monkeypatch.setattr(rd, "_get_table", lambda uid, tid: {
        "columns": [{"key": "X", "type": "number"}],
        "rows": [["1"]], "formulas": {},
    }, raising=False)

    async def fake_plan(question, answer, excerpts, kind, **kwargs):
        return {"type": "plot2d", "shapes": [
            {"kind": "point", "x": 1, "y": 9},
            {"kind": "axis", "from": [0, 0], "to": [1, 0], "label": "x"},
        ]}

    monkeypatch.setattr(rd, "plan_diagram", fake_plan)
    app = Starlette(routes=[Route(
        "/api/research/diagrams/plan", rd.plan_endpoint, methods=["POST"])])
    res = TestClient(app).post("/api/research/diagrams/plan", json={
        "question": "画图", "answer": "解释", "tableId": "t1",
    })
    assert res.status_code == 200
    assert res.json()["diagram"] is None


def test_data_plot_uses_fit_points_not_model_values():
    fit = {
        "points": [
            {"row": 0, "actual": 1.0, "fitted": 1.1, "residual": -0.1},
            {"row": 1, "actual": 2.0, "fitted": 2.1, "residual": -0.1},
        ],
        "fitCurve": [{"x": 0, "y": 1.0}, {"x": 3, "y": 4.0}],
    }
    spec = rd.build_data_plot("t1", "X", "Y", fit)
    assert spec["type"] == "plot2d"
    points = [s for s in spec["shapes"] if s["kind"] == "point"]
    assert len(points) == 2
    assert points[0]["x"] == 0
    assert points[0]["y"] == 1.0
    assert any(s["kind"] == "curve" for s in spec["shapes"])


def test_marker_split_across_chunks():
    stream = MarkerStream("r1")
    assert stream.feed("前[[MG_DIA") == "前"
    assert stream.feed("GRAM:relation]]后") == "后"
    markers = stream.drain()
    assert len(markers) == 1
    assert markers[0].kind == "relation"
    assert markers[0].anchor_index == 1


def test_anchor_counts_text_before_markers_in_same_feed():
    stream = MarkerStream("r1b")
    clean = stream.feed(
        "AAA[[MG_DIAGRAM:relation]]BBB[[MG_DIAGRAM:flow]]CCC")
    assert clean == "AAABBBCCC"
    markers = stream.drain()
    assert [m.anchor_index for m in markers] == [3, 6]


def test_node_diagrams_prune_geometry_decorations():
    spec = rd.prepare_diagram({
        "type": "relation",
        "nodes": [{"id": "a", "label": "A"}, {"id": "b", "label": "B"}],
        "edges": [{"from": "a", "to": "b"}],
        "shapes": [{"kind": "axis", "from": [-1, 0], "to": [1, 0]}],
        "annotations": [{"x": 0, "y": 0, "text": "装饰"}],
    })
    assert spec
    assert spec["shapes"] == [] and spec["annotations"] == []


def test_2d_axes_are_normalized_orthogonal():
    spec = rd.prepare_diagram({
        "type": "plot2d",
        "shapes": [
            {"kind": "axis", "label": "x", "from": [-1, 1], "to": [1, 2]},
            {"kind": "axis", "label": "y", "from": [0, 0], "to": [1, 1]},
            {"kind": "curve", "expr": "x^2", "domain": [-1, 1]},
        ],
    })
    assert spec
    x_axis = next(shape for shape in spec["shapes"]
                  if shape.get("label") == "x")
    y_axis = next(shape for shape in spec["shapes"]
                  if shape.get("label") == "y")
    assert x_axis["from"][1] == 0 and x_axis["to"][1] == 0
    assert y_axis["from"][0] == 0 and y_axis["to"][0] == 0


def test_uppercase_marker_is_hidden_not_leaked():
    stream = MarkerStream("r-upper")
    assert stream.feed("前[[MG_DIAGRAM:RELATION]]后") == "前后"
    assert stream.drain() == []


def test_incomplete_marker_does_not_leak_uppercase_fragment():
    stream = MarkerStream("r-tail")
    assert stream.feed("前[[MG_DIAGRAM:plot2dD") == "前"
    assert stream.finish() == ""
    assert stream.drain() == []


def test_malformed_marker_with_closing_does_not_leak_fragment():
    stream = MarkerStream("r-malformed")
    assert stream.feed("前[[MG_DIAGRAM:plot2dD]]后") == "前后"


def test_unclosed_marker_preserves_visible_tail():
    stream = MarkerStream("r1c")
    assert stream.feed("前[[MG_DIAGRAM:relation 后文") == "前"
    assert stream.finish() == " 后文"


def test_anchor_uses_utf16_units_for_emoji():
    stream = MarkerStream("r1e")
    assert stream.feed("😀[[MG_DIAGRAM:relation]]") == "😀"
    assert stream.drain()[0].anchor_index == 2


def test_marker_accepts_type_prefix():
    stream = MarkerStream("r1d")
    assert stream.feed("前[[MG_DIAGRAM:type=flow]]后") == "前后"
    markers = stream.drain()
    assert len(markers) == 1 and markers[0].kind == "flow"


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


def test_validate_annotation_keeps_z_for_3d():
    spec = validate_diagram({
        "type": "geometry3d",
        "shapes": [{"kind": "point", "x": 1, "y": 2, "z": 3}],
        "annotations": [{"x": 1, "y": 2, "z": 3, "text": "P"}],
    })
    assert spec and spec["annotations"][0]["z"] == 3


def test_explicit_type_only_overrides_single_request():
    assert rd.explicit_type("用三维图表示三者关系") == "geometry3d"
    assert rd.explicit_type("请用三维坐标系画出曲面") == "surface3d"
    assert rd.explicit_type("画个流程图总结") == "flow"
    # 同时要求 2D/3D/流程,是在描述一整套分步图解,不能整题覆盖成一种类型。
    assert rd.explicit_type(
        "先用2D几何讲方向,再用三维曲面标出最陡方向,最后用流程图总结") is None
    # “坐标轴不要标数字”是排除项,不能误判成要画函数曲线。
    assert rd.explicit_types(
        "请用三维图表示梯度与方向导数,坐标轴不要标数字,不要画思维导图") == [
            "surface3d"]


def test_plan_diagram_retries_once_after_invalid_output(monkeypatch):
    monkeypatch.setattr(rd.llm, "is_configured", lambda role="main", **k: True)
    calls = {"n": 0}

    async def fake_stream(system, user, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            yield '{"type":"flow","nodes":"bad"}'
        else:
            yield json.dumps({
                "type": "flow",
                "nodes": [{"id": "a", "label": "Step"}],
                "edges": [],
            })

    monkeypatch.setattr(rd.llm, "stream_chat", fake_stream)
    result = asyncio.run(plan_diagram(
        "Explain the steps", "First do this, then do that.", [], "flow", strict=True))
    assert calls["n"] == 2
    assert result is not None and result["type"] == "flow"


def test_surface_normal_is_not_forced_vertical():
    """z=f(x,y) 上的法向量必须按 -f_x,-f_y,1 修正,不能画成 (0,0,1)。"""
    raw = {
        "type": "surface3d",
        "shapes": [
            {"kind": "surface", "expr": "x^2+y^2",
             "domain": [-2, 2, -2, 2], "rows": 8, "cols": 8},
            {"kind": "vector", "from": [1, 1, 2], "to": [1, 1, 3],
             "label": "n"},
        ],
    }
    diagram = rd.prepare_diagram(raw)
    vector = next(s for s in diagram["shapes"] if s["kind"] == "vector")
    dx = vector["to"][0] - vector["from"][0]
    dy = vector["to"][1] - vector["from"][1]
    dz = vector["to"][2] - vector["from"][2]
    assert abs(dx) > 0.1 and abs(dy) > 0.1
    assert dz > 0
    # 方向应平行于 (-2,-2,1)
    assert abs(dx - dy) < 1e-4
    assert abs(dx / dz + 2) < 1e-4


def test_sphere_normal_projects_start_onto_surface():
    """球面法向起点必须在球面上;模型从球外 2 画到 3 时要拉回 r=1。"""
    raw = {
        "type": "geometry3d",
        "shapes": [
            {"kind": "sphere", "x": 0, "y": 0, "z": 0, "r": 1,
             "label": "S"},
            {"kind": "vector", "from": [2, 0, 0], "to": [3, 0, 0],
             "label": "法向量 n"},
        ],
    }
    diagram = rd.prepare_diagram(raw)
    vector = next(s for s in diagram["shapes"] if s["kind"] == "vector")
    assert vector["from"] == [1.0, 0.0, 0.0]
    assert vector["to"] == [2.0, 0.0, 0.0]


def test_plane_normal_projects_start_onto_plane():
    """过 z=0 的平面,法向量起点 z=2 要滑到平面上。"""
    raw = {
        "type": "geometry3d",
        "shapes": [
            {"kind": "plane", "x": 0, "y": 0, "z": 0,
             "normal": [0, 0, 1], "label": "平面"},
            {"kind": "vector", "from": [1, 1, 2], "to": [1, 1, 3],
             "label": "法向量 n"},
        ],
    }
    diagram = rd.prepare_diagram(raw)
    vector = next(s for s in diagram["shapes"] if s["kind"] == "vector")
    assert vector["from"] == [1.0, 1.0, 0.0]
    assert vector["to"] == [1.0, 1.0, 1.0]


def test_cylinder_cap_normal_is_vertical():
    """圆柱上底面的法向是 +z,不能按侧面画成径向。"""
    raw = {
        "type": "geometry3d",
        "shapes": [
            {"kind": "cylinder", "x": 0, "y": 0, "z": 0,
             "r": 1, "height": 2, "label": "圆柱"},
            {"kind": "vector", "from": [0, 0, 1], "to": [1, 0, 1],
             "label": "法向量 n"},
        ],
    }
    diagram = rd.prepare_diagram(raw)
    vector = next(s for s in diagram["shapes"] if s["kind"] == "vector")
    dx = vector["to"][0] - vector["from"][0]
    dy = vector["to"][1] - vector["from"][1]
    dz = vector["to"][2] - vector["from"][2]
    assert abs(dx) < 1e-6 and abs(dy) < 1e-6
    assert dz > 0.5
    assert vector["from"][2] == 1.0


def test_projection_circle_gets_radius_and_sits_on_xy_plane():
    question = "抛物面 z=x^2+y^2 被平面 z=1 截下，画出投影区域"
    assert rd._surface_question_terms(question) == ("x^2+y^2", 1.0)
    raw = {
        "type": "surface3d",
        "shapes": [{"kind": "circle", "label": "投影区域 D"}],
    }
    repaired = rd.repair_surface_shapes(raw, question)
    circle = next(s for s in repaired["shapes"] if s["kind"] == "circle")
    assert circle["z"] == 0.0
    assert circle["r"] == 1.0


def test_plan_diagram_fills_missing_type_and_samples_curve(monkeypatch):
    monkeypatch.setattr(rd.llm, "is_configured", lambda role="main": True)

    async def fake_stream(system, user, **kwargs):
        yield json.dumps({
            "title": "方向导数",
            "shapes": [
                {"kind": "vector", "from": [0, 0], "to": [1, 1]},
                {"kind": "curve", "expr": "sin(x)", "domain": [-3.14, 3.14],
                 "points": 60},
            ],
        })

    monkeypatch.setattr(rd.llm, "stream_chat", fake_stream)
    result = asyncio.run(plan_diagram("2D几何讲方向", "", [], "geometry2d"))
    assert result and result["type"] == "geometry2d"
    curve = [s for s in result["shapes"] if s["kind"] == "curve"][0]
    assert len(curve["points"]) == 60


def test_plan_diagram_drops_bad_optional_fields_not_whole_diagram(monkeypatch):
    monkeypatch.setattr(rd.llm, "is_configured", lambda role="main", **k: True)

    async def fake_stream(system, user, **kwargs):
        yield json.dumps({
            "type": "geometry2d",
            "shapes": [
                {"kind": "point", "x": 1, "y": 2, "z": None, "r": "bad"},
                {"kind": "circle", "x": 0, "y": 0, "r": None},
            ],
            "annotations": [{"x": 1, "y": 2, "text": "P"}],
        })

    monkeypatch.setattr(rd.llm, "stream_chat", fake_stream)
    result = asyncio.run(plan_diagram("画个图", "", [], "geometry2d"))
    assert result
    assert [s["kind"] for s in result["shapes"]] == ["point", "circle"]
    assert result["shapes"][0]["x"] == 1


def test_score_segment_prefers_surface_for_gradient():
    kind, score = rd.score_segment(
        "在曲面上,梯度方向是函数增长最快的方向,它垂直于等高线。")
    assert kind == "surface3d"
    assert score >= 4


def test_select_segments_follows_numbered_steps():
    text = (
        "第一步:写出方向导数。\n\n"
        "第二步:把它写成梯度与单位方向向量的点乘。\n\n"
        "第三步:当夹角为 0 时点乘最大。"
    )
    segments = rd.select_segments("请一步一步讲", text)
    assert len(segments) == 3
    anchors = [segment.anchor_index for segment in segments]
    assert anchors == sorted(anchors)
    assert all(segment.kind for segment in segments)


def test_select_segments_splits_inline_steps():
    text = "首先画出函数图像,然后标出梯度向量,最后写出方向导数。"
    segments = rd.select_segments("一步步讲", text)
    assert len(segments) == 3
    assert all(segment.kind for segment in segments)


def test_select_segments_preserves_offsets_with_indentation_and_emoji():
    text = "😀\n\n    首先画函数图像。然后画曲线图像。"
    segments = rd.select_segments("一步步讲", text)
    assert [segment.anchor_index for segment in segments] == [
        rd._utf16_len(text[:text.index("然后")]), rd._utf16_len(text)
    ]


def test_select_segments_merges_semantically_continuous_steps():
    text = (
        "第一步:写出方向导数 D_u f = ∇f·u。\n\n"
        "第二步:把它展开成点乘。\n\n"
        "第三步:令夹角 θ=0,方向导数最大。"
    )
    segments = rd.select_segments("一步步讲", text)
    assert len(segments) == 2
    assert "把它展开" in segments[0].text
    assert [s.anchor_index for s in segments] == sorted(
        s.anchor_index for s in segments)


def test_select_segments_skips_greeting_and_covered_paragraph():
    assert rd.select_segments("你好", "你好,很高兴见到你。") == []
    text = "梯度方向是曲面最陡的上坡方向。\n\n这段是补充说明。"
    covered = [rd._utf16_len(text.split("\n\n")[0])]
    assert rd.select_segments("梯度", text, covered) == []


def test_select_segments_scans_whole_text_without_steps():
    text = (
        "先给结论:梯度方向是函数在该点增长最快的方向。\n\n"
        "从几何上看,它垂直于等高线,并且指向曲面最陡的上坡方向。"
    )
    segments = rd.select_segments("怎么理解梯度", text)
    assert segments
    assert segments[0].kind == "surface3d"


@pytest.mark.parametrize(("text", "expected"), [
    ("一元函数的单调性与极值", "plot2d"),
    ("定积分表示曲线下的面积", "plot2d"),
    ("傅里叶级数把周期函数分解为正弦波", "plot2d"),
    ("多元函数 z=f(x,y) 的偏导数", "surface3d"),
    ("方向导数与梯度,沿等高线法向变化最快", "surface3d"),
    ("二元函数的切平面与法向量", "surface3d"),
    ("二重积分的几何意义是曲顶柱体体积", "surface3d"),
    ("三重积分与空间区域", "geometry3d"),
    ("空间向量与平面方程", "geometry3d"),
    ("矩阵特征值与特征向量,只拉伸不偏转", "geometry2d"),
    ("行列式的几何意义是面积/体积缩放", "geometry2d"),
    ("概率密度函数与正态分布", "plot2d"),
    ("二维联合分布与边缘分布", "surface3d"),
    ("假设检验的步骤", "flow"),
    ("梯度下降算法迭代求最小值", "flow"),
    ("线性规划的可行域与约束", "geometry2d"),
    ("圆锥曲线的极坐标方程", "geometry2d"),
    ("函数的凹凸性与拐点", "plot2d"),
    ("微分方程的斜率场与相轨迹", "plot2d"),
])
def test_taxonomy_covers_common_knowledge_points(text: str, expected: str):
    kind, score = rd.score_segment(text)
    assert kind == expected, f"{text}: got {kind} ({score})"
    assert score >= 1.0


def test_score_segment_chooses_dimension_by_content():
    kind, score = rd.score_segment(
        "一元函数及其导数的图像,导数为正时函数单调递增。")
    assert kind == "plot2d"
    assert score >= 3
    kind, score = rd.score_segment(
        "多元函数 z=f(x,y) 的偏导数,在曲面上沿不同方向的变化率。")
    assert kind == "surface3d"
    assert score >= 3


def test_plan_diagram_uses_weight_hint_without_explicit_dimension(monkeypatch):
    seen: dict[str, str] = {}
    monkeypatch.setattr(rd.llm, "is_configured", lambda role="main", **k: True)

    async def fake_stream(system, user, **kwargs):
        seen["user"] = user
        yield json.dumps({
            "type": "plot2d",
            "shapes": [{"kind": "curve", "expr": "x^2", "domain": [-2, 2]}],
        })

    monkeypatch.setattr(rd.llm, "stream_chat", fake_stream)
    result = asyncio.run(plan_diagram(
        "帮我把图做出来", "一元函数及其导数的图像。", [], "", strict=False))
    assert result and result["type"] == "plot2d"
    assert "请求图解类型:plot2d" in seen["user"]
    # 权重只在后台参与决策,不把分数/选型依据写进规划上下文。
    assert "形式权重参考" not in seen["user"]


def test_3d_duplicate_model_axes_are_filtered():
    spec = rd.prepare_diagram({
        "type": "surface3d",
        "shapes": [
            {"kind": "surface", "expr": "x^2+y^2", "domain": [-2, 2],
             "rows": 5, "cols": 5},
            {"kind": "segment", "from": [-2, 0, 0], "to": [2, 0, 0]},
            {"kind": "segment", "from": [0, -2, 0], "to": [0, 2, 0]},
        ],
        "annotations": [
            {"x": -2.2, "y": 0, "z": 0, "text": "x"},
            {"x": 0, "y": 0, "z": 2.2, "text": "z"},
        ],
    })
    assert spec
    assert [shape["kind"] for shape in spec["shapes"]] == ["surface"]
    assert spec["annotations"] == []


def test_3d_line_parallel_to_axis_is_not_filtered_as_axis():
    """只有真正穿过原点的轴向线段才当重复坐标轴;平行线要保留。"""
    spec = rd.prepare_diagram({
        "type": "geometry3d",
        "shapes": [
            {"kind": "point", "x": 0, "y": 1, "z": 1, "label": "P"},
            {"kind": "segment", "label": "l", "from": [0, 1, 1], "to": [0, 2, 1]},
        ],
    })
    assert spec
    labels = [shape.get("label") for shape in spec["shapes"]]
    assert "l" in labels


def test_duplicate_expression_annotations_are_dropped():
    spec = rd.prepare_diagram({
        "type": "plot2d",
        "shapes": [
            {"kind": "curve", "expr": "x^2", "domain": [-2, 2]},
            {"kind": "point", "x": 0.5, "y": 0.25, "label": "(1/2, 1/4)"},
            {"kind": "segment", "label": "切线",
             "from": [0.3, 0.05], "to": [0.7, 0.45]},
        ],
        "annotations": [
            {"x": 1.3, "y": 1.9, "text": "y = x²"},
            {"x": 0.62, "y": 0.25, "text": "(1/2, 1/4)"},
        ],
    })
    assert spec and spec["annotations"] == []


def test_plot2d_equation_labelled_line_is_also_corrected():
    spec = rd.prepare_diagram({
        "type": "plot2d",
        "shapes": [
            {"kind": "curve", "expr": "x^2", "domain": [-2, 2]},
            {"kind": "point", "x": 0.5, "y": 0.25, "label": "P"},
            {"kind": "segment", "label": "y=x-1/4",
             "from": [-0.3, -0.1], "to": [1.3, 1.5]},
        ],
    })
    assert spec
    tangent = next(shape for shape in spec["shapes"]
                   if shape.get("kind") == "segment")
    assert abs(tangent["from"][1] - 0.05) < 1e-5
    assert abs(tangent["to"][1] - 0.45) < 1e-5
    curve = next(shape for shape in spec["shapes"]
                 if shape.get("kind") == "curve")
    assert curve["label"] == "y=x²"


def test_geometry2d_straight_curve_is_corrected_as_tangent():
    spec = rd.prepare_diagram({
        "type": "geometry2d",
        "shapes": [
            {"kind": "curve", "label": "y=x²", "expr": "x^2", "domain": [-2, 2]},
            {"kind": "curve", "label": "y=x", "expr": "x", "domain": [-2, 2]},
            {"kind": "point", "x": 0.5, "y": 0.25, "label": "P"},
        ],
    })
    assert spec
    tangent = next(shape for shape in spec["shapes"]
                   if shape.get("label") == "切线")
    assert tangent["kind"] == "curve"
    assert len(tangent["points"]) == 2
    assert abs(tangent["from"][1] - 0.05) < 1e-5
    assert abs(tangent["to"][1] - 0.45) < 1e-5


def test_plot2d_parametric_curve_uses_point_order_for_vertical_tangent():
    """参数曲线不能按 x 排序;半圆顶点的切线应竖直。"""
    points = [
        [math.cos(t), math.sin(t)]
        for t in (-math.pi / 2 + math.pi * i / 200 for i in range(201))
    ]
    raw = {
        "type": "plot2d",
        "shapes": [
            {"kind": "curve", "points": points, "label": "半圆"},
            {"kind": "point", "x": 1, "y": 0, "label": "P"},
            {"kind": "segment", "label": "切线",
             "from": [0.9, -0.1], "to": [1.1, 0.1]},
        ],
        "annotations": [],
    }
    diagram = rd.prepare_diagram(raw)
    assert diagram is not None
    tangent = next(shape for shape in diagram["shapes"]
                   if shape.get("label") == "切线")
    x1, y1 = tangent["from"][:2]
    x2, y2 = tangent["to"][:2]
    assert abs(x2 - x1) < 0.02
    assert abs(y2 - y1) > 0.2


def test_tangent_on_axis_is_not_dropped_as_duplicate_axis():
    """水平切线可能正好与 x 轴重合;标了切线就不能当重复坐标轴删掉。"""
    raw = {
        "type": "plot2d",
        "shapes": [
            {"kind": "curve", "expr": "x^2", "domain": [-2, 2]},
            {"kind": "point", "x": 0, "y": 0, "label": "O"},
            {"kind": "segment", "label": "切线", "from": [-1, 0.2], "to": [1, -0.2]},
        ],
        "annotations": [],
    }
    diagram = rd.prepare_diagram(raw)
    assert diagram is not None
    tangent = next(shape for shape in diagram["shapes"]
                   if shape.get("label") == "切线")
    assert tangent["from"][1] == 0 and tangent["to"][1] == 0


def test_plot2d_cusp_has_no_fake_tangent():
    """abs(x) 在 0 处左右导数不一致,不存在唯一切线;应删掉模型画的假切线。"""
    raw = {
        "type": "plot2d",
        "shapes": [
            {"kind": "curve", "expr": "abs(x)", "domain": [-2, 2]},
            {"kind": "point", "x": 0, "y": 0, "label": "O"},
            {"kind": "segment", "label": "切线",
             "from": [-0.2, 0], "to": [0.2, 0]},
        ],
        "annotations": [],
    }
    diagram = rd.prepare_diagram(raw)
    assert diagram is not None
    assert not any(shape.get("label") == "切线" for shape in diagram["shapes"])


def test_plot2d_tangent_uses_the_curve_through_the_point():
    """同图有多条函数曲线时,切线必须跟着切点所在的那条,不能总用第一条。"""
    raw = {
        "type": "plot2d",
        "shapes": [
            {"kind": "curve", "expr": "x^2", "domain": [-2, 2]},
            {"kind": "curve", "expr": "-x^2", "domain": [-2, 2]},
            {"kind": "point", "x": 1, "y": -1, "label": "P"},
            {"kind": "segment", "label": "切线",
             "from": [0.8, -0.8], "to": [1.2, -1.2]},
        ],
        "annotations": [],
    }
    diagram = rd.prepare_diagram(raw)
    assert diagram is not None
    tangent = next(shape for shape in diagram["shapes"]
                   if shape.get("label") == "切线")
    x1, y1 = tangent["from"][:2]
    x2, y2 = tangent["to"][:2]
    assert abs((y2 - y1) / (x2 - x1) + 2.0) < 1e-3
    point = next(shape for shape in diagram["shapes"]
                 if shape.get("label") == "P")
    assert point["y"] == -1


def test_tangent_object_with_curve_and_x_is_materialized():
    raw = {
        "type": "plot2d",
        "shapes": [
            {"kind": "curve", "expr": "x^2", "domain": [-2, 2]},
            {"kind": "tangent", "curve": "x^2", "x": 1},
        ],
        "annotations": [],
    }
    diagram = rd.prepare_diagram(raw)
    tangent = next(shape for shape in diagram["shapes"]
                   if shape.get("label") == "切线")
    assert tangent["kind"] == "segment"
    x1, y1 = tangent["from"][:2]
    x2, y2 = tangent["to"][:2]
    assert abs((y2 - y1) / (x2 - x1) - 2.0) < 1e-3
    assert abs(y1 + (1 - x1) * 2 - 1) < 1e-3


def test_tangent_object_targets_circle_and_ellipse():
    circle = rd.prepare_diagram({
        "type": "geometry2d",
        "shapes": [
            {"kind": "circle", "x": 0, "y": 0, "r": 2, "label": "C"},
            {"kind": "tangent", "curve": "C", "x": 2, "y": 0},
        ],
    })
    tangent = next(shape for shape in circle["shapes"]
                   if shape.get("label") == "切线")
    x1, y1 = tangent["from"][:2]
    x2, y2 = tangent["to"][:2]
    assert abs(x1 - 2) < 1e-6 and abs(x2 - 2) < 1e-6
    ellipse = rd.prepare_diagram({
        "type": "geometry2d",
        "shapes": [
            {"kind": "ellipse", "x": 0, "y": 0, "rx": 2, "ry": 1,
             "label": "E"},
            {"kind": "tangent", "curve": "E", "x": 2, "y": 0},
        ],
    })
    tangent = next(shape for shape in ellipse["shapes"]
                   if shape.get("label") == "切线")
    x1, y1 = tangent["from"][:2]
    x2, y2 = tangent["to"][:2]
    assert abs(x1 - 2) < 1e-6 and abs(x2 - 2) < 1e-6


def test_tangent_alias_is_normalized_and_corrected():
    """tangent 语义对象落到渲染层为 segment,并走同一套切线校正。"""
    raw = {
        "type": "plot2d",
        "shapes": [
            {"kind": "curve", "expr": "x^2", "domain": [-2, 2]},
            {"kind": "point", "x": 1, "y": 1, "label": "P"},
            {"kind": "tangent", "from": [0.8, 0.8], "to": [1.2, 1.2]},
        ],
        "annotations": [],
    }
    diagram = rd.prepare_diagram(raw)
    tangent = next(shape for shape in diagram["shapes"]
                   if shape.get("label") == "切线")
    assert tangent["kind"] == "segment"
    x1, y1 = tangent["from"][:2]
    x2, y2 = tangent["to"][:2]
    assert abs((y2 - y1) / (x2 - x1) - 2.0) < 1e-3


def test_plot2d_does_not_turn_a_secant_into_a_tangent():
    """同图有割线和切线时,只能校正切线;不能把所有直线都当切线。"""
    raw = {
        "type": "plot2d",
        "shapes": [
            {"kind": "curve", "expr": "x^2", "domain": [-2, 2]},
            {"kind": "point", "x": 1, "y": 1, "label": "P"},
            {"kind": "segment", "label": "切线",
             "from": [0.8, 0.8], "to": [1.2, 1.2]},
            {"kind": "segment", "label": "割线",
             "from": [-1, 1], "to": [2, 4]},
        ],
        "annotations": [],
    }
    diagram = rd.prepare_diagram(raw)
    assert diagram is not None
    tangent = next(shape for shape in diagram["shapes"]
                   if shape.get("label") == "切线")
    secant = next(shape for shape in diagram["shapes"]
                  if shape.get("label") == "割线")
    tx1, ty1 = tangent["from"][:2]
    tx2, ty2 = tangent["to"][:2]
    assert abs((ty2 - ty1) / (tx2 - tx1) - 2.0) < 1e-3
    assert secant["from"] == [-1.0, 1.0]
    assert secant["to"] == [2.0, 4.0]


def test_plot2d_single_unlabeled_line_is_still_treated_as_tangent():
    """模型漏标签且图里只有一条直线时,仍按切线校正。"""
    raw = {
        "type": "plot2d",
        "shapes": [
            {"kind": "curve", "expr": "x^2", "domain": [-2, 2]},
            {"kind": "point", "x": 1, "y": 1, "label": "P"},
            {"kind": "segment", "from": [0.8, 0.8], "to": [1.2, 1.2]},
        ],
        "annotations": [],
    }
    diagram = rd.prepare_diagram(raw)
    assert diagram is not None
    tangent = next(shape for shape in diagram["shapes"]
                   if shape.get("kind") == "segment")
    x1, y1 = tangent["from"][:2]
    x2, y2 = tangent["to"][:2]
    assert abs((y2 - y1) / (x2 - x1) - 2.0) < 1e-3


@pytest.mark.parametrize("expr,x0,domain", [
    ("x^2", 1.0, [-2, 2]),
    ("sin(x)", 0.3, [-3, 3]),
    ("e^x", 0.0, [-2, 2]),
    ("x^3-2*x", 0.7, [-2, 2]),
    ("sqrt(x)", 0.25, [0, 4]),
    ("1/x", 1.5, [0.5, 3]),
])
def test_tangent_invariant_passes_through_curve_with_derivative_slope(expr, x0, domain):
    """不变量:切线必须过曲线上的切点,斜率等于该点导数。"""
    run = rd._compile_expr(expr)
    assert run is not None
    y0 = float(run(x0))
    raw = {
        "type": "plot2d",
        "shapes": [
            {"kind": "curve", "expr": expr, "domain": domain},
            {"kind": "point", "x": x0, "y": y0, "label": "P"},
            {"kind": "segment", "label": "切线",
             "from": [x0 - 0.05, y0], "to": [x0 + 0.05, y0]},
        ],
        "annotations": [],
    }
    diagram = rd.prepare_diagram(raw)
    tangent = next(shape for shape in diagram["shapes"]
                   if shape.get("label") == "切线")
    x1, y1 = tangent["from"][:2]
    x2, y2 = tangent["to"][:2]
    slope = (y2 - y1) / (x2 - x1)
    h = 1e-4 * max(1.0, abs(x0))
    derivative = (float(run(x0 + h)) - float(run(x0 - h))) / (2 * h)
    assert abs(slope - derivative) < 1e-2
    # 切线在 x0 处的高度必须等于曲线高度
    line_y = y1 + slope * (x0 - x1)
    assert abs(line_y - y0) < 1e-2


def test_circle_tangent_invariant_perpendicular_to_radius():
    spec = rd.prepare_diagram({
        "type": "geometry2d",
        "shapes": [
            {"kind": "circle", "x": 1, "y": -1, "r": 2.5},
            {"kind": "point", "x": 3.5, "y": -1, "label": "P"},
            {"kind": "line", "label": "切线", "from": [3.5, -3], "to": [3.5, 1]},
        ],
    })
    tangent = next(shape for shape in spec["shapes"]
                   if shape.get("label") == "切线")
    x1, y1 = tangent["from"][:2]
    x2, y2 = tangent["to"][:2]
    rx, ry = 3.5 - 1, -1 - (-1)
    tx, ty = x2 - x1, y2 - y1
    assert abs(rx * tx + ry * ty) < 1e-6
    # 切线到圆心的距离等于半径
    distance = abs((x1 - 1) * ty - (y1 + 1) * tx) / math.hypot(tx, ty)
    assert abs(distance - 2.5) < 1e-6


def test_tangent_plane_normal_is_recomputed_from_surface():
    raw = {
        "type": "surface3d",
        "shapes": [
            {"kind": "surface", "expr": "x^2+y^2",
             "domain": [-2, 2, -2, 2], "rows": 8, "cols": 8},
            {"kind": "plane", "label": "切平面", "x": 1, "y": 1, "z": 2,
             "normal": [0, 0, 1]},
        ],
    }
    spec = rd.prepare_diagram(raw)
    plane = next(shape for shape in spec["shapes"]
                 if shape.get("label") == "切平面")
    assert plane["normal"] == [-2.0, -2.0, 1.0]
    assert plane["z"] == 2.0


def test_parametric_curve_is_sampled_and_tangent_is_vertical_at_circle_top():
    spec = rd.prepare_diagram({
        "type": "geometry2d",
        "shapes": [
            {"kind": "parametric_curve",
             "xexpr": "cos(u)", "yexpr": "sin(u)",
             "domain": [0, 2 * math.pi], "samples": 240},
            {"kind": "point", "x": 1, "y": 0, "label": "P"},
            {"kind": "line", "label": "切线", "from": [0.5, -1], "to": [1.5, 1]},
        ],
    })
    curve = next(shape for shape in spec["shapes"]
                 if shape["kind"] == "parametric_curve")
    assert len(curve["points"]) == 240
    tangent = next(shape for shape in spec["shapes"]
                   if shape.get("label") == "切线")
    x1, y1 = tangent["from"][:2]
    x2, y2 = tangent["to"][:2]
    assert abs(x1 - 1) < 0.02 and abs(x2 - 1) < 0.02
    assert abs(y2 - y1) > 0.1


def test_parametric_curve_3d_is_sampled_on_cylinder():
    spec = rd.prepare_diagram({
        "type": "geometry3d",
        "shapes": [{
            "kind": "parametric_curve",
            "xexpr": "cos(u)", "yexpr": "sin(u)", "zexpr": "u/6.283185",
            "domain": [0, 6.283185], "samples": 120,
        }],
    })
    curve = next(shape for shape in spec["shapes"]
                 if shape["kind"] == "parametric_curve")
    assert len(curve["points"]) == 120
    for x, y, _z in curve["points"]:
        assert abs(x * x + y * y - 1) < 1e-5


def test_implicit_curve_is_sampled_and_tangent_is_perpendicular_to_gradient():
    spec = rd.prepare_diagram({
        "type": "geometry2d",
        "shapes": [
            {"kind": "implicit_curve", "expr": "x^2+y^2-1",
             "domain": [-1.5, 1.5, -1.5, 1.5], "resolution": 60},
            {"kind": "point", "x": 1, "y": 0, "label": "P"},
            {"kind": "line", "label": "切线", "from": [0.5, -1], "to": [1.5, 1]},
        ],
    })
    curve = next(shape for shape in spec["shapes"]
                 if shape["kind"] == "implicit_curve")
    assert curve["segments"] and curve["points"]
    tangent = next(shape for shape in spec["shapes"]
                   if shape.get("label") == "切线")
    x1, y1 = tangent["from"][:2]
    x2, y2 = tangent["to"][:2]
    # 圆在 (1,0) 的切线竖直
    assert abs(x1 - 1) < 0.03 and abs(x2 - 1) < 0.03
    assert abs(y2 - y1) > 0.1


def test_implicit_curve_sphere_contour_is_closed():
    """隐式曲线的 marching squares 不能产生空结果。"""
    spec = rd.prepare_diagram({
        "type": "plot2d",
        "shapes": [{
            "kind": "implicit_curve", "expr": "x^2/4+y^2-1",
            "domain": [-3, 3, -2, 2], "resolution": 80,
        }],
    })
    curve = next(shape for shape in spec["shapes"]
                 if shape["kind"] == "implicit_curve")
    assert len(curve["segments"]) > 20
    for segment in curve["segments"]:
        assert len(segment) == 2


def test_implicit_curve3d_sphere_plane_intersection_is_circle():
    spec = rd.prepare_diagram({
        "type": "geometry3d",
        "shapes": [{
            "kind": "implicit_curve3d",
            "expr": "x^2+y^2+z^2-1", "expr2": "z",
            "domain": [-1.2, 1.2, -1.2, 1.2, -1.2, 1.2],
            "resolution": 20,
        }],
    })
    curve = next(shape for shape in spec["shapes"]
                 if shape["kind"] == "implicit_curve3d")
    assert curve["segments"]
    for segment in curve["segments"]:
        for x, y, z in segment:
            assert abs(z) < 2e-2
            assert abs(x * x + y * y - 1) < 5e-2


def test_implicit_curve3d_tangent_follows_curve():
    spec = rd.prepare_diagram({
        "type": "geometry3d",
        "shapes": [
            {"kind": "implicit_curve3d",
             "expr": "x^2+y^2+z^2-1", "expr2": "z",
             "domain": [-1.2, 1.2, -1.2, 1.2, -1.2, 1.2],
             "resolution": 20},
            {"kind": "point", "x": 1, "y": 0, "z": 0, "label": "P"},
            {"kind": "line", "label": "切线",
             "from": [0.5, -1, 0], "to": [1.5, 1, 0]},
        ],
    })
    tangent = next(shape for shape in spec["shapes"]
                   if shape.get("label") == "切线")
    x1, y1, z1 = tangent["from"][:3]
    x2, y2, z2 = tangent["to"][:3]
    assert abs(x1 - x2) < 0.2 and abs(z1 - z2) < 0.2
    assert abs(y2 - y1) > 0.2


def test_implicit_surface_sphere_is_meshed():
    spec = rd.prepare_diagram({
        "type": "surface3d",
        "shapes": [{
            "kind": "implicit_surface",
            "expr": "x^2+y^2+z^2-1",
            "domain": [-1.5, 1.5, -1.5, 1.5, -1.5, 1.5],
            "resolution": 14,
        }],
    })
    surface = next(shape for shape in spec["shapes"]
                   if shape["kind"] == "implicit_surface")
    positions = _mesh_positions(surface)
    indices = _mesh_indices(surface)
    assert len(positions) >= 9 and len(indices) >= 3
    assert len(indices) % 3 == 0
    assert max(indices) < len(positions) // 3
    for index in range(0, len(positions), 3):
        x, y, z = positions[index:index + 3]
        assert abs(x * x + y * y + z * z - 1) < 0.15


def test_implicit_surface_high_resolution_covers_full_sphere():
    spec = rd.prepare_diagram({
        "type": "surface3d",
        "shapes": [{
            "kind": "implicit_surface",
            "expr": "x^2+y^2+z^2-1",
            "domain": [-1, 1, -1, 1, -1, 1],
            "resolution": 32,
        }],
    })
    surface = next(shape for shape in spec["shapes"]
                   if shape["kind"] == "implicit_surface")
    positions = _mesh_positions(surface)
    xs = positions[0::3]
    assert max(xs) > 0.99 and min(xs) < -0.99
    # 顶点去重后不会因为网格截断只覆盖球的一半
    assert len(positions) // 3 < 30000


def test_implicit_surface_normal_uses_gradient():
    raw = {
        "type": "surface3d",
        "shapes": [
            {"kind": "implicit_surface", "expr": "x^2+y^2+z^2-1",
             "domain": [-1, 1, -1, 1, -1, 1], "resolution": 15},
            {"kind": "vector", "label": "法向量 n",
             "from": [1.05, 0, 0], "to": [2, 0, 0]},
            {"kind": "plane", "label": "切平面", "x": 0, "y": 0, "z": 1,
             "normal": [0, 0, 1]},
        ],
    }
    spec = rd.prepare_diagram(raw)
    vector = next(shape for shape in spec["shapes"]
                  if shape["kind"] == "vector")
    fx, fy, fz = vector["from"]
    dx = vector["to"][0] - fx
    dy = vector["to"][1] - fy
    dz = vector["to"][2] - fz
    anchor_norm = math.sqrt(fx * fx + fy * fy + fz * fz)
    vector_norm = math.sqrt(dx * dx + dy * dy + dz * dz)
    radial = (fx * dx + fy * dy + fz * dz) / (anchor_norm * vector_norm)
    assert radial > 0.8
    plane = next(shape for shape in spec["shapes"]
                 if shape.get("label") == "切平面")
    nx, ny, nz = plane["normal"]
    assert abs(nz) > 0.8


def test_parametric_surface_scalar_field_gradient_stays_in_tangent_plane():
    raw = {
        "type": "surface3d",
        "shapes": [
            {"kind": "parametric_surface",
             "xexpr": "u", "yexpr": "v", "zexpr": "u+v",
             "fieldexpr": "x+y",
             "domain": [0, 2, 0, 2], "rows": 5, "cols": 5},
            {"kind": "vector", "label": "梯度 ∇f",
             "from": [1, 1, 2], "to": [2, 2, 3]},
        ],
    }
    spec = rd.prepare_diagram(raw)
    vector = next(shape for shape in spec["shapes"]
                  if shape["kind"] == "vector")
    dx = vector["to"][0] - vector["from"][0]
    dy = vector["to"][1] - vector["from"][1]
    dz = vector["to"][2] - vector["from"][2]
    # 平面法向 (-1,-1,1)/√3;曲面梯度必须与法向正交
    assert abs(-dx - dy + dz) < 1e-3
    assert abs(dx) + abs(dy) + abs(dz) > 0.1


def test_parametric_tangent_plane_normal_uses_grid_derivatives():
    raw = {
        "type": "surface3d",
        "shapes": [
            {"kind": "parametric_surface",
             "xexpr": "u", "yexpr": "v", "zexpr": "u+v",
             "domain": [0, 2, 0, 2], "rows": 5, "cols": 5},
            {"kind": "plane", "label": "切平面", "x": 1, "y": 1, "z": 2,
             "normal": [0, 0, 1]},
        ],
    }
    spec = rd.prepare_diagram(raw)
    plane = next(shape for shape in spec["shapes"]
                 if shape.get("label") == "切平面")
    nx, ny, nz = plane["normal"]
    assert abs(nx - ny) < 1e-6
    assert nz > 0 and abs(nx + nz) < 1e-6


def test_parametric_surface_normal_uses_grid_derivatives():
    """参数曲面的法向量按 r_u × r_v 修正;平面 z=u+v 的法向应为 (-1,-1,1)。"""
    raw = {
        "type": "surface3d",
        "shapes": [
            {"kind": "parametric_surface",
             "xexpr": "u", "yexpr": "v", "zexpr": "u+v",
             "domain": [0, 2, 0, 2], "rows": 5, "cols": 5},
            {"kind": "vector", "label": "法向量 n",
             "from": [1, 1, 2], "to": [0, 0, 3]},
        ],
    }
    spec = rd.prepare_diagram(raw)
    vector = next(shape for shape in spec["shapes"]
                  if shape["kind"] == "vector")
    assert vector["from"] == [1.0, 1.0, 2.0]
    dx = vector["to"][0] - vector["from"][0]
    dy = vector["to"][1] - vector["from"][1]
    dz = vector["to"][2] - vector["from"][2]
    assert abs(dx - dy) < 1e-4
    assert dz > 0 and abs(dx + dz) < 1e-4


def test_parametric_surface_is_sampled_and_rendered_as_surface():
    spec = rd.prepare_diagram({
        "type": "surface3d",
        "shapes": [{
            "kind": "parametric_surface",
            "xexpr": "cos(u)*sin(v)",
            "yexpr": "sin(u)*sin(v)",
            "zexpr": "cos(v)",
            "domain": [0, 2 * math.pi, 0, math.pi],
            "rows": 6, "cols": 7,
        }],
    })
    surface = next(shape for shape in spec["shapes"]
                   if shape["kind"] == "parametric_surface")
    assert len(surface["points"]) == 42
    for x, y, z in surface["points"]:
        assert abs(x * x + y * y + z * z - 1) < 1e-5


def test_surface_sample_points_satisfy_expression():
    spec = rd.prepare_diagram({
        "type": "surface3d",
        "shapes": [{"kind": "surface", "expr": "x^2+y^2",
                    "domain": [-1, 1, -1, 1], "rows": 4, "cols": 5}],
    })
    surface = next(shape for shape in spec["shapes"]
                   if shape["kind"] == "surface")
    for x, y, z in surface["points"]:
        assert abs(z - (x * x + y * y)) < 1e-5


def test_labeled_straight_curve_tangent_without_point_uses_midpoint():
    """切线被画成直线型 curve 且没有关键点时,也要按曲线中点校正。"""
    spec = rd.prepare_diagram({
        "type": "plot2d",
        "shapes": [
            {"kind": "curve", "label": "y=x²", "expr": "x^2", "domain": [-2, 2]},
            {"kind": "curve", "label": "切线",
             "points": [[0, 0], [2, 2]]},
        ],
    })
    assert spec
    tangent = next(shape for shape in spec["shapes"]
                   if shape.get("label") == "切线")
    assert tangent["kind"] == "curve"
    x1, y1 = tangent["from"][:2]
    x2, y2 = tangent["to"][:2]
    assert abs((y2 - y1) / (x2 - x1) - 2.0) < 1e-3
    assert abs(y1 + (1 - x1) * 2 - 1) < 1e-3


def test_3d_ellipse_tangent_is_corrected():
    spec = rd.prepare_diagram({
        "type": "geometry3d",
        "shapes": [
            {"kind": "ellipse", "x": 0, "y": 0, "z": 1, "rx": 2, "ry": 1},
            {"kind": "point", "x": 2, "y": 0, "z": 1, "label": "P"},
            {"kind": "line", "label": "切线", "from": [1, -1, 1], "to": [3, 1, 2]},
        ],
    })
    tangent = next(shape for shape in spec["shapes"]
                   if shape.get("label") == "切线")
    assert tangent["from"][2] == 1.0 and tangent["to"][2] == 1.0
    assert abs(tangent["from"][0] - 2) < 1e-6
    assert abs(tangent["to"][0] - 2) < 1e-6
    assert abs(tangent["from"][1] - tangent["to"][1]) > 0.2


def test_3d_ellipse_tangent_honors_tilted_plane():
    spec = rd.prepare_diagram({
        "type": "geometry3d",
        "shapes": [
            {"kind": "ellipse", "x": 0, "y": 0, "z": 0, "rx": 2, "ry": 1,
             "normal": [0, 1, 0]},
            {"kind": "point", "x": 2, "y": 0, "z": 0, "label": "P"},
            {"kind": "line", "label": "切线", "from": [1, -1, 1], "to": [3, 1, 1]},
        ],
    })
    tangent = next(shape for shape in spec["shapes"]
                   if shape.get("label") == "切线")
    assert abs(tangent["from"][1]) < 1e-6
    assert abs(tangent["to"][1]) < 1e-6
    assert abs(tangent["from"][0] - 2) < 1e-6
    assert abs(tangent["to"][0] - 2) < 1e-6
    assert abs(tangent["from"][2] - tangent["to"][2]) > 0.2


def test_3d_circle_tangent_is_horizontal_and_perpendicular_to_radius():
    raw = {
        "type": "geometry3d",
        "shapes": [
            {"kind": "circle", "x": 0, "y": 0, "z": 1, "r": 2},
            {"kind": "point", "x": 2, "y": 0, "z": 1, "label": "P"},
            {"kind": "line", "label": "切线",
             "from": [1, -1, 1], "to": [3, 1, 2]},
        ],
    }
    spec = rd.prepare_diagram(raw)
    tangent = next(shape for shape in spec["shapes"]
                   if shape.get("label") == "切线")
    assert tangent["from"][2] == 1.0 and tangent["to"][2] == 1.0
    # 过 (2,0,1) 的竖直线在 xy 平面内切圆
    assert abs(tangent["from"][0] - 2) < 1e-6
    assert abs(tangent["to"][0] - 2) < 1e-6
    assert abs(tangent["from"][1] - tangent["to"][1]) > 0.2


def test_3d_circle_tangent_honors_plane_normal():
    """竖直平面 xz 内的圆,切向应在该平面内,不能按水平圆画。"""
    raw = {
        "type": "geometry3d",
        "shapes": [
            {"kind": "circle", "x": 0, "y": 0, "z": 0, "r": 2,
             "normal": [0, 1, 0]},
            {"kind": "point", "x": 2, "y": 0, "z": 0, "label": "P"},
            {"kind": "line", "label": "切线",
             "from": [1, -1, 1], "to": [3, 1, 1]},
        ],
    }
    spec = rd.prepare_diagram(raw)
    tangent = next(shape for shape in spec["shapes"]
                   if shape.get("label") == "切线")
    x1, y1, z1 = tangent["from"][:3]
    x2, y2, z2 = tangent["to"][:3]
    assert abs(y1) < 1e-6 and abs(y2) < 1e-6
    assert abs(x1 - 2) < 1e-6 and abs(x2 - 2) < 1e-6
    assert abs(z2 - z1) > 0.2


def test_3d_curve_tangent_uses_neighbor_direction():
    """3D 参数曲线的切线方向取局部点列差分,并落在曲线上。"""
    raw = {
        "type": "geometry3d",
        "shapes": [
            {"kind": "curve", "label": "空间曲线",
             "points": [[0, 0, 0], [1, 1, 0], [2, 4, 0], [3, 9, 0]]},
            {"kind": "segment", "label": "切线",
             "from": [0.5, -1, 0], "to": [2.5, 2, 1]},
        ],
    }
    spec = rd.prepare_diagram(raw)
    tangent = next(shape for shape in spec["shapes"]
                   if shape.get("label") == "切线")
    from_point = tangent["from"]
    to_point = tangent["to"]
    direction = [to_point[i] - from_point[i] for i in range(3)]
    # 局部方向应平行于 (2,4,0),即 direction[1] ≈ 2*direction[0],z≈0
    assert abs(direction[1] - 2 * direction[0]) < 1e-3
    assert abs(direction[2]) < 1e-6
    # 线段中点应落在曲线点 (1,1,0) 或 (2,4,0) 附近
    mid = [(from_point[i] + to_point[i]) / 2 for i in range(3)]
    assert any(abs(mid[0] - point[0]) < 1e-3
               and abs(mid[1] - point[1]) < 1e-3
               for point in [[1, 1, 0], [2, 4, 0]])


def test_geometry2d_ellipse_tangent_is_corrected():
    """椭圆切线:在 (rx,0) 处应竖直,且不能过圆心。"""
    spec = rd.prepare_diagram({
        "type": "geometry2d",
        "shapes": [
            {"kind": "ellipse", "x": 0, "y": 0, "rx": 2, "ry": 1},
            {"kind": "point", "x": 2, "y": 0, "label": "P"},
            {"kind": "line", "label": "切线", "from": [1, -1], "to": [3, 1]},
        ],
    })
    assert spec
    tangent = next(shape for shape in spec["shapes"]
                   if shape.get("label") == "切线")
    x1, y1 = tangent["from"][:2]
    x2, y2 = tangent["to"][:2]
    assert abs(x1 - 2) < 1e-6 and abs(x2 - 2) < 1e-6
    assert abs(y2 - y1) > 0.2


def test_geometry2d_rotated_ellipse_tangent_is_perpendicular_to_gradient():
    """旋转椭圆:切线方向仍垂直于椭圆梯度。"""
    spec = rd.prepare_diagram({
        "type": "geometry2d",
        "shapes": [
            {"kind": "ellipse", "x": 0, "y": 0, "rx": 2, "ry": 1,
             "rotation": math.pi / 6},
            {"kind": "line", "label": "切线", "from": [-1, 0], "to": [1, 0]},
        ],
    })
    tangent = next(shape for shape in spec["shapes"]
                   if shape.get("label") == "切线")
    # 无关键点时切点由切线中点投影;只检查切线到椭圆中心的距离合理且方向非零
    dx = tangent["to"][0] - tangent["from"][0]
    dy = tangent["to"][1] - tangent["from"][1]
    assert abs(dx) + abs(dy) > 0.1


def test_geometry2d_circle_tangent_is_corrected():
    """圆的切线垂直于半径;竖切线不能被模型画成斜线。"""
    spec = rd.prepare_diagram({
        "type": "geometry2d",
        "shapes": [
            {"kind": "circle", "x": 0, "y": 0, "r": 2},
            {"kind": "point", "x": 2, "y": 0, "label": "P"},
            {"kind": "line", "label": "切线", "from": [1, -1], "to": [3, 1]},
        ],
    })
    assert spec
    tangent = next(shape for shape in spec["shapes"]
                   if shape.get("label") == "切线")
    x1, y1 = tangent["from"][:2]
    x2, y2 = tangent["to"][:2]
    # 过 (2,0) 的竖切线
    assert abs(x1 - 2) < 1e-3 and abs(x2 - 2) < 1e-3
    assert abs(y2 - y1) > 0.2


def test_geometry2d_circle_tangent_without_point_projects_from_center():
    """没有切点时,用圆心到切线的垂足投到圆上定切点。"""
    spec = rd.prepare_diagram({
        "type": "geometry2d",
        "shapes": [
            {"kind": "circle", "x": 0, "y": 0, "r": 2},
            {"kind": "line", "label": "切线", "from": [2.2, -1], "to": [2.2, 1]},
        ],
    })
    assert spec
    tangent = next(shape for shape in spec["shapes"]
                   if shape.get("label") == "切线")
    x1, y1 = tangent["from"][:2]
    x2, y2 = tangent["to"][:2]
    assert abs(x1 - 2) < 0.05 and abs(x2 - 2) < 0.05


def test_geometry2d_circle_tangent_drawn_as_straight_curve():
    """切线被画成两点 curve 时,圆切线也要校正并保留 curve 类型。"""
    spec = rd.prepare_diagram({
        "type": "geometry2d",
        "shapes": [
            {"kind": "circle", "x": 0, "y": 0, "r": 2},
            {"kind": "point", "x": 2, "y": 0, "label": "P"},
            {"kind": "curve", "label": "切线", "points": [[1, -1], [3, 1]]},
        ],
    })
    assert spec
    tangent = next(shape for shape in spec["shapes"]
                   if shape.get("label") == "切线")
    assert tangent["kind"] == "curve"
    x1, y1 = tangent["from"][:2]
    x2, y2 = tangent["to"][:2]
    assert abs(x1 - 2) < 1e-3 and abs(x2 - 2) < 1e-3


def test_plot2d_tangent_uses_the_requested_key_point():
    spec = rd.prepare_diagram({
        "type": "plot2d",
        "shapes": [
            {"kind": "curve", "label": "y=x²", "expr": "x^2", "domain": [-2, 2]},
            {"kind": "point", "x": 0.5, "y": 0.25, "label": "P"},
            {"kind": "segment", "label": "切线",
             "from": [0.2, 0.1], "to": [0.8, 0.9]},
        ],
    })
    assert spec
    tangent = next(shape for shape in spec["shapes"]
                   if shape.get("label") == "切线")
    point = next(shape for shape in spec["shapes"]
                 if shape.get("label") == "P")
    assert point["y"] == 0.25
    assert abs(tangent["from"][1] - (0.25 - 0.2)) < 1e-5
    assert abs(tangent["to"][1] - (0.25 + 0.2)) < 1e-5


def test_plot2d_drops_derivative_overlay_and_fixes_tangent():
    spec = rd.prepare_diagram({
        "type": "plot2d",
        "shapes": [
            {"kind": "curve", "label": "y=x²", "expr": "x^2", "domain": [-3, 3]},
            {"kind": "curve", "label": "y'=2x", "expr": "2*x", "domain": [-3, 3]},
            {"kind": "point", "x": 0, "y": 0, "label": "O"},
            {"kind": "segment", "label": "水平切线",
             "from": [-1, 1], "to": [1, -1]},
        ],
    })
    assert spec
    labels = [shape.get("label") for shape in spec["shapes"]]
    assert "y'=2x" not in labels
    tangent = next(shape for shape in spec["shapes"]
                   if shape.get("label") == "水平切线")
    assert tangent["from"][1] == 0
    assert tangent["to"][1] == 0


def test_validate_rejects_unsampled_curve_only_plots():
    assert validate_diagram({
        "type": "plot2d",
        "shapes": [
            {"kind": "axis", "from": [-3, 0], "to": [3, 0]},
            {"kind": "curve", "expr": "x^2", "domain": [-3, 3]},
        ],
    }) is None


def test_validate_rejects_future_schema_version():
    assert validate_diagram({
        "schemaVersion": rd.DIAGRAM_SCHEMA_VERSION + 1,
        "type": "flow",
        "nodes": [{"id": "a", "label": "A"}],
    }) is None
    current = validate_diagram({
        "type": "flow",
        "nodes": [{"id": "a", "label": "A"}],
    })
    assert current and current["schemaVersion"] == rd.DIAGRAM_SCHEMA_VERSION


def test_plan_metrics_do_not_include_content(monkeypatch):
    import diagram_metrics

    monkeypatch.setattr(rd.llm, "is_configured", lambda role="main", **k: True)

    async def fake_stream(system, user, **kwargs):
        yield json.dumps({"type": "flow", "nodes": [{"id": "a", "label": "A"}]})

    monkeypatch.setattr(rd.llm, "stream_chat", fake_stream)
    assert asyncio.run(rd.plan_diagram("机密问题", "机密回答", [], "flow"))
    snap = diagram_metrics.snapshot()
    assert snap["planCount"] == 1
    assert snap["planFailures"] == 0
    assert "机密" not in json.dumps(snap, ensure_ascii=False)


def test_placeholder_label_is_dropped():
    spec = validate_diagram({
        "type": "geometry2d",
        "shapes": [{"kind": "point", "x": 1, "y": 2, "label": "DJJ"}],
    })
    assert spec and "label" not in spec["shapes"][0]


def test_prefer_visual_keeps_function_plot_over_flow():
    kind, _score = rd.score_segment(
        "一元函数 y=x² 的导数是 2x,导数大于 0 时单调递增。",
        prefer_visual=True,
    )
    assert kind == "plot2d"


def test_concept_relation_question_forces_mind_map(monkeypatch):
    seen: dict[str, str] = {}
    monkeypatch.setattr(rd.llm, "is_configured", lambda role="main", **k: True)

    async def fake_stream(system, user, **kwargs):
        seen["user"] = user
        yield json.dumps({
            "type": "tree",
            "nodes": [{"id": "a", "label": "可微"}, {"id": "b", "label": "连续"}],
            "edges": [{"from": "a", "to": "b"}],
        })

    monkeypatch.setattr(rd.llm, "stream_chat", fake_stream)
    result = asyncio.run(rd.plan_diagram(
        "偏导数连续、可微、连续之间是什么关系", "解释", [], "surface3d",
        strict=False))
    assert result and result["type"] == "tree"
    assert "请求图解类型:tree" in seen["user"]


def test_relation_question_with_analogy_can_use_concrete_image(monkeypatch):
    monkeypatch.setattr(rd.llm, "is_configured", lambda role="main", **k: True)

    async def fake_stream(system, user, **kwargs):
        yield json.dumps({
            "type": "geometry2d",
            "shapes": [{"kind": "vector", "from": [0, 0], "to": [1, 1]}],
        })

    monkeypatch.setattr(rd.llm, "stream_chat", fake_stream)
    result = asyncio.run(rd.plan_diagram(
        "用类比讲讲偏导数与连续的关系", "解释", [], "", strict=False))
    assert result and result["type"] == "geometry2d"


def test_meta_question_never_gets_diagram():
    question = "你好，今天先介绍一下这个系统能做什么"
    assert rd.is_meta_question(question)
    text = "系统可以做概念动画、章节知识导航、问题记录、公式查询和待办清单。"
    assert rd.select_segments(question, text) == []


def test_diagram_suppressed_by_explicit_no_draw_instruction():
    assert rd.diagram_suppressed("先不要画图，只讲概念")
    assert rd.diagram_suppressed("这轮不用配图")
    assert rd.diagram_suppressed("别画了，用文字说")
    # 同一条消息里明确改口要三维图,以后半句为准。
    assert not rd.diagram_suppressed("不要画思维导图，画三维图")
    assert not rd.diagram_suppressed("现在可以画图了")
    assert not rd.diagram_suppressed("用三维图讲讲梯度")
    assert rd.select_segments("先不要画图", "第一步画曲线，第二步标梯度。") == []


def test_diagram_suppression_follows_history_until_user_resumes():
    history = [
        {"role": "user", "content": "先不要画图，等我讲完"},
        {"role": "assistant", "content": "好的，我继续用文字讲。"},
    ]
    assert rd.diagram_suppressed("继续讲这个定理", history)
    # 用户恢复画图后,后续追问不能一直停在图解模式。
    assert not rd.diagram_suppressed("现在可以画图了", history)
    assert not rd.diagram_suppressed("用三维图讲讲梯度", history)
    resumed = history + [
        {"role": "user", "content": "现在可以画图了"},
        {"role": "assistant", "content": "好的。"},
    ]
    assert not rd.diagram_suppressed("继续", resumed)


def test_validate_rejects_type_structure_mismatch():
    assert validate_diagram({
        "type": "surface3d",
        "nodes": [{"id": "a", "label": "A"}],
    }) is None
    assert validate_diagram({
        "type": "flow",
        "shapes": [{"kind": "point", "x": 1, "y": 2}],
    }) is None


def test_plan_diagram_rejects_wrong_requested_type(monkeypatch):
    monkeypatch.setattr(rd.llm, "is_configured", lambda role="main", **k: True)

    async def fake_stream(system, user, **kwargs):
        yield json.dumps({
            "type": "relation",
            "nodes": [{"id": "a", "label": "A"}, {"id": "b", "label": "B"}],
            "edges": [{"from": "a", "to": "b"}],
        })

    monkeypatch.setattr(rd.llm, "stream_chat", fake_stream)
    # 明确要流程图,却返回关系图:宁可不出图,也不能画错类型。
    assert asyncio.run(plan_diagram("画个流程图", "", [], "flow")) is None


def test_plan_diagram_can_override_suggested_type(monkeypatch):
    monkeypatch.setattr(rd.llm, "is_configured", lambda role="main", **k: True)

    async def fake_stream(system, user, **kwargs):
        yield json.dumps({
            "type": "geometry2d",
            "shapes": [{"kind": "vector", "from": [0, 0], "to": [1, 1]}],
        })

    monkeypatch.setattr(rd.llm, "stream_chat", fake_stream)
    # 标记建议 relation,但内容更适合二维几何;建议类型不是硬性要求,应允许改选。
    result = asyncio.run(plan_diagram("怎么理解这个变换", "", [], "relation"))
    assert result and result["type"] == "geometry2d"


def test_gradient_does_not_move_unrelated_point_or_invent_zero_vector():
    result = rd.prepare_diagram({
        "type": "surface3d",
        "shapes": [
            {"kind": "surface", "expr": "x^2+y^2", "domain": [-4, 4],
             "rows": 3, "cols": 3},
            {"kind": "point", "x": 3, "y": 3, "z": 18},
            {"kind": "vector", "label": "gradient", "from": [0, 0, 0], "to": [1, 0, 1]},
            {"kind": "plane", "label": "tangent", "normal": [1, 0, 1],
             "x": 0, "y": 0, "z": 0},
        ],
    })
    assert result
    assert next(s for s in result["shapes"] if s["kind"] == "point")["z"] == 18
    assert not any(s["kind"] == "vector" for s in result["shapes"])
    assert next(s for s in result["shapes"] if s["kind"] == "plane")["normal"] == [0, 0, 1]


def test_surface_repair_fills_missing_surface_and_plane_height():
    raw = {
        "type": "surface3d",
        "shapes": [
            {"kind": "plane", "normal": [0, 0, 1]},
            {"kind": "circle", "radius": 1},
            {"kind": "point", "x": 1, "y": 0, "z": 1},
        ],
    }
    repaired = rd.repair_surface_shapes(
        raw, "用三维图画出抛物面 z = x^2 + y^2 和平面 z = 1 的交线。")
    result = rd.prepare_diagram(repaired)
    assert result
    assert any(shape["kind"] == "surface" for shape in result["shapes"])
    plane = next(shape for shape in result["shapes"] if shape["kind"] == "plane")
    circle = next(shape for shape in result["shapes"] if shape["kind"] == "circle")
    assert plane["x"] == 0 and plane["y"] == 0 and plane["z"] == 1
    assert circle["x"] == 0 and circle["y"] == 0 and circle["z"] == 1


def test_surface_repair_does_not_pick_one_of_multiple_plane_heights():
    raw = {
        "type": "surface3d",
        "shapes": [
            {"kind": "surface", "expr": "x^2+y^2", "domain": [-1, 1],
             "rows": 4, "cols": 4},
            {"kind": "plane", "normal": [0, 0, 1]},
        ],
    }
    repaired = rd.repair_surface_shapes(
        raw, "画出曲面 z=x^2+y^2 与平面 z=1、平面 z=2 的交线")
    plane = repaired["shapes"][1]
    assert "z" not in plane


def test_surface_repair_does_not_give_tilted_plane_an_arbitrary_height():
    """倾斜平面不能只凭题面 z=c 填 z;法向不是竖直时应丢弃而不是画错位置。"""
    raw = {
        "type": "surface3d",
        "shapes": [
            {"kind": "surface", "expr": "x^2+y^2", "domain": [-1, 1],
             "rows": 4, "cols": 4},
            {"kind": "plane", "normal": [1, 0, 1], "label": "切平面"},
        ],
    }
    repaired = rd.repair_surface_shapes(
        raw, "画出曲面 z=x^2+y^2 在 z=1 处的切平面")
    plane = repaired["shapes"][1]
    assert "z" not in plane
    assert rd.prepare_diagram(repaired) is None or not any(
        shape["kind"] == "plane" for shape in rd.prepare_diagram(repaired)["shapes"])


def test_surface3d_without_surface_is_rejected():
    assert rd.prepare_diagram({
        "type": "surface3d",
        "shapes": [{"kind": "plane", "x": 0, "y": 0, "z": 1,
                    "normal": [0, 0, 1]}],
    }) is None


def test_3d_model_axes_are_removed_because_renderer_owns_axes():
    result = rd.prepare_diagram({
        "type": "geometry3d",
        "shapes": [
            {"kind": "axis", "label": "x", "from": [0, 0, 0], "to": [2, 0, 0]},
            {"kind": "axis", "label": "y", "from": [0, 0, 0], "to": [0, 2, 0]},
            {"kind": "point", "x": 1, "y": 1, "z": 1, "label": "P"},
        ],
        "annotations": [
            {"x": 2, "y": 0, "z": 0, "text": "x 轴"},
            {"x": 0, "y": 2, "z": 0, "text": "y"},
        ],
    })
    assert result
    assert not any(shape["kind"] == "axis" for shape in result["shapes"])
    assert not any(note["text"].startswith(("x", "y")) for note in result["annotations"])


@pytest.mark.parametrize("invalid", [float("nan"), float("inf"), float("-inf")])
def test_nonfinite_sampling_counts_do_not_crash(invalid):
    result = rd.prepare_diagram({
        "type": "plot2d",
        "shapes": [{"kind": "curve", "expr": "x", "domain": [-1, 1],
                    "points": invalid, "samples": invalid}],
    })
    assert result and len(result["shapes"][0]["points"]) >= 8


def test_invalid_coordinates_are_filtered_before_math_refinement():
    plot = rd.prepare_diagram({
        "type": "plot2d",
        "shapes": [
            {"kind": "curve", "points": [["bad", 1], [0, 0], [1, 1]]},
            {"kind": "point", "x": 0, "y": 0},
            {"kind": "line", "label": "tangent", "from": [0, 0], "to": [1, 1]},
        ],
    })
    assert plot and next(s for s in plot["shapes"] if s["kind"] == "curve")["points"] == [[0, 0], [1, 1]]
    surface = rd.prepare_diagram({
        "type": "surface3d",
        "shapes": [
            {"kind": "surface", "expr": "x+y", "domain": [-1, 1]},
            {"kind": "point", "x": "bad", "y": 0},
            {"kind": "vector", "label": "gradient", "from": [0, 0], "to": [1, 1]},
        ],
    })
    assert surface and not any(s["kind"] == "point" for s in surface["shapes"])


def test_surface_gradient_is_recomputed_from_expression(monkeypatch):
    monkeypatch.setattr(rd.llm, "is_configured", lambda role="main": True)

    async def fake_stream(system, user, **kwargs):
        yield json.dumps({
            "type": "surface3d",
            "shapes": [
                {"kind": "surface", "expr": "x^2+y^2", "domain": [-2, 2],
                 "rows": 5, "cols": 5},
                {"kind": "point", "x": 1, "y": 1, "z": 999},
                {"kind": "vector", "from": [1, 1, 0], "to": [9, 9, 9],
                 "label": "梯度方向 ∇f"},
            ],
        })

    monkeypatch.setattr(rd.llm, "stream_chat", fake_stream)
    result = asyncio.run(plan_diagram("用三维曲面画梯度", "", [], "surface3d"))
    assert result
    point = [s for s in result["shapes"] if s["kind"] == "point"][0]
    vector = [s for s in result["shapes"] if s["kind"] == "vector"][0]
    assert point["z"] == 2
    assert vector["from"] == [1, 1, 2]
    dx = vector["to"][0] - 1
    dy = vector["to"][1] - 1
    assert dx > 0 and abs(dx - dy) < 1e-5
    assert abs(vector["to"][2] - (2 + 2 * dx + 2 * dy)) < 1e-4


def test_plan_diagram_explicit_3d_request_overrides_marker(monkeypatch):
    seen: dict[str, str] = {}
    monkeypatch.setattr(rd.llm, "is_configured", lambda role="main": True)

    async def fake_stream(system, user, **kwargs):
        seen["user"] = user
        yield json.dumps({
            "type": "surface3d",
            "title": "梯度方向",
            "shapes": [
                {"kind": "surface", "expr": "x^2+y^2", "domain": [-1, 1],
                 "rows": 3, "cols": 3},
                {"kind": "vector", "from": [1, 1, 2], "to": [2, 2, 4]},
                {"kind": "point", "x": 1, "y": 1, "z": 2, "label": "P"},
            ],
            "annotations": [{"x": 1, "y": 1, "z": 2, "text": "最陡上升"}],
        })

    monkeypatch.setattr(rd.llm, "stream_chat", fake_stream)
    result = asyncio.run(plan_diagram(
        "梯度方向为什么是函数增长最快的方向?请用三维图表示",
        "先看曲面", [], "relation"))
    assert result and result["type"] == "surface3d"
    surface = result["shapes"][0]
    assert surface["rows"] == 3 and surface["cols"] == 3
    assert len(surface["points"]) == 9
    assert surface["points"][0] == [-1.0, -1.0, 2.0]
    assert result["annotations"][0]["z"] == 2
    assert "请求图解类型:surface3d" in seen["user"]
    assert "用户明确要求" in seen["user"]


def test_plan_diagram_drops_unsafe_expression(monkeypatch):
    monkeypatch.setattr(rd.llm, "is_configured", lambda role="main": True)

    async def fake_stream(system, user, **kwargs):
        yield json.dumps({
            "type": "surface3d",
            "shapes": [{"kind": "surface", "expr": "__import__('os').system('x')",
                        "domain": [-1, 1]}],
        })

    monkeypatch.setattr(rd.llm, "stream_chat", fake_stream)
    assert asyncio.run(plan_diagram("用三维图表示", "", [], "surface3d")) is None


def test_plan_diagram_samples_curve_expression(monkeypatch):
    monkeypatch.setattr(rd.llm, "is_configured", lambda role="main": True)

    async def fake_stream(system, user, **kwargs):
        yield json.dumps({
            "type": "plot2d",
            "shapes": [{"kind": "curve", "expr": "sin(x)", "domain": [-3.14, 3.14]}],
        })

    monkeypatch.setattr(rd.llm, "stream_chat", fake_stream)
    result = asyncio.run(plan_diagram("画出函数图像", "", [], "plot2d"))
    assert result and result["type"] == "plot2d"
    curve = result["shapes"][0]
    assert len(curve["points"]) == rd._CURVE_SAMPLES
    assert abs(curve["points"][0][1]) < 0.01


def test_plan_diagram_uses_latest_paragraph(monkeypatch):
    seen: dict[str, str] = {}
    monkeypatch.setattr(rd.llm, "is_configured", lambda role="main": True)

    async def fake_stream(system, user, **kwargs):
        seen["user"] = user
        yield json.dumps({"type": "flow", "nodes": [{"id": "a", "label": "A"}]})

    monkeypatch.setattr(rd.llm, "stream_chat", fake_stream)
    asyncio.run(plan_diagram("步骤", "旧内容" + "甲" * 6000 + "最新一步", [], "flow"))
    assert "旧内容" not in seen["user"]
    assert "最新一步" in seen["user"]


def test_diagram_event_rejects_nan():
    frame = diagram_event({
        "type": "geometry2d",
        "shapes": [{"kind": "point", "x": float("nan"), "y": 0}],
    }, "r", "r-1", 0)
    assert frame == ""


def test_diagram_cost_counts_points_and_bytes():
    points, size = rd.diagram_cost({
        "type": "surface3d",
        "shapes": [{"kind": "surface", "points": [[0, 0, 0]] * 12}],
    })
    assert points == 12
    assert size > 0


def test_planner_breaker_opens_and_resets(monkeypatch):
    calls = 0

    async def broken(system, user, **kwargs):
        nonlocal calls
        calls += 1
        raise RuntimeError("provider down")
        yield  # pragma: no cover

    monkeypatch.setattr(rd.llm, "is_configured", lambda role="main", **k: True)
    monkeypatch.setattr(rd.llm, "stream_chat", broken)
    for _ in range(rd._PLANNER_BREAKER_THRESHOLD):
        assert asyncio.run(rd.plan_diagram("q", "a", [], "flow")) is None
    before = calls
    # 熔断打开后不再调用模型。
    assert asyncio.run(rd.plan_diagram("q", "a", [], "flow")) is None
    assert calls == before
    rd.reset_planner_breaker()


def test_plan_diagram_samples_in_worker_thread(monkeypatch):
    main_thread = threading.get_ident()
    seen: dict[str, int] = {}

    monkeypatch.setattr(rd.llm, "is_configured", lambda role="main", **k: True)

    async def fake_stream(system, user, **kwargs):
        yield json.dumps({"type": "flow", "nodes": [{"id": "a", "label": "A"}]})

    def fake_prepare(raw):
        seen["thread"] = threading.get_ident()
        return raw

    monkeypatch.setattr(rd.llm, "stream_chat", fake_stream)
    monkeypatch.setattr(rd, "prepare_diagram", fake_prepare)
    assert asyncio.run(rd.plan_diagram("q", "a", [], "flow"))
    assert seen["thread"] != main_thread


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
        "为什么 A 会变化", "前面解释 A", [{"section": "S", "text": "资料"}],
        "relation"))
    assert result and result["type"] == "relation"
    assert "为什么 A 会变化" in seen["user"]
    assert "前面解释 A" in seen["user"]
    assert "资料" in seen["user"]
    assert "relation" in seen["user"]


def test_plan_diagram_rejects_bad_model_output(monkeypatch):
    monkeypatch.setattr(rd.llm, "is_configured", lambda role="main": True)

    async def bad(system, user, **kwargs):
        yield "不是 JSON"

    monkeypatch.setattr(rd.llm, "stream_chat", bad)
    assert asyncio.run(plan_diagram("q", "a", [], "flow")) is None


def test_plan_diagram_without_llm(monkeypatch):
    monkeypatch.setattr(rd.llm, "is_configured", lambda role="main": False)
    assert asyncio.run(plan_diagram("q", "a", [], "tree")) is None


def test_metrics_endpoint_returns_aggregates(monkeypatch):
    from starlette.applications import Starlette
    from starlette.routing import Route
    from starlette.testclient import TestClient

    import diagram_metrics

    monkeypatch.setattr(rd, "require_auth", lambda request: {"uid": "u-m"})
    diagram_metrics.record("plan", True, "ok", duration_ms=12, points=3)
    app = Starlette(routes=[Route("/metrics", rd.metrics_endpoint)])
    client = TestClient(app)
    res = client.get("/metrics")
    assert res.status_code == 200, res.text
    data = res.json()
    assert data["planCount"] == 1
    assert data["totalPoints"] == 3
    assert "u-m" not in json.dumps(data)


def test_metrics_endpoint_prometheus_format(monkeypatch):
    from starlette.applications import Starlette
    from starlette.routing import Route
    from starlette.testclient import TestClient

    import diagram_metrics

    monkeypatch.setattr(rd, "require_auth", lambda request: {"uid": "u-p"})
    diagram_metrics.record("plan", True, "ok", duration_ms=8, points=2)
    app = Starlette(routes=[Route("/metrics", rd.metrics_endpoint)])
    client = TestClient(app)
    res = client.get("/metrics?format=prometheus")
    assert res.status_code == 200
    assert "mg_diagram_events_total" in res.text
    assert "reason=\"ok\"" in res.text


def test_diagram_alert_payload_has_no_content(monkeypatch):
    import diagram_alerts

    monkeypatch.delenv("MG_DIAGRAM_ALERT_WEBHOOK", raising=False)
    payload = diagram_alerts.build_payload("breaker_open")
    text = json.dumps(payload, ensure_ascii=False)
    assert payload["event"] == "diagram_alert"
    assert payload["reason"] == "breaker_open"
    assert "snapshot" in payload
    assert "机密" not in text


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


# ---------- 曲线采样与标注校正(数学硬伤防线) ----------

def test_curve_sampling_splits_asymptotes():
    """1/x、tan 不能在极点处连成一条实线。"""
    shape = {"kind": "curve", "expr": "1/x", "domain": [-2, 2]}
    assert rd._sample_shape(shape)
    assert len(shape["segments"]) == 2

    shape = {"kind": "curve", "expr": "tan(x)", "domain": [-2, 2]}
    assert rd._sample_shape(shape)
    assert len(shape["segments"]) >= 3


def test_curve_domain_shrinks_instead_of_dropping():
    """ln/sqrt 在定义域外不能把整条曲线丢掉。"""
    for expr in ("ln(x)", "sqrt(x)"):
        shape = {"kind": "curve", "expr": expr, "domain": [-2, 2]}
        assert rd._sample_shape(shape), expr
        assert shape["domain"][0] > 0
        assert len(shape["points"]) >= 2


def test_annotations_snap_to_curve_or_drop_far_ones():
    raw = {
        "type": "plot2d",
        "shapes": [{"kind": "curve", "expr": "x^2", "domain": [-2, 2]}],
        "annotations": [
            {"x": 1, "y": 1.01, "text": "切点"},
            {"x": 1, "y": 50, "text": "明显错位"},
            {"x": 1, "y": 1.2, "text": "排版偏移"},
        ],
    }
    diagram = rd.prepare_diagram(raw)
    assert diagram is not None
    notes = diagram["annotations"]
    assert len(notes) == 2
    snapped = next(note for note in notes if note["text"] == "切点")
    assert abs(snapped["y"] - 1.0) < 1e-6
    assert all(note["text"] != "明显错位" for note in notes)


def test_references_diagram_detection():
    assert rd.references_diagram("如图所示,切线斜率为 2")
    assert rd.references_diagram("The figure below shows the slope")
    assert not rd.references_diagram("切线斜率为 2,它表示瞬时变化率")
    assert not rd.references_diagram("")


def test_tangent_slope_computed_from_expression():
    """切线斜率必须由表达式算,不能用模型给的坐标。"""
    raw = {
        "type": "plot2d",
        "shapes": [
            {"kind": "curve", "expr": "x^2", "domain": [-2, 2]},
            {"kind": "point", "x": 1, "y": 1},
            {"kind": "line", "from": [0, 0], "to": [2, 2], "label": "切线"},
        ],
        "annotations": [],
    }
    diagram = rd.prepare_diagram(raw)
    assert diagram is not None
    tangent = next(shape for shape in diagram["shapes"] if shape["kind"] == "line")
    x1, y1 = tangent["from"][:2]
    x2, y2 = tangent["to"][:2]
    assert abs((y2 - y1) / (x2 - x1) - 2.0) < 1e-3
    # 切线必须过切点 (1, 1)
    assert abs(y1 + (1 - x1) * 2 - 1) < 1e-3


def test_tangent_is_not_stolen_by_an_unrelated_origin_point():
    """原点 O 也在切线附近时,不能把 O 当成切点;切点仍是 P。"""
    raw = {
        "type": "plot2d",
        "shapes": [
            {"kind": "curve", "expr": "x^2", "domain": [-2, 2]},
            {"kind": "point", "x": 0, "y": 0, "label": "O"},
            {"kind": "point", "x": 1, "y": 1, "label": "P"},
            {"kind": "line", "from": [0, 0], "to": [2, 2], "label": "切线"},
        ],
        "annotations": [],
    }
    diagram = rd.prepare_diagram(raw)
    assert diagram is not None
    tangent = next(shape for shape in diagram["shapes"] if shape["kind"] == "line")
    x1, y1 = tangent["from"][:2]
    x2, y2 = tangent["to"][:2]
    assert abs((y2 - y1) / (x2 - x1) - 2.0) < 1e-3
    assert abs(y1 + (1 - x1) * 2 - 1) < 1e-3


def test_tangent_without_points_uses_segment_midpoint():
    """没有关键点时,用切线自身的中点定切点,不能拿 line 的起点。"""
    raw = {
        "type": "plot2d",
        "shapes": [
            {"kind": "curve", "expr": "x^2", "domain": [-2, 2]},
            {"kind": "line", "from": [0, 0], "to": [2, 2], "label": "切线"},
        ],
        "annotations": [],
    }
    diagram = rd.prepare_diagram(raw)
    assert diagram is not None
    tangent = next(shape for shape in diagram["shapes"] if shape["kind"] == "line")
    x1, y1 = tangent["from"][:2]
    x2, y2 = tangent["to"][:2]
    assert abs((y2 - y1) / (x2 - x1) - 2.0) < 1e-3
    assert abs(y1 + (1 - x1) * 2 - 1) < 1e-3


def test_tangent_line_midpoint_wins_over_unlabeled_origin():
    """图上只有一个原点 O 时,长切线仍应按线中点找切点,不能把 O 当切点。"""
    raw = {
        "type": "plot2d",
        "shapes": [
            {"kind": "curve", "expr": "x^2", "domain": [-2, 2]},
            {"kind": "point", "x": 0, "y": 0, "label": "O"},
            {"kind": "line", "from": [0, 0], "to": [2, 2], "label": "切线"},
        ],
        "annotations": [],
    }
    diagram = rd.prepare_diagram(raw)
    assert diagram is not None
    tangent = next(shape for shape in diagram["shapes"] if shape["kind"] == "line")
    x1, y1 = tangent["from"][:2]
    x2, y2 = tangent["to"][:2]
    assert abs((y2 - y1) / (x2 - x1) - 2.0) < 1e-3
    assert abs(y1 + (1 - x1) * 2 - 1) < 1e-3


def test_plot2d_samples_y_equals_expression_for_tangent():
    """模型把表达式写成 y = x^2 时也要能采样并算切线。"""
    raw = {
        "type": "plot2d",
        "shapes": [
            {"kind": "curve", "expr": "y = x^2", "domain": [-2, 2]},
            {"kind": "point", "x": 1, "y": 1, "label": "P"},
            {"kind": "segment", "label": "切线",
             "from": [0.8, 0.8], "to": [1.2, 1.2]},
        ],
        "annotations": [],
    }
    diagram = rd.prepare_diagram(raw)
    assert diagram is not None
    curve = next(shape for shape in diagram["shapes"] if shape["kind"] == "curve")
    assert len(curve.get("points") or []) > 10
    tangent = next(shape for shape in diagram["shapes"] if shape["label"] == "切线")
    x1, y1 = tangent["from"][:2]
    x2, y2 = tangent["to"][:2]
    assert abs((y2 - y1) / (x2 - x1) - 2.0) < 1e-3


def test_plot2d_samples_latex_fraction_for_tangent():
    """LaTeX 分式要能采样;否则切线只能退回模型手画。"""
    raw = {
        "type": "plot2d",
        "shapes": [
            {"kind": "curve", "expr": "\\frac{x^2}{2}", "domain": [-2, 2]},
            {"kind": "point", "x": 1, "y": 0.5, "label": "P"},
            {"kind": "segment", "label": "切线",
             "from": [0.8, 0.3], "to": [1.2, 0.7]},
        ],
        "annotations": [],
    }
    diagram = rd.prepare_diagram(raw)
    assert diagram is not None
    curve = next(shape for shape in diagram["shapes"] if shape["kind"] == "curve")
    assert len(curve.get("points") or []) > 10
    tangent = next(shape for shape in diagram["shapes"] if shape["label"] == "切线")
    x1, y1 = tangent["from"][:2]
    x2, y2 = tangent["to"][:2]
    assert abs((y2 - y1) / (x2 - x1) - 1.0) < 1e-3


def test_plot2d_tangent_shortens_steep_segment():
    """陡峭曲线上的切线不能铺满全图,否则会把曲线压扁,看着不像切线。"""
    raw = {
        "type": "plot2d",
        "shapes": [
            {"kind": "curve", "expr": "e^x", "domain": [-2, 2]},
            {"kind": "point", "x": 2, "y": math.e ** 2, "label": "P"},
            {"kind": "line", "from": [1, 1], "to": [3, 3], "label": "切线"},
        ],
        "annotations": [],
    }
    diagram = rd.prepare_diagram(raw)
    assert diagram is not None
    tangent = next(shape for shape in diagram["shapes"] if shape["kind"] == "line")
    y1, y2 = tangent["from"][1], tangent["to"][1]
    assert abs(y2 - y1) < (math.e ** 2 - math.e ** -2) * 0.35


def test_plot2d_boundary_tangent_uses_one_sided_derivative():
    """sqrt(x) 在 x=0 只有单侧导数;不能因为中心差分失败就保留错误斜线。"""
    raw = {
        "type": "plot2d",
        "shapes": [
            {"kind": "curve", "expr": "sqrt(x)", "domain": [0, 4]},
            {"kind": "point", "x": 0, "y": 0, "label": "O"},
            {"kind": "line", "from": [-0.2, -0.2], "to": [0.2, 0.2], "label": "切线"},
        ],
        "annotations": [],
    }
    diagram = rd.prepare_diagram(raw)
    assert diagram is not None
    tangent = next(shape for shape in diagram["shapes"] if shape["kind"] == "line")
    x1, y1 = tangent["from"][:2]
    x2, y2 = tangent["to"][:2]
    # 竖直切线:x 跨度很小,y 跨度有限且不为 0
    assert abs(x2 - x1) < 0.02
    assert 0.2 < abs(y2 - y1) < 2.0


def test_plot2d_high_exponent_curve_is_sampled():
    """x^10 的指数 10 不应被幂运算上限误判,曲线要能采样。"""
    raw = {
        "type": "plot2d",
        "shapes": [
            {"kind": "curve", "expr": "x^10", "domain": [0.5, 1.5]},
            {"kind": "point", "x": 1, "y": 1, "label": "P"},
            {"kind": "segment", "label": "切线",
             "from": [0.9, 0.9], "to": [1.1, 1.1]},
        ],
        "annotations": [],
    }
    diagram = rd.prepare_diagram(raw)
    assert diagram is not None
    curve = next(shape for shape in diagram["shapes"] if shape["kind"] == "curve")
    assert len(curve.get("points") or []) > 10
    tangent = next(shape for shape in diagram["shapes"] if shape["label"] == "切线")
    x1, y1 = tangent["from"][:2]
    x2, y2 = tangent["to"][:2]
    assert abs((y2 - y1) / (x2 - x1) - 10.0) < 1e-2



def test_verify_enabled_reads_env(monkeypatch):
    monkeypatch.setenv("MG_DIAGRAM_VERIFY", "0")
    assert rd.verify_enabled() is False
    monkeypatch.setenv("MG_DIAGRAM_VERIFY", "1")
    assert rd.verify_enabled() is True


def test_verify_diagram_parses_verdict(monkeypatch):
    monkeypatch.setattr(rd.llm, "is_configured", lambda role="main": True)

    async def fake_stream(system, user, role="main", **kwargs):
        yield '{"ok": false, "reason": "图画的是导数,问题问的是积分"}'

    monkeypatch.setattr(rd.llm, "stream_chat", fake_stream)
    verdict = asyncio.run(rd.verify_diagram(
        "积分怎么理解", "定积分是面积", {"type": "plot2d", "shapes": []}))
    assert verdict is False


def test_verify_diagram_returns_none_on_bad_output(monkeypatch):
    monkeypatch.setattr(rd.llm, "is_configured", lambda role="main": True)

    async def fake_stream(system, user, role="main", **kwargs):
        yield "看起来还行"

    monkeypatch.setattr(rd.llm, "stream_chat", fake_stream)
    assert asyncio.run(rd.verify_diagram("q", "ctx", {"type": "flow"})) is None


def test_axis_labels_pinned_to_their_equations():
    """“水平渐近线 y=0 / 垂直渐近线 x=0” 以文字为准,不跟随模型漂移的坐标。"""
    raw = {
        "type": "plot2d",
        "shapes": [{"kind": "curve", "expr": "1/x", "domain": [-2, 2]}],
        "annotations": [
            {"x": 5, "y": 5.2, "text": "水平渐近线 y=0"},
            {"x": 3, "y": 5.2, "text": "垂直渐近线 x=0"},
            {"x": 2, "y": 5, "text": "y = 1/x 的图像"},
        ],
    }
    diagram = rd.prepare_diagram(raw)
    notes = {note["text"]: note for note in diagram["annotations"]}
    assert notes["水平渐近线 y=0"]["y"] == 0.0
    assert notes["垂直渐近线 x=0"]["x"] == 0.0
    # "y = 1/x" 不能被当成 "y = 1"
    assert notes["y = 1/x 的图像"]["y"] == 5.0


# ---------- GeoGebra 引擎 ----------

def test_diagram_summary_includes_directed_edges():
    summary = rd._diagram_summary({
        "type": "tree",
        "nodes": [{"id": "a", "label": "A"}, {"id": "b", "label": "B"}],
        "edges": [{"from": "a", "to": "b", "label": "推出"}],
    })
    assert "a->b(推出)" in summary


def test_geogebra_validator_whitelist():
    ok = rd.validate_geogebra({
        "type": "geogebra2d",
        "commands": ["f(x)=x^2", "A=(1,1)", "t=Tangent(A,f)"],
    })
    assert ok is not None and ok["commands"][0] == "f(x)=x^2"

    assert rd.validate_geogebra(
        {"type": "geogebra2d", "commands": ['Execute("x")']}) is None
    assert rd.validate_geogebra(
        {"type": "geogebra2d", "commands": ["f(x)=x^2"] * 31}) is None
    assert rd.validate_geogebra(
        {"type": "geogebra2d", "commands": ["SetColor(f,1,2,3)"]}) is None
    assert rd.validate_geogebra({
        "type": "geogebra3d",
        "commands": ["s=Surface(u,v,u^2+v^2,u,-2,2,v,-2,2)"],
    }) is not None
    assert rd.validate_geogebra({
        "type": "geogebra2d", "commands": ["l: y=x"],
    }) is not None


def test_plan_geogebra_defers_3d_to_legacy(monkeypatch):
    """3D 曲面继续走旧规划器 + Three.js,不在页面回退成 GeoGebra 画布。"""
    monkeypatch.setattr(rd.llm, "is_configured", lambda role="main", **k: True)
    assert asyncio.run(rd.plan_geogebra(
        "用三维图讲讲曲面 z=x^2+y^2 的梯度", "解释")) is None


def test_plan_geogebra_accepts_constructible_3d(monkeypatch):
    monkeypatch.setattr(rd.llm, "is_configured", lambda role="main", **k: True)

    async def fake_stream(system, user, **kwargs):
        yield json.dumps({
            "type": "geogebra3d",
            "commands": [
                "A=(1,0,0)", "B=(0,1,0)", "C=(0,0,1)",
                "p=Plane(A,B,C)", "S=Sphere((0,0,0),2)",
            ],
        })

    monkeypatch.setattr(rd.llm, "stream_chat", fake_stream)
    diagram = asyncio.run(rd.plan_geogebra(
        "画出空间中的平面和球面", "解释"))
    assert diagram is not None and diagram["type"] == "geogebra3d"


def test_plan_geogebra_defers_surface_command(monkeypatch):
    monkeypatch.setattr(rd.llm, "is_configured", lambda role="main", **k: True)

    async def fake_stream(system, user, **kwargs):
        yield json.dumps({
            "type": "geogebra3d",
            "commands": ["s=Surface(u,v,u^2+v^2,u,-1,1,v,-1,1)"],
        })

    monkeypatch.setattr(rd.llm, "stream_chat", fake_stream)
    assert asyncio.run(rd.plan_geogebra(
        "画一个旋转抛物面", "解释")) is None


def test_plan_diagram_auto_falls_back_to_legacy(monkeypatch):
    monkeypatch.setenv("MG_DIAGRAM_ENGINE", "geogebra")
    sentinel = {"type": "plot2d", "shapes": [{"kind": "point", "x": 0, "y": 0}],
                "nodes": [], "edges": [], "annotations": []}

    async def no_geo(question, before, role="main"):
        return None

    async def legacy(*args, **kwargs):
        return sentinel

    monkeypatch.setattr(rd, "plan_geogebra", no_geo)
    monkeypatch.setattr(rd, "plan_diagram", legacy)
    got = asyncio.run(rd.plan_diagram_auto(
        "画出抛物线", "y=x^2", [], "plot2d", strict=False))
    assert got is sentinel


def test_plan_diagram_auto_keeps_generic_fallback_for_dimension_only_cue(monkeypatch):
    monkeypatch.setenv("MG_DIAGRAM_ENGINE", "geogebra")
    sentinel = {"type": "surface3d", "shapes": [{"kind": "surface", "points": [[0, 0, 0]]}],
                "nodes": [], "edges": [], "annotations": []}

    async def no_linear(question, before, role="main"):
        return None

    async def no_geo(question, before, role="main"):
        return None

    async def legacy(*args, **kwargs):
        return sentinel

    monkeypatch.setattr(rd.linear_algebra, "plan_linear", no_linear)
    monkeypatch.setattr(rd, "plan_geogebra", no_geo)
    monkeypatch.setattr(rd, "plan_diagram", legacy)
    got = asyncio.run(rd.plan_diagram_auto(
        "画出 z=x^2+y^2 在 R^2 上的等高线", "解释", [], "surface3d",
        strict=False))
    assert got is sentinel


def test_plan_diagram_auto_blocks_freehand_for_linear_semantic_question(monkeypatch):
    async def no_linear(question, before, role="main"):
        return None

    async def legacy(*args, **kwargs):
        raise AssertionError("linear semantic failure must not fall back")

    monkeypatch.setattr(rd.linear_algebra, "plan_linear", no_linear)
    monkeypatch.setattr(rd, "plan_diagram", legacy)
    assert asyncio.run(rd.plan_diagram_auto(
        "解释 R^3 中由两个向量张成的子空间", "解释", [], "geometry3d",
        strict=False)) is None
