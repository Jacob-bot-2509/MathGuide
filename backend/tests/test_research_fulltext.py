import asyncio

import research_fulltext as rf


def test_normalize_identifiers_trims_and_lowercases_doi():
    result = rf.normalize_identifiers(
        doi=" 10.1000/ABC ", arxiv_id=" 2410.12345v2 ",
        pmid=" 123 ", pmcid=" PMC456 ", title="  A title  ")
    assert result["doi"] == "10.1000/abc"
    assert result["arxiv_id"] == "2410.12345v2"
    assert result["pmid"] == "123"
    assert result["pmcid"] == "PMC456"
    assert result["title"] == "A title"


def test_dedupe_prefers_pdf_candidate():
    landing = rf.make_candidate(
        "https://example.org/paper", kind="landing", source="openalex")
    pdf = rf.make_candidate(
        "https://arxiv.org/pdf/2410.12345", kind="pdf", source="arxiv",
        host_type="preprint", version="submittedVersion", is_preprint=True,
        server_downloadable=True)
    out = rf.dedupe_candidates([landing, pdf, pdf])
    assert len(out) == 2
    assert out[0]["kind"] == "pdf"


def test_choose_status_prefers_downloadable_pdf():
    pdf = rf.make_candidate(
        "https://arxiv.org/pdf/2410.12345", kind="pdf", source="arxiv",
        server_downloadable=True)
    landing = rf.make_candidate(
        "https://example.org/paper", kind="landing", source="openalex")
    assert rf.choose_status([landing, pdf], []) == "oa_pdf"


def test_choose_status_no_legal_copy_vs_unknown():
    assert rf.choose_status([], []) == "no_legal_copy"
    assert rf.choose_status([], ["openalex: timeout"]) == "unknown"


def test_resolve_doi_maps_oa_url_to_candidate(monkeypatch):
    async def fake_resolve(client, doi):
        return {
            "isOa": True, "oaUrl": "https://example.org/paper.pdf",
            "resolver": "unpaywall", "oaSource": "repository",
            "version": "acceptedVersion", "license": "cc_by",
            "error": False,
        }

    monkeypatch.setattr(rf.oa, "resolve_doi", fake_resolve)
    result = asyncio.run(rf.resolve(object(), doi="10.1/x"))
    assert result["status"] == "oa_landing"
    assert result["best"]["kind"] == "pdf"
    assert result["best"]["source"] == "unpaywall"
    assert result["identifier"] == {"type": "doi", "value": "10.1/x"}


def test_title_similarity_threshold():
    assert rf.title_similarity(
        "Attention Is All You Need", "Attention is all you need.") >= 0.92
    assert rf.title_similarity(
        "Attention Is All You Need", "A Survey of Databases") < 0.5


def test_title_candidates_are_ambiguous_when_two_close_matches():
    class Response:
        status_code = 200

        @staticmethod
        def json():
            return {"message": {"items": [
                {"title": ["Attention Is All You Need"], "DOI": "10.1/a",
                 "author": [{"given": "A", "family": "One"}],
                 "container-title": ["NeurIPS"], "issued": {"date-parts": [[2017]]}},
                {"title": ["Attention Is All You Need"], "DOI": "10.1/b",
                 "author": [{"given": "B", "family": "Two"}],
                 "container-title": ["NeurIPS"], "issued": {"date-parts": [[2018]]}},
            ]}}

    class Client:
        async def get(self, url, params=None, timeout=None):
            return Response()

    result = asyncio.run(rf.resolve(Client(), title="Attention Is All You Need"))
    assert result["status"] == "ambiguous"
    assert len(result["candidates"]) == 2
    assert result["best"] is None


def test_doi_closed_but_arxiv_pdf_still_returns_oa_pdf(monkeypatch):
    async def fake_doi(client, doi, errors):
        return []

    async def fake_arxiv(client, arxiv_id):
        return [rf.make_candidate(
            "https://arxiv.org/pdf/2410.12345", kind="pdf", source="arxiv",
            host_type="preprint", version="submittedVersion",
            is_preprint=True, server_downloadable=True)]

    monkeypatch.setattr(rf, "_doi_candidates", fake_doi)
    monkeypatch.setattr(rf, "_arxiv_candidates", fake_arxiv)
    result = asyncio.run(rf.resolve(
        object(), doi="10.1/closed", arxiv_id="2410.12345"))
    assert result["status"] == "oa_pdf"
    assert result["best"]["source"] == "arxiv"
    assert {item["type"] for item in result["matchedIdentifiers"]} == {"doi", "arxiv"}


def test_fulltext_endpoint_returns_status(monkeypatch):
    from starlette.applications import Starlette
    from starlette.routing import Route
    from starlette.testclient import TestClient

    async def fake_resolve(client, **kwargs):
        return {
            "status": "oa_pdf",
            "identifier": {"type": "doi", "value": "10.1/x"},
            "matchedIdentifiers": [{"type": "doi", "value": "10.1/x"}],
            "best": {"url": "https://arxiv.org/pdf/1", "serverDownloadable": True},
            "alternatives": [], "candidates": [], "reason": "",
        }

    monkeypatch.setattr(rf, "resolve", fake_resolve)
    monkeypatch.setattr(rf, "require_auth", lambda request: {"uid": "u"})
    app = Starlette(routes=[Route("/api/research/fulltext", rf.fulltext_lookup)])
    client = TestClient(app)
    res = client.get("/api/research/fulltext?doi=10.1/x")
    assert res.status_code == 200
    assert res.json()["status"] == "oa_pdf"
