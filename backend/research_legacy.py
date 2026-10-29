"""Import the old browser research archive without deleting its original backup."""
from __future__ import annotations

import asyncio
import hashlib
import json
import math
import time

from starlette.requests import Request
from starlette.responses import JSONResponse

from auth import require_auth
import research_corpus as corpus

MAX_BYTES = 6 * 1024 * 1024


def _legacy_time(value: object, fallback: float) -> float:
    if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value > 0:
        return value / 1000
    return fallback


def _import_archive(uid: str, archive: object) -> dict:
    if not isinstance(archive, dict):
        raise ValueError("Invalid archive")
    projects, files = archive.get("projects"), archive.get("files")
    if not isinstance(projects, list) or not isinstance(files, list) or len(projects) > 30 or len(files) > 60:
        raise ValueError("Invalid archive contents")
    for entries in (projects, files):
        ids = [item.get("id") if isinstance(item, dict) else None for item in entries]
        if any(not isinstance(i, int) or isinstance(i, bool) for i in ids) or len(set(ids)) != len(ids):
            raise ValueError("Invalid archive identifiers")
    for p in projects:
        if any(not isinstance(p.get(k, ""), str) for k in ("title", "goal", "approach", "notes", "status")):
            raise ValueError("Invalid project fields")
    for f in files:
        if not isinstance(f.get("name"), str) or not f["name"] or not isinstance(f.get("text", ""), str):
            raise ValueError("Invalid file fields")
        if not isinstance(f.get("size", 0), int) or f.get("size", 0) < 0:
            raise ValueError("Invalid file size")

    digest = hashlib.sha256(json.dumps(archive, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()
    conn = corpus._connect(uid)
    try:
        conn.commit()
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("CREATE TABLE IF NOT EXISTS legacy_imports(digest TEXT PRIMARY KEY)")
        if conn.execute("SELECT 1 FROM legacy_imports WHERE digest = ?", (digest,)).fetchone():
            conn.commit()
            return {"duplicate": True, "projects": len(projects), "files": len(files)}
        mapping = {}
        now = time.time()
        for p in projects:
            pid = "legacy-p-" + hashlib.sha256(f"{digest}:{p['id']}".encode()).hexdigest()[:24]
            mapping[p["id"]] = pid
            status = p.get("status") if p.get("status") in corpus.PROJECT_STATUSES else "exploring"
            conn.execute("INSERT INTO projects(id,title,goal,approach,notes,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)",
                         (pid, p.get("title") or "未命名研究", p.get("goal", ""), p.get("approach", ""), p.get("notes", ""), status, _legacy_time(p.get("createdAt"), now), _legacy_time(p.get("updatedAt"), now)))
        for f in files:
            doc_id = "legacy-d-" + hashlib.sha256(f"{digest}:{f['id']}".encode()).hexdigest()[:24]
            content = f.get("text", "")
            project_id = mapping.get(f.get("projectId"))
            conn.execute("INSERT INTO docs(id,name,size,sha,pages,created_at,mime,project_id,title) VALUES(?,?,?,?,?,?,?,?,?)",
                         (doc_id, f["name"], f.get("size", 0), doc_id, 1 if content else 0, _legacy_time(f.get("addedAt"), now),
                          "application/x-mathguide-legacy", project_id, f["name"]))
            if content:
                node_id = doc_id + "#s1"
                conn.execute("INSERT INTO nodes(id,doc_id,parent_id,title,summary,page_start,page_end,text) VALUES(?,?,?,?,?,?,?,?)",
                             (node_id, doc_id, None, f["name"], content[:200], 1, 1, content))
                for i in range(0, len(content), 1000):
                    conn.execute("INSERT INTO chunks(id,doc_id,node_id,page_start,page_end,section,text) VALUES(?,?,?,?,?,?,?)",
                                 (f"{node_id}c{i // 1000}", doc_id, node_id, 1, 1, f["name"], content[i:i + 1000]))
        conn.execute("INSERT INTO legacy_imports(digest) VALUES(?)", (digest,))
        corpus._bump_version(conn)
        conn.commit()
    finally:
        conn.close()
    with corpus._index_lock:
        corpus._indexes.pop(uid, None)
    return {"duplicate": False, "projects": len(projects), "files": len(files)}


async def import_archive(request: Request) -> JSONResponse:
    uid = require_auth(request)["uid"]
    raw = await request.body()
    if len(raw) > MAX_BYTES:
        return JSONResponse({"error": "Archive is too large"}, status_code=413)
    try:
        archive = json.loads(raw)
        result = await asyncio.to_thread(_import_archive, uid, archive)
    except (ValueError, TypeError, json.JSONDecodeError):
        return JSONResponse({"error": "Invalid archive"}, status_code=400)
    return JSONResponse(result)
