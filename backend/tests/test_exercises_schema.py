"""习题 schema:字段校验、双语内容、交叉知识点与哈希。"""
from __future__ import annotations

import pytest

from exercises import schema


def make(**overrides):
    data = {
        "id": "test:1",
        "source": {
            "name": "Test",
            "tier": "safe",
            "license": "MIT",
            "url": "https://example.com/source",
            "attribution": "Test Source",
        },
        "original_language": "en",
        "content": {
            "en": {
                "question": "Compute the value of 1 + 1.",
                "answer": "2",
                "solution": "1 + 1 = 2, so the final answer is 2.",
            }
        },
        "type": "compute",
        "difficulty": 1,
        "difficulty_source": "source",
        "primary_topic": "analysis",
        "topics": ["analysis"],
        "cross_topics": [],
        "tag_source": "rule",
        "quality": {
            "gate_version": 1,
            "answer_in_solution": True,
            "latex_ok": True,
            "ocr_ok": True,
            "manual_review": "passed",
        },
    }
    data.update(overrides)
    return data


def test_parse_valid_exercise_round_trips():
    exercise = schema.parse_exercise(make())

    assert exercise.id == "test:1"
    assert exercise.available_languages == ("en",)
    assert exercise.source.tier == "safe"
    assert exercise.source.license_scope == "dataset"
    assert exercise.content["en"].translation.status == "native"
    assert exercise.hash.startswith("sha256:")

    again = schema.parse_exercise(exercise.to_dict())
    assert again.to_dict() == exercise.to_dict()


def test_non_original_language_defaults_to_machine_translation():
    data = make()
    data["content"]["zh"] = {
        "question": "计算 1 + 1 的值。",
        "answer": "2",
        "solution": "1 + 1 = 2,所以最终答案是 2。",
    }

    exercise = schema.parse_exercise(data)

    assert exercise.available_languages == ("en", "zh")
    assert exercise.content["zh"].translation.status == "machine"
    assert exercise.content["zh"].translation.reviewed is False


def test_rejects_missing_id():
    data = make()
    del data["id"]

    with pytest.raises(schema.SchemaError, match="id"):
        schema.parse_exercise(data)


def test_rejects_unknown_tier():
    data = make()
    data["source"]["tier"] = "public"

    with pytest.raises(schema.SchemaError, match="tier"):
        schema.parse_exercise(data)


def test_rejects_incomplete_language_block():
    data = make()
    del data["content"]["en"]["answer"]

    with pytest.raises(schema.SchemaError, match="answer"):
        schema.parse_exercise(data)


def test_rejects_unknown_topic():
    data = make(topics=["analysis", "astrology"], primary_topic="analysis")

    with pytest.raises(schema.SchemaError, match="topic"):
        schema.parse_exercise(data)


def test_rejects_unknown_cross_topic():
    data = make(cross_topics=["not-a-real-cross-topic"])

    with pytest.raises(schema.SchemaError, match="cross"):
        schema.parse_exercise(data)


def test_rejects_primary_topic_outside_topics():
    data = make(topics=["algebra"], primary_topic="analysis")

    with pytest.raises(schema.SchemaError, match="primary"):
        schema.parse_exercise(data)


def test_rejects_invalid_difficulty_and_type():
    with pytest.raises(schema.SchemaError, match="difficulty"):
        schema.parse_exercise(make(difficulty=7))
    with pytest.raises(schema.SchemaError, match="type"):
        schema.parse_exercise(make(type="essay"))


def test_rejects_invalid_translation_status():
    data = make()
    data["content"]["en"]["translation"] = {"status": "guess"}

    with pytest.raises(schema.SchemaError, match="translation"):
        schema.parse_exercise(data)


def test_question_hash_ignores_case_and_whitespace():
    left = schema.question_hash("  Compute   1 + 1.  ")
    right = schema.question_hash("compute 1+1.")

    assert left == right
    assert left != schema.question_hash("Compute 2 + 2.")


def test_blocked_tier_is_valid_at_schema_level():
    data = make()
    data["source"]["tier"] = "blocked"

    exercise = schema.parse_exercise(data)

    assert exercise.source.tier == "blocked"
