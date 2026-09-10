"""
轻量持久层(演示环境):用户表 + token 表,落盘为 JSON 文件。

正式环境替换为数据库(PostgreSQL / SQLite)即可,store 的接口形状保持不变:
- users: uid -> 用户记录
- tokens: token -> uid(重启不丢,避免前端重复登录)
"""
import hashlib
import json
import secrets
import time
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent / "data"
USERS_PATH = DATA_DIR / "users.json"
TOKENS_PATH = DATA_DIR / "tokens.json"

# 内存缓存(进程内唯一读写入口;演示环境单进程,无需锁)
_users: dict[str, dict] = {}
_tokens: dict[str, dict] = {}
# 手机号 -> uid 索引:认证请求 O(1) 查找
_phone_index: dict[str, str] = {}

TOKEN_TTL_HOURS = 24  # 演示 token 有效期(测试期安全):验证时逐条检查过期,签发时顺带清理过期项


def _load(path: Path) -> dict:
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        pass
    return {}


def _save(path: Path, data: dict) -> None:
    """原子写盘:先写临时文件再整体替换,避免中途崩溃/并发写坏 JSON(_load 会把坏文件吞成空库)"""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(path)


def init() -> None:
    """启动时装载数据文件"""
    global _users, _tokens, _phone_index
    _users = _load(USERS_PATH)
    _tokens = _load(TOKENS_PATH)
    _phone_index = {rec["phone"]: uid for uid, rec in _users.items() if rec.get("phone")}


# ---------- 密码 ----------

def hash_password(password: str, salt: str | None = None) -> tuple[str, str]:
    """返回 (salt, 加盐哈希)。演示环境不做慢哈希,正式环境换 bcrypt/argon2"""
    salt = salt or secrets.token_hex(8)
    digest = hashlib.sha256((salt + password).encode("utf-8")).hexdigest()
    return salt, digest


# ---------- 用户 ----------

def find_user_by_phone(phone: str) -> tuple[str, dict] | None:
    uid = _phone_index.get(phone)
    if not uid:
        return None
    rec = _users.get(uid)
    return (uid, rec) if rec else None


def create_user(rec: dict) -> str:
    """写入用户;调用方保证 uid 唯一"""
    uid = rec["uid"]
    _users[uid] = rec
    if rec.get("phone"):
        _phone_index[rec["phone"]] = uid
    _save(USERS_PATH, _users)
    return uid


# ---------- token ----------

def _sweep_tokens() -> None:
    """清理过期 token(签发时顺带执行,摊薄写盘成本)"""
    now = time.time()
    stale = [t for t, e in _tokens.items()
             if isinstance(e, dict) and now - e.get("issued", now) > TOKEN_TTL_HOURS * 3600]
    if not stale:
        return
    for t in stale:
        _tokens.pop(t, None)
    _save(TOKENS_PATH, _tokens)


def issue_token(uid: str) -> str:
    _sweep_tokens()
    token = secrets.token_hex(24)
    _tokens[token] = {"uid": uid, "issued": time.time()}
    _save(TOKENS_PATH, _tokens)
    return token


def resolve_token(token: str) -> dict | None:
    """token -> 用户记录(兼容旧格式 token -> uid 字符串);
    过期 token 视为无效(旧格式无签发时间按当前时间起算)"""
    entry = _tokens.get(token)
    if entry is None:
        return None
    if isinstance(entry, dict):
        issued = entry.get("issued")
        if isinstance(issued, (int, float)) and time.time() - issued > TOKEN_TTL_HOURS * 3600:
            return None
        uid = entry.get("uid")
    else:
        uid = entry
    return _users.get(uid) if uid else None


def revoke_token(token: str) -> None:
    _tokens.pop(token, None)
    _save(TOKENS_PATH, _tokens)
