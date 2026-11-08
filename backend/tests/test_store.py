"""store.py:密码哈希、token 生命周期、SQLite 持久化与旧数据迁移。"""
from __future__ import annotations

import hashlib
import json
import pytest
from contextlib import closing
import sqlite3
import threading

import db
import store


def _user(uid: str = "u-1", phone: str | None = None, password_hash=None) -> dict:
    return {
        "uid": uid,
        "phone": phone,
        "password_hash": password_hash,
        "authMethod": "phone-pass",
        "nickname": "n",
        "avatar": "preset:sum",
        "createdAt": "2026-01-01T00:00:00",
    }


def _reopen() -> None:
    """模拟进程重启:清掉就绪标记后重新初始化。"""
    store._ready_key = None
    store.init()


def test_new_hash_uses_pbkdf2_and_verifies():
    spec, digest = store.hash_password("secret123")
    assert spec.startswith("pbkdf2_sha256$")
    assert store.is_legacy_hash(spec) is False
    assert store.hash_password("secret123", spec)[1] == digest
    assert store.hash_password("wrong", spec)[1] != digest


def test_legacy_hash_still_verifies():
    salt = "0123456789abcdef"
    digest = hashlib.sha256((salt + "secret123").encode("utf-8")).hexdigest()
    assert store.is_legacy_hash(salt) is True
    assert store.hash_password("secret123", salt) == (salt, digest)
    assert store.hash_password("wrong", salt)[1] != digest


def test_token_issue_expire_and_revoke(temp_store, monkeypatch):
    temp_store.init()
    now = [1_000_000.0]
    monkeypatch.setattr(store.time, "time", lambda: now[0])
    token = temp_store.issue_token("u-1")
    assert temp_store.resolve_token(token) is None  # 用户不存在
    temp_store.create_user(_user("u-1"))
    assert temp_store.resolve_token(token)["uid"] == "u-1"

    now[0] += store.TOKEN_TTL_HOURS * 3600 + 1
    assert temp_store.resolve_token(token) is None

    now[0] += 1
    token2 = temp_store.issue_token("u-1")
    assert temp_store.revoke_token(token2) is True
    assert temp_store.resolve_token(token2) is None
    assert temp_store.revoke_token("missing") is False


def test_init_imports_legacy_json_once(temp_store):
    temp_store.USERS_PATH.write_text(
        json.dumps({"u-1": _user("u-1", "13800138000")}, ensure_ascii=False),
        encoding="utf-8")
    temp_store.TOKENS_PATH.write_text(json.dumps({"tok": "u-1"}), encoding="utf-8")

    temp_store.init()

    key = temp_store._token_key("tok")
    assert "tok" not in temp_store.tokens_snapshot()
    assert key in temp_store.tokens_snapshot()
    assert temp_store.resolve_token("tok")["uid"] == "u-1"
    # 旧文件保留作备份,不被改写
    assert json.loads(temp_store.TOKENS_PATH.read_text(encoding="utf-8")) == {"tok": "u-1"}


def test_legacy_import_is_idempotent(temp_store):
    temp_store.USERS_PATH.write_text(
        json.dumps({"u-1": _user("u-1")}, ensure_ascii=False), encoding="utf-8")
    temp_store.init()
    temp_store.init()  # 再初始化不能重复插入或报错
    assert list(temp_store.users_snapshot()) == ["u-1"]


def test_corrupt_json_blocks_migration_until_repaired(temp_store):
    temp_store.USERS_PATH.write_text("{not json", encoding="utf-8")
    with pytest.raises(json.JSONDecodeError):
        temp_store.init()
    assert db.get_meta(temp_store.MIGRATION_KEY) is None
    temp_store.USERS_PATH.write_text(json.dumps({"u-1": _user("u-1", "13800138000")}), encoding="utf-8")
    temp_store.init()
    assert temp_store.find_user_by_phone("13800138000")[0] == "u-1"


def test_non_object_json_blocks_migration(temp_store):
    temp_store.USERS_PATH.write_text("[]", encoding="utf-8")
    with pytest.raises(ValueError):
        temp_store.init()
    assert db.get_meta(temp_store.MIGRATION_KEY) is None


def test_non_dict_user_records_roll_back_migration(temp_store):
    temp_store.USERS_PATH.write_text(json.dumps({
        "good": _user("good", "13800138000"),
        "bad": "not-a-user",
    }, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(ValueError):
        temp_store.init()
    assert db.get_meta(temp_store.MIGRATION_KEY) is None
    with closing(db.connect()) as conn:
        assert conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0


def test_token_without_issued_blocks_migration(temp_store):
    temp_store.USERS_PATH.write_text(
        json.dumps({"u-1": _user("u-1")}, ensure_ascii=False), encoding="utf-8")
    temp_store.TOKENS_PATH.write_text(
        json.dumps({"tok": {"uid": "u-1"}}), encoding="utf-8")
    with pytest.raises(ValueError):
        temp_store.init()
    assert db.get_meta(temp_store.MIGRATION_KEY) is None


def test_data_survives_reopen(temp_store):
    temp_store.create_user(_user("u-1", "13800138000"))
    token = temp_store.issue_token("u-1")
    _reopen()
    assert temp_store.find_user_by_phone("13800138000")[0] == "u-1"
    assert temp_store.resolve_token(token)["uid"] == "u-1"


def test_update_password_hash_persists(temp_store):
    temp_store.create_user(_user("u-1"))
    spec, digest = store.hash_password("newpass")
    assert temp_store.update_password_hash("u-1", (spec, digest)) is True
    _reopen()
    rec = temp_store.users_snapshot()["u-1"]
    assert rec["password_hash"] == (spec, digest)
    assert temp_store.update_password_hash("missing", (spec, digest)) is False


def _guest(uid: str, created: str) -> dict:
    rec = _user(uid)
    rec.update({"authMethod": "wechat", "phone": None, "createdAt": created})
    return rec


def test_prune_guests_removes_oldest_inactive(temp_store):
    for uid, created in (
        ("guest-a", "2026-01-01"),
        ("guest-b", "2026-01-02"),
        ("guest-c", "2026-01-03"),
    ):
        temp_store.create_user(_guest(uid, created))
    assert temp_store.guest_count() == 3

    assert temp_store.prune_guests(2) == 1
    assert set(temp_store.users_snapshot()) == {"guest-b", "guest-c"}


def test_prune_guests_keeps_active_guests(temp_store):
    temp_store.create_user(_guest("guest-a", "2026-01-01"))
    token = temp_store.issue_token("guest-a")
    temp_store.create_user(_guest("guest-b", "2026-01-02"))
    temp_store.create_user(_guest("guest-c", "2026-01-03"))

    assert temp_store.prune_guests(2) == 1
    assert "guest-a" in temp_store.users_snapshot()
    assert temp_store.resolve_token(token)["uid"] == "guest-a"


def test_delete_user_removes_phone_index_and_all_tokens(temp_store):
    temp_store.create_user(_user("u-1", "13800138000"))
    temp_store.create_user(_user("u-2", "13900139000"))
    token1 = temp_store.issue_token("u-1")
    token2 = temp_store.issue_token("u-1")
    other = temp_store.issue_token("u-2")

    rec = temp_store.delete_user("u-1")
    assert rec and rec["phone"] == "13800138000"
    assert temp_store.find_user_by_phone("13800138000") is None
    assert temp_store.find_user_by_phone("13900139000")[0] == "u-2"
    assert temp_store.resolve_token(token1) is None
    assert temp_store.resolve_token(token2) is None
    assert temp_store.resolve_token(other)["uid"] == "u-2"
    assert temp_store.delete_user("missing") is None


def test_phone_uid_map_is_a_copy(temp_store):
    temp_store.create_user(_user("u-1", "13800138000"))
    mapping = temp_store.phone_uid_map()
    mapping["13800138000"] = "tampered"
    assert temp_store.find_user_by_phone("13800138000")[0] == "u-1"


def test_token_is_hashed_at_rest(temp_store):
    temp_store.create_user(_user("u-1"))
    token = temp_store.issue_token("u-1")
    conn = db.connect()
    try:
        conn.execute("PRAGMA wal_checkpoint(FULL)")
    finally:
        conn.close()
    raw = db.DB_PATH.read_bytes()
    assert token.encode() not in raw, "SQLite 库里仍含明文 token"
    assert temp_store._token_key(token).encode() in raw
    assert temp_store.resolve_token(token)["uid"] == "u-1"


def test_schema_has_indexes(temp_store):
    temp_store.init()
    conn = db.connect()
    try:
        names = {
            row["name"] for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'index'")
        }
    finally:
        conn.close()
    assert "idx_users_phone" in names
    assert "idx_tokens_uid" in names


def test_delete_user_is_atomic_across_tables(temp_store):
    """注销在单事务内删用户与令牌;中途失败应整体回滚。"""
    temp_store.create_user(_user("u-1"))
    temp_store.issue_token("u-1")
    try:
        with db.transaction() as conn:
            conn.execute("DELETE FROM users WHERE uid = ?", ("u-1",))
            raise RuntimeError("boom")
    except RuntimeError:
        pass
    assert "u-1" in temp_store.users_snapshot(), "事务异常后用户被误删"


def test_concurrent_writes_do_not_lock(temp_store):
    errors: list[Exception] = []

    def worker(index: int) -> None:
        try:
            temp_store.create_user(_user(f"u-{index}"))
            temp_store.issue_token(f"u-{index}")
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(12)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert not errors, errors
    assert len(temp_store.users_snapshot()) == 12
