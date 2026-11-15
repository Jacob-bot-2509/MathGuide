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
import diagnosis  # noqa: E402
import diagram_alerts  # noqa: E402
import diagram_metrics  # noqa: E402
import research_corpus  # noqa: E402
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


@pytest.fixture(autouse=True)
def isolate_research_data_dir(tmp_path, monkeypatch):
    """把科研语料的落盘根目录重定向到 tmp_path。

    `research_corpus.DATA_DIR` 默认是 `backend/data/research`,而研究区端点(文献检索缓存、
    语料索引)会按 uid 在那个目录下建 `index.sqlite3`。有些用例只打 `monkeypatch` 就调端点,
    于是把 `u-lit-cache` 这类测试索引写进了真实 data 目录 —— 与本文件开头"不碰 backend/data"
    的约定相悖,部署前也会变成来路不明的残留。

    统一在这里兜底:用例自己再 `setattr` 的(79 处)会在其后覆盖,行为不变。
    """
    monkeypatch.setattr(research_corpus, "DATA_DIR", tmp_path / "research-tmp")


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
    # 同一临时库:usage/diagnosis 的旧文件路径也必须指向临时目录,
    # 否则初始化会把 backend/data 里的真实旧数据导入测试库(计数被污染)
    monkeypatch.setattr(usage, "PATH", data_dir / "usage.jsonl")
    monkeypatch.setattr(usage, "LEGACY_PATH", data_dir / "usage.json")
    monkeypatch.setattr(diagnosis, "PATH", data_dir / "diagnoses.jsonl")
    monkeypatch.setattr(research_corpus, "DATA_DIR", data_dir / "research")
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
    monkeypatch.setattr(diagnosis, "PATH", data_dir / "diagnoses.jsonl")
    store.reset_for_tests()
    usage.reset_for_tests()
    diagnosis.reset_for_tests()
    yield usage
    store.reset_for_tests()
    usage.reset_for_tests()
    diagnosis.reset_for_tests()
