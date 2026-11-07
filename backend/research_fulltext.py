"""合法全文解析:把标识符变成开放获取候选,不代理付费墙内容。"""
from __future__ import annotations

import difflib
import re
from typing import Iterable
from urllib.parse import urlparse
from xml.etree import ElementTree

import httpx
from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import JSONResponse

import research_oa as oa
import research_urls as urls
from auth import require_auth
from rate_limit import SlidingWindowLimiter

STATUSES = {
    "oa_pdf", "oa_landing", "preprint", "institutional",
    "no_legal_copy", "unknown", "ambiguous",
}

_SOURCE_PRIORITY = {
    "unpaywall": 5,
    "europepmc": 4,
    "arxiv": 3,
    "biorxiv": 3,
    "chemrxiv": 3,
    "openalex": 2,
    "crossref": 1,
    "dblp": 0,
}
_ATOM = "{http://www.w3.org/2005/Atom}"
_ARXIV = "{http://arxiv.org/schemas/atom}"
_limiter = SlidingWindowLimiter(12, 60.0)


def normalize_identifiers(*, doi: str = "", arxiv_id: str = "",
                          pmid: str = "", pmcid: str = "",
                          title: str = "") -> dict[str, str]:
    return {
        "doi": str(doi or "").strip().lower(),
        "arxiv_id": str(arxiv_id or "").strip(),
        "pmid": str(pmid or "").strip(),
        "pmcid": str(pmcid or "").strip().upper(),
        "title": str(title or "").strip(),
    }


def make_candidate(url: str, *, kind: str, source: str,
                   host_type: str = "", version: str = "",
                   license: str = "", server_downloadable: bool = False,
                   is_preprint: bool = False) -> dict:
    return {
        "url": str(url or ""),
        "kind": kind,
        "source": source,
        "hostType": host_type,
        "version": version or "unknown",
        "license": license,
        "serverDownloadable": bool(server_downloadable),
        "isPreprint": bool(is_preprint),
    }


def _candidate_rank(candidate: dict) -> tuple[int, int, int]:
    return (
        1 if candidate.get("kind") == "pdf" else 0,
        1 if candidate.get("serverDownloadable") else 0,
        _SOURCE_PRIORITY.get(str(candidate.get("source") or ""), 0),
    )


def dedupe_candidates(candidates: list[dict]) -> list[dict]:
    best: dict[str, dict] = {}
    for candidate in candidates:
        url = str(candidate.get("url") or "")
        if not url:
            continue
        current = best.get(url)
        if current is None or _candidate_rank(candidate) > _candidate_rank(current):
            best[url] = candidate
    return sorted(best.values(), key=_candidate_rank, reverse=True)


def choose_status(candidates: list[dict], source_errors: list[str]) -> str:
    if any(item.get("serverDownloadable") for item in candidates):
        return "oa_pdf"
    if any(item.get("kind") in {"pdf", "landing", "html"} for item in candidates):
        return "oa_landing"
    if any(item.get("isPreprint") for item in candidates):
        return "preprint"
    return "unknown" if source_errors else "no_legal_copy"


def _mark_downloadable(candidates: Iterable[dict]) -> None:
    for candidate in candidates:
        candidate["serverDownloadable"] = bool(
            candidate.get("kind") == "pdf"
            and urls.is_safe_pdf_url(str(candidate.get("url") or ""))
        )


async def _doi_candidates(client: httpx.AsyncClient, doi: str,
                          source_errors: list[str]) -> list[dict]:
    result = await oa.resolve_doi(client, doi)
    if result.get("error"):
        source_errors.append("doi: resolver error")
    url = str(result.get("oaUrl") or "")
    if not url:
        return []
    path = urlparse(url).path.lower()
    source = str(result.get("resolver") or "openalex")
    return [make_candidate(
        url,
        kind="pdf" if path.endswith(".pdf") else "landing",
        source=source,
        host_type=str(result.get("oaSource") or ""),
        version=str(result.get("version") or ""),
        license=str(result.get("license") or ""),
        server_downloadable=False,
        is_preprint=source in {"arxiv", "biorxiv", "chemrxiv"},
    )]


def title_similarity(a: str, b: str) -> float:
    def normalize(text: str) -> str:
        return re.sub(r"[^a-z0-9一-鿿]+", " ",
                      str(text or "").lower()).strip()
    left, right = normalize(a), normalize(b)
    if not left or not right:
        return 0.0
    return difflib.SequenceMatcher(None, left, right).ratio()


def _title_from_item(item: dict) -> str:
    raw = item.get("title")
    if isinstance(raw, list):
        raw = raw[0] if raw else ""
    return str(raw or "").strip()


async def _title_candidates(client: httpx.AsyncClient, title: str,
                            limit: int = 5) -> list[dict]:
    res = await client.get(
        "https://api.crossref.org/works",
        params={"query.title": title, "rows": limit},
        timeout=8.0,
    )
    if res.status_code != 200:
        return []
    items = (((res.json() or {}).get("message") or {}).get("items") or [])
    out: list[dict] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        candidate_title = _title_from_item(item)
        doi = str(item.get("DOI") or "").strip().lower()
        if not candidate_title:
            continue
        url = str(item.get("URL") or (f"https://doi.org/{doi}" if doi else ""))
        candidate = make_candidate(
            url, kind="landing", source="crossref", version="unknown",
            server_downloadable=False, is_preprint=False)
        candidate["title"] = candidate_title[:300]
        candidate["doi"] = doi
        candidate["similarity"] = round(title_similarity(title, candidate_title), 6)
        out.append(candidate)
    return out


async def _arxiv_candidates(client: httpx.AsyncClient,
                            arxiv_id: str) -> list[dict]:
    res = await client.get(
        "https://export.arxiv.org/api/query",
        params={"id_list": arxiv_id},
        timeout=8.0,
    )
    if res.status_code != 200:
        return []
    try:
        root = ElementTree.fromstring(res.text)
    except (ElementTree.ParseError, TypeError, ValueError):
        return []
    out: list[dict] = []
    for entry in root.findall(f"{_ATOM}entry"):
        pdf_url = ""
        landing = ""
        for link in entry.findall(f"{_ATOM}link"):
            href = str(link.get("href") or "")
            if "arxiv.org/pdf/" in href:
                pdf_url = href
            elif "arxiv.org/abs/" in href:
                landing = href
        if not pdf_url:
            continue
        candidate = make_candidate(
            pdf_url, kind="pdf", source="arxiv",
            host_type="preprint", version="submittedVersion",
            server_downloadable=False, is_preprint=True)
        candidate["landingUrl"] = landing
        out.append(candidate)
    return out


async def _pmc_candidates(client: httpx.AsyncClient, pmid: str,
                          pmcid: str) -> list[dict]:
    query = f"PMCID:{pmcid}" if pmcid else f"EXT_ID:{pmid}"
    if not (pmcid or pmid):
        return []
    res = await client.get(
        "https://www.ebi.ac.uk/europepmc/webservices/rest/search",
        params={"query": query, "format": "json", "resultType": "core"},
        timeout=8.0,
    )
    if res.status_code != 200:
        return []
    results = (((res.json() or {}).get("resultList") or {}).get("result") or [])
    out: list[dict] = []
    for item in results:
        if not isinstance(item, dict):
            continue
        full = ((item.get("fullTextUrlList") or {}).get("fullTextUrl") or [])
        if isinstance(full, dict):
            full = [full]
        for link in full:
            if not isinstance(link, dict):
                continue
            url = str(link.get("url") or "")
            if not url:
                continue
            style = str(link.get("documentStyle") or "").lower()
            candidate = make_candidate(
                url,
                kind="pdf" if ("pdf" in style or urlparse(url).path.lower().endswith(".pdf")) else "landing",
                source="europepmc",
                host_type="repository",
                version="publishedVersion",
                server_downloadable=False,
                is_preprint=False,
            )
            out.append(candidate)
    return out


def _matched_identifiers(ids: dict[str, str]) -> list[dict]:
    return [
        {"type": kind, "value": ids[key]}
        for kind, key in (("doi", "doi"), ("arxiv", "arxiv_id"),
                          ("pmid", "pmid"), ("pmcid", "pmcid"))
        if ids[key]
    ]


async def resolve(client: httpx.AsyncClient, *, doi: str = "",
                  arxiv_id: str = "", pmid: str = "", pmcid: str = "",
                  title: str = "") -> dict:
    ids = normalize_identifiers(
        doi=doi, arxiv_id=arxiv_id, pmid=pmid, pmcid=pmcid, title=title)
    candidates: list[dict] = []
    source_errors: list[str] = []
    if ids["doi"]:
        candidates += await _doi_candidates(client, ids["doi"], source_errors)
    if ids["arxiv_id"]:
        candidates += await _arxiv_candidates(client, ids["arxiv_id"])
    if ids["pmid"] or ids["pmcid"]:
        candidates += await _pmc_candidates(client, ids["pmid"], ids["pmcid"])

    matched = _matched_identifiers(ids)
    if not matched and ids["title"]:
        title_candidates = await _title_candidates(client, ids["title"], 5)
        accepted = [item for item in title_candidates
                    if item.get("similarity", 0.0) >= 0.92]
        accepted.sort(key=lambda item: item.get("similarity", 0.0), reverse=True)
        ambiguous = (
            len(accepted) != 1
            or (len(accepted) >= 2
                and accepted[0]["similarity"] - accepted[1]["similarity"] < 0.03)
        )
        if ambiguous:
            return {
                "status": "ambiguous",
                "identifier": None,
                "matchedIdentifiers": [],
                "best": None,
                "alternatives": [],
                "candidates": sorted(
                    title_candidates,
                    key=lambda item: item.get("similarity", 0.0),
                    reverse=True)[:5],
                "reason": "标题命中多个候选或相似度不足",
            }
        candidates = accepted

    candidates = dedupe_candidates(candidates)
    _mark_downloadable(candidates)
    status = choose_status(candidates, source_errors)
    if status == "ambiguous":
        return {
            "status": status, "identifier": None, "matchedIdentifiers": matched,
            "best": None, "alternatives": [], "candidates": candidates[:5],
            "reason": "标题命中多个候选或相似度不足",
        }
    identifier = matched[0] if matched else (
        {"type": "doi", "value": candidates[0].get("doi", "")}
        if candidates and candidates[0].get("doi") else None)
    return {
        "status": status,
        "identifier": identifier,
        "matchedIdentifiers": matched,
        "best": candidates[0] if candidates else None,
        "alternatives": candidates[1:],
        "candidates": [],
        "reason": "; ".join(source_errors)[:300],
    }


async def fulltext_lookup(request: Request) -> JSONResponse:
    """按标识符解析合法全文;只返回候选,不下载、不代理。"""
    rec = require_auth(request)
    uid = str(rec.get("uid") or "")
    params = request.query_params
    doi = (params.get("doi") or "").strip()[:100]
    arxiv_id = (params.get("arxivId") or "").strip()[:100]
    pmid = (params.get("pmid") or "").strip()[:100]
    pmcid = (params.get("pmcid") or "").strip()[:100]
    title = (params.get("title") or "").strip()[:300]
    if not any((doi, arxiv_id, pmid, pmcid, title)):
        raise HTTPException(400, "缺少 doi、arxivId、pmid、pmcid 或 title")
    if not _limiter.allow(uid):
        raise HTTPException(429, "检索过于频繁,请稍后再试")
    async with httpx.AsyncClient(
            timeout=8.0, follow_redirects=True,
            headers={"User-Agent": "MathGuide/1.18 (research fulltext)"}) as client:
        result = await resolve(
            client, doi=doi, arxiv_id=arxiv_id, pmid=pmid,
            pmcid=pmcid, title=title)
    return JSONResponse(result, headers={"Cache-Control": "no-store"})
