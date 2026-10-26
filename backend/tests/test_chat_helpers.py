"""chat.py 的纯函数与流式契约:历史校验、范围清洗、限流、字数记账、SSE 收尾。"""
from __future__ import annotations

import asyncio
import json

import pytest
from starlette.exceptions import HTTPException

import chat
from rate_limit import SlidingWindowLimiter


async def _collect(response) -> list[str]:
    return [frame async for frame in response.body_iterator]


def test_validated_history_bounds_and_filters():
    assert chat._validated_history(None) == []
    assert chat._validated_history("x") == []

    valid = [{"role": "user", "content": "x" * 500}] * 20
    out = chat._validated_history(valid)
    assert len(out) == 16
    assert all(len(m["content"]) == 400 for m in out)

    mixed = [
        {"role": "system", "content": "no"},
        {"role": "user", "content": "   "},
        {"role": "assistant", "content": "ok"},
        "not-a-dict",
    ]
    assert chat._validated_history(mixed) == [{"role": "assistant", "content": "ok"}]


def test_strip_meta():
    assert chat._strip_meta("[章节知识导航] 什么是极限", "章节知识导航") == "什么是极限"
    assert chat._strip_meta("章节知识导航: 什么是极限", "章节知识导航") == "什么是极限"
    assert chat._strip_meta("什么是极限", None) == "什么是极限"


def test_clean_scope():
    assert chat._clean_scope(None) is None
    assert chat._clean_scope("arXiv") is None
    assert chat._clean_scope([]) is None
    items = [f"source-{i}" for i in range(20)]
    out = chat._clean_scope(items)
    assert out is not None and len(out) == 12
    assert all(len(s) <= 30 for s in out)


def test_research_cache_key_is_scope_order_independent():
    a = chat._research_cache_key(" 泰勒展开 ", ["arXiv", "zbMATH"])
    b = chat._research_cache_key("泰勒展开", ["zbMATH", "arXiv"])
    assert a == b
    assert chat._research_cache_key("泰勒展开") == chat._research_cache_key("泰勒展开", [])


def test_rate_check_raises_429(monkeypatch):
    monkeypatch.setattr(chat, "_rate_limiter", SlidingWindowLimiter(2, 60))
    chat._rate_check("u")
    chat._rate_check("u")
    with pytest.raises(HTTPException) as exc:
        chat._rate_check("u")
    assert exc.value.status_code == 429


def test_frame_text_len_counts_only_content():
    assert chat._frame_text_len('data: "abc"\n\n') == 3
    assert chat._frame_text_len('data: [DONE]\n\n') == 0
    assert chat._frame_text_len('data: {"mg_meta":{"research":true}}\n\n') == 0
    text = "a\nb\\c"
    frame = f"data: {json.dumps(text, ensure_ascii=False)}\n\n"
    assert chat._frame_text_len(frame) == len(text)


def test_sse_has_exactly_one_done_marker():
    async def gen():
        yield 'data: "a"\n\n'
        yield chat._DONE

    frames = asyncio.run(_collect(chat._sse(gen())))
    assert frames.count(chat._DONE) == 1
    assert frames[0] == 'data: "a"\n\n'


def test_meter_counts_visible_text_not_sse_framing(monkeypatch):
    captured: dict = {}

    def fake_record(rec, **kwargs):
        captured.update(kwargs)

    monkeypatch.setattr(chat, "_record", fake_record)

    async def gen():
        async for frame in chat._frames("你好", pace=False):
            yield frame

    response = chat._meter(
        chat._sse(gen()),
        {"nickname": "n", "uid": "u", "phone": ""},
        prompt_len=2,
        cmd="",
        meta={"role": "main", "research": False},
    )
    asyncio.run(_collect(response))
    assert captured["reply_len"] == 2
    assert captured["role"] == "main"


def test_record_uses_uid_without_identity_fields(monkeypatch):
    captured: dict = {}

    def fake_usage_record(**kwargs):
        captured.update(kwargs)

    monkeypatch.setattr(chat.usage, "record", fake_usage_record)
    chat._record({"uid": "u-1", "nickname": "private", "phone": "13800138000"},
                 cmd="提问", prompt_len=3, reply_len=4, role="main", research=False)
    assert captured["uid"] == "u-1"
    assert "user" not in captured and "phone" not in captured


def test_formula_followup_detection():
    history = [
        {"role": "user", "content": "请先询问我想查哪个具体知识点"},
        {"role": "assistant", "content": "你想查什么?"},
    ]
    assert chat._is_formula_followup(history) is True
    assert chat._is_formula_followup([{"role": "assistant", "content": "x"}]) is False


def test_gen_continue_uses_original_question_and_partial(monkeypatch):
    captured: dict = {}

    async def fake_stream(system, user, role="main", fallback=True, history=None, max_tokens=None):
        captured.update(system=system, user=user, role=role)
        yield "续写内容"

    monkeypatch.setattr(chat.rag.llm, "stream_chat", fake_stream)
    monkeypatch.setattr(chat, "_pick_role", lambda question: "main")

    async def collect():
        return [frame async for frame in chat._gen_continue("原问题", "已经写了一半", True)]

    frames = asyncio.run(collect())
    assert "续写内容" in frames[0]
    assert "已经写了一半" in captured["user"]
    assert "原问题" in captured["user"]
    assert "续写" in captured["system"]
    assert captured["role"] == "main"
