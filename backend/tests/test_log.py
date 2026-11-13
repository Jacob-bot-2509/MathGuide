"""log.py:request_id 上下文、级别解析、日志不泄露正文。"""
from __future__ import annotations

import logging

import log


def test_request_id_default_and_scope():
    assert log.current_request_id() == "-"
    token = log._REQUEST_ID.set("abc123")
    try:
        assert log.current_request_id() == "abc123"
    finally:
        log._REQUEST_ID.reset(token)
    assert log.current_request_id() == "-"


def test_log_record_carries_request_id():
    record = logging.LogRecord("mg.test", logging.INFO, __file__, 1, "hi", None, None)
    log._RequestIdFilter().filter(record)
    assert record.request_id == "-"


def test_level_env(monkeypatch):
    monkeypatch.setenv("MG_LOG_LEVEL", "warning")
    assert log._level() == logging.WARNING
    monkeypatch.setenv("MG_LOG_LEVEL", "nonsense")
    assert log._level() == logging.INFO


def test_logger_namespaced():
    logger = log.get_logger("backend.chat")
    assert logger.name == "mg.chat"
    # 只挂在 mg 命名空间下,不会污染 root logger
    assert logger.parent.name == "mg"


def test_request_id_middleware_assigns_per_request():
    """每个请求一个 id,请求结束后上下文恢复(不会串到下一个请求)。"""
    from starlette.applications import Starlette
    from starlette.middleware import Middleware
    from starlette.responses import JSONResponse
    from starlette.routing import Route
    from starlette.testclient import TestClient

    async def handler(request):
        return JSONResponse({"rid": log.current_request_id()})

    app = Starlette(
        routes=[Route("/_rid", handler)],
        middleware=[Middleware(log.RequestIdMiddleware)],
    )
    with TestClient(app) as client:
        first = client.get("/_rid").json()["rid"]
        second = client.get("/_rid").json()["rid"]
    assert first != "-" and second != "-"
    assert first != second
    assert log.current_request_id() == "-"


def test_format_has_no_free_text():
    """格式里只有时间/级别/request_id/模块名,不会带出问题或回答正文。"""
    assert "%(message)s" in log._DEFAULT_FORMAT
    assert "prompt" not in log._DEFAULT_FORMAT
