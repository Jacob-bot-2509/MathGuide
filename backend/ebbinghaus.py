"""艾宾浩斯遗忘曲线:图谱复习评判与学习分析共用的时间衰减。

R(t,s) = exp(-t / tau(s)),tau(s) = 30 + 15 * (s - 1) 天。
R < REVIEW_RETENTION 时进入待复核;只影响复习优先级,不改写原始诊断分。
"""
from __future__ import annotations

import math
from datetime import datetime, timezone

TAU_BASE = 30.0
TAU_STEP = 15.0
REVIEW_RETENTION = 0.6


def parse_at(value) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def age_days(at, now: datetime | None = None) -> int | None:
    """距诊断时间的天数;时间戳不可解析时返回 None。"""
    parsed = parse_at(at)
    if parsed is None:
        return None
    now = now or datetime.now().astimezone()
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    return max(0, int((now - parsed).total_seconds() // 86400))


def tau_days(score: int) -> float:
    """记忆强度(天):掌握度越高,遗忘越慢。"""
    score = max(1, min(5, int(score)))
    return TAU_BASE + TAU_STEP * (score - 1)


def retention(age: int | None, score: int | None) -> float | None:
    """R(t,s);0 天为 1,随时间单调下降。"""
    if score is None or age is None:
        return None
    if age <= 0:
        return 1.0
    return math.exp(-age / tau_days(score))


def review_due(at, score: int | None,
               now: datetime | None = None) -> tuple[bool, float | None, int | None]:
    """返回 (是否待复核, 保持率, 距诊断天数)。"""
    age = age_days(at, now) if score is not None else None
    rate = retention(age, score)
    due = rate is not None and rate < REVIEW_RETENTION
    return due, rate, age
