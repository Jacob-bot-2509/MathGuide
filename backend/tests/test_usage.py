"""usage.py:SQLite 写入、旧格式导入、身份清洗、按账号导出/删除与保留上限。"""
from __future__ import annotations

import json
import pytest

import db
import usage


def _setup(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    monkeypatch.setattr(db, "DB_PATH", data_dir / "mathguide.db")
    monkeypatch.setattr(usage, "DATA_DIR", data_dir)
    monkeypatch.setattr(usage, "PATH", data_dir / "usage.jsonl")
    monkeypatch.setattr(usage, "LEGACY_PATH", data_dir / "usage.json")
    db.reset_for_tests()
    usage.reset_for_tests()


def _record(uid: str, reply_len: int = 1, ts: float = 1.0) -> None:
    usage.record(uid=uid, cmd="", prompt_len=0,
                 reply_len=reply_len, role="main", research=False, ts=ts)


def _rows() -> list[dict]:
    conn = db.connect()
    try:
        rows = conn.execute("SELECT uid, ts, doc FROM usage ORDER BY id").fetchall()
    finally:
        conn.close()
    return [json.loads(row["doc"]) for row in rows]


def test_record_and_summary(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    usage.record(uid="u-A", cmd="提问", prompt_len=10,
                 reply_len=5, role="main", research=False, ts=1.0)
    usage.record(uid="u-B", cmd="研究", prompt_len=20,
                 reply_len=7, role="deep", research=True, ts=2.0)

    summary = usage.summary()
    assert summary["calls"] == 2
    assert summary["totalChars"] == 12
    assert summary["roles"] == {"main": 1, "deep": 1}
    by_uid = {u["uid"]: u for u in summary["users"]}
    assert by_uid["u-A"]["chars"] == 5
    assert by_uid["u-B"]["chars"] == 7
    for entry in _rows():
        assert "uid" in entry
        assert "phone" not in entry and "user" not in entry


def test_records_are_persisted_in_order(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    _record("u1", ts=1.0)
    _record("u2", ts=2.0)
    assert [entry["uid"] for entry in _rows()] == ["u1", "u2"]


def test_max_calls_trims_oldest(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    monkeypatch.setattr(usage, "_MAX_CALLS", 3)
    for i in range(5):
        _record(f"u{i}", ts=float(i))
    summary = usage.summary()
    assert summary["calls"] == 3
    assert {u["uid"] for u in summary["users"]} == {"u2", "u3", "u4"}
    assert len(_rows()) == 3


def test_legacy_json_array_is_imported_and_sanitized(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    legacy = [
        {"user": "old1", "phone": "13800138000", "cmd": "", "prompt_len": 0,
         "reply_len": 2, "role": "main", "research": False, "ts": 1.0},
        {"user": "old2", "phone": "", "cmd": "", "prompt_len": 0,
         "reply_len": 3, "role": "deep", "research": True, "ts": 2.0},
    ]
    (tmp_path / "data" / "usage.json").write_text(json.dumps(legacy), encoding="utf-8")

    assert usage.summary()["calls"] == 2
    assert usage.migrate_identity({"13800138000": "u-old1"}) > 0
    _record("new", reply_len=4, ts=3.0)

    entries = _rows()
    assert [entry["uid"] for entry in entries] == ["u-old1", "anonymous", "new"]
    assert all("phone" not in entry and "user" not in entry for entry in entries)
    assert (tmp_path / "data" / "usage.json").exists()  # 旧文件保留作备份
    backup = json.loads((tmp_path / "data" / "usage.json").read_text(encoding="utf-8"))
    assert all("phone" not in entry and "user" not in entry for entry in backup), \
        "旧备份里还留着 PII"


def test_legacy_jsonl_is_imported_once(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    path = tmp_path / "data" / "usage.jsonl"
    path.write_text(
        json.dumps({"uid": "u-A", "ts": 1.0, "reply_len": 2, "role": "main"}) + "\n"
        + json.dumps({"uid": "u-B", "ts": 2.0, "reply_len": 3, "role": "main"}) + "\n",
        encoding="utf-8",
    )
    assert usage.summary()["calls"] == 2
    usage.reset_for_tests()
    assert usage.summary()["calls"] == 2, "重启后重复导入"


def test_migrate_identity_is_idempotent(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    _record("u-A")
    assert usage.migrate_identity({"13800138000": "u-A"}) == 0
    assert usage.migrate_identity({}) == 0


def test_for_user_scopes_and_redacts_legacy(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    _record("u-A", reply_len=2)
    _record("u-B", reply_len=3)
    conn = db.connect()
    try:
        with conn:
            conn.execute(
                "INSERT INTO usage(uid, ts, doc) VALUES(?, ?, ?)",
                ("", 9.0, json.dumps({
                    "ts": 9.0, "user": "old", "phone": "13800138000",
                    "cmd": "旧", "prompt_len": 1, "reply_len": 4,
                    "role": "main", "research": False,
                }, ensure_ascii=False)),
            )
    finally:
        conn.close()

    rows = usage.for_user("u-A")
    assert [row["reply_len"] for row in rows] == [2]
    assert all("phone" not in row and "user" not in row and "uid" not in row
               for row in rows)

    legacy_rows = usage.for_user("u-legacy", "13800138000")
    assert len(legacy_rows) == 1 and legacy_rows[0]["reply_len"] == 4
    assert "phone" not in legacy_rows[0] and "user" not in legacy_rows[0]


def test_delete_user_removes_uid_and_legacy_phone_records(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    _record("u-A", reply_len=2)
    _record("u-B", reply_len=3)
    conn = db.connect()
    try:
        with conn:
            conn.execute(
                "INSERT INTO usage(uid, ts, doc) VALUES(?, ?, ?)",
                ("", 9.0, json.dumps({
                    "ts": 9.0, "user": "old", "phone": "13800138000",
                    "cmd": "旧", "prompt_len": 1, "reply_len": 4,
                    "role": "main", "research": False,
                }, ensure_ascii=False)),
            )
    finally:
        conn.close()

    assert usage.delete_user("missing") == 0
    assert usage.delete_user("u-A") == 1
    assert [entry.get("uid") for entry in _rows()] == ["u-B", None]
    assert usage.delete_user("u-legacy", "13800138000") == 1
    assert [entry["uid"] for entry in _rows()] == ["u-B"]
    assert usage.summary()["calls"] == 1


def test_corrupt_legacy_lines_block_migration(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    path = tmp_path / "data" / "usage.jsonl"
    path.write_text(
        "\n".join([
            json.dumps({"user": "ok", "reply_len": 1, "role": "main"}),
            "{not json",
            json.dumps([1, 2, 3]),
            "",
        ]) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match=":2:"):
        usage.summary()
    assert db.get_meta(usage.MIGRATION_KEY) is None
    path.write_text(json.dumps({"user": "ok", "reply_len": 1, "role": "main"}) + "\n", encoding="utf-8")
    assert usage.summary()["calls"] == 1


def test_delete_user_cleans_legacy_backup(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    legacy = [
        {"uid": "u-A", "ts": 1.0, "cmd": "", "prompt_len": 0, "reply_len": 1,
         "role": "main", "research": False},
        {"uid": "u-B", "ts": 2.0, "cmd": "", "prompt_len": 0, "reply_len": 2,
         "role": "main", "research": False},
    ]
    path = tmp_path / "data" / "usage.json"
    path.write_text(json.dumps(legacy), encoding="utf-8")

    assert usage.delete_user("u-A") == 2
    backup = json.loads(path.read_text(encoding="utf-8"))
    assert [entry["uid"] for entry in backup] == ["u-B"]
    assert [entry["uid"] for entry in _rows()] == ["u-B"]


def test_prune_older_than_removes_rows(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    _record("old", ts=1.0)
    _record("new", ts=100.0)
    removed = usage.prune_older_than(1.0, now=86450.0)
    assert removed == 1
    assert [entry["uid"] for entry in _rows()] == ["new"]
