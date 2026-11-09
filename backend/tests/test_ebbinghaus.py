"""艾宾浩斯遗忘曲线：时间常数、保持率与待复核判定。"""
from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

import pytest

from ebbinghaus import REVIEW_RETENTION, age_days, retention, review_due, tau_days

NOW = datetime(2026, 11, 9, 12, 0, tzinfo=timezone.utc)


def _at(days: int) -> str:
    return (NOW - timedelta(days=days)).isoformat(timespec="seconds")


def test_tau_scales_with_score():
    assert tau_days(1) == 30
    assert tau_days(3) == 60
    assert tau_days(5) == 90


def test_retention_decays_monotonically():
    assert retention(0, 5) == 1.0
    assert retention(30, 5) == pytest.approx(math.exp(-30 / 90), abs=0.001)
    assert retention(60, 5) < retention(30, 5)


def test_higher_score_retains_longer():
    assert retention(60, 5) > retention(60, 3)


def test_review_due_threshold():
    due, rate, days = review_due(_at(90), 5, now=NOW)
    assert due is True
    assert rate < REVIEW_RETENTION
    assert days == 90

    due, rate, _ = review_due(_at(0), 5, now=NOW)
    assert due is False
    assert rate == 1.0


def test_age_days_handles_bad_timestamp():
    assert age_days("not-a-date", now=NOW) is None
