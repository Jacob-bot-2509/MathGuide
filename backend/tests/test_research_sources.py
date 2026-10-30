"""来源注册表、场所权威、OA 解析与分学科检索。"""
from __future__ import annotations

import asyncio
from xml.etree import ElementTree

import httpx
import pytest

import research_lit as rl
import research_oa as ro
import research_sources as rs
import research_venues as rv


@pytest.fixture(autouse=True)
def _clear_caches():
    ro._CACHE.clear()
    rl._SEARCH_CACHE.clear()
    yield
    ro._CACHE.clear()
    rl._SEARCH_CACHE.clear()


def test_source_specs_route_by_field():
    general = {s.id for s in rs.specs_for("general", True)}
    assert {"crossref", "arxiv", "europepmc", "openalex"} <= general
    assert "pubmed" not in general and "inspire" not in general and "zbmath" not in general

    physics = {s.id for s in rs.specs_for("physics", True)}
    assert "inspire" in physics and "physics" in rs.SPECS["inspire"].domains
    assert "pubmed" not in physics
    assert "arxiv" in physics

    biology = {s.id for s in rs.specs_for("biology", False)}
    assert "pubmed" in biology
    assert "arxiv" not in biology or rs.SPECS["arxiv"].tier != "preprint"
    assert "biorxiv" not in biology  # 预印本关闭


def test_venue_normalization_and_tier():
    assert rv.normalize_issn("0028-0836") == "00280836"
    assert rv.normalize_issn("bad") == ""
    venue = rv.lookup(["0028-0836"], "Nature")
    assert venue and venue["name"] == "Nature"
    assert rv.tier_for(venue, "physics") == "T0"
    assert rv.tier_for(venue, "math") == "T0"
    prl = rv.lookup([], "Physical Review Letters")
    assert prl and rv.tier_for(prl, "physics") == "T1"
    assert rv.tier_for(prl, "biology") == ""


def test_registry_covers_p0_disciplines():
    by_name = rv._registry()[1]
    venues = by_name.values()
    for field in ("math", "physics", "chemistry", "biology"):
        assert sum(
            field in ((venue.get("tiers") or {}))
            for venue in venues
        ) >= 20


def test_enrich_sets_tier_and_preprint_label():
    peer = rl._result(title="Nature paper", venue="Nature", issn="0028-0836",
                      peerReviewed=True, sources=["crossref"])
    pre = rl._result(title="arXiv paper", venue="arXiv", sources=["arxiv"],
                     articleType="preprint", sourceTier="preprint")
    journal_pre = rl._result(
        title="Nature preprint", venue="Nature", issn="0028-0836",
        sources=["inspire"], articleType="preprint", sourceTier="preprint")
    rl._enrich([peer, pre, journal_pre], "physics")
    assert peer["venueTier"] == "T0"
    assert peer["landingUrl"] == peer["url"]
    assert pre["venueTier"] == "P"
    assert journal_pre["venueTier"] == "T0"
    assert journal_pre["peerReviewed"] is False
    assert peer["fields"] == ["biology", "chemistry", "math", "physics"]


def test_merge_keeps_new_metadata_and_retraction():
    preprint = rl._result(title="Paper", doi="10.1/x", sources=["arxiv"],
                          peerReviewed=False, venueTier="P", oaStatus="green",
                          oaUrl="https://arxiv.org/pdf/1.pdf",
                          articleType="preprint", sourceTier="preprint")
    published = rl._result(title="Paper", doi="10.1/x", sources=["crossref"],
                           peerReviewed=True, venueTier="T2", oaStatus="gold",
                           retractionStatus="retracted", articleType="research",
                           sourceTier="authority")
    merged = rl._merge([preprint, published])[0]
    assert merged["peerReviewed"] is True
    assert merged["venueTier"] == "T2"
    assert merged["oaStatus"] == "gold"
    assert merged["retractionStatus"] == "retracted"
    assert merged["articleType"] == "research"
    assert merged["sourceTier"] == "authority"


def test_arxiv_repository_pdf_is_green_not_gold():
    entry = ElementTree.fromstring(
        '<entry xmlns="http://www.w3.org/2005/Atom">'
        '<id>http://arxiv.org/abs/2401.00001</id>'
        '<published>2024-01-01T00:00:00Z</published>'
        '<title>Repository paper</title><summary>Abstract</summary>'
        '<author><name>Author</name></author>'
        '<link rel="alternate" href="http://arxiv.org/abs/2401.00001"/>'
        '<category term="math.AG"/></entry>')
    item = rl._arxiv_entry(entry)
    assert item is not None
    assert item["oaStatus"] == "green"
    assert item["peerReviewed"] is False
    assert item["articleType"] == "preprint"


def test_oa_url_requires_https():
    assert rl._result(oaUrl="http://example.org/paper.pdf")["oaUrl"] == ""
    assert rl._result(
        oaUrl="https://example.org/paper.pdf"
    )["oaUrl"] == "https://example.org/paper.pdf"


def test_filter_results_peer_and_oa():
    peer = rl._result(title="A", peerReviewed=True, oaStatus="diamond")
    pre = rl._result(title="B", peerReviewed=False, articleType="preprint",
                     sourceTier="preprint", oaStatus="unknown")
    noise = rl._result(title="Front Matter", peerReviewed=True, oaStatus="unknown")
    out = rl._filter_results([peer, pre, noise], peer_reviewed=True, oa_only=False,
                             include_preprints=True)
    assert [x["title"] for x in out] == ["A"]
    out = rl._filter_results([peer, pre], peer_reviewed=False, oa_only=True,
                             include_preprints=True)
    assert [x["title"] for x in out] == ["A"]


def test_pubmed_year_to_only_sets_range_and_filters_results():
    class Response:
        def __init__(self, *, payload=None, text=""):
            self._payload = payload
            self.text = text
            self.status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return self._payload

    class Client:
        def __init__(self):
            self.params = []

        async def get(self, url, params=None):
            self.params.append(dict(params or {}))
            if url.endswith("esearch.fcgi"):
                return Response(payload={"esearchresult": {"idlist": ["1"]}})
            return Response(text=(
                "<PubmedArticleSet><PubmedArticle><MedlineCitation>"
                "<PMID>1</PMID><Article><ArticleTitle>Older result</ArticleTitle>"
                "<Journal><ISSN>0028-0836</ISSN><JournalIssue><PubDate>"
                "<Year>2024</Year></PubDate></JournalIssue><Title>Journal</Title>"
                "</Journal></Article></MedlineCitation></PubmedArticle>"
                "</PubmedArticleSet>"))

    client = Client()
    results = asyncio.run(
        rl._pubmed(client, "test", 5, {"yearFrom": None, "yearTo": 2020}))
    assert client.params[0]["mindate"] == "1900"
    assert client.params[0]["maxdate"] == "2020"
    assert results == []


def test_zbmath_skips_license_placeholder_records():
    class Response:
        @staticmethod
        def json():
            return {"result": [{
                "title": {
                    "title": "zbMATH Open Web Interface contents unavailable "
                             "due to conflicting licenses."
                },
                "year": "2024",
            }]}

        @staticmethod
        def raise_for_status():
            return None

    class Client:
        async def get(self, url, params=None):
            return Response()

    assert asyncio.run(rl._zbmath(Client(), "algebra", 5)) == []


def test_zbmath_uses_series_venue_and_issn():
    class Response:
        @staticmethod
        def json():
            return {"result": [{
                "title": {"title": "A math paper"},
                "year": "2010",
                "source": {
                    "source": "Proc. Am. Math. Soc. 138, 85-99 (2010).",
                    "series": [{
                        "title": "Proceedings of the American Mathematical Society",
                        "publisher": "American Mathematical Society",
                        "issn": [{"number": "0002-9939"}],
                    }],
                },
                "document_type": {"description": "journal article"},
                "zbmath_url": "https://zbmath.org/123",
            }]}

        @staticmethod
        def raise_for_status():
            return None

    class Client:
        async def get(self, url, params=None):
            return Response()

    item = asyncio.run(rl._zbmath(Client(), "algebra", 5))[0]
    assert item["venue"] == "Proceedings of the American Mathematical Society"
    assert item["issn"] == "0002-9939"
    assert item["publisher"] == "American Mathematical Society"


def test_inspire_uses_control_number_as_landing_fallback():
    class Response:
        @staticmethod
        def json():
            return {"hits": {"hits": [{
                "id": "123456",
                "metadata": {
                    "titles": [{"title": "A physics paper"}],
                    "document_type": ["article"],
                    "control_number": 123456,
                },
            }]}}

        @staticmethod
        def raise_for_status():
            return None

    class Client:
        async def get(self, url, params=None):
            return Response()

    item = asyncio.run(rl._inspire(Client(), "physics", 5))[0]
    assert item["url"] == "https://inspirehep.net/literature/123456"


def test_openalex_oa_resolver_uses_configured_key(monkeypatch):
    class Response:
        status_code = 200

        @staticmethod
        def json():
            return {
                "oa_status": "gold",
                "is_oa": True,
                "best_oa_location": {"pdf_url": "https://example.org/paper.pdf"},
            }

    class Client:
        params = None
        calls = 0

        async def get(self, url, params=None, timeout=None):
            self.calls += 1
            self.params = dict(params or {})
            return Response()

    monkeypatch.delenv("MG_UNPAYWALL_EMAIL", raising=False)
    monkeypatch.setenv("MG_OPENALEX_API_KEY", "test-key")
    client = Client()
    result = asyncio.run(ro.resolve_doi(client, "10.1/x"))
    cached = asyncio.run(ro.resolve_doi(client, "10.1/x"))
    assert client.params["api_key"] == "test-key"
    assert client.calls == 1
    assert result["resolver"] == "openalex"
    assert cached == result
    assert result["oaUrl"] == "https://example.org/paper.pdf"
    assert result["error"] is False


def test_openalex_oa_resolver_marks_transport_failure(monkeypatch):
    class Client:
        async def get(self, url, params=None, timeout=None):
            raise httpx.TimeoutException("timeout")

    monkeypatch.delenv("MG_UNPAYWALL_EMAIL", raising=False)
    result = asyncio.run(ro.resolve_doi(Client(), "10.1/x"))
    assert result["isOa"] is False
    assert result["error"] is True


def test_openalex_oa_resolver_marks_rate_limit(monkeypatch):
    class Response:
        status_code = 429

    class Client:
        async def get(self, url, params=None, timeout=None):
            return Response()

    monkeypatch.delenv("MG_UNPAYWALL_EMAIL", raising=False)
    result = asyncio.run(ro.resolve_doi(Client(), "10.1/x"))
    assert result["isOa"] is False
    assert result["error"] is True


def test_unpaywall_closed_result_survives_openalex_failure(monkeypatch):
    class Response:
        def __init__(self, status_code, payload=None):
            self.status_code = status_code
            self.payload = payload

        def json(self):
            return self.payload

    class Client:
        calls = 0

        async def get(self, url, params=None, timeout=None):
            self.calls += 1
            if "unpaywall" in url:
                return Response(200, {
                    "is_oa": False,
                    "oa_status": "closed",
                    "best_oa_location": {},
                })
            return Response(429)

    monkeypatch.setenv("MG_UNPAYWALL_EMAIL", "test@example.com")
    client = Client()
    result = asyncio.run(ro.resolve_doi(client, "10.1/closed"))
    assert result["isOa"] is False
    assert result["resolver"] == "unpaywall"
    assert result["error"] is False
    assert client.calls == 2


def test_parse_unpaywall_and_openalex():
    assert ro._safe_url("https://example.org/a b") == ""
    assert ro._safe_url("https://user:pass@example.org/a") == ""
    unpaywall = ro.parse_unpaywall({
        "is_oa": True, "oa_status": "gold",
        "best_oa_location": {"url_for_pdf": "https://example.org/a.pdf",
                             "license": "cc_by", "host_type": "publisher"},
    })
    assert unpaywall["isOa"] is True
    assert unpaywall["oaStatus"] == "gold"
    assert unpaywall["oaUrl"].endswith("a.pdf")

    openalex = ro.parse_openalex({
        "oa_status": "green",
        "best_oa_location": {"pdf_url": "http://insecure.example/a.pdf"},
    })
    assert openalex["isOa"] is False
    assert openalex["oaUrl"] == ""

    openalex = ro.parse_openalex({
        "open_access": {"is_oa": True, "oa_status": "gold"},
        "best_oa_location": {"pdf_url": "https://oa.example/a.pdf",
                             "license": "cc_by"},
    })
    assert openalex["isOa"] is True
    assert openalex["oaStatus"] == "gold"


def test_fill_oa_updates_unknown_items(monkeypatch):
    import asyncio

    async def fake_resolve(client, doi):
        return {"isOa": True, "oaStatus": "gold",
                "oaUrl": f"https://oa.example/{doi}.pdf", "license": "cc_by"}

    monkeypatch.setattr(rl.oa_resolver, "resolve_doi", fake_resolve)
    items = [
        rl._result(title="A", doi="10.1/a", oaStatus="unknown"),
        rl._result(title="B", doi="10.1/b", oaStatus="closed"),
        rl._result(title="C", doi="", oaStatus="unknown"),
    ]
    asyncio.run(rl._fill_oa(None, items))
    assert items[0]["oaStatus"] == "gold"
    assert items[0]["oaUrl"].endswith("10.1/a.pdf")
    assert items[1]["oaStatus"] == "gold"
    assert items[2]["oaUrl"] == ""


def test_search_fills_oa_after_ranking(monkeypatch):
    from starlette.applications import Starlette
    from starlette.routing import Route
    from starlette.testclient import TestClient

    seen: list[str] = []

    async def crossref(client, query, limit, filters=None):
        return [
            rl._result(title="Low", doi="10.1/low", citations=1,
                       sources=["crossref"], oaStatus="unknown"),
            rl._result(title="High", doi="10.1/high", citations=100,
                       sources=["crossref"], oaStatus="unknown"),
        ]

    async def empty(client, query, limit, filters=None):
        return []

    async def fill_oa(client, results):
        seen.extend(item["title"] for item in results)
        for item in results:
            item["oaStatus"] = "gold"

    monkeypatch.setattr(rl, "require_auth", lambda request: {"uid": "u-rank"})
    monkeypatch.setattr(rl, "_crossref", crossref)
    monkeypatch.setattr(rl, "_fill_oa", fill_oa)
    for name in ("_arxiv", "_europe_pmc", "_openalex",
                 "_semantic_scholar", "_doaj", "_pubmed",
                 "_inspire", "_zbmath"):
        monkeypatch.setattr(rl, name, empty)
    app = Starlette(routes=[Route("/api/research/literature", rl.search)])
    res = TestClient(app).get(
        "/api/research/literature?q=test&oaOnly=true&limit=10")
    assert res.status_code == 200, res.text
    assert seen[:2] == ["High", "Low"]
    assert [item["title"] for item in res.json()["results"]] == ["High", "Low"]


def test_search_does_not_cache_failed_empty_result(monkeypatch):
    from starlette.applications import Starlette
    from starlette.routing import Route
    from starlette.testclient import TestClient

    calls = 0

    async def failing(client, query, limit, filters=None):
        nonlocal calls
        calls += 1
        raise TimeoutError()

    async def empty(client, query, limit, filters=None):
        return []

    monkeypatch.setattr(rl, "require_auth", lambda request: {"uid": "u-fail"})
    monkeypatch.setattr(rl, "_crossref", failing)
    for name in ("_arxiv", "_europe_pmc", "_openalex",
                 "_semantic_scholar", "_doaj", "_pubmed",
                 "_inspire", "_zbmath"):
        monkeypatch.setattr(rl, name, empty)
    app = Starlette(routes=[Route("/api/research/literature", rl.search)])
    client = TestClient(app)
    for _ in range(2):
        res = client.get("/api/research/literature?q=retry")
        assert res.status_code == 200
        assert res.json()["results"] == []
    assert calls == 2


def test_oa_endpoint_requires_doi(monkeypatch):
    from starlette.applications import Starlette
    from starlette.routing import Route
    from starlette.testclient import TestClient

    monkeypatch.setattr(rl, "require_auth", lambda request: {"uid": "u-oa"})
    app = Starlette(routes=[Route("/api/research/literature/oa", rl.oa_lookup)])
    client = TestClient(app)
    assert client.get("/api/research/literature/oa").status_code == 400


def test_semantic_scholar_attempts_keyless(monkeypatch):
    class Response:
        @staticmethod
        def raise_for_status():
            return None

        @staticmethod
        def json():
            return {"data": [{
                "title": "S2 paper", "year": 2024, "venue": "Nature",
                "externalIds": {"DOI": "10.1/x"}, "authors": [],
                "citationCount": 3, "publicationTypes": ["JournalArticle"],
                "openAccessPdf": {"url": "https://example.org/x.pdf"},
            }]}

    class Client:
        headers = "unset"

        async def get(self, url, params=None, headers=None):
            self.headers = headers
            return Response()

    monkeypatch.delenv("MG_S2_API_KEY", raising=False)
    client = Client()
    items = asyncio.run(rl._semantic_scholar(client, "x", 5))
    assert client.headers is None
    assert items[0]["doi"] == "10.1/x"
    assert items[0]["peerReviewed"] is True
    assert items[0]["oaUrl"] == "https://example.org/x.pdf"


def test_venues_endpoint(monkeypatch):
    from starlette.applications import Starlette
    from starlette.routing import Route
    from starlette.testclient import TestClient

    monkeypatch.setattr(rl, "require_auth", lambda request: {"uid": "u-venue"})
    app = Starlette(routes=[Route("/api/research/venues", rl.venues_lookup)])
    client = TestClient(app)
    res = client.get("/api/research/venues?issn=0028-0836&field=physics")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["found"] is True
    assert body["tier"] == "T0"
    assert body["venue"]["name"] == "Nature"
    assert client.get("/api/research/venues").status_code == 400
    assert client.get("/api/research/venues?name=NoSuchVenue").json()["found"] is False


def test_sources_endpoint(monkeypatch):
    from starlette.applications import Starlette
    from starlette.routing import Route
    from starlette.testclient import TestClient

    monkeypatch.setattr(rl, "require_auth", lambda request: {"uid": "u-src"})
    app = Starlette(routes=[Route("/api/research/sources", rl.sources_info)])
    body = TestClient(app).get("/api/research/sources").json()
    by_id = {item["id"]: item for item in body["sources"]}
    assert by_id["semanticscholar"]["keyEnv"] == ""
    assert by_id["openalex"]["keyEnv"] == ""
    assert by_id["pubmed"]["keyEnv"] == "MG_NCBI_API_KEY"
    assert body["registryVersion"]


def test_get_doc_endpoint(monkeypatch):
    from starlette.applications import Starlette
    from starlette.routing import Route
    from starlette.testclient import TestClient

    import research_corpus as rc

    row = {"id": "d1", "name": "a.pdf", "deletedAt": 0, "title": "A paper",
           "venue": "Nature", "oaStatus": "gold"}

    def fake_doc_row(uid, doc_id):
        return dict(row) if uid == "u-doc" and doc_id == "d1" else None

    monkeypatch.setattr(rl, "require_auth", lambda request: {"uid": "u-doc"})
    monkeypatch.setattr(rc, "require_auth", lambda request: {"uid": "u-doc"})
    monkeypatch.setattr(rc, "_doc_row", fake_doc_row)
    app = Starlette(routes=[
        Route("/api/research/docs/{doc_id}", rc.get_doc, methods=["GET"])])
    client = TestClient(app)
    res = client.get("/api/research/docs/d1")
    assert res.status_code == 200
    assert res.json()["doc"]["venue"] == "Nature"
    assert client.get("/api/research/docs/missing").status_code == 404


def test_biorxiv_detail_only_for_biorxiv_doi():
    class Response:
        status_code = 200

        @staticmethod
        def json():
            return {"collection": [{
                "title": "A preprint", "authors": "A. Author",
                "date": "2024-05-01", "version": "2", "license": "cc_by",
                "abstract": "Abstract", "server": "biorxiv",
            }]}

    class Client:
        calls = 0

        async def get(self, url):
            self.calls += 1
            return Response()

    client = Client()
    assert asyncio.run(rl._biorxiv_detail(client, "10.1000/other")) == []
    assert client.calls == 0
    items = asyncio.run(rl._biorxiv_detail(client, "10.1101/2024.05.01.123456"))
    assert items[0]["articleType"] == "preprint"
    assert items[0]["peerReviewed"] is False
    assert items[0]["year"] == 2024
    assert items[0]["oaUrl"].endswith("v2.full.pdf")
    assert client.calls == 2


def test_search_field_physics_uses_inspire(monkeypatch):
    from starlette.applications import Starlette
    from starlette.routing import Route
    from starlette.testclient import TestClient

    called: list[str] = []

    async def fake_inspire(client, query, limit, filters=None):
        called.append("inspire")
        return [rl._result(title="Higgs", sources=["inspire"], peerReviewed=True,
                           venue="Physical Review Letters", venueTier="T1")]

    async def empty(client, query, limit, filters=None):
        return []

    monkeypatch.setattr(rl, "require_auth", lambda request: {"uid": "u-phys"})
    monkeypatch.setattr(rl, "_inspire", fake_inspire)
    for name in ("_crossref", "_arxiv", "_europe_pmc", "_openalex",
                 "_semantic_scholar", "_doaj", "_pubmed", "_zbmath"):
        monkeypatch.setattr(rl, name, empty)
    app = Starlette(routes=[Route("/api/research/literature", rl.search)])
    client = TestClient(app)
    res = client.get("/api/research/literature?q=higgs&field=physics")
    assert res.status_code == 200, res.text
    assert called == ["inspire"]
    body = res.json()
    assert body["field"] == "physics"
    assert body["results"][0]["venueTier"] == "T1"
