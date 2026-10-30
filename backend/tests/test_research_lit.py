"""文献发现:聚合、去重与接口契约(不访问真实网络)。"""
from __future__ import annotations

import research_lit as rl


def test_merge_dedupes_by_doi_and_keeps_longer_abstract():
    a = rl._result(title="Paper A", doi="10.1/x", abstract="short",
                   citations=3, sources=["crossref"], year=2020)
    b = rl._result(title="Paper A", doi="10.1/x", abstract="a much longer abstract",
                   citations=9, sources=["arxiv"], year=2020)
    merged = rl._merge([a, b])
    assert len(merged) == 1
    assert merged[0]["abstract"] == "a much longer abstract"
    assert merged[0]["citations"] == 9
    assert sorted(merged[0]["sources"]) == ["arxiv", "crossref"]


def test_openalex_abstract_reconstruction():
    item = {"abstract_inverted_index": {"We": [0], "study": [1], "gaps": [2]}}
    assert rl._openalex_abstract(item) == "We study gaps"


def test_doi_normalization():
    assert rl._doi("https://doi.org/10.1000/ABC") == "10.1000/abc"
    assert rl._doi("doi: 10.1000/xyz") == "10.1000/xyz"


def test_search_endpoint_merges_providers(monkeypatch):
    from starlette.applications import Starlette
    from starlette.routing import Route
    from starlette.testclient import TestClient

    async def fake_crossref(client, query, limit, filters=None):
        return [rl._result(title="Stable signal recovery", doi="10.1/a",
                           citations=5, sources=["crossref"], year=2020)]

    async def fake_arxiv(client, query, limit, filters=None):
        return [rl._result(title="Stable signal recovery preprint", doi="10.1/a",
                           citations=1, sources=["arxiv"], year=2020)]

    async def empty(client, query, limit, filters=None):
        return []

    monkeypatch.setattr(rl, "require_auth", lambda request: {"uid": "u-lit"})
    for name in ("_crossref", "_arxiv", "_europe_pmc", "_openalex", "_semantic_scholar", "_doaj"):
        monkeypatch.setattr(rl, name, fake_crossref if name == "_crossref"
                            else fake_arxiv if name == "_arxiv" else empty)
    app = Starlette(routes=[
        Route("/api/research/literature", rl.search),
    ])
    client = TestClient(app)
    res = client.get("/api/research/literature?q=signal recovery")
    assert res.status_code == 200, res.text
    body = res.json()
    assert len(body["results"]) == 1
    assert body["results"][0]["doi"] == "10.1/a"
    assert sorted(body["results"][0]["sources"]) == ["arxiv", "crossref"]
    assert body["warnings"] == []


def test_search_endpoint_validates_query(monkeypatch):
    from starlette.applications import Starlette
    from starlette.routing import Route
    from starlette.testclient import TestClient

    monkeypatch.setattr(rl, "require_auth", lambda request: {"uid": "u-lit2"})
    app = Starlette(routes=[Route("/api/research/literature", rl.search)])
    client = TestClient(app)
    assert client.get("/api/research/literature?q=a").status_code == 400


def test_pdf_url_allowlist():
    assert rl._pdf_url_allowed("https://arxiv.org/pdf/2501.00001.pdf")
    assert rl._pdf_url_allowed("https://www.ebi.ac.uk/europepmc/webservices/rest/PMC1/fullTextPDF")
    assert not rl._pdf_url_allowed("http://arxiv.org/pdf/1.pdf")
    assert not rl._pdf_url_allowed("https://evil-arxiv.org/a.pdf")
    assert not rl._pdf_url_allowed("https://example.com/a.pdf")


def test_open_pdf_endpoint(monkeypatch, tmp_path):
    from starlette.applications import Starlette
    from starlette.routing import Route
    from starlette.testclient import TestClient

    monkeypatch.setattr(rl, "require_auth", lambda request: {"uid": "u-pdf"})
    monkeypatch.setattr(rl.rc, "DATA_DIR", tmp_path / "research")
    opened: list = []

    async def fake_download(client, url):
        return b"%PDF-1.4 fake bytes"

    monkeypatch.setattr(rl, "_download_pdf", fake_download)
    monkeypatch.setattr(rl, "_open_in_office", lambda path: opened.append(path) or True)
    app = Starlette(routes=[
        Route("/api/research/literature/open-pdf", rl.open_pdf, methods=["POST"]),
    ])
    client = TestClient(app)

    bad = client.post("/api/research/literature/open-pdf",
                      json={"url": "https://example.com/a.pdf"},
                      headers={"host": "127.0.0.1:8000"})
    assert bad.status_code == 400

    res = client.post("/api/research/literature/open-pdf",
                      json={"url": "https://arxiv.org/pdf/2501.00001.pdf"},
                      headers={"host": "127.0.0.1:8000"})
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["opened"] is True and body["file"].endswith(".pdf")
    assert opened and opened[0].exists()


def test_detect_identifier():
    assert rl._detect_identifier("10.1234/abcd.5678") == ("doi", "10.1234/abcd.5678")
    assert rl._detect_identifier("https://doi.org/10.1234/ABCD.5678.") == (
        "doi", "10.1234/abcd.5678")
    assert rl._detect_identifier("arXiv:2401.12345v2") == ("arxiv", "2401.12345")
    assert rl._detect_identifier("2401.12345") == ("arxiv", "2401.12345")
    assert rl._detect_identifier("PMC1234567") == ("pmcid", "PMC1234567")
    assert rl._detect_identifier("PMID: 12345678") == ("pmid", "12345678")
    assert rl._detect_identifier("sparse attention") is None


def test_search_identifier_bypasses_keyword_providers(monkeypatch):
    from starlette.applications import Starlette
    from starlette.routing import Route
    from starlette.testclient import TestClient

    async def fake_doi(client, doi):
        return [rl._result(title="Exact paper", doi=doi, sources=["crossref"])]

    async def should_not_run(client, query, limit, filters=None):
        raise AssertionError("keyword provider must not run")

    monkeypatch.setattr(rl, "require_auth", lambda request: {"uid": "u-id"})
    monkeypatch.setattr(rl, "_crossref_doi", fake_doi)
    for name in ("_crossref", "_arxiv", "_europe_pmc", "_openalex", "_semantic_scholar", "_doaj"):
        monkeypatch.setattr(rl, name, should_not_run)
    app = Starlette(routes=[Route("/api/research/literature", rl.search)])
    client = TestClient(app)
    res = client.get("/api/research/literature?q=10.1234/abcd.5678")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["identifier"] == {"type": "doi", "value": "10.1234/abcd.5678"}
    assert body["results"][0]["title"] == "Exact paper"


def test_search_passes_author_and_year_filters(monkeypatch):
    from starlette.applications import Starlette
    from starlette.routing import Route
    from starlette.testclient import TestClient

    seen: list[dict | None] = []

    async def fake(client, query, limit, filters=None):
        seen.append(filters)
        return []

    monkeypatch.setattr(rl, "require_auth", lambda request: {"uid": "u-filter"})
    for name in ("_crossref", "_arxiv", "_europe_pmc", "_openalex", "_semantic_scholar", "_doaj"):
        monkeypatch.setattr(rl, name, fake)
    app = Starlette(routes=[Route("/api/research/literature", rl.search)])
    client = TestClient(app)
    res = client.get(
        "/api/research/literature?q=attention&author=Zhang&yearFrom=2020&yearTo=2024")
    assert res.status_code == 200
    assert seen and seen[0] == {"author": "Zhang", "yearFrom": 2020, "yearTo": 2024}

    bad = client.get("/api/research/literature?q=attention&yearFrom=2024&yearTo=2020")
    assert bad.status_code == 400
