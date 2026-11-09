"""知识点讲解：首轮主干/注意点、缺失笔记降级与追问上下文。"""
from __future__ import annotations

import asyncio
import json

import chat
import pytest
from knowledge_graph import KnowledgeGraph, KnowledgePoint


def _graph() -> KnowledgeGraph:
    points = {
        "p1": KnowledgePoint(
            "p1", "极限", "函数与极限", 3, (), "摘要内容", ("要点一", "要点二")),
        "p2": KnowledgePoint(
            "p2", "连续", "函数与极限", 3, ("p1",)),
    }
    return KnowledgeGraph(points)


def _joined(response) -> str:
    parts: list[str] = []
    for frame in asyncio.run(_collect(response)):
        if not frame.startswith("data: "):
            continue
        payload = frame[6:].strip()
        if payload == "[DONE]":
            continue
        try:
            value = json.loads(payload)
        except json.JSONDecodeError:
            continue
        if isinstance(value, str):
            parts.append(value)
    return "".join(parts)


async def _collect(response) -> list[str]:
    return [frame async for frame in response.body_iterator]


def test_point_lesson_command_uses_notes(monkeypatch):
    captured: dict = {}

    async def fake_stream(system, user, **kwargs):
        captured["system"] = system
        captured["user"] = user
        yield "主干：定义、性质。"

    monkeypatch.setattr(chat.diagnosis, "get_graph", lambda: _graph())
    monkeypatch.setattr(chat.rag.llm, "is_configured", lambda: True)
    monkeypatch.setattr(chat.rag.llm, "stream_chat", fake_stream)

    resp = asyncio.run(chat._route_chat(
        "讲解知识点：极限", "知识点讲解", {"pointId": "p1"}, {"uid": "u"},
        {"role": "main", "research": False}, "learn"))
    text = _joined(resp)

    assert "摘要内容" in captured["system"]
    assert "要点一" in captured["system"]
    assert "主干" in text


def test_point_lesson_unknown_point_returns_friendly_text(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("未知知识点不应调用模型")

    monkeypatch.setattr(chat.diagnosis, "get_graph", lambda: _graph())
    monkeypatch.setattr(chat.rag.llm, "is_configured", lambda: True)
    monkeypatch.setattr(chat.rag.llm, "stream_chat", forbidden)

    resp = asyncio.run(chat._route_chat(
        "讲解知识点：不存在", "知识点讲解", {"pointId": "missing"}, {"uid": "u"},
        {"role": "main", "research": False}, "learn"))
    text = _joined(resp)

    assert "未找到" in text


def test_point_lesson_falls_back_without_llm(monkeypatch):
    monkeypatch.setattr(chat.diagnosis, "get_graph", lambda: _graph())
    monkeypatch.setattr(chat.rag.llm, "is_configured", lambda: False)

    resp = asyncio.run(chat._route_chat(
        "讲解知识点：极限", "知识点讲解", {"pointId": "p1"}, {"uid": "u"},
        {"role": "main", "research": False}, "learn"))
    text = _joined(resp)

    assert "摘要内容" in text
    assert "重点注意点" in text
    assert "要点一" in text


def test_point_context_injected_for_followups(monkeypatch):
    captured: dict = {}

    async def fake_gen(question, cmd, chunks, **kwargs):
        captured["chunks"] = chunks
        yield 'data: "继续讲"\n\n'

    monkeypatch.setattr(chat.diagnosis, "get_graph", lambda: _graph())
    monkeypatch.setattr(chat.rag, "search", lambda *args, **kwargs: [])
    monkeypatch.setattr(chat.rag.llm, "is_configured", lambda: True)
    monkeypatch.setattr(chat, "_gen_llm", fake_gen)
    monkeypatch.setattr(chat, "_pick_role", lambda question: "main")

    resp = asyncio.run(chat._route_chat(
        "再讲讲第二步", None, {"pointId": "p1"}, {"uid": "u"},
        {"role": "main", "research": False}, "learn"))
    text = _joined(resp)

    chunk, score = captured["chunks"][0]
    assert chunk.title == "极限"
    assert "摘要内容" in chunk.text
    assert score == 9.0
    assert "继续讲" in text


def test_point_lesson_ignored_in_research_workspace(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("科研区不应进入知识点讲解")

    monkeypatch.setattr(chat, "_gen_point_lesson", forbidden)
    monkeypatch.setattr(chat.rag, "search", lambda *args, **kwargs: [])
    monkeypatch.setattr(chat.rag.llm, "is_configured", lambda: False)
    monkeypatch.setattr(chat.rag, "is_math_question", lambda question: False)
    monkeypatch.setattr(chat.rag.route, "is_research_intent", lambda question: False)
    monkeypatch.setattr(chat.research_corpus, "chat_hits",
                        lambda *args, **kwargs: [])

    resp = asyncio.run(chat._route_chat(
        "讲解知识点：极限", "知识点讲解", {"pointId": "p1"}, {"uid": "u"},
        {"role": "main", "research": False}, "research"))
    text = _joined(resp)

    assert text
