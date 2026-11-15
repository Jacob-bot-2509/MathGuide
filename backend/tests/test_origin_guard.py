"""origin_guard.py:写方法的跨站来源拦截。"""
from __future__ import annotations

import pytest
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from origin_guard import OriginGuardMiddleware

ALLOWED = ["http://localhost:5173"]


def _client() -> TestClient:
    async def write(request):
        return JSONResponse({"ok": True})

    app = Starlette(
        routes=[Route("/api/write", write, methods=["POST"]), Route("/api/read", write)],
        middleware=[Middleware(OriginGuardMiddleware, allowed_origins=ALLOWED)],
    )
    return TestClient(app)


def test_same_origin_write_is_allowed():
    res = _client().post("/api/write", headers={"host": "mg.example.com",
                                                "origin": "https://mg.example.com"})
    assert res.status_code == 200


def test_cross_site_write_is_blocked():
    res = _client().post("/api/write", headers={"host": "mg.example.com",
                                                "origin": "https://evil.test"})
    assert res.status_code == 403
    assert res.json()["detail"] == "cross-origin request blocked"


def test_configured_cors_origin_is_allowed():
    """前端直连后端(非同源)时靠 MG_CORS_ORIGINS 放行,校验口径必须与它一致。"""
    res = _client().post("/api/write", headers={"host": "127.0.0.1:8000",
                                                "origin": "http://localhost:5173"})
    assert res.status_code == 200


def test_safe_methods_are_not_checked():
    res = _client().get("/api/read", headers={"host": "mg.example.com",
                                              "origin": "https://evil.test"})
    assert res.status_code == 200


def test_referer_is_used_when_origin_missing():
    bad = _client().post("/api/write", headers={"host": "mg.example.com",
                                                "referer": "https://evil.test/page"})
    assert bad.status_code == 403
    good = _client().post("/api/write", headers={"host": "mg.example.com",
                                                 "referer": "https://mg.example.com/page"})
    assert good.status_code == 200


def test_non_browser_client_without_origin_passes():
    """curl / 脚本 / 测试不带 Origin,不受 CSRF 影响,不能拦。"""
    res = _client().post("/api/write", headers={"host": "mg.example.com"})
    assert res.status_code == 200


def test_scheme_mismatch_behind_proxy_still_passes():
    """反代常把 scheme 改写:只比 netloc,避免 HTTPS 站点被自家 http:// 判成跨站。"""
    res = _client().post("/api/write", headers={"host": "mg.example.com",
                                                "origin": "http://mg.example.com"})
    assert res.status_code == 200


@pytest.mark.parametrize("path", ["/api/auth/login", "/api/auth/register"])
def test_login_pages_are_exempt(path):
    async def handler(request):
        return JSONResponse({"ok": True})

    app = Starlette(
        routes=[Route(path, handler, methods=["POST"])],
        middleware=[Middleware(OriginGuardMiddleware, allowed_origins=[])],
    )
    res = TestClient(app).post(path, headers={"host": "mg.example.com",
                                              "origin": "https://eval-notes.example"})
    assert res.status_code == 200
