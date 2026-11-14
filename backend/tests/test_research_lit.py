"""文献发现:聚合、去重与接口契约(不访问真实网络)。"""
from __future__ import annotations

import asyncio
import os

import httpx
import pytest

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


def test_dblp_parses_hit_list():
    class Response:
        status_code = 200

        @staticmethod
        def json():
            return {"result": {"hits": {"hit": [
                {"info": {
                    "title": "Graph Neural Networks.",
                    "authors": {"author": [{"text": "Ada"}, {"text": "Bo"}]},
                    "venue": "NeurIPS",
                    "year": "2024",
                    "doi": "10.1234/gnn",
                    "ee": "https://doi.org/10.1234/gnn",
                    "url": "https://dblp.org/rec/conf/neurips/x",
                }},
            ]}}}

    class Client:
        async def get(self, url, params=None, timeout=None):
            assert "dblp.org/search/publ/api" in url
            return Response()

    items = asyncio.run(rl._dblp(Client(), "graph neural networks", 5, None))
    assert len(items) == 1
    assert items[0]["title"] == "Graph Neural Networks."
    assert items[0]["doi"] == "10.1234/gnn"
    assert items[0]["sources"] == ["dblp"]


def test_dblp_bot_challenge_is_reported():
    class Response:
        status_code = 202
        headers = {"content-type": "text/html; charset=utf-8"}

    class Client:
        async def get(self, url, params=None, timeout=None):
            return Response()

    with pytest.raises(RuntimeError, match="bot"):
        asyncio.run(rl._dblp(Client(), "graph neural networks", 5, None))


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


def test_arxiv_doi_maps_to_reader_pdf():
    assert rl._arxiv_pdf_from_doi("10.48550/arXiv.2501.06425") == (
        "https://arxiv.org/pdf/2501.06425.pdf")
    assert rl._arxiv_pdf_from_doi("10.48550/arxiv.2501.06425v2") == (
        "https://arxiv.org/pdf/2501.06425v2.pdf")
    assert rl._arxiv_pdf_from_doi("10.1234/not-arxiv") == ""
    item = rl._result(title="Tensor Product Attention", doi="10.48550/arxiv.2501.06425")
    enriched = rl._enrich([item], "general")[0]
    assert enriched["pdfUrl"] == "https://arxiv.org/pdf/2501.06425.pdf"


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


# ---------- G3 补充:纯映射 / 归一化 / 去重(不访问网络) ----------


class _Resp:
    """最小 httpx.Response 替身:状态码 + JSON + 文本 + 头。"""

    def __init__(self, status_code=200, json_data=None, text="", headers=None):
        self.status_code = status_code
        self._json = json_data
        self.text = text
        self.headers = headers or {}

    def json(self):
        if isinstance(self._json, Exception):
            raise self._json
        return self._json

    def raise_for_status(self):
        if self.status_code >= 400:
            request = httpx.Request("GET", "https://provider.test/")
            raise httpx.HTTPStatusError(
                "bad status", request=request,
                response=httpx.Response(self.status_code, request=request))


class _Client:
    """按 URL 片段返回录好的响应;记录请求参数用于断言查询构造。"""

    def __init__(self, routes):
        self.routes = list(routes)
        self.calls = []

    async def get(self, url, params=None, headers=None, timeout=None):
        self.calls.append({"url": url, "params": params, "headers": headers})
        for prefix, queue in self.routes:
            if prefix in url:
                item = queue.pop(0) if len(queue) > 1 else queue[0]
                if isinstance(item, Exception):
                    raise item
                return item
        raise AssertionError(f"未预期的请求: {url}")


class _Body:
    """流式响应替身:只有 headers/status_code/aiter_bytes。"""

    def __init__(self, chunks, status_code=200, headers=None):
        self._chunks = list(chunks)
        self.status_code = status_code
        self.headers = headers or {}

    async def aiter_bytes(self):
        for chunk in self._chunks:
            yield chunk

    def raise_for_status(self):
        _Resp(status_code=self.status_code).raise_for_status()


class _StreamContext:
    def __init__(self, body):
        self.body = body

    async def __aenter__(self):
        return self.body

    async def __aexit__(self, *exc):
        return False


class _StreamClient:
    """同时支持 `client.stream(...)` 与 `async with client` 的下载客户端替身。"""

    def __init__(self, handler):
        self.handler = handler
        self.urls = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    def stream(self, method, url, follow_redirects=False):
        self.urls.append(url)
        return _StreamContext(self.handler(url))

    async def get(self, url, params=None, **kwargs):
        return self.handler(url)


class _HttpFactory:
    """把 httpx.AsyncClient 换成受控客户端(仅注入 rl.httpx,用例结束自动还原)。"""

    def __init__(self, handler):
        self.handler = handler

    def __call__(self, *args, **kwargs):
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def get(self, url, params=None, **kwargs):
        return self.handler(url, params)


class _DeniedLimiter:
    def allow(self, key):
        return False


def _allow_public(monkeypatch, value=True):
    async def fake(url):
        return value

    monkeypatch.setattr(rl.research_urls, "resolves_to_public_host", fake)


def _lit_app():
    from starlette.applications import Starlette
    from starlette.routing import Route

    return Starlette(routes=[
        Route("/api/research/literature", rl.search),
        Route("/api/research/literature/related", rl.related),
        Route("/api/research/literature/oa", rl.oa_lookup),
        Route("/api/research/literature/venues", rl.venues_lookup),
        Route("/api/research/literature/sources", rl.sources_info),
    ])


def test_clean_strips_html_and_truncates():
    assert rl._clean("<p>Graph <b>neural</b> nets</p>") == "Graph neural nets"
    assert rl._clean(None) == ""
    assert rl._clean("  ") == ""
    assert rl._clean("x" * 50, 10) == "x" * 10


def test_result_drops_unsafe_urls_and_normalizes_fields():
    item = rl._result(
        title="T",
        url="javascript:alert(1)",
        pdfUrl="https://arxiv.org/pdf/1.pdf",
        oaUrl="http://arxiv.org/pdf/1.pdf",
        fields="math",
    )
    assert item["url"] == ""
    assert item["pdfUrl"] == "https://arxiv.org/pdf/1.pdf"
    assert item["oaUrl"] == ""          # oaUrl 只接受 https
    assert item["fields"] == []         # 非 list 归一为空列表

    assert rl._result(url="https://user:pw@example.test/a")["url"] == ""
    assert rl._result(url="https://exa mple.test/a")["url"] == ""
    assert rl._result(pdfUrl="https://example.test/a\x01")["pdfUrl"] == ""
    assert rl._result(url="")["url"] == ""


def test_arxiv_pdf_from_doi_variants():
    assert rl._arxiv_pdf_from_doi("10.48550/arXiv.2401.12345v2") == (
        "https://arxiv.org/pdf/2401.12345v2.pdf")
    assert rl._arxiv_pdf_from_doi("10.48550/arxiv.not-an-id") == ""
    assert rl._arxiv_pdf_from_doi("10.1000/xyz") == ""
    assert rl._arxiv_pdf_from_doi(None) == ""


def test_doi_normalization_handles_prefixes_and_none():
    assert rl._doi("http://dx.doi.org/10.1000/AbC") == "10.1000/abc"
    assert rl._doi(None) == ""
    assert rl._doi(" 10.1000/x  ") == "10.1000/x"
    assert len(rl._doi("10.1000/" + "x" * 400)) == 200


def test_search_key_is_stable_and_sensitive():
    a = rl._search_key("q", "math", 5, {"author": "Li"}, True, False, False)
    b = rl._search_key("q", "math", 5, {"author": "Li"}, True, False, False)
    c = rl._search_key("q", "math", 6, {"author": "Li"}, True, False, False)
    assert a == b and a != c and len(a) == 64
    assert rl._search_key("q", "math", 5, None, True, False, False) != a


def test_crossref_item_maps_license_retraction_and_type():
    item = {
        "type": "journal-article",
        "title": ["A <i>clean</i> title"],
        "author": [{"family": "Zhang"}, {"name": "Consortium"}, {}],
        "issued": {"date-parts": [[2021, 3]]},
        "DOI": "https://doi.org/10.1000/ABC",
        "container-title": ["Nature"],
        "URL": "https://doi.org/10.1000/abc",
        "abstract": "<jats:p>We prove it.</jats:p>",
        "is-referenced-by-count": "17",
        "ISSN": ["0028-0836", "1476-4687", "9999-0000", "0000-1111"],
        "publisher": "Springer Nature",
        "license": [{"URL": ""}, "junk",
                    {"URL": "https://creativecommons.org/licenses/by/4.0/"}],
        "update-to": [{"type": "retraction"}, "junk"],
    }
    parsed = rl._crossref_item(item)
    assert parsed["title"] == "A clean title"
    assert parsed["doi"] == "10.1000/abc"
    assert parsed["year"] == 2021
    assert parsed["citations"] == 17
    assert parsed["peerReviewed"] is True
    assert parsed["articleType"] == "research"
    assert parsed["venue"] == "Nature"
    assert parsed["abstract"] == "We prove it."
    assert parsed["license"].startswith("https://creativecommons.org/")
    assert parsed["retractionStatus"] == "retracted"
    assert parsed["issn"].split(",") == ["0028-0836", "1476-4687", "9999-0000"]
    assert parsed["fields"] == []


def test_crossref_item_rejects_components_and_maps_corrections():
    assert rl._crossref_item({"type": "dataset", "title": ["X"]}) is None
    assert rl._crossref_item({"type": "component", "title": ["X"]}) is None
    assert rl._crossref_item({"type": "journal-article", "title": []}) is None

    corrected = rl._crossref_item({
        "type": "proceedings-article",
        "title": ["Proc paper"],
        "update-to": [{"type": "correction"}],
    })
    assert corrected["articleType"] == "conference"
    assert corrected["retractionStatus"] == "corrected"
    assert corrected["year"] == 0
    assert corrected["peerReviewed"] is True

    plain = rl._crossref_item({"type": "", "title": ["Bare"]})
    assert plain["articleType"] == "research"
    assert plain["retractionStatus"] == "none"
    assert plain["license"] == ""


_ARXIV_FEED = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom" xmlns:arxiv="http://arxiv.org/schemas/atom">
  <entry>
    <id>http://arxiv.org/abs/2401.12345v1</id>
    <title>Quantum  walks on
      graphs</title>
    <summary>We   study walks.</summary>
    <published>2024-01-23T00:00:00Z</published>
    <author><name>Ada</name></author>
    <author><name>Bo</name></author>
    <link rel="alternate" href="http://arxiv.org/abs/2401.12345v1"/>
    <arxiv:doi>10.1000/AX</arxiv:doi>
    <category term="math.CO"/>
    <category term="q-bio.NC"/>
    <category term="cond-mat.stat-mech"/>
    <category term="cs.LG"/>
  </entry>
  <entry>
    <id>http://example.test/abs/2</id>
    <published>2025-02-02T00:00:00Z</published>
  </entry>
  <entry>
    <title>Entry without alternate link</title>
    <id>http://arxiv.org/abs/2501.00002</id>
    <published>not-a-date</published>
    <link rel="related" href="http://example.test/related"/>
  </entry>
</feed>
"""

_EPMC_PAYLOAD = {"resultList": {"result": [
    {
        "title": "<b>CRISPR</b> screens",
        "doi": "10.1000/EPMC",
        "source": "MED",
        "id": "12345",
        "pubYear": "2020",
        "authorString": "Ada A, Bo B",
        "journalInfo": {"journal": {
            "title": "Cell", "issn": "0092-8674",
            "essn": "1097-4172", "publisher": "Elsevier"}},
        "pubTypeList": {"pubType": [
            {"pubType": "Retracted Publication"}, {"pubType": "Review"}]},
        "fullTextUrlList": {"fullTextUrl": [
            {"documentStyle": "pdf", "url": "https://www.ebi.ac.uk/x.pdf"},
            {"availability": "Open access", "documentStyle": "html",
             "url": "https://europepmc.org/y"},
        ]},
        "abstractText": "Text.",
        "citedByCount": 9,
        "license": "cc-by",
    },
    {
        "title": "Preprint on mice",
        "source": "PPR",
        "id": "PPR1",
        "pubYear": "2021",
        "fullTextUrlList": {"fullTextUrl": [
            {"availability": "Open access", "url": "https://europepmc.org/z"},
            "junk",
        ]},
    },
    {
        "title": "Paper without links",
        "source": "MED",
        "id": "99999",
        "pubYear": "2019",
    },
    {"title": ""},
]}}

_PUBMED_XML = """<PubmedArticleSet>
  <PubmedArticle>
    <MedlineCitation>
      <PMID>12345678</PMID>
      <Article>
        <ArticleTitle>Graph <i>spectra</i> of networks</ArticleTitle>
        <AuthorList>
          <Author><LastName>Zhang</LastName><ForeName>Wei</ForeName></Author>
        </AuthorList>
        <Journal>
          <Title>Journal of Tests</Title>
          <ISSN>1234-5678</ISSN>
          <JournalIssue><PubDate><Year>2021</Year></PubDate></JournalIssue>
        </Journal>
        <Abstract><AbstractText>We study spectra.</AbstractText></Abstract>
        <PublicationTypeList>
          <PublicationType>Retracted Publication</PublicationType>
          <PublicationType>Review</PublicationType>
        </PublicationTypeList>
      </Article>
    </MedlineCitation>
    <PubmedData>
      <ArticleIdList>
        <ArticleId IdType="doi">10.1000/ABC</ArticleId>
        <ArticleId IdType="pmc">PMC7654321</ArticleId>
      </ArticleIdList>
    </PubmedData>
  </PubmedArticle>
  <PubmedArticle>
    <MedlineCitation>
      <PMID>22222222</PMID>
      <Article>
        <ArticleTitle>Second paper</ArticleTitle>
        <Journal>
          <Title>Other</Title>
          <JournalIssue><PubDate>
            <MedlineDate>2019 Mar-Apr</MedlineDate>
          </PubDate></JournalIssue>
        </Journal>
      </Article>
    </MedlineCitation>
  </PubmedArticle>
  <PubmedArticle>
    <MedlineCitation>
      <PMID>33333333</PMID>
      <Article><Journal><Title>No title</Title></Journal></Article>
    </MedlineCitation>
  </PubmedArticle>
  <PubmedArticle>
    <MedlineCitation><PMID>44444444</PMID></MedlineCitation>
  </PubmedArticle>
  <PubmedArticle/>
</PubmedArticleSet>
"""


def test_crossref_builds_query_filters_and_retries_on_429(monkeypatch):
    monkeypatch.setenv("MG_LITERATURE_MAILTO", "lab@example.test")
    client = _Client([("api.crossref.org/works", [
        _Resp(status_code=429),
        _Resp(json_data={"message": {"items": [
            {"type": "journal-article", "title": ["Hit"], "DOI": "10.1000/hit"},
            {"type": "dataset", "title": ["Skipped"]},
        ]}}),
    ])])
    items = asyncio.run(rl._crossref(client, "spectral gap", 5,
                                    {"author": "Zhang", "yearFrom": 2019, "yearTo": 2023}))
    assert [i["title"] for i in items] == ["Hit"]
    assert len(client.calls) == 2                     # 429 后重试一次
    params = client.calls[0]["params"]
    assert params["query.author"] == "Zhang"
    assert params["mailto"] == "lab@example.test"
    assert "from-pub-date:2019-01-01" in params["filter"]
    assert "until-pub-date:2023-12-31" in params["filter"]
    assert params["rows"] == 5


def test_crossref_raises_on_500_and_doi_404_is_empty():
    with pytest.raises(httpx.HTTPStatusError):
        asyncio.run(rl._crossref(
            _Client([("api.crossref.org", [_Resp(status_code=500)])]), "q", 3))

    missing = _Client([("api.crossref.org", [_Resp(status_code=404)])])
    assert asyncio.run(rl._crossref_doi(missing, "10.1000/none")) == []

    found = _Client([("api.crossref.org", [_Resp(json_data={"message": {
        "type": "journal-article", "title": ["Exact"], "DOI": "10.1000/exact"}})])])
    assert [i["doi"] for i in asyncio.run(
        rl._crossref_doi(found, "10.1000/exact"))] == ["10.1000/exact"]

    empty = _Client([("api.crossref.org", [_Resp(json_data={"message": {
        "type": "dataset", "title": ["Skipped"]}})])])
    assert asyncio.run(rl._crossref_doi(empty, "10.1000/skip")) == []


def test_arxiv_parses_feed_and_builds_query():
    client = _Client([("export.arxiv.org", [_Resp(text=_ARXIV_FEED)])])
    items = asyncio.run(rl._arxiv(client, "quantum walks", 5,
                                  {"author": "Zhang", "yearFrom": 2020, "yearTo": 2024}))
    assert [i["title"] for i in items] == [
        "Quantum walks on graphs", "Entry without alternate link"]
    first = items[0]
    assert first["fields"] == ["math", "biology", "physics"]
    assert first["oaStatus"] == "green"
    assert first["pdfUrl"] == "https://arxiv.org/pdf/2401.12345v1.pdf"
    assert first["abstract"] == "We study walks."
    assert first["year"] == 2024
    assert first["authors"] == "Ada, Bo"
    assert first["doi"] == "10.1000/ax"
    second = items[1]
    assert second["year"] == 0
    assert second["pdfUrl"] == "https://arxiv.org/pdf/2501.00002.pdf"
    query = client.calls[0]["params"]["search_query"]
    assert 'au:"Zhang"' in query
    assert "submittedDate:[202001010000 TO 202412312359]" in query


def test_arxiv_by_id_uses_id_list():
    client = _Client([("export.arxiv.org", [_Resp(text=_ARXIV_FEED)])])
    items = asyncio.run(rl._arxiv_by_id(client, "2401.12345"))
    assert len(items) == 2
    assert client.calls[0]["params"] == {"id_list": "2401.12345", "max_results": 3}


def test_europe_pmc_maps_oa_license_and_retraction():
    client = _Client([("europepmc", [_Resp(json_data=_EPMC_PAYLOAD)])])
    items = asyncio.run(rl._europe_pmc(client, "crispr", 5))
    assert len(items) == 3
    first = items[0]
    assert first["title"] == "CRISPR screens"
    assert first["retractionStatus"] == "retracted"
    assert first["articleType"] == "review"
    assert first["oaUrl"] == "https://www.ebi.ac.uk/x.pdf"
    assert first["oaStatus"] == "green"
    assert first["issn"] == "0092-8674,1097-4172"
    assert first["license"] == "cc-by"
    assert first["citations"] == 9
    assert first["fields"] == ["biology"]
    second = items[1]
    assert second["articleType"] == "preprint"
    assert second["peerReviewed"] is False
    assert second["oaStatus"] == "green"
    assert second["oaUrl"] == "https://europepmc.org/z"
    third = items[2]
    assert third["url"] == "https://europepmc.org/article/MED/99999"
    assert third["oaUrl"] == ""
    assert third["oaStatus"] == "unknown"
    assert third["year"] == 2019


def test_europe_pmc_title_only_and_year_window():
    client = _Client([("europepmc", [_Resp(json_data={"resultList": {"result": []}})])])
    assert asyncio.run(rl._europe_pmc(client, "x" * 400, 3, {"yearFrom": 2018},
                                      title_only=True)) == []
    search = client.calls[0]["params"]["query"]
    assert search.startswith('TITLE:"') and len(search) <= 160

    client2 = _Client([("europepmc", [_Resp(json_data={"resultList": {}})])])
    asyncio.run(rl._europe_pmc(client2, "crispr", 3, {"author": "Li", "yearTo": 2022}))
    query = client2.calls[0]["params"]["query"]
    assert 'AUTH:"Li"' in query and "PUB_YEAR:[1900 TO 2022]" in query


def test_pubmed_esearch_efetch_and_retraction():
    client = _Client([
        ("esearch.fcgi", [_Resp(json_data={"esearchresult": {
            "idlist": ["12345678", "22222222", "33333333", "44444444"]}})]),
        ("efetch.fcgi", [_Resp(text=_PUBMED_XML)]),
    ])
    items = asyncio.run(rl._pubmed(client, "spectra", 5, {"yearFrom": 2015}))
    assert [i["title"] for i in items] == ["Graph spectra of networks", "Second paper"]
    first = items[0]
    assert first["doi"] == "10.1000/abc"
    assert first["oaUrl"] == "https://www.ncbi.nlm.nih.gov/pmc/articles/PMC7654321/"
    assert first["oaStatus"] == "green"
    assert first["retractionStatus"] == "retracted"
    assert first["articleType"] == "review"
    assert first["url"] == "https://pubmed.ncbi.nlm.nih.gov/12345678/"
    assert first["authors"] == "Zhang Wei"
    assert first["venue"] == "Journal of Tests"
    assert first["abstract"] == "We study spectra."
    assert items[1]["year"] == 2019
    assert client.calls[0]["params"]["mindate"] == "2015"
    assert client.calls[1]["params"]["id"] == "12345678,22222222,33333333,44444444"


def test_pubmed_author_query_and_empty_id_list(monkeypatch):
    monkeypatch.setenv("MG_NCBI_API_KEY", "ncbi-key")
    client = _Client([("esearch.fcgi", [_Resp(json_data={"esearchresult": {}})])])
    assert asyncio.run(rl._pubmed(client, "crispr", 2,
                                  {"author": "Li", "yearTo": 2021})) == []
    params = client.calls[0]["params"]
    assert params["term"] == 'crispr AND "Li"[Author]'
    assert params["maxdate"] == "2021"
    assert params["api_key"] == "ncbi-key"
    assert len(client.calls) == 1        # 没有 ID 就不再 efetch


def test_inspire_maps_publication_info_and_preprints():
    client = _Client([("inspirehep.net", [_Resp(json_data=_INSPIRE_PAYLOAD)])])
    items = asyncio.run(rl._inspire(client, "muon", 5))
    assert len(items) == 2
    first = items[0]
    assert first["doi"] == "10.1103/prl"
    assert first["articleType"] == "review"
    assert first["peerReviewed"] is True
    assert first["venue"] == "Phys. Rev. Lett."
    assert first["citations"] == 12
    assert first["sourceTier"] == "authority"
    second = items[1]
    assert second["articleType"] == "preprint"
    assert second["venue"] == "arXiv"
    assert second["url"] == "https://arxiv.org/abs/2401.12345"
    assert second["pdfUrl"] == "https://arxiv.org/pdf/2401.12345.pdf"
    assert second["year"] == 2024
    assert second["abstract"] == "We model."
    assert client.calls[0]["params"]["size"] == 5


def test_inspire_type_and_passes_filters_matrix():
    assert rl._inspire_type("Thesis") == ("thesis", False)
    assert rl._inspire_type("Preprint") == ("preprint", False)
    assert rl._inspire_type("Review article") == ("review", True)
    assert rl._inspire_type("Article") == ("research", True)
    item = {"authors": "Ada Lovelace", "year": 2019}
    assert rl._passes_filters(item, {"author": "lovelace"}) is True
    assert rl._passes_filters(item, {"author": "turing"}) is False
    assert rl._passes_filters(item, {"yearFrom": 2020}) is False
    assert rl._passes_filters(item, {"yearTo": 2018}) is False
    assert rl._passes_filters({"authors": "", "year": 0}, {"yearFrom": 2020}) is True
    assert rl._passes_filters(item, None) is True


_INSPIRE_PAYLOAD = {"hits": {"hits": [
    {"id": "1", "metadata": {
        "titles": [{"title": "Muon anomaly review"}],
        "authors": [{"full_name": "A Author"}, "junk"],
        "publication_info": [{"journal_title": "Phys. Rev. Lett.", "year": 2021}],
        "dois": [{"value": "10.1103/PRL"}],
        "citation_count": 12,
        "document_type": ["review"],
        "control_number": 4321,
    }},
    {"id": "2", "metadata": {
        "titles": [{"title": "Dark matter preprint"}],
        "publication_info": {"journal_title": "", "year": 0},
        "arxiv_eprints": [{"value": "2401.12345"}],
        "preprint_date": "2024-01-23",
        "document_type": "preprint",
        "abstracts": [{"value": "We model."}],
    }},
    {"id": "3", "metadata": {"titles": []}},
]}}

_ADS_PAYLOAD = {"response": {"docs": [
    {"title": ["Cosmic rays"], "doi": ["10.1000/ADS"], "bibcode": "2020ApJ...1..1A",
     "property": ["REFEREED", "OPENACCESS"], "pub": "ApJ", "doctype": "article",
     "year": "2020", "citation_count": 5, "author": ["A Author"],
     "issn": ["0004-637X", "1538-4357"], "publisher": "IOP",
     "esources": ["PUB_PDF", "EPRINT_PDF"], "abstract": "Text"},
    {"title": ["Retracted preprint"], "property": ["RETRACTED", "REVIEW"],
     "pub": "arXiv", "doctype": "eprint", "year": 2021,
     "bibcode": "2021arXiv1"},
    {"title": [], "property": []},
    "junk",
]}}

_ZBMATH_PAYLOAD = {"result": [
    {"title": {"title": "Algebraic <b>geometry</b>"},
     "contributors": {"authors": [{"name": "Ada"}, {"name": ""}, "junk"]},
     "source": {"source": "zbMATH Open Web Interface contents unavailable",
                "series": [{"title": "Invent. Math.",
                            "issn": [{"number": "0070-0000"}]}]},
     "links": [{"url": "https://doi.org/10.1000/x"},
               {"url": "https://example.test/a.PDF"}],
     "document_type": {"description": "Review"},
     "year": "2019"},
    {"title": "Plain title", "links": [{"url": "http://ignored.test"}],
     "source": "not-a-dict", "document_type": "not-a-dict", "year": 2018,
     "zbmath_url": "https://zbmath.org/?q=1"},
    {"title": {"title": "zbMATH Open Web Interface contents unavailable"}},
]}

_DOAJ_PAYLOAD = {"results": [
    {"bibjson": {
        "title": "Open math",
        "author": [{"name": "A"}, "x"],
        "identifier": [{"type": "doi", "id": "10.1000/DOAJ"}],
        "link": [{"type": "fulltext", "url": "https://doaj.test/a"}],
        "journal": {"title": "J. Open", "issns": ["1111-2222"], "publisher": "Pub"},
        "year": "2021",
    }},
    {"bibjson": {"title": ""}},
    {"bibjson": {"title": "No links", "year": "notyear",
                 "link": [{"type": "fulltext", "url": "http://insecure.test/a"}]}},
]}


def test_ads_requires_key_and_maps_oa_gateway(monkeypatch):
    monkeypatch.delenv("MG_ADS_API_KEY", raising=False)
    assert asyncio.run(rl._ads(_Client([]), "cosmic rays", 5)) == []

    monkeypatch.setenv("MG_ADS_API_KEY", "ads-key")
    client = _Client([("adsabs.harvard.edu", [_Resp(json_data=_ADS_PAYLOAD)])])
    items = asyncio.run(rl._ads(client, 'cosmic "rays\\x"', 5,
                                {"author": "Li", "yearFrom": 2019}))
    assert len(items) == 2
    first = items[0]
    assert first["doi"] == "10.1000/ads"
    assert first["oaUrl"] == ("https://ui.adsabs.harvard.edu/link_gateway/"
                             "2020ApJ...1..1A/EPRINT_PDF")
    assert first["oaStatus"] == "green"
    assert first["peerReviewed"] is True
    assert first["issn"] == "0004-637X,1538-4357"
    assert first["abstract"] == "Text"
    second = items[1]
    assert second["retractionStatus"] == "retracted"
    assert second["articleType"] == "preprint"
    assert second["peerReviewed"] is False
    assert second["oaUrl"] == ""
    assert client.calls[0]["headers"]["Authorization"] == "Bearer ads-key"
    query = client.calls[0]["params"]["q"]
    assert 'author:"Li"' in query and "year:[2019 TO " in query


def test_zbmath_maps_dict_title_links_and_series():
    client = _Client([("api.zbmath.org", [_Resp(json_data=_ZBMATH_PAYLOAD)])])
    items = asyncio.run(rl._zbmath(client, "algebraic geometry", 5))
    assert len(items) == 2
    first = items[0]
    assert first["title"] == "Algebraic geometry"
    assert first["venue"] == "Invent. Math."
    assert first["url"] == "https://doi.org/10.1000/x"
    assert first["pdfUrl"] == "https://example.test/a.PDF"
    assert first["articleType"] == "review"
    assert first["issn"] == "0070-0000"
    assert first["year"] == 2019
    second = items[1]
    assert second["title"] == "Plain title"
    assert second["url"] == "https://zbmath.org/?q=1"
    assert second["year"] == 2018
    assert second["pdfUrl"] == ""
    assert client.calls[0]["params"]["results_per_page"] == 5


def test_doaj_maps_bibjson_and_skips_unusable_items():
    client = _Client([("doaj.org", [_Resp(json_data=_DOAJ_PAYLOAD)])])
    items = asyncio.run(rl._doaj(client, "open math", 5))
    assert len(items) == 2
    first = items[0]
    assert first["title"] == "Open math"
    assert first["doi"] == "10.1000/doaj"
    assert first["url"] == "https://doaj.test/a"
    assert first["issn"] == "1111-2222"
    assert first["publisher"] == "Pub"
    assert first["year"] == 2021
    assert first["license"] == ""
    assert first["peerReviewed"] is True
    second = items[1]
    assert second["year"] == 0
    assert second["url"] == ""


_OPENALEX_PAYLOAD = {"results": [
    {"title": "Spectral gaps", "doi": "https://doi.org/10.1000/OA",
     "publication_year": 2020,
     "authorships": [{"author": {"display_name": "Ada"}},
                     {"author": None}],
     "primary_location": {"source": {
         "display_name": "Nature", "issn_l": "0028-0836",
         "host_organization_name": "Springer Nature"}},
     "primary_topic": {"field": {"display_name": "Mathematics"}},
     "abstract_inverted_index": {"We": [0], "prove": [1]},
     "cited_by_count": 7, "type": "article",
     "open_access": {"oa_status": "gold"},
     "best_oa_location": {"pdf_url": "https://example.test/x.pdf",
                          "license": "cc-by"},
     "is_retracted": True},
    {"title": None},
    {"title": "Medicine preprint", "type": "preprint",
     "primary_topic": {"field": {"display_name": "Medicine"}},
     "abstract_inverted_index": "not-a-dict",
     "open_access": {}, "best_oa_location": {}},
]}

_S2_PAYLOAD = {"data": [
    {"title": "Deep learning", "year": 2019,
     "authors": [{"name": "Ada"}, {"name": None}],
     "venue": "NeurIPS", "externalIds": {"DOI": "10.1000/S2", "ArXiv": "2401.12345"},
     "url": "https://s2.test/1", "citationCount": 4,
     "openAccessPdf": {"url": "https://example.test/oa.pdf"},
     "publicationTypes": ["JournalArticle"]},
    {"title": "", "externalIds": {}},
    {"title": "Preprint thing", "externalIds": {"ArXiv": "not-an-id"},
     "openAccessPdf": "not-a-dict", "publicationTypes": ["Review", "Preprint"],
     "citationCount": None},
]}


def test_openalex_maps_topics_oa_and_retraction(monkeypatch):
    monkeypatch.setenv("MG_OPENALEX_API_KEY", "oa-key")
    client = _Client([("api.openalex.org/works", [_Resp(json_data=_OPENALEX_PAYLOAD)])])
    items = asyncio.run(rl._openalex(client, "spectral gap", 5,
                                    {"author": "Li", "yearFrom": 2018, "yearTo": 2022}))
    assert len(items) == 2
    first = items[0]
    assert first["title"] == "Spectral gaps"
    assert first["doi"] == "10.1000/oa"
    assert first["venue"] == "Nature"
    assert first["issn"] == "0028-0836"
    assert first["fields"] == ["math"]
    assert first["oaStatus"] == "gold"
    assert first["oaUrl"] == "https://example.test/x.pdf"
    assert first["license"] == "cc-by"
    assert first["retractionStatus"] == "retracted"
    assert first["articleType"] == "research"
    assert first["peerReviewed"] is True
    assert first["abstract"] == "We prove"
    second = items[1]
    assert second["fields"] == ["biology"]
    assert second["articleType"] == "preprint"
    assert second["oaStatus"] == "unknown"
    assert second["abstract"] == ""
    params = client.calls[0]["params"]
    assert params["api_key"] == "oa-key"
    assert "raw_author_name.search:Li" in params["filter"]
    assert "from_publication_date:2018-01-01" in params["filter"]
    assert "to_publication_date:2022-12-31" in params["filter"]


def test_openalex_abstract_ignores_malformed_index():
    assert rl._openalex_abstract({"abstract_inverted_index": "not-a-dict"}) == ""
    assert rl._openalex_abstract({"abstract_inverted_index": {
        "keep": [0], "drop": "not-a-list"}}) == "keep"
    assert rl._openalex_abstract({"abstract_inverted_index": {
        "b word": [1], "a word": [0]}}) == "a word b word"
    assert rl._openalex_abstract({"abstract_inverted_index": {
        "only": [0, "not-an-index"]}}) == "only"
    assert rl._openalex_abstract({}) == ""


def test_merge_fills_pdf_and_oa_url_from_later_source():
    first = rl._result(title="Pdf fill", doi="10.1000/pf", sources=["crossref"])
    second = rl._result(title="Pdf fill", doi="10.1000/pf", sources=["arxiv"],
                        pdfUrl="https://arxiv.org/pdf/1.pdf",
                        oaUrl="https://arxiv.org/pdf/1.pdf")
    merged = rl._merge([first, second])
    assert merged[0]["pdfUrl"] == "https://arxiv.org/pdf/1.pdf"
    assert merged[0]["oaUrl"] == "https://arxiv.org/pdf/1.pdf"


def test_search_identifier_dispatches_arxiv_pmcid_and_pmid(monkeypatch):
    from starlette.testclient import TestClient

    seen = {"epmc": []}

    async def fake_arxiv(client, arxiv_id):
        seen["arxiv"] = arxiv_id
        return [rl._result(title="arXiv exact", doi="10.48550/arxiv.2401.12345")]

    async def fake_epmc(client, query, limit, filters=None):
        seen["epmc"].append(query)
        return [rl._result(title=f"EPMC hit {query}")]

    monkeypatch.setattr(rl, "require_auth", lambda request: {"uid": "u-lit-id-kinds"})
    monkeypatch.setattr(rl, "_arxiv_by_id", fake_arxiv)
    monkeypatch.setattr(rl, "_europe_pmc", fake_epmc)
    client = TestClient(_lit_app())

    body = client.get("/api/research/literature?q=arXiv:2401.12345").json()
    assert body["identifier"] == {"type": "arxiv", "value": "2401.12345"}
    assert body["results"][0]["title"] == "arXiv exact"
    assert seen["arxiv"] == "2401.12345"
    assert body["results"][0]["pdfUrl"] == "https://arxiv.org/pdf/2401.12345.pdf"

    pmc = client.get("/api/research/literature?q=PMC7654321").json()
    assert pmc["identifier"] == {"type": "pmcid", "value": "PMC7654321"}
    pmid = client.get("/api/research/literature?q=PMID:%2012345678").json()
    assert pmid["identifier"] == {"type": "pmid", "value": "12345678"}
    assert seen["epmc"] == ["PMCID:PMC7654321", "EXT_ID:12345678 AND SRC:MED"]


def test_search_excludes_preprints_when_disabled(monkeypatch):
    from starlette.testclient import TestClient

    async def one(client, query, limit, filters=None):
        return [rl._result(title="Journal only", doi="10.1000/jj", year=2020,
                           sources=["crossref"], peerReviewed=True),
                rl._result(title="Preprint only", doi="10.1000/pp", year=2021,
                           sources=["arxiv"], articleType="preprint",
                           sourceTier="preprint")]

    async def empty(client, query, limit, filters=None):
        return []

    monkeypatch.setattr(rl, "require_auth", lambda request: {"uid": "u-lit-nopre"})
    monkeypatch.setattr(rl, "_SEARCH_CACHE", {})
    monkeypatch.setattr(rl, "_crossref", one)
    for name in ("_arxiv", "_europe_pmc", "_openalex", "_semantic_scholar", "_doaj"):
        monkeypatch.setattr(rl, name, empty)
    client = TestClient(_lit_app())
    body = client.get("/api/research/literature?q=nopreprint&includePreprints=false").json()
    assert [i["title"] for i in body["results"]] == ["Journal only"]


def test_semantic_scholar_key_year_and_pdf_mapping(monkeypatch):
    monkeypatch.delenv("MG_S2_API_KEY", raising=False)
    client = _Client([("api.semanticscholar.org", [_Resp(json_data=_S2_PAYLOAD)])])
    items = asyncio.run(rl._semantic_scholar(client, "deep learning", 5,
                                             {"yearFrom": 2015}))
    assert client.calls[0]["headers"] is None
    assert client.calls[0]["params"]["year"].startswith("2015-")
    assert len(items) == 2
    first = items[0]
    assert first["doi"] == "10.1000/s2"
    assert first["pdfUrl"] == "https://arxiv.org/pdf/2401.12345.pdf"
    assert first["peerReviewed"] is True
    assert first["articleType"] == "research"
    assert first["oaUrl"] == "https://example.test/oa.pdf"
    assert first["venue"] == "NeurIPS"
    second = items[1]
    assert second["pdfUrl"] == ""
    assert second["articleType"] == "preprint"
    assert second["peerReviewed"] is False
    assert second["citations"] == 0
    assert second["oaUrl"] == ""

    monkeypatch.setenv("MG_S2_API_KEY", "s2-key")
    keyed = _Client([("api.semanticscholar.org", [_Resp(json_data={"data": []})])])
    asyncio.run(rl._semantic_scholar(keyed, "q", 3))
    assert keyed.calls[0]["headers"] == {"x-api-key": "s2-key"}


def test_biorxiv_detail_only_for_biorxiv_dois_and_skips_bad_json():
    assert asyncio.run(rl._biorxiv_detail(_Client([]), "10.1000/x")) == []

    client = _Client([
        ("api.biorxiv.org/details/biorxiv", [_Resp(json_data={"collection": [
            {"title": "Mice <b>study</b>", "date": "2021-05-04", "version": "2",
             "authors": "Ada; Bo", "abstract": "Text", "license": "cc-by"},
            {"title": ""},
            "junk",
        ]})]),
        ("api.biorxiv.org/details/medrxiv", [_Resp(status_code=500)]),
    ])
    items = asyncio.run(rl._biorxiv_detail(client, "10.1101/2021.05.04.123456"))
    assert len(items) == 1
    first = items[0]
    assert first["title"] == "Mice study"
    assert first["year"] == 2021
    assert first["oaUrl"] == ("https://www.biorxiv.org/content/"
                             "10.1101/2021.05.04.123456v2.full.pdf")
    assert first["oaStatus"] == "green"
    assert first["articleType"] == "preprint"
    assert first["license"] == "cc-by"

    bad = _Client([("api.biorxiv.org/details", [_Resp(json_data=ValueError("bad json"))])])
    assert asyncio.run(rl._biorxiv_detail(bad, "10.1101/x")) == []


def test_dblp_skips_non_dict_hits_and_bad_year():
    class Response:
        status_code = 200
        headers = {"content-type": "application/json"}

        @staticmethod
        def json():
            return {"result": {"hits": {"hit": [
                {"info": {"title": "Solo <i>hit</i>", "year": "notayear",
                          "authors": {"author": {"text": "Ada"}},
                          "ee": "https://dblp.org/rec/1"}},
                {"info": {"title": ""}},
                {"noinfo": True},
                "junk",
            ]}}}

    class Client:
        async def get(self, url, params=None, timeout=None):
            return Response()

    items = asyncio.run(rl._dblp(Client(), "graph", 5, None))
    assert len(items) == 1
    assert items[0]["title"] == "Solo hit"
    assert items[0]["year"] == 0
    assert items[0]["authors"] == "Ada"

    class Single(Client):
        async def get(self, url, params=None, timeout=None):
            class R:
                status_code = 200
                headers = {}

                @staticmethod
                def json():
                    return {"result": {"hits": {"hit": {"info": {
                        "title": "Single dict hit", "year": "2020"}}}}}
            return R()

    assert [i["title"] for i in asyncio.run(
        rl._dblp(Single(), "graph", 5, None))] == ["Single dict hit"]

    class NoJson(Client):
        async def get(self, url, params=None, timeout=None):
            class R:
                status_code = 200
                headers = {}
            return R()

    assert asyncio.run(rl._dblp(NoJson(), "graph", 5, None)) == []


def test_mark_local_flags_imported_and_temp_docs(monkeypatch):
    monkeypatch.setattr(rl.rc, "_docs_by_doi", lambda uid, dois: {
        "10.1000/a": {"id": "doc-a", "status": "ready"},
        "10.1000/b": {"id": "doc-b", "status": "temp"},
    })
    results = [
        rl._result(title="A", doi="10.1000/A"),
        rl._result(title="B", doi="10.1000/b"),
        rl._result(title="C"),
    ]
    out = rl._mark_local("u-1", results)
    assert out[0]["docId"] == "doc-a" and out[0]["imported"] is True
    assert out[1]["tempDocId"] == "doc-b" and out[1]["imported"] is False
    assert out[2]["docId"] == "" and out[2]["tempDocId"] == ""


def test_merge_dedupes_title_case_and_prefers_stronger_metadata():
    preprint = rl._result(
        title="Deep  Learning", doi="", abstract="short", citations=1,
        sources=["arxiv"], year=2019, venue="",
        pdfUrl="https://arxiv.org/pdf/2401.12345.pdf",
        articleType="preprint", sourceTier="preprint", oaStatus="green")
    journal = rl._result(
        title="deep learning", doi="", abstract="a much longer abstract",
        citations=4, sources=["crossref"], year=2020, venue="Nature",
        venueTier="T0", sourceTier="authority", articleType="research",
        oaStatus="gold", retractionStatus="retracted", license="cc-by",
        peerReviewed=True, fields=["math"])
    merged = rl._merge([preprint, journal])
    assert len(merged) == 1                    # 标题仅大小写/空白差异 → 同一条
    item = merged[0]
    assert item["citations"] == 4
    assert item["articleType"] == "research"   # preprint 被正式发表版本覆盖
    assert item["sourceTier"] == "authority"
    assert item["venueTier"] == "T0"
    assert item["oaStatus"] == "gold"
    assert item["retractionStatus"] == "retracted"
    assert item["license"] == "cc-by"
    assert item["fields"] == ["math"]
    assert item["pdfUrl"] == "https://arxiv.org/pdf/2401.12345.pdf"
    assert sorted(item["sources"]) == ["arxiv", "crossref"]


def test_merge_fills_article_type_and_orders_by_citations():
    blank = rl._result(title="Same title", doi="10.1000/dup", articleType="",
                       citations=0, year=0, sources=["doaj"])
    typed = rl._result(title="Same title", doi="10.1000/dup", articleType="review",
                       citations=3, year=2022, sources=["doaj"])
    older = rl._result(title="Older", doi="10.1000/old", citations=1, year=1999)
    newer = rl._result(title="Newer", doi="10.1000/new", citations=1, year=2020)
    merged = rl._merge([blank, typed, older, newer])
    assert [i["doi"] for i in merged] == ["10.1000/dup", "10.1000/new",
                                         "10.1000/old"]
    assert merged[0]["articleType"] == "review"


def test_enrich_uses_venue_registry_and_tier_fallbacks():
    nature = rl._result(title="Nature paper", issn="0028-0836", venue="Nature",
                        sourceTier="authority", year=2020)
    preprint = rl._result(title="Preprint", articleType="preprint",
                          sourceTier="preprint", year=2021)
    reviewed = rl._result(title="Reviewed", peerReviewed=True,
                          sourceTier="authority", year=2022)
    bare = rl._result(title="Bare", year=2023)
    arxiv_doi = rl._result(title="arXiv DOI", doi="10.48550/arxiv.2401.12345")
    out = rl._enrich([nature, preprint, reviewed, bare, arxiv_doi], "math")
    assert out[0]["venueTier"] == "T0"
    assert out[0]["peerReviewed"] is True
    assert out[0]["venueLabel"].startswith("Nature")
    assert "math" in out[0]["fields"]
    assert out[1]["venueTier"] == "P"
    assert out[2]["venueTier"] == "T3"
    assert out[3]["venueTier"] == "U"
    assert out[3]["landingUrl"] == ""
    assert out[4]["pdfUrl"] == "https://arxiv.org/pdf/2401.12345.pdf"


def test_sort_results_prefers_venue_tier_for_subject_fields():
    strong = rl._result(title="strong", citations=1, year=2020, venueTier="T0",
                        sources=["zbmath"])
    weak = rl._result(title="weak", citations=99, year=2024, venueTier="U",
                      sources=["openalex"])
    assert [i["title"] for i in rl._sort_results([weak, strong], "math")] == [
        "strong", "weak"]
    assert [i["title"] for i in rl._sort_results([weak, strong], "general")] == [
        "weak", "strong"]


def test_noise_and_filter_matrix():
    assert rl._is_noise({"title": "Front  Matter"}) is True
    assert rl._is_noise({"title": "Front matter: special issue"}) is True
    assert rl._is_noise({"title": "Back matter"}) is True
    assert rl._is_noise({"title": "A real paper"}) is False
    assert rl._is_noise({}) is False

    strong = rl._result(title="A", peerReviewed=True, oaStatus="gold",
                        sourceTier="authority", articleType="research")
    preprint = rl._result(title="B", sourceTier="preprint",
                          articleType="preprint", oaStatus="unknown")
    noise = rl._result(title="Index")
    out = rl._filter_results([strong, preprint, noise], peer_reviewed=True,
                             oa_only=True, include_preprints=False)
    assert [i["title"] for i in out] == ["A"]
    out2 = rl._filter_results([strong, preprint], peer_reviewed=False,
                              oa_only=False, include_preprints=True)
    assert [i["title"] for i in out2] == ["A", "B"]


def test_provider_warning_maps_error_kinds():
    def status_error(code):
        request = httpx.Request("GET", "https://provider.test/")
        return httpx.HTTPStatusError(
            "x", request=request,
            response=httpx.Response(code, request=request))

    assert "429" in rl._provider_warning("crossref", status_error(429))
    assert rl._provider_warning("doaj", status_error(503)).startswith("doaj: HTTP 503")
    assert rl._provider_warning("arxiv", asyncio.TimeoutError()).endswith("timeout")
    assert rl._provider_warning("arxiv", httpx.ReadTimeout("slow")).endswith("timeout")
    assert "bot challenge" in rl._provider_warning("dblp", RuntimeError("bot challenge"))
    assert rl._provider_warning("zbmath", ValueError("x")) == "zbmath: ValueError"


def test_run_providers_maps_deadline_and_exceptions():
    async def slow(client, query, limit, filters=None):
        await asyncio.sleep(0.3)
        return []

    async def boom(client, query, limit, filters=None):
        raise ValueError("bad payload")

    async def ok(client, query, limit, filters=None):
        return [{"title": "x"}]

    outcomes = asyncio.run(rl._run_providers(
        None, [("slow", slow), ("boom", boom), ("ok", ok)], "q", 3, deadline=0.05))
    by_name = dict(outcomes)
    assert isinstance(by_name["slow"], TimeoutError)   # 超过 deadline 直接取消
    assert isinstance(by_name["boom"], ValueError)     # 异常作为结果回报,不炸整页
    assert by_name["ok"] == [{"title": "x"}]
    assert [name for name, _ in outcomes] == ["boom", "ok", "slow"]


def test_fill_oa_enriches_only_missing_candidates(monkeypatch):
    async def fake_resolve(client, doi):
        if doi == "10.1000/boom":
            raise asyncio.TimeoutError
        return {"isOa": True, "oaUrl": "https://arxiv.org/pdf/x.pdf",
                "oaStatus": "gold", "license": "cc-by"}

    monkeypatch.setattr(rl.oa_resolver, "resolve_doi", fake_resolve)
    results = [
        rl._result(title="A", doi="10.1000/a", oaStatus="unknown"),
        rl._result(title="B", doi="10.1000/boom", oaStatus="closed"),
        rl._result(title="C", doi="", oaStatus="unknown"),
        rl._result(title="D", doi="10.1000/d", oaStatus="gold",
                   oaUrl="https://arxiv.org/pdf/d.pdf"),
    ]
    asyncio.run(rl._fill_oa(None, results))
    assert results[0]["oaStatus"] == "gold"
    assert results[0]["oaUrl"] == "https://arxiv.org/pdf/x.pdf"
    assert results[0]["license"] == "cc-by"
    assert results[1]["oaUrl"] == ""      # 超时 → 保持原样,不抛错
    assert results[3]["oaStatus"] == "gold"

    untouched = [rl._result(title="E", doi="", oaStatus="unknown")]
    asyncio.run(rl._fill_oa(None, untouched))
    assert untouched[0]["oaStatus"] == "unknown"


# ---------- 端点层:错误码映射 / 缓存 / 过滤 ----------


def test_search_validation_and_limiter(monkeypatch):
    from starlette.testclient import TestClient

    monkeypatch.setattr(rl, "require_auth", lambda request: {"uid": "u-lit-val"})
    monkeypatch.setattr(rl, "_SEARCH_CACHE", {})
    client = TestClient(_lit_app())
    assert client.get("/api/research/literature?q=a").status_code == 400
    assert client.get("/api/research/literature?q=" + "x" * 201).status_code == 400
    monkeypatch.setattr(rl, "_limiter", _DeniedLimiter())
    assert client.get("/api/research/literature?q=attention").status_code == 429


def test_search_limit_and_field_fallbacks(monkeypatch):
    from starlette.testclient import TestClient

    calls = {}

    async def empty(client, query, limit, filters=None):
        calls["limit"] = limit
        return []

    monkeypatch.setattr(rl, "require_auth", lambda request: {"uid": "u-lit-limit"})
    monkeypatch.setattr(rl, "_SEARCH_CACHE", {})
    for name in ("_crossref", "_arxiv", "_europe_pmc", "_openalex",
                 "_semantic_scholar", "_doaj", "_pubmed", "_inspire",
                 "_ads", "_zbmath", "_dblp"):
        monkeypatch.setattr(rl, name, empty)
    client = TestClient(_lit_app())
    res = client.get("/api/research/literature?q=spectral&limit=abc&field=bogus"
                     "&yearFrom=1800&includePreprints=0&peerReviewed=yes&oaOnly=0")
    assert res.status_code == 200
    body = res.json()
    assert body["field"] == "general"      # 未知学科回落 general
    assert body["results"] == []
    assert body["warnings"] == []
    assert body.get("cached") is None
    assert calls["limit"] == 10            # limit 非法 → 默认 10


def test_search_second_call_uses_cache(monkeypatch):
    from starlette.testclient import TestClient

    hits = {"n": 0}

    async def one(client, query, limit, filters=None):
        hits["n"] += 1
        return [rl._result(title="Cached paper", doi="10.1000/cache", year=2020,
                           citations=1, sources=["crossref"])]

    monkeypatch.setattr(rl, "require_auth", lambda request: {"uid": "u-lit-cache"})
    monkeypatch.setattr(rl, "_SEARCH_CACHE", {})
    for name in ("_crossref", "_arxiv", "_europe_pmc", "_openalex",
                 "_semantic_scholar", "_doaj", "_pubmed", "_inspire",
                 "_ads", "_zbmath", "_dblp"):
        monkeypatch.setattr(rl, name, one)
    client = TestClient(_lit_app())
    first = client.get("/api/research/literature?q=cache%20me").json()
    second = client.get("/api/research/literature?q=cache%20me").json()
    assert first["results"][0]["title"] == "Cached paper"
    assert first.get("cached") is None
    assert second["cached"] is True
    assert second["results"][0]["title"] == "Cached paper"
    provider_count = len(rl.rs.specs_for("general", True))
    assert hits["n"] == provider_count     # 第二次没有再打外部源


def test_search_reports_provider_failures_as_warnings(monkeypatch):
    from starlette.testclient import TestClient

    async def boom(client, query, limit, filters=None):
        request = httpx.Request("GET", "https://provider.test/")
        raise httpx.HTTPStatusError(
            "429", request=request,
            response=httpx.Response(429, request=request))

    async def empty(client, query, limit, filters=None):
        return []

    monkeypatch.setattr(rl, "require_auth", lambda request: {"uid": "u-lit-warn"})
    monkeypatch.setattr(rl, "_SEARCH_CACHE", {})
    monkeypatch.setattr(rl, "_crossref", boom)
    for name in ("_arxiv", "_europe_pmc", "_openalex", "_semantic_scholar", "_doaj"):
        monkeypatch.setattr(rl, name, empty)
    client = TestClient(_lit_app())
    body = client.get("/api/research/literature?q=warnings").json()
    assert body["results"] == []
    assert len(body["warnings"]) == 1
    assert body["warnings"][0].startswith("crossref")
    assert "429" in body["warnings"][0]


def test_search_cache_keeps_entry_count_bounded(monkeypatch):
    from starlette.testclient import TestClient

    async def empty(client, query, limit, filters=None):
        return []

    monkeypatch.setattr(rl, "require_auth", lambda request: {"uid": "u-lit-evict"})
    monkeypatch.setattr(rl, "_SEARCH_CACHE",
                        {f"k{i}": (0.0, [], []) for i in range(64)})
    monkeypatch.setattr(rl, "_SEARCH_MAX", 64)
    for name in ("_crossref", "_arxiv", "_europe_pmc", "_openalex",
                 "_semantic_scholar", "_doaj", "_pubmed", "_inspire",
                 "_ads", "_zbmath", "_dblp"):
        monkeypatch.setattr(rl, name, empty)
    client = TestClient(_lit_app())
    client.get("/api/research/literature?q=evict%20me")
    assert len(rl._SEARCH_CACHE) == 64
    assert "k0" not in rl._SEARCH_CACHE


def test_search_oa_only_fills_and_filters(monkeypatch):
    from starlette.testclient import TestClient

    async def one(client, query, limit, filters=None):
        return [rl._result(title="Closed paper", doi="10.1000/closed", year=2020,
                           sources=["crossref"], oaStatus="unknown"),
                rl._result(title="Already gold", doi="10.1000/gold", year=2020,
                           sources=["crossref"], oaStatus="gold",
                           oaUrl="https://arxiv.org/pdf/x.pdf")]

    async def empty(client, query, limit, filters=None):
        return []

    async def fake_fill(client, results):
        for item in results:
            if item["doi"] == "10.1000/closed":
                item["oaStatus"] = "green"
                item["oaUrl"] = "https://europepmc.org/pdf/1.pdf"
                item["license"] = "cc-by"

    monkeypatch.setattr(rl, "require_auth", lambda request: {"uid": "u-lit-oa"})
    monkeypatch.setattr(rl, "_SEARCH_CACHE", {})
    monkeypatch.setattr(rl, "_crossref", one)
    for name in ("_arxiv", "_europe_pmc", "_openalex", "_semantic_scholar", "_doaj"):
        monkeypatch.setattr(rl, name, empty)
    monkeypatch.setattr(rl, "_fill_oa", fake_fill)
    client = TestClient(_lit_app())
    body = client.get("/api/research/literature?q=oa%20only&oaOnly=yes").json()
    by_title = {i["title"]: i for i in body["results"]}
    assert sorted(by_title) == ["Already gold", "Closed paper"]
    assert by_title["Closed paper"]["oaStatus"] == "green"
    assert by_title["Closed paper"]["license"] == "cc-by"


def test_search_peer_reviewed_filter_drops_preprints(monkeypatch):
    from starlette.testclient import TestClient

    async def one(client, query, limit, filters=None):
        return [rl._result(title="Journal paper", doi="10.1000/j", year=2020,
                           sources=["crossref"], peerReviewed=True),
                rl._result(title="Preprint paper", doi="10.1000/p", year=2021,
                           sources=["arxiv"], articleType="preprint",
                           sourceTier="preprint")]

    async def empty(client, query, limit, filters=None):
        return []

    monkeypatch.setattr(rl, "require_auth", lambda request: {"uid": "u-lit-peer"})
    monkeypatch.setattr(rl, "_SEARCH_CACHE", {})
    monkeypatch.setattr(rl, "_crossref", one)
    for name in ("_arxiv", "_europe_pmc", "_openalex", "_semantic_scholar", "_doaj"):
        monkeypatch.setattr(rl, name, empty)
    client = TestClient(_lit_app())
    body = client.get("/api/research/literature?q=peer&peerReviewed=1").json()
    assert [i["title"] for i in body["results"]] == ["Journal paper"]


def test_search_identifier_network_error_becomes_502(monkeypatch):
    from starlette.testclient import TestClient

    async def boom(client, doi):
        request = httpx.Request("GET", "https://api.crossref.org/works/x")
        raise httpx.ConnectError("down", request=request)

    monkeypatch.setattr(rl, "require_auth", lambda request: {"uid": "u-lit-id-err"})
    monkeypatch.setattr(rl, "_crossref_doi", boom)
    client = TestClient(_lit_app())
    res = client.get("/api/research/literature?q=10.1234/abcd.5678")
    assert res.status_code == 502


def test_related_merges_references_and_drops_noise(monkeypatch):
    from starlette.testclient import TestClient

    def handler(url, params):
        assert url.startswith("https://api.crossref.org/works/")
        return _Resp(json_data={"message": {"reference": [
            {"DOI": "10.1000/ref", "article-title": "Referenced <i>work</i>",
             "year": "2018", "journal-title": "Nature", "author": "Ada"},
            {"unstructured": "Untitled ref", "year": "n/a"},
            {"year": "2019"},
        ]}})

    async def similar(client, query, limit, filters=None):
        return [rl._result(title="Similar paper", doi="10.1000/sim", year=2021,
                           sources=["crossref"]),
                rl._result(title="Front Matter", sources=["crossref"]),
                rl._result(title="Seed paper", doi="10.1000/seed",
                           sources=["crossref"])]

    async def failing(client, query, limit, filters=None, *a, **k):
        raise RuntimeError("bot challenge")

    async def empty(client, query, limit, filters=None, *a, **k):
        return []

    monkeypatch.setattr(rl, "require_auth", lambda request: {"uid": "u-lit-rel"})
    monkeypatch.setattr(rl.httpx, "AsyncClient", _HttpFactory(handler))
    monkeypatch.setattr(rl, "_crossref", similar)
    monkeypatch.setattr(rl, "_arxiv", empty)
    monkeypatch.setattr(rl, "_europe_pmc", failing)
    monkeypatch.setattr(rl, "_openalex", empty)
    client = TestClient(_lit_app())
    body = client.get(
        "/api/research/literature/related?doi=10.1000/seed&title=Seed%20paper").json()
    titles = sorted(i["title"] for i in body["results"])
    assert titles == ["Referenced work", "Similar paper", "Untitled ref"]
    assert body["query"] == "Seed paper"       # 有标题时用标题做种子查询
    assert any(w.startswith("europepmc") for w in body["warnings"])
    by_title = {i["title"]: i for i in body["results"]}
    assert by_title["Referenced work"]["doi"] == "10.1000/ref"
    assert by_title["Untitled ref"]["year"] == 0


def test_related_tolerates_crossref_failure(monkeypatch):
    from starlette.testclient import TestClient

    def handler(url, params):
        raise httpx.ConnectError("down")

    async def empty(client, query, limit, filters=None, *a, **k):
        return []

    monkeypatch.setattr(rl, "require_auth", lambda request: {"uid": "u-lit-rel-err"})
    monkeypatch.setattr(rl.httpx, "AsyncClient", _HttpFactory(handler))
    for name in ("_crossref", "_arxiv", "_europe_pmc", "_openalex"):
        monkeypatch.setattr(rl, name, empty)
    client = TestClient(_lit_app())
    body = client.get("/api/research/literature/related"
                      "?doi=10.1000/seed&title=Attention%20is%20all").json()
    assert body["results"] == []
    assert any(w.startswith("crossref-reference") for w in body["warnings"])


def test_related_requires_doi_or_title_and_respects_limiter(monkeypatch):
    from starlette.testclient import TestClient

    monkeypatch.setattr(rl, "require_auth", lambda request: {"uid": "u-lit-rel-400"})
    client = TestClient(_lit_app())
    assert client.get("/api/research/literature/related?title=abc").status_code == 400
    monkeypatch.setattr(rl, "_limiter", _DeniedLimiter())
    assert client.get("/api/research/literature/related?doi=10.1000/x").status_code == 429


def test_oa_lookup_maps_resolver_status(monkeypatch):
    from starlette.testclient import TestClient

    monkeypatch.setattr(rl, "require_auth", lambda request: {"uid": "u-lit-oa-api"})
    client = TestClient(_lit_app())

    async def oa_pdf(client, doi):
        return {"isOa": True, "oaUrl": "https://arxiv.org/pdf/2401.00001.pdf",
                "oaStatus": "green", "doi": doi}

    monkeypatch.setattr(rl.oa_resolver, "resolve_doi", oa_pdf)
    body = client.get("/api/research/literature/oa?doi=10.1000/x").json()
    assert body["status"] == "oa_pdf"
    assert body["oaUrl"].endswith(".pdf")

    async def landing(client, doi):
        return {"isOa": True, "oaUrl": "https://example.test/article/9",
                "oaStatus": "green"}

    monkeypatch.setattr(rl.oa_resolver, "resolve_doi", landing)
    assert client.get("/api/research/literature/oa?doi=10.1000/y").json()[
        "status"] == "oa_landing"

    async def errored(client, doi):
        return {"isOa": False, "oaUrl": "", "error": True}

    monkeypatch.setattr(rl.oa_resolver, "resolve_doi", errored)
    assert client.get("/api/research/literature/oa?doi=10.1000/z").json()[
        "status"] == "unknown"

    async def closed(client, doi):
        return {"isOa": False, "oaUrl": "", "error": False}

    monkeypatch.setattr(rl.oa_resolver, "resolve_doi", closed)
    assert client.get("/api/research/literature/oa?doi=10.1000/w").json()[
        "status"] == "no_legal_copy"

    assert client.get("/api/research/literature/oa").status_code == 400
    monkeypatch.setattr(rl, "_limiter", _DeniedLimiter())
    assert client.get("/api/research/literature/oa?doi=10.1000/x").status_code == 429


def test_venues_lookup_uses_registry(monkeypatch):
    from starlette.testclient import TestClient

    monkeypatch.setattr(rl, "require_auth", lambda request: {"uid": "u-lit-venue"})
    client = TestClient(_lit_app())
    assert client.get("/api/research/literature/venues").status_code == 400
    assert client.get("/api/research/literature/venues?issn=,%20").status_code == 400

    body = client.get(
        "/api/research/literature/venues?issn=0028-0836,1476-4687&field=math").json()
    assert body["found"] is True
    assert body["venue"]["name"] == "Nature"
    assert body["tier"] == "T0"
    assert body["peerReviewed"] is True
    assert body["field"] == "math"
    assert body["label"].startswith("Nature")
    assert body["registryVersion"]

    missing = client.get(
        "/api/research/literature/venues?name=Journal%20of%20Nothing").json()
    assert missing["found"] is False
    assert "venue" not in missing


def test_sources_info_reports_key_configuration(monkeypatch):
    from starlette.testclient import TestClient

    monkeypatch.setattr(rl, "require_auth", lambda request: {"uid": "u-lit-src"})
    monkeypatch.delenv("MG_ADS_API_KEY", raising=False)
    monkeypatch.setenv("MG_NCBI_API_KEY", "ncbi-key")
    client = TestClient(_lit_app())
    body = client.get("/api/research/literature/sources").json()
    by_id = {s["id"]: s for s in body["sources"]}
    assert by_id["ads"]["keyConfigured"] is False
    assert by_id["ads"]["keyRequired"] is True
    assert by_id["pubmed"]["keyConfigured"] is True
    assert by_id["crossref"]["keyConfigured"] is True   # 无 key 要求的源视为已配置
    assert by_id["arxiv"]["capabilities"]["download"] is True
    assert by_id["crossref"]["capabilities"]["oa"] is False
    assert body["registryVersion"]


# ---------- 开放获取下载:白名单 / 重定向 / 大小与类型校验 ----------

_PDF_URL = "https://arxiv.org/pdf/2401.00001.pdf"
_PAGE_URL = "https://europepmc.org/article/MED/1"


def test_download_pdf_rejects_untrusted_and_private_hosts(monkeypatch):
    with pytest.raises(ValueError):
        asyncio.run(rl._download_pdf(
            _StreamClient(lambda url: _Body([b"%PDF-1"])), "http://127.0.0.1/a.pdf"))
    _allow_public(monkeypatch, False)
    with pytest.raises(ValueError):
        asyncio.run(rl._download_pdf(
            _StreamClient(lambda url: _Body([b"%PDF-1"])), _PDF_URL))


def test_download_pdf_follows_redirect_and_validates_content(monkeypatch):
    _allow_public(monkeypatch)

    def handler(url):
        if url.endswith("/redirect"):
            return _Body([], status_code=302, headers={"location": _PDF_URL})
        return _Body([b"%PDF-", b"payload"],
                     headers={"content-type": "application/pdf"})

    data = asyncio.run(rl._download_pdf(
        _StreamClient(handler), "https://arxiv.org/pdf/redirect"))
    assert data == b"%PDF-payload"

    with pytest.raises(ValueError):
        asyncio.run(rl._download_pdf(
            _StreamClient(lambda url: _Body([b"<html>"])), _PDF_URL))

    monkeypatch.setattr(rl.rc, "MAX_UPLOAD_BYTES", 4)
    with pytest.raises(ValueError):
        asyncio.run(rl._download_pdf(
            _StreamClient(lambda url: _Body([b"%PDF-123456"])), _PDF_URL))

    with pytest.raises(httpx.HTTPStatusError):
        asyncio.run(rl._download_pdf(
            _StreamClient(lambda url: _Body([], status_code=503)), _PDF_URL))


def test_download_pdf_rejects_too_many_redirects(monkeypatch):
    _allow_public(monkeypatch)
    target = "https://arxiv.org/pdf/loop"
    client = _StreamClient(
        lambda url: _Body([], status_code=301, headers={"location": target}))
    with pytest.raises(ValueError):
        asyncio.run(rl._download_pdf(client, target))
    assert len(client.urls) == 3        # 最多跟 3 次跳转


def test_download_page_checks_content_type_and_size(monkeypatch):
    _allow_public(monkeypatch)
    data = asyncio.run(rl._download_page(
        _StreamClient(lambda url: _Body(
            [b"<html>ok</html>"],
            headers={"content-type": "text/html; charset=utf-8"})), _PAGE_URL))
    assert data == b"<html>ok</html>"

    with pytest.raises(ValueError):
        asyncio.run(rl._download_page(
            _StreamClient(lambda url: _Body(
                [b"x"], headers={"content-type": "image/png"})), _PAGE_URL))

    with pytest.raises(ValueError):
        asyncio.run(rl._download_page(
            _StreamClient(lambda url: _Body(
                [b"  "], headers={"content-type": "text/plain"})), _PAGE_URL))

    with pytest.raises(ValueError):
        asyncio.run(rl._download_page(
            _StreamClient(lambda url: _Body([b"x"])), "https://example.test/page"))

    _allow_public(monkeypatch, False)
    with pytest.raises(ValueError):
        asyncio.run(rl._download_page(
            _StreamClient(lambda url: _Body([b"x"])), _PAGE_URL))


def test_download_allowed_helpers_reject_unsafe_urls():
    with pytest.raises(ValueError):
        asyncio.run(rl.download_allowed_pdf("https://example.test/a.pdf"))
    with pytest.raises(ValueError):
        asyncio.run(rl.download_allowed_page("https://example.test/page"))


def test_save_pdf_writes_once_and_prunes_old_files(monkeypatch, tmp_path):
    monkeypatch.setattr(rl.rc, "DATA_DIR", tmp_path / "research")
    first = rl._save_pdf("u1", b"%PDF-one")
    again = rl._save_pdf("u1", b"%PDF-one")
    assert first == again and first.exists()
    assert first.read_bytes() == b"%PDF-one"

    folder = first.parent
    for index in range(23):
        extra = folder / f"old{index}.pdf"
        extra.write_bytes(b"%PDF-old")
        os.utime(extra, (1000 + index, 1000 + index))
    os.utime(first, (500, 500))

    rl._save_pdf("u1", b"%PDF-two")
    assert len(list(folder.glob("*.pdf"))) == 20


def test_save_pdf_uses_safe_uid_folder(monkeypatch, tmp_path):
    monkeypatch.setattr(rl.rc, "DATA_DIR", tmp_path / "research")
    path = rl._save_pdf("../bad uid", b"%PDF-x")
    assert path.parent.parent.parent == tmp_path / "research"   # 无法逃出数据目录
    assert "/" not in path.parent.name and "\\" not in path.parent.name
    assert path.exists()


def test_open_pdf_rejects_remote_host_and_rate_limit(monkeypatch):
    from starlette.applications import Starlette
    from starlette.routing import Route
    from starlette.testclient import TestClient

    monkeypatch.setattr(rl, "require_auth", lambda request: {"uid": "u-pdf-guard"})
    app = Starlette(routes=[
        Route("/api/lit/open-pdf", rl.open_pdf, methods=["POST"])])
    client = TestClient(app)

    monkeypatch.setattr(rl, "_print_allowed", lambda request: False)
    assert client.post("/api/lit/open-pdf", json={"url": _PDF_URL}).status_code == 403

    monkeypatch.setattr(rl, "_print_allowed", lambda request: True)
    monkeypatch.setattr(rl, "_limiter", _DeniedLimiter())
    assert client.post("/api/lit/open-pdf", json={"url": _PDF_URL}).status_code == 429


def test_open_pdf_maps_download_errors(monkeypatch):
    from starlette.applications import Starlette
    from starlette.routing import Route
    from starlette.testclient import TestClient

    monkeypatch.setattr(rl, "require_auth", lambda request: {"uid": "u-pdf-err"})
    monkeypatch.setattr(rl, "_print_allowed", lambda request: True)
    app = Starlette(routes=[
        Route("/api/lit/open-pdf", rl.open_pdf, methods=["POST"])])
    client = TestClient(app)

    bad = client.post("/api/lit/open-pdf", json={"url": "https://example.test/a.pdf"})
    assert bad.status_code == 400

    _allow_public(monkeypatch)

    def boom(url):
        raise httpx.ConnectError("down")

    monkeypatch.setattr(rl.httpx, "AsyncClient", lambda *a, **k: _StreamClient(boom))
    dead = client.post("/api/lit/open-pdf", json={"url": _PDF_URL})
    assert dead.status_code == 502

    monkeypatch.setattr(rl.httpx, "AsyncClient", lambda *a, **k: _StreamClient(
        lambda url: _Body([b"<html>"])))
    not_pdf = client.post("/api/lit/open-pdf", json={"url": _PDF_URL})
    assert not_pdf.status_code == 400
