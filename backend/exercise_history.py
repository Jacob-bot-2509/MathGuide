"""习题集生成历史:草稿、导出确认、列表与清理。

只保存用户实际导出的文档快照;预览/生成但未下载的记录是 draft,
24 小时后自动清理,不进入历史列表。
"""
from __future__ import annotations

import json
import secrets
from datetime import datetime, timedelta

import db

DRAFT_TTL_HOURS = 24
EXPORT_TTL_DAYS = 180
MAX_EXPORTED = 50


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _prune(conn, uid: str) -> None:
    now = datetime.now().astimezone()
    draft_cutoff = (now - timedelta(hours=DRAFT_TTL_HOURS)).isoformat(timespec="seconds")
    export_cutoff = (now - timedelta(days=EXPORT_TTL_DAYS)).isoformat(timespec="seconds")
    conn.execute(
        "DELETE FROM exercise_documents WHERE uid = ? AND status = 'draft' AND created_at < ?",
        (uid, draft_cutoff),
    )
    conn.execute(
        "DELETE FROM exercise_documents WHERE uid = ? AND status = 'exported' AND created_at < ?",
        (uid, export_cutoff),
    )
    rows = conn.execute(
        "SELECT id FROM exercise_documents WHERE uid = ? AND status = 'exported' "
        "ORDER BY created_at DESC, id DESC",
        (uid,),
    ).fetchall()
    for row in rows[MAX_EXPORTED:]:
        conn.execute("DELETE FROM exercise_documents WHERE id = ?", (row["id"],))


def create_draft(
    uid: str,
    document: dict,
    filters: dict,
    seed: int,
    exclude_ids: list[str],
    lang: str,
    mode: str,
    title: str,
) -> str:
    doc_id = secrets.token_hex(12)
    count = int(document.get("exercise_meta", {}).get("count", 0) or 0)
    with db.transaction() as conn:
        conn.execute(
            "INSERT INTO exercise_documents "
            "(id, uid, status, created_at, exported_at, title, lang, mode, "
            " item_count, seed, exclude_ids, filters, document) "
            "VALUES (?, ?, 'draft', ?, NULL, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                doc_id, uid, _now(), title, lang, mode, count, int(seed),
                json.dumps(exclude_ids, ensure_ascii=False),
                json.dumps(filters, ensure_ascii=False),
                json.dumps(document, ensure_ascii=False),
            ),
        )
        _prune(conn, uid)
    return doc_id


def confirm(uid: str, doc_id: str) -> bool:
    with db.transaction() as conn:
        result = conn.execute(
            "UPDATE exercise_documents SET status = 'exported', exported_at = ? "
            "WHERE id = ? AND uid = ? AND status = 'draft'",
            (_now(), doc_id, uid),
        )
        if result.rowcount:
            _prune(conn, uid)
            return True
        row = conn.execute(
            "SELECT 1 FROM exercise_documents WHERE id = ? AND uid = ? AND status = 'exported'",
            (doc_id, uid),
        ).fetchone()
        return row is not None


def list_documents(uid: str, limit: int = 20) -> list[dict]:
    limit = max(1, min(50, int(limit)))
    conn = db.connect()
    try:
        rows = conn.execute(
            "SELECT id, title, created_at, exported_at, item_count, lang, mode, filters "
            "FROM exercise_documents WHERE uid = ? AND status = 'exported' "
            "ORDER BY created_at DESC, id DESC LIMIT ?",
            (uid, limit),
        ).fetchall()
    finally:
        conn.close()
    return [
        {
            "id": row["id"],
            "title": row["title"],
            "createdAt": row["created_at"],
            "exportedAt": row["exported_at"],
            "count": row["item_count"],
            "lang": row["lang"],
            "mode": row["mode"],
            "filters": json.loads(row["filters"]),
        }
        for row in rows
    ]


def get_document(uid: str, doc_id: str) -> dict | None:
    conn = db.connect()
    try:
        row = conn.execute(
            "SELECT id, title, created_at, exported_at, item_count, lang, mode, "
            "seed, filters, document FROM exercise_documents "
            "WHERE id = ? AND uid = ? AND status = 'exported'",
            (doc_id, uid),
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        return None
    return {
        "id": row["id"],
        "title": row["title"],
        "createdAt": row["created_at"],
        "exportedAt": row["exported_at"],
        "count": row["item_count"],
        "lang": row["lang"],
        "mode": row["mode"],
        "seed": row["seed"],
        "filters": json.loads(row["filters"]),
        "document": json.loads(row["document"]),
    }


def delete_document(uid: str, doc_id: str) -> bool:
    with db.transaction() as conn:
        result = conn.execute(
            "DELETE FROM exercise_documents WHERE id = ? AND uid = ?",
            (doc_id, uid),
        )
        return bool(result.rowcount)


def delete_user(uid: str) -> None:
    with db.transaction() as conn:
        conn.execute("DELETE FROM exercise_documents WHERE uid = ?", (uid,))
