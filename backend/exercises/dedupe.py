"""习题去重:题干精确哈希 + 字符 5-gram Jaccard 近似匹配。"""
from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass

from .schema import Exercise, question_hash

NGRAM_SIZE = 5
DEFAULT_THRESHOLD = 0.92
_WS_RE = re.compile(r"\s+")


@dataclass(frozen=True)
class DedupeResult:
    kept: tuple[Exercise, ...]
    dropped: tuple[tuple[Exercise, Exercise], ...]


def normalize_question(text: str) -> str:
    return _WS_RE.sub("", text.lower())


def ngrams(text: str, size: int = NGRAM_SIZE) -> set[str]:
    value = normalize_question(text)
    if not value:
        return set()
    if len(value) <= size:
        return {value}
    return {value[index:index + size] for index in range(len(value) - size + 1)}


def jaccard(left: set[str], right: set[str]) -> float:
    if not left and not right:
        return 1.0
    union = left | right
    if not union:
        return 1.0
    return len(left & right) / len(union)


def similarity(left: str, right: str) -> float:
    return jaccard(ngrams(left), ngrams(right))


def is_near_duplicate(left: str, right: str, threshold: float = DEFAULT_THRESHOLD) -> bool:
    return similarity(left, right) >= threshold


def _question(exercise: Exercise) -> str:
    return exercise.content[exercise.original_language].question


def dedupe(
    exercises: Iterable[Exercise],
    threshold: float = DEFAULT_THRESHOLD,
) -> DedupeResult:
    """保留首次出现的题;相同题干或近似题干进入 dropped。"""
    if not 0 <= threshold <= 1:
        raise ValueError("threshold 必须在 0~1 之间")

    kept: list[Exercise] = []
    dropped: list[tuple[Exercise, Exercise]] = []
    exact: dict[str, int] = {}
    index: dict[str, set[int]] = {}

    for exercise in exercises:
        text = _question(exercise)
        digest = question_hash(text)
        if digest in exact:
            dropped.append((kept[exact[digest]], exercise))
            continue

        grams = ngrams(text)
        candidates: set[int] = set()
        for gram in grams:
            candidates.update(index.get(gram, ()))

        duplicate_of: Exercise | None = None
        for candidate_index in candidates:
            if similarity(text, _question(kept[candidate_index])) >= threshold:
                duplicate_of = kept[candidate_index]
                break
        if duplicate_of is not None:
            dropped.append((duplicate_of, exercise))
            continue

        exact[digest] = len(kept)
        position = len(kept)
        for gram in grams:
            index.setdefault(gram, set()).add(position)
        kept.append(exercise)

    return DedupeResult(kept=tuple(kept), dropped=tuple(dropped))
