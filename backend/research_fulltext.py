"""合法全文解析:把标识符变成开放获取候选,不代理付费墙内容。"""
from __future__ import annotations

from urllib.parse import urlparse

import httpx

import research_oa as oa

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


async def resolve(client: httpx.AsyncClient, *, doi: str = "",
                  arxiv_id: str = "", pmid: str = "", pmcid: str = "",
                  title: str = "") -> dict:
    ids = normalize_identifiers(
        doi=doi, arxiv_id=arxiv_id, pmid=pmid, pmcid=pmcid, title=title)
    candidates: list[dict] = []
    source_errors: list[str] = []
    if ids["doi"]:
        candidates += await _doi_candidates(client, ids["doi"], source_errors)
    candidates = dedupe_candidates(candidates)

    matched = [
        {"type": kind, "value": ids[key]}
        for kind, key in (("doi", "doi"), ("arxiv", "arxiv_id"),
                          ("pmid", "pmid"), ("pmcid", "pmcid"))
        if ids[key]
    ]
    identifier = matched[0] if matched else None
    return {
        "status": choose_status(candidates, source_errors),
        "identifier": identifier,
        "matchedIdentifiers": matched,
        "best": candidates[0] if candidates else None,
        "alternatives": candidates[1:],
        "candidates": [],
        "reason": "; ".join(source_errors)[:300],
    }
