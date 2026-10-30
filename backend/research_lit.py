"""
科研文献发现:跨库检索已发表论文的元数据与摘要。

只返回元数据/摘要与原文链接,不抓取或转存付费全文;
用户自行上传的论文仍走 research_corpus 的本地语料库。

数据源:
- Crossref(DOI 权威元数据,免 key)
- arXiv(预印本,免 key)
- Europe PMC(生命科学,免 key)
- PubMed E-utilities(生物医学,免 key;可选 MG_NCBI_API_KEY)
- INSPIRE-HEP(高能物理,免 key)
- zbMATH Open(数学,免 key)
- DOAJ(开放获取期刊,免 key)
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
from copy import deepcopy
from pathlib import Path
from urllib.parse import quote, urlparse
from xml.etree import ElementTree

import httpx
from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import JSONResponse

import research_corpus as rc
import research_oa as oa_resolver
import research_sources as rs
import research_venues as rv
from auth import require_auth
from http_utils import read_json_object
from rate_limit import SlidingWindowLimiter
from research_tables import _open_in_office, _print_allowed

TIMEOUT = 15.0
DEADLINE = 12.0
MAX_RESULTS = 20
_limiter = SlidingWindowLimiter(20, 60)

# 外部检索结果短期缓存:同一查询重复点击不再打满 Crossref/DOAJ 限额。
_SEARCH_TTL = 300.0
_SEARCH_MAX = 64
_SEARCH_CACHE: dict[str, tuple[float, list[dict], list[str]]] = {}


def _search_key(query: str, field: str, limit: int, filters: dict | None,
                include_preprints: bool, peer_reviewed: bool, oa_only: bool) -> str:
    payload = {
        "q": query, "field": field, "limit": limit,
        "filters": filters or {},
        "preprints": include_preprints,
        "peer": peer_reviewed,
        "oa": oa_only,
    }
    return hashlib.sha256(json.dumps(
        payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()

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


_DOI_IN_TEXT = re.compile(r"\b10\.\d{4,9}/[^\s\"'<>]+", re.IGNORECASE)
_ARXIV_ID = re.compile(r"(?:arxiv:\s*)?(\d{4}\.\d{4,5})(?:v\d+)?\b", re.IGNORECASE)
_PMCID = re.compile(r"\b(PMC\d{6,})\b", re.IGNORECASE)
_PMID = re.compile(r"\bPMID[:\s]*(\d{6,9})\b", re.IGNORECASE)


def _detect_identifier(query: str) -> tuple[str, str] | None:
    """识别 DOI / arXiv / PMCID / PMID;命中后跳过关键词检索。"""
    match = _DOI_IN_TEXT.search(query)
    if match:
        doi = _doi(match.group(0).rstrip(".,;)]}"))
        if doi:
            return ("doi", doi)
    match = _ARXIV_ID.search(query)
    if match:
        return ("arxiv", match.group(1))
    match = _PMCID.search(query)
    if match:
        return ("pmcid", match.group(1).upper())
    match = _PMID.search(query)
    if match:
        return ("pmid", match.group(1))
    return None


def _result(**kwargs) -> dict:
    result = {
        "title": "", "authors": "", "year": 0, "venue": "", "doi": "",
        "url": "", "pdfUrl": "", "abstract": "", "citations": 0, "sources": [],
        "docId": "", "tempDocId": "", "imported": False,
        "issn": "", "publisher": "", "peerReviewed": False,
        "articleType": "", "oaStatus": "unknown", "oaUrl": "", "license": "",
        "retractionStatus": "none", "versionOf": "",
        "fields": [], "sourceTier": "", "venueTier": "", "venueLabel": "",
        **kwargs,
    }
    for key in ("url", "pdfUrl", "oaUrl"):
        value = result[key]
        try:
            parsed = urlparse(value) if isinstance(value, str) else None
            schemes = {"https"} if key == "oaUrl" else {"http", "https"}
            if (not parsed or parsed.scheme not in schemes or not parsed.hostname
                    or parsed.username or parsed.password or any(c.isspace() or ord(c) < 32 for c in value)):
                result[key] = ""
        except ValueError:
            result[key] = ""
    if not isinstance(result.get("fields"), list):
        result["fields"] = []
    return result


def _mark_local(uid: str, results: list[dict]) -> list[dict]:
    """标记结果是否已在论文库(imported)或已临时入库(tempDocId)。"""
    dois = {r["doi"] for r in results if r.get("doi")}
    known = rc._docs_by_doi(uid, dois)
    for item in results:
        hit = known.get(str(item.get("doi") or "").lower())
        if not hit:
            continue
        if hit["status"] == "temp":
            item["tempDocId"] = hit["id"]
        else:
            item["docId"] = hit["id"]
            item["imported"] = True
    return results


def _crossref_item(item: dict) -> dict | None:
    if item.get("type") in {"component", "dataset"}:
        return None
    title = _clean((item.get("title") or [""])[0], 300)
    if not title:
        return None
    authors = ", ".join(
        a.get("family") or a.get("name") or "" for a in item.get("author", []))
    issued = item.get("issued", {}).get("date-parts") or [[0]]
    year = issued[0][0] if issued and issued[0] else 0
    doi = _doi(item.get("DOI"))
    ctype = str(item.get("type") or "")
    peer_reviewed = ctype in {"journal-article", "proceedings-article"}
    update_types = {
        str(u.get("type") or "") for u in (item.get("update-to") or [])
        if isinstance(u, dict)
    }
    retraction = ("retracted" if "retraction" in update_types
                  else "corrected" if update_types & {"correction", "erratum"}
                  else "none")
    license_value = ""
    for lic in item.get("license") or []:
        if isinstance(lic, dict) and lic.get("URL"):
            license_value = str(lic["URL"])[:200]
            break
    return _result(
        title=title, authors=authors[:300], year=year,
        venue=_clean((item.get("container-title") or [""])[0], 160),
        doi=doi, url=item.get("URL") or (f"https://doi.org/{doi}" if doi else ""),
        abstract=_clean(item.get("abstract")),
        citations=int(item.get("is-referenced-by-count") or 0),
        sources=["crossref"],
        issn=",".join(str(x) for x in (item.get("ISSN") or [])[:3]),
        publisher=_clean(item.get("publisher"), 160),
        peerReviewed=peer_reviewed,
        articleType=("conference" if ctype == "proceedings-article"
                     else "research" if ctype == "journal-article" else ctype or "research"),
        license=license_value,
        retractionStatus=retraction,
        sourceTier="authority",
    )


async def _crossref(client: httpx.AsyncClient, query: str, limit: int,
                    filters: dict | None = None) -> list[dict]:
    filters = filters or {}
    params = {
        "query.bibliographic": query, "rows": limit,
        "select": "DOI,title,author,issued,container-title,abstract,"
                  "is-referenced-by-count,URL,type,ISSN,publisher,license,update-to",
    }
    if filters.get("author"):
        params["query.author"] = filters["author"]
    date_filters = ["type:journal-article", "type:proceedings-article"]
    if filters.get("yearFrom"):
        date_filters.append(f"from-pub-date:{filters['yearFrom']}-01-01")
    if filters.get("yearTo"):
        date_filters.append(f"until-pub-date:{filters['yearTo']}-12-31")
    params["filter"] = ",".join(date_filters)
    mailto = os.getenv("MG_LITERATURE_MAILTO", "").strip()
    if mailto:
        params["mailto"] = mailto
    res = await client.get("https://api.crossref.org/works", params=params)
    if res.status_code == 429:
        await asyncio.sleep(0.6)
        res = await client.get("https://api.crossref.org/works", params=params)
    res.raise_for_status()
    out = []
    for item in res.json().get("message", {}).get("items", []):
        parsed = _crossref_item(item)
        if parsed:
            out.append(parsed)
    return out


async def _crossref_doi(client: httpx.AsyncClient, doi: str) -> list[dict]:
    res = await client.get(f"https://api.crossref.org/works/{doi}")
    if res.status_code == 404:
        return []
    res.raise_for_status()
    parsed = _crossref_item(res.json().get("message", {}))
    return [parsed] if parsed else []


def _arxiv_fields(entry) -> list[str]:
    out: list[str] = []
    for node in entry.findall(f"{_ATOM}category"):
        term = str(node.get("term") or "").lower()
        if term.startswith("math"):
            field = "math"
        elif term.startswith("q-bio"):
            field = "biology"
        elif "chem" in term:
            field = "chemistry"
        elif term.startswith(("hep", "quant-ph", "cond-mat", "astro-ph", "physics", "nucl", "gr-qc")):
            field = "physics"
        else:
            continue
        if field not in out:
            out.append(field)
    return out


def _arxiv_entry(entry) -> dict | None:  # noqa: ANN001
    title = _clean(entry.findtext(f"{_ATOM}title"), 300)
    if not title:
        return None
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
    return _result(
        title=title, authors=authors[:300], year=year, venue="arXiv",
        doi=_doi(entry.findtext(f"{_ARXIV}doi")), url=link,
        pdfUrl=pdf_url, oaUrl=pdf_url, oaStatus="green" if pdf_url else "unknown",
        abstract=_clean(entry.findtext(f"{_ATOM}summary")),
        sources=["arxiv"], peerReviewed=False, articleType="preprint",
        sourceTier="preprint", fields=_arxiv_fields(entry),
    )


async def _arxiv(client: httpx.AsyncClient, query: str, limit: int,
                 filters: dict | None = None) -> list[dict]:
    filters = filters or {}
    parts = [f"all:{query}"] if query else []
    if filters.get("author"):
        parts.append(f'au:"{filters["author"]}"')
    if filters.get("yearFrom") or filters.get("yearTo"):
        start = f"{filters.get('yearFrom') or 1990}01010000"
        end = f"{filters.get('yearTo') or time.localtime().tm_year}12312359"
        parts.append(f"submittedDate:[{start} TO {end}]")
    search_query = " AND ".join(f"({part})" for part in parts) or f"all:{query}"
    res = await client.get(
        "https://export.arxiv.org/api/query",
        params={"search_query": search_query, "max_results": limit},
    )
    res.raise_for_status()
    root = ElementTree.fromstring(res.text)
    out = []
    for entry in root.findall(f"{_ATOM}entry"):
        parsed = _arxiv_entry(entry)
        if parsed:
            out.append(parsed)
    return out


async def _arxiv_by_id(client: httpx.AsyncClient, arxiv_id: str) -> list[dict]:
    res = await client.get(
        "https://export.arxiv.org/api/query",
        params={"id_list": arxiv_id, "max_results": 3},
    )
    res.raise_for_status()
    root = ElementTree.fromstring(res.text)
    out = []
    for entry in root.findall(f"{_ATOM}entry"):
        parsed = _arxiv_entry(entry)
        if parsed:
            out.append(parsed)
    return out


async def _europe_pmc(client: httpx.AsyncClient, query: str, limit: int,
                      filters: dict | None = None,
                      title_only: bool = False) -> list[dict]:
    filters = filters or {}
    if title_only:
        search = f'TITLE:"{query[:150]}"'
    else:
        parts = [query] if query else []
        if filters.get("author"):
            parts.append(f'AUTH:"{filters["author"]}"')
        if filters.get("yearFrom") or filters.get("yearTo"):
            start = filters.get("yearFrom") or 1900
            end = filters.get("yearTo") or time.localtime().tm_year
            parts.append(f"PUB_YEAR:[{start} TO {end}]")
        search = " AND ".join(parts) or query
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
        journal = (item.get("journalInfo") or {}).get("journal") or {}
        journal_title = item.get("journalTitle") or (
            journal.get("title") if isinstance(journal, dict) else "") or ""
        pub_types = [
            str(p.get("pubType") or "") for p in
            ((item.get("pubTypeList") or {}).get("pubType") or [])
            if isinstance(p, dict)
        ]
        lowered = " ".join(pub_types).lower()
        retraction = ("retracted" if "retracted publication" in lowered
                      else "corrected" if "published erratum" in lowered
                      else "none")
        is_preprint = str(item.get("source") or "").upper() == "PPR" or "preprint" in lowered
        oa_url = ""
        for link in ((item.get("fullTextUrlList") or {}).get("fullTextUrl") or []):
            if not isinstance(link, dict):
                continue
            url = str(link.get("url") or "")
            if link.get("documentStyle") == "pdf" and _pdf_url_allowed(url):
                oa_url = url
                break
        if not oa_url:
            for link in ((item.get("fullTextUrlList") or {}).get("fullTextUrl") or []):
                if isinstance(link, dict) and link.get("availability") == "Open access":
                    url = str(link.get("url") or "")
                    if url.startswith("https://"):
                        oa_url = url
                        break
        out.append(_result(
            title=title, authors=_clean(item.get("authorString"), 300),
            year=int(year) if str(year).isdigit() else 0,
            venue=_clean(journal_title, 160),
            doi=doi, url=url,
            abstract=_clean(item.get("abstractText")),
            citations=int(item.get("citedByCount") or 0),
            sources=["europepmc"],
            issn=",".join(
                str(x) for x in ([journal.get("issn"), journal.get("essn")]
                                 if isinstance(journal, dict) else []) if x)[:80],
            publisher=_clean(journal.get("publisher") if isinstance(journal, dict) else "", 160),
            peerReviewed=not is_preprint,
            articleType="preprint" if is_preprint else (
                "review" if "review" in lowered else "research"),
            oaStatus="green" if oa_url else "unknown",
            oaUrl=oa_url,
            license=str(item.get("license") or "")[:120],
            retractionStatus=retraction,
            sourceTier="preprint" if is_preprint else "authority",
            fields=["biology"],
        ))
    return out


def _passes_filters(item: dict, filters: dict | None) -> bool:
    filters = filters or {}
    author = str(filters.get("author") or "").strip().lower()
    if author and author not in str(item.get("authors") or "").lower():
        return False
    year = int(item.get("year") or 0)
    if filters.get("yearFrom") and year and year < int(filters["yearFrom"]):
        return False
    if filters.get("yearTo") and year and year > int(filters["yearTo"]):
        return False
    return True


def _inspire_type(value: str) -> tuple[str, bool]:
    low = value.lower()
    if "preprint" in low:
        return "preprint", False
    if "review" in low:
        return "review", True
    if "thesis" in low:
        return "thesis", False
    return "research", True


async def _inspire(client: httpx.AsyncClient, query: str, limit: int,
                   filters: dict | None = None) -> list[dict]:
    params = {
        "q": query, "size": max(1, min(limit, 50)), "sort": "mostrecent",
        "fields": "titles,authors,publication_info,dois,arxiv_eprints,"
                  "citation_count,abstracts,document_type,preprint_date,"
                  "control_number",
    }
    res = await client.get("https://inspirehep.net/api/literature", params=params)
    res.raise_for_status()
    out: list[dict] = []
    for hit in (res.json().get("hits") or {}).get("hits", []):
        meta = hit.get("metadata") or {}
        title = _clean(((meta.get("titles") or [{}])[0]).get("title"), 300)
        if not title:
            continue
        authors = ", ".join(
            str(a.get("full_name") or "") for a in meta.get("authors", [])
            if isinstance(a, dict))[:300]
        pub_raw = meta.get("publication_info")
        if isinstance(pub_raw, list):
            pub = pub_raw[0] if pub_raw and isinstance(pub_raw[0], dict) else {}
        else:
            pub = pub_raw if isinstance(pub_raw, dict) else {}
        year = pub.get("year") or 0
        if not year:
            preprint = str(meta.get("preprint_date") or "")
            year = int(preprint[:4]) if preprint[:4].isdigit() else 0
        doi = _doi(((meta.get("dois") or [{}])[0]).get("value"))
        arxiv = str(((meta.get("arxiv_eprints") or [{}])[0]).get("value") or "")
        journal = _clean(pub.get("journal_title"), 160)
        is_preprint = not journal and bool(arxiv)
        control_number = str(meta.get("control_number") or hit.get("id") or "")
        url = f"https://arxiv.org/abs/{arxiv}" if arxiv else (
            f"https://doi.org/{doi}" if doi else (
                f"https://inspirehep.net/literature/{control_number}"
                if control_number else ""))
        pdf_url = f"https://arxiv.org/pdf/{arxiv}.pdf" if arxiv else ""
        doc_type = str((meta.get("document_type") or [""])[0] if isinstance(
            meta.get("document_type"), list) else meta.get("document_type") or "")
        article_type, reviewed = _inspire_type(doc_type)
        if is_preprint:
            article_type, reviewed = "preprint", False
        out.append(_result(
            title=title, authors=authors, year=int(year or 0),
            venue=journal or ("arXiv" if is_preprint else "INSPIRE-HEP"),
            doi=doi, url=url, pdfUrl=pdf_url, oaUrl=pdf_url,
            oaStatus="green" if pdf_url else "unknown",
            abstract=_clean(((meta.get("abstracts") or [{}])[0]).get("value")),
            citations=int(meta.get("citation_count") or 0),
            sources=["inspire"], peerReviewed=reviewed,
            articleType=article_type,
            sourceTier="preprint" if is_preprint else "authority",
            retractionStatus="none", fields=["physics"],
        ))
    return [item for item in out if _passes_filters(item, filters)][:limit]


async def _pubmed(client: httpx.AsyncClient, query: str, limit: int,
                  filters: dict | None = None) -> list[dict]:
    filters = filters or {}
    params = {
        "db": "pubmed", "term": query, "retmode": "json",
        "retmax": max(1, min(limit, 50)), "sort": "relevance",
        "tool": "MathGuide",
    }
    if filters.get("author"):
        params["term"] = f'{query} AND "{filters["author"]}"[Author]'
    if filters.get("yearFrom") or filters.get("yearTo"):
        params["mindate"] = str(filters.get("yearFrom") or 1900)
        params["maxdate"] = str(filters.get("yearTo") or time.localtime().tm_year)
        params["datetype"] = "pdat"
    key = os.getenv("MG_NCBI_API_KEY", "").strip()
    if key:
        params["api_key"] = key
    base = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
    search_res = await client.get(f"{base}/esearch.fcgi", params=params)
    search_res.raise_for_status()
    ids = ((search_res.json().get("esearchresult") or {}).get("idlist") or [])[:limit]
    if not ids:
        return []
    fetch_params = {"db": "pubmed", "id": ",".join(ids), "retmode": "xml",
                    "tool": "MathGuide"}
    if key:
        fetch_params["api_key"] = key
    fetch_res = await client.get(f"{base}/efetch.fcgi", params=fetch_params)
    fetch_res.raise_for_status()
    root = ElementTree.fromstring(fetch_res.text)
    out: list[dict] = []
    for article in root.findall(".//PubmedArticle"):
        citation = article.find("MedlineCitation")
        if citation is None:
            continue
        pmid = (citation.findtext("PMID") or "").strip()
        art = citation.find("Article")
        if art is None:
            continue
        title = _clean("".join(art.find("ArticleTitle").itertext())
                       if art.find("ArticleTitle") is not None else "", 300)
        if not title:
            continue
        authors = ", ".join(
            " ".join(x for x in [a.findtext("LastName"), a.findtext("ForeName")] if x)
            for a in art.findall("AuthorList/Author"))[:300]
        journal = art.find("Journal")
        venue = _clean(journal.findtext("Title") if journal is not None else "", 160)
        issn = (journal.findtext("ISSN") if journal is not None else "") or ""
        year = 0
        pub_date = journal.find("JournalIssue/PubDate") if journal is not None else None
        if pub_date is not None:
            raw_year = pub_date.findtext("Year") or (
                (pub_date.findtext("MedlineDate") or "")[:4])
            year = int(raw_year) if str(raw_year).isdigit() else 0
        abstract = " ".join(
            "".join(node.itertext()) for node in art.findall("Abstract/AbstractText"))
        pub_types = [
            (node.text or "").strip() for node in art.findall("PublicationTypeList/PublicationType")]
        lowered = " ".join(pub_types).lower()
        ids_node = article.find("PubmedData/ArticleIdList")
        doi = pmcid = ""
        if ids_node is not None:
            for node in ids_node.findall("ArticleId"):
                kind = node.get("IdType")
                if kind == "doi":
                    doi = _doi(node.text)
                elif kind == "pmc":
                    pmcid = (node.text or "").strip()
        retraction = ("retracted" if "retracted publication" in lowered
                      else "corrected" if "published erratum" in lowered
                      else "none")
        pmc_url = (f"https://www.ncbi.nlm.nih.gov/pmc/articles/{pmcid}/"
                   if pmcid else "")
        out.append(_result(
            title=title, authors=authors, year=year, venue=venue,
            doi=doi, url=f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/" if pmid else "",
            abstract=_clean(abstract), sources=["pubmed"],
            issn=issn, peerReviewed=True,
            articleType="review" if "review" in lowered else "research",
            oaStatus="green" if pmc_url else "unknown", oaUrl=pmc_url,
            retractionStatus=retraction, sourceTier="authority",
            fields=["biology"],
        ))
    return [item for item in out if _passes_filters(item, filters)][:limit]


def _zbmath_title(item: dict) -> str:
    title = item.get("title")
    if isinstance(title, dict):
        return _clean(title.get("title") or title.get("original"), 300)
    return _clean(title, 300)


async def _zbmath(client: httpx.AsyncClient, query: str, limit: int,
                  filters: dict | None = None) -> list[dict]:
    params = {"search_string": query, "results_per_page": max(1, min(limit, 50))}
    res = await client.get("https://api.zbmath.org/v1/document/_search", params=params)
    res.raise_for_status()
    out: list[dict] = []
    for item in res.json().get("result", []):
        title = _zbmath_title(item)
        if not title or "zbMATH Open Web Interface contents unavailable" in title:
            continue
        authors = ", ".join(
            str(a.get("name") or "") for a in
            ((item.get("contributors") or {}).get("authors") or [])
            if isinstance(a, dict))[:300]
        source = item.get("source") or {}
        source_text = str(source.get("source") or "") if isinstance(source, dict) else ""
        if "contents unavailable" in source_text.lower():
            source_text = "zbMATH Open"
        series = source.get("series") if isinstance(source, dict) else []
        journal = next((
            entry for entry in (series if isinstance(series, list) else [])
            if isinstance(entry, dict) and entry.get("title")
        ), {})
        issns = [
            str(entry.get("number") or "")
            for entry in (journal.get("issn") or [])
            if isinstance(entry, dict) and entry.get("number")
        ]
        links = item.get("links") or []
        url = ""
        pdf_url = ""
        for link in links:
            if not isinstance(link, dict):
                continue
            candidate = str(link.get("url") or "")
            if candidate.startswith("https://doi.org/"):
                url = candidate
            elif candidate.lower().endswith(".pdf") and not pdf_url:
                pdf_url = candidate
        if not url:
            url = str(item.get("zbmath_url") or "")
        doc_type = item.get("document_type") or {}
        type_text = str(doc_type.get("description") or "") if isinstance(doc_type, dict) else ""
        year = item.get("year")
        out.append(_result(
            title=title, authors=authors,
            year=int(year) if str(year).isdigit() else 0,
            venue=_clean(journal.get("title") or source_text, 160), url=url,
            pdfUrl=pdf_url, oaUrl=pdf_url,
            oaStatus="unknown",
            sources=["zbmath"], peerReviewed=True,
            articleType="review" if "review" in type_text.lower() else "research",
            issn=",".join(issns[:3]),
            publisher=_clean(journal.get("publisher"), 160),
            sourceTier="authority", fields=["math"],
        ))
    return [item for item in out if _passes_filters(item, filters)][:limit]


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


async def _doaj(client: httpx.AsyncClient, query: str, limit: int,
                filters: dict | None = None) -> list[dict]:
    params = {"pageSize": max(1, min(limit, 50))}
    res = await client.get(
        f"https://doaj.org/api/search/articles/{quote(query, safe='')}",
        params=params)
    res.raise_for_status()
    out: list[dict] = []
    for item in res.json().get("results", []):
        bib = item.get("bibjson") or {}
        title = _clean(bib.get("title"), 300)
        if not title:
            continue
        journal = bib.get("journal") or {}
        authors = ", ".join(
            str(a.get("name") or "") for a in (bib.get("author") or [])
            if isinstance(a, dict))[:300]
        doi = ""
        fulltext = ""
        for ident in bib.get("identifier") or []:
            if isinstance(ident, dict) and ident.get("type") == "doi":
                doi = _doi(ident.get("id"))
        for link in bib.get("link") or []:
            if isinstance(link, dict) and link.get("type") == "fulltext":
                url = str(link.get("url") or "")
                if url.startswith("https://"):
                    fulltext = url
                    break
        issns = journal.get("issns") if isinstance(journal, dict) else []
        out.append(_result(
            title=title, authors=authors,
            year=int(bib.get("year")) if str(bib.get("year")).isdigit() else 0,
            venue=_clean(journal.get("title") if isinstance(journal, dict) else "", 160),
            doi=doi, url=fulltext or (f"https://doi.org/{doi}" if doi else ""),
            oaUrl=fulltext, oaStatus="gold" if fulltext else "unknown",
            abstract=_clean(bib.get("abstract")),
            sources=["doaj"], peerReviewed=True, articleType="research",
            issn=",".join(str(x) for x in (issns or [])[:3]),
            publisher=_clean(journal.get("publisher") if isinstance(journal, dict) else "", 160),
            license="", sourceTier="authority", fields=["general"],
        ))
    return [item for item in out if _passes_filters(item, filters)][:limit]


async def _openalex(client: httpx.AsyncClient, query: str, limit: int,
                    filters: dict | None = None) -> list[dict]:
    key = os.getenv("MG_OPENALEX_API_KEY", "").strip()
    filters = filters or {}
    params = {"search": query, "per-page": limit,
              "select": "id,doi,title,publication_year,authorships,"
                        "primary_location,primary_topic,abstract_inverted_index,"
                        "cited_by_count,type,open_access,best_oa_location,is_retracted"}
    if key:
        params["api_key"] = key
    pieces = []
    if filters.get("author"):
        pieces.append(f'raw_author_name.search:{filters["author"]}')
    if filters.get("yearFrom"):
        pieces.append(f"from_publication_date:{filters['yearFrom']}-01-01")
    if filters.get("yearTo"):
        pieces.append(f"to_publication_date:{filters['yearTo']}-12-31")
    if pieces:
        params["filter"] = ",".join(pieces)
    res = await client.get("https://api.openalex.org/works", params=params)
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
        source = location.get("source") or {}
        venue = source.get("display_name") or ""
        doi = _doi(item.get("doi"))
        oa = item.get("best_oa_location") or {}
        oa_info = item.get("open_access") or {}
        oa_url = str(oa.get("pdf_url") or oa.get("url_for_pdf") or "")
        topic = item.get("primary_topic") or {}
        field_name = str(((topic.get("field") or {}).get("display_name") or "")).lower()
        field_map = {
            "mathematics": "math", "physics": "physics", "chemistry": "chemistry",
            "biology": "biology", "medicine": "biology",
        }
        fields = [field_map[field_name]] if field_name in field_map else []
        ctype = str(item.get("type") or "")
        out.append(_result(
            title=title, authors=authors, year=item.get("publication_year") or 0,
            venue=_clean(venue, 160), doi=doi,
            url=item.get("doi") or location.get("landing_page_url") or "",
            abstract=_openalex_abstract(item),
            citations=int(item.get("cited_by_count") or 0),
            sources=["openalex"],
            issn=str(source.get("issn_l") or ""),
            publisher=_clean((source.get("host_organization_name") or ""), 160),
            peerReviewed=ctype in {"article", "review"},
            articleType="preprint" if ctype == "preprint" else (
                "review" if ctype == "review" else "research"),
            oaStatus=str(oa_info.get("oa_status") or item.get("oa_status") or "unknown"),
            oaUrl=oa_url,
            license=str(oa.get("license") or "")[:120],
            retractionStatus="retracted" if item.get("is_retracted") else "none",
            sourceTier="discovery",
            fields=fields,
        ))
    return out


async def _semantic_scholar(client: httpx.AsyncClient, query: str, limit: int,
                            filters: dict | None = None) -> list[dict]:
    key = os.getenv("MG_S2_API_KEY", "").strip()
    filters = filters or {}
    params = {"query": query, "limit": limit,
              "fields": "title,abstract,year,venue,authors,externalIds,"
                        "url,citationCount,openAccessPdf,publicationTypes"}
    if filters.get("yearFrom") or filters.get("yearTo"):
        params["year"] = f"{filters.get('yearFrom') or 1900}-{filters.get('yearTo') or time.localtime().tm_year}"
    # key 可选:无 key 走共享池,有 key 用独立额度。
    headers = {"x-api-key": key} if key else None
    res = await client.get(
        "https://api.semanticscholar.org/graph/v1/paper/search",
        params=params,
        headers=headers,
    )
    res.raise_for_status()
    out = []
    for item in res.json().get("data", []):
        title = _clean(item.get("title"), 300)
        if not title:
            continue
        ext = item.get("externalIds") or {}
        pub_types = [str(x) for x in (item.get("publicationTypes") or [])]
        lowered = " ".join(pub_types).lower()
        oa = item.get("openAccessPdf") or {}
        oa_url = str(oa.get("url") or "") if isinstance(oa, dict) else ""
        out.append(_result(
            title=title,
            authors=", ".join(a.get("name") or "" for a in item.get("authors", []))[:300],
            year=item.get("year") or 0, venue=_clean(item.get("venue"), 160),
            doi=_doi(ext.get("DOI")),
            url=item.get("url") or "",
            abstract=_clean(item.get("abstract")),
            citations=int(item.get("citationCount") or 0),
            sources=["semanticscholar"],
            oaStatus="unknown",
            oaUrl=oa_url,
            peerReviewed="journalarticle" in lowered and "preprint" not in lowered,
            articleType="preprint" if "preprint" in lowered else (
                "review" if "review" in lowered else "research"),
            sourceTier="discovery",
        ))
    return out


async def _biorxiv_detail(client: httpx.AsyncClient, doi: str) -> list[dict]:
    """bioRxiv/medRxiv 只按 DOI 补充;关键词搜索仍走 Europe PMC。"""
    if not doi.startswith("10.1101/"):
        return []
    out: list[dict] = []
    for server in ("biorxiv", "medrxiv"):
        try:
            res = await client.get(
                f"https://api.biorxiv.org/details/{server}/{doi}")
            if res.status_code != 200:
                continue
            collection = res.json().get("collection") or []
        except (httpx.HTTPError, ValueError):
            continue
        for item in collection:
            if not isinstance(item, dict):
                continue
            title = _clean(item.get("title"), 300)
            if not title:
                continue
            raw_date = str(item.get("date") or "")
            year = int(raw_date[:4]) if raw_date[:4].isdigit() else 0
            version = str(item.get("version") or "1")
            pdf_url = f"https://www.{server}.org/content/{doi}v{version}.full.pdf"
            out.append(_result(
                title=title,
                authors=_clean(item.get("authors"), 300),
                year=year, venue=server,
                doi=doi, url=f"https://doi.org/{doi}",
                abstract=_clean(item.get("abstract")),
                sources=["biorxiv"], peerReviewed=False,
                articleType="preprint", sourceTier="preprint",
                oaStatus="green", oaUrl=pdf_url,
                license=_clean(item.get("license"), 120),
                fields=["biology"],
            ))
    return out


_SOURCE_TIER_RANK = {
    "authority": 3, "repository": 2, "discovery": 1, "preprint": 0,
}
_OA_STATUS_RANK = {
    "gold": 5, "diamond": 5, "hybrid": 4, "bronze": 3, "green": 2,
    "closed": 1, "unknown": 0,
}


def _merge(results: list[dict]) -> list[dict]:
    merged: dict[str, dict] = {}
    for item in results:
        key = item["doi"] or re.sub(r"\W+", "", item["title"].lower())[:120]
        current = merged.get(key)
        if current is None:
            merged[key] = item
            continue
        current["sources"] = sorted(set(current["sources"]) | set(item["sources"]))
        for field in ("abstract", "authors", "year", "venue", "url", "pdfUrl",
                      "issn", "publisher", "oaUrl", "license",
                      "retractionStatus"):
            if field == "pdfUrl" or field == "oaUrl":
                if item.get(field) and not current.get(field):
                    current[field] = item[field]
                continue
            if len(str(item.get(field) or "")) > len(str(current.get(field) or "")):
                current[field] = item[field]
        current["citations"] = max(current["citations"], item["citations"])
        current["peerReviewed"] = bool(current.get("peerReviewed") or item.get("peerReviewed"))
        current["fields"] = sorted(set(current.get("fields") or []) | set(item.get("fields") or []))
        if (current.get("articleType") == "preprint"
                and item.get("articleType") in {"research", "review"}):
            current["articleType"] = item["articleType"]
        elif not current.get("articleType") and item.get("articleType"):
            current["articleType"] = item["articleType"]
        if (_SOURCE_TIER_RANK.get(str(item.get("sourceTier") or ""), -1)
                > _SOURCE_TIER_RANK.get(str(current.get("sourceTier") or ""), -1)):
            current["sourceTier"] = item.get("sourceTier") or ""
        if rv.rank(str(item.get("venueTier") or "")) > rv.rank(str(current.get("venueTier") or "")):
            current["venueTier"] = item.get("venueTier") or ""
        if (_OA_STATUS_RANK.get(str(item.get("oaStatus") or ""), -1)
                > _OA_STATUS_RANK.get(str(current.get("oaStatus") or ""), -1)):
            current["oaStatus"] = item["oaStatus"]
        if item.get("retractionStatus") in {"retracted", "corrected", "expression_of_concern"}:
            current["retractionStatus"] = item["retractionStatus"]
    items = list(merged.values())
    items.sort(key=lambda x: (-x["citations"], -int(x["year"] or 0)))
    return items


def _enrich(results: list[dict], field: str) -> list[dict]:
    """补场所层级、同行评审、学科标签与落地页。"""
    for item in results:
        is_preprint = (
            item.get("sourceTier") == "preprint"
            or item.get("articleType") == "preprint"
        )
        issns = [x for x in str(item.get("issn") or "").split(",") if x.strip()]
        venue = rv.lookup(issns, str(item.get("venue") or ""))
        tier = rv.tier_for(venue, field)
        if tier:
            item["venueTier"] = tier
        if venue and rv.peer_reviewed(venue) and not is_preprint:
            item["peerReviewed"] = True
        if venue:
            item["venueLabel"] = rv.label(venue)
        fields = set(item.get("fields") or [])
        if venue:
            for scope in venue.get("scope") or []:
                if scope in rs.ALL_FIELDS and scope != "general":
                    fields.add(scope)
        item["fields"] = sorted(fields)
        if not item.get("venueTier"):
            if is_preprint:
                item["venueTier"] = "P"
            elif item.get("peerReviewed"):
                item["venueTier"] = "T3"
            else:
                item["venueTier"] = "U"
        item["landingUrl"] = item.get("url") or ""
    return results


def _sort_results(results: list[dict], field: str) -> list[dict]:
    """学科检索优先权威层级;general 仍以被引数/年份为主。"""
    if field == "general":
        return sorted(results, key=lambda x: (-x["citations"], -int(x["year"] or 0)))
    return sorted(results, key=lambda x: (
        -rv.rank(str(x.get("venueTier") or "")),
        -rs.source_priority(x),
        -x["citations"],
        -int(x["year"] or 0),
    ))


_NOISE_TITLES = {
    "front matter", "back matter", "index", "table of contents",
    "editorial board", "masthead", "issue information", "cover",
}


def _is_noise(item: dict) -> bool:
    title = re.sub(r"\s+", " ", str(item.get("title") or "").strip().lower())
    return title in _NOISE_TITLES or title.startswith(("front matter", "back matter"))


def _filter_results(results: list[dict], *, peer_reviewed: bool,
                    oa_only: bool, include_preprints: bool) -> list[dict]:
    out = []
    for item in results:
        if _is_noise(item):
            continue
        if peer_reviewed and not item.get("peerReviewed"):
            continue
        if not include_preprints and (
                item.get("sourceTier") == "preprint" or item.get("articleType") == "preprint"):
            continue
        if oa_only and item.get("oaStatus") not in {
                "gold", "diamond", "hybrid", "green", "bronze"}:
            continue
        out.append(item)
    return out


def _provider_warning(name: str, exc: Exception) -> str:
    if isinstance(exc, httpx.HTTPStatusError):
        code = exc.response.status_code
        if code == 429:
            return f"{name}: 429(额度/频率限制)"
        return f"{name}: HTTP {code}"
    if isinstance(exc, (asyncio.TimeoutError, httpx.TimeoutException)):
        return f"{name}: timeout"
    return f"{name}: {type(exc).__name__}"


async def _run_providers(client: httpx.AsyncClient, providers, query: str,
                         limit: int, filters: dict | None = None,
                         deadline: float = DEADLINE) -> list[tuple[str, object]]:
    """并行检索;超过 deadline 的慢源直接取消,不让一个源拖住整页。"""
    tasks = {
        asyncio.create_task(fn(client, query, limit, filters)): name
        for name, fn in providers
    }
    done, pending = await asyncio.wait(tasks, timeout=deadline)
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


async def oa_lookup(request: Request) -> JSONResponse:
    """按 DOI 解析合法 OA 地址;不下载、不代理全文。"""
    rec = require_auth(request)
    uid = str(rec.get("uid") or "")
    doi = _doi(request.query_params.get("doi"))
    if not doi:
        raise HTTPException(400, "缺少 doi")
    if not _limiter.allow(uid):
        raise HTTPException(429, "检索过于频繁,请稍后再试")
    async with httpx.AsyncClient(
            timeout=TIMEOUT, follow_redirects=True,
            headers={"User-Agent": "MathGuide/1.14 (research oa resolver)"}) as client:
        result = await oa_resolver.resolve_doi(client, doi)
    return JSONResponse(result, headers={"Cache-Control": "no-store"})


async def venues_lookup(request: Request) -> JSONResponse:
    """按 ISSN 或名称查场所权威;返回学科层级,不做模糊猜测。"""
    require_auth(request)
    issns = [
        part.strip()
        for raw in request.query_params.getlist("issn")
        for part in raw.split(",")
        if part.strip()
    ]
    name = (request.query_params.get("name") or "").strip()
    field = (request.query_params.get("field") or "").strip().lower()
    if not issns and not name:
        raise HTTPException(400, "缺少 issn 或 name")
    venue = rv.lookup(issns, name)
    version = rv.registry_version()
    if venue is None:
        return JSONResponse(
            {"found": False, "field": field, "registryVersion": version},
            headers={"Cache-Control": "no-store"})
    return JSONResponse({
        "found": True,
        "venue": {
            "name": str(venue.get("name") or ""),
            "aliases": list(venue.get("aliases") or []),
            "publisher": str(venue.get("publisher") or ""),
            "issn": list(venue.get("issn") or []),
            "scope": list(venue.get("scope") or []),
            "tiers": dict(venue.get("tiers") or {}),
        },
        "tier": rv.tier_for(venue, field) if field else "",
        "peerReviewed": rv.peer_reviewed(venue),
        "label": rv.label(venue),
        "field": field,
        "registryVersion": version,
    }, headers={"Cache-Control": "no-store"})


async def sources_info(request: Request) -> JSONResponse:
    """来源清单与 key 配置状态;只报告配置,不探测外网。"""
    require_auth(request)
    sources = []
    for spec in rs.SPECS.values():
        key_env = spec.requires_key
        sources.append({
            "id": spec.id,
            "name": spec.name,
            "domains": list(spec.domains),
            "tier": spec.tier,
            "peerReviewed": spec.peer_reviewed,
            "fulltext": spec.fulltext,
            "keyEnv": key_env,
            "keyConfigured": bool(os.getenv(key_env, "").strip()) if key_env else True,
            "keyRequired": spec.key_required,
        })
    return JSONResponse({
        "sources": sources,
        "registryVersion": rv.registry_version(),
    }, headers={"Cache-Control": "no-store"})


async def _fill_oa(client: httpx.AsyncClient, results: list[dict]) -> None:
    """仅在没有 OA 标记时补齐;用于「仅免费全文」筛选,避免几十次外部请求。"""
    candidates = [
        item for item in results[:5]
        if item.get("doi") and not item.get("oaUrl")
        and item.get("oaStatus") in {"unknown", "closed", ""}
    ]
    if not candidates:
        return
    sem = asyncio.Semaphore(3)

    async def one(item: dict) -> None:
        async with sem:
            try:
                data = await asyncio.wait_for(
                    oa_resolver.resolve_doi(client, str(item["doi"])), timeout=4.5)
            except (asyncio.TimeoutError, httpx.HTTPError):
                return
            if data.get("isOa") and data.get("oaUrl"):
                item["oaStatus"] = data.get("oaStatus") or "green"
                item["oaUrl"] = data["oaUrl"]
                item["license"] = data.get("license") or item.get("license") or ""

    await asyncio.gather(*(one(item) for item in candidates), return_exceptions=True)


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

    author = (request.query_params.get("author") or "").strip()[:100]

    def _year(name: str) -> int | None:
        raw = (request.query_params.get(name) or "").strip()
        if not raw.isdigit():
            return None
        value = int(raw)
        return value if 1900 <= value <= time.localtime().tm_year + 1 else None

    year_from, year_to = _year("yearFrom"), _year("yearTo")
    if year_from and year_to and year_from > year_to:
        raise HTTPException(400, "起始年份不能晚于结束年份")
    filters = {"author": author, "yearFrom": year_from, "yearTo": year_to}
    has_filters = bool(author or year_from or year_to)
    field = (request.query_params.get("field") or "general").strip().lower()
    if field not in rs.ALL_FIELDS:
        field = "general"
    include_preprints = request.query_params.get("includePreprints", "true") not in {
        "false", "0", "no"}
    peer_reviewed_only = request.query_params.get("peerReviewed", "false") in {
        "true", "1", "yes"}
    oa_only = request.query_params.get("oaOnly", "false") in {"true", "1", "yes"}

    identifier = _detect_identifier(query)
    if identifier:
        kind, value = identifier
        async with httpx.AsyncClient(
            timeout=TIMEOUT, follow_redirects=True,
            headers={"User-Agent": "MathGuide/1.14 (research literature identifier)"},
        ) as client:
            try:
                if kind == "doi":
                    exact = await _crossref_doi(client, value)
                    exact += await _biorxiv_detail(client, value)
                elif kind == "arxiv":
                    exact = await _arxiv_by_id(client, value)
                elif kind == "pmcid":
                    exact = await _europe_pmc(client, f"PMCID:{value}", limit)
                else:
                    exact = await _europe_pmc(
                        client, f"EXT_ID:{value} AND SRC:MED", limit)
            except httpx.HTTPError as exc:
                raise HTTPException(
                    502, f"编号检索失败: {type(exc).__name__}") from exc
        results = _enrich(_merge(exact), field)[:limit]
        results = _mark_local(uid, results)
        return JSONResponse({
            "query": query, "results": results, "warnings": [],
            "identifier": {"type": kind, "value": value}, "field": field,
        })

    provider_funcs = {
        "crossref": _crossref,
        "arxiv": _arxiv,
        "europepmc": _europe_pmc,
        "pubmed": _pubmed,
        "inspire": _inspire,
        "zbmath": _zbmath,
        "openalex": _openalex,
        "semanticscholar": _semantic_scholar,
        "doaj": _doaj,
    }
    cache_key = _search_key(
        query, field, limit, filters if has_filters else None,
        include_preprints, peer_reviewed_only, oa_only)
    cached = _SEARCH_CACHE.get(cache_key)
    if cached and time.monotonic() - cached[0] < _SEARCH_TTL:
        return JSONResponse({
            "query": query,
            "results": _mark_local(uid, deepcopy(cached[1])),
            "warnings": list(cached[2]),
            "identifier": None, "field": field, "cached": True,
        })
    providers = [
        (spec.id, provider_funcs[spec.id])
        for spec in rs.specs_for(field, include_preprints)
        if spec.id in provider_funcs
    ]
    warnings: list[str] = []
    gathered: list[dict] = []
    async with httpx.AsyncClient(timeout=TIMEOUT, follow_redirects=True,
                                 headers={"User-Agent": "MathGuide/1.14 "
                                          "(research literature search)"}) as client:
        outcomes = await _run_providers(
            client, providers, query, limit, filters if has_filters else None,
            deadline=12.0 if field != "general" else DEADLINE)
    for name, outcome in outcomes:
        if isinstance(outcome, Exception):
            warnings.append(_provider_warning(name, outcome))
            continue
        gathered.extend(outcome)  # type: ignore[arg-type]

    results = _sort_results(_enrich(_merge(gathered), field), field)
    if oa_only:
        async with httpx.AsyncClient(
                timeout=TIMEOUT, follow_redirects=True,
                headers={"User-Agent": "MathGuide/1.14 (research oa fill)"}) as oa_client:
            await _fill_oa(oa_client, results)
    results = _filter_results(
        results, peer_reviewed=peer_reviewed_only,
        oa_only=oa_only, include_preprints=include_preprints)
    results = _sort_results(results, field)[:limit]
    if results or (not warnings and not oa_only):
        _SEARCH_CACHE[cache_key] = (
            time.monotonic(), deepcopy(results), list(warnings))
        if len(_SEARCH_CACHE) > _SEARCH_MAX:
            _SEARCH_CACHE.pop(next(iter(_SEARCH_CACHE)))
    results = _mark_local(uid, results)
    return JSONResponse({
        "query": query, "results": results, "warnings": warnings,
        "identifier": None, "field": field,
    })


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
            async def epmc_title(c: httpx.AsyncClient, q: str, n: int,
                                 f: dict | None = None) -> list[dict]:
                return await _europe_pmc(c, q, n, f, title_only=True)

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
            warnings.append(_provider_warning(name, outcome))
            continue
        items.extend(outcome)  # type: ignore[arg-type]
    norm_query = re.sub(r"\W+", "", query.lower())
    filtered = [
        i for i in _merge(items)
        if not _is_noise(i)
        and (not doi or i["doi"] != doi)
        and re.sub(r"\W+", "", i["title"].lower()) != norm_query
    ][:20]
    items = _enrich(filtered, "general")
    items = _mark_local(uid, items)
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


async def download_allowed_pdf(url: str) -> bytes:
    """供临时入库复用:严格白名单下载,返回 PDF 字节。"""
    if not _pdf_url_allowed(url):
        raise ValueError("该论文没有可用的开放获取 PDF")
    async with httpx.AsyncClient(
        timeout=30, follow_redirects=False,
        headers={"User-Agent": "MathGuide/1.11 (open access PDF)"},
    ) as client:
        return await _download_pdf(client, url)


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
