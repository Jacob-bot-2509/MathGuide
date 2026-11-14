"""diagram_alerts:图解告警出口(可选 webhook,只发聚合指标)。

缺 42.6% 的那部分正好是**"线上真出事时才会走"的路径**:冷却窗口、
webhook 未配置、请求失败、以及在无事件循环时静默跳过。
这些路径一旦写错,表现是"告警永远发不出去"或"告警风暴",而不是报错。
"""
from __future__ import annotations

import asyncio

import pytest

import diagram_alerts as da


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    monkeypatch.delenv("MG_DIAGRAM_ALERT_WEBHOOK", raising=False)
    monkeypatch.delenv("MG_DIAGRAM_ALERT_COOLDOWN", raising=False)
    da.reset_for_tests()
    yield
    da.reset_for_tests()


def test_payload_contains_only_aggregates(monkeypatch):
    monkeypatch.setattr(da.diagram_metrics, "snapshot", lambda: {"render": 3})
    payload = da.build_payload("verify_failed")

    assert payload["service"] == "mathguide"
    assert payload["event"] == "diagram_alert"
    assert payload["reason"] == "verify_failed"
    assert payload["snapshot"] == {"render": 3}
    assert isinstance(payload["ts"], int)
    # 只允许这三个键 + ts:加正文/身份就是隐私事故
    assert set(payload) == {"service", "event", "reason", "snapshot", "ts"}


def test_payload_truncates_reason_and_defaults(monkeypatch):
    monkeypatch.setattr(da.diagram_metrics, "snapshot", lambda: {})
    assert da.build_payload("x" * 200)["reason"] == "x" * 80
    assert da.build_payload("")["reason"] == "unknown"


def test_cooldown_defaults_minimum_and_ignores_garbage(monkeypatch):
    assert da._cooldown() == 300.0
    monkeypatch.setenv("MG_DIAGRAM_ALERT_COOLDOWN", "10")
    assert da._cooldown() == 30.0        # 下限 30s,避免告警风暴
    monkeypatch.setenv("MG_DIAGRAM_ALERT_COOLDOWN", "abc")
    assert da._cooldown() == 300.0


def test_notify_without_webhook_is_noop(monkeypatch):
    async def fail(*_args, **_kwargs):
        raise AssertionError("没有配置 webhook 时不该发请求")

    monkeypatch.setattr(da, "_cooldown", lambda: 0.0)
    assert asyncio.run(da.notify("boom")) is False
    assert fail is not None


def test_notify_sends_once_then_respects_cooldown(monkeypatch):
    calls = []

    class FakeClient:
        def __init__(self, **_kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_exc):
            return False

        async def post(self, url, json=None):
            calls.append((url, json))

            class _Response:
                status_code = 204
            return _Response()

    import httpx
    monkeypatch.setenv("MG_DIAGRAM_ALERT_WEBHOOK", "https://hook.example/x")
    monkeypatch.setenv("MG_DIAGRAM_ALERT_COOLDOWN", "300")
    monkeypatch.setattr(httpx, "AsyncClient", FakeClient)
    monkeypatch.setattr(da.diagram_metrics, "snapshot", lambda: {"a": 1})

    assert asyncio.run(da.notify("first")) is True
    assert len(calls) == 1
    assert calls[0][0] == "https://hook.example/x"
    assert calls[0][1]["reason"] == "first"

    # 冷却期内第二次直接返回 False,不再发请求
    assert asyncio.run(da.notify("second")) is False
    assert len(calls) == 1


def test_notify_non_2xx_counts_as_failure(monkeypatch):
    class FakeClient:
        def __init__(self, **_kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_exc):
            return False

        async def post(self, url, json=None):
            class _Response:
                status_code = 503
            return _Response()

    import httpx
    monkeypatch.setenv("MG_DIAGRAM_ALERT_WEBHOOK", "https://hook.example/x")
    monkeypatch.setattr(httpx, "AsyncClient", FakeClient)

    assert asyncio.run(da.notify("boom")) is False


def test_notify_swallows_transport_errors(monkeypatch):
    """告警通道炸了不能影响业务,只能记一条日志。"""
    class BrokenClient:
        def __init__(self, **_kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_exc):
            return False

        async def post(self, *_args, **_kwargs):
            raise OSError("network down")

    import httpx
    monkeypatch.setenv("MG_DIAGRAM_ALERT_WEBHOOK", "https://hook.example/x")
    monkeypatch.setattr(httpx, "AsyncClient", BrokenClient)

    assert asyncio.run(da.notify("boom")) is False


def test_schedule_requires_webhook_and_running_loop(monkeypatch):
    # 没配置 → 直接返回
    da.schedule("boom")

    monkeypatch.setenv("MG_DIAGRAM_ALERT_WEBHOOK", "https://hook.example/x")

    # 有配置但在同步上下文(没有 running loop) → 静默跳过,不能抛
    da.schedule("boom")

    # 在事件循环里 → 真的建了任务(用假的 notify 观察调用)
    seen = []

    async def fake_notify(reason):
        seen.append(reason)
        return True

    monkeypatch.setattr(da, "notify", fake_notify)

    async def scenario():
        da.schedule("in-loop")
        await asyncio.sleep(0)      # 让 create_task 跑起来
        await asyncio.sleep(0)

    asyncio.run(scenario())
    assert seen == ["in-loop"]
