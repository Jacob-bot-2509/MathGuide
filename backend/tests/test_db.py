"""db.py:SQLite 连接、事务、meta 标记与旧 JSON/JSONL 读取。

此前没有专门测试文件,83% 是 store/usage 的用例顺带蹭到的 —— 也就是说连接失败、
WAL 重试、坏行拒绝这些**只在这层才会发生**的分支从来没被验证过。
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

import db


@pytest.fixture()
def temp_db(tmp_path, monkeypatch):
    """把库文件指到 tmp_path,避免碰 backend/data。"""
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "mathguide.db")
    yield tmp_path / "mathguide.db"
    db.reset_for_tests()


def test_connect_sets_wal_and_row_factory(temp_db):
    conn = db.connect()
    try:
        mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        assert mode.lower() == "wal"
        assert conn.row_factory is sqlite3.Row
    finally:
        conn.close()


def test_connect_closes_connection_when_pragma_fails(temp_db, monkeypatch):
    """初始化失败必须关掉连接,否则 WAL 文件会被长期占用。"""
    closed = {"value": False}

    class _Broken:
        row_factory = None

        def execute(self, *_args, **_kwargs):
            raise sqlite3.OperationalError("boom")

        def close(self):
            closed["value"] = True

    monkeypatch.setattr(db.sqlite3, "connect", lambda *_a, **_k: _Broken())
    with pytest.raises(sqlite3.OperationalError):
        db.connect()
    assert closed["value"] is True


def test_connect_retries_on_busy_then_succeeds(temp_db, monkeypatch):
    """首次切 WAL 可能撞锁:busy/locked 要重试,而不是立刻失败。"""
    attempts = {"n": 0}

    class _Result:
        def fetchone(self):
            return ("wal",)

    class _BusyOnce:
        row_factory = None

        def execute(self, sql, *args, **kwargs):
            if "journal_mode" in sql:
                attempts["n"] += 1
                if attempts["n"] == 1:
                    error = sqlite3.OperationalError("database is locked")
                    error.sqlite_errorcode = sqlite3.SQLITE_BUSY
                    raise error
            return _Result()

        def close(self):
            pass

    monkeypatch.setattr(db.sqlite3, "connect", lambda *_a, **_k: _BusyOnce())
    assert db.connect() is not None
    assert attempts["n"] == 2


def test_connect_raises_for_non_busy_error(temp_db, monkeypatch):
    class _Other:
        row_factory = None

        def execute(self, sql, *args, **kwargs):
            error = sqlite3.OperationalError("syntax error")
            error.sqlite_errorcode = sqlite3.SQLITE_ERROR
            raise error

        def close(self):
            pass

    monkeypatch.setattr(db.sqlite3, "connect", lambda *_a, **_k: _Other())
    with pytest.raises(sqlite3.OperationalError, match="syntax error"):
        db.connect()


def test_init_creates_all_tables_idempotently(temp_db):
    db.init()
    db.init()  # 第二次不应报错
    conn = db.connect()
    try:
        names = {row["name"] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
    finally:
        conn.close()
    assert {"users", "tokens", "usage", "diagnoses", "meta"} <= names


def test_meta_roundtrip_and_overwrite(temp_db):
    db.init()
    assert db.get_meta("migrated") is None
    db.set_meta("migrated", "1")
    assert db.get_meta("migrated") == "1"
    db.set_meta("migrated", "2")      # upsert 分支
    assert db.get_meta("migrated") == "2"


def test_transaction_commits_and_rolls_back(temp_db):
    db.init()
    with db.transaction() as conn:
        conn.execute("INSERT INTO meta(key, value) VALUES('k', 'v')")
    assert db.get_meta("k") == "v"

    with pytest.raises(RuntimeError):
        with db.transaction() as conn:
            conn.execute("INSERT INTO meta(key, value) VALUES('k2', 'v2')")
            raise RuntimeError("boom")
    assert db.get_meta("k2") is None


def test_table_empty_and_unknown_table(temp_db):
    db.init()
    assert db.table_empty("users") is True
    with db.transaction() as conn:
        conn.execute("INSERT INTO users(uid, doc) VALUES('u-1', '{}')")
    assert db.table_empty("users") is False
    # 表名是白名单,外部字符串拼不进 SQL
    with pytest.raises(ValueError, match="未知表名"):
        db.table_empty("users; DROP TABLE users")


def test_reset_for_tests_removes_db_and_is_idempotent(temp_db):
    db.init()
    assert Path(temp_db).exists()
    db.reset_for_tests()
    assert not Path(temp_db).exists()
    db.reset_for_tests()   # 文件已不存在时不应抛异常


def test_read_json_missing_and_valid(tmp_path):
    assert db.read_json(tmp_path / "nope.json") is None
    path = tmp_path / "ok.json"
    path.write_text(json.dumps({"a": 1}), encoding="utf-8")
    assert db.read_json(path) == {"a": 1}


def test_read_jsonl_skips_blanks_and_rejects_bad_lines(tmp_path):
    assert db.read_jsonl(tmp_path / "missing.jsonl") == []

    good = tmp_path / "good.jsonl"
    good.write_text('{"a": 1}\n\n{"b": 2}\n', encoding="utf-8")
    assert db.read_jsonl(good) == [{"a": 1}, {"b": 2}]

    broken = tmp_path / "broken.jsonl"
    broken.write_text('{"a": 1}\nnot-json\n', encoding="utf-8")
    with pytest.raises(ValueError, match="无效 JSON"):
        db.read_jsonl(broken)

    not_object = tmp_path / "scalar.jsonl"
    not_object.write_text('[1, 2]\n', encoding="utf-8")
    with pytest.raises(ValueError, match="必须是对象"):
        db.read_jsonl(not_object)


def test_write_legacy_replaces_atomically_and_leaves_no_temp(tmp_path):
    path = tmp_path / "legacy.jsonl"
    path.write_text("old\n", encoding="utf-8")

    db.write_legacy(path, "new\n")

    assert path.read_text(encoding="utf-8") == "new\n"
    assert [item.name for item in tmp_path.iterdir() if item.name.endswith(".tmp")] == []


def test_remove_jsonl_returns_count_and_rewrites_only_when_needed(tmp_path):
    path = tmp_path / "usage.jsonl"
    path.write_text(
        '{"uid": "u-1"}\n{"uid": "u-2"}\n{"uid": "u-1"}\n', encoding="utf-8")

    assert db.remove_jsonl(path, lambda entry: entry["uid"] == "u-1") == 2
    assert [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()] == [
        {"uid": "u-2"}]

    # 没有匹配项时不重写文件
    before = path.read_text(encoding="utf-8")
    assert db.remove_jsonl(path, lambda entry: False) == 0
    assert path.read_text(encoding="utf-8") == before
