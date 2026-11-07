"""MATH 导入器:从解答的 \\boxed{} 抽取最终答案。"""
from __future__ import annotations

import hashlib
import re
from typing import Any

from ..schema import Source
from .common import ImportSkip, finalize, language_of, make_exercise, text_of

SOURCE = Source(
    name="MATH",
    tier="research",
    license="MIT",
    url="https://huggingface.co/datasets/EleutherAI/hendrycks_math",
    attribution="MATH (Hendrycks et al., 2021)",
    license_scope="dataset",
)

TOPIC_BY_SUBJECT = {
    "algebra": "algebra",
    "intermediate algebra": "algebra",
    "prealgebra": "algebra",
    "counting & probability": "probability",
    "counting and probability": "probability",
    "geometry": "geometry",
    "number theory": "numberTheory",
    "precalculus": "analysis",
}

_BOXED_RE = re.compile(r"\\boxed\s*\{")


def topic_for(subject: str) -> str:
    return TOPIC_BY_SUBJECT.get((subject or "").strip().lower(), "analysis")


def difficulty_for(level: str) -> int:
    match = re.search(r"(\d+)", level or "")
    if not match:
        return 3
    return max(1, min(5, int(match.group(1))))


def extract_boxed(solution: str) -> str:
    """取最后一个 \\boxed{...},支持嵌套花括号。"""
    matches = list(_BOXED_RE.finditer(solution))
    if not matches:
        return ""
    start = matches[-1].end()
    depth = 1
    index = start
    while index < len(solution) and depth:
        char = solution[index]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
        index += 1
    if depth:
        return ""
    return solution[start:index - 1].strip()


def _item_id(config: str, row: dict[str, Any], index: int) -> str:
    problem = str(row.get("problem", ""))
    digest = hashlib.sha1(problem.encode("utf-8")).hexdigest()[:12]
    return f"math:{config}:{index}-{digest}"


def parse_row(row: dict[str, Any], config: str, index: int = 0):
    question = text_of(row.get("problem"))
    solution = text_of(row.get("solution"))
    answer = extract_boxed(solution)
    if not answer:
        raise ImportSkip("answer_missing")

    exercise = make_exercise(
        exercise_id=_item_id(config, row, index),
        source=SOURCE,
        language=language_of(question),
        question=question,
        answer=answer,
        solution=solution,
        exercise_type="compute",
        difficulty=difficulty_for(str(row.get("level", ""))),
        primary_topic=topic_for(str(row.get("type", ""))),
    )
    return finalize(exercise)


def iter_exercises(rows, config: str):
    for index, row in enumerate(rows):
        try:
            yield parse_row(row, config, index)
        except ImportSkip:
            continue
