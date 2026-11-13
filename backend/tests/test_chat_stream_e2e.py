"""chat.chat_stream 端到端:认证 → 限流 → 路由 → SSE 收尾 → 用量记账。

刻意**不 mock 业务路由**:这条链路上的 bug(降级分支没兜住、记账漏记或多记、
帧格式不兼容前端解析)只有真跑才会暴露。测试环境没有 `.env.local`,
所以 LLM 未配置,走的是"知识库直答 / 寒暄"降级分支 —— 这正是演示环境的真实路径。

知识库用 `tests/fixtures/rag/` 的 12 个固定切片(与 test_rag_regression 共用),
不读仓库里真实的 knowledge/,也不联网。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from starlette.applications import Starlette
from starlette.routing import Route
from starlette.testclient import TestClient

import chat
import chat_sse
import rag
import store
import usage

PHONE = "13800138002"
PASSWORD = "secret123"
UID = f"u-{PHONE}"
FIXTURES = Path(__file__).parent / "fixtures" / "rag"


@pytest.fixture()
def client(temp_store, temp_usage, monkeypatch):
    """真实 store + 真实检索 + 小语料;每个测试独立限流窗口。"""
    monkeypatch.setattr(rag, "KNOWLEDGE_DIR", FIXTURES)
    monkeypatch.setattr(rag, "_index", None)
    monkeypatch.setattr(rag, "_stamp", None)
    # 逐字流的节奏只为"看着像打字",测试里没必要等。
    # 注意:节奏常量已随 _frames 迁到 chat_sse,必须 patch 它的模块全局,
    # 改 chat.FRAME_MS 不再影响流(那只是本模块的一份导入绑定)。
    monkeypatch.setattr(chat_sse, "FRAME_MS", 0.0)
    rag.init()
    chat._rate_limiter.reset()

    temp_store.init()
    temp_store.create_user({
        "uid": UID,
        "phone": PHONE,
        "password_hash": None,
        "authMethod": "phone-code",
        "nickname": "测试",
        "avatar": "preset:sum",
    })
    app = Starlette(routes=[Route("/api/chat/stream", chat.chat_stream, methods=["POST"])])
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c
    chat._rate_limiter.reset()


def _auth() -> dict[str, str]:
    token = store.issue_token(UID)
    return {"Authorization": f"Bearer {token}"}


def _payloads(text: str) -> list[str]:
    """把 SSE 正文拆成增量字符串(跳过 [DONE] 与非 data 行)。"""
    out: list[str] = []
    for line in text.splitlines():
        if not line.startswith("data:"):
            continue
        raw = line[5:].strip()
        if not raw or raw == "[DONE]":
            continue
        try:
            value = json.loads(raw)
        except json.JSONDecodeError:
            out.append(raw)
            continue
        if isinstance(value, str):
            out.append(value)
    return out


def test_requires_auth(client):
    res = client.post("/api/chat/stream", json={"prompt": "你好"})
    assert res.status_code == 401


def test_stream_ends_with_done_marker(client):
    """每帧都是 data: 行,并且必须以 [DONE] 收尾(前端据此判断"回答完整")。"""
    res = client.post("/api/chat/stream", json={"prompt": "什么是夹逼定理?"}, headers=_auth())
    assert res.status_code == 200
    body = res.text
    assert body.count("[DONE]") == 1
    assert body.rstrip().endswith("data: [DONE]")
    text = "".join(_payloads(body))
    assert text.strip(), "回答正文不能为空"


def test_knowledge_fallback_answers_from_fixture(client):
    """LLM 未配置时走知识库直答:答案里应出现检索到的片段内容。"""
    res = client.post("/api/chat/stream", json={"prompt": "夹逼定理"}, headers=_auth())
    assert res.status_code == 200
    text = "".join(_payloads(res.text))
    assert "夹逼" in text


def test_empty_prompt_does_not_consume_quota(client):
    """新会话问候不占限流额度:连刷 8 次(上限 6)仍应全部 200。"""
    headers = _auth()
    for _ in range(8):
        res = client.post("/api/chat/stream", json={"prompt": ""}, headers=headers)
        assert res.status_code == 200


def test_rate_limit_blocks_seventh_question(client):
    headers = _auth()
    for index in range(chat._RATE_LIMIT_MAX):
        res = client.post("/api/chat/stream", json={"prompt": f"第{index}问:极限"}, headers=headers)
        assert res.status_code == 200, f"第 {index + 1} 次被限流"
    blocked = client.post("/api/chat/stream", json={"prompt": "再问一次"}, headers=headers)
    assert blocked.status_code == 429


def test_usage_recorded_once_per_stream(client):
    """一次完整回答记一条用量;中途没流完的不该记账(这里只验正常路径)。"""
    res = client.post("/api/chat/stream", json={"prompt": "矩阵的秩是什么"}, headers=_auth())
    assert res.status_code == 200

    entries = usage.for_user(UID)
    assert len(entries) == 1, f"应记 1 条,实际 {len(entries)}"
    entry = entries[0]
    assert entry["reply_len"] > 0, "回复字数应大于 0"
    assert entry["workspace"] == "learn"
    assert entry["role"] in {"main", "backup", "deep", "long"}


def test_usage_not_recorded_when_unauthorized(client):
    client.post("/api/chat/stream", json={"prompt": "未登录提问"})
    assert usage.for_user(UID) == []


def test_daily_quota_blocks_further_requests(client, monkeypatch):
    """MG_DAILY_LLM_CALLS=1:当天第一条放行,第二条 429(测评期成本护栏)。"""
    monkeypatch.setenv("MG_DAILY_LLM_CALLS", "1")
    headers = _auth()
    first = client.post("/api/chat/stream", json={"prompt": "夹逼定理"}, headers=headers)
    assert first.status_code == 200
    second = client.post("/api/chat/stream", json={"prompt": "泰勒公式"}, headers=headers)
    assert second.status_code == 429


def test_daily_quota_ignores_empty_prompt(client, monkeypatch):
    """问候不调用模型,不该消耗额度。"""
    monkeypatch.setenv("MG_DAILY_LLM_CALLS", "1")
    headers = _auth()
    assert client.post("/api/chat/stream", json={"prompt": ""}, headers=headers).status_code == 200
    assert client.post("/api/chat/stream", json={"prompt": "极限"}, headers=headers).status_code == 200
    assert client.post("/api/chat/stream", json={"prompt": "极限"}, headers=headers).status_code == 429

