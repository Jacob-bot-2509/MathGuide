"""习题存储:JSONL 读取、来源分层、条件过滤、确定性抽样与覆盖统计。"""
from __future__ import annotations

import json
import os
import random
from collections import Counter
from collections.abc import Iterable
from pathlib import Path

from .schema import EXERCISE_TYPES, Exercise, SchemaError, parse_exercise
from .taxonomy import CATEGORY_KEYS, CROSS_TOPIC_IDS

DEFAULT_TIERS: tuple[str, ...] = ("safe",)
_ALLOWED_TIERS = frozenset({"safe", "research"})
LANGUAGES = ("zh", "en", "both")


def tiers_from_env(value: str | None = None) -> tuple[str, ...]:
    """读取 MG_EXERCISE_TIERS;未知层与 blocked 忽略,空值回退 safe。"""
    raw = os.environ.get("MG_EXERCISE_TIERS", "safe") if value is None else value
    tiers = tuple(
        tier
        for tier in dict.fromkeys(part.strip() for part in raw.split(","))
        if tier in _ALLOWED_TIERS
    )
    return tiers or DEFAULT_TIERS


def load_jsonl(path: Path) -> tuple[Exercise, ...]:
    """逐行读取 JSONL;空行跳过,坏行带行号抛 SchemaError。"""
    exercises: list[Exercise] = []
    text = path.read_text(encoding="utf-8")
    for lineno, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise SchemaError(f"{path.name} 第 {lineno} 行: JSON 无效 ({exc.msg})") from exc
        try:
            exercises.append(parse_exercise(value))
        except SchemaError as exc:
            raise SchemaError(f"{path.name} 第 {lineno} 行: {exc}") from exc
    return tuple(exercises)


class ExerciseStore:
    """只保留 safe/research 层;blocked 永不进入内存。"""

    def __init__(
        self,
        exercises: Iterable[Exercise],
        tiers: tuple[str, ...] = DEFAULT_TIERS,
    ) -> None:
        self._tiers = tuple(tier for tier in tiers if tier in _ALLOWED_TIERS)
        allowed = set(self._tiers)
        self._exercises = tuple(item for item in exercises if item.source.tier in allowed)

    @classmethod
    def from_jsonl(
        cls,
        paths: Iterable[Path],
        tiers: tuple[str, ...] = DEFAULT_TIERS,
    ) -> ExerciseStore:
        loaded: list[Exercise] = []
        for path in paths:
            loaded.extend(load_jsonl(Path(path)))
        return cls(loaded, tiers=tiers)

    @classmethod
    def from_directory(
        cls,
        directory: Path,
        tiers: tuple[str, ...] = DEFAULT_TIERS,
    ) -> ExerciseStore:
        base = Path(directory)
        return cls.from_jsonl(sorted(base.glob("*.jsonl")), tiers=tiers)

    @property
    def exercises(self) -> tuple[Exercise, ...]:
        return self._exercises

    @property
    def tiers(self) -> tuple[str, ...]:
        return self._tiers

    def __len__(self) -> int:
        return len(self._exercises)

    def filter(
        self,
        *,
        topics: Iterable[str] = (),
        cross_topics: Iterable[str] = (),
        types: Iterable[str] = (),
        difficulty: tuple[int, int] | None = None,
        lang: str = "any",
        limit: int | None = None,
    ) -> tuple[Exercise, ...]:
        if lang not in ("any",) + LANGUAGES:
            raise ValueError(f"lang 不合法: {lang}")
        topic_set = set(topics)
        cross_set = set(cross_topics)
        type_set = set(types)
        low, high = difficulty or (1, 5)
        if low > high:
            raise ValueError("difficulty 下界不能大于上界")

        result: list[Exercise] = []
        for item in self._exercises:
            if topic_set and not topic_set.intersection(item.topics):
                continue
            if cross_set and not cross_set.intersection(item.cross_topics):
                continue
            if type_set and item.type not in type_set:
                continue
            if not low <= item.difficulty <= high:
                continue
            languages = item.available_languages
            if lang == "zh" and "zh" not in languages:
                continue
            if lang == "en" and "en" not in languages:
                continue
            if lang == "both" and not ("zh" in languages and "en" in languages):
                continue
            result.append(item)
            if limit is not None and len(result) >= limit:
                break
        return tuple(result)

    def sample(
        self,
        count: int,
        *,
        seed: int = 20261106,
        **filters: object,
    ) -> tuple[Exercise, ...]:
        """同条件、同 seed 必然得到同一组题;先按 id 排序,避免输入顺序影响。"""
        if count <= 0:
            return ()
        items = sorted(self.filter(**filters), key=lambda item: item.id)
        if count >= len(items):
            return tuple(items)
        return tuple(random.Random(seed).sample(items, count))

    def coverage(self) -> dict[str, dict[str, int]]:
        topic_counts = Counter({key: 0 for key in CATEGORY_KEYS})
        cross_counts = Counter({key: 0 for key in CROSS_TOPIC_IDS})
        type_counts = Counter({key: 0 for key in EXERCISE_TYPES})
        difficulty_counts = Counter({str(level): 0 for level in range(1, 6)})
        language_counts = Counter({"zh": 0, "en": 0, "both": 0})

        for item in self._exercises:
            topic_counts.update(item.topics)
            cross_counts.update(item.cross_topics)
            type_counts.update([item.type])
            difficulty_counts.update([str(item.difficulty)])
            languages = item.available_languages
            if "zh" in languages and "en" in languages:
                language_counts.update(["both"])
            elif "zh" in languages:
                language_counts.update(["zh"])
            elif "en" in languages:
                language_counts.update(["en"])

        return {
            "topics": dict(topic_counts),
            "cross_topics": dict(cross_counts),
            "types": dict(type_counts),
            "difficulties": dict(difficulty_counts),
            "languages": dict(language_counts),
        }
