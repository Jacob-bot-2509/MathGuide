"""
科研文献发现:跨库检索已发表论文的元数据与摘要。

只返回元数据/摘要与原文链接,不抓取或转存付费全文;
用户自行上传的论文仍走 research_corpus 的本地语料库。

数据源:
- Crossref(DOI 权威元数据,免 key)
- arXiv(预印本,免 key)
- Europe PMC(生命科学,免 key)
- OpenAlex(引用图,需免费 key:MG_OPENALEX_API_KEY)
- Semantic Scholar(可选 key:MG_S2_API_KEY)
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import shutil
import time
from pathlib import Path
from urllib.parse import urlparse
from xml.etree import ElementTree

import httpx
from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import JSONResponse

import research_corpus as rc
from auth import require_auth
from http_utils import read_json_object
from rate_limit import SlidingWindowLimiter
from research_tables import _open_in_office, _print_allowed

TIMEOUT = 10.0
DEADLINE = 8.0
MAX_RESULTS = 20
_limiter = SlidingWindowLimiter(20, 60)

_ATOM = "{http://www.w3.org/2005/Atom}"
_ARXIV = "{http://arxiv.org/schemas/atom}"


def _clean(text: str | None, limit: int = 1200) -> str:
    if not text:
        return ""
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit]


def _doi(raw: str | None) -> str:
    value = (raw or "").strip().lower()
    value = re.sub(r"^https?://(dx\.)?doi\.org/", "", value)
    value = re.sub(r"^doi:\s*", "", value)
    return value[:200]


def _result(**kwargs) -> dict:
    return {
        "title": "", "authors": "", "year": 0, "venue": "", "doi": "",
        "url": "", "pdfUrl": "", "abstract": "", "citations": 0, "sources": [],
        **kwargs,
    }


async def _crossref(client: httpx.AsyncClient, query: str, limit: int) -> list[dict]:
    params = {
        "query.bibliographic": query, "rows": limit,
        "select": "DOI,title,author,issued,container-title,abstract,"
                  "is-referenced-by-count,URL,type",
    }
    mailto = os.getenv("MG_LITERATURE_MAILTO", "").strip()
    if mailto:
        params["mailto"] = mailto
    res = await client.get("https://api.crossref.org/works", params=params)
    res.raise_for_status()
    items = res.json().get("message", {}).get("items", [])
    out = []
    for item in items:
        if item.get("type") in {"component", "dataset"}:
            continue
        title = _clean((item.get("title") or [""])[0], 300)
        if not title:
            continue
        authors = ", ".join(
            a.get("family") or a.get("name") or "" for a in item.get("author", []))
        issued = item.get("issued", {}).get("date-parts") or [[0]]
        year = issued[0][0] if issued and issued[0] else 0
        doi = _doi(item.get("DOI"))
        out.append(_result(
            title=title, authors=authors[:300], year=year,
            venue=_clean((item.get("container-title") or [""])[0], 160),
            doi=doi, url=item.get("URL") or (f"https://doi.org/{doi}" if doi else ""),
            abstract=_clean(item.get("abstract")),
            citations=int(item.get("is-referenced-by-count") or 0),
            sources=["crossref"],
        ))
    return out


async def _arxiv(client: httpx.AsyncClient, query: str, limit: int) -> list[dict]:
    res = await client.get(
        "https://export.arxiv.org/api/query",
        params={"search_query": f"all:{query}", "max_results": limit},
    )
    res.raise_for_status()
    root = ElementTree.fromstring(res.text)
    out = []
    for entry in root.findall(f"{_ATOM}entry"):
        title = _clean(entry.findtext(f"{_ATOM}title"), 300)
        if not title:
            continue
        authors = ", ".join(
            name.text or "" for name in entry.findall(f"{_ATOM}author/{_ATOM}name"))
        published = entry.findtext(f"{_ATOM}published") or ""
        year = int(published[:4]) if published[:4].isdigit() else 0
        link = ""
        for candidate in entry.findall(f"{_ATOM}link"):
            if candidate.get("rel") == "alternate":
                link = candidate.get("href") or ""
                break
        if not link:
            link = _clean(entry.findtext(f"{_ATOM}id"), 300)
        pdf_url = ""
        if "arxiv.org/abs/" in link:
            pdf_url = link.replace("/abs/", "/pdf/").replace("http://", "https://", 1)
            if not pdf_url.endswith(".pdf"):
                pdf_url += ".pdf"
        out.append(_result(
            title=title, authors=authors[:300], year=year, venue="arXiv",
            doi=_doi(entry.findtext(f"{_ARXIV}doi")), url=link,
            pdfUrl=pdf_url,
            abstract=_clean(entry.findtext(f"{_ATOM}summary")),
            sources=["arxiv"],
        ))
    return out


async def _europe_pmc(client: httpx.AsyncClient, query: str, limit: int,
                      title_only: bool = False) -> list[dict]:
    search = f'TITLE:"{query[:150]}"' if title_only else query
    res = await client.get(
        "https://www.ebi.ac.uk/europepmc/webservices/rest/search",
        params={"query": search, "format": "json", "pageSize": limit,
                "resultType": "core"},
    )
    res.raise_for_status()
    items = res.json().get("resultList", {}).get("result", [])
    out = []
    for item in items:
        title = _clean(item.get("title"), 300)
        if not title:
            continue
        doi = _doi(item.get("doi"))
        url = (f"https://europepmc.org/article/{item.get('source')}/{item.get('id')}"
               if item.get("source") and item.get("id") else
               (f"https://doi.org/{doi}" if doi else ""))
        year = item.get("pubYear")
        out.append(_result(
            title=title, authors=_clean(item.get("authorString"), 300),
            year=int(year) if str(year).isdigit() else 0,
            venue=_clean(item.get("journalTitle"), 160),
            doi=doi, url=url,
            abstract=_clean(item.get("abstractText")),
            citations=int(item.get("citedByCount") or 0),
            sources=["europepmc"],
        ))
    return out


def _openalex_abstract(item: dict) -> str:
    inverted = item.get("abstract_inverted_index") or {}
    if not isinstance(inverted, dict):
        return ""
    positions: dict[int, str] = {}
    for word, indexes in inverted.items():
        if not isinstance(indexes, list):
            continue
        for index in indexes:
            if isinstance(index, int):
                positions[index] = str(word)
    return " ".join(positions[i] for i in sorted(positions))[:1200]


async def _openalex(client: httpx.AsyncClient, query: str, limit: int) -> list[dict]:
    key = os.getenv("MG_OPENALEX_API_KEY", "").strip()
    if not key:
        return []
    res = await client.get(
        "https://api.openalex.org/works",
        params={"search": query, "per-page": limit, "api_key": key,
                "select": "id,doi,title,publication_year,authorships,"
                          "primary_location,abstract_inverted_index,"
                          "cited_by_count"},
    )
    res.raise_for_status()
    out = []
    for item in res.json().get("results", []):
        title = _clean(item.get("title"), 300)
        if not title:
            continue
        authors = ", ".join(
            str((a.get("author") or {}).get("display_name") or "")
            for a in item.get("authorships", []))[:300]
        location = item.get("primary_location") or {}
        venue = ((location.get("source") or {}).get("display_name") or "")
        doi = _doi(item.get("doi"))
        out.append(_result(
            title=title, authors=authors, year=item.get("publication_year") or 0,
            venue=_clean(venue, 160), doi=doi,
            url=item.get("doi") or location.get("landing_page_url") or "",
            abstract=_openalex_abstract(item),
            citations=int(item.get("cited_by_count") or 0),
            sources=["openalex"],
        ))
    return out


async def _semantic_scholar(client: httpx.AsyncClient, query: str, limit: int) -> list[dict]:
    key = os.getenv("MG_S2_API_KEY", "").strip()
    if not key:
        return []
    res = await client.get(
        "https://api.semanticscholar.org/graph/v1/paper/search",
        params={"query": query, "limit": limit,
                "fields": "title,abstract,year,venue,authors,externalIds,"
                          "url,citationCount"},
        headers={"x-api-key": key},
    )
    res.raise_for_status()
    out = []
    for item in res.json().get("data", []):
        title = _clean(item.get("title"), 300)
        if not title:
            continue
        out.append(_result(
            title=title,
            authors=", ".join(a.get("name") or "" for a in item.get("authors", []))[:300],
            year=item.get("year") or 0, venue=_clean(item.get("venue"), 160),
            doi=_doi((item.get("externalIds") or {}).get("DOI")),
            url=item.get("url") or "",
            abstract=_clean(item.get("abstract")),
            citations=int(item.get("citationCount") or 0),
            sources=["semanticscholar"],
        ))
    return out


def _merge(results: list[dict]) -> list[dict]:
    merged: dict[str, dict] = {}
    for item in results:
        key = item["doi"] or re.sub(r"\W+", "", item["title"].lower())[:120]
        current = merged.get(key)
        if current is None:
            merged[key] = item
            continue
        current["sources"] = sorted(set(current["sources"]) | set(item["sources"]))
        for field in ("abstract", "authors", "year", "venue", "url", "pdfUrl"):
            if field == "pdfUrl":
                if item.get(field) and not current.get(field):
                    current[field] = item[field]
                continue
            if len(str(item.get(field) or "")) > len(str(current.get(field) or "")):
                current[field] = item[field]
        current["citations"] = max(current["citations"], item["citations"])
    items = list(merged.values())
    items.sort(key=lambda x: (-x["citations"], -int(x["year"] or 0)))
    return items


async def _run_providers(client: httpx.AsyncClient, providers, query: str,
                         limit: int) -> list[tuple[str, object]]:
    """并行检索;超过 DEADLINE 的慢源直接取消,不让一个源拖住整页。"""
    tasks = {
        asyncio.create_task(fn(client, query, limit)): name
        for name, fn in providers
    }
    done, pending = await asyncio.wait(tasks, timeout=DEADLINE)
    for task in pending:
        task.cancel()
    outcomes: list[tuple[str, object]] = []
    for task in done:
        name = tasks[task]
        try:
            outcomes.append((name, task.result()))
        except Exception as exc:  # noqa: BLE001
            outcomes.append((name, exc))
    for task in pending:
        outcomes.append((tasks[task], TimeoutError()))
    outcomes.sort(key=lambda item: item[0])
    return outcomes


async def search(request: Request) -> JSONResponse:
    rec = require_auth(request)
    uid = str(rec.get("uid") or "")
    query = (request.query_params.get("q") or "").strip()
    if len(query) < 2:
        raise HTTPException(400, "检索词至少 2 个字符")
    if len(query) > 200:
        raise HTTPException(400, "检索词过长")
    try:
        limit = int(request.query_params.get("limit") or 10)
    except ValueError:
        limit = 10
    limit = max(1, min(MAX_RESULTS, limit))
    if not _limiter.allow(uid):
        raise HTTPException(429, "检索过于频繁,请稍后再试")

    providers = [
        ("crossref", _crossref),
        ("arxiv", _arxiv),
        ("europepmc", _europe_pmc),
        ("openalex", _openalex),
        ("semanticscholar", _semantic_scholar),
    ]
    warnings: list[str] = []
    gathered: list[dict] = []
    async with httpx.AsyncClient(timeout=TIMEOUT, follow_redirects=True,
                                 headers={"User-Agent": "MathGuide/1.10 "
                                          "(research literature search)"}) as client:
        outcomes = await _run_providers(client, providers, query, limit)
    for name, outcome in outcomes:
        if isinstance(outcome, Exception):
            warnings.append(f"{name}: {type(outcome).__name__}")
            continue
        gathered.extend(outcome)  # type: ignore[arg-type]

    results = _merge(gathered)[:limit]
    return JSONResponse({"query": query, "results": results, "warnings": warnings})


async def related(request: Request) -> JSONResponse:
    """以 DOI/标题为种子找相关论文:Crossref 参考文献 + 各库相似检索。"""
    rec = require_auth(request)
    uid = str(rec.get("uid") or "")
    doi = _doi(request.query_params.get("doi"))
    title = (request.query_params.get("title") or "").strip()
    if not doi and len(title) < 4:
        raise HTTPException(400, "需要 DOI 或论文标题")
    if not _limiter.allow(uid):
        raise HTTPException(429, "检索过于频繁,请稍后再试")

    warnings: list[str] = []
    items: list[dict] = []
    query = title or doi
    async with httpx.AsyncClient(timeout=TIMEOUT, follow_redirects=True,
                                 headers={"User-Agent": "MathGuide/1.10 "
                                          "(research literature related)"}) as client:
        if doi:
            try:
                res = await client.get(f"https://api.crossref.org/works/{doi}")
                res.raise_for_status()
                for ref in res.json().get("message", {}).get("reference", [])[:20]:
                    ref_doi = _doi(ref.get("DOI"))
                    ref_title = _clean(ref.get("article-title") or ref.get("unstructured"), 300)
                    if not ref_title and not ref_doi:
                        continue
                    items.append(_result(
                        title=ref_title or ref_doi,
                        authors=_clean(ref.get("author"), 300),
                        year=int(ref.get("year")) if str(ref.get("year")).isdigit() else 0,
                        venue=_clean(ref.get("journal-title"), 160),
                        doi=ref_doi,
                        url=f"https://doi.org/{ref_doi}" if ref_doi else "",
                        sources=["crossref-reference"],
                    ))
            except Exception as exc:  # noqa: BLE001
                warnings.append(f"crossref-reference: {type(exc).__name__}")
        try:
            async def epmc_title(c: httpx.AsyncClient, q: str, n: int) -> list[dict]:
                return await _europe_pmc(c, q, n, title_only=True)

            outcomes = await _run_providers(client, [
                ("crossref", _crossref),
                ("arxiv", _arxiv),
                ("europepmc", epmc_title),
                ("openalex", _openalex),
            ], query, 10)
        except Exception:  # noqa: BLE001
            outcomes = []
    for name, outcome in outcomes:
        if isinstance(outcome, Exception):
            warnings.append(f"{name}: {type(outcome).__name__}")
            continue
        items.extend(outcome)  # type: ignore[arg-type]
    norm_query = re.sub(r"\W+", "", query.lower())
    items = [
        i for i in _merge(items)
        if (not doi or i["doi"] != doi)
        and re.sub(r"\W+", "", i["title"].lower()) != norm_query
    ][:20]
    return JSONResponse({"query": query, "results": items, "warnings": warnings})


# ---------- 打开开放获取 PDF ----------

# 只允许从开放获取来源下载,避免把任意 URL 变成服务端请求(SSRF)
_PDF_HOSTS = (
    "arxiv.org",
    "europepmc.org",
    "ebi.ac.uk",
    "ncbi.nlm.nih.gov",
)


def _pdf_url_allowed(url: str) -> bool:
    try:
        parsed = urlparse(url)
    except ValueError:
        return False
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or not host:
        return False
    return any(host == suffix or host.endswith("." + suffix) for suffix in _PDF_HOSTS)


async def _download_pdf(client: httpx.AsyncClient, url: str) -> bytes:
    from urllib.parse import urljoin

    for _ in range(3):
        if not _pdf_url_allowed(url):
            raise ValueError("不允许的 PDF 地址")
        async with client.stream("GET", url, follow_redirects=False) as res:
            if res.status_code in (301, 302, 303, 307, 308):
                url = urljoin(url, res.headers.get("location") or "")
                continue
            res.raise_for_status()
            chunks: list[bytes] = []
            total = 0
            async for chunk in res.aiter_bytes():
                total += len(chunk)
                if total > rc.MAX_UPLOAD_BYTES:
                    raise ValueError("PDF 超过大小上限")
                chunks.append(chunk)
            data = b"".join(chunks)
        if not data.startswith(b"%PDF-"):
            raise ValueError("该链接不是 PDF 文件")
        return data
    raise ValueError("重定向次数过多")


def _save_pdf(uid: str, data: bytes) -> Path:
    folder = Path(rc.DATA_DIR) / "pdf" / rc._safe_uid(uid)
    folder.mkdir(parents=True, exist_ok=True)
    name = hashlib.sha256(data).hexdigest()[:20] + ".pdf"
    path = folder / name
    if not path.exists():
        path.write_bytes(data)
    files = sorted(folder.glob("*.pdf"), key=lambda p: p.stat().st_mtime, reverse=True)
    for old in files[20:]:
        try:
            old.unlink()
        except OSError:
            continue
    return path


async def open_pdf(request: Request) -> JSONResponse:
    """下载开放获取 PDF,并用本机默认程序(WPS/阅读器)打开。"""
    rec = require_auth(request)
    uid = str(rec.get("uid") or "")
    if not _print_allowed(request):
        raise HTTPException(403, "打开 PDF 仅支持本机访问")
    body = await read_json_object(request)
    url = str(body.get("url") or "")
    if not _pdf_url_allowed(url):
        raise HTTPException(400, "该论文没有可用的开放获取 PDF")
    if not _limiter.allow(uid):
        raise HTTPException(429, "操作过于频繁,请稍后再试")
    try:
        async with httpx.AsyncClient(
            timeout=30, follow_redirects=False,
            headers={"User-Agent": "MathGuide/1.10 (open access PDF)"},
        ) as client:
            data = await _download_pdf(client, url)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(502, f"下载 PDF 失败: {type(exc).__name__}") from exc
    path = await asyncio.to_thread(_save_pdf, uid, data)
    opened = await asyncio.to_thread(_open_in_office, path)
    return JSONResponse({"ok": True, "opened": opened, "file": path.name})
