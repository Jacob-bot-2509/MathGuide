"""习题质量门:题干、答案、完整过程、LaTeX、OCR 与来源许可。"""
from __future__ import annotations

from dataclasses import replace

from exercises import schema
from exercises.gate import gate_exercise


def make(**overrides):
    data = {
        "id": "gate:1",
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
                "question": "Compute the exact value of the following integral.",
                "answer": "2",
                "solution": (
                    "We split the integral into two symmetric parts. "
                    "Each part evaluates to 1, therefore the total is 2."
                ),
            }
        },
        "type": "compute",
        "difficulty": 2,
        "difficulty_source": "source",
        "primary_topic": "analysis",
        "topics": ["analysis"],
        "cross_topics": [],
        "tag_source": "rule",
        "quality": {
            "gate_version": 1,
            "answer_in_solution": False,
            "latex_ok": False,
            "ocr_ok": False,
            "manual_review": "pending",
        },
    }
    data.update(overrides)
    return schema.parse_exercise(data)


def test_valid_exercise_passes_and_records_quality():
    result = gate_exercise(make())

    assert result.accepted is True
    assert result.reasons == ()
    quality = result.to_quality()
    assert quality["gate_version"] == 1
    assert quality["answer_in_solution"] is True
    assert quality["latex_ok"] is True
    assert quality["ocr_ok"] is True
    assert quality["manual_review"] == "pending"


def test_short_question_is_rejected():
    exercise = make(content={
        "en": {
            "question": "Find 1+1.",
            "answer": "2",
            "solution": "One plus one equals two, therefore the answer is exactly 2.",
        }
    })

    result = gate_exercise(exercise)

    assert result.accepted is False
    assert "question_too_short" in result.reasons


def test_short_solution_is_rejected():
    exercise = make(content={
        "en": {
            "question": "Compute the exact value of the following integral.",
            "answer": "2",
            "solution": "It is 2.",
        }
    })

    result = gate_exercise(exercise)

    assert result.accepted is False
    assert "solution_too_short" in result.reasons


def test_solution_equal_to_answer_is_rejected():
    exercise = make(content={
        "en": {
            "question": "Compute the exact value of the following integral.",
            "answer": "2",
            "solution": "2",
        }
    })

    result = gate_exercise(exercise)

    assert result.accepted is False
    assert "solution_equals_answer" in result.reasons


def test_answer_missing_from_solution_is_rejected():
    exercise = make(content={
        "en": {
            "question": "Compute the exact value of the following integral.",
            "answer": "7",
            "solution": "We split the integral and obtain the value 2 after simplification.",
        }
    })

    result = gate_exercise(exercise)

    assert result.accepted is False
    assert "answer_not_in_solution" in result.reasons


def test_proof_with_conclusion_marker_and_long_solution_passes():
    exercise = make(
        type="proof",
        content={
            "en": {
                "question": "Prove that the sum of two even integers is even.",
                "answer": "证明见解析",
                "solution": (
                    "Let the two even integers be 2a and 2b for integers a and b. "
                    "Their sum is 2a + 2b = 2(a + b). Since a + b is an integer, "
                    "the sum is divisible by 2 and is therefore even. 证毕。"
                ),
            }
        },
    )

    result = gate_exercise(exercise)

    assert result.accepted is True
    assert result.reasons == ()


def test_proof_marker_with_short_solution_is_rejected():
    exercise = make(
        type="proof",
        content={
            "en": {
                "question": "Prove that the sum of two even integers is even.",
                "answer": "证明见解析",
                "solution": "It is obvious. 证毕。",
            }
        },
    )

    result = gate_exercise(exercise)

    assert result.accepted is False
    assert "solution_too_short" in result.reasons


def test_unbalanced_latex_is_rejected():
    exercise = make(content={
        "en": {
            "question": "Compute the exact value of the following integral.",
            "answer": "2",
            "solution": "We know that $x = 1 and therefore the final value is 2 after substitution.",
        }
    })

    result = gate_exercise(exercise)

    assert result.accepted is False
    assert "latex_unbalanced" in result.reasons


def test_ocr_noise_is_rejected():
    exercise = make(content={
        "en": {
            "question": "Compute the exact value of the following integral.",
            "answer": "2",
            "solution": "�" * 20 + " therefore the final value is 2.",
        }
    })

    result = gate_exercise(exercise)

    assert result.accepted is False
    assert "ocr_noise" in result.reasons


def test_blocked_source_is_rejected():
    exercise = make(source={
        "name": "Blocked",
        "tier": "blocked",
        "license": "unknown",
        "url": "https://example.com/blocked",
        "attribution": "Blocked",
    })

    result = gate_exercise(exercise)

    assert result.accepted is False
    assert "blocked_source" in result.reasons


def test_incomplete_license_is_rejected():
    exercise = make()
    incomplete = replace(exercise.source, attribution="")
    exercise = replace(exercise, source=incomplete)

    result = gate_exercise(exercise)

    assert result.accepted is False
    assert "license_incomplete" in result.reasons


def test_manually_rejected_item_is_rejected():
    exercise = make(quality={
        "gate_version": 1,
        "answer_in_solution": True,
        "latex_ok": True,
        "ocr_ok": True,
        "manual_review": "rejected",
    })

    result = gate_exercise(exercise)

    assert result.accepted is False
    assert "manual_rejected" in result.reasons
