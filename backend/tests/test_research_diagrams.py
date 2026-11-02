"""图解标记流:跨 chunk 剥离、锚点、schema 白名单。"""
from __future__ import annotations

import asyncio
import json
import threading

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
            {"kind": "plane", "label": "tangent", "normal": [1, 0, 1]},
        ],
    })
    assert result
    assert next(s for s in result["shapes"] if s["kind"] == "point")["z"] == 18
    assert not any(s["kind"] == "vector" for s in result["shapes"])
    assert next(s for s in result["shapes"] if s["kind"] == "plane")["normal"] == [0, 0, 1]


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
