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
    '"note":""}],'
    '"groups":[["f1"],["f2"]],"master":null,"warnings":[]}\n'
    "规则:\n"
    "1. expr 用变量名书写,不用单元格引用,不要带等号左边;target 是这条公式要计算的量;\n"
    "2. variables 列出 expr 中出现的变量;variableMap 给出变量到表头名称的建议映射,不确定填空;\n"
    "3. 若若干公式互不依赖,分别放入不同的 groups;若一条总公式把若干子公式联系起来,"
    "把总公式 id 填入 master,groups 仍保留子公式分组;\n"
    "4. 图片模糊或公式不完整时写入 warnings,不要猜;\n"
    "5. 不要输出 Markdown 代码块,不要输出 JSON 以外的内容。"
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


def _prompt(columns: list[dict]) -> str:
    labels = [str(c.get("label") or c.get("key") or "") for c in columns][:30]
    return (
        SYSTEM
        + "\n\n当前表格表头(供 variableMap 参考):" + "、".join(labels)
        + "\n请提取图片中的全部公式。"
    )


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
        formulas.append({
            "id": fid,
            "target": target,
            "expr": expr,
            "variables": variables,
            "variableMap": variable_map,
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


def _call_model(images: list[tuple[str, bytes]], columns: list[dict]) -> dict[str, Any]:
    cfg = _cfg()
    if not (cfg["base"] and cfg["key"]):
        raise RuntimeError("视觉模型未配置")
    content: list[dict] = [{"type": "text", "text": _prompt(columns)}]
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


def extract(images: list[tuple[str, bytes]], columns: list[dict]) -> dict[str, Any]:
    return _call_model(images, columns)


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
    try:
        result = await asyncio.to_thread(extract, images, columns)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(502, str(exc)) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(502, f"视觉模型连接失败: {type(exc).__name__}") from exc
    return JSONResponse(result, headers={"Cache-Control": "no-store"})
