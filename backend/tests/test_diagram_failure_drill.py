"""系统级故障演练:图解任何一层失败,回答正文都必须完整。"""
from __future__ import annotations

import asyncio
import json
import time

import chat
import diagram_metrics
import research_diagrams as rd


async def _collect(generator) -> list[str]:
    return [frame async for frame in generator]


def _joined(frames: list[str]) -> str:
    parts: list[str] = []
    for frame in frames:
        if not frame.startswith("data: "):
            continue
        payload = frame[6:].strip()
        if payload == "[DONE]":
            continue
        try:
            parts.append(json.loads(payload))
        except json.JSONDecodeError:
            continue
    return "".join(part for part in parts if isinstance(part, str))


def _events(frames: list[str]) -> list[dict]:
    return [json.loads(frame[6:].strip()) for frame in frames
            if frame.startswith("data: ") and "mg_event" in frame]


def _stream_parts():
    prefix = "梯度方向是函数增长最快的方向"
    return prefix, prefix + "[[MG_DIAGRAM:relation]]后"


def test_planner_exception_keeps_answer_text(monkeypatch):
    prefix, stream = _stream_parts()

    async def fake_stream(system, user, history=None, role="main"):
        yield stream

    async def broken_plan(*args, **kwargs):
        raise RuntimeError("planner crashed")

    monkeypatch.setattr(chat.rag.llm, "stream_chat", fake_stream)
    monkeypatch.setattr(chat.research_diagrams, "plan_diagram", broken_plan)
    frames = asyncio.run(_collect(chat._gen_llm(
        "怎么理解梯度", None, [], diagram_mode=True,
        diagram_request_id="drill-crash")))
    assert _joined(frames) == prefix + "后"
    assert _events(frames) == []


def test_planner_returns_none_keeps_answer_text(monkeypatch):
    prefix, stream = _stream_parts()

    async def fake_stream(system, user, history=None, role="main"):
        yield stream

    async def empty_plan(*args, **kwargs):
        return None

    monkeypatch.setattr(chat.rag.llm, "stream_chat", fake_stream)
    monkeypatch.setattr(chat.research_diagrams, "plan_diagram", empty_plan)
    frames = asyncio.run(_collect(chat._gen_llm(
        "怎么理解梯度", None, [], diagram_mode=True,
        diagram_request_id="drill-empty")))
    assert _joined(frames) == prefix + "后"
    assert _events(frames) == []


def test_open_breaker_keeps_answer_text(monkeypatch):
    prefix, stream = _stream_parts()
    calls = 0

    async def fake_stream(system, user, history=None, role="main"):
        nonlocal calls
        calls += 1
        yield stream

    monkeypatch.setattr(rd.llm, "is_configured", lambda role="main", **k: True)
    monkeypatch.setattr(chat.rag.llm, "stream_chat", fake_stream)
    monkeypatch.setattr(rd, "_planner_open_until", time.monotonic() + 60)
    frames = asyncio.run(_collect(chat._gen_llm(
        "怎么理解梯度", None, [], diagram_mode=True,
        diagram_request_id="drill-breaker")))
    assert _joined(frames) == prefix + "后"
    assert _events(frames) == []
    # 熔断打开时 planner 不调用模型;主回答的 stream 仍然只调用一次。
    assert calls == 1
    snap = diagram_metrics.snapshot()
    assert snap["counts"].get("plan:fail:breaker", 0) >= 1
