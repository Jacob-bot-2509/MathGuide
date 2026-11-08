"""后端测试基座。

原则:不读真实 .env.local、不访问网络、不碰 backend/data 与 knowledge/。
每个测试用 tmp_path 建独立数据目录;需要改全局状态的 fixture 负责恢复。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import auth  # noqa: E402
import db  # noqa: E402
import diagram_alerts  # noqa: E402
import diagram_metrics  # noqa: E402
import diagnosis  # noqa: E402
import research_diagrams  # noqa: E402
import session_cache  # noqa: E402
import store  # noqa: E402
import usage  # noqa: E402


@pytest.fixture(autouse=True)
def clean_global_state(monkeypatch):
    """每个测试前后清空会话缓存与认证限流,避免测试互相污染。"""
    # 图解语义校验会调真实模型;测试默认关闭,需要时在用例里显式开启。
    monkeypatch.setenv("MG_DIAGRAM_VERIFY", "0")
    session_cache.reset()
    auth._auth_limiter.reset()
    research_diagrams.reset_planner_breaker()
    diagram_metrics.reset()
    diagram_alerts.reset_for_tests()
    yield
    session_cache.reset()
    auth._auth_limiter.reset()
    research_diagrams.reset_planner_breaker()
    diagram_metrics.reset()
    diagram_alerts.reset_for_tests()


@pytest.fixture()
def temp_store(tmp_path, monkeypatch):
    """独立 SQLite 库 + 旧 JSON 路径;每个测试一个全新库文件。"""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    monkeypatch.setattr(db, "DB_PATH", data_dir / "mathguide.db")
    monkeypatch.setattr(store, "DATA_DIR", data_dir)
    monkeypatch.setattr(store, "DB_PATH", data_dir / "mathguide.db")
    monkeypatch.setattr(store, "USERS_PATH", data_dir / "users.json")
    monkeypatch.setattr(store, "TOKENS_PATH", data_dir / "tokens.json")
    store.reset_for_tests()
    usage.reset_for_tests()
    diagnosis.reset_for_tests()
    yield store
    store.reset_for_tests()
    usage.reset_for_tests()
    diagnosis.reset_for_tests()


@pytest.fixture()
def temp_usage(tmp_path, monkeypatch):
    """独立 SQLite 库与旧 usage 文件路径,避免测试碰 backend/data。"""
    data_dir = tmp_path / "data"
    data_dir.mkdir(exist_ok=True)
    monkeypatch.setattr(db, "DB_PATH", data_dir / "mathguide.db")
    monkeypatch.setattr(store, "DATA_DIR", data_dir)
    monkeypatch.setattr(usage, "DATA_DIR", data_dir)
    monkeypatch.setattr(usage, "PATH", data_dir / "usage.jsonl")
    monkeypatch.setattr(usage, "LEGACY_PATH", data_dir / "usage.json")
    store.reset_for_tests()
    usage.reset_for_tests()
    diagnosis.reset_for_tests()
    yield usage
    store.reset_for_tests()
    usage.reset_for_tests()
    diagnosis.reset_for_tests()
