"""PDF 导出并发闸门:同时能起几个浏览器、排不下就 429、槽位必须归还。

为什么值得单独测:闸门是**唯一**防"导出把服务器打 OOM"的机制,而它失效的方式
很安静 —— 多半是"没关好门"(槽位泄漏)或"门形同虚设"(上限没生效),线上表现为
内存曲线随导出次数单调上升,而不是某个接口报错。
"""
from __future__ import annotations

import asyncio
import threading
import time

import pytest
from starlette.applications import Starlette
from starlette.exceptions import HTTPException
from starlette.routing import Route
from starlette.testclient import TestClient

import doc
import docgen


@pytest.fixture(autouse=True)
def _clean_gate():
    """每条用例都从"零在跑、零排队"开始,并且结束后还回去。"""
    doc._pdf_gate_reset()
    yield
    doc._pdf_gate_reset()


def test_gate_rejects_immediately_when_queue_is_full(monkeypatch):
    monkeypatch.setenv("MG_PDF_CONCURRENCY", "1")
    monkeypatch.setenv("MG_PDF_QUEUE", "0")  # 不排队:第二个请求必须立刻被拒
    with doc.pdf_slot():
        started = time.monotonic()
        with pytest.raises(doc.PdfBusy):
            with doc.pdf_slot():
                pass
        assert time.monotonic() - started < 1.0  # 不是"等一会儿再拒",是立刻


def test_gate_waits_for_free_slot_within_timeout(monkeypatch):
    monkeypatch.setenv("MG_PDF_CONCURRENCY", "1")
    monkeypatch.setenv("MG_PDF_QUEUE", "1")
    monkeypatch.setenv("MG_PDF_QUEUE_WAIT", "5")
    entered = threading.Event()
    errors: list[BaseException] = []

    def waiter():
        try:
            with doc.pdf_slot():
                entered.set()
        except BaseException as exc:  # noqa: BLE001 线程里必须自己收
            errors.append(exc)

    with doc.pdf_slot():
        thread = threading.Thread(target=waiter, daemon=True)
        thread.start()
        time.sleep(0.15)
        assert not entered.is_set()  # 槽位还占着,只能等
        assert doc._gate.snapshot() == (1, 1)
    thread.join(timeout=5)
    assert errors == []
    assert entered.is_set()  # 槽位一释放就轮到它


def test_gate_gives_up_after_wait_timeout(monkeypatch):
    monkeypatch.setenv("MG_PDF_CONCURRENCY", "1")
    monkeypatch.setenv("MG_PDF_QUEUE", "1")
    monkeypatch.setenv("MG_PDF_QUEUE_WAIT", "0.1")
    with doc.pdf_slot():
        started = time.monotonic()
        with pytest.raises(doc.PdfBusy):
            with doc.pdf_slot():
                pass
        assert time.monotonic() - started >= 0.05  # 确实等过,不是队列满直接拒


def test_gate_does_not_leak_slots_when_body_raises(monkeypatch):
    monkeypatch.setenv("MG_PDF_CONCURRENCY", "1")
    monkeypatch.setenv("MG_PDF_QUEUE", "0")
    with pytest.raises(ValueError):
        with doc.pdf_slot():
            raise ValueError("boom")
    assert doc._gate.snapshot() == (0, 0)
    with doc.pdf_slot():  # 槽位还回来了
        pass


def test_env_values_are_clamped_and_typos_fall_back(monkeypatch):
    monkeypatch.setenv("MG_PDF_CONCURRENCY", "99")
    assert doc.pdf_concurrency_limit() == 8
    monkeypatch.setenv("MG_PDF_CONCURRENCY", "0")
    assert doc.pdf_concurrency_limit() == 1  # 0 个浏览器等于导出功能消失,不许
    monkeypatch.setenv("MG_PDF_QUEUE", "-3")
    assert doc.pdf_queue_limit() == 0
    monkeypatch.setenv("MG_PDF_QUEUE_WAIT", "abc")
    assert doc.pdf_queue_wait() == doc.PDF_QUEUE_WAIT_DEFAULT


def test_html_to_pdf_wraps_browser_call_with_gate(monkeypatch, tmp_path):
    monkeypatch.setenv("MG_PDF_CONCURRENCY", "1")
    monkeypatch.setenv("MG_PDF_QUEUE", "0")
    calls: list[tuple] = []

    def fake_render(html_path, pdf_path):
        calls.append((html_path, pdf_path))
        return b"%PDF-1.4 fake"

    monkeypatch.setattr(doc, "_html_to_pdf_ungated", fake_render)
    html_path, pdf_path = tmp_path / "a.html", tmp_path / "a.pdf"

    assert doc._html_to_pdf(html_path, pdf_path) == b"%PDF-1.4 fake"
    assert doc._gate.snapshot() == (0, 0)  # 成功路径也把槽位还了

    with doc.pdf_slot():
        with pytest.raises(doc.PdfBusy):
            doc._html_to_pdf(html_path, pdf_path)
        # 被拒的请求根本没起浏览器:这是"内存不会涨"的直接证据
        assert len(calls) == 1
        # 能力探测不受闸门影响(否则"正好有人在导出"会被判成机器不能出 PDF)
        assert doc._html_to_pdf(html_path, pdf_path, gated=False) == b"%PDF-1.4 fake"


def test_export_pdf_returns_429_with_retry_after(monkeypatch, tmp_path):
    monkeypatch.setenv("MG_PDF_CONCURRENCY", "1")
    monkeypatch.setenv("MG_PDF_QUEUE", "0")
    monkeypatch.setattr(doc, "require_auth", lambda request: {"uid": "u1"})
    monkeypatch.setattr(doc, "_rate_check", lambda account: None)

    async def fake_stream(*args, **kwargs):
        if False:  # pragma: no cover - 只为让它成为异步生成器
            yield ""

    monkeypatch.setattr(doc.llm, "stream_chat", fake_stream)

    async def fake_record(*args, **kwargs):
        return None

    monkeypatch.setattr(doc, "_record", fake_record)

    app = Starlette(routes=[Route("/api/doc/export", doc.export_pdf, methods=["POST"])])
    client = TestClient(app, raise_server_exceptions=False)

    with doc.pdf_slot():
        res = client.post("/api/doc/export", json={"content": "正文", "lang": "zh"})
    assert res.status_code == 429
    assert res.json()["detail"] == "pdf export busy, retry later"
    assert res.headers["Retry-After"] == str(doc.PdfBusy.retry_after)


def test_docgen_render_maps_busy_to_429(monkeypatch):
    monkeypatch.setenv("MG_PDF_CONCURRENCY", "1")
    monkeypatch.setenv("MG_PDF_QUEUE", "0")

    def busy(*args, **kwargs):
        raise doc.PdfBusy("满了")

    document = {"title": "文档", "sections": [{"heading": "一", "paragraphs": ["正文"]}]}
    monkeypatch.setattr(docgen.doc, "render_pdf_bytes", busy)
    with doc.pdf_slot():
        with pytest.raises(HTTPException) as excinfo:
            asyncio.run(docgen._render(document, "zh", "pdf", "mg-qa"))
    assert excinfo.value.status_code == 429
    assert excinfo.value.headers["Retry-After"] == str(doc.PdfBusy.retry_after)

