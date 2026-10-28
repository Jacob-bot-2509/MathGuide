"""留存清理:按环境变量删除长期不活跃账号与过期用量记录。

默认关闭(`0`),避免演示环境启动时误删历史数据。
- MG_ACCOUNT_TTL_DAYS: 账号超过 N 天未登录则删除,管理员白名单永久保留;
- MG_USAGE_TTL_DAYS: 用量记录超过 N 天则删除(JSONL 与旧备份都清)。
只输出数量,不输出手机号/昵称/内容。
"""
from __future__ import annotations

import os
from datetime import datetime

import auth
import research_corpus
import session_cache
import store
import usage


def _days(name: str) -> float:
    raw = os.getenv(name, "").strip()
    try:
        value = float(raw)
    except ValueError:
        return 0.0
    return value if value > 0 else 0.0


def run(now: datetime | None = None) -> dict[str, int]:
    account_days = _days("MG_ACCOUNT_TTL_DAYS")
    usage_days = _days("MG_USAGE_TTL_DAYS")
    removed_accounts = 0
    removed_usage = 0

    if account_days > 0:
        users = store.users_snapshot()
        exempt = {uid for uid, rec in users.items() if auth.is_admin(rec)}
        removed = store.prune_inactive(account_days, exempt, now=now)
        for rec in removed:
            uid = str(rec.get("uid") or "")
            phone = str(rec.get("phone") or "")
            if uid:
                removed_usage += usage.delete_user(uid, phone)
                session_cache.clear_user(uid)
                research_corpus.delete_user(uid)
        removed_accounts = len(removed)

    if usage_days > 0:
        removed_usage += usage.prune_older_than(usage_days, now=None if now is None else now.timestamp())

    return {
        "accounts": removed_accounts,
        "usage": removed_usage,
    }
