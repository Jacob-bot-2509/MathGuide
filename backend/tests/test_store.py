"""store.py:密码哈希、token 生命周期、原子写盘与旧格式迁移。"""
from __future__ import annotations

import hashlib
import json

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


def test_corrupt_hash_spec_falls_back_without_crashing():
    spec, digest = store.hash_password("secret123", "pbkdf2_sha256$not-a-number$salt")
    # 损坏的存储不抛异常:生成新格式,后续比较自然失败
    assert spec.startswith("pbkdf2_sha256$")
    assert digest


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


def test_init_migrates_legacy_string_token(temp_store):
    temp_store.USERS_PATH.write_text(
        json.dumps({"u-1": _user("u-1")}, ensure_ascii=False), encoding="utf-8")
    temp_store.TOKENS_PATH.write_text(json.dumps({"tok": "u-1"}), encoding="utf-8")

    temp_store.init()

    entry = temp_store._tokens["tok"]
    assert isinstance(entry, dict)
    assert entry["uid"] == "u-1"
    assert isinstance(entry["issued"], float)
    assert temp_store.resolve_token("tok")["uid"] == "u-1"
    # 迁移结果已写回磁盘
    assert isinstance(json.loads(temp_store.TOKENS_PATH.read_text(encoding="utf-8"))["tok"], dict)


def test_corrupt_json_is_treated_as_empty(temp_store):
    temp_store.USERS_PATH.write_text("{not json", encoding="utf-8")
    temp_store.init()
    assert temp_store._users == {}
    temp_store.create_user(_user("u-1", "13800138000"))
    assert temp_store.find_user_by_phone("13800138000")[0] == "u-1"


def test_non_object_json_is_treated_as_empty(temp_store):
    temp_store.USERS_PATH.write_text("[]", encoding="utf-8")
    temp_store.init()
    assert temp_store._users == {}


def test_non_dict_user_records_are_dropped(temp_store):
    temp_store.USERS_PATH.write_text(json.dumps({
        "good": _user("good", "13800138000"),
        "bad": "not-a-user",
    }, ensure_ascii=False), encoding="utf-8")
    temp_store.init()
    assert set(temp_store._users) == {"good"}
    assert temp_store.find_user_by_phone("13800138000")[0] == "good"


def test_token_without_issued_is_invalid(temp_store):
    temp_store.USERS_PATH.write_text(
        json.dumps({"u-1": _user("u-1")}, ensure_ascii=False), encoding="utf-8")
    temp_store.TOKENS_PATH.write_text(
        json.dumps({"tok": {"uid": "u-1"}}), encoding="utf-8")
    temp_store.init()
    assert temp_store.resolve_token("tok") is None

    # 下一次签发会顺带清掉损坏记录
    temp_store.issue_token("u-1")
    assert "tok" not in temp_store._tokens


def test_save_is_atomic_and_leaves_no_tmp_file(temp_store):
    temp_store.create_user(_user("u-1"))
    assert temp_store.USERS_PATH.is_file()
    tmp = temp_store.USERS_PATH.with_suffix(temp_store.USERS_PATH.suffix + ".tmp")
    assert not tmp.exists()
    data = json.loads(temp_store.USERS_PATH.read_text(encoding="utf-8"))
    assert data["u-1"]["uid"] == "u-1"


def test_update_password_hash(temp_store):
    temp_store.create_user(_user("u-1"))
    spec, digest = store.hash_password("newpass")
    assert temp_store.update_password_hash("u-1", (spec, digest)) is True
    assert temp_store._users["u-1"]["password_hash"] == (spec, digest)
    # 落盘后是 JSON 数组,重新加载仍可验证
    reloaded = json.loads(temp_store.USERS_PATH.read_text(encoding="utf-8"))
    assert reloaded["u-1"]["password_hash"] == [spec, digest]
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
    assert set(temp_store._users) == {"guest-b", "guest-c"}


def test_prune_guests_keeps_active_guests(temp_store):
    temp_store.create_user(_guest("guest-a", "2026-01-01"))
    token = temp_store.issue_token("guest-a")
    temp_store.create_user(_guest("guest-b", "2026-01-02"))
    temp_store.create_user(_guest("guest-c", "2026-01-03"))

    assert temp_store.prune_guests(2) == 1
    assert "guest-a" in temp_store._users
    assert temp_store.resolve_token(token)["uid"] == "guest-a"
