"""图解标记流:跨 chunk 剥离、锚点、schema 白名单。"""
from __future__ import annotations

import asyncio
import json

import pytest

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


def test_anchor_counts_text_before_markers_in_same_feed():
    stream = MarkerStream("r1b")
    clean = stream.feed(
        "AAA[[MG_DIAGRAM:relation]]BBB[[MG_DIAGRAM:flow]]CCC")
    assert clean == "AAABBBCCC"
    markers = stream.drain()
    assert [m.anchor_index for m in markers] == [3, 6]


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
    assert len(curve["points"]) == 80
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
