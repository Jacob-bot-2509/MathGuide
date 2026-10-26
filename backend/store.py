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
GUEST_UID_PREFIX = "guest-"

# 密码哈希:新记录用 PBKDF2-HMAC-SHA256(stdlib,无新依赖);
# 旧记录是单轮 sha256(salt+password),登录成功后自动升级(见 auth.login)。
PBKDF2_ROUNDS = 200_000
PBKDF2_PREFIX = "pbkdf2_sha256"


def _load(path: Path) -> dict:
    try:
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            # 合法 JSON 但不是对象("[]" / "null" / 数字)时按空库处理:
            # 调用方一律 .items(),直接放行会在启动阶段抛 AttributeError 起不来
            if not isinstance(data, dict):
                print(f"[store] {path.name} 不是 JSON 对象,按空库处理: {type(data).__name__}")
                return {}
            return data
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
    """启动时装载数据文件;顺带把旧格式 token(token -> uid 字符串)迁移为带签发时间的记录"""
    global _users, _tokens, _phone_index
    # 顶层是对象不代表每个用户记录都合法:手改/写坏成字符串的条目直接丢弃,
    # 否则 _phone_index 的 rec.get 与 user_dto 的 rec["nickname"] 会在请求期抛 500
    _users = {uid: rec for uid, rec in _load(USERS_PATH).items() if isinstance(rec, dict)}
    _tokens = _load(TOKENS_PATH)
    migrated = False
    for token, entry in list(_tokens.items()):
        if isinstance(entry, str):
            _tokens[token] = {"uid": entry, "issued": time.time()}
            migrated = True
    if migrated:
        try:
            _save(TOKENS_PATH, _tokens)
        except OSError as exc:  # 只读/占用时不阻断启动,内存中的迁移仍然有效
            print(f"[store] 旧格式 token 迁移写盘失败(不影响本次运行): {exc}")
    _phone_index = {
        rec["phone"]: uid
        for uid, rec in _users.items()
        if isinstance(rec.get("phone"), str) and rec["phone"]
    }


# ---------- 密码 ----------

def _is_new_hash_spec(salt: str) -> bool:
    return salt.startswith(PBKDF2_PREFIX + "$")


def is_legacy_hash(salt: object) -> bool:
    """旧格式(单轮 sha256)的 salt 没有算法前缀;登录成功后可升级。"""
    return isinstance(salt, str) and not _is_new_hash_spec(salt)


def hash_password(password: str, salt: str | None = None) -> tuple[str, str]:
    """返回 (salt_spec, digest)。

    salt 为 None → 生成新格式 `pbkdf2_sha256$<rounds>$<salt>`;
    salt 为新格式 → 按其中的轮数/盐重算(验证用);
    salt 为旧格式(无前缀)→ 按旧算法重算,保证历史用户仍能登录。
    """
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
            # 存储损坏:按新哈希重新生成,避免登录 500(用户需重置密码)
            return hash_password(password)
        if rounds < 1:
            return hash_password(password)
        digest = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), real_salt.encode("utf-8"), rounds)
        return salt, digest.hex()

    # 旧格式:单轮 sha256(salt + password),只用于验证/迁移
    return salt, hashlib.sha256((salt + password).encode("utf-8")).hexdigest()


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


def update_password_hash(uid: str, password_hash: tuple[str, str]) -> bool:
    """替换用户密码哈希(旧格式登录成功后升级用)。"""
    rec = _users.get(uid)
    if rec is None:
        return False
    rec["password_hash"] = password_hash
    _save(USERS_PATH, _users)
    return True


# ---------- 游客账号 ----------

def guest_count() -> int:
    return sum(1 for uid in _users if str(uid).startswith(GUEST_UID_PREFIX))


def _token_uid(entry: object) -> str:
    if isinstance(entry, dict):
        return str(entry.get("uid") or "")
    return str(entry or "")


def prune_guests(max_guests: int) -> int:
    """把游客账号压到 max_guests 以内;只删「没有有效 token」的最旧记录。

    返回实际删除数。若游客都还有有效 token,可能删不到目标数量,
    由调用方决定拒绝新建(见 auth.login)。
    """
    if max_guests < 0:
        max_guests = 0
    guests = {
        uid: rec for uid, rec in _users.items()
        if str(uid).startswith(GUEST_UID_PREFIX) and isinstance(rec, dict)
    }
    excess = len(guests) - max_guests
    if excess <= 0:
        return 0

    now = time.time()
    active = {
        _token_uid(entry) for entry in _tokens.values()
        if isinstance(entry, dict)
        and isinstance(entry.get("issued"), (int, float))
        and now - entry["issued"] <= TOKEN_TTL_HOURS * 3600
    }
    removable = [uid for uid in guests if uid not in active]
    removable.sort(key=lambda uid: str(_users[uid].get("createdAt") or ""))
    removed = removable[:excess]
    if not removed:
        return 0

    for uid in removed:
        _users.pop(uid, None)
    removed_set = set(removed)
    for token in [t for t, entry in _tokens.items() if _token_uid(entry) in removed_set]:
        _tokens.pop(token, None)
    _save(USERS_PATH, _users)
    _save(TOKENS_PATH, _tokens)
    return len(removed)


# ---------- token ----------

def _sweep_tokens() -> None:
    """清理过期/损坏 token(签发时顺带执行,摊薄写盘成本)"""
    now = time.time()
    stale = [token for token, entry in _tokens.items()
             if not isinstance(entry, dict)
             or not isinstance(entry.get("issued"), (int, float))
             or now - entry["issued"] > TOKEN_TTL_HOURS * 3600]
    if not stale:
        return
    for token in stale:
        _tokens.pop(token, None)
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
        # 缺签发时间 = 损坏/手工编辑的记录,不能当成永久 token
        if not isinstance(issued, (int, float)):
            return None
        if time.time() - issued > TOKEN_TTL_HOURS * 3600:
            return None
        uid = entry.get("uid")
    else:
        uid = entry
    return _users.get(uid) if uid else None


def revoke_token(token: str) -> bool:
    """吊销 token;返回是否真的删除了一条记录。

    没删到就不写盘:否则任意伪造 token 调一次 /api/auth/logout 都能触发
    全量 tokens.json 重写(几千条 token 时是几百 KB 的写放大,可被用来刷盘)。
    """
    if token not in _tokens:
        return False
    del _tokens[token]
    _save(TOKENS_PATH, _tokens)
    return True
