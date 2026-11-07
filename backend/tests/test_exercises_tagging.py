"""交叉知识点标注:中英术语命中、多个标签与去重。"""
from __future__ import annotations

from dataclasses import replace

from exercises import schema
from exercises.tagging import apply_tags, tag_cross_topics


def make_exercise(**overrides):
    data = {
        "id": "tag:1",
        "source": {
            "name": "Test",
            "tier": "research",
            "license": "MIT",
            "url": "https://example.com/source",
            "attribution": "Test",
        },
        "original_language": "zh",
        "content": {
            "zh": {
                "question": "用最小二乘回归拟合数据。",
                "answer": "2",
                "solution": "最小二乘回归得到系数 2,所以答案是 2。",
            }
        },
        "type": "compute",
        "difficulty": 2,
        "difficulty_source": "rule",
        "primary_topic": "algebra",
        "topics": ["algebra"],
        "cross_topics": [],
        "tag_source": "rule",
    }
    data.update(overrides)
    return schema.parse_exercise(data)


def test_chinese_term_is_tagged():
    assert tag_cross_topics("用最小二乘回归拟合数据") == ("least-squares",)


def test_english_term_is_tagged_case_insensitively():
    assert tag_cross_topics("Apply the Least Squares estimator") == ("least-squares",)


def test_multiple_cross_topics_are_detected_in_registry_order():
    tags = tag_cross_topics("特征值与常微分方程组;再用傅里叶变换")

    assert tags == ("eigen", "fourier-transform", "ode-system")


def test_unrelated_text_returns_empty():
    assert tag_cross_topics("计算 1 + 1 的值") == ()


def test_apply_tags_updates_cross_topics_without_mutating_original():
    exercise = make_exercise()
    tagged = apply_tags(exercise)

    assert tagged.cross_topics == ("least-squares",)
    assert tagged.tag_source == "rule"
    assert exercise.cross_topics == ()
    assert tagged.primary_topic == exercise.primary_topic


def test_apply_tags_uses_solution_text_too():
    exercise = make_exercise(content={
        "zh": {
            "question": "求这个积分。",
            "answer": "2",
            "solution": "用留数定理计算该积分,得到 2。",
        }
    })

    tagged = apply_tags(exercise)

    assert tagged.cross_topics == ("residue",)
