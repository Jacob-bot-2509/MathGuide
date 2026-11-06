"""OlympiadBench 导入器:只收 text-only + open-ended + 有最终答案的题。"""
from __future__ import annotations

import hashlib
from typing import Any

from ..schema import Source
from .common import ImportSkip, finalize, has_image, language_of, make_exercise, text_of

SOURCE = Source(
    name="OlympiadBench",
    tier="research",
    license="Apache-2.0",
    url="https://huggingface.co/datasets/Hothan/OlympiadBench",
    attribution="OlympiadBench (He et al., ACL 2024)",
    license_scope="dataset",
)

TOPIC_BY_SUBFIELD = {
    "probability": "probability",
    "probability and statistics": "probability",
    "statistics": "probability",
    "combinatorics": "probability",
    "plane geometry": "geometry",
    "solid geometry": "geometry",
    "conic sections": "geometry",
    "geometry": "geometry",
    "algebra": "algebra",
    "inequality": "analysis",
    "inequalities": "analysis",
    "derivative": "analysis",
    "elementary functions": "analysis",
    "trigonometric functions": "analysis",
    "calculus": "analysis",
    "number theory": "numberTheory",
    "differential equations": "ode",
}

DIFFICULTY_BY_LABEL = {
    "chinese college entrance exam": 3,
    "competition": 4,
}


def topic_for(subfield: str) -> str:
    return TOPIC_BY_SUBFIELD.get((subfield or "").strip().lower(), "analysis")


def difficulty_for(label: str) -> int:
    return DIFFICULTY_BY_LABEL.get((label or "").strip().lower(), 3)


def _item_id(config: str, row: dict[str, Any], index: int) -> str:
    raw = str(row.get("id", index))
    if not raw:
        raw = hashlib.sha1(str(row.get("question", "")).encode()).hexdigest()[:12]
    return f"olympiadbench:{config}:{raw}"


def parse_row(row: dict[str, Any], config: str, index: int = 0):
    question = text_of(row.get("question"))
    if has_image(question, row):
        raise ImportSkip("image_dependency")
    question_type = str(row.get("question_type", "")).strip().lower()
    if question_type == "theorem proof":
        raise ImportSkip("proof_without_answer")
    answer = text_of(row.get("final_answer"))
    if not answer:
        raise ImportSkip("answer_missing")
    solution = text_of(row.get("solution"))
    if not solution:
        raise ImportSkip("solution_missing")

    language = "zh" if str(row.get("language", "")).lower().startswith("chin") else language_of(question)
    exercise = make_exercise(
        exercise_id=_item_id(config, row, index),
        source=SOURCE,
        language=language,
        question=question,
        answer=answer,
        solution=solution,
        exercise_type="compute",
        difficulty=difficulty_for(str(row.get("difficulty", ""))),
        primary_topic=topic_for(str(row.get("subfield", ""))),
    )
    return finalize(exercise)


def iter_exercises(rows, config: str):
    for index, row in enumerate(rows):
        try:
            yield parse_row(row, config, index)
        except ImportSkip:
            continue
