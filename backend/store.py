"""用户与令牌持久层(SQLite)。

接口形状保持不变(users: uid → 记录;tokens: 哈希键 → uid/签发时间):
调用方只依赖本模块函数,不感知存储实现。

- 事务:账号删除、令牌吊销、游客清理在单事务内完成,不会只删一半;
- 索引:手机号、token uid 均有索引;
- 并发:WAL + busy_timeout,多线程/多进程可安全访问;
- 迁移:首次建库时导入旧 users.json / tokens.json,旧文件保留作备份。
"""
from __future__ import annotations

import hashlib
import json
import secrets
import time
from datetime import datetime
from pathlib import Path

import db

DATA_DIR = Path(__file__).resolve().parent / "data"
DB_PATH = DATA_DIR / "mathguide.db"
USERS_PATH = DATA_DIR / "users.json"
TOKENS_PATH = DATA_DIR / "tokens.json"

TOKEN_TTL_HOURS = 24
TOKEN_KEY_PREFIX = "sha256:"
GUEST_UID_PREFIX = "guest-"

PBKDF2_ROUNDS = 200_000
PBKDF2_PREFIX = "pbkdf2_sha256"

MIGRATION_KEY = "migrated:store"
_ready_key: str | None = None


def _token_key(token: str) -> str:
    """token 落盘键:只存 SHA-256,库文件泄露拿不到可直接使用的 bearer token。"""
    return TOKEN_KEY_PREFIX + hashlib.sha256(token.encode("utf-8")).hexdigest()


def _doc(rec: dict) -> str:
    return json.dumps(rec, ensure_ascii=False)


def _rec_from_row(row) -> dict:
    """把存储的 doc 还原为调用方期望的形状(元组而非列表)。"""
    try:
        rec = json.loads(row["doc"])
    except (TypeError, json.JSONDecodeError):
        rec = {}
    if not isinstance(rec, dict):
        rec = {}
    digest = rec.get("password_hash")
    if isinstance(digest, list) and len(digest) == 2:
        rec["password_hash"] = (digest[0], digest[1])
    return rec


def _user_columns(rec: dict) -> tuple:
    return (
        rec.get("phone") if isinstance(rec.get("phone"), str) and rec["phone"] else None,
        _doc(rec),
        rec.get("createdAt") if isinstance(rec.get("createdAt"), str) else None,
        rec.get("lastActiveAt") if isinstance(rec.get("lastActiveAt"), str) else None,
    )


def _import_legacy(conn) -> None:
    """首次建库时导入旧 JSON;损坏记录阻止迁移。"""
    users = db.read_json(USERS_PATH)
    if not isinstance(users, dict) and USERS_PATH.exists():
        raise ValueError(f"{USERS_PATH}: 用户文件必须是对象")
    if isinstance(users, dict):
        for uid, rec in users.items():
            if not isinstance(rec, dict) or not uid:
                raise ValueError(f"{USERS_PATH}: 无效用户记录")
            rec = dict(rec)
            rec.setdefault("uid", uid)
            phone, doc, created, active = _user_columns(rec)
            conn.execute(
                "INSERT INTO users(uid, phone, doc, created_at, last_active_at) "
                "VALUES(?, ?, ?, ?, ?)",
                (uid, phone, doc, created, active),
            )

    tokens = db.read_json(TOKENS_PATH)
    if not isinstance(tokens, dict) and TOKENS_PATH.exists():
        raise ValueError(f"{TOKENS_PATH}: 令牌文件必须是对象")
    if isinstance(tokens, dict):
        for token, entry in tokens.items():
            if isinstance(entry, str):
                entry = {"uid": entry, "issued": time.time()}
            if not isinstance(entry, dict):
                raise ValueError(f"{TOKENS_PATH}: 无效令牌记录")
            uid = entry.get("uid")
            issued = entry.get("issued")
            if not isinstance(uid, str) or not uid or not isinstance(issued, (int, float)):
                raise ValueError(f"{TOKENS_PATH}: 无效令牌记录")
            key = token if token.startswith(TOKEN_KEY_PREFIX) else _token_key(token)
            conn.execute(
                "INSERT INTO tokens(key, uid, issued) VALUES(?, ?, ?)",
                (key, uid, float(issued)),
            )


def init() -> None:
    """建库并做一次性旧数据迁移;可重复调用。"""
    global _ready_key
    db.init()
    key = str(db.DB_PATH)
    if _ready_key == key and db.get_meta(MIGRATION_KEY) == "1":
        return
    with db.transaction() as conn:
        conn.execute("BEGIN IMMEDIATE")
        if not conn.execute("SELECT 1 FROM meta WHERE key = ? AND value = '1'", (MIGRATION_KEY,)).fetchone():
            _import_legacy(conn)
            conn.execute("INSERT OR REPLACE INTO meta(key, value) VALUES(?, '1')", (MIGRATION_KEY,))
    _ready_key = key


def _conn():
    init()
    return db.connect()


# ---------- 密码 ----------

def _is_new_hash_spec(salt: str) -> bool:
    return salt.startswith(PBKDF2_PREFIX + "$")


def is_legacy_hash(salt: object) -> bool:
    """旧格式(单轮 sha256)的 salt 没有算法前缀;登录成功后可升级。"""
    return isinstance(salt, str) and not _is_new_hash_spec(salt)


def hash_password(password: str, salt: str | None = None) -> tuple[str, str]:
    """返回 (salt_spec, digest);兼容旧格式验证与损坏存储。"""
    if salt is None:
        real_salt = secrets.token_hex(16)
        spec = f"{PBKDF2_PREFIX}${PBKDF2_ROUNDS}${real_salt}"
        digest = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), real_salt.encode("utf-8"), PBKDF2_ROUNDS)
        return spec, digest.hex()

    if _is_new_hash_spec(salt):
        try:
            _, rounds_text, real_salt = salt.split("$", 2)
            rounds = int(rounds_text)
        except (ValueError, TypeError):
            return hash_password(password)
        if rounds < 1:
            return hash_password(password)
        digest = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), real_salt.encode("utf-8"), rounds)
        return salt, digest.hex()

    return salt, hashlib.sha256((salt + password).encode("utf-8")).hexdigest()


# ---------- 用户 ----------

def find_user_by_phone(phone: str) -> tuple[str, dict] | None:
    conn = _conn()
    try:
        row = conn.execute(
            "SELECT uid, doc FROM users WHERE phone = ? LIMIT 1", (phone,)).fetchone()
    finally:
        conn.close()
    return (row["uid"], _rec_from_row(row)) if row else None


def create_user(rec: dict) -> str:
    """写入用户;调用方保证 uid 唯一(重复 uid 会抛 IntegrityError)。"""
    uid = rec["uid"]
    phone, doc, created, active = _user_columns(rec)
    conn = _conn()
    try:
        with conn:
            conn.execute(
                "INSERT INTO users(uid, phone, doc, created_at, last_active_at) "
                "VALUES(?, ?, ?, ?, ?)",
                (uid, phone, doc, created, active),
            )
    finally:
        conn.close()
    return uid


def touch_user(uid: str) -> bool:
    """记录最近登录时间(用于留存清理);只改用户表,不碰 token。"""
    conn = _conn()
    try:
        row = conn.execute("SELECT doc FROM users WHERE uid = ?", (uid,)).fetchone()
        if row is None:
            return False
        rec = _rec_from_row(row)
        stamp = datetime.now().isoformat(timespec="seconds")
        rec["lastActiveAt"] = stamp
        with conn:
            conn.execute(
                "UPDATE users SET doc = ?, last_active_at = ? WHERE uid = ?",
                (_doc(rec), stamp, uid),
            )
        return True
    finally:
        conn.close()


def users_snapshot() -> dict[str, dict]:
    """用户表只读快照;留存清理需要遍历,但不暴露内部可变表。"""
    conn = _conn()
    try:
        rows = conn.execute("SELECT uid, doc FROM users").fetchall()
    finally:
        conn.close()
    return {row["uid"]: _rec_from_row(row) for row in rows}


def update_password_hash(uid: str, password_hash: tuple[str, str]) -> bool:
    """替换用户密码哈希(旧格式登录成功后升级用)。"""
    conn = _conn()
    try:
        row = conn.execute("SELECT doc FROM users WHERE uid = ?", (uid,)).fetchone()
        if row is None:
            return False
        rec = _rec_from_row(row)
        rec["password_hash"] = password_hash
        with conn:
            conn.execute("UPDATE users SET doc = ? WHERE uid = ?", (_doc(rec), uid))
        return True
    finally:
        conn.close()


def phone_uid_map() -> dict[str, str]:
    """手机号 → uid 的只读副本;供 usage 身份迁移使用。"""
    conn = _conn()
    try:
        rows = conn.execute(
            "SELECT phone, uid FROM users WHERE phone IS NOT NULL AND phone <> ''"
        ).fetchall()
    finally:
        conn.close()
    return {row["phone"]: row["uid"] for row in rows}


def prune_inactive(days: float, exempt_uids: set[str] | None = None,
                   now: datetime | None = None, before_delete=None) -> list[dict]:
    """删除超过 days 天未活动的账号及其 token;返回被删记录列表。"""
    if days <= 0:
        return []
    exempt = exempt_uids or set()
    current = now or datetime.now()
    cutoff = current.timestamp() - days * 86400
    removed: list[dict] = []
    users = users_snapshot()
    for uid, rec in users.items():
        if uid in exempt:
            continue
        stamp = rec.get("lastActiveAt") or rec.get("createdAt")
        if not isinstance(stamp, str) or not stamp:
            continue
        try:
            active = datetime.fromisoformat(stamp)
        except ValueError:
            continue
        if active.timestamp() >= cutoff:
            continue
        removed.append(rec)
    if not removed:
        return []
    if before_delete:
        for rec in removed:
            before_delete(rec)
    removed_uids = {str(rec.get("uid") or "") for rec in removed}
    with db.transaction() as conn:
        conn.execute("BEGIN IMMEDIATE")
        for uid in removed_uids:
            _delete_legacy_user(uid)
            conn.execute("DELETE FROM tokens WHERE uid = ?", (uid,))
            conn.execute("DELETE FROM users WHERE uid = ?", (uid,))
    return removed


def _delete_legacy_user(uid: str) -> None:
    users = db.read_json(USERS_PATH)
    tokens = db.read_json(TOKENS_PATH)
    if not isinstance(users, dict) and USERS_PATH.exists():
        raise ValueError(f"{USERS_PATH}: 用户文件必须是对象")
    if not isinstance(tokens, dict) and TOKENS_PATH.exists():
        raise ValueError(f"{TOKENS_PATH}: 令牌文件必须是对象")
    if tokens is not None:
        if any(not isinstance(entry, (str, dict)) or isinstance(entry, dict) and not isinstance(entry.get("uid"), str)
               for entry in tokens.values()):
            raise ValueError(f"{TOKENS_PATH}: 无效令牌记录")
        kept = {key: entry for key, entry in tokens.items()
                if (entry if isinstance(entry, str) else entry["uid"]) != uid}
        if len(kept) != len(tokens):
            db.write_legacy(TOKENS_PATH, json.dumps(kept, ensure_ascii=False))
    if users is not None and uid in users:
        del users[uid]
        db.write_legacy(USERS_PATH, json.dumps(users, ensure_ascii=False))


def delete_user(uid: str) -> dict | None:
    """删除账号、令牌及迁移保留的旧记录。"""
    conn = _conn()
    try:
        with conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT doc FROM users WHERE uid = ?", (uid,)).fetchone()
            if row is None:
                return None
            rec = _rec_from_row(row)
            _delete_legacy_user(uid)
            conn.execute("DELETE FROM tokens WHERE uid = ?", (uid,))
            conn.execute("DELETE FROM users WHERE uid = ?", (uid,))
        return rec
    finally:
        conn.close()


# ---------- 游客账号 ----------

def guest_count() -> int:
    conn = _conn()
    try:
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM users WHERE uid LIKE ?",
            (GUEST_UID_PREFIX + "%",)).fetchone()
        return int(row["n"])
    finally:
        conn.close()


def _token_uid(entry: object) -> str:
    """兼容旧调用:token 条目可能是 dict 或纯 uid 字符串。"""
    if isinstance(entry, dict):
        return str(entry.get("uid") or "")
    return str(entry or "")


def prune_guests(max_guests: int, before_delete=None) -> int:
    """把游客账号压到 max_guests 以内;只删「没有有效 token」的最旧记录。"""
    if max_guests < 0:
        max_guests = 0
    conn = _conn()
    try:
        users = users_snapshot()
        guests = {
            uid: rec for uid, rec in users.items()
            if uid.startswith(GUEST_UID_PREFIX) and isinstance(rec, dict)
        }
        excess = len(guests) - max_guests
        if excess <= 0:
            return 0

        now = time.time()
        rows = conn.execute("SELECT uid, issued FROM tokens").fetchall()
        active = {
            row["uid"] for row in rows
            if isinstance(row["issued"], (int, float))
            and now - row["issued"] <= TOKEN_TTL_HOURS * 3600
        }
        removable = [uid for uid in guests if uid not in active]
        removable.sort(key=lambda uid: str(users[uid].get("createdAt") or ""))
        removed = removable[:excess]
        if not removed:
            return 0

        if before_delete:
            for uid in removed:
                before_delete(users[uid])
        with conn:
            conn.execute("BEGIN IMMEDIATE")
            for uid in removed:
                _delete_legacy_user(uid)
                conn.execute("DELETE FROM tokens WHERE uid = ?", (uid,))
                conn.execute("DELETE FROM users WHERE uid = ?", (uid,))
        return len(removed)
    finally:
        conn.close()


# ---------- token ----------

def _sweep_tokens(conn) -> None:
    now = time.time()
    conn.execute("DELETE FROM tokens WHERE issued <= ?",
                 (now - TOKEN_TTL_HOURS * 3600,))


def issue_token(uid: str) -> str:
    conn = _conn()
    try:
        with conn:
            _sweep_tokens(conn)
            token = secrets.token_hex(24)
            conn.execute(
                "INSERT INTO tokens(key, uid, issued) VALUES(?, ?, ?)",
                (_token_key(token), uid, time.time()),
            )
        return token
    finally:
        conn.close()


def resolve_token(token: str) -> dict | None:
    """token → 用户记录;库中只存 SHA-256 键,不存明文 token。"""
    conn = _conn()
    try:
        row = conn.execute(
            "SELECT uid, issued FROM tokens WHERE key = ?",
            (_token_key(token),)).fetchone()
        if row is None:
            return None
        issued = row["issued"]
        if not isinstance(issued, (int, float)):
            return None
        if time.time() - issued > TOKEN_TTL_HOURS * 3600:
            return None
        uid = row["uid"]
        if not uid:
            return None
        user = conn.execute("SELECT doc FROM users WHERE uid = ?", (uid,)).fetchone()
        return _rec_from_row(user) if user else None
    finally:
        conn.close()


def revoke_token(token: str) -> bool:
    """吊销 token;返回是否真的删除了一条记录(未命中不写库)。"""
    conn = _conn()
    try:
        with conn:
            cur = conn.execute("DELETE FROM tokens WHERE key = ?", (_token_key(token),))
            return cur.rowcount > 0
    finally:
        conn.close()


def tokens_snapshot() -> dict[str, dict]:
    """令牌表只读快照(测试与运维排查用);键为 SHA-256 摘要。"""
    conn = _conn()
    try:
        rows = conn.execute("SELECT key, uid, issued FROM tokens").fetchall()
    finally:
        conn.close()
    return {row["key"]: {"uid": row["uid"], "issued": row["issued"]} for row in rows}


def reset_for_tests() -> None:
    """测试切换临时库时调用:清掉就绪标记并按 db.DB_PATH 重建。"""
    global _ready_key
    _ready_key = None
    db.reset_for_tests()
