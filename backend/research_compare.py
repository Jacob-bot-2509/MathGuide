"""多文献对比表:勾选论文 → 逐篇抽取研究问题/方法/数据/结果/局限 → 结构化表格。

约束:
- 只依据用户自己的论文正文,每行必须带回来源 docId 与页码;
- 模型只做归纳,不计算、不补全缺失数字;抽不到的字段留空并写警告;
- 对比结果不直接落库,由前端确认后创建数据表(沿用统一表格 schema)。
"""
from __future__ import annotations

import asyncio
import json
import re

from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import JSONResponse

import rag.llm as llm
import research_corpus as rc
from auth import require_auth
from http_utils import read_json_object
from rate_limit import SlidingWindowLimiter

MAX_DOCS = 6
EXCERPT_CHARS = 7000
FIELD_MAX = 500
_limiter = SlidingWindowLimiter(6, 300)

COLUMNS = ["论文", "年份", "研究问题", "方法", "数据与样本", "主要结果", "局限", "核对"]
FIELDS = ["question", "method", "data", "results", "limitations"]

SYSTEM = (
    "你是文献对比抽取器。只依据用户提供的一篇论文正文,抽取结构化字段。"
    "只输出 JSON,不要解释,不要 markdown 代码块。\n"
    "输出格式:\n"
    '{"question":"研究问题","method":"方法","data":"数据与样本",'
    '"results":"主要结果(保留原文数值与单位)","limitations":"局限"}\n'
    "规则:\n"
    "1. 每个字段用 1~3 句话概括,不得编造;正文没有就说空字符串;\n"
    "2. results 必须从正文 Results/结果 段落逐字摘录关键句,保留两组数值的对应关系;"
    "禁止改写、合并或复述错位;每个数字都要能在正文找到;\n"
    "3. data 优先摘录样本量、数据来源、实验条件的原句;不得换算或补算;\n"
    "4. 不要输出 JSON 以外的任何内容。"
)


def _parse_json(text: str) -> dict:
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.IGNORECASE)
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("模型未返回 JSON")
    data = json.loads(cleaned[start:end + 1])
    if not isinstance(data, dict):
        raise ValueError("模型返回的不是对象")
    return data


def _doc_meta(uid: str, doc_id: str) -> dict | None:
    conn = rc._connect(uid)
    try:
        row = conn.execute(
            "SELECT id, name, title, authors, year, venue, pages FROM docs"
            " WHERE id = ? AND deleted_at IS NULL",
            (doc_id,)).fetchone()
        return {
            "id": row[0], "name": row[1], "title": row[2] or row[1],
            "authors": row[3] or "", "year": row[4], "venue": row[5] or "",
            "pages": row[6] or 1,
        } if row else None
    finally:
        conn.close()


def _excerpt(uid: str, doc_id: str, limit: int = EXCERPT_CHARS) -> tuple[str, int]:
    """按页序拼正文摘要;返回 (text, first_page)。"""
    conn = rc._connect(uid)
    try:
        rows = conn.execute(
            "SELECT section, page_start, text FROM chunks WHERE doc_id = ?"
            " ORDER BY page_start, rowid", (doc_id,)).fetchall()
    finally:
        conn.close()
    parts: list[str] = []
    size = 0
    first_page = 1
    for i, (section, page, text) in enumerate(rows):
        if i == 0:
            first_page = int(page or 1)
        block = f"[第 {page} 页 · {section}]\n{text}"
        if size + len(block) > limit:
            parts.append(block[:max(0, limit - size)])
            break
        parts.append(block)
        size += len(block)
    return "\n\n".join(parts), first_page


def _clean_fields(data: dict) -> dict:
    out: dict[str, str] = {}
    for key in FIELDS:
        value = re.sub(r"\s+", " ", str(data.get(key) or "")).strip()
        out[key] = value[:FIELD_MAX]
    return out


def _numbers(text: str) -> set[str]:
    out: set[str] = set()
    for match in re.finditer(r"\d+(?:\.\d+)?", text or ""):
        value = match.group()
        if "." in value:
            value = value.rstrip("0").rstrip(".")
        out.add(value)
    return out


def _verify_numbers(fields: dict, text: str) -> str:
    """结果/数据里的数字必须能在原文找到;找不到就明确提示人工核对。"""
    used = _numbers(fields.get("data", "") + " " + fields.get("results", ""))
    missing = sorted(used - _numbers(text))
    if missing:
        preview = "、".join(missing[:3])
        return f"数值 {preview} 未在原文找到,请核对"
    return ""


async def _ask_doc(meta: dict, text: str) -> dict:
    prompt = (
        f"论文标题:{meta['title']}\n作者:{meta['authors']}\n年份:{meta['year'] or ''}\n"
        f"期刊/会议:{meta['venue']}\n\n正文:\n{text}"
    )
    parts: list[str] = []
    async for delta in llm.stream_chat(
            SYSTEM, prompt, role="main", fallback=True, thinking=False):
        parts.append(delta)
    return _clean_fields(_parse_json("".join(parts)))


async def _extract_one(uid: str, doc_id: str) -> tuple[dict, dict, dict, str]:
    meta = await asyncio.to_thread(_doc_meta, uid, doc_id)
    if meta is None:
        raise ValueError("论文不存在或已删除")
    text, first_page = await asyncio.to_thread(_excerpt, uid, doc_id)
    if not text.strip():
        raise ValueError("论文没有可提取的正文")
    fields = await _ask_doc(meta, text)
    source = {
        "docId": doc_id,
        "docName": meta["title"][:200],
        "page": first_page,
        "quote": "",
        "kind": "paper",
    }
    return meta, fields, source, _verify_numbers(fields, text)


async def compare(request: Request) -> JSONResponse:
    rec = require_auth(request)
    uid = str(rec.get("uid") or "")
    if not llm.is_configured():
        raise HTTPException(503, "LLM not configured")
    if not _limiter.allow(uid):
        raise HTTPException(429, "操作过于频繁,请稍后再试")
    body = await read_json_object(request)
    raw_ids = body.get("docIds")
    if not isinstance(raw_ids, list):
        raise HTTPException(400, "缺少 docIds")
    doc_ids: list[str] = []
    for item in raw_ids:
        value = str(item or "").strip()[:64]
        if value and value not in doc_ids:
            doc_ids.append(value)
    if len(doc_ids) < 2:
        raise HTTPException(400, "至少选择 2 篇论文")
    if len(doc_ids) > MAX_DOCS:
        raise HTTPException(400, f"最多对比 {MAX_DOCS} 篇论文")

    rows: list[list[str]] = []
    row_labels: list[str] = []
    row_sources: list[dict] = []
    warnings: list[str] = []
    succeeded = 0
    for doc_id in doc_ids:
        try:
            meta, fields, source, note = await _extract_one(uid, doc_id)
            rows.append([
                meta["title"][:200],
                str(meta["year"] or ""),
                fields["question"],
                fields["method"],
                fields["data"],
                fields["results"],
                fields["limitations"],
                note,
            ])
            row_labels.append(meta["title"][:120])
            row_sources.append(source)
            if note:
                warnings.append(f"{meta['title'][:80]}:{note}")
            if not fields["question"] and not fields["results"]:
                warnings.append(f"{meta['title'][:80]}:正文信息不足,该行需人工核对")
            succeeded += 1
        except Exception as exc:  # noqa: BLE001 单篇失败不拖垮整张表
            rows.append([doc_id, "", "", "", "", "", f"抽取失败:{str(exc)[:120]}", ""])
            row_labels.append(doc_id)
            row_sources.append({})
            warnings.append(f"{doc_id}:{str(exc)[:120]}")
    if not succeeded:
        raise HTTPException(502, "所有论文抽取失败")
    return JSONResponse({
        "title": f"文献对比表 · {succeeded} 篇",
        "columns": [{"key": chr(65 + i), "label": label, "type": "text"}
                    for i, label in enumerate(COLUMNS)],
        "rows": rows,
        "rowLabels": row_labels,
        "rowSources": row_sources,
        "warnings": warnings,
    }, headers={"Cache-Control": "no-store"})
