"""构建流程:逐行导入、拒绝原因统计、去重、JSONL 与 manifest 输出。"""
from __future__ import annotations

import json

from exercises.build import build_source
from exercises.store import load_jsonl


def math_row(problem: str, answer: int = 4) -> dict:
    return {
        "problem": problem,
        "solution": (
            f"We add the two numbers directly: $2+2={answer}$. "
            f"Therefore the final answer is $\\boxed{{{answer}}}$."
        ),
        "type": "Algebra",
        "level": "Level 4",
    }


def olympiad_row(question: str = "计算函数 $f(x)=x^2$ 在区间 $[0,2]$ 上的定积分,并写出步骤。") -> dict:
    return {
        "id": 1,
        "question": question,
        "final_answer": ["$\\frac{8}{3}$"],
        "solution": [
            "由定积分定义,$\\int_0^2 x^2 dx = \\frac{x^3}{3}\\big|_0^2 "
            "= \\frac{8}{3}$,所以结果是 $\\frac{8}{3}$。"
        ],
        "question_type": "Open-ended",
        "difficulty": "Competition",
        "language": "Chinese",
        "subfield": "Derivative",
        "modality": "Text only",
        "image_1": None,
    }


def numina_row() -> dict:
    return {
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
    }


def test_build_math_writes_jsonl_manifest_and_dedupes(tmp_path):
    rows = {
        "algebra": [
            math_row("Find the exact value of the sum $2+2$."),
            math_row("  find the exact value of the sum $2+2$.  "),
        ]
    }

    report = build_source("math", rows, tmp_path)

    assert report.parsed == 2
    assert report.accepted == 1
    assert report.duplicates == 1
    assert report.rejected == {}

    loaded = load_jsonl(tmp_path / "math.jsonl")
    assert [item.id.startswith("math:") for item in loaded] == [True]
    manifest = json.loads((tmp_path / "math.manifest.json").read_text(encoding="utf-8"))
    assert manifest["source"] == "math"
    assert manifest["license"] == "MIT"
    assert manifest["parsed"] == 2
    assert manifest["accepted"] == 1
    assert manifest["duplicates"] == 1


def test_build_applies_cross_topic_tags(tmp_path):
    row = math_row("Find the least squares solution of the overdetermined system.")

    report = build_source("math", {"algebra": [row]}, tmp_path)
    loaded = load_jsonl(tmp_path / "math.jsonl")

    assert report.accepted == 1
    assert "least-squares" in loaded[0].cross_topics


def test_build_olympiadbench_reports_image_rejection(tmp_path):
    rows = {
        "OE_MM_maths_zh_CEE": [
            olympiad_row("如图, 计算面积。 <image_1>"),
            olympiad_row(),
        ]
    }
    rows["OE_MM_maths_zh_CEE"][0]["modality"] = "Multimodal"

    report = build_source("olympiadbench", rows, tmp_path)

    assert report.parsed == 2
    assert report.accepted == 1
    assert report.rejected == {"image_dependency": 1}
    assert (tmp_path / "olympiadbench.jsonl").exists()


def test_build_numinamath_reports_invalid(tmp_path):
    invalid = numina_row()
    invalid["problem_is_valid"] = "No"

    report = build_source("numinamath", {"": [numina_row(), invalid]}, tmp_path)

    assert report.accepted == 1
    assert report.rejected == {"problem_invalid": 1}
    manifest = json.loads((tmp_path / "numinamath.manifest.json").read_text(encoding="utf-8"))
    assert manifest["license"] == "Apache-2.0"
