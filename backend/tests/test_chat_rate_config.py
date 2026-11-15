"""chat.configure_rate_limit:每用户限流可配,0 = 关闭(压测「测天花板」用)。

背景:这条限流在贵的活**之前**判定(chat 入口、导出入口都是),默认 6 次/分时
同一账号并发 7 个请求,第 7 个撞到 `rate limited` 而不是导出闸门的
`pdf export busy` —— 不关掉它,量到的是限流口径,不是机器上限。
"""
from __future__ import annotations

import pytest

import chat
from rate_limit import NullLimiter, SlidingWindowLimiter


@pytest.fixture(autouse=True)
def _restore_default_limiter():
    """测试会重建模块级限流器;结束后按已还原的环境重建回默认值。

    monkeypatch 在 teardown 时才撤销 env,所以这里必须排在它之后执行
    (fixture 的 yield 后代码天然晚于 monkeypatch 撤销)。
    """
    yield
    chat.configure_rate_limit()


def test_defaults_are_unchanged(monkeypatch):
    monkeypatch.delenv("MG_CHAT_RATE_MAX", raising=False)
    monkeypatch.delenv("MG_CHAT_RATE_WINDOW", raising=False)
    chat.configure_rate_limit()
    assert isinstance(chat._rate_limiter, SlidingWindowLimiter)
    assert chat._rate_limiter.max_hits == 6
    assert chat._rate_limiter.window == 60.0


def test_env_overrides(monkeypatch):
    """压测天花板:把阈值抬到高于并发数,限流就不该先咬人。"""
    monkeypatch.setenv("MG_CHAT_RATE_MAX", "600")
    monkeypatch.setenv("MG_CHAT_RATE_WINDOW", "30")
    chat.configure_rate_limit()
    assert chat._rate_limiter.max_hits == 600
    assert chat._rate_limiter.window == 30.0


def test_zero_disables_the_limiter(monkeypatch):
    monkeypatch.setenv("MG_CHAT_RATE_MAX", "0")
    chat.configure_rate_limit()
    assert isinstance(chat._rate_limiter, NullLimiter)
    # 关闭后无论打多少次都放行(压测期间不该出现 rate limited)
    assert all(chat._rate_limiter.allow("u") for _ in range(1000))


def test_bad_values_fall_back_to_defaults(monkeypatch):
    """拼错/窗口非法 → 回退默认,而不是把保护悄悄关掉。"""
    monkeypatch.setenv("MG_CHAT_RATE_MAX", "many")
    monkeypatch.setenv("MG_CHAT_RATE_WINDOW", "0")
    chat.configure_rate_limit()
    assert isinstance(chat._rate_limiter, SlidingWindowLimiter)
    assert chat._rate_limiter.max_hits == 6
    assert chat._rate_limiter.window == 60.0


def test_negative_falls_back_instead_of_disabling(monkeypatch):
    """-1 必须回退 6:多打一个负号就关掉保护,比报错危险得多。"""
    monkeypatch.setenv("MG_CHAT_RATE_MAX", "-1")
    chat.configure_rate_limit()
    assert chat._rate_limiter.max_hits == 6
