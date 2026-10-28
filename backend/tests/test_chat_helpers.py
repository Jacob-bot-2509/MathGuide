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
    # 用户语料私有:不同用户的答案不得互相复用
    assert chat._research_cache_key("q", None, "u1") != chat._research_cache_key("q", None, "u2")


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


def _stub_learn_pipeline(monkeypatch):
    """让非研究链路可跑完:不命中知识库、未配置 LLM、非数学题。"""
    monkeypatch.setattr(chat.rag.route, "is_research_intent", lambda q: True)
    monkeypatch.setattr(chat.rag, "search", lambda *a, **k: [])
    monkeypatch.setattr(chat.rag.llm, "is_configured", lambda: False)
    monkeypatch.setattr(chat.rag, "is_math_question", lambda q: False)


def test_learn_workspace_never_enters_research_chain(monkeypatch):
    """学习区即使命中研究型措辞,也不得进入跨文献库检索链路。"""
    _stub_learn_pipeline(monkeypatch)

    def forbidden(*args, **kwargs):
        raise AssertionError("learn workspace entered research chain")

    monkeypatch.setattr(chat.rag.research, "deep_search", forbidden)

    resp = asyncio.run(chat._route_chat(
        "泰勒展开的最新研究进展", None, {"sessionId": 1}, {"uid": "u"},
        {"role": "main", "research": False}, "learn"))
    frames = asyncio.run(_collect(resp))
    assert frames, "学习区应正常返回普通回答帧"


def test_research_workspace_enters_research_chain(monkeypatch):
    """科研区才允许触发 deep_search(研究检索链路)。"""
    _stub_learn_pipeline(monkeypatch)
    called: dict[str, bool] = {}

    class Outcome:
        any_hit = False

    async def fake_deep_search(question, top_k=3, scope=None):
        called["yes"] = True
        return Outcome()

    monkeypatch.setattr(chat.rag.research, "deep_search", fake_deep_search)
    monkeypatch.setattr(chat, "_research_reply", lambda outcome, zh: "研究结果")
    chat._RESEARCH_ANSWER.clear()

    resp = asyncio.run(chat._route_chat(
        "泰勒展开的最新研究进展", None, {"sessionId": 1}, {"uid": "u"},
        {"role": "main", "research": False}, "research"))
    frames = asyncio.run(_collect(resp))
    assert called.get("yes") is True
    assert any("研究结果" in f for f in frames)


def test_workspace_from_host():
    import config

    assert config.workspace_from_host("research.mg.example.com") == "research"
    assert config.workspace_from_host("learn.mg.example.com:443") == "learn"
    assert config.workspace_from_host("mg.example.com") == ""
    assert config.workspace_from_host("localhost:5173") == ""
    assert config.workspace_from_host(None) == ""


def test_session_cache_isolates_workspaces():
    import session_cache

    session_cache.reset()
    session_cache.cache_textbook("u", 1, "教材" * 50, workspace="learn")
    assert session_cache.get_textbook("u", 1, workspace="learn")
    assert session_cache.get_textbook("u", 1, workspace="research") == ""

    session_cache.set_summary("u", 1, "摘要", workspace="research")
    assert session_cache.get_summary("u", 1, workspace="research") == "摘要"
    assert session_cache.get_summary("u", 1, workspace="learn") == ""
    assert session_cache.valid_workspace("bogus") == "learn"
    assert session_cache.valid_workspace(None) == "learn"


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
