"""
用量统计(演示/测试期成本可见):
- record():每次聊天请求应答后写一条,追加到 data/usage.jsonl(内存只保留最近 2000 条);
  新记录只存 uid,不存手机号/昵称,避免把身份信息混进成本日志;
- migrate_identity():启动时把旧记录的 phone/user 字段迁移为 uid 并删除,旧数据不保留 PII;
- for_user()/delete_user():账号导出/注销时读取或删除该账号的记录;
- summary():按账号与模型角色汇总,供 /api/stats 接口与 tools/usage.py 报表共用;
- 兼容旧格式 data/usage.json(JSON 数组):首次读取时加载,下一次写入时迁移为 JSONL,
  旧文件保留作备份,不主动删除;
- 客户端中途断开则本次不记账(记录在流结束后落盘)。

为什么用 JSONL:旧实现每记一条都要读出整个数组、追加、再全量重写,
记录越多写放大越严重;追加一行是 O(1)。文件行数允许比内存上限多
_COMPACT_SLACK 行,超过后整体压实一次,避免每写一条都重写。
"""
import json
import threading
import time
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent / "data"
PATH = DATA_DIR / "usage.jsonl"
LEGACY_PATH = DATA_DIR / "usage.json"
_lock = threading.Lock()
_MAX_CALLS = 2000
_COMPACT_SLACK = 200

# 进程内缓存:启动/首次访问时从磁盘装载,之后读写都走内存 + 追加
_calls: list[dict] | None = None
_loaded_key: str | None = None
_file_lines = 0
_needs_compact = False


def _read_all() -> tuple[list[dict], int, bool]:
    """返回 (有效记录, 文件行数, 是否需要整体重写)。"""
    if PATH.exists():
        calls: list[dict] = []
        lines = 0
        dirty = False
        try:
            with PATH.open(encoding="utf-8") as fh:
                for raw in fh:
                    lines += 1
                    text = raw.strip()
                    if not text:
                        continue
                    try:
                        entry = json.loads(text)
                    except json.JSONDecodeError:
                        dirty = True
                        continue
                    if isinstance(entry, dict):
                        calls.append(entry)
                    else:
                        dirty = True
        except OSError:
            return [], 0, False
        return calls, lines, dirty

    if LEGACY_PATH.exists():
        try:
            data = json.loads(LEGACY_PATH.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return [], 0, False
        if isinstance(data, list):
            calls = [entry for entry in data if isinstance(entry, dict)]
            return calls, len(data), True
        return [], 0, True

    return [], 0, False


def _ensure_loaded() -> None:
    global _calls, _loaded_key, _file_lines, _needs_compact
    key = str(PATH)
    if _calls is not None and _loaded_key == key:
        return
    calls, lines, needs_compact = _read_all()
    if len(calls) > _MAX_CALLS:
        calls = calls[-_MAX_CALLS:]
        needs_compact = True
    _calls = calls
    _loaded_key = key
    _file_lines = lines
    _needs_compact = needs_compact


def _write_all_locked(entries: list[dict]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp = PATH.with_suffix(PATH.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        for entry in entries:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
    tmp.replace(PATH)


def _append_locked(entry: dict) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with PATH.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False) + "\n")


def record(*, uid: str, cmd: str, prompt_len: int, reply_len: int,
           role: str, research: bool, ts: float) -> None:
    """追加一条调用记录;只存 uid,不存手机号/昵称。"""
    entry = {
        "ts": round(ts, 1),
        "uid": uid or "anonymous",
        "cmd": cmd or "",
        "prompt_len": prompt_len,
        "reply_len": reply_len,
        "role": role,
        "research": research,
    }
    global _calls, _file_lines, _needs_compact
    with _lock:
        _ensure_loaded()
        if _calls is None:  # 理论上不会发生;保证后续 append 有落点
            _calls = []
        calls = _calls
        calls.append(entry)
        if len(calls) > _MAX_CALLS:
            del calls[:-_MAX_CALLS]

        if _needs_compact or _file_lines + 1 > _MAX_CALLS + _COMPACT_SLACK:
            _write_all_locked(_calls)
            _file_lines = len(_calls)
            _needs_compact = False
        else:
            _append_locked(entry)
            _file_lines += 1


def _sanitize_entry(entry: dict, phone_to_uid: dict[str, str]) -> bool:
    """把一条旧记录换成 uid 并删除 phone/user;返回是否有改动。"""
    if "uid" in entry and "phone" not in entry and "user" not in entry:
        return False
    phone = entry.pop("phone", "")
    entry.pop("user", None)
    if not entry.get("uid"):
        entry["uid"] = phone_to_uid.get(str(phone or ""), "") or "anonymous"
    return True


def _sanitize_legacy_locked(phone_to_uid: dict[str, str]) -> int:
    """旧 usage.json 备份也含 phone/user:原地清洗,避免迁移后仍留一份 PII。"""
    if not LEGACY_PATH.exists():
        return 0
    try:
        raw = json.loads(LEGACY_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return 0
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
    """把旧记录的 phone/user 迁移成 uid 并删除 PII 字段。

    旧记录没有 uid,只有 phone(手机号)或 user(昵称)。启动时用当前
    phone → uid 索引回填;找不到对应账号的记录归为 anonymous。返回改动条数。
    旧 usage.json 备份也一并清洗,不能只洗 JSONL 而把 PII 留在备份里。
    """
    global _calls, _file_lines, _needs_compact
    with _lock:
        _ensure_loaded()
        calls = _calls or []
        changed = 0
        for entry in calls:
            if _sanitize_entry(entry, phone_to_uid):
                changed += 1
        if changed:
            _write_all_locked(calls)
            _file_lines = len(calls)
            _needs_compact = False
        changed += _sanitize_legacy_locked(phone_to_uid)
        return changed


def _prune_legacy_locked(cutoff: float) -> int:
    """按 ts 清理旧 usage.json 备份;返回删除条数。"""
    if not LEGACY_PATH.exists():
        return 0
    try:
        raw = json.loads(LEGACY_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return 0
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
    global _calls, _file_lines, _needs_compact
    with _lock:
        _ensure_loaded()
        calls = _calls or []
        kept = [
            entry for entry in calls
            if not (
                isinstance(entry.get("ts"), (int, float))
                and entry["ts"] < cutoff
            )
        ]
        removed = len(calls) - len(kept)
        if removed:
            _calls = kept
            _write_all_locked(kept)
            _file_lines = len(kept)
            _needs_compact = False
        return removed + _prune_legacy_locked(cutoff)


def for_user(uid: str, phone: str = "") -> list[dict]:
    """导出某账号的用量元数据;不返回旧记录里的 phone/user 字段。"""
    with _lock:
        _ensure_loaded()
        calls = list(_calls or [])
    fields = ("ts", "cmd", "prompt_len", "reply_len", "role", "research")
    out: list[dict] = []
    for entry in calls:
        if entry.get("uid") == uid or (phone and entry.get("phone") == phone):
            out.append({key: entry.get(key) for key in fields})
    return out


def _delete_from_legacy_locked(uid: str, phone: str) -> int:
    """从旧 usage.json 备份中删除账号记录;返回删除条数。"""
    if not LEGACY_PATH.exists():
        return 0
    try:
        raw = json.loads(LEGACY_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return 0
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
    global _calls, _file_lines, _needs_compact
    with _lock:
        _ensure_loaded()
        calls = _calls or []
        kept = [
            entry for entry in calls
            if not (entry.get("uid") == uid or (phone and entry.get("phone") == phone))
        ]
        removed = len(calls) - len(kept)
        if removed:
            _calls = kept
            _write_all_locked(kept)
            _file_lines = len(kept)
            _needs_compact = False
        return removed + _delete_from_legacy_locked(uid, phone)


def summary() -> dict:
    """汇总:总调用数 / 总字数 / 按账号 / 按模型角色"""
    with _lock:
        _ensure_loaded()
        calls = list(_calls or [])
    users: dict[str, dict] = {}
    roles: dict[str, int] = {}
    total_chars = 0
    for c in calls:
        key = str(c.get("uid") or "anonymous")
        u = users.setdefault(key, {
            "uid": key,
            "calls": 0,
            "chars": 0,
        })
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
    """清空进程内缓存(测试切换临时路径时使用)。"""
    global _calls, _loaded_key, _file_lines, _needs_compact
    with _lock:
        _calls = None
        _loaded_key = None
        _file_lines = 0
        _needs_compact = False
