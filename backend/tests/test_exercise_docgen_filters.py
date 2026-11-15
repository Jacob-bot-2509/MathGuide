"""exercise_docgen:从自由描述里推断筛选条件。

组卷请求里 `requirement` 是一句人话("来点难题""中等难度""和线性代数交叉"),
`difficulty`/`count` 是前端可能传脏的结构体。这些映射一旦错,老师要的"难题"
会变成简单题 —— 属于静默的业务错误,不会报错。
"""
from __future__ import annotations

import exercise_docgen as ed


def test_requirement_infers_hard_and_medium_and_easy_difficulty():
    assert ed._requirement_filters("出几道难题")["difficulty"] == (4, 5)
    assert ed._requirement_filters("中等难度")["difficulty"] == (3, 3)
    assert ed._requirement_filters("简单一点的")["difficulty"] == (1, 2)
    # 什么都没说 → 不限难度
    assert ed._requirement_filters("随便来几道")["difficulty"] is None


def test_requirement_collects_types_and_cross_topics_without_duplicates():
    result = ed._requirement_filters("证明题加计算题,和线性代数、概率论交叉")
    assert "proof" in result["types"] or result["types"]
    assert len(result["types"]) == len(set(result["types"]))
    assert len(result["cross_topics"]) == len(set(result["cross_topics"]))


def test_filters_prefer_explicit_fields_and_clamp_difficulty():
    filters = ed._filters({"difficulty": ["0", "9"], "count": 3})
    assert filters["difficulty"] == (1, 5)     # 夹到 1..5


def test_filters_fall_back_when_difficulty_is_malformed():
    assert ed._filters({"difficulty": ["x", "y"]})["difficulty"] == (1, 5)
    # 长度不是 2 也不当结构体处理
    assert ed._filters({"difficulty": [3]})["difficulty"] == (1, 5)


def test_filters_fall_back_when_count_is_not_a_number():
    assert ed._filters({"count": "abc"})["count"] == 20
    assert ed._filters({"count": 0})["count"] == 1
    assert ed._filters({"count": 10 ** 6})["count"] == ed.MAX_COUNT


def test_filters_infer_from_requirement_when_fields_missing():
    filters = ed._filters({"requirement": "中等难度的证明题"})
    assert filters["difficulty"] == (3, 3)
    assert filters["types"]
