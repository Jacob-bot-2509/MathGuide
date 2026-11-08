"""SQLite 持久层:连接、建表与一次性旧数据迁移。

为什么从 JSON 文件迁到 SQLite:
- 账号删除、令牌吊销、用量与诊断删除需要事务,避免"删了一半"；
- 手机号、uid、token 键需要索引,避免全表扫描；
- WAL 模式下读写不互相阻塞,多进程/多线程访问安全。

库文件:backend/data/mathguide.db(与旧 JSON/JSONL 同目录)。
旧文件不删除,作为备份保留;只在首次建库时导入一次(meta 表标记)。
"""
from __future__ import annotations

import json
import sqlite3
import threading
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

DATA_DIR = Path(__file__).resolve().parent / "data"
DB_PATH = DATA_DIR / "mathguide.db"

_lock = threading.Lock()

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    uid            TEXT PRIMARY KEY,
    phone          TEXT,
    doc            TEXT NOT NULL,
    created_at     TEXT,
    last_active_at TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_users_phone
    ON users(phone) WHERE phone IS NOT NULL AND phone <> '';

CREATE TABLE IF NOT EXISTS tokens (
    key    TEXT PRIMARY KEY,
    uid    TEXT NOT NULL,
    issued REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_tokens_uid ON tokens(uid);

CREATE TABLE IF NOT EXISTS usage (
    id  INTEGER PRIMARY KEY AUTOINCREMENT,
    uid TEXT NOT NULL,
    ts  REAL NOT NULL,
    doc TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_usage_uid ON usage(uid);
CREATE INDEX IF NOT EXISTS idx_usage_ts ON usage(ts);

CREATE TABLE IF NOT EXISTS diagnoses (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    uid      TEXT NOT NULL,
    point_id TEXT NOT NULL,
    score    INTEGER NOT NULL,
    doc      TEXT NOT NULL,
    at       TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_diagnoses_uid ON diagnoses(uid);
CREATE INDEX IF NOT EXISTS idx_diagnoses_point ON diagnoses(uid, point_id, id);

CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


def connect() -> sqlite3.Connection:
    """打开连接。WAL + busy_timeout:并发写等待而不是立刻报 database is locked。"""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA busy_timeout=10000")
        # 首次切换 WAL 可能直接返回锁冲突,即使已设置 busy_timeout。
        deadline = time.monotonic() + 10
        while True:
            try:
                conn.execute("PRAGMA journal_mode=WAL")
                break
            except sqlite3.OperationalError as exc:
                if getattr(exc, "sqlite_errorcode", 0) & 255 not in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED) or time.monotonic() >= deadline:
                    raise
                time.sleep(0.05)
        conn.execute("PRAGMA synchronous=NORMAL")
        return conn
    except BaseException:
        conn.close()
        raise


@contextmanager
def transaction() -> Iterator[sqlite3.Connection]:
    """显式事务:异常回滚,正常提交。用于跨表操作(如注销账号)。"""
    conn = connect()
    try:
        with conn:  # sqlite3.Connection 的上下文管理器负责 commit/rollback
            yield conn
    finally:
        conn.close()


def init() -> None:
    """建表(幂等)。旧数据导入由各模块用 meta 标记控制。"""
    with _lock:
        conn = connect()
        try:
            conn.executescript(SCHEMA)
            conn.commit()
        finally:
            conn.close()


def get_meta(key: str) -> str | None:
    conn = connect()
    try:
        row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else None
    finally:
        conn.close()


def set_meta(key: str, value: str) -> None:
    with transaction() as conn:
        conn.execute(
            "INSERT INTO meta(key, value) VALUES(?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )


def table_empty(table: str) -> bool:
    """表是否为空;只接受固定表名,避免把外部字符串拼进 SQL。"""
    if table not in {"users", "tokens", "usage", "diagnoses"}:
        raise ValueError(f"未知表名: {table}")
    conn = connect()
    try:
        row = conn.execute(f"SELECT 1 FROM {table} LIMIT 1").fetchone()
        return row is None
    finally:
        conn.close()


def reset_for_tests() -> None:
    """删除测试库文件(WAL/SHM 一并清理),供 fixture 在临时目录重建。"""
    for suffix in ("", "-wal", "-shm"):
        path = Path(str(DB_PATH) + suffix)
        try:
            path.unlink()
        except FileNotFoundError:
            pass


def read_json(path: Path) -> object | None:
    """读取旧 JSON 文件;不存在返回 None,损坏或无法读取时拒绝迁移。"""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None


def read_jsonl(path: Path) -> list[dict]:
    """完整解析旧 JSONL,任何坏行都必须先修复才能继续。"""
    try:
        with path.open(encoding="utf-8") as handle:
            entries = []
            for number, line in enumerate(handle, 1):
                if not line.strip():
                    continue
                try:
                    item = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise ValueError(f"{path}:{number}: 无效 JSON") from exc
                if not isinstance(item, dict):
                    raise ValueError(f"{path}:{number}: 记录必须是对象")
                entries.append(item)
            return entries
    except FileNotFoundError:
        return []


def write_legacy(path: Path, text: str) -> None:
    """原子替换旧文件,失败时保留原文件。"""
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         prefix=path.name + ".", suffix=".tmp", delete=False) as handle:
            temp_path = Path(handle.name)
            handle.write(text)
        temp_path.replace(path)
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)


def remove_jsonl(path: Path, predicate) -> int:
    entries = read_jsonl(path)
    kept = [entry for entry in entries if not predicate(entry)]
    removed = len(entries) - len(kept)
    if removed:
        write_legacy(path, "".join(json.dumps(entry, ensure_ascii=False) + "\n" for entry in kept))
    return removed
