"""Phase 2 导入器:行解析、字段映射、图片/证明/无效题跳过。"""
from __future__ import annotations

import pytest

from exercises.importers import math_dataset, numinamath, olympiadbench
from exercises.importers.common import ImportSkip


def olympiad_row(**overrides):
    row = {
        "id": 2400,
        "question": (
            "计算函数 $f(x)=x^2$ 在区间 $[0,2]$ 上的定积分,并给出精确值。"
            "请写出换元或原函数步骤。"
        ),
        "final_answer": ["$\\frac{8}{3}$"],
        "solution": [
            "由定积分定义,$\\int_0^2 x^2 dx = \\frac{x^3}{3}\\big|_0^2 "
            "= \\frac{8}{3}$,所以最终结果是 $\\frac{8}{3}$。"
        ],
        "question_type": "Open-ended",
        "difficulty": "Chinese College Entrance Exam",
        "language": "Chinese",
        "subfield": "Derivative",
        "modality": "Text only",
        "is_multiple_answer": False,
        "image_1": None,
    }
    row.update(overrides)
    return row


def math_row(**overrides):
    row = {
        "problem": "Find the exact value of the sum $2+2$.",
        "solution": (
            "We add the two numbers directly: $2+2=4$. "
            "Therefore the final answer is $\\boxed{4}$."
        ),
        "type": "Algebra",
        "level": "Level 4",
    }
    row.update(overrides)
    return row


def numina_row(**overrides):
    row = {
        "problem": "What is the value of 3 + 4? Show the result clearly.",
        "answer": "7",
        "solution": (
            "Adding three and four gives seven. We can verify by counting "
            "three steps from four, so the final answer is 7."
        ),
        "problem_type": "Algebra",
        "question_type": "MCQ",
        "source": "cn_k12",
        "problem_is_valid": "Yes",
        "solution_is_valid": "Yes",
        "synthetic": False,
    }
    row.update(overrides)
    return row


def test_olympiadbench_text_only_open_ended_is_imported():
    exercise = olympiadbench.parse_row(olympiad_row(), config="OE_TO_maths_zh_CEE")

    assert exercise.id.startswith("olympiadbench:OE_TO_maths_zh_CEE:")
    assert exercise.original_language == "zh"
    assert exercise.available_languages == ("zh",)
    assert exercise.type == "compute"
    assert exercise.difficulty == 3
    assert exercise.difficulty_source == "rule"
    assert exercise.primary_topic == "analysis"
    assert exercise.source.tier == "research"
    assert exercise.source.license == "Apache-2.0"
    assert exercise.source.license_scope == "dataset"
    assert exercise.quality["answer_in_solution"] is True


def test_olympiadbench_multimodal_is_skipped():
    with pytest.raises(ImportSkip, match="image"):
        olympiadbench.parse_row(
            olympiad_row(modality="Multimodal", question="如图, 计算面积。 <image_1>"),
            config="OE_MM_maths_zh_CEE",
        )


def test_olympiadbench_proof_is_skipped():
    with pytest.raises(ImportSkip, match="proof"):
        olympiadbench.parse_row(
            olympiad_row(question_type="Theorem proof", final_answer=None),
            config="TP_TO_maths_zh_CEE",
        )


def test_olympiadbench_missing_answer_is_skipped():
    with pytest.raises(ImportSkip, match="answer"):
        olympiadbench.parse_row(olympiad_row(final_answer=[]), config="OE_TO_maths_zh_CEE")


def test_math_extracts_boxed_answer_and_level():
    exercise = math_dataset.parse_row(math_row(), config="algebra")

    assert exercise.id.startswith("math:algebra:")
    assert exercise.original_language == "en"
    assert exercise.content["en"].answer == "4"
    assert exercise.type == "compute"
    assert exercise.difficulty == 4
    assert exercise.primary_topic == "algebra"
    assert exercise.source.license == "MIT"
    assert exercise.quality["answer_in_solution"] is True


def test_math_without_boxed_answer_is_skipped():
    with pytest.raises(ImportSkip, match="answer"):
        math_dataset.parse_row(
            math_row(solution="The answer is 4, but there is no boxed marker here."),
            config="algebra",
        )


def test_numinamath_mcq_is_imported():
    exercise = numinamath.parse_row(numina_row(), index=3)

    assert exercise.id.startswith("numinamath:cn_k12:")
    assert exercise.original_language == "en"
    assert exercise.type == "choice"
    assert exercise.difficulty == 2
    assert exercise.primary_topic == "algebra"
    assert exercise.source.tier == "research"
    assert exercise.source.license == "Apache-2.0"
    assert exercise.quality["answer_in_solution"] is True


def test_numinamath_word_problem_maps_to_apply():
    exercise = numinamath.parse_row(
        numina_row(source="cn_contest", question_type="math-word-problem", problem_type="Geometry"),
        index=4,
    )

    assert exercise.type == "apply"
    assert exercise.difficulty == 4
    assert exercise.primary_topic == "geometry"


def test_numinamath_invalid_problem_is_skipped():
    with pytest.raises(ImportSkip, match="valid"):
        numinamath.parse_row(numina_row(problem_is_valid="No"), index=5)


def test_numinamath_unknown_source_is_skipped():
    with pytest.raises(ImportSkip, match="source"):
        numinamath.parse_row(numina_row(source="orca_math"), index=6)
