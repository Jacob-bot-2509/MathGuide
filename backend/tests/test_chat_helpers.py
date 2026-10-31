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


def _joined(response) -> str:
    """把 SSE 帧拼回正文,便于断言跨帧文本。"""
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


def test_paper_question_uses_local_context_only(monkeypatch):
    """阅读器/拖拽论文提问:只查本地正文,绝不调用外部文献检索。"""
    _stub_learn_pipeline(monkeypatch)
    monkeypatch.setattr(
        chat.research_corpus, "_doc_row",
        lambda uid, doc_id: {"deletedAt": 0} if doc_id == "d1" else None)
    monkeypatch.setattr(
        chat.research_corpus, "paper_context",
        lambda uid, doc_id, question, top_k=6, max_chars=20000: {
            "title": "测试论文",
            "chunks": [{
                "pageStart": 2, "pageEnd": 2,
                "section": "Methods", "text": "论文正文里记录的实验结果。",
            }],
        })

    def forbidden(*args, **kwargs):
        raise AssertionError("attached paper entered external search")

    monkeypatch.setattr(chat.rag.research, "deep_search", forbidden)

    resp = asyncio.run(chat._route_chat(
        "这篇论文的结论是什么", None,
        {"sessionId": 1, "paperId": "d1"}, {"uid": "u"},
        {"role": "main", "research": False}, "research"))
    text = _joined(resp)
    assert "论文正文里记录的实验结果" in text
    assert "网络或限额" not in text


def test_paper_question_empty_text_does_not_fall_back_to_external(monkeypatch):
    """论文没有可用正文时给出明确提示,不能改为外部检索。"""
    _stub_learn_pipeline(monkeypatch)
    monkeypatch.setattr(
        chat.research_corpus, "_doc_row",
        lambda uid, doc_id: {"deletedAt": 0})
    monkeypatch.setattr(
        chat.research_corpus, "paper_context",
        lambda uid, doc_id, question, top_k=6, max_chars=20000: {
            "title": "测试论文", "chunks": [],
        })

    def forbidden(*args, **kwargs):
        raise AssertionError("empty paper context entered external search")

    monkeypatch.setattr(chat.rag.research, "deep_search", forbidden)

    resp = asyncio.run(chat._route_chat(
        "总结一下", None, {"sessionId": 1, "paperId": "d1"}, {"uid": "u"},
        {"role": "main", "research": False}, "research"))
    text = _joined(resp)
    assert "未能从当前论文中提取到可用正文" in text


def test_paper_question_meta_carries_window_actions(monkeypatch):
    """论文问答的 meta 帧要带模型规划出的窗口动作,前端据此跳页/批注。"""
    _stub_learn_pipeline(monkeypatch)
    monkeypatch.setattr(
        chat.research_corpus, "_doc_row",
        lambda uid, doc_id: {"deletedAt": 0})
    monkeypatch.setattr(
        chat.research_corpus, "paper_context",
        lambda uid, doc_id, question, top_k=6, max_chars=20000: {
            "title": "测试论文",
            "chunks": [{
                "pageStart": 3, "pageEnd": 3,
                "section": "Results", "text": "最适温度是 37 摄氏度。",
            }],
        })

    async def fake_plan(uid, doc_id, question, excerpts=None, history=None):
        return [{
            "type": "highlight", "page": 3,
            "quote": "最适温度是 37 摄氏度。", "query": "最适温度",
        }]

    monkeypatch.setattr(chat.research_actions, "plan_actions", fake_plan)
    meta: dict = {"role": "main", "research": False, "workspace": "research"}
    resp = asyncio.run(chat._route_chat(
        "最适温度在哪一页", None, {"sessionId": 1, "paperId": "d1"}, {"uid": "u"},
        meta, "research"))
    asyncio.run(_collect(resp))
    assert meta["paperActions"] == [{
        "type": "highlight", "page": 3,
        "quote": "最适温度是 37 摄氏度。", "query": "最适温度",
    }]


def test_paper_answer_streams_before_actions(monkeypatch):
    """回答先出字,动作规划完成后在同一流里补发 meta 帧。"""
    async def fake_answer(*args, **kwargs):
        yield 'data: "第一段"\n\n'
        await asyncio.sleep(0.05)
        yield 'data: "第二段"\n\n'

    async def fake_plan(uid, doc_id, question, excerpts=None, history=None):
        await asyncio.sleep(0.01)
        return [{"type": "highlight", "page": 2, "quote": "方法"}]

    monkeypatch.setattr(chat, "_gen_llm", fake_answer)
    monkeypatch.setattr(chat.research_actions, "plan_actions", fake_plan)
    monkeypatch.setattr(chat, "_pick_role", lambda question: "main")

    async def run():
        return [frame async for frame in chat._gen_paper_llm(
            "方法在哪", None, [], uid="u", uid_for_actions="u", doc_id="d1")]

    frames = asyncio.run(run())
    first = next(i for i, frame in enumerate(frames) if "第一段" in frame)
    action = next(i for i, frame in enumerate(frames) if "paper_actions" in frame)
    assert first < action
    payload = json.loads(frames[action][6:].strip())
    assert payload["mg_event"] == "paper_actions"
    assert payload["actions"][0]["type"] == "highlight"
    assert any("第二段" in frame for frame in frames)


def test_paper_import_intent_moves_temp_doc(monkeypatch):
    """拖入论文后要求“先入库”:只对当前论文执行,入库状态回传前端。"""
    _stub_learn_pipeline(monkeypatch)
    monkeypatch.setattr(
        chat.research_corpus, "_doc_row",
        lambda uid, doc_id: {"deletedAt": 0})
    monkeypatch.setattr(
        chat.research_corpus, "paper_context",
        lambda uid, doc_id, question, top_k=6, max_chars=20000: {
            "title": "测试论文",
            "chunks": [{"pageStart": 1, "pageEnd": 1, "section": "摘要",
                        "text": "论文摘要。"}],
        })
    monkeypatch.setattr(
        chat.research_corpus, "get_live_doc",
        lambda uid, doc_id: {"id": doc_id, "status": "temp", "pages": 1})
    called: list[str] = []

    def fake_import(uid, doc_id):
        called.append(doc_id)
        return {"docId": doc_id, "status": "imported"}

    monkeypatch.setattr(chat.research_corpus, "import_temp_doc", fake_import)
    monkeypatch.setattr(
        chat.research_actions, "plan_actions",
        lambda *args, **kwargs: _no_actions())

    meta: dict = {"role": "main", "research": False, "workspace": "research"}
    resp = asyncio.run(chat._route_chat(
        "请先入库这篇论文", None, {"sessionId": 1, "paperId": "d1"}, {"uid": "u"},
        meta, "research"))
    asyncio.run(_collect(resp))
    assert called == ["d1"]
    assert meta["paperImported"]["status"] == "imported"
    assert meta["paperImported"]["docId"] == "d1"


def test_paper_import_requires_explicit_intent(monkeypatch):
    _stub_learn_pipeline(monkeypatch)
    monkeypatch.setattr(
        chat.research_corpus, "_doc_row", lambda uid, doc_id: {"deletedAt": 0})
    monkeypatch.setattr(
        chat.research_corpus, "paper_context",
        lambda uid, doc_id, question, top_k=6, max_chars=20000: {
            "title": "测试论文",
            "chunks": [{"pageStart": 1, "pageEnd": 1, "section": "摘要",
                        "text": "论文摘要。"}],
        })
    monkeypatch.setattr(
        chat.research_corpus, "get_live_doc",
        lambda uid, doc_id: {"id": doc_id, "status": "temp", "pages": 1})
    called: list[str] = []
    monkeypatch.setattr(
        chat.research_corpus, "import_temp_doc",
        lambda uid, doc_id: called.append(doc_id))
    monkeypatch.setattr(
        chat.research_actions, "plan_actions",
        lambda *args, **kwargs: _no_actions())

    meta: dict = {"role": "main", "research": False, "workspace": "research"}
    resp = asyncio.run(chat._route_chat(
        "这篇论文讲了什么", None, {"sessionId": 1, "paperId": "d1"}, {"uid": "u"},
        meta, "research"))
    asyncio.run(_collect(resp))
    assert called == []
    assert "paperImported" not in meta


async def _no_actions():
    return []


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


def test_chat_stream_workspace_from_host(monkeypatch):
    """双域部署:Host 命中 learn./research. 时,服务端以 Host 为准,
    请求体里的 workspace 不能跨区。"""
    from starlette.applications import Starlette
    from starlette.routing import Route
    from starlette.testclient import TestClient

    captured: dict[str, str] = {}

    async def fake_route(prompt, cmd, body, rec, meta, workspace="learn"):
        captured["workspace"] = workspace
        return chat._stream_text("ok")

    monkeypatch.setattr(chat, "require_auth", lambda request: {"uid": "u"})
    monkeypatch.setattr(chat, "_rate_check", lambda uid: None)
    monkeypatch.setattr(chat, "_route_chat", fake_route)
    monkeypatch.setattr(
        chat, "_meter",
        lambda resp, rec, prompt_len, cmd, meta: resp)
    app = Starlette(routes=[Route("/api/chat/stream", chat.chat_stream, methods=["POST"])])
    client = TestClient(app)

    res = client.post("/api/chat/stream", json={"prompt": "q", "workspace": "learn"},
                      headers={"host": "research.example.com"})
    assert res.status_code == 200
    assert captured["workspace"] == "research"

    client.post("/api/chat/stream", json={"prompt": "q", "workspace": "learn"})
    assert captured["workspace"] == "learn"


def test_formula_followup_detection():
    history = [
        {"role": "user", "content": "请先询问我想查哪个具体知识点"},
        {"role": "assistant", "content": "你想查什么?"},
    ]
    assert chat._is_formula_followup(history) is True
    assert chat._is_formula_followup([{"role": "assistant", "content": "x"}]) is False


def test_research_prompt_includes_table_context():
    from rag.research.synthesize import _user_prompt

    prompt = _user_prompt("趋势如何?", [], "【研究数据表】长表\n| A |\n| 1 |")
    assert "【研究数据表" in prompt
    assert "趋势如何?" in prompt


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


def test_retrieval_query_uses_previous_user_turn_for_followup():
    history = [
        {"role": "user", "content": "什么是导数"},
        {"role": "assistant", "content": "导数是瞬时变化率。"},
    ]
    query = chat._retrieval_query("那它和积分有什么关系?", history)
    assert "什么是导数" in query
    assert "积分" in query


def test_retrieval_query_keeps_standalone_question():
    history = [{"role": "user", "content": "什么是导数"}]
    question = "泰勒展开和幂级数有什么关系?"
    assert chat._retrieval_query(question, history) == question
    assert chat._retrieval_query(question, None) == question
