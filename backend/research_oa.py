"""合法开放获取地址解析:Unpaywall 优先,OpenAlex 兜底。

只返回 HTTPS 地址与许可信息,不下载内容;
没有配置 Unpaywall email 时不发请求,返回 unknown。
"""
from __future__ import annotations

import os
import time
from urllib.parse import urlparse

import httpx

TIMEOUT = 8.0
_CACHE_TTL = 86400.0
_CACHE_MAX = 512
_CACHE: dict[str, tuple[float, dict]] = {}


def _safe_url(value: object) -> str:
    text = str(value or "").strip()
    try:
        parsed = urlparse(text)
    except ValueError:
        return ""
    if (parsed.scheme != "https" or not parsed.hostname
            or parsed.username or parsed.password
            or any(c.isspace() or ord(c) < 32 for c in text)):
        return ""
    return text[:1000]


def parse_unpaywall(data: dict) -> dict:
    best = data.get("best_oa_location") or {}
    if not isinstance(best, dict):
        best = {}
    url = _safe_url(best.get("url_for_pdf") or best.get("url"))
    return {
        "isOa": bool(data.get("is_oa")) and bool(url),
        "oaStatus": str(data.get("oa_status") or "unknown"),
        "oaUrl": url,
        "license": str(best.get("license") or "")[:120],
        "oaSource": str(best.get("host_type") or "")[:40],
        "version": str(best.get("version") or "")[:40],
    }


def parse_openalex(data: dict) -> dict:
    best = data.get("best_oa_location") or {}
    if not isinstance(best, dict):
        best = {}
    open_access = data.get("open_access") or {}
    if not isinstance(open_access, dict):
        open_access = {}
    url = _safe_url(best.get("pdf_url") or best.get("url_for_pdf") or best.get("landing_page_url"))
    status = str(data.get("oa_status") or open_access.get("oa_status") or "unknown")
    is_oa = bool(data.get("is_oa") or open_access.get("is_oa") or best.get("is_oa"))
    return {
        "isOa": is_oa and bool(url),
        "oaStatus": status,
        "oaUrl": url,
        "license": str(best.get("license") or "")[:120],
        "oaSource": str((best.get("source") or {}).get("type") or "")[:40]
        if isinstance(best.get("source"), dict) else "",
        "version": str(best.get("version") or "")[:40],
    }


def _remember(doi: str, value: dict) -> None:
    if not doi:
        return
    _CACHE[doi] = (time.monotonic(), dict(value))
    if len(_CACHE) > _CACHE_MAX:
        oldest = min(_CACHE, key=lambda key: _CACHE[key][0])
        _CACHE.pop(oldest, None)


async def resolve_doi(client: httpx.AsyncClient, doi: str) -> dict:
    doi = str(doi or "").strip().lower()
    cached = _CACHE.get(doi)
    if cached and time.monotonic() - cached[0] < _CACHE_TTL:
        return dict(cached[1])
    email = os.getenv("MG_UNPAYWALL_EMAIL", "").strip()
    had_error = False
    fallback: dict | None = None
    if email and doi:
        try:
            res = await client.get(
                f"https://api.unpaywall.org/v2/{doi}",
                params={"email": email}, timeout=TIMEOUT)
            if res.status_code == 200:
                parsed = parse_unpaywall(res.json())
                parsed["resolver"] = "unpaywall"
                parsed["error"] = False
                if parsed["isOa"]:
                    _remember(doi, parsed)
                    return parsed
                fallback = parsed
            elif res.status_code != 404:
                had_error = True
        except (httpx.HTTPError, ValueError):
            had_error = True
    if doi:
        try:
            params = {}
            key = os.getenv("MG_OPENALEX_API_KEY", "").strip()
            if key:
                params["api_key"] = key
            res = await client.get(
                f"https://api.openalex.org/works/doi:{doi}",
                params=params or None, timeout=TIMEOUT)
            if res.status_code == 200:
                parsed = parse_openalex(res.json())
                parsed["resolver"] = "openalex"
                parsed["error"] = False
                if parsed["isOa"]:
                    _remember(doi, parsed)
                    return parsed
                fallback = fallback or parsed
            elif res.status_code != 404:
                had_error = True
        except (httpx.HTTPError, ValueError):
            had_error = True
    result = fallback or {
        "isOa": False, "oaStatus": "unknown", "oaUrl": "",
        "license": "", "oaSource": "", "version": "", "resolver": "",
    }
    result["error"] = bool(had_error and fallback is None)
    if not result["error"]:
        _remember(doi, result)
    return result
