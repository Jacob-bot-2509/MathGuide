"""
用量统计(演示/测试期成本可见):
- record():每次聊天请求应答后写一条,追加到 data/usage.jsonl(内存只保留最近 2000 条);
- summary():按用户与模型角色汇总,供 /api/stats 接口与 tools/usage.py 报表共用;
- 兼容旧格式 data/usage.json(JSON 数组):首次读取时加载,下一次写入时迁移为 JSONL,
  旧文件保留作备份,不主动删除;
- 客户端中途断开则本次不记账(记录在流结束后落盘)。

为什么用 JSONL:旧实现每记一条都要读出整个数组、追加、再全量重写,
记录越多写放大越严重;追加一行是 O(1)。文件行数允许比内存上限多
_COMPACT_SLACK 行,超过后整体压实一次,避免每写一条都重写。
"""
import json
import threading
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


def record(*, user: str, phone: str, cmd: str, prompt_len: int, reply_len: int,
           role: str, research: bool, ts: float) -> None:
    """追加一条调用记录(user 为昵称/uid 展示用,phone 为空表示访客)"""
    entry = {
        "ts": round(ts, 1),
        "user": user,
        "phone": phone or "",
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


def summary() -> dict:
    """汇总:总调用数 / 总字数 / 按用户 / 按模型角色"""
    with _lock:
        _ensure_loaded()
        calls = list(_calls or [])
    users: dict[str, dict] = {}
    roles: dict[str, int] = {}
    total_chars = 0
    for c in calls:
        key = c.get("phone") or c.get("user") or "访客"
        u = users.setdefault(key, {
            "user": c.get("user") or "访客",
            "phone": c.get("phone") or "",
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
