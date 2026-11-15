"""main.py:装配冒烟、中间件顺序与启动期降级。

为什么需要:此前所有测试都用手搭的 `Starlette(routes=[...])`(见各 test_*.py),
`main.py` 的装配 —— 路由表、中间件顺序、CORS、安全头、启动期数据迁移 —— **从未被执行过**,
所以它在覆盖率台账里长期是 0%。

要注意的坑:`main` 在**模块级**执行 `store.init()` / `usage.migrate_identity` / `retention.run` /
`rag.init()`,直接 `import main` 会写 `backend/data`。因此这里先 patch 数据路径,再 import。
"""
from __future__ import annotations

import importlib

import pytest
from starlette.applications import Starlette
from starlette.testclient import TestClient

import research_corpus
import retention
import usage


@pytest.fixture()
def main_module(temp_store, temp_usage, monkeypatch):
    """在临时库路径下 import main:模块级 init 只落到 tmp_path,不碰 backend/data。"""
    monkeypatch.setenv("MG_DEMO_MODE", "1")
    monkeypatch.delenv("WEB_CONCURRENCY", raising=False)
    module = importlib.import_module("main")
    return importlib.reload(module)


def test_app_is_starlette_and_routes_registered(main_module):
    assert isinstance(main_module.app, Starlette)
    paths = [getattr(route, "path", "") for route in main_module.app.routes]
    api_paths = [path for path in paths if path.startswith("/api/")]
    # 接口全表见 backend/README.md;这里守住"不要意外掉路由"
    assert len(api_paths) >= 70
    for expected in ("/api/health", "/api/auth/session", "/api/chat/stream", "/api/stats"):
        assert expected in api_paths


def test_no_duplicate_route_registrations(main_module):
    """同路径 + 同方法重复注册时,后一条永远不会命中,属于静默错误。"""
    seen = set()
    for route in main_module.app.routes:
        path = getattr(route, "path", "")
        if not path.startswith("/api/"):
            continue
        key = (path, tuple(sorted(getattr(route, "methods", None) or [])))
        assert key not in seen, f"重复注册: {key}"
        seen.add(key)


def test_health_endpoint(main_module):
    client = TestClient(main_module.app)
    response = client.get("/api/health")
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["service"] == "mg-backend"
    assert isinstance(body["demo"], bool)


def test_unknown_path_is_404(main_module):
    assert TestClient(main_module.app).get("/api/does-not-exist").status_code == 404


def test_get_on_post_only_route_is_405(main_module):
    # /api/chat/stream 只注册了 POST
    assert TestClient(main_module.app).get("/api/chat/stream").status_code == 405


def test_cross_origin_write_blocked_before_business_logic(main_module):
    """中间件顺序:来源校验在业务鉴权之前,跨站请求连 401 都不该看到。"""
    response = TestClient(main_module.app).post(
        "/api/chat/stream",
        json={"prompt": "", "workspace": "learn"},
        headers={"Origin": "https://evil.example"},
    )
    assert response.status_code == 403
    assert "cross-origin" in response.text


def test_cors_preflight_allows_configured_origin(main_module):
    response = TestClient(main_module.app).options(
        "/api/health",
        headers={"Origin": "http://localhost:5173", "Access-Control-Request-Method": "GET"},
    )
    assert response.status_code in (200, 204)
    assert "access-control-allow-origin" in {key.lower() for key in response.headers}


def test_security_headers_are_applied(main_module):
    headers = {key.lower(): value
               for key, value in TestClient(main_module.app).get("/api/health").headers.items()}
    assert headers.get("x-content-type-options") == "nosniff"
    assert "x-frame-options" in headers
    assert headers.get("referrer-policy") == "no-referrer"
    assert "permissions-policy" in headers


def test_stats_requires_admin_then_returns_summary(main_module, temp_store, monkeypatch):
    client = TestClient(main_module.app, raise_server_exceptions=False)
    # 未登录 → 401
    assert client.get("/api/stats").status_code == 401
    # 已登录但非管理员 → 403
    uid = temp_store.create_user({
        "uid": "u-stats", "phone": "13900139001", "password_hash": None,
        "authMethod": "phone-pass", "nickname": "n", "avatar": "preset:sum",
        "createdAt": "2026-01-01T00:00:00",
    })
    headers = {"Authorization": f"Bearer {temp_store.issue_token(uid)}"}
    assert client.get("/api/stats", headers=headers).status_code == 403
    # 管理员 → 200,且 body 是用量汇总
    monkeypatch.setenv("MG_ADMIN_UIDS", uid)
    response = client.get("/api/stats", headers=headers)
    assert response.status_code == 200
    assert isinstance(response.json(), dict)


def test_lifespan_starts_and_stops_retention_task(main_module):
    """进入/退出 lifespan 不应残留后台任务(卸载时会 cancel 并等待)。"""
    with TestClient(main_module.app) as client:
        assert client.get("/api/health").status_code == 200
    # 退出上下文即触发 task.cancel() + await;没有异常即为通过


def test_startup_survives_data_migrations_failing(main_module, monkeypatch):
    """启动期旧数据迁移 / 留存清理失败只能告警,不能让服务起不来。

    caplog 抓不到是因为 backend/log.py 的 logger 不向 root 传播(自带 handler),
    所以这里 patch `log.get_logger`:reload 会重新执行 `from log import get_logger`,
    于是 main 拿到的是记录器而不是真 logger。
    """
    import log as log_module

    records: list[tuple[str, str]] = []

    class _Recorder:
        def info(self, message):
            records.append(("INFO", message))

        def warning(self, message):
            records.append(("WARNING", message))

    monkeypatch.setattr(log_module, "get_logger", lambda _name: _Recorder())
    # 多 worker 的告警现在由 config 发出(启动期硬校验在 config.assert_single_worker 里),
    # 而 config 的 logger 在 import 时就绑定了,所以这里连它一起换成记录器。
    import config as config_module
    monkeypatch.setattr(config_module, "log", _Recorder())
    monkeypatch.setenv("WEB_CONCURRENCY", "4")  # 触发多 worker 告警分支
    monkeypatch.setattr(usage, "migrate_identity", _boom)
    monkeypatch.setattr(retention, "run", lambda: {"accounts": 2, "usage": 3})
    monkeypatch.setattr(research_corpus, "purge_expired_history_all", lambda: 7)

    reloaded = importlib.reload(main_module)
    assert isinstance(reloaded.app, Starlette)

    text = "\n".join(message for _level, message in records)
    assert "worker" in text                      # 多 worker 告警
    assert "旧用量身份迁移失败" in text            # OSError 分支(不阻断启动)
    assert "已清理账号 2 个、用量 3 条" in text      # 有清理结果时的 info 分支
    assert "已清理过期浏览历史 7 条" in text        # 同上

    # 再跑一次:留存清理本身抛 OSError,同样只能告警
    monkeypatch.setattr(retention, "run", _boom)
    monkeypatch.setattr(research_corpus, "purge_expired_history_all", _boom)
    records.clear()
    importlib.reload(main_module)
    text = "\n".join(message for _level, message in records)
    assert "留存清理失败" in text
    assert "浏览历史清理失败" in text


def _boom(*_args, **_kwargs):
    raise OSError("disk on fire")
