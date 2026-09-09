"""
用量统计(演示/测试期成本可见):
- record():每次聊天请求应答后记一行,落盘 data/usage.json(上限 2000 条,超量丢最旧);
- summary():按用户与模型角色汇总,供 /api/stats 接口与 tools/usage.py 报表共用。
客户端中途断开则本次不记账(记录在流结束后落盘)。
"""
import json
import threading
import time
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent / "data"
PATH = DATA_DIR / "usage.json"
_lock = threading.Lock()
_MAX_CALLS = 2000


def _load() -> list[dict]:
    try:
        if PATH.exists():
            data = json.loads(PATH.read_text(encoding="utf-8"))
            if isinstance(data, list):
                return data
    except (OSError, json.JSONDecodeError):
        pass
    return []


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
    with _lock:
        calls = _load()
        calls.append(entry)
        if len(calls) > _MAX_CALLS:
            calls = calls[-_MAX_CALLS:]
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        tmp = PATH.with_suffix(PATH.suffix + ".tmp")
        tmp.write_text(json.dumps(calls, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(PATH)


def summary() -> dict:
    """汇总:总调用数 / 总字数 / 按用户 / 按模型角色"""
    calls = _load()
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
