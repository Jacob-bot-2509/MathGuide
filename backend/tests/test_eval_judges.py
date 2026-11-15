"""评审结果归一化与失败重试。"""
from __future__ import annotations

import asyncio

from evaluation import judges
from evaluation.judges import _normalize
from evaluation.types import EvalItem


def _item() -> EvalItem:
    return EvalItem(id="u", question="q", answer_type="unanswerable",
                    answerable=False)


def test_unanswerable_correct_nonexistence_kept():
    result = _normalize({"correct": True, "refused": False, "claims": []}, _item())
    assert result["correct"] is True


def test_unanswerable_falls_back_to_refused_when_correct_missing():
    result = _normalize({"refused": True, "claims": []}, _item())
    assert result["correct"] is True


def test_judge_retries_once_after_timeout(monkeypatch):
    item = EvalItem(id="q", question="q", reference_answer="a")
    calls = {"n": 0}

    async def fake_stream(system, user, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise TimeoutError("slow")
        yield '{"correct": true, "score": 1, "refused": false, "claims": []}'

    monkeypatch.setattr(judges.llm, "is_configured", lambda role: True)
    monkeypatch.setattr(judges.llm, "stream_chat", fake_stream)
    result = asyncio.run(judges.judge_answer(item, "answer", [], role="backup"))

    assert result["correct"] is True
    assert calls["n"] == 2


def test_judge_stops_after_two_attempts(monkeypatch):
    item = EvalItem(id="q", question="q", reference_answer="a")
    calls = {"n": 0}

    async def fake_stream(system, user, **kwargs):
        calls["n"] += 1
        raise TimeoutError("slow")
        yield ""  # pragma: no cover

    monkeypatch.setattr(judges.llm, "is_configured", lambda role: True)
    monkeypatch.setattr(judges.llm, "stream_chat", fake_stream)
    result = asyncio.run(judges.judge_answer(item, "answer", [], role="backup"))

    assert "error" in result
    assert calls["n"] == 2


def test_judge_uses_reference_solution_and_can_ignore_chunks(monkeypatch):
    item = EvalItem(id="p", question="证明", answer_type="proof",
                    reference_answer="Proof", reference_solution="标准推导步骤")
    captured: dict[str, str] = {}

    async def fake_stream(system, user, **kwargs):
        captured["user"] = user
        yield '{"correct": true, "score": 1, "refused": false, "claims": []}'

    monkeypatch.setattr(judges.llm, "is_configured", lambda role: True)
    monkeypatch.setattr(judges.llm, "stream_chat", fake_stream)
    asyncio.run(judges.judge_answer(item, "答案", [], role="backup",
                                    ground_truth_only=True))

    assert "标准推导步骤" in captured["user"]
    assert "本次判分不使用检索资料" in captured["user"]
