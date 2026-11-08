"""NuminaMath 导入器:只取 cn_k12 / cn_contest,过滤无效题。"""
from __future__ import annotations

import hashlib
from typing import Any

from ..schema import Source
from .common import ImportSkip, finalize, language_of, make_exercise, text_of

SOURCE = Source(
    name="NuminaMath",
    tier="research",
    license="Apache-2.0",
    url="https://huggingface.co/datasets/project-numina/NuminaMath-1.5",
    attribution="NuminaMath (AI-MO, 2024)",
    license_scope="dataset",
)

ALLOWED_SOURCES = frozenset({"cn_k12", "cn_contest"})

TOPIC_BY_PROBLEM = {
    "algebra": "algebra",
    "geometry": "geometry",
    "combinatorics": "probability",
    "inequalities": "analysis",
    "calculus": "analysis",
    "number theory": "numberTheory",
    "logic and puzzles": "analysis",
    "other": "analysis",
}

TYPE_BY_QUESTION = {
    "mcq": "choice",
    "math-word-problem": "apply",
    "proof": "proof",
}


def topic_for(problem_type: str) -> str:
    return TOPIC_BY_PROBLEM.get((problem_type or "").strip().lower(), "analysis")


def type_for(question_type: str) -> str:
    return TYPE_BY_QUESTION.get((question_type or "").strip().lower(), "compute")


def difficulty_for(source: str) -> int:
    return 4 if source == "cn_contest" else 2


def _item_id(source: str, row: dict[str, Any], index: int) -> str:
    problem = str(row.get("problem", ""))
    digest = hashlib.sha1(problem.encode("utf-8")).hexdigest()[:12]
    return f"numinamath:{source}:{index}-{digest}"


def parse_row(row: dict[str, Any], index: int = 0):
    source_name = str(row.get("source", "")).strip()
    if source_name not in ALLOWED_SOURCES:
        raise ImportSkip(f"source_not_allowed:{source_name or 'missing'}")
    if str(row.get("problem_is_valid", "Yes")).strip().lower() == "no":
        raise ImportSkip("problem_invalid")
    if str(row.get("solution_is_valid", "Yes")).strip().lower() == "no":
        raise ImportSkip("solution_invalid")

    question = text_of(row.get("problem"))
    answer = text_of(row.get("answer"))
    solution = text_of(row.get("solution"))
    if not answer:
        raise ImportSkip("answer_missing")
    if not solution:
        raise ImportSkip("solution_missing")

    exercise = make_exercise(
        exercise_id=_item_id(source_name, row, index),
        source=SOURCE,
        language=language_of(question),
        question=question,
        answer=answer,
        solution=solution,
        exercise_type=type_for(str(row.get("question_type", ""))),
        difficulty=difficulty_for(source_name),
        primary_topic=topic_for(str(row.get("problem_type", ""))),
    )
    return finalize(exercise)


def iter_exercises(rows):
    for index, row in enumerate(rows):
        try:
            yield parse_row(row, index)
        except ImportSkip:
            continue
