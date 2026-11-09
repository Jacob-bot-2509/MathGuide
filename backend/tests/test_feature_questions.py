"""系统能力问题：艾宾浩斯/学习分析必须按实现参数回答，不走模型自由发挥。"""
from __future__ import annotations

import asyncio
import json

import chat


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


def test_feature_questions_are_detected():
    assert chat._is_feature_question("艾宾浩斯曲线是什么")
    assert chat._is_feature_question("知识图谱的遗忘曲线算法")
    assert chat._is_feature_question("复习优先级怎么算")
    assert not chat._is_feature_question("求极限")
    assert not chat._is_feature_question("我的遗忘曲线怎么样")


def test_feature_question_returns_exact_parameters(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("系统能力问题不应进入 RAG 自由发挥")

    monkeypatch.setattr(chat.rag, "search", forbidden)
    monkeypatch.setattr(chat.rag.llm, "is_configured", lambda: True)

    resp = asyncio.run(chat._route_chat(
        "知识图谱的艾宾浩斯曲线算法是什么", None, {}, {"uid": "u"},
        {"role": "main", "research": False}, "learn"))
    text = _joined(resp)

    assert "30+15" in text
    assert "0.6" in text
    assert "不阻断" in text
    assert "复习优先级" in text
