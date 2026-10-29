"""docgen.py:问答提取、问答/文档渲染、严格依据的大纲与分节生成。"""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from starlette.applications import Starlette
from starlette.routing import Route
from starlette.testclient import TestClient

import docgen

ANSWER = "导数是函数在一点的瞬时变化率。\n\n记作 $f'(x)$。"


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setattr(docgen, "require_auth", lambda request: {"uid": "u-1"})
    monkeypatch.setattr(docgen, "_rate_check", lambda uid: None)
    monkeypatch.setattr(docgen, "_record", lambda *a, **k: None)
    app = Starlette(routes=[
        Route("/api/doc/questions", docgen.questions, methods=["POST"]),
        Route("/api/doc/qa", docgen.qa_export, methods=["POST"]),
        Route("/api/doc/outline", docgen.outline, methods=["POST"]),
        Route("/api/doc/generate", docgen.generate, methods=["POST"]),
        Route("/api/doc/render", docgen.render, methods=["POST"]),
    ])
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


def test_questions_extracts_pairs_and_filters_commands(client):
    res = client.post("/api/doc/questions", json={"messages": [
        {"role": "user", "content": "什么是导数"},
        {"role": "assistant", "content": ANSWER},
        {"role": "user", "content": "章节知识导航", "cmd": "章节知识导航"},
        {"role": "assistant", "content": "..."},
        {"role": "user", "content": "什么是极限"},
        {"role": "assistant", "content": ""},
        {"role": "user", "content": "什么是导数"},
        {"role": "assistant", "content": "重复问题"},
    ]})
    assert res.status_code == 200
    items = res.json()["items"]
    assert [item["question"] for item in items] == ["什么是导数", "什么是极限"]
    assert items[0]["has_answer"] is True
    assert items[1]["has_answer"] is False


def test_qa_export_markdown_uses_original_answer(client):
    res = client.post("/api/doc/qa", json={
        "items": [{"question": "什么是导数", "answer": ANSWER}],
        "source": "当前对话",
        "lang": "zh",
        "format": "md",
    })
    assert res.status_code == 200
    assert "text/markdown" in res.headers["content-type"]
    body = res.content.decode("utf-8")
    assert "# 问题解答文档" in body
    assert "什么是导数" in body
    assert "瞬时变化率" in body
    assert "当前对话" in body


def test_qa_export_docx_is_valid_zip(client):
    res = client.post("/api/doc/qa", json={
        "items": [{"question": "什么是导数", "answer": ANSWER}], "lang": "zh", "format": "docx",
    })
    assert res.status_code == 200
    assert res.content[:2] == b"PK"
    assert "wordprocessingml" in res.headers["content-type"]


def test_qa_export_rejects_empty_items(client):
    assert client.post("/api/doc/qa", json={"items": []}).status_code == 400
    assert client.post("/api/doc/qa", json={
        "items": [{"question": "q", "answer": "a"}],
        "source": "x", "format": "md"}).status_code == 200


def test_render_rejects_oversized_document(client):
    document = {"title": "T", "sections": [
        {"heading": "H", "paragraphs": ["x" * 100_001]},
    ]}
    assert client.post("/api/doc/render", json={"document": document}).status_code == 413


def test_outline_without_evidence_is_422(client, monkeypatch):
    monkeypatch.setattr(docgen.rag, "search", lambda query, top_k: [])
    res = client.post("/api/doc/outline", json={"request": "写一份泰勒展开讲义"})
    assert res.status_code == 422
    assert res.json()["error"] == "no_evidence"


def test_generate_requires_evidence_and_builds_document(client, monkeypatch):
    chunk = SimpleNamespace(
        id="c1", title="泰勒展开", section="定义",
        text="泰勒展开用多项式逼近函数。", keywords=[], category="analysis")
    monkeypatch.setattr(docgen.rag, "search", lambda query, top_k: [(chunk, 1.0)])
    monkeypatch.setattr(docgen.rag.llm, "is_configured", lambda role="main": True)

    async def fake_llm(system, user, *, max_tokens):
        return "泰勒展开把函数写成幂级数。\n\n收敛半径决定适用范围。"

    monkeypatch.setattr(docgen, "_collect_llm", fake_llm)
    body = {
        "request": "写一份泰勒展开讲义",
        "lang": "zh",
        "outline": {"title": "泰勒展开", "sections": [
            {"heading": "定义", "points": ["幂级数"], "evidence_ids": ["E1"]},
            {"heading": "无依据章节", "points": [], "evidence_ids": []},
        ]},
    }
    res = client.post("/api/doc/generate", json=body)
    assert res.status_code == 200
    data = res.json()
    assert data["document"]["title"] == "泰勒展开"
    assert data["document"]["sections"][0]["heading"] == "定义"
    assert data["document"]["references"][0]["title"] == "泰勒展开"
    assert data["gaps"] == ["无依据章节"]


def test_normalize_outline_marks_missing_evidence():
    evidence = [{"id": "E1", "title": "T", "section": "S", "text": "x"}]
    plan = docgen._normalize_outline({
        "title": "Doc",
        "sections": [
            {"heading": "A", "points": ["p"], "evidence_ids": ["E1"]},
            {"heading": "B", "points": ["q"], "evidence_ids": ["missing"]},
        ],
    }, evidence, "req", "zh")
    assert plan["sections"][0]["has_evidence"] is True
    assert plan["sections"][1]["has_evidence"] is False
    assert "B" in plan["gaps"]


def test_clean_markdown_strips_visible_syntax_not_math():
    text = "### 标题\n\n> 引用\n\n---\n\n* 条目 [是](cmd://nb/yes)\n\n公式 $f'(x)$ 保留"
    cleaned = docgen._clean_markdown(text)
    assert "###" not in cleaned and "> 引用" not in cleaned and "---" not in cleaned
    assert "[是]" not in cleaned and "cmd://" not in cleaned
    assert "$f'(x)$" in cleaned
    assert "• 条目" in cleaned
