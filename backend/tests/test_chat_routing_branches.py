"""chat.py 的决策分支:路由选型 / 闲聊与降级 / 澄清 / 复核三态 / 图解校验 / 论文问答降级。

只断言**决策结果**(走了哪条分支、返回什么结构、有没有降级/追加更正块),
不断言提示词文案。所有模型调用都打桩,不联网、不碰真实数据目录。
"""
from __future__ import annotations

import asyncio
import json
import time

import pytest
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient

import chat
import chat_routing
import session_cache
import usage

# ---------- 打桩与断言工具 ----------

def _fake_llm(chunks: list[str] | None = None, *, raises: Exception | None = None,
              capture: dict | None = None, fail_after: int | None = None,
              delay: float = 0.0):
    """伪 stream_chat:按需产出增量、在指定增量后抛错、记录入参。"""
    async def stream_chat(system, user, role="main", fallback=True, history=None,
                          max_tokens=None, thinking=None, temperature=None):
        if capture is not None:
            capture.update(system=system, user=user, role=role, history=history,
                           max_tokens=max_tokens, temperature=temperature)
        if delay:
            await asyncio.sleep(delay)
        emitted = 0
        for chunk in chunks or []:
            if fail_after is not None and emitted >= fail_after:
                raise raises or RuntimeError("upstream failure")
            emitted += 1
            yield chunk
        if raises is not None:
            raise raises
    return stream_chat


async def _aiter(gen) -> list[str]:
    return [frame async for frame in gen]


def _collect(gen) -> list[str]:
    return asyncio.run(_aiter(gen))


def _collect_response(resp) -> list[str]:
    return asyncio.run(_aiter(resp.body_iterator))


def _payload(frame: str):
    if not frame.startswith("data: "):
        return None
    raw = frame[6:].strip()
    if raw == "[DONE]":
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


def _joined(frames: list[str]) -> str:
    return "".join(v for v in map(_payload, frames) if isinstance(v, str))


def _events(frames: list[str]) -> list[dict]:
    return [v for v in map(_payload, frames) if isinstance(v, dict) and v.get("mg_event")]


def _meta(frames: list[str]) -> dict:
    for value in map(_payload, frames):
        if isinstance(value, dict) and "mg_meta" in value:
            return value["mg_meta"]
    return {}


def _chunk(text: str = "知识库正文", title: str = "标题") -> tuple:
    return (chat.rag.Chunk("c1", title, "", "第一节", text), 9.0)


def _route(prompt: str, cmd: str | None = None, body: dict | None = None, *,
           workspace: str = "learn", uid: str = "u", meta: dict | None = None):
    meta = dict(meta or {"role": "main", "research": False, "workspace": workspace})
    resp = asyncio.run(chat._route_chat(
        prompt, cmd, dict(body or {}), {"uid": uid}, meta, workspace))
    return resp, meta


def _text_route(prompt: str, cmd: str | None = None, body: dict | None = None, **kwargs):
    resp, meta = _route(prompt, cmd, body, **kwargs)
    return _joined(_collect_response(resp)), meta


def _offline(monkeypatch, *, research_intent: bool = False, math: bool = False):
    """离线基线:未配置模型、检索不命中、非研究意图、无私有语料。"""
    monkeypatch.setattr(chat.rag.llm, "is_configured", lambda *a, **k: False)
    monkeypatch.setattr(chat.rag, "search", lambda *a, **k: [])
    monkeypatch.setattr(chat.rag.route, "is_research_intent", lambda q: research_intent)
    monkeypatch.setattr(chat.rag, "is_math_question", lambda q: math)
    monkeypatch.setattr(chat.research_corpus, "chat_hits", lambda *a, **k: [])
    monkeypatch.setattr(chat.research_corpus, "corpus_stamp", lambda uid: "stamp")
    monkeypatch.setattr(chat.research_corpus, "_doc_row", lambda uid, doc_id: None)


@pytest.fixture(autouse=True)
def _clean_caches():
    chat._RESEARCH_ANSWER.clear()
    chat._INTUITION_CACHE.clear()
    yield
    chat._RESEARCH_ANSWER.clear()
    chat._INTUITION_CACHE.clear()


# ---------- 复核三态:_verify_answer ----------

def test_verify_answer_maps_verdicts(monkeypatch):
    """correct / wrong / uncertain 原样透传;非法取值一律归为 uncertain。"""
    cases = [
        ('{"verdict":"correct","issue":"过程无误","correction":""}', "correct"),
        ('{"verdict":"wrong","issue":"符号写错","correction":"x=2"}', "wrong"),
        ('{"verdict":"uncertain","issue":"条件不足"}', "uncertain"),
        ('{"verdict":"maybe","issue":"?"}', "uncertain"),
        ('{"verdict":"有误","issue":"?"}', "uncertain"),
    ]
    for payload, expected in cases:
        monkeypatch.setattr(chat.rag.llm, "stream_chat", _fake_llm([payload]))
        verdict = asyncio.run(chat._verify_answer("1+1=?", "答案是 3", "deep"))
        assert verdict["verdict"] == expected

    monkeypatch.setattr(chat.rag.llm, "stream_chat", _fake_llm(
        ['{"verdict":"wrong","issue":"符号写错","correction":"x=2"}']))
    wrong = asyncio.run(chat._verify_answer("1+1=?", "答案是 3", "deep"))
    assert wrong["correction"] == "x=2"
    assert wrong["issue"] == "符号写错"


def test_verify_answer_degrades_to_uncertain(monkeypatch):
    """只给一句话 / 给数组 / 一字未出 / 调用异常 → 不判错、不打断主回答。"""
    monkeypatch.setattr(chat.rag.llm, "stream_chat", _fake_llm(["结论正确,没有问题"]))
    plain = asyncio.run(chat._verify_answer("q", "a", "main"))
    assert plain["verdict"] == "uncertain"
    assert plain["issue"] == "结论正确,没有问题"
    assert plain["correction"] == ""

    monkeypatch.setattr(chat.rag.llm, "stream_chat", _fake_llm(["[1,2]"]))
    assert asyncio.run(chat._verify_answer("q", "a", "main"))["verdict"] == "uncertain"

    monkeypatch.setattr(chat.rag.llm, "stream_chat", _fake_llm([]))
    assert asyncio.run(chat._verify_answer("q", "a", "main")) is None

    monkeypatch.setattr(chat.rag.llm, "stream_chat", _fake_llm(raises=RuntimeError("429")))
    assert asyncio.run(chat._verify_answer("q", "a", "main")) is None


# ---------- 复核三态接线:_gen_llm(verify=True) ----------

def _verify_reply(monkeypatch, verdict: dict | None, *, role: str = "main",
                  workspace: str = "learn") -> tuple[str, dict]:
    monkeypatch.setattr(chat.rag.llm, "stream_chat", _fake_llm(["正文回答"]))
    monkeypatch.setattr(chat.rag.llm, "pick", lambda name: name)
    captured: dict = {}

    async def fake_verify(question, answer, vrole):
        captured["vrole"] = vrole
        return verdict

    monkeypatch.setattr(chat, "_verify_answer", fake_verify)
    frames = _collect(chat._gen_llm(
        "1+1=?", None, [], role=role, verify=True, workspace=workspace))
    return _joined(frames), captured


def test_verify_wrong_appends_correction_block_before_review_line(monkeypatch):
    """wrong + correction:先追加「更正」块,再追加复核行(评测只剥末尾复核行)。"""
    text, captured = _verify_reply(
        monkeypatch, {"verdict": "wrong", "issue": "1+1 应为 2", "correction": "1+1=2"})
    assert text.startswith("正文回答")
    assert "**更正**" in text and "1+1=2" in text
    assert "有误" in text and "1+1 应为 2" in text
    assert text.index("**更正**") < text.index("🔍 复核")
    assert "cmd://nb/yes" in text          # learn 区追加问题记录入口
    assert captured["vrole"] == "deep"     # main 解答 → deep 复核


def test_verify_correct_and_uncertain_do_not_append_correction(monkeypatch):
    text, _ = _verify_reply(
        monkeypatch, {"verdict": "correct", "issue": "", "correction": ""})
    assert "**更正**" not in text
    assert "正确" in text

    text, _ = _verify_reply(
        monkeypatch, {"verdict": "wrong", "issue": "存疑", "correction": ""})
    assert "**更正**" not in text          # 有 verdict 无 correction 不追加更正块
    assert "有误" in text

    text, _ = _verify_reply(
        monkeypatch, {"verdict": "uncertain", "issue": "条件不足", "correction": ""})
    assert "需人工复核" in text


def test_verify_skipped_when_unavailable_and_role_deep_verified_by_main(monkeypatch):
    # 复核不可用 → 不追加复核行,但问题记录入口照旧
    text, _ = _verify_reply(monkeypatch, None)
    assert "🔍 复核" not in text
    assert "cmd://nb/yes" in text

    # deep 解答 → main 复核(角色错开);科研区不追问问题记录
    text, captured = _verify_reply(
        monkeypatch, {"verdict": "correct", "issue": "", "correction": ""},
        role="deep", workspace="research")
    assert captured["vrole"] == "main"
    assert "cmd://nb/yes" not in text



# ---------- 模型侧失败:降级直答 vs 中断提示 ----------

def test_gen_llm_failure_before_output_falls_back_to_kb(monkeypatch):
    monkeypatch.setattr(chat.rag.llm, "stream_chat", _fake_llm(
        raises=RuntimeError("upstream 429")))
    text = _joined(_collect(chat._gen_llm("什么是夹逼定理", None, [_chunk("夹逼定理正文")])))
    assert "知识库直答" in text
    assert "夹逼定理正文" in text


def test_gen_llm_failure_after_output_only_adds_interrupt_note(monkeypatch):
    """已经流出一部分 → 只追加中断提示,不回放直答(避免答案拼接两遍)。"""
    monkeypatch.setattr(chat.rag.llm, "stream_chat", _fake_llm(
        ["半截回答"], raises=TimeoutError("read timeout"), fail_after=1))
    text = _joined(_collect(chat._gen_llm("什么是夹逼定理", None, [_chunk("夹逼定理正文")])))
    assert text.startswith("半截回答")
    assert "中断" in text
    assert "知识库直答" not in text
    assert "夹逼定理正文" not in text


def test_gen_llm_cancel_propagates(monkeypatch):
    """客户端断开 → CancelledError 继续上抛(不被降级分支吞成正常回复)。"""
    async def fake_stream(system, user, **kwargs):
        raise asyncio.CancelledError
        yield  # 先抛错:这里的 yield 只为让函数成为 async generator

    monkeypatch.setattr(chat.rag.llm, "stream_chat", fake_stream)

    async def run():
        with pytest.raises(asyncio.CancelledError):
            async for _frame in chat._gen_llm("画图", None, [], diagram_mode=True,
                                              diagram_question="画图",
                                              diagram_request_id="r-cancel"):
                pass

    asyncio.run(run())


# ---------- 会话摘要与电表 ----------

def test_update_summary_writes_and_skips_on_failure(monkeypatch):
    session_cache.reset()
    monkeypatch.setattr(chat.rag.llm, "stream_chat", _fake_llm(["早前聊了极限与导数"]))
    asyncio.run(chat._update_summary(
        "u", 7, [{"role": "user", "content": "什么是极限"},
                 {"role": "assistant", "content": "夹逼"}], ""))
    assert session_cache.get_summary("u", 7) == "早前聊了极限与导数"

    session_cache.reset()
    monkeypatch.setattr(chat.rag.llm, "stream_chat", _fake_llm(raises=RuntimeError("boom")))
    asyncio.run(chat._update_summary("u", 8, [{"role": "user", "content": "x"}], "旧摘要"))
    assert session_cache.get_summary("u", 8) == ""


def test_summary_tick_triggers_background_compression(monkeypatch):
    """第 8 的倍数次长会话请求触发后台摘要,其余不触发。"""
    monkeypatch.setattr(chat.rag.llm, "stream_chat", _fake_llm(["回答"]))
    monkeypatch.setattr(chat, "get_summary", lambda *a, **k: "")
    recorded: list[tuple] = []

    async def fake_update(uid, sid, turns, prev, workspace="learn"):
        recorded.append((uid, sid, len(turns)))

    monkeypatch.setattr(chat, "_update_summary", fake_update)
    history = [{"role": "user", "content": f"问题{i}"} for i in range(16)]

    async def run():
        frames = [f async for f in chat._gen_llm("问题", None, [], history=history,
                                                 sid=3, uid="u")]
        await asyncio.sleep(0.01)
        return frames

    monkeypatch.setattr(chat, "bump_tick", lambda *a, **k: 8)
    asyncio.run(run())
    assert recorded == [("u", 3, 8)]

    recorded.clear()
    monkeypatch.setattr(chat, "bump_tick", lambda *a, **k: 7)
    asyncio.run(run())
    assert recorded == []


def test_meter_counts_text_and_survives_record_failure(monkeypatch):
    resp = chat._stream_text("回答正文")
    metered = chat._meter(resp, {"uid": "u"}, 4, "", {"role": "main", "research": False})
    assert _joined(_collect_response(metered)) == "回答正文"

    def boom(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(chat, "_record", boom)
    resp = chat._stream_text("再来一次")
    metered = chat._meter(resp, {"uid": "u"}, 4, "", {"role": "main", "research": False})
    assert _joined(_collect_response(metered)) == "再来一次"




# ---------- 研究检索:无命中/命中/综合失败三种形态 ----------

def _outcome(**kwargs):
    params = {"question": "q", "hits": [], "sources": {}, "errors": []}
    params.update(kwargs)
    return chat.rag.research.SearchOutcome(**params)


def _hit(**kwargs):
    params = {"source": "arXiv", "title": "论文标题", "snippet": "摘要片段",
              "authors": "张三", "year": 2024, "url": "https://example.org/a",
              "score": 0.91}
    params.update(kwargs)
    return chat.SearchHit(**params)


def test_research_reply_reports_unreachable_sources_when_no_hit():
    zh = chat._research_reply(_outcome(errors=["arXiv", "zbMATH"]), True)
    assert "arXiv" in zh and "zbMATH" in zh
    assert "暂未找到高置信来源" in zh

    en = chat._research_reply(_outcome(errors=["arXiv"]), False)
    assert "unreachable: arXiv" in en

    plain_en = chat._research_reply(_outcome(), False)
    assert "network or rate limits" in plain_en


def test_research_reply_lists_hits_and_marks_local_source():
    outcome = _outcome(
        hits=[_hit(), _hit(source="zbMATH", title="第二条", url="")],
        sources={"arXiv": 8, "zbMATH": 3}, errors=["Semantic Scholar"])
    text = chat._research_reply(outcome, True)
    assert "2 条高置信来源" in text
    assert "arXiv 1" in text and "zbMATH 1" in text   # 统计口径按真正入选条数
    assert "🔗 https://example.org/a" in text
    assert "📚 来源:本地知识库" in text
    assert "Semantic Scholar" in text


def test_gen_research_streams_text_citations_and_caches(monkeypatch):
    async def fake_synth(question, hits, zh, role="main", fallback=True, extra=""):
        yield "综合正文"
        yield "结尾"

    monkeypatch.setattr(chat.rag.research.synthesize, "synthesize_stream", fake_synth)
    monkeypatch.setattr(chat.rag.research.synthesize, "citations_block",
                        lambda hits, zh: "\n---\n引用区")
    frames = _collect(chat._gen_research(
        "泰勒展开最新进展", _outcome(hits=[_hit()]), True, ck="cache-key"))
    text = _joined(frames)
    assert text == "综合正文结尾\n---\n引用区"
    assert chat._RESEARCH_ANSWER["cache-key"][1] == text
    assert _events(frames) == []


def test_gen_research_falls_back_to_source_list_when_synthesis_fails(monkeypatch):
    async def fake_synth(*args, **kwargs):
        raise RuntimeError("deep role 429")
        yield  # 先抛错:这里的 yield 只为让函数成为 async generator

    monkeypatch.setattr(chat.rag.research.synthesize, "synthesize_stream", fake_synth)
    monkeypatch.setattr(chat, "_research_reply", lambda outcome, zh: "来源列表兜底")
    frames = _collect(chat._gen_research("问题", _outcome(hits=[_hit()]), True))
    assert "来源列表兜底" in _joined(frames)
    assert chat._RESEARCH_ANSWER == {}   # 没有 ck 时不写缓存


def test_gen_research_partial_failure_keeps_text_and_skips_list(monkeypatch):
    async def fake_synth(*args, **kwargs):
        yield "半截综述"
        raise TimeoutError("read timeout")

    def forbidden(outcome, zh):
        raise AssertionError("不应回放来源列表")

    monkeypatch.setattr(chat.rag.research.synthesize, "synthesize_stream", fake_synth)
    monkeypatch.setattr(chat, "_research_reply", forbidden)
    text = _joined(_collect(chat._gen_research("问题", _outcome(hits=[_hit()]), True)))
    assert text.startswith("半截综述")
    assert "中断" in text


def test_gen_research_diagram_failure_does_not_break_summary(monkeypatch):
    async def fake_synth(question, hits, zh, role="main", fallback=True, extra=""):
        yield "综述正文"

    async def failing_plan(*args, **kwargs):
        raise RuntimeError("planner down")

    monkeypatch.setattr(chat.rag.research.synthesize, "synthesize_stream", fake_synth)
    monkeypatch.setattr(chat.rag.research.synthesize, "citations_block",
                        lambda hits, zh: "")
    monkeypatch.setattr(chat.research_diagrams, "plan_diagram", failing_plan)
    frames = _collect(chat._gen_research(
        "问题", _outcome(hits=[_hit()]), True, diagrams=True, request_id="r1"))
    assert _joined(frames) == "综述正文"
    assert _events(frames) == []


def test_gen_research_emits_diagram_event_when_planned(monkeypatch):
    async def fake_synth(question, hits, zh, role="main", fallback=True, extra=""):
        yield "综述正文"

    async def fake_plan(*args, **kwargs):
        return {"type": "relation", "nodes": [{"id": "a", "label": "A"}],
                "edges": [], "shapes": [], "annotations": []}

    monkeypatch.setattr(chat.rag.research.synthesize, "synthesize_stream", fake_synth)
    monkeypatch.setattr(chat.rag.research.synthesize, "citations_block",
                        lambda hits, zh: "")
    monkeypatch.setattr(chat.research_diagrams, "plan_diagram", fake_plan)
    frames = _collect(chat._gen_research(
        "问题", _outcome(hits=[_hit()]), True, diagrams=True, request_id="r2"))
    events = _events(frames)
    assert len(events) == 1 and events[0]["mg_event"] == "diagram"


# ---------- 路由选型:角色(deep/main)与降级 ----------

def test_pick_role_falls_back_to_main_when_deep_provider_missing(monkeypatch):
    for name in ("MG_ALIYUN_BASE_URL", "MG_ALIYUN_API_KEY", "MG_ROLE_DEEP"):
        monkeypatch.delenv(name, raising=False)
    assert chat._pick_role("请证明这个不等式") == "main"   # deep 未配置 → 回退 main

    monkeypatch.setenv("MG_ALIYUN_BASE_URL", "https://example.invalid/v1")
    monkeypatch.setenv("MG_ALIYUN_API_KEY", "k")
    monkeypatch.setenv("MG_ROLE_DEEP", "aliyun:deep-model")
    assert chat._pick_role("请证明这个不等式") == "deep"  # 显式配置 → 走 deep
    assert chat._pick_role("什么是极限") == "main"


# ---------- 续写(被中断的回答) ----------

def test_route_resume_without_partial_returns_hint(monkeypatch):
    _offline(monkeypatch)
    text, _ = _text_route("接着讲", body={"resume": True, "partial": "   "})
    assert "没有可续写的内容" in text


def test_route_resume_streams_continuation_without_retrieval(monkeypatch):
    _offline(monkeypatch)
    captured: dict = {}

    async def fake_continue(question, partial, zh):
        captured.update(question=question, partial=partial, zh=zh)
        yield 'data: "续写"\n\n'

    monkeypatch.setattr(chat, "_gen_continue", fake_continue)

    def forbidden(*args, **kwargs):
        raise AssertionError("续写不应重新检索")

    monkeypatch.setattr(chat.rag, "search", forbidden)
    text, meta = _text_route("原问题", body={"resume": True, "partial": "已写一半"})
    assert text == "续写"
    assert captured == {"question": "原问题", "partial": "已写一半", "zh": True}
    assert meta["role"] == "main"


def test_gen_continue_failure_reports_instead_of_rewriting(monkeypatch):
    monkeypatch.setattr(chat.rag.llm, "stream_chat", _fake_llm(
        ["不该出现"], raises=RuntimeError("deep 超时"), fail_after=1))
    text = _joined(_collect(chat._gen_continue("原问题", "已写一半", True)))
    assert "续写失败" in text
    assert "已写一半" not in text


# ---------- 附件消息:回执 vs 长文阅读 ----------

def test_route_attach_text_goes_to_long_reader(monkeypatch):
    _offline(monkeypatch)
    monkeypatch.setattr(chat.rag.llm, "is_configured", lambda *a, **k: True)
    called: dict = {}

    async def fake_attach(name, body, zh):
        called.update(name=name, body=body, zh=zh)
        yield 'data: "已阅读"\n\n'

    monkeypatch.setattr(chat, "_gen_attach_llm", fake_attach)
    text, meta = _text_route("[attach:file]笔记.txt\n\n导数的定义是……")
    assert text == "已阅读"
    assert called == {"name": "笔记.txt", "body": "导数的定义是……", "zh": True}
    assert meta["role"] == "long"


def test_route_attach_receipt_when_llm_missing_or_image(monkeypatch):
    _offline(monkeypatch)
    text, meta = _text_route("[attach:file]讲义.pdf\n\n正文")
    assert "讲义.pdf" in text            # 未配置模型 → 接收回执,不调模型
    assert meta["role"] == "main"

    text, _ = _text_route("[attach:image]图.png")
    assert "图.png" in text and "图片" in text

    text, _ = _text_route("[attach:file]lecture.pdf")   # 英文 → EN 回执
    assert "lecture.pdf" in text and "metadata only" in text


def test_gen_attach_llm_degrades_by_stream_position(monkeypatch):
    monkeypatch.setattr(chat.rag.llm, "stream_chat", _fake_llm(
        raises=RuntimeError("429"), delay=0))
    text = _joined(_collect(chat._gen_attach_llm("a.txt", "正文", True)))
    assert "a.txt" in text               # 一字未出 → 回执(不假死)

    monkeypatch.setattr(chat.rag.llm, "stream_chat", _fake_llm(
        ["读到一半"], raises=RuntimeError("read timeout"), fail_after=1))
    text = _joined(_collect(chat._gen_attach_llm("a.txt", "正文", True)))
    assert "读到一半" in text and "中断" in text


# ---------- 章节导航 / 章节指引 ----------

def test_route_nav_requires_configured_llm(monkeypatch):
    _offline(monkeypatch)
    text, _ = _text_route("第一章 函数", "章节知识导航")
    assert "章节导航需要已配置 LLM" in text


def test_route_nav_list_caches_textbook_for_later_guides(monkeypatch):
    _offline(monkeypatch)
    monkeypatch.setattr(chat.rag.llm, "is_configured", lambda *a, **k: True)
    session_cache.reset()
    textbook = "第一章 函数与极限 " * 20   # >=80 字才入缓存(见 session_cache)

    async def fake_nav(question):
        yield 'data: "章节列表"\n\n'

    monkeypatch.setattr(chat, "_gen_nav_list", fake_nav)
    text, meta = _text_route(textbook, "章节知识导航", {"sessionId": 5})
    assert text == "章节列表"
    assert meta["role"] == "long"
    assert session_cache.get_textbook("u", 5) == textbook.strip()


def test_route_nav_guide_reads_cached_textbook(monkeypatch):
    _offline(monkeypatch)
    monkeypatch.setattr(chat.rag.llm, "is_configured", lambda *a, **k: True)
    session_cache.reset()
    textbook = "第二章 导数与微分 " * 20
    session_cache.cache_textbook("u", 6, textbook)
    captured: dict = {}

    async def fake_guide(question, tb=""):
        captured.update(question=question, tb=tb)
        yield 'data: "该章指引"\n\n'

    monkeypatch.setattr(chat, "_gen_nav_guide", fake_guide)
    text, meta = _text_route("第二章 极限", "章节知识指引", {"sessionId": 6})
    assert text == "该章指引"
    assert meta["role"] == "long"
    assert captured["tb"] == textbook


def test_gen_nav_list_and_guide_degrade_by_stream_position(monkeypatch):
    monkeypatch.setattr(chat.rag.llm, "stream_chat", _fake_llm(raises=RuntimeError("boom")))
    assert "章节导航调用失败" in _joined(_collect(chat._gen_nav_list("教材")))
    assert "章节指引调用失败" in _joined(_collect(chat._gen_nav_guide("第二章")))

    monkeypatch.setattr(chat.rag.llm, "stream_chat", _fake_llm(
        ["开头"], raises=RuntimeError("boom"), fail_after=1))
    assert "章节导航中断" in _joined(_collect(chat._gen_nav_list("教材")))
    assert "章节指引中断" in _joined(_collect(chat._gen_nav_guide("第二章")))


def test_gen_nav_guide_appends_back_button_only_on_success(monkeypatch):
    monkeypatch.setattr(chat.rag.llm, "stream_chat", _fake_llm(["指引正文"]))
    text = _joined(_collect(chat._gen_nav_guide("第二章", tb="教材")))
    assert "指引正文" in text and "cmd://back" in text


# ---------- 公式手册:澄清第一步(不检索、独立复核、失败降级) ----------

def test_route_formula_clarify_skips_retrieval(monkeypatch):
    _offline(monkeypatch)

    def forbidden(*args, **kwargs):
        raise AssertionError("澄清第一步不应检索知识库")

    monkeypatch.setattr(chat.rag, "search", forbidden)

    async def fake_clarify(question):
        yield 'data: "你想查哪个知识点?"\n\n'

    monkeypatch.setattr(chat, "_gen_formula_clarify", fake_clarify)
    text, _ = _text_route(chat._CLARIFY_ZH, "公式查询手册")
    assert text == "你想查哪个知识点?"


def test_gen_formula_clarify_streams_then_appends_review(monkeypatch):
    monkeypatch.setattr(chat.rag.llm, "stream_chat", _fake_llm(["你想查哪个知识点?"]))
    monkeypatch.setattr(chat.rag.llm, "pick", lambda role: "deep")

    async def fake_verify(question, answer, role):
        return "符合要求:只问了知识点"

    monkeypatch.setattr(chat, "_verify_clarify", fake_verify)
    text = _joined(_collect(chat._gen_formula_clarify("极限公式")))
    assert "你想查哪个知识点?" in text
    assert "复核(deep)" in text


def test_gen_formula_clarify_degrades_by_stream_position(monkeypatch):
    monkeypatch.setattr(chat.rag.llm, "stream_chat", _fake_llm(raises=RuntimeError("429")))
    text = _joined(_collect(chat._gen_formula_clarify("极限公式")))
    assert "知识点" in text                  # 静态澄清语,面板点击绝不无回应
    assert "中断" not in text

    monkeypatch.setattr(chat.rag.llm, "stream_chat", _fake_llm(
        ["半截提问"], raises=RuntimeError("boom"), fail_after=1))
    text = _joined(_collect(chat._gen_formula_clarify("极限公式")))
    assert "半截提问" in text and "中断" in text


def test_verify_clarify_returns_text_or_none(monkeypatch):
    monkeypatch.setattr(chat.rag.llm, "stream_chat", _fake_llm(["符合要求"]))
    assert asyncio.run(chat._verify_clarify("q", "a", "deep")) == "符合要求"

    monkeypatch.setattr(chat.rag.llm, "stream_chat", _fake_llm([]))
    assert asyncio.run(chat._verify_clarify("q", "a", "deep")) is None

    monkeypatch.setattr(chat.rag.llm, "stream_chat", _fake_llm(raises=RuntimeError("x")))
    assert asyncio.run(chat._verify_clarify("q", "a", "deep")) is None


# ---------- 当前论文问答:本地正文 / 入库失败 / 动作规划失败 ----------

def _paper(monkeypatch, *, chunks: list[dict] | None = None, llm: bool = False):
    _offline(monkeypatch)
    monkeypatch.setattr(chat.rag.llm, "is_configured", lambda *a, **k: llm)
    monkeypatch.setattr(chat.research_corpus, "_doc_row",
                        lambda uid, doc_id: {"deletedAt": 0})
    payload = chunks if chunks is not None else [
        {"pageStart": 2, "pageEnd": 3, "section": "Methods", "text": "正文片段"}]
    monkeypatch.setattr(
        chat.research_corpus, "paper_context",
        lambda uid, doc_id, question="", top_k=6, max_chars=20000: {
            "title": "测试论文", "chunks": payload})


def test_paper_doc_validation_failure_keeps_normal_chat(monkeypatch):
    _offline(monkeypatch)
    monkeypatch.setattr(chat.rag.route, "is_research_intent", lambda q: True)

    def boom(uid, doc_id):
        raise RuntimeError("db down")

    monkeypatch.setattr(chat.research_corpus, "_doc_row", boom)
    called: dict = {}

    async def fake_deep(question, top_k=3, scope=None):
        called["deep"] = True
        return _outcome(errors=["arXiv"])

    monkeypatch.setattr(chat.rag.research, "deep_search", fake_deep)
    text, _ = _text_route("聊聊这个研究方向", body={"paperId": "d1"},
                          workspace="research")
    assert called.get("deep") is True      # 论文校验失败 → 退回普通科研链路
    assert "arXiv" in text


def test_paper_import_failure_reported_in_meta(monkeypatch):
    _paper(monkeypatch)

    def boom(uid, doc_id):
        raise RuntimeError("权限不足")

    monkeypatch.setattr(chat.research_corpus, "get_live_doc", boom)

    async def no_actions(*args, **kwargs):
        return []

    monkeypatch.setattr(chat.research_actions, "plan_actions", no_actions)
    text, meta = _text_route("把这篇论文入库", body={"paperId": "d1"},
                             workspace="research")
    assert meta["paperImported"]["status"] == "failed"
    assert "权限不足" in meta["paperImported"]["reason"]
    assert text                            # 入库失败仍给出回答


def test_paper_action_planner_failure_keeps_answer(monkeypatch):
    _paper(monkeypatch)

    async def boom(*args, **kwargs):
        raise RuntimeError("planner down")

    monkeypatch.setattr(chat.research_actions, "plan_actions", boom)
    text, meta = _text_route("最适温度在哪一页", body={"paperId": "d1"},
                             workspace="research")
    assert "paperActions" not in meta
    assert "正文片段" in text


def test_paper_llm_path_streams_answer_with_request_id(monkeypatch):
    _paper(monkeypatch, llm=True)
    captured: dict = {}

    async def fake_paper(question, cmd, chunks, **kwargs):
        captured.update(question=question, chunks=chunks, **kwargs)
        yield 'data: "论文回答"\n\n'

    monkeypatch.setattr(chat, "_gen_paper_llm", fake_paper)
    text, meta = _text_route("这篇论文的结论是什么",
                             body={"paperId": "d1", "sessionId": 9},
                             workspace="research")
    assert text == "论文回答"
    assert captured["doc_id"] == "d1"
    assert captured["request_id"]
    assert captured["workspace"] == "research"
    assert meta["role"] == "main"




# ---------- 科研链路:缓存命中 / 私有语料 / 综合与否 ----------

def test_research_cache_hit_replays_without_search(monkeypatch):
    _offline(monkeypatch, research_intent=True)
    monkeypatch.setattr(chat.rag.llm, "is_configured", lambda *a, **k: True)
    monkeypatch.setattr(chat, "_research_cache_key", lambda *a, **k: "ck")
    chat._RESEARCH_ANSWER["ck"] = (time.monotonic(), "缓存综述")

    def forbidden(*args, **kwargs):
        raise AssertionError("命中缓存不应再检索")

    monkeypatch.setattr(chat.rag.research, "deep_search", forbidden)
    text, meta = _text_route("泰勒展开的最新进展", workspace="research")
    assert text == "缓存综述"
    assert meta["role"] == "deep"
    assert meta["research"] is True


def test_research_cache_expiry_retries_and_rewrites(monkeypatch):
    _offline(monkeypatch, research_intent=True)
    monkeypatch.setattr(chat.rag.llm, "is_configured", lambda *a, **k: True)
    monkeypatch.setattr(chat, "_research_cache_key", lambda *a, **k: "ck-old")
    chat._RESEARCH_ANSWER["ck-old"] = (time.monotonic() - 10_000, "过期综述")
    called: dict = {}

    async def fake_deep(question, top_k=3, scope=None):
        called["deep"] = True
        return _outcome(hits=[_hit()])

    monkeypatch.setattr(chat.rag.research, "deep_search", fake_deep)
    captured: dict = {}

    async def fake_gen(question, outcome, zh, **kwargs):
        captured.update(kwargs)
        yield 'data: "新综述"\n\n'

    monkeypatch.setattr(chat, "_gen_research", fake_gen)
    text, _ = _text_route("泰勒展开的最新进展", body={"diagrams": True},
                          workspace="research")
    assert called.get("deep") is True
    assert text == "新综述"
    assert captured["ck"] == "ck-old"        # 新结果回写同一缓存键
    assert captured["diagrams"] is True


def test_research_prepends_private_corpus_hits(monkeypatch):
    _offline(monkeypatch, research_intent=True)
    monkeypatch.setattr(chat.rag.llm, "is_configured", lambda *a, **k: True)
    monkeypatch.setattr(chat, "_research_cache_key", lambda *a, **k: "ck-corpus")

    async def fake_deep(question, top_k=3, scope=None):
        return _outcome()

    monkeypatch.setattr(chat.rag.research, "deep_search", fake_deep)
    monkeypatch.setattr(
        chat.research_corpus, "chat_hits",
        lambda uid, question, top_k=4, doc_id=None: [{
            "docName": "我的论文", "section": "引言", "pageStart": 1, "pageEnd": 2,
            "snippet": "私有片段"}])
    captured: dict = {}

    async def fake_gen(question, outcome, zh, **kwargs):
        captured["outcome"] = outcome
        yield 'data: "综述"\n\n'

    monkeypatch.setattr(chat, "_gen_research", fake_gen)
    text, meta = _text_route("最新研究进展", workspace="research")
    hits = captured["outcome"].hits
    assert hits[0].source == "我的论文"      # 私有语料排外部来源之前
    assert "第 1-2 页" in hits[0].title
    assert captured["outcome"].sources["我的论文"] == 1
    assert text == "综述"
    assert meta["role"] == "deep"


def test_research_corpus_failure_does_not_block_external_search(monkeypatch):
    _offline(monkeypatch, research_intent=True)
    monkeypatch.setattr(chat, "_research_cache_key", lambda *a, **k: "ck-fail")

    async def fake_deep(question, top_k=3, scope=None):
        return _outcome()

    def boom(*args, **kwargs):
        raise RuntimeError("index broken")

    monkeypatch.setattr(chat.rag.research, "deep_search", fake_deep)
    monkeypatch.setattr(chat.research_corpus, "chat_hits", boom)
    text, _ = _text_route("最新研究进展", workspace="research")
    assert "暂未找到高置信来源" in text



# ---------- 数据表回归:重算 / 过期标记 / 失败降级 ----------

def _regression_env(monkeypatch, result: dict | None = None, raises: Exception | None = None):
    _offline(monkeypatch)
    monkeypatch.setattr(chat.rag.llm, "is_configured", lambda *a, **k: True)
    monkeypatch.setattr(chat.research_tables, "_get_table", lambda uid, table_id: {
        "columns": [{"key": "A"}, {"key": "B"}],
        "rows": [["1", "2"]], "formulas": {}, "updatedAt": 100})
    summaries: list[str] = []

    def context_text(table, summary=""):
        summaries.append(summary)
        return f"CTX:{summary}"

    monkeypatch.setattr(chat.research_tables, "context_text", context_text)

    async def fake_run(payload, timeout=30.0):
        if raises is not None:
            raise raises
        return result

    monkeypatch.setattr(chat.analysis_client, "run_analysis", fake_run)

    async def fake_deep(question, top_k=3, scope=None):
        return _outcome()

    monkeypatch.setattr(chat.rag.research, "deep_search", fake_deep)
    monkeypatch.setattr(chat, "_research_cache_key", lambda *a, **k: "ck-table")
    captured: dict = {}

    async def fake_gen(question, outcome, zh, **kwargs):
        captured["extra"] = kwargs.get("extra")
        yield 'data: "回归解读"\n\n'

    monkeypatch.setattr(chat, "_gen_research", fake_gen)
    return captured, summaries


def test_table_regression_marks_stale_when_table_changed(monkeypatch):
    captured, _ = _regression_env(monkeypatch, result={
        "model": "ols", "n": 1, "equation": "B=2A", "r2": 0.5,
        "coefficients": [{"term": "const", "estimate": 1, "p": 0.1}]})
    _, meta = _text_route("回归结果怎么解释", body={
        "tableId": "t1",
        "tableRegression": {"model": "ols", "x": ["A"], "y": "B",
                            "tableUpdatedAt": 999}}, workspace="research")
    assert meta["tableChanged"] is True
    assert "table_changed" in captured["extra"]   # 模型被告知表已变
    assert "equation=B=2A" in captured["extra"]


def test_table_regression_fresh_result_has_no_stale_prefix(monkeypatch):
    captured, _ = _regression_env(monkeypatch, result={"model": "poly", "n": 3})
    _, meta = _text_route("解释回归", body={
        "tableId": "t1",
        "tableRegression": {"model": "poly", "degree": 2, "x": ["A"], "y": "B",
                            "tableUpdatedAt": 100}}, workspace="research")
    assert "tableChanged" not in meta
    assert "table_changed" not in captured["extra"]
    assert "model=poly" in captured["extra"]


def test_table_regression_unparsable_stamp_is_stale(monkeypatch):
    captured, _ = _regression_env(monkeypatch, result={"model": "ols"})
    _, meta = _text_route("解释回归", body={
        "tableId": "t1",
        "tableRegression": {"model": "ols", "x": ["A"], "y": "B",
                            "tableUpdatedAt": "abc"}}, workspace="research")
    assert meta["tableChanged"] is True
    assert "table_changed" in captured["extra"]


def test_table_regression_failure_degrades_with_warning(monkeypatch):
    captured, summaries = _regression_env(
        monkeypatch, raises=RuntimeError("worker missing"))
    _, meta = _text_route("解释回归", body={
        "tableId": "t1",
        "tableRegression": {"model": "ols", "x": ["A"], "y": "B"}}, workspace="research")
    assert "tableChanged" not in meta
    assert "回归结果不可用" in summaries[-1]
    assert "回归结果不可用" in captured["extra"]


# ---------- 无上下文降级:数学题兜底 vs 闲聊直答 ----------

def test_route_math_question_without_context_uses_method_fallback(monkeypatch):
    _offline(monkeypatch, math=True)
    text, _ = _text_route("求 x^2 的导数")
    assert text == chat.FALLBACK_ZH


def test_route_chitchat_uses_conversational_reply(monkeypatch):
    _offline(monkeypatch)
    text, meta = _text_route("你好呀")
    zh_lines = {line for lines in chat_routing.CHITCHAT_SETS_ZH.values() for line in lines}
    assert text in zh_lines
    assert text != chat.FALLBACK_ZH
    assert meta["role"] == "main"


def test_route_empty_prompt_welcome_differs_by_workspace(monkeypatch):
    _offline(monkeypatch)
    learn, _ = _text_route("")
    research, _ = _text_route("", workspace="research")
    assert learn == chat.WELCOME_ZH
    assert research == chat.WELCOME_RESEARCH_ZH



# ---------- 图解:语义校验回退 / 各类闸门 ----------

def test_diagram_verified_releases_on_failure_or_unknown(monkeypatch):
    """质检异常或无法判断 → 放行(不因质检故障丢图);明确不一致才拦。"""
    monkeypatch.setenv("MG_DIAGRAM_VERIFY", "1")

    async def boom(*args, **kwargs):
        raise RuntimeError("质检服务 503")

    monkeypatch.setattr(chat.research_diagrams, "verify_diagram", boom)
    assert asyncio.run(chat._diagram_verified("q", "ctx", {"type": "relation"})) is True

    async def unknown(*args, **kwargs):
        return None

    monkeypatch.setattr(chat.research_diagrams, "verify_diagram", unknown)
    assert asyncio.run(chat._diagram_verified("q", "ctx", {"type": "relation"})) is True

    async def mismatch(*args, **kwargs):
        return False

    monkeypatch.setattr(chat.research_diagrams, "verify_diagram", mismatch)
    assert asyncio.run(chat._diagram_verified("q", "ctx", {"type": "relation"})) is False

    monkeypatch.setenv("MG_DIAGRAM_VERIFY", "0")
    assert asyncio.run(chat._diagram_verified("q", "ctx", {"type": "relation"})) is True


def _diagram_env(monkeypatch, answer: list[str], *, plan=None,
                 stepwise: bool = False, explicit: str | None = None,
                 relation: bool = False, meta: bool = False):
    """图解闸门测试的公共打桩:模型只吐固定增量,规划器记录调用。"""
    planned: list[str] = []

    async def fake_stream(system, user, **kwargs):
        for chunk in answer:
            yield chunk

    async def default_plan(question, before, excerpts, kind, role="main", **kwargs):
        planned.append(kind)
        return {"type": kind or "relation", "nodes": [{"id": "a", "label": "A"}],
                "edges": [], "shapes": [], "annotations": []}

    monkeypatch.setattr(chat.rag.llm, "stream_chat", fake_stream)
    monkeypatch.setattr(chat.research_diagrams, "plan_diagram_auto", plan or default_plan)
    monkeypatch.setattr(chat.research_diagrams, "select_segments", lambda *a, **k: [])
    monkeypatch.setattr(chat.research_diagrams, "is_step_text", lambda text: stepwise)
    monkeypatch.setattr(chat.research_diagrams, "explicit_type", lambda q: explicit)
    monkeypatch.setattr(chat.research_diagrams, "is_relation_question", lambda q: relation)
    monkeypatch.setattr(chat.research_diagrams, "is_meta_question", lambda q: meta)
    return planned


def _diagram_run(question: str, **kwargs) -> list[str]:
    return _collect(chat._gen_llm(
        question, None, [], diagram_mode=True, diagram_question=question,
        diagram_request_id="r-gate", **kwargs))


def test_chat_drops_marker_for_meta_question(monkeypatch):
    planned = _diagram_env(
        monkeypatch, ["我可以画图。[[MG_DIAGRAM:relation]]"], meta=True)
    frames = _diagram_run("你能画图吗")
    assert planned == []
    assert _events(frames) == []


def test_chat_keeps_one_diagram_for_relation_question(monkeypatch):
    planned = _diagram_env(
        monkeypatch,
        ["关系如下。[[MG_DIAGRAM:relation]]再看第二个。[[MG_DIAGRAM:relation]]"],
        explicit="relation", relation=True)
    frames = _diagram_run("画出概念之间的关系")
    assert len(planned) == 1
    assert len(_events(frames)) == 1


def test_chat_drops_second_diagram_too_close(monkeypatch):
    """非步骤回答的锚点间隔 <400 字 → 第二张图丢弃(避免同段堆图)。"""
    planned = _diagram_env(
        monkeypatch,
        ["切线斜率是导数。[[MG_DIAGRAM:geometry2d]]再看这张。[[MG_DIAGRAM:geometry2d]]"],
        explicit="geometry2d")
    frames = _diagram_run("画图说明切线")
    assert len(planned) == 1
    assert len(_events(frames)) == 1


def test_chat_drops_third_diagram_by_density(monkeypatch):
    """非步骤回答最多 2 张图:第三张按密度丢弃。"""
    body = ("甲" * 450 + "[[MG_DIAGRAM:geometry2d]]" + "乙" * 450
            + "[[MG_DIAGRAM:geometry2d]]" + "丙" * 450 + "[[MG_DIAGRAM:geometry2d]]")
    planned = _diagram_env(monkeypatch, [body], explicit="geometry2d")
    _diagram_run("画图说明切线")
    assert len(planned) == 2


def test_chat_drops_decorative_diagram_by_visual_cue(monkeypatch):
    """步骤段落里没有任何可视化线索 → 视为装饰性配图,丢弃。"""
    planned = _diagram_env(
        monkeypatch,
        ["这是一段讲解,先说结论。\n\n切线斜率等于导数。[[MG_DIAGRAM:geometry2d]]"])
    monkeypatch.setattr(chat.research_diagrams, "references_diagram",
                        lambda text, window=400: True)
    monkeypatch.setattr(chat.research_diagrams, "wants_visual", lambda q: False)
    monkeypatch.setattr(
        chat.research_diagrams, "is_step_text",
        lambda text: "\n" not in text and text.strip().startswith("这是一段讲解"))
    monkeypatch.setattr(chat.research_diagrams, "visual_cue_score", lambda text: 0.0)
    frames = _diagram_run("解释切线")
    assert planned == []
    assert _events(frames) == []


def test_chat_drops_low_importance_diagram(monkeypatch):
    planned = _diagram_env(
        monkeypatch,
        ["这是一段讲解,先说结论。\n\n切线斜率等于导数。[[MG_DIAGRAM:geometry2d]]"])
    monkeypatch.setattr(chat.research_diagrams, "references_diagram",
                        lambda text, window=400: True)
    monkeypatch.setattr(chat.research_diagrams, "wants_visual", lambda q: False)
    monkeypatch.setattr(chat.research_diagrams, "importance_score",
                        lambda seg, terms: 0.0)
    frames = _diagram_run("解释切线")
    assert planned == []
    assert _events(frames) == []



# ---------- 安全外壳:输入上限与非流式响应透传 ----------

def _stream_client(monkeypatch, route_fn):

    monkeypatch.setattr(chat, "require_auth", lambda request: {"uid": "u"})
    monkeypatch.setattr(chat.quota, "check", lambda uid: None)
    monkeypatch.setattr(chat, "_rate_check", lambda uid: None)
    monkeypatch.setattr(chat, "_route_chat", route_fn)
    monkeypatch.setattr(chat, "_meter", lambda resp, rec, prompt_len, cmd, meta: resp)
    app = Starlette(routes=[Route("/api/chat/stream", chat.chat_stream, methods=["POST"])])
    return TestClient(app)


def test_chat_stream_truncates_oversized_prompt(monkeypatch):
    captured: dict = {}

    async def fake_route(prompt, cmd, body, rec, meta, workspace="learn"):
        captured["prompt"] = prompt
        return chat._stream_text("ok")

    client = _stream_client(monkeypatch, fake_route)
    res = client.post("/api/chat/stream", json={"prompt": "字" * (chat.PROMPT_MAX + 50)})
    assert res.status_code == 200
    assert len(captured["prompt"]) == chat.PROMPT_MAX


def test_chat_stream_passes_through_non_streaming_response(monkeypatch):
    async def fake_route(prompt, cmd, body, rec, meta, workspace="learn"):
        return JSONResponse({"detail": "blocked"}, status_code=400)

    client = _stream_client(monkeypatch, fake_route)
    res = client.post("/api/chat/stream", json={"prompt": "问题"})
    assert res.status_code == 400
    assert res.json() == {"detail": "blocked"}


# ---------- 语音转写:一字未出回放原文 / 已出半截中断 ----------

def _speech(monkeypatch, body: dict):
    from starlette.requests import Request

    monkeypatch.setattr(chat, "require_auth", lambda request: {"uid": "u-speech"})
    monkeypatch.setattr(chat.quota, "check", lambda uid: None)
    monkeypatch.setattr(chat, "_rate_check", lambda uid: None)

    async def fake_body(request):
        return dict(body)

    monkeypatch.setattr(chat, "read_json_object", fake_body)
    request = Request({"type": "http", "method": "POST", "headers": []})
    return asyncio.run(chat.speech_to_math(request))


def test_speech_empty_text_streams_nothing(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("空文本不应调用模型")

    monkeypatch.setattr(chat.rag.llm, "stream_chat", forbidden)
    resp = _speech(monkeypatch, {"text": "   "})
    assert _joined(_collect_response(resp)) == ""


def test_speech_transcription_streams_and_records_usage(monkeypatch, temp_usage):
    monkeypatch.setattr(chat.rag.llm, "stream_chat", _fake_llm(["x²+1"]))
    resp = _speech(monkeypatch, {"text": "x 平方加一"})
    assert _joined(_collect_response(resp)) == "x²+1"
    entries = temp_usage.for_user("u-speech")
    assert len(entries) == 1
    assert entries[0]["cmd"] == "语音转写"


def test_speech_record_failure_does_not_break_transcription(monkeypatch):
    monkeypatch.setattr(chat.rag.llm, "stream_chat", _fake_llm(["x²+1"]))

    def boom(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(chat, "_record", boom)
    resp = _speech(monkeypatch, {"text": "x 平方加一"})
    assert _joined(_collect_response(resp)) == "x²+1"


def test_speech_failure_before_output_replays_original_text(monkeypatch):
    monkeypatch.setattr(chat.rag.llm, "stream_chat",
                        _fake_llm(raises=RuntimeError("429")))
    resp = _speech(monkeypatch, {"text": "x 平方加一"})
    assert _joined(_collect_response(resp)) == "x 平方加一"


def test_speech_failure_after_output_aborts_stream(monkeypatch):
    """已输出半截 → 主动中断流(前端 complete=false 回退原文),不拼原文。"""
    monkeypatch.setattr(chat.rag.llm, "stream_chat", _fake_llm(
        ["x²"], raises=RuntimeError("read timeout"), fail_after=1))
    resp = _speech(monkeypatch, {"text": "x 平方"})
    with pytest.raises(RuntimeError):
        _collect_response(resp)


# ---------- 直观解释:400 / 失败提示 / LRU 淘汰 ----------

def _intuition_client(monkeypatch):

    monkeypatch.setattr(chat, "require_auth", lambda request: {"uid": "u-intuition"})
    monkeypatch.setattr(chat.quota, "check", lambda uid: None)
    monkeypatch.setattr(chat, "_rate_check", lambda uid: None)
    app = Starlette(routes=[
        Route("/api/chat/intuition", chat.intuition, methods=["POST"])])
    return TestClient(app)


def test_intuition_requires_question(monkeypatch):
    client = _intuition_client(monkeypatch)
    res = client.post("/api/chat/intuition", json={"answer": "只有解答"})
    assert res.status_code == 400


def test_intuition_failure_reports_instead_of_faking(monkeypatch):
    monkeypatch.setattr(chat.rag.llm, "stream_chat", _fake_llm(raises=RuntimeError("boom")))
    text = _joined(_collect(chat._gen_intuition("什么是导数", "导数是变化率", True)))
    assert "直观解释生成失败" in text
    assert chat._INTUITION_CACHE == {}


def test_intuition_cache_evicts_lru(monkeypatch):
    monkeypatch.setattr(chat, "_INTUITION_MAX", 1)
    monkeypatch.setattr(chat.rag.llm, "stream_chat", _fake_llm(["比喻说法"]))
    asyncio.run(_aiter(chat._gen_intuition("问题一", "解答一", True)))
    asyncio.run(_aiter(chat._gen_intuition("问题二", "解答二", True)))
    assert len(chat._INTUITION_CACHE) == 1
    assert ("问题二", "解答二") in chat._INTUITION_CACHE


# ---------- 知识点讲解:缺预置内容走检索 / 英文提问 / 模型失败降级 ----------

def _graph():
    from knowledge_graph import KnowledgeGraph, KnowledgePoint

    return KnowledgeGraph({
        "p1": KnowledgePoint("p1", "极限", "函数与极限", 3, (),
                             "摘要内容", ("要点一", "要点二")),
        "p2": KnowledgePoint("p2", "Limit", "Functions", 2, ()),
    })


def test_point_lesson_without_notes_uses_retrieval_excerpts(monkeypatch):
    _offline(monkeypatch)
    monkeypatch.setattr(chat.diagnosis, "get_graph", _graph)
    searched: dict = {}

    def fake_search(query, top_k=5):
        searched["query"] = query
        return [(chat.rag.Chunk("c", "检索标题", "", "检索小节", "检索正文"), 0.5)]

    monkeypatch.setattr(chat.rag, "search", fake_search)
    text, _ = _text_route("讲讲解", "知识点讲解", {"pointId": "p2"})
    assert searched["query"] == "Limit"
    assert "检索正文" in text


def test_point_lesson_english_question_answers_directly(monkeypatch):
    _offline(monkeypatch)
    monkeypatch.setattr(chat.diagnosis, "get_graph", _graph)
    monkeypatch.setattr(chat.rag.llm, "is_configured", lambda *a, **k: True)
    monkeypatch.setattr(chat.rag.llm, "stream_chat", _fake_llm(["Main structure: ..."]))
    text, _ = _text_route("Explain the Limit concept", "知识点讲解", {"pointId": "p2"})
    assert text == "Main structure: ..."


def test_point_lesson_model_failure_falls_back_to_prepared_notes(monkeypatch):
    _offline(monkeypatch)
    monkeypatch.setattr(chat.diagnosis, "get_graph", _graph)
    monkeypatch.setattr(chat.rag.llm, "is_configured", lambda *a, **k: True)
    monkeypatch.setattr(chat.rag.llm, "stream_chat", _fake_llm(raises=RuntimeError("boom")))
    text, _ = _text_route("讲讲解", "知识点讲解", {"pointId": "p1"})
    assert "摘要内容" in text
    assert "要点一" in text


# ---------- 学习分析:模型失败降级为确定性报告 ----------

def _analysis_snapshot() -> dict:
    from datetime import datetime, timezone

    from knowledge_graph import KnowledgeGraph, KnowledgePoint

    points = {
        "a": KnowledgePoint("a", "点a", "第一章", 1, ()),
        "b": KnowledgePoint("b", "点b", "第一章", 5, ("a",)),
    }
    now = datetime(2026, 11, 8, 12, 0, tzinfo=timezone.utc)
    at = now.isoformat(timespec="seconds")
    return chat.learning_analysis.build_snapshot(
        "u", graph=KnowledgeGraph(points),
        latest_map={"a": {"pointId": "a", "score": 4, "at": at}}, now=now)


def test_learning_analysis_model_failure_falls_back_to_report(monkeypatch):
    snapshot = _analysis_snapshot()
    monkeypatch.setattr(chat.learning_analysis, "build_snapshot", lambda uid: snapshot)
    monkeypatch.setattr(chat.rag.llm, "is_configured", lambda *a, **k: True)
    monkeypatch.setattr(chat.rag.llm, "stream_chat", _fake_llm(raises=RuntimeError("boom")))
    text, _ = _text_route("分析我的学习进度", "学习分析")
    assert "覆盖度" in text

    # 已流出半截:降级报告接在正文之后
    monkeypatch.setattr(chat.rag.llm, "stream_chat", _fake_llm(
        ["半截解读"], raises=RuntimeError("boom"), fail_after=1))
    text, _ = _text_route("分析我的学习进度", "学习分析")
    assert "半截解读" in text
    assert "覆盖度" in text


# ---------- 数据表上下文读取失败不影响聊天 ----------

def test_table_context_failure_keeps_normal_chat(monkeypatch):
    _offline(monkeypatch)
    monkeypatch.setattr(chat.rag.llm, "is_configured", lambda *a, **k: True)

    def boom(uid, table_id):
        raise RuntimeError("db locked")

    monkeypatch.setattr(chat.research_tables, "_get_table", boom)

    async def fake_gen(question, cmd, chunks, **kwargs):
        yield 'data: "回答"\n\n'

    monkeypatch.setattr(chat, "_gen_llm", fake_gen)
    text, _ = _text_route("解释一下", body={"tableId": "t1"}, workspace="research")
    assert text == "回答"


def test_paper_question_includes_table_context_chunk(monkeypatch):
    _paper(monkeypatch, llm=True)
    monkeypatch.setattr(chat.research_tables, "_get_table",
                        lambda uid, table_id: {"columns": [], "rows": [],
                                               "formulas": {}, "updatedAt": 1})
    monkeypatch.setattr(chat.research_tables, "context_text",
                        lambda table, summary="": "数据表上下文")
    captured: dict = {}

    async def fake_paper(question, cmd, chunks, **kwargs):
        captured["chunks"] = chunks
        yield 'data: "ok"\n\n'

    monkeypatch.setattr(chat, "_gen_paper_llm", fake_paper)
    _text_route("这张表和论文结论一致吗",
                body={"paperId": "d1", "tableId": "t1"}, workspace="research")
    assert any(chunk.title == "研究数据表" for chunk, _score in captured["chunks"])




# ---------- 论文回答与窗口动作并行:先到先发 / 规划失败 / 取消 ----------

def _paper_answer(monkeypatch, frames: list[str], *, answer_delay: float = 0.0):
    async def fake_gen(*args, **kwargs):
        for frame in frames:
            if answer_delay:
                await asyncio.sleep(answer_delay)
            yield frame

    monkeypatch.setattr(chat, "_gen_llm", fake_gen)


def _actions(values: list[dict], *, delay: float = 0.0, error: Exception | None = None):
    async def plan(uid, doc_id, question, excerpts=None, history=None):
        if delay:
            await asyncio.sleep(delay)
        if error is not None:
            raise error
        return values

    return plan


def test_paper_actions_frame_is_empty_for_no_actions():
    assert chat._paper_actions_frame([], "r", "d") == ""
    frame = chat._paper_actions_frame([{"type": "highlight"}], "r", "d")
    assert json.loads(frame[len("data: "):])["actions"] == [{"type": "highlight"}]


def test_gen_paper_llm_emits_actions_before_answer_ends(monkeypatch):
    _paper_answer(monkeypatch, ['data: "前半"\n\n', 'data: "后半"\n\n'],
                  answer_delay=0.02)
    monkeypatch.setattr(chat.research_actions, "plan_actions", _actions(
        [{"type": "highlight", "page": 2}]))
    frames = _collect(chat._gen_paper_llm(
        "问题", None, [_chunk()], uid_for_actions="u", doc_id="d1", request_id="r1"))
    events = [v for v in map(_payload, frames) if isinstance(v, dict)]
    assert any(v.get("mg_event") == "paper_actions" for v in events)
    assert "后半" in _joined(frames)


def test_gen_paper_llm_planner_failure_keeps_answer(monkeypatch):
    _paper_answer(monkeypatch, ['data: "回答"\n\n'], answer_delay=0.02)
    monkeypatch.setattr(chat.research_actions, "plan_actions",
                        _actions([], error=RuntimeError("planner down")))
    frames = _collect(chat._gen_paper_llm(
        "问题", None, [_chunk()], uid_for_actions="u", doc_id="d1", request_id="r2"))
    events = [v for v in map(_payload, frames) if isinstance(v, dict)]
    assert not any(v.get("mg_event") == "paper_actions" for v in events)
    assert "回答" in _joined(frames)


def test_gen_paper_llm_waits_for_actions_after_answer_ends(monkeypatch):
    """回答先结束 → 等规划一会儿再补发动作帧,不静默丢弃批注。"""
    _paper_answer(monkeypatch, ['data: "回答"\n\n'])
    monkeypatch.setattr(chat.research_actions, "plan_actions", _actions(
        [{"type": "annotate"}], delay=0.05))
    frames = _collect(chat._gen_paper_llm(
        "问题", None, [_chunk()], uid_for_actions="u", doc_id="d1", request_id="r3"))
    events = [v for v in map(_payload, frames) if isinstance(v, dict)]
    assert any(v.get("mg_event") == "paper_actions" for v in events)


def test_gen_paper_llm_waits_then_survives_planner_error(monkeypatch):
    _paper_answer(monkeypatch, ['data: "回答"\n\n'])
    monkeypatch.setattr(chat.research_actions, "plan_actions",
                        _actions([], delay=0.05, error=RuntimeError("late boom")))
    frames = _collect(chat._gen_paper_llm(
        "问题", None, [_chunk()], uid_for_actions="u", doc_id="d1", request_id="r4"))
    assert "回答" in _joined(frames)


def test_gen_paper_llm_cancel_cancels_pending_tasks(monkeypatch):
    async def endless(*args, **kwargs):
        yield 'data: "第一段"\n\n'
        await asyncio.sleep(5)
        yield 'data: "第二段"\n\n'

    monkeypatch.setattr(chat, "_gen_llm", endless)
    monkeypatch.setattr(chat.research_actions, "plan_actions", _actions([], delay=5.0))

    async def run():
        gen = chat._gen_paper_llm("问题", None, [_chunk()], uid_for_actions="u",
                                  doc_id="d1", request_id="r5")

        async def consume():
            async for _frame in gen:
                pass

        task = asyncio.create_task(consume())
        await asyncio.sleep(0.05)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(run())


# ---------- 其它分支:长度上限 / 坏 JSON / 缓存淘汰 / 参数转发 ----------

def test_verify_answer_tolerates_broken_json_inside_braces(monkeypatch):
    monkeypatch.setattr(chat.rag.llm, "stream_chat", _fake_llm(["{不是 JSON}"]))
    verdict = asyncio.run(chat._verify_answer("q", "a", "main"))
    assert verdict["verdict"] == "uncertain"


def test_update_summary_stops_at_length_cap(monkeypatch):
    session_cache.reset()
    monkeypatch.setattr(chat.rag.llm, "stream_chat", _fake_llm(["字" * 450]))
    asyncio.run(chat._update_summary("u", 9, [{"role": "user", "content": "x"}], ""))
    assert len(session_cache.get_summary("u", 9)) >= 400


def test_gen_research_cache_evicts_lru(monkeypatch):
    async def fake_synth(question, hits, zh, role="main", fallback=True, extra=""):
        yield "综述"

    monkeypatch.setattr(chat.rag.research.synthesize, "synthesize_stream", fake_synth)
    monkeypatch.setattr(chat.rag.research.synthesize, "citations_block",
                        lambda hits, zh: "")
    monkeypatch.setattr(chat, "_RESEARCH_MAX", 1)
    _collect(chat._gen_research("问题", _outcome(hits=[_hit()]), True, ck="k1"))
    _collect(chat._gen_research("问题", _outcome(hits=[_hit()]), True, ck="k2"))
    assert list(chat._RESEARCH_ANSWER) == ["k2"]


def test_gen_llm_forwards_temperature_and_summary(monkeypatch):
    captured: dict = {}
    monkeypatch.setattr(chat.rag.llm, "stream_chat",
                        _fake_llm(["回答"], capture=captured))
    _collect(chat._gen_llm("问题", None, [], temperature=0.0, summary="更早的摘要"))
    assert captured["temperature"] == 0.0
    assert "更早的摘要" in captured["system"]


def test_regression_summary_includes_warnings_and_stale_prefix():
    summary = chat._regression_summary({
        "model": "ols", "n": 4, "equation": "y=x", "r2": None,
        "coefficients": [], "warnings": ["样本量偏小"]}, True)
    assert summary.startswith("table_changed: ")
    assert "warnings=样本量偏小" in summary
    assert "R²=—" in summary


# ---------- 科研区 RAG 路径:私有语料前置 / 语料故障不影响主链路 ----------

def test_research_rag_path_prepends_private_corpus(monkeypatch):
    _offline(monkeypatch)
    monkeypatch.setattr(chat.rag.llm, "is_configured", lambda *a, **k: True)
    monkeypatch.setattr(chat.rag, "search", lambda *a, **k: [_chunk("公共知识")])
    monkeypatch.setattr(
        chat.research_corpus, "chat_hits",
        lambda uid, question, top_k=4, doc_id=None: [{
            "nodeId": "n1", "docName": "我的论文", "section": "结果",
            "pageStart": 3, "pageEnd": 4, "snippet": "私有片段", "text": "私有正文"}])
    captured: dict = {}

    async def fake_gen(question, cmd, chunks, **kwargs):
        captured["chunks"] = chunks
        yield 'data: "回答"\n\n'

    monkeypatch.setattr(chat, "_gen_llm", fake_gen)
    text, _ = _text_route("这个方向怎么建模", workspace="research")
    titles = [chunk.title for chunk, _score in captured["chunks"]]
    assert titles[0] == "我的论文"
    assert titles[-1] == "标题"
    assert text == "回答"


def test_research_rag_corpus_failure_is_ignored(monkeypatch):
    _offline(monkeypatch)
    monkeypatch.setattr(chat.rag.llm, "is_configured", lambda *a, **k: True)
    monkeypatch.setattr(chat.rag, "search", lambda *a, **k: [_chunk("公共知识")])

    def boom(*args, **kwargs):
        raise RuntimeError("index broken")

    monkeypatch.setattr(chat.research_corpus, "chat_hits", boom)
    captured: dict = {}

    async def fake_gen(question, cmd, chunks, **kwargs):
        captured["chunks"] = chunks
        yield 'data: "回答"\n\n'

    monkeypatch.setattr(chat, "_gen_llm", fake_gen)
    text, _ = _text_route("这个方向怎么建模", workspace="research")
    assert [chunk.title for chunk, _score in captured["chunks"]] == ["标题"]
    assert text == "回答"


def test_research_without_llm_falls_back_to_source_list(monkeypatch):
    """科研区未配置模型 → 直接给来源列表,不谈综合。"""
    _offline(monkeypatch, research_intent=True)
    monkeypatch.setattr(chat, "_research_cache_key", lambda *a, **k: "ck-list")

    async def fake_deep(question, top_k=3, scope=None):
        return _outcome(hits=[_hit()])

    monkeypatch.setattr(chat.rag.research, "deep_search", fake_deep)
    text, meta = _text_route("泰勒展开", workspace="research")
    assert "论文标题" in text
    assert meta["research"] is True


def test_point_lesson_search_failure_still_answers(monkeypatch):
    """知识点没预置内容且检索失败 → 讲解入口不中断。"""
    _offline(monkeypatch)
    monkeypatch.setattr(chat.diagnosis, "get_graph", _graph)

    def boom(*args, **kwargs):
        raise RuntimeError("index broken")

    monkeypatch.setattr(chat.rag, "search", boom)
    text, _ = _text_route("讲讲解", "知识点讲解", {"pointId": "p2"})
    assert "Limit" in text


# ---------- 图解边讲边画:流中完成即发 / 取消与异常的清理 ----------

def test_chat_emits_diagram_completed_while_streaming(monkeypatch):
    """图在正文还在流的时候规划完 → 立刻下发,不必等答案结束。"""
    async def fake_stream(system, user, **kwargs):
        yield "如图所示,切线斜率是导数。[[MG_DIAGRAM:geometry2d]]"
        await asyncio.sleep(0.02)
        yield "继续讲解。"
        await asyncio.sleep(0.02)
        yield "结束。"

    async def fake_plan(question, before, excerpts, kind, role="main", **kwargs):
        return {"type": "geometry2d", "shapes": [], "nodes": [], "edges": [],
                "annotations": []}

    monkeypatch.setattr(chat.rag.llm, "stream_chat", fake_stream)
    monkeypatch.setattr(chat.research_diagrams, "plan_diagram_auto", fake_plan)
    monkeypatch.setattr(chat.research_diagrams, "select_segments", lambda *a, **k: [])
    frames = _diagram_run("画图说明切线斜率")
    events = _events(frames)
    assert len(events) == 1
    assert "结束。" in _joined(frames)


def test_chat_density_gate_drops_fourth_diagram(monkeypatch):
    """图数上限放宽后(MAX_DIAGRAMS=3),非步骤内容仍按密度只画 2 张。"""
    monkeypatch.setattr(chat.research_diagrams, "MAX_DIAGRAMS", 3)
    body = ("甲" * 450 + "[[MG_DIAGRAM:geometry2d]]" + "乙" * 450
            + "[[MG_DIAGRAM:geometry2d]]" + "丙" * 450
            + "[[MG_DIAGRAM:geometry2d]]")
    planned = _diagram_env(monkeypatch, [body], explicit="geometry2d")
    monkeypatch.setattr(chat.research_diagrams, "MAX_DIAGRAMS", 3)
    _diagram_run("画图说明切线")
    assert len(planned) == 2


def test_chat_cancel_while_diagram_pending(monkeypatch):
    async def fake_stream(system, user, **kwargs):
        yield "如图[[MG_DIAGRAM:geometry2d]]"
        raise asyncio.CancelledError
        yield  # 先抛错:这里的 yield 只为让函数成为 async generator

    async def slow_plan(*args, **kwargs):
        await asyncio.sleep(5)
        return None

    monkeypatch.setattr(chat.rag.llm, "stream_chat", fake_stream)
    monkeypatch.setattr(chat.research_diagrams, "plan_diagram_auto", slow_plan)

    async def run():
        with pytest.raises(asyncio.CancelledError):
            async for _frame in chat._gen_llm(
                    "画图说明切线", None, [], diagram_mode=True,
                    diagram_question="画图说明切线", diagram_request_id="r-cancel2"):
                pass

    asyncio.run(run())


def test_chat_model_error_cancels_pending_diagram_tasks(monkeypatch):
    async def fake_stream(system, user, **kwargs):
        yield "如图[[MG_DIAGRAM:geometry2d]]"
        raise RuntimeError("deep 429")
        yield  # 先抛错:这里的 yield 只为让函数成为 async generator

    async def slow_plan(*args, **kwargs):
        await asyncio.sleep(5)
        return None

    monkeypatch.setattr(chat.rag.llm, "stream_chat", fake_stream)
    monkeypatch.setattr(chat.research_diagrams, "plan_diagram_auto", slow_plan)
    text = _joined(_diagram_run("画图说明切线"))
    assert text.startswith("如图")
    assert "中断" in text



def _streaming_diagram(monkeypatch, *, verify=None, plan=None):
    """正文分三段流出,中间留出时间让图解规划/校验在流内完成。"""
    async def fake_stream(system, user, **kwargs):
        yield "如图所示,切线斜率是导数。[[MG_DIAGRAM:geometry2d]]"
        await asyncio.sleep(0.02)
        yield "继续讲解。"
        await asyncio.sleep(0.02)
        yield "结束。"

    async def fake_plan(question, before, excerpts, kind, role="main", **kwargs):
        return {"type": "geometry2d", "shapes": [], "nodes": [], "edges": [],
                "annotations": []}

    monkeypatch.setattr(chat.rag.llm, "stream_chat", fake_stream)
    monkeypatch.setattr(chat.research_diagrams, "plan_diagram_auto", plan or fake_plan)
    monkeypatch.setattr(chat.research_diagrams, "select_segments", lambda *a, **k: [])
    if verify is not None:
        monkeypatch.setattr(chat, "_diagram_verified", verify)


def test_chat_releases_diagram_when_verify_task_fails(monkeypatch):
    """图已规划、语义校验任务本身异常 → 放行(不因质检故障丢图)。"""
    async def broken_verify(*args, **kwargs):
        raise RuntimeError("verify worker down")

    _streaming_diagram(monkeypatch, verify=broken_verify)
    frames = _diagram_run("画图说明切线斜率")
    assert len(_events(frames)) == 1


def test_chat_drops_diagram_when_verify_rejects_midstream(monkeypatch):
    async def reject(*args, **kwargs):
        return False

    _streaming_diagram(monkeypatch, verify=reject)
    frames = _diagram_run("画图说明切线斜率")
    assert _events(frames) == []
    assert "结束。" in _joined(frames)


def test_chat_emits_diagram_at_stream_end_when_verify_is_slow(monkeypatch):
    async def slow_ok(*args, **kwargs):
        await asyncio.sleep(0.15)     # 流结束后才返回 → 走 force 收尾
        return True

    _streaming_diagram(monkeypatch, verify=slow_ok)
    frames = _diagram_run("画图说明切线斜率")
    assert len(_events(frames)) == 1


def test_chat_planner_task_error_keeps_text(monkeypatch):
    async def failing_plan(*args, **kwargs):
        raise RuntimeError("planner down")

    _streaming_diagram(monkeypatch, plan=failing_plan)
    frames = _diagram_run("画图说明切线斜率")
    assert _events(frames) == []
    assert "结束。" in _joined(frames)


def test_chat_restores_truncated_marker_as_text(monkeypatch):
    """模型输出被截断的标记不能吞字:残留缓冲要还原成正文。"""
    async def fake_stream(system, user, **kwargs):
        yield "正文"
        yield "[[MG_DIA"

    monkeypatch.setattr(chat.rag.llm, "stream_chat", fake_stream)
    frames = _diagram_run("解释切线")
    assert _joined(frames) == "正文[[MG_DIA"


def test_chat_cancel_while_verify_pending(monkeypatch):
    async def fake_stream(system, user, **kwargs):
        yield "如图[[MG_DIAGRAM:geometry2d]]"
        await asyncio.sleep(0.02)
        yield "继续。"
        await asyncio.sleep(0.02)
        raise asyncio.CancelledError
        yield  # 先抛错:这里的 yield 只为让函数成为 async generator

    async def slow_plan(question, before, excerpts, kind, role="main", **kwargs):
        return {"type": "geometry2d", "shapes": [], "nodes": [], "edges": [],
                "annotations": []}

    async def slow_verify(*args, **kwargs):
        await asyncio.sleep(5)
        return True

    monkeypatch.setattr(chat.rag.llm, "stream_chat", fake_stream)
    monkeypatch.setattr(chat.research_diagrams, "plan_diagram_auto", slow_plan)
    monkeypatch.setattr(chat, "_diagram_verified", slow_verify)

    async def run():
        with pytest.raises(asyncio.CancelledError):
            async for _frame in chat._gen_llm(
                    "画图说明切线", None, [], diagram_mode=True,
                    diagram_question="画图说明切线", diagram_request_id="r-cancel3"):
                pass

    asyncio.run(run())


def test_chat_model_error_cancels_pending_verify(monkeypatch):
    async def fake_stream(system, user, **kwargs):
        yield "如图[[MG_DIAGRAM:geometry2d]]"
        await asyncio.sleep(0.02)
        yield "继续。"
        await asyncio.sleep(0.02)
        raise RuntimeError("deep 429")
        yield  # 先抛错:这里的 yield 只为让函数成为 async generator

    async def fake_plan(question, before, excerpts, kind, role="main", **kwargs):
        return {"type": "geometry2d", "shapes": [], "nodes": [], "edges": [],
                "annotations": []}

    async def slow_verify(*args, **kwargs):
        await asyncio.sleep(5)
        return True

    monkeypatch.setattr(chat.rag.llm, "stream_chat", fake_stream)
    monkeypatch.setattr(chat.research_diagrams, "plan_diagram_auto", fake_plan)
    monkeypatch.setattr(chat, "_diagram_verified", slow_verify)
    text = _joined(_diagram_run("画图说明切线"))
    assert text.startswith("如图")
    assert "中断" in text

