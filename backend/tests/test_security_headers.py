"""security_headers.py:API 基础安全头与 HSTS 条件。"""
from __future__ import annotations

from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from security_headers import SecurityHeadersMiddleware


async def _ok(request):
    return JSONResponse({"ok": True})


def _client(base_url: str = "http://testserver") -> TestClient:
    app = Starlette(
        routes=[Route("/ok", _ok)],
        middleware=[Middleware(SecurityHeadersMiddleware)],
    )
    return TestClient(app, base_url=base_url, raise_server_exceptions=False)


def test_basic_headers_on_http():
    res = _client().get("/ok")
    assert res.status_code == 200
    assert res.headers["x-content-type-options"] == "nosniff"
    assert res.headers["referrer-policy"] == "no-referrer"
    assert res.headers["x-frame-options"] == "DENY"
    assert "microphone=(self)" in res.headers["permissions-policy"]
    assert "strict-transport-security" not in res.headers


def test_hsts_on_https():
    res = _client("https://testserver").get("/ok")
    assert res.headers["strict-transport-security"].startswith("max-age=")


def test_hsts_behind_https_proxy():
    res = _client().get("/ok", headers={"x-forwarded-proto": "https"})
    assert "strict-transport-security" in res.headers


def test_hsts_can_be_forced_by_env(monkeypatch):
    monkeypatch.setenv("MG_ENABLE_HSTS", "1")
    res = _client().get("/ok")
    assert "strict-transport-security" in res.headers
