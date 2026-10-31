"""
科研公式图片识别:调用 OpenAI 兼容的多模态模型,把照片里的公式整理成结构化结果。

配置(缺省复用阿里云文本模型地址/Key):
    MG_VISION_BASE_URL / MG_VISION_API_KEY / MG_VISION_MODEL
未设置时回退到 MG_ALIYUN_BASE_URL / MG_ALIYUN_API_KEY,模型默认 qwen3.8-omni-flash。
(实测该账号 qwen3-vl-plus / qwen-vl-ocr 返回 403 未开通;omni 系列可调用。)

约束:
- 图片只在内存中编码为 data URI,不落盘;
- 模型不计算,只负责识别与结构化;
- 返回结果必须经前端确认变量到列的映射后才会写入表格;
- 独立公式组返回 groups;若存在总公式,返回 master,由前端直接采用。
"""
from __future__ import annotations

import asyncio
import base64
import json
import os
import re
from typing import Any

import httpx
from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import JSONResponse

from auth import require_auth
from http_utils import read_json_object
from rate_limit import SlidingWindowLimiter
import research_corpus as rc

MAX_IMAGES = 4
MAX_IMAGE_BYTES = 8 * 1024 * 1024
MAX_TOTAL_BYTES = 20 * 1024 * 1024
MAX_FORMULAS = 20
TIMEOUT = 90.0

_ALLOWED_MIME = {"image/png", "image/jpeg", "image/webp", "image/gif"}
_limiter = SlidingWindowLimiter(10, 300)  # 每用户 5 分钟最多 10 次识别

SYSTEM = (
    "你是实验数据公式提取器。读取用户提供的图片,提取其中所有计算公式,"
    "并判断它们之间的关系。只输出 JSON,不要解释。\n"
    "输出格式:\n"
    '{"formulas":[{"id":"f1","target":"速度","expr":"位移/时间",'
    '"variables":["位移","时间"],"variableMap":{"位移":"位移","时间":"时间"},'
    '"handwriting":false,"confidence":0.0,"note":""}],'
    '"groups":[["f1"],["f2"]],"master":null,"warnings":[]}\n'
    "规则:\n"
    "1. expr 用变量名书写,不用单元格引用,不要带等号左边;target 是这条公式要计算的量;\n"
    "2. variables 列出 expr 中出现的变量;variableMap 给出变量到表头名称的建议映射,不确定填空;\n"
    "3. 若若干公式互不依赖,分别放入不同的 groups;若一条总公式把若干子公式联系起来,"
    "把总公式 id 填入 master,groups 仍保留子公式分组;\n"
    "4. 图片模糊或公式不完整时写入 warnings,不要猜;每条形如 handwriting 标明是否手写,"
    "confidence 填 0 到 1 的识别置信度;\n"
    "5. 不要输出 Markdown 代码块,不要输出 JSON 以外的内容;\n"
    "6. 若同时提供页面文字,用其中的变量定义、单位与实验对象补全 variableMap 和 note,"
    "忽略与公式无关的段落,不要从文字中臆造公式。"
)


def _cfg() -> dict[str, str]:
    return {
        "base": (os.getenv("MG_VISION_BASE_URL", "")
                 or os.getenv("MG_ALIYUN_BASE_URL", "")).rstrip("/"),
        "key": os.getenv("MG_VISION_API_KEY", "") or os.getenv("MG_ALIYUN_API_KEY", ""),
        "model": os.getenv("MG_VISION_MODEL", "") or "qwen3.8-omni-flash",
    }


def is_configured() -> bool:
    cfg = _cfg()
    return bool(cfg["base"] and cfg["key"] and cfg["model"])


def _prompt(columns: list[dict], context: str = "") -> str:
    labels = [str(c.get("label") or c.get("key") or "") for c in columns][:30]
    prompt = (
        SYSTEM
        + "\n\n当前表格表头(供 variableMap 参考):" + "、".join(labels)
        + "\n请提取图片中的全部公式。"
    )
    if context.strip():
        prompt += (
            "\n\n页面文字说明(用于确定变量含义、单位、适用实验对象;"
            "忽略与本页公式无关的段落):\n"
            + context.strip()[:8000]
        )
    return prompt


def _parse_json(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", cleaned, flags=re.IGNORECASE)
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("模型未返回 JSON")
    data = json.loads(cleaned[start:end + 1])
    if not isinstance(data, dict):
        raise ValueError("模型返回的不是对象")
    return data


def _clean_result(data: dict[str, Any]) -> dict[str, Any]:
    formulas: list[dict] = []
    ids: set[str] = set()
    raw = data.get("formulas")
    if not isinstance(raw, list):
        raise ValueError("缺少 formulas")
    for i, item in enumerate(raw[:MAX_FORMULAS], 1):
        if not isinstance(item, dict):
            continue
        fid = str(item.get("id") or f"f{i}")[:40]
        if fid in ids:
            fid = f"{fid}-{i}"
        expr = str(item.get("expr") or "").strip().lstrip("=")[:300]
        target = str(item.get("target") or "").strip()[:60]
        if not expr or not target:
            continue
        variables = item.get("variables")
        variables = [str(v)[:40] for v in variables if isinstance(v, (str, int, float))][:10] \
            if isinstance(variables, list) else []
        vmap = item.get("variableMap")
        variable_map = {
            str(k)[:40]: str(v)[:60]
            for k, v in (vmap.items() if isinstance(vmap, dict) else [])
            if isinstance(k, (str, int, float)) and isinstance(v, str)
        }
        try:
            confidence = float(item.get("confidence") or 0)
        except (TypeError, ValueError):
            confidence = 0.0
        formulas.append({
            "id": fid,
            "target": target,
            "expr": expr,
            "variables": variables,
            "variableMap": variable_map,
            "handwriting": bool(item.get("handwriting")),
            "confidence": max(0.0, min(1.0, confidence)),
            "note": str(item.get("note") or "")[:200],
        })
        ids.add(fid)
    if not formulas:
        raise ValueError("图片里没有识别到可用公式")

    groups_raw = data.get("groups")
    groups: list[list[str]] = []
    if isinstance(groups_raw, list):
        for group in groups_raw:
            if not isinstance(group, list):
                continue
            clean_group = [str(g) for g in group if str(g) in ids]
            if clean_group:
                groups.append(clean_group)
    covered = {g for group in groups for g in group}
    for fid in ids - covered:
        groups.append([fid])
    if not groups:
        groups = [[f["id"] for f in formulas]]

    master = data.get("master")
    master = str(master) if isinstance(master, str) and master in ids else None
    warnings = data.get("warnings")
    warnings = [str(w)[:200] for w in warnings][:10] if isinstance(warnings, list) else []
    return {"formulas": formulas, "groups": groups, "master": master, "warnings": warnings}


def _call_model(images: list[tuple[str, bytes]], columns: list[dict],
                context: str = "") -> dict[str, Any]:
    cfg = _cfg()
    if not (cfg["base"] and cfg["key"]):
        raise RuntimeError("视觉模型未配置")
    content: list[dict] = [{"type": "text", "text": _prompt(columns, context)}]
    for mime, data in images:
        uri = f"data:{mime};base64,{base64.b64encode(data).decode('ascii')}"
        content.append({"type": "image_url", "image_url": {"url": uri}})
    payload = {
        "model": cfg["model"],
        "messages": [{"role": "user", "content": content}],
        "temperature": 0,
    }
    resp = httpx.post(
        cfg["base"] + "/chat/completions",
        headers={"Authorization": f"Bearer {cfg['key']}", "Content-Type": "application/json"},
        json=payload,
        timeout=TIMEOUT,
    )
    if resp.status_code != 200:
        raise RuntimeError(f"视觉模型返回 HTTP {resp.status_code}: {resp.text[:200]}")
    body = resp.json()
    try:
        message = body["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise RuntimeError("视觉模型返回格式异常") from exc
    if isinstance(message, list):
        text = "".join(
            part.get("text", "") for part in message
            if isinstance(part, dict) and isinstance(part.get("text"), str)
        )
    else:
        text = str(message)
    return _clean_result(_parse_json(text))


def explain_image(mime: str, data: bytes, question: str) -> str:
    """解释论文中的图表/公式截图;只依据图片,不给无依据数值。"""
    if mime not in _ALLOWED_MIME:
        raise ValueError("不支持的图片类型")
    if not data or len(data) > MAX_IMAGE_BYTES:
        raise ValueError("图片为空或超过 8MB")
    cfg = _cfg()
    if not (cfg["base"] and cfg["key"]):
        raise RuntimeError("视觉模型未配置")
    uri = f"data:{mime};base64,{base64.b64encode(data).decode('ascii')}"
    prompt = question.strip()[:1000] or "解释这张图表或公式的含义、变量和结论。"
    system = (
        "你是学术论文阅读助手。只依据用户给的截图回答,解释图表/公式的含义、"
        "坐标轴、变量与结论。看不清或信息不足时明确说明,不要猜测具体数值;"
        "数值以论文原文为准。用简洁的中文回答,必要时分点。"
    )
    payload = {
        "model": cfg["model"],
        "messages": [{
            "role": "user",
            "content": [
                {"type": "text", "text": f"{system}\n\n问题: {prompt}"},
                {"type": "image_url", "image_url": {"url": uri}},
            ],
        }],
        "temperature": 0.2,
    }
    resp = httpx.post(
        cfg["base"] + "/chat/completions",
        headers={"Authorization": f"Bearer {cfg['key']}", "Content-Type": "application/json"},
        json=payload,
        timeout=TIMEOUT,
    )
    if resp.status_code != 200:
        raise RuntimeError(f"视觉模型返回 HTTP {resp.status_code}: {resp.text[:200]}")
    body = resp.json()
    try:
        message = body["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise RuntimeError("视觉模型返回格式异常") from exc
    if isinstance(message, list):
        text = "".join(
            part.get("text", "") for part in message
            if isinstance(part, dict) and isinstance(part.get("text"), str)
        )
    else:
        text = str(message)
    return text.strip()[:4000]


TABLE_SYSTEM = (
    "你是学术论文表格转录器。读取用户框选的论文表格截图,把它完整转录为结构化 JSON。"
    "只输出 JSON,不要解释,不要输出 Markdown 代码块。\n"
    "输出格式:\n"
    '{"title":"表格标题","columns":["列1","列2"],"rows":[["单元格","单元格"]],'
    '"notes":"表注/单位/条件",'
    '"handwriting":{"detected":false,"cells":[[行下标,列下标]],"note":""},'
    '"warnings":[]}\n'
    "规则:\n"
    "1. 严格按截图逐格转录,数字、小数点、正负号、单位保持原样,不做换算,不补算缺失值;\n"
    "2. 第一行表头放入 columns;数据行放入 rows;合并单元格在覆盖位置留空字符串;\n"
    "3. 看不清的单元格留空,并在 warnings 里说明,不要猜测;\n"
    "4. 只转录一张表;若截图里有多张,转录最完整的一张并写入 warnings;\n"
    "5. 最多 30 列、200 行,超出部分截断;\n"
    "6. 判断单元格是印刷还是手写。若存在手写实验数据,把 detected 设为 true,"
    "cells 填入手写单元格的 [数据行下标, 列下标](都从 0 开始),note 简要说明;"
    "单元格类型不确定时不要标成手写。"
)


def _chat_text(cfg: dict[str, str], prompt: str, mime: str, data: bytes,
               temperature: float = 0.0) -> str:
    uri = f"data:{mime};base64,{base64.b64encode(data).decode('ascii')}"
    payload = {
        "model": cfg["model"],
        "messages": [{
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": uri}},
            ],
        }],
        "temperature": temperature,
    }
    resp = httpx.post(
        cfg["base"] + "/chat/completions",
        headers={"Authorization": f"Bearer {cfg['key']}", "Content-Type": "application/json"},
        json=payload,
        timeout=TIMEOUT,
    )
    if resp.status_code != 200:
        raise RuntimeError(f"视觉模型返回 HTTP {resp.status_code}: {resp.text[:200]}")
    body = resp.json()
    try:
        message = body["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise RuntimeError("视觉模型返回格式异常") from exc
    if isinstance(message, list):
        return "".join(
            part.get("text", "") for part in message
            if isinstance(part, dict) and isinstance(part.get("text"), str)
        )
    return str(message)


def _clean_table_result(raw: dict[str, Any]) -> dict[str, Any]:
    title = str(raw.get("title") or "论文表格").strip()[:120]
    warnings = raw.get("warnings")
    warnings = [str(w)[:200] for w in warnings][:10] if isinstance(warnings, list) else []

    rows_raw = raw.get("rows")
    if not isinstance(rows_raw, list):
        raise ValueError("模型未返回 rows")
    rows: list[list[str]] = []
    for item in rows_raw[:200]:
        if not isinstance(item, list):
            continue
        rows.append(["" if v is None else str(v).strip()[:200] for v in item[:30]])
    if not rows:
        raise ValueError("没有识别到表格数据")

    cols_raw = raw.get("columns")
    columns = ([str(v).strip()[:60] for v in cols_raw[:30]]
               if isinstance(cols_raw, list) else [])
    width = max(len(r) for r in rows)
    width = max(width, len(columns))
    if not columns and len(rows) > 1:
        # 模型漏给表头:首行全为文本时按表头处理,避免把表头当数据
        first = rows[0]
        if all(v and not _looks_numeric(v) for v in first):
            columns = first
            rows = rows[1:]
    while len(columns) < width:
        columns.append(f"列{len(columns) + 1}")
    columns = columns[:30]
    width = min(len(columns), 30)
    padded: list[list[str]] = []
    for row in rows[:200]:
        out = (row + [""] * width)[:width]
        padded.append(out)
    if not padded:
        raise ValueError("没有识别到表格数据")
    if len(rows_raw) > 200 or any(len(r) > 30 for r in rows_raw if isinstance(r, list)):
        warnings.append("表格过大,已按 30 列 / 200 行截断")
    notes = str(raw.get("notes") or "").strip()[:500]
    hw_raw = raw.get("handwriting")
    hw_raw = hw_raw if isinstance(hw_raw, dict) else {}
    hw_cells: list[list[int]] = []
    raw_cells = hw_raw.get("cells")
    invalid_cells = any(not isinstance(row, list) for row in rows_raw[:200])
    if isinstance(raw_cells, list):
        invalid_cells = invalid_cells or len(raw_cells) > 400
        for pair in raw_cells[:400]:
            if (not isinstance(pair, list) or len(pair) != 2
                    or any(type(index) is not int for index in pair)
                    or not (0 <= pair[0] < len(padded) and 0 <= pair[1] < width)):
                invalid_cells = True
                break
            hw_cells.append(pair)
    elif raw_cells is not None:
        invalid_cells = True
    detected = (hw_raw.get("detected") is True or raw.get("hasHandwriting") is True
                or bool(raw_cells))
    if invalid_cells:
        hw_cells = []
    if detected and not hw_cells:
        warnings.append("检测到手写数据,但未定位到具体单元格,请逐格核对")
    handwriting = {
        "detected": detected,
        "cells": hw_cells,
        "note": str(hw_raw.get("note") or "").strip()[:300],
    }
    return {
        "title": title,
        "columns": columns,
        "rows": padded,
        "notes": notes,
        "handwriting": handwriting,
        "warnings": warnings,
    }


def _looks_numeric(text: str) -> bool:
    try:
        float(text.replace(",", "").replace("%", "").strip())
        return True
    except ValueError:
        return False


def extract_table(mime: str, data: bytes) -> dict[str, Any]:
    """论文表格截图 → 结构化表格;只转录,不做数值推断。"""
    if mime not in _ALLOWED_MIME:
        raise ValueError("不支持的图片类型")
    if not data or len(data) > MAX_IMAGE_BYTES:
        raise ValueError("图片为空或超过 8MB")
    cfg = _cfg()
    if not (cfg["base"] and cfg["key"]):
        raise RuntimeError("视觉模型未配置")
    text = _chat_text(cfg, TABLE_SYSTEM + "\n请转录这张表。", mime, data)
    return _clean_table_result(_parse_json(text))


def _decode_image(item: object) -> tuple[str, bytes]:
    if not isinstance(item, dict):
        raise ValueError("图片格式错误")
    mime = str(item.get("mime") or "").lower()
    if mime not in _ALLOWED_MIME:
        raise ValueError(f"不支持的图片类型: {mime or 'unknown'}")
    raw = str(item.get("data") or "")
    try:
        data = base64.b64decode(raw, validate=True)
    except Exception as exc:  # noqa: BLE001
        raise ValueError("图片 base64 解码失败") from exc
    if not data or len(data) > MAX_IMAGE_BYTES:
        raise ValueError("单张图片超过 8MB 或为空")
    return mime, data


def extract(images: list[tuple[str, bytes]], columns: list[dict],
            context: str = "") -> dict[str, Any]:
    return _call_model(images, columns, context)


async def extract_formulas(request: Request) -> JSONResponse:
    rec = require_auth(request)
    uid = str(rec.get("uid") or "")
    if not _limiter.allow(uid):
        raise HTTPException(429, "too many requests")
    if not is_configured():
        raise HTTPException(503, "vision model not configured")
    body = await read_json_object(request)
    raw_images = body.get("images")
    if not isinstance(raw_images, list) or not raw_images:
        raise HTTPException(400, "images required")
    if len(raw_images) > MAX_IMAGES:
        raise HTTPException(400, f"最多上传 {MAX_IMAGES} 张图片")
    try:
        images = [_decode_image(item) for item in raw_images]
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    if sum(len(data) for _, data in images) > MAX_TOTAL_BYTES:
        raise HTTPException(413, "图片总大小超过 20MB")
    columns = body.get("columns")
    columns = columns if isinstance(columns, list) else []
    context = body.get("text")
    context = context[:8000] if isinstance(context, str) else ""
    doc_id = body.get("docId") if isinstance(body.get("docId"), str) else ""
    table_id = body.get("tableId") if isinstance(body.get("tableId"), str) else ""
    doc_id = doc_id[:64]
    table_id = table_id[:64]
    try:
        page = int(body.get("page") or 0)
    except (TypeError, ValueError):
        page = 0
    if doc_id:
        try:
            doc = await asyncio.to_thread(rc._doc_row, uid, doc_id)
            if doc is None or doc["deletedAt"]:
                doc_id = ""
        except Exception:  # noqa: BLE001 文档校验失败不影响识别
            doc_id = ""
    try:
        result = await asyncio.to_thread(extract, images, columns, context)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(502, str(exc)) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(502, f"视觉模型连接失败: {type(exc).__name__}") from exc
    saved = 0
    blocks = 0
    if doc_id or table_id:
        try:
            saved = await asyncio.to_thread(
                rc._save_extracted_formulas, uid, doc_id, table_id,
                result.get("formulas") or [])
        except Exception as exc:  # noqa: BLE001 公式库写入失败不影响本次识别
            print(f"[vision] 公式候选保存失败(忽略): {exc}")
    if doc_id:
        try:
            blocks = await asyncio.to_thread(
                rc._save_source_blocks, uid, doc_id, page,
                result.get("formulas") or [])
        except Exception as exc:  # noqa: BLE001 区块写入失败不影响本次识别
            print(f"[vision] 公式来源区块保存失败(忽略): {exc}")
    return JSONResponse({**result, "saved": saved, "blocks": blocks},
                        headers={"Cache-Control": "no-store"})
