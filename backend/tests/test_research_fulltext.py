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
