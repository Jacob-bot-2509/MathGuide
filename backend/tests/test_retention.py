"""retention.py:按环境变量清理不活跃账号与过期用量。"""
from __future__ import annotations

import json
from datetime import datetime

import auth
import retention
import store
import usage


def _user(uid: str, phone: str, last_active: str) -> dict:
    return {
        "uid": uid,
        "phone": phone,
        "password_hash": None,
        "authMethod": "phone-code",
        "nickname": f"n-{uid}",
        "avatar": "preset:sum",
        "createdAt": last_active,
        "lastActiveAt": last_active,
    }


def _ts(value: str) -> float:
    return datetime.fromisoformat(value).timestamp()


def test_retention_prunes_inactive_but_keeps_admin(temp_store, temp_usage, monkeypatch):
    now = datetime(2026, 10, 26, 12, 0, 0)
    temp_store.create_user(_user("old", "13800138001", "2026-01-01T00:00:00"))
    temp_store.create_user(_user("new", "13800138002", "2026-10-20T00:00:00"))
    temp_store.create_user(_user("admin", "13800138003", "2026-01-01T00:00:00"))
    old_token = temp_store.issue_token("old")
    new_token = temp_store.issue_token("new")
    admin_token = temp_store.issue_token("admin")

    temp_usage.record(uid="old", cmd="", prompt_len=0, reply_len=1,
                      role="main", research=False, ts=_ts("2026-01-01T00:00:00"))
    temp_usage.record(uid="new", cmd="", prompt_len=0, reply_len=2,
                      role="main", research=False, ts=_ts("2026-10-20T00:00:00"))
    temp_usage.record(uid="admin", cmd="", prompt_len=0, reply_len=3,
                      role="main", research=False, ts=_ts("2026-01-01T00:00:00"))

    monkeypatch.setenv("MG_ACCOUNT_TTL_DAYS", "30")
    monkeypatch.setenv("MG_USAGE_TTL_DAYS", "90")
    monkeypatch.setenv("MG_ADMIN_PHONES", "13800138003")
    result = retention.run(now=now)

    assert result["accounts"] == 1
    assert set(temp_store.users_snapshot()) == {"new", "admin"}
    assert temp_store.resolve_token(old_token) is None
    assert temp_store.resolve_token(new_token)["uid"] == "new"
    assert temp_store.resolve_token(admin_token)["uid"] == "admin"
    # old 账号记录 + admin 的过期用量被删;new 的保留
    assert result["usage"] == 2
    assert temp_usage.summary()["calls"] == 1
    assert temp_usage.summary()["users"][0]["uid"] == "new"


def test_retention_defaults_off(temp_store, temp_usage, monkeypatch):
    now = datetime(2026, 10, 26, 12, 0, 0)
    temp_store.create_user(_user("old", "13800138001", "2020-01-01T00:00:00"))
    temp_usage.record(uid="old", cmd="", prompt_len=0, reply_len=1,
                      role="main", research=False, ts=_ts("2020-01-01T00:00:00"))
    monkeypatch.delenv("MG_ACCOUNT_TTL_DAYS", raising=False)
    monkeypatch.delenv("MG_USAGE_TTL_DAYS", raising=False)

    assert retention.run(now=now) == {"accounts": 0, "usage": 0}
    assert "old" in temp_store.users_snapshot()
    assert temp_usage.summary()["calls"] == 1


def test_usage_prune_also_cleans_legacy_backup(tmp_path, monkeypatch):
    monkeypatch.setattr(usage, "DATA_DIR", tmp_path)
    monkeypatch.setattr(usage, "PATH", tmp_path / "usage.jsonl")
    monkeypatch.setattr(usage, "LEGACY_PATH", tmp_path / "usage.json")
    usage.reset_for_tests()
    now = _ts("2026-10-26T00:00:00")
    old = {"ts": _ts("2025-01-01T00:00:00"), "uid": "old"}
    new = {"ts": _ts("2026-10-01T00:00:00"), "uid": "new"}
    (tmp_path / "usage.jsonl").write_text(
        "\n".join(json.dumps(x) for x in (old, new)) + "\n", encoding="utf-8")
    (tmp_path / "usage.json").write_text(json.dumps([old, new]), encoding="utf-8")

    assert usage.prune_older_than(30, now=now) == 2
    assert [x["uid"] for x in usage.summary()["users"]] == ["new"]
    backup = json.loads((tmp_path / "usage.json").read_text(encoding="utf-8"))
    assert [x["uid"] for x in backup] == ["new"]
