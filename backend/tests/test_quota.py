"""quota.py / config.daily_llm_limit:每日额度护栏。

计数口径是 usage 表当天该账号的记录数,所以这里不 mock 存储,直接用临时库真写。
"""
from __future__ import annotations

import time

import pytest
from starlette.exceptions import HTTPException

import config
import quota
import usage


def _record(uid: str, ts: float | None = None) -> None:
    usage.record(
        uid=uid, cmd="", prompt_len=1, reply_len=1, role="main",
        research=False, ts=time.time() if ts is None else ts,
    )


def test_day_start_is_local_midnight():
    now = time.time()
    start = usage.day_start(now)
    assert start <= now
    local = time.localtime(start)
    assert (local.tm_hour, local.tm_min, local.tm_sec) == (0, 0, 0)
    # 当天 0 点到现在不会超过一天(夏令时最多多一小时)
    assert now - start < 86400 + 3600


def test_count_since_scopes_by_user_and_time(temp_usage):
    _record("u-quota", 100.0)
    _record("u-quota", 200.0)
    _record("u-other", 200.0)

    assert usage.count_since("u-quota", 0) == 2
    assert usage.count_since("u-quota", 150.0) == 1
    assert usage.count_since("u-quota", 500.0) == 0
    assert usage.count_since("", 0) == 0


def test_limit_zero_means_unlimited(temp_usage, monkeypatch):
    monkeypatch.delenv("MG_DAILY_LLM_CALLS", raising=False)
    for _ in range(5):
        _record("u-x")
    quota.check("u-x")  # 不抛


def test_limit_blocks_when_reached(temp_usage, monkeypatch):
    monkeypatch.setenv("MG_DAILY_LLM_CALLS", "2")
    _record("u-y")
    _record("u-y")
    with pytest.raises(HTTPException) as err:
        quota.check("u-y")
    assert err.value.status_code == 429
    # 额度是按账号的:别的账号不受影响
    quota.check("u-z")


def test_bad_limit_value_is_treated_as_unlimited(monkeypatch):
    monkeypatch.setenv("MG_DAILY_LLM_CALLS", "many")
    assert config.daily_llm_limit() == 0
    monkeypatch.setenv("MG_DAILY_LLM_CALLS", "-3")
    assert config.daily_llm_limit() == 0
    monkeypatch.setenv("MG_DAILY_LLM_CALLS", "50")
    assert config.daily_llm_limit() == 50
