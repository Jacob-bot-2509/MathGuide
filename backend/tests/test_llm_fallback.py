"""rag.llm:只在「一字未出」时切换 backup,避免半截答案 + 完整答案拼接。"""
from __future__ import annotations

import asyncio

import pytest

from rag import llm


def _resolve(role):
    return {
        "main": ("base-1", "key-1", "primary"),
        "backup": ("base-2", "key-2", "backup"),
    }.get(role)


async def _collect(async_gen) -> list[str]:
    return [delta async for delta in async_gen]


def _fake_stream(primary_behavior):
    async def fake(base, key, model, system, user, history=None, max_tokens=None,
                   first_token_secs=20.0):
        if model == "primary":
            async for delta in primary_behavior():
                yield delta
        else:
            yield "B"
    return fake


async def _raises_after_one():
    yield "A"
    raise RuntimeError("connection dropped")


async def _raises_immediately():
    raise RuntimeError("connection refused")
    yield  # pragma: no cover


def test_partial_primary_does_not_replay_backup(monkeypatch):
    monkeypatch.setattr(llm, "resolve", _resolve)
    monkeypatch.setattr(llm, "_stream_once", _fake_stream(_raises_after_one))

    out: list[str] = []

    async def run():
        async for delta in llm.stream_chat("system", "user", role="main", fallback=True):
            out.append(delta)

    with pytest.raises(RuntimeError):
        asyncio.run(run())
    assert out == ["A"]  # 不能再出现 backup 的 "B"


def test_zero_output_primary_falls_back_to_backup(monkeypatch):
    monkeypatch.setattr(llm, "resolve", _resolve)
    monkeypatch.setattr(llm, "_stream_once", _fake_stream(_raises_immediately))

    out = asyncio.run(_collect(
        llm.stream_chat("system", "user", role="main", fallback=True)))
    assert out == ["B"]


def test_fallback_disabled_propagates(monkeypatch):
    monkeypatch.setattr(llm, "resolve", _resolve)
    monkeypatch.setattr(llm, "_stream_once", _fake_stream(_raises_immediately))

    with pytest.raises(RuntimeError):
        asyncio.run(_collect(
            llm.stream_chat("system", "user", role="main", fallback=False)))


def test_backup_role_has_no_second_fallback(monkeypatch):
    monkeypatch.setattr(llm, "resolve", _resolve)

    async def always_fail(*args, **kwargs):
        raise RuntimeError("down")
        yield  # pragma: no cover

    monkeypatch.setattr(llm, "_stream_once", always_fail)

    with pytest.raises(RuntimeError):
        asyncio.run(_collect(
            llm.stream_chat("system", "user", role="backup", fallback=True)))


def test_unconfigured_role_raises(monkeypatch):
    monkeypatch.setattr(llm, "resolve", lambda role: None)
    with pytest.raises(RuntimeError):
        asyncio.run(_collect(llm.stream_chat("system", "user", role="main")))
