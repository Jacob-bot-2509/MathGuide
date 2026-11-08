"""用量统计(SQLite):每次调用记一条,只存 uid,不存手机号/昵称。

- record():写入后把表裁到最近 _MAX_CALLS 条,避免无限增长；
- for_user()/delete_user():账号导出/注销时读取或删除该账号记录；
- summary():按账号与模型角色汇总,供 /api/stats 与 tools/usage.py 共用；
- migrate_identity():旧记录里的 phone/user 换成 uid 并删除 PII；
- 旧 usage.jsonl / usage.json 在首次建库时导入一次,文件保留作备份；
- 客户端中途断开不记账(调用方在流结束后才调用 record)。
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import db

DATA_DIR = Path(__file__).resolve().parent / "data"
PATH = DATA_DIR / "usage.jsonl"
LEGACY_PATH = DATA_DIR / "usage.json"
_MAX_CALLS = 2000

MIGRATION_KEY = "migrated:usage"
_ready_key: str | None = None

_FIELDS = ("ts", "cmd", "prompt_len", "reply_len", "role", "research", "workspace")


def _doc(entry: dict) -> str:
    return json.dumps(entry, ensure_ascii=False)


def _entry(row) -> dict:
    try:
        data = json.loads(row["doc"])
    except (TypeError, json.JSONDecodeError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    data.setdefault("ts", row["ts"])
    data.setdefault("uid", row["uid"])
    return data


def _doc_entry(row) -> dict:
    """只读 doc 列的行(无 ts/uid 列)使用。"""
    try:
        data = json.loads(row["doc"])
    except (TypeError, json.JSONDecodeError):
        data = {}
    return data if isinstance(data, dict) else {}


def init() -> None:
    """建库并一次性导入旧 JSONL/JSON;可重复调用。"""
    global _ready_key
    db.init()
    key = f"{db.DB_PATH}"
    if _ready_key == key and db.get_meta(MIGRATION_KEY) == "1":
        return
    if db.get_meta(MIGRATION_KEY) != "1":
        _import_legacy()
        db.set_meta(MIGRATION_KEY, "1")
    _ready_key = key


def _read_legacy_entries() -> list[dict]:
    entries: list[dict] = []
    if PATH.exists():
        try:
            with PATH.open(encoding="utf-8") as fh:
                for raw in fh:
                    text = raw.strip()
                    if not text:
                        continue
                    try:
                        item = json.loads(text)
                    except json.JSONDecodeError:
                        continue
                    if isinstance(item, dict):
                        entries.append(item)
        except OSError:
            raise
        return entries
    raw = db.read_json(LEGACY_PATH)
    if isinstance(raw, list):
        return [item for item in raw if isinstance(item, dict)]
    return []


def _import_legacy() -> None:
    if not db.table_empty("usage"):
        return
    entries = _read_legacy_entries()
    if not entries:
        return
    with db.transaction() as conn:
        for item in entries:
            uid = str(item.get("uid") or "")
            ts = item.get("ts") if isinstance(item.get("ts"), (int, float)) else 0.0
            # 旧记录可能只有 phone/user:先原样保留,由 migrate_identity 清洗
            conn.execute(
                "INSERT INTO usage(uid, ts, doc) VALUES(?, ?, ?)",
                (uid, float(ts), _doc(item)),
            )


def _conn():
    init()
    return db.connect()


def _trim(conn) -> None:
    """只保留最近 _MAX_CALLS 条;按 id 倒序取阈值,再删更早的行。"""
    row = conn.execute(
        "SELECT id FROM usage ORDER BY id DESC LIMIT 1 OFFSET ?",
        (max(0, _MAX_CALLS - 1),),
    ).fetchone()
    if row is not None:
        conn.execute("DELETE FROM usage WHERE id < ?", (row["id"],))


def record(*, uid: str, cmd: str, prompt_len: int, reply_len: int,
           role: str, research: bool, ts: float, workspace: str = "learn") -> None:
    """写入一条调用记录;只存 uid,不存手机号/昵称。"""
    entry = {
        "ts": round(ts, 1),
        "uid": uid or "anonymous",
        "cmd": cmd or "",
        "prompt_len": prompt_len,
        "reply_len": reply_len,
        "role": role,
        "research": research,
        "workspace": workspace if workspace in ("learn", "research") else "learn",
    }
    conn = _conn()
    try:
        with conn:
            conn.execute(
                "INSERT INTO usage(uid, ts, doc) VALUES(?, ?, ?)",
                (entry["uid"], float(entry["ts"]), _doc(entry)),
            )
            _trim(conn)
    finally:
        conn.close()


def _all_entries(conn) -> list[dict]:
    rows = conn.execute("SELECT id, uid, ts, doc FROM usage ORDER BY id").fetchall()
    return [_entry(row) for row in rows]


def _sanitize_entry(entry: dict, phone_to_uid: dict[str, str]) -> bool:
    """把一条旧记录换成 uid 并删除 phone/user;返回是否有改动。"""
    if "uid" in entry and "phone" not in entry and "user" not in entry:
        return False
    phone = entry.pop("phone", "")
    entry.pop("user", None)
    if not entry.get("uid"):
        entry["uid"] = phone_to_uid.get(str(phone or ""), "") or "anonymous"
    return True


def _sanitize_legacy_file(phone_to_uid: dict[str, str]) -> int:
    """旧 usage.json 备份也含 phone/user:原地清洗,避免迁移后仍留 PII。"""
    raw = db.read_json(LEGACY_PATH)
    if not isinstance(raw, list):
        return 0
    cleaned: list[dict] = []
    changed = 0
    for item in raw:
        if not isinstance(item, dict):
            changed += 1
            continue
        entry = dict(item)
        if _sanitize_entry(entry, phone_to_uid):
            changed += 1
        cleaned.append(entry)
    if not changed:
        return 0
    tmp = LEGACY_PATH.with_suffix(LEGACY_PATH.suffix + ".tmp")
    tmp.write_text(json.dumps(cleaned, ensure_ascii=False), encoding="utf-8")
    tmp.replace(LEGACY_PATH)
    return changed


def migrate_identity(phone_to_uid: dict[str, str]) -> int:
    """把旧记录的 phone/user 迁移成 uid 并删除 PII;返回改动条数。"""
    conn = _conn()
    changed = 0
    try:
        rows = conn.execute("SELECT id, uid, ts, doc FROM usage").fetchall()
        with conn:
            for row in rows:
                entry = _doc_entry(row)
                if _sanitize_entry(entry, phone_to_uid):
                    conn.execute(
                        "UPDATE usage SET uid = ?, doc = ? WHERE id = ?",
                        (str(entry.get("uid") or "anonymous"), _doc(entry), row["id"]),
                    )
                    changed += 1
    finally:
        conn.close()
    return changed + _sanitize_legacy_file(phone_to_uid)


def _prune_legacy_file(cutoff: float) -> int:
    raw = db.read_json(LEGACY_PATH)
    if not isinstance(raw, list):
        return 0
    kept: list[object] = []
    removed = 0
    for item in raw:
        stamp = item.get("ts") if isinstance(item, dict) else None
        if isinstance(stamp, (int, float)) and stamp < cutoff:
            removed += 1
            continue
        kept.append(item)
    if not removed:
        return 0
    tmp = LEGACY_PATH.with_suffix(LEGACY_PATH.suffix + ".tmp")
    tmp.write_text(json.dumps(kept, ensure_ascii=False), encoding="utf-8")
    tmp.replace(LEGACY_PATH)
    return removed


def prune_older_than(days: float, now: float | None = None) -> int:
    """按时间清理用量记录(含旧备份);返回删除条数。days <= 0 表示关闭。"""
    if days <= 0:
        return 0
    cutoff = (time.time() if now is None else now) - days * 86400
    conn = _conn()
    try:
        with conn:
            cur = conn.execute("DELETE FROM usage WHERE ts < ?", (cutoff,))
            removed = cur.rowcount
    finally:
        conn.close()
    return removed + _prune_legacy_file(cutoff)


def for_user(uid: str, phone: str = "") -> list[dict]:
    """导出某账号的用量元数据;不返回旧记录里的 phone/user 字段。"""
    conn = _conn()
    try:
        entries = _all_entries(conn)
    finally:
        conn.close()
    out: list[dict] = []
    for entry in entries:
        if entry.get("uid") == uid or (phone and entry.get("phone") == phone):
            out.append({key: entry.get(key) for key in _FIELDS})
    return out


def _delete_from_legacy_file(uid: str, phone: str) -> int:
    raw = db.read_json(LEGACY_PATH)
    if not isinstance(raw, list):
        return 0
    kept: list[object] = []
    removed = 0
    for item in raw:
        if isinstance(item, dict) and (
            item.get("uid") == uid or (phone and item.get("phone") == phone)
        ):
            removed += 1
            continue
        kept.append(item)
    if not removed:
        return 0
    tmp = LEGACY_PATH.with_suffix(LEGACY_PATH.suffix + ".tmp")
    tmp.write_text(json.dumps(kept, ensure_ascii=False), encoding="utf-8")
    tmp.replace(LEGACY_PATH)
    return removed


def delete_user(uid: str, phone: str = "") -> int:
    """删除某账号的用量记录(含旧 phone 记录与 usage.json 备份);返回删除条数。"""
    conn = _conn()
    try:
        victim_ids = [
            row["id"] for row in conn.execute("SELECT id, doc FROM usage").fetchall()
            if (
                _doc_entry(row).get("uid") == uid
                or (phone and _doc_entry(row).get("phone") == phone)
            )
        ]
        if victim_ids:
            with conn:
                conn.executemany("DELETE FROM usage WHERE id = ?",
                                 [(item,) for item in victim_ids])
    finally:
        conn.close()
    return len(victim_ids) + _delete_from_legacy_file(uid, phone)


def summary() -> dict:
    """汇总:总调用数 / 总字数 / 按账号 / 按模型角色。"""
    conn = _conn()
    try:
        calls = _all_entries(conn)
    finally:
        conn.close()
    users: dict[str, dict] = {}
    roles: dict[str, int] = {}
    total_chars = 0
    for c in calls:
        key = str(c.get("uid") or "anonymous")
        u = users.setdefault(key, {"uid": key, "calls": 0, "chars": 0})
        u["calls"] += 1
        u["chars"] += int(c.get("reply_len") or 0)
        role = c.get("role") or "main"
        roles[role] = roles.get(role, 0) + 1
        total_chars += int(c.get("reply_len") or 0)
    return {
        "calls": len(calls),
        "totalChars": total_chars,
        "users": sorted(users.values(), key=lambda u: -u["calls"]),
        "roles": roles,
    }


def reset_for_tests() -> None:
    """测试切换临时库时调用:清掉就绪标记并按 db.DB_PATH 重建。"""
    global _ready_key
    _ready_key = None
    db.reset_for_tests()
