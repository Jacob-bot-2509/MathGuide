"""外部论文临时入库:阅读器打开前把开放获取 PDF 放进语料库,
状态为 temp,不进入「我的论文」列表与默认检索,导入后转为 imported。"""
from __future__ import annotations

import asyncio
from urllib.parse import urlparse

import httpx
from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import JSONResponse

import research_corpus as rc
import research_lit as lit
import research_vision as vision
from auth import require_auth
from http_utils import read_json_object


def _pdf_name(url: str) -> str:
    path = urlparse(url).path
    name = path.rsplit("/", 1)[-1] or "paper.pdf"
    if not name.lower().endswith(".pdf"):
        name = f"{name}.pdf"
    return name[:200]


async def create_temp(request: Request) -> JSONResponse:
    rec = require_auth(request)
    uid = str(rec.get("uid") or "")
    body = await read_json_object(request)
    url = str(body.get("url") or "").strip()
    if not lit._pdf_url_allowed(url):
        raise HTTPException(400, "该论文没有可用的开放获取 PDF")
    metadata = body.get("metadata") if isinstance(body.get("metadata"), dict) else None
    rc._rate(rc._upload_limiter, uid)
    try:
        data = await lit.download_allowed_pdf(url)
        result = await asyncio.to_thread(
            rc._ingest, uid, _pdf_name(url), data, "application/pdf",
            None, status="temp", origin_url=url, analyze=False, metadata=metadata)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(502, f"下载 PDF 失败: {type(exc).__name__}") from exc
    return JSONResponse(result, headers={"Cache-Control": "no-store"})


async def history_retention_loop() -> None:
    while True:
        await asyncio.sleep(24 * 60 * 60)
        try:
            await asyncio.to_thread(rc.purge_expired_history_all)
        except Exception as exc:  # A failed cleanup must not stop future daily attempts.
            print(f"[retention] 浏览历史清理失败: {exc}")


async def history_list(request: Request) -> JSONResponse:
    rec = require_auth(request)
    uid = str(rec.get("uid") or "")
    await asyncio.to_thread(rc.purge_expired_history, uid)
    items = await asyncio.to_thread(rc._history_items, uid)
    return JSONResponse({"items": items}, headers={"Cache-Control": "no-store"})


async def history_trash(request: Request) -> JSONResponse:
    rec = require_auth(request)
    uid = str(rec.get("uid") or "")
    await asyncio.to_thread(rc.purge_expired_history, uid)
    items = await asyncio.to_thread(rc._history_trash, uid)
    return JSONResponse({"items": items}, headers={"Cache-Control": "no-store"})


async def history_delete(request: Request) -> JSONResponse:
    rec = require_auth(request)
    uid = str(rec.get("uid") or "")
    doc_id = str(request.path_params.get("doc_id") or "")
    hard = request.query_params.get("hard", "").lower() in {"1", "true", "yes"}
    if hard:
        ok = await asyncio.to_thread(rc._delete, uid, doc_id)
        if ok:
            await asyncio.to_thread(rc._vacuum, uid)
    else:
        ok = await asyncio.to_thread(rc._history_delete, uid, doc_id)
    if not ok:
        raise HTTPException(404, "not found")
    return JSONResponse({"ok": True, "hard": hard,
                         "days": 0 if hard else rc.HISTORY_TTL_DAYS})


async def history_restore(request: Request) -> JSONResponse:
    rec = require_auth(request)
    uid = str(rec.get("uid") or "")
    doc_id = str(request.path_params.get("doc_id") or "")
    ok = await asyncio.to_thread(rc._history_restore, uid, doc_id)
    if not ok:
        raise HTTPException(404, "not found")
    return JSONResponse({"ok": True})


async def explain_region(request: Request) -> JSONResponse:
    """解释阅读器里框选的图表/公式区域:只依据截图,不猜数值。"""
    rec = require_auth(request)
    uid = str(rec.get("uid") or "")
    doc_id = str(request.path_params.get("doc_id") or "")
    doc = await asyncio.to_thread(rc._doc_row, uid, doc_id)
    if doc is None or doc["deletedAt"]:
        raise HTTPException(404, "not found")
    if not vision.is_configured():
        raise HTTPException(503, "vision model not configured")
    if not vision._limiter.allow(uid):
        raise HTTPException(429, "操作过于频繁,请稍后再试")
    body = await read_json_object(request)
    question = str(body.get("question") or "")
    try:
        mime, data = vision._decode_image(body.get("image"))
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    try:
        answer = await asyncio.to_thread(vision.explain_image, mime, data, question)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(502, str(exc)) from exc
    return JSONResponse({"answer": answer}, headers={"Cache-Control": "no-store"})


async def extract_table(request: Request) -> JSONResponse:
    """论文表格截图 → 结构化表格;只返回预览,由用户确认后才写入数据表。"""
    rec = require_auth(request)
    uid = str(rec.get("uid") or "")
    doc_id = str(request.path_params.get("doc_id") or "")
    doc = await asyncio.to_thread(rc._doc_row, uid, doc_id)
    if doc is None or doc["deletedAt"]:
        raise HTTPException(404, "not found")
    if not vision.is_configured():
        raise HTTPException(503, "vision model not configured")
    if not vision._limiter.allow(uid):
        raise HTTPException(429, "操作过于频繁,请稍后再试")
    body = await read_json_object(request)
    try:
        mime, data = vision._decode_image(body.get("image"))
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    try:
        page = int(body.get("page") or 0)
    except (TypeError, ValueError):
        page = 0
    try:
        table = await asyncio.to_thread(vision.extract_table, mime, data)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(502, str(exc)) from exc
    return JSONResponse({
        "table": table,
        "docId": doc_id,
        "docName": str(doc.get("name") or "")[:200],
        "page": max(0, min(page, 100000)),
    }, headers={"Cache-Control": "no-store"})


async def locate(request: Request) -> JSONResponse:
    """在当前论文内定位与问题相关的段落,供阅读器高亮。"""
    rec = require_auth(request)
    uid = str(rec.get("uid") or "")
    doc_id = str(request.path_params.get("doc_id") or "")
    body = await read_json_object(request)
    query = str(body.get("query") or "").strip()
    if not query:
        raise HTTPException(400, "缺少 query")
    doc = await asyncio.to_thread(rc._doc_row, uid, doc_id)
    if doc is None or doc["deletedAt"]:
        raise HTTPException(404, "not found")
    hits = await asyncio.to_thread(rc.chat_hits, uid, query, 6, doc_id)
    mode = _locate_mode(query)
    passages = [{
        "page": int(hit.get("pageStart") or 1),
        "pageEnd": int(hit.get("pageEnd") or 1),
        "quote": _trim_quote(str(hit.get("snippet") or ""), query, mode),
        "section": hit.get("section") or "",
        "mode": mode,
    } for hit in hits]
    return JSONResponse({"passages": passages}, headers={"Cache-Control": "no-store"})


def _locate_mode(query: str) -> str:
    low = query.lower()
    if any(key in low for key in (
            "定义", "什么是", "是什么", "符号", "what is", "define", "definition")):
        return "sentence"
    if any(key in low for key in (
            "解释", "说明", "这段", "这句话", "概括", "总结",
            "explain", "summarize", "summary", "paragraph")):
        return "paragraph"
    return "auto"


def _trim_quote(text: str, query: str, mode: str) -> str:
    """按问题粒度裁剪命中片段:术语给一句,解释给一段,其余给两三句。"""
    import re as _re

    clean = _re.sub(r"\s+", " ", text or "").strip()
    if not clean:
        return ""
    parts = [p.strip() for p in _re.findall(r"[^.!?。！？]+[.!?。！？]?", clean) if p.strip()]
    if not parts:
        return clean[:500]
    tokens = sorted(
        (t for t in _re.findall(r"[\w一-鿿]{3,}", query.lower())),
        key=len, reverse=True)
    anchor = 0
    if tokens:
        for index, part in enumerate(parts):
            if tokens[0] in part.lower():
                anchor = index
                break
    if mode == "sentence":
        return parts[anchor][:300]
    count = 3 if mode == "paragraph" else 2
    chosen = parts[anchor:anchor + count]
    if not chosen:
        chosen = parts[:count]
    return " ".join(chosen)[:600]


async def import_paper(request: Request) -> JSONResponse:
    """临时论文转为正式入库;批注按 docId 保留,无需迁移。"""
    rec = require_auth(request)
    uid = str(rec.get("uid") or "")
    body = await read_json_object(request)
    doc_id = str(body.get("docId") or "")
    project_id = body.get("projectId")
    if not doc_id:
        raise HTTPException(400, "缺少 docId")
    project = str(project_id) if isinstance(project_id, str) and project_id else None
    keep_annotations = body.get("keepAnnotations", True) is not False
    try:
        result = await asyncio.to_thread(
            rc._import_temp, uid, doc_id, project, keep_annotations)
    except FileNotFoundError as exc:
        raise HTTPException(404, "not found") from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return JSONResponse(result)
