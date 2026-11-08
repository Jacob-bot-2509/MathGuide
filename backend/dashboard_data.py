"""只读看板数据(供 Streamlit 运维看板复用,也可单独调用)。

直接读 SQLite,不启动 Web 服务;所有查询只读,不修改线上数据。
"""
from __future__ import annotations

from pathlib import Path

import db


def _connect() -> "object":
    db.init()  # 看板可能先于业务模块启动,确保表存在
    conn = db.connect()
    conn.execute("PRAGMA query_only=ON")
    return conn


def overview() -> dict:
    """返回账号、令牌、用量与诊断的汇总数字。"""
    conn = _connect()
    try:
        users = conn.execute("SELECT COUNT(*) AS n FROM users").fetchone()["n"]
        guests = conn.execute(
            "SELECT COUNT(*) AS n FROM users WHERE uid LIKE 'guest-%'").fetchone()["n"]
        tokens = conn.execute("SELECT COUNT(*) AS n FROM tokens").fetchone()["n"]
        usage = conn.execute(
            "SELECT COUNT(*) AS n, COALESCE(SUM(json_extract(doc, '$.reply_len')), 0) AS chars "
            "FROM usage"
        ).fetchone()
        roles = {
            row["role"]: row["n"] for row in conn.execute(
                "SELECT COALESCE(json_extract(doc, '$.role'), 'main') AS role, "
                "COUNT(*) AS n FROM usage GROUP BY role ORDER BY n DESC")
        }
        workspaces = {
            row["workspace"]: row["n"] for row in conn.execute(
                "SELECT COALESCE(json_extract(doc, '$.workspace'), 'learn') AS workspace, "
                "COUNT(*) AS n FROM usage GROUP BY workspace")
        }
        diagnoses = conn.execute("SELECT COUNT(*) AS n FROM diagnoses").fetchone()["n"]
        weak = conn.execute(
            "SELECT COUNT(*) AS n FROM diagnoses WHERE score < 3").fetchone()["n"]
    finally:
        conn.close()
    return {
        "users": int(users),
        "guests": int(guests),
        "tokens": int(tokens),
        "usage_calls": int(usage["n"]),
        "usage_chars": int(usage["chars"] or 0),
        "roles": roles,
        "workspaces": workspaces,
        "diagnoses": int(diagnoses),
        "weak": int(weak),
    }


def weak_points(limit: int = 10) -> list[dict]:
    """每个知识点取最后一次诊断,按分数升序返回薄弱点。"""
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT point_id, score, doc, at FROM diagnoses d "
            "WHERE id = (SELECT MAX(id) FROM diagnoses x "
            "            WHERE x.uid = d.uid AND x.point_id = d.point_id) "
            "AND score < 3 ORDER BY score ASC, at DESC LIMIT ?",
            (limit,),
        ).fetchall()
    finally:
        conn.close()
    return [
        {"pointId": row["point_id"], "score": row["score"], "at": row["at"]}
        for row in rows
    ]


def db_path() -> Path:
    return db.DB_PATH
