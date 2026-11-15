"""rag/llm:角色解析、思考开关、流式帧解析与"只在未出字时才切 backup"。

缺的 41 行几乎全在 `_stream_once`(112-174)与 `stream_chat`(194-224):
保活帧撑过 read 超时导致首字超时、异常帧持续到达、思考帧算不算"活着",
以及最要紧的一条 —— **已经向调用方 yield 过内容就绝不能再走 backup**,
否则用户会看到「半截 A + 完整 B」的拼接答案。
"""
from __future__ import annotations

import asyncio
import json

import pytest

import rag.llm as llm

BASE, KEY, MODEL = "https://api.example/v1", "sk-test", "test-model"


class FakeResponse:
    def __init__(self, lines, error: Exception | None = None):
        self._lines = lines
        self._error = error

    def raise_for_status(self):
        if self._error:
            raise self._error

    async def aiter_lines(self):
        for line in self._lines:
            yield line


class FakeClient:
    """替掉 httpx.AsyncClient:记录请求,回放固定的 SSE 行。"""

    capture: dict = {}

    def __init__(self, lines, error=None):
        self._lines = lines
        self._error = error

    def __call__(self, **_kwargs):
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_exc):
        return False

    def stream(self, method, url, **kwargs):
        FakeClient.capture = {"method": method, "url": url, **kwargs}
        client = self

        class _Ctx:
            async def __aenter__(self_inner):
                return FakeResponse(client._lines, client._error)

            async def __aexit__(self_inner, *_exc):
                return False

        return _Ctx()


def _patch_http(monkeypatch, lines, error=None):
    monkeypatch.setattr(llm.httpx, "AsyncClient", FakeClient(lines, error))


async def _collect(coro_iter) -> list[str]:
    return [chunk async for chunk in coro_iter]


def _frame(content: str | None = None, reasoning: str | None = None) -> str:
    delta = {}
    if content is not None:
        delta["content"] = content
    if reasoning is not None:
        delta["reasoning_content"] = reasoning
    return "data: " + json.dumps({"choices": [{"delta": delta}]})


# ---------- 角色解析 ----------

def test_resolve_requires_provider_key_and_model(monkeypatch):
    monkeypatch.setenv("MG_ROLE_MAIN", "aliyun:qwen")
    monkeypatch.setenv("MG_ALIYUN_BASE_URL", BASE)
    monkeypatch.setenv("MG_ALIYUN_API_KEY", KEY)
    assert llm.resolve("main") == (BASE, KEY, "qwen")


def test_resolve_returns_none_for_bad_specs(monkeypatch):
    monkeypatch.setenv("MG_ROLE_MAIN", "no-colon-here")
    assert llm.resolve("main") is None

    monkeypatch.setenv("MG_ROLE_MAIN", "unknown:p")
    assert llm.resolve("main") is None

    monkeypatch.setenv("MG_ROLE_MAIN", "aliyun:qwen")
    monkeypatch.setenv("MG_ALIYUN_BASE_URL", BASE)
    monkeypatch.delenv("MG_ALIYUN_API_KEY", raising=False)
    assert llm.resolve("main") is None


def test_pick_falls_back_to_main_when_role_unconfigured(monkeypatch):
    monkeypatch.setenv("MG_ROLE_MAIN", "aliyun:qwen")
    monkeypatch.setenv("MG_ALIYUN_BASE_URL", BASE)
    monkeypatch.setenv("MG_ALIYUN_API_KEY", KEY)
    monkeypatch.delenv("MG_ZHIPU_API_KEY", raising=False)

    assert llm.pick("main") == "main"
    assert llm.pick("backup") == "main"      # 备胎没配 → 用 main,链路不断


def test_thinking_param_for_normal_and_always_thinking_models():
    assert llm._thinking_param("qwen", True) == {}
    assert llm._thinking_param("qwen", False) == {"enable_thinking": False}
    # 始终思考的模型拒收 enable_thinking=false,只能用 reasoning_effort=low
    assert llm._thinking_param("glm-5.3", False) == {"reasoning_effort": "low"}


# ---------- 流式帧解析 ----------

def test_stream_once_yields_content_and_skips_noise(monkeypatch):
    lines = [
        ": keep-alive",
        "",
        "data: [DONE]",
        _frame(content="极限"),
        _frame(reasoning="想一想"),      # 思考帧:不转发,但算链路活着
        _frame(content="的定义"),
    ]
    _patch_http(monkeypatch, lines)

    chunks = asyncio.run(_collect(llm._stream_once(
        BASE, KEY, MODEL, "sys", "user", None, None, 20.0, thinking=False)))

    assert chunks == ["极限", "的定义"]
    payload = FakeClient.capture["json"]
    assert payload["stream"] is True
    assert payload["messages"][0] == {"role": "system", "content": "sys"}
    assert FakeClient.capture["method"] == "POST"


def test_stream_once_temperature_is_forwarded(monkeypatch):
    _patch_http(monkeypatch, [_frame(content="x")])
    asyncio.run(_collect(llm._stream_once(
        BASE, KEY, MODEL, "s", "u", None, None, 20.0, thinking=False, temperature=0)))
    assert FakeClient.capture["json"]["temperature"] == 0


def test_stream_once_times_out_when_only_keepalives_arrive(monkeypatch):
    """保活帧会重置 httpx 的 read 超时,所以必须自己盯首字硬限时。"""
    _patch_http(monkeypatch, [": ping", ": ping", ": ping"])

    with pytest.raises(TimeoutError, match="首字超时"):
        asyncio.run(_collect(llm._stream_once(
            BASE, KEY, MODEL, "s", "u", None, None, 0.0, thinking=False)))


def test_stream_once_times_out_on_persistent_bad_frames(monkeypatch):
    _patch_http(monkeypatch, ["data: {not json}", "data: {}"])

    with pytest.raises(TimeoutError, match="异常帧"):
        asyncio.run(_collect(llm._stream_once(
            BASE, KEY, MODEL, "s", "u", None, None, 0.0, thinking=False)))


# ---------- 容灾切换 ----------

def test_stream_chat_raises_when_role_unconfigured(monkeypatch):
    monkeypatch.setenv("MG_ROLE_MAIN", "aliyun:qwen")
    monkeypatch.delenv("MG_ALIYUN_API_KEY", raising=False)

    with pytest.raises(RuntimeError, match="未配置"):
        asyncio.run(_collect(llm.stream_chat("s", "u")))


def _configure_both(monkeypatch):
    monkeypatch.setenv("MG_ROLE_MAIN", "aliyun:qwen")
    monkeypatch.setenv("MG_ALIYUN_BASE_URL", BASE)
    monkeypatch.setenv("MG_ALIYUN_API_KEY", KEY)
    monkeypatch.setenv("MG_ROLE_BACKUP", "zhipu:glm")
    monkeypatch.setenv("MG_ZHIPU_BASE_URL", "https://api.zhipu/v1")
    monkeypatch.setenv("MG_ZHIPU_API_KEY", "sk-backup")


def test_stream_chat_switches_to_backup_before_any_output(monkeypatch):
    _configure_both(monkeypatch)
    calls = []

    async def fake_stream_once(base, *_args, **_kwargs):
        calls.append(base)
        if "zhipu" in base:
            yield "备胎回答"
            return
        raise RuntimeError("primary down")
        yield  # pragma: no cover 让函数保持异步生成器

    monkeypatch.setattr(llm, "_stream_once", fake_stream_once)

    assert asyncio.run(_collect(llm.stream_chat("s", "u"))) == ["备胎回答"]
    assert calls == [BASE, "https://api.zhipu/v1"]


def test_stream_chat_never_replays_after_partial_output(monkeypatch):
    """已经 yield 过内容再切 backup,用户会看到「半截 A + 完整 B」—— 必须直接抛。"""
    _configure_both(monkeypatch)

    async def broken_stream(*_args, **_kwargs):
        yield "半截"
        raise RuntimeError("断了")

    monkeypatch.setattr(llm, "_stream_once", broken_stream)
    collected: list[str] = []

    async def scenario():
        with pytest.raises(RuntimeError):
            async for chunk in llm.stream_chat("s", "u"):
                collected.append(chunk)

    asyncio.run(scenario())
    assert collected == ["半截"]      # 只出过 A,没有 B 的拼接


def test_stream_chat_without_fallback_raises_immediately(monkeypatch):
    _configure_both(monkeypatch)

    async def broken_stream(*_args, **_kwargs):
        raise RuntimeError("primary down")
        yield  # pragma: no cover

    monkeypatch.setattr(llm, "_stream_once", broken_stream)

    with pytest.raises(RuntimeError, match="primary down"):
        asyncio.run(_collect(llm.stream_chat("s", "u", fallback=False)))


def test_stream_chat_raises_when_backup_missing(monkeypatch):
    monkeypatch.setenv("MG_ROLE_MAIN", "aliyun:qwen")
    monkeypatch.setenv("MG_ALIYUN_BASE_URL", BASE)
    monkeypatch.setenv("MG_ALIYUN_API_KEY", KEY)
    monkeypatch.delenv("MG_ZHIPU_API_KEY", raising=False)

    async def broken_stream(*_args, **_kwargs):
        raise RuntimeError("primary down")
        yield  # pragma: no cover

    monkeypatch.setattr(llm, "_stream_once", broken_stream)

    with pytest.raises(RuntimeError, match="primary down"):
        asyncio.run(_collect(llm.stream_chat("s", "u")))
