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


def test_title_match_continues_to_doi_pdf(monkeypatch):
    async def fake_title(client, title, limit=5):
        candidate = rf.make_candidate(
            "https://doi.org/10.1/x", kind="landing", source="crossref")
        candidate["title"] = "Attention Is All You Need"
        candidate["doi"] = "10.1/x"
        candidate["similarity"] = 0.99
        return [candidate]

    async def fake_doi(client, doi, errors):
        return [rf.make_candidate(
            "https://arxiv.org/pdf/2410.12345", kind="pdf", source="arxiv",
            server_downloadable=True)]

    monkeypatch.setattr(rf, "_title_candidates", fake_title)
    monkeypatch.setattr(rf, "_doi_candidates", fake_doi)
    result = asyncio.run(rf.resolve(object(), title="Attention Is All You Need"))
    assert result["status"] == "oa_pdf"
    assert result["best"]["source"] == "arxiv"


def test_make_candidate_rejects_non_https_url():
    candidate = rf.make_candidate(
        "javascript:alert(1)", kind="landing", source="crossref")
    assert candidate["url"] == ""


def test_arxiv_pdf_path_without_suffix_is_classified_pdf(monkeypatch):
    async def fake_resolve(client, doi):
        return {
            "isOa": True, "oaUrl": "https://arxiv.org/pdf/2410.12345",
            "resolver": "openalex", "oaSource": "repository",
            "version": "submittedVersion", "license": "", "error": False,
        }

    monkeypatch.setattr(rf.oa, "resolve_doi", fake_resolve)
    rf._CACHE.clear()
    result = asyncio.run(rf.resolve(object(), doi="10.1/x"))
    assert result["best"]["kind"] == "pdf"
    assert result["status"] == "oa_pdf"


def test_resolve_caches_doi_lookup(monkeypatch):
    calls = 0

    async def fake_doi(client, doi, errors):
        nonlocal calls
        calls += 1
        return [rf.make_candidate(
            "https://arxiv.org/pdf/1", kind="pdf", source="arxiv",
            server_downloadable=True)]

    monkeypatch.setattr(rf, "_doi_candidates", fake_doi)
    rf._CACHE.clear()
    first = asyncio.run(rf.resolve(object(), doi="10.1/x"))
    second = asyncio.run(rf.resolve(object(), doi="10.1/x"))
    assert first["status"] == second["status"] == "oa_pdf"
    assert calls == 1
    rf._CACHE.clear()


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


# ---------------------------------------------------------------------------
# 追加:URL 白名单、逐个解析器的失败降级、缓存 TTL 与端点状态码。
# 为什么重要:这一层的输出直接决定"能不能给用户一个合法全文链接",
# 解析器静默返回 [] 与"确实没有合法副本"必须区分开(unknown vs no_legal_copy)。
# ---------------------------------------------------------------------------

class _Resp:
    """httpx 响应的最小替身:只需 status_code / json() / text。"""

    def __init__(self, *, status_code: int = 200, payload=None, text: str = ""):
        self.status_code = status_code
        self._payload = payload
        self.text = text

    def json(self):
        return self._payload


class _Client:
    """按 URL 关键字返回预置响应的假 client,并记录请求参数。"""

    def __init__(self, routes: dict[str, _Resp]):
        self.routes = routes
        self.calls: list[tuple[str, dict]] = []

    async def get(self, url, params=None, timeout=None):
        self.calls.append((url, dict(params or {})))
        for key, resp in self.routes.items():
            if key in url:
                return resp
        return _Resp(status_code=404)


def test_safe_url_rejects_non_https_credentials_and_junk():
    """候选链接必须是干净的 https 绝对地址。

    javascript:/自带凭据/含控制字符的链接一旦落地到前端,就是点击即中招。
    """
    assert rf._safe_url("https://example.org/paper.pdf") == "https://example.org/paper.pdf"
    assert rf._safe_url("http://example.org/paper.pdf") == ""      # 非 https
    assert rf._safe_url("https://") == ""                          # 没有主机名
    assert rf._safe_url("https://user:pw@example.org/x") == ""     # 带凭据
    assert rf._safe_url("https://example.org/a\tb") == ""          # 含制表符
    assert rf._safe_url("https://[::1") == ""                      # urlparse 直接抛 ValueError
    assert rf._safe_url(None) == ""
    assert len(rf._safe_url("https://example.org/" + "x" * 2000)) == 1000


def test_looks_like_pdf_matches_path_shapes():
    assert rf._looks_like_pdf("https://example.org/paper.pdf")
    assert rf._looks_like_pdf("https://example.org/paper.pdf/")
    assert rf._looks_like_pdf("https://example.org/pdf")
    assert rf._looks_like_pdf("https://arxiv.org/pdf/2501.00001")
    assert not rf._looks_like_pdf("https://example.org/abstract")
    assert not rf._looks_like_pdf("")


def test_dedupe_drops_candidates_without_url_and_keeps_best_rank():
    """没有 url 的候选直接丢掉;同 URL 保留排名更高的那份。

    空 URL 进结果就是一条点不开的"全文链接"。
    """
    no_url = rf.make_candidate("javascript:void(0)", kind="pdf", source="arxiv")
    low = rf.make_candidate("https://example.org/p", kind="landing", source="dblp")
    high = rf.make_candidate("https://example.org/p", kind="pdf", source="unpaywall",
                             server_downloadable=True)
    out = rf.dedupe_candidates([no_url, low, high])
    assert len(out) == 1
    assert out[0]["source"] == "unpaywall"
    assert out[0]["kind"] == "pdf"


def test_choose_status_preprint_and_landing_precedence():
    """status 的判定顺序:可下载 PDF > 落地页/PDF > 预印本 > unknown/no_legal_copy。

    unknown 与 no_legal_copy 的区别是"源出错"还是"确实没有",
    前端文案完全不同,不能混。
    """
    preprint = rf.make_candidate("https://example.org/pre", kind="other",
                                 source="crossref", is_preprint=True)
    landing = rf.make_candidate("https://example.org/p", kind="landing",
                                source="crossref")
    assert rf.choose_status([preprint], []) == "preprint"
    assert rf.choose_status([preprint, landing], []) == "oa_landing"
    # 源出错且无候选 → unknown(不是"没有合法副本")
    assert rf.choose_status([], ["doi: resolver error"]) == "unknown"
    assert rf.choose_status([], []) == "no_legal_copy"


def test_doi_candidates_records_resolver_error_and_skips_empty_url(monkeypatch):
    """解析器报错要落进 source_errors(影响 status 与提示),空 URL 不产生候选。"""
    async def erroring(client, doi):
        return {"error": True, "oaUrl": ""}

    monkeypatch.setattr(rf.oa, "resolve_doi", erroring)
    errors: list[str] = []
    assert asyncio.run(rf._doi_candidates(object(), "10.1/x", errors)) == []
    assert errors == ["doi: resolver error"]

    async def closed(client, doi):
        return {"error": False, "oaUrl": ""}

    monkeypatch.setattr(rf.oa, "resolve_doi", closed)
    errors = []
    assert asyncio.run(rf._doi_candidates(object(), "10.1/x", errors)) == []
    assert errors == []


def test_doi_candidates_marks_preprint_hosts_and_default_resolver(monkeypatch):
    """预印本服务器(arxiv/biorxiv/medrxiv)要打 isPreprint;缺 resolver 时默认 openalex。"""
    async def biorxiv(client, doi):
        return {"oaUrl": "https://www.biorxiv.org/content/10.1101/1.full.pdf"}

    monkeypatch.setattr(rf.oa, "resolve_doi", biorxiv)
    candidates = asyncio.run(rf._doi_candidates(object(), "10.1101/1", []))
    assert len(candidates) == 1
    assert candidates[0]["source"] == "openalex"     # resolver 缺失时的兜底
    assert candidates[0]["isPreprint"] is True
    assert candidates[0]["kind"] == "pdf"
    assert candidates[0]["version"] == "unknown"

    async def journal(client, doi):
        return {"oaUrl": "https://example.org/article", "resolver": "unpaywall"}

    monkeypatch.setattr(rf.oa, "resolve_doi", journal)
    candidate = asyncio.run(rf._doi_candidates(object(), "10.1/x", []))[0]
    assert candidate["isPreprint"] is False
    assert candidate["kind"] == "landing"


def test_title_similarity_returns_zero_for_empty_side():
    assert rf.title_similarity("", "anything") == 0.0
    assert rf.title_similarity("anything", "  ") == 0.0
    # 只有标点也算空(归一化后为空串)
    assert rf.title_similarity("!!!", "???") == 0.0


def test_title_candidates_skips_non_200_and_dirty_rows():
    """Crossref 非 200 → 空列表;非 dict 条目 / 无标题条目跳过;URL 缺失时用 DOI 拼。"""
    bad_status = _Client({"crossref": _Resp(status_code=429, payload={})})
    assert asyncio.run(rf._title_candidates(bad_status, "Attention")) == []

    payload = {"message": {"items": [
        "not-a-dict",
        {"title": [], "DOI": "10.1/empty"},                       # 无标题 → 跳过
        {"title": ["Attention Is All You Need"], "DOI": "10.1/A"},  # DOI 转小写
    ]}}
    client = _Client({"crossref": _Resp(payload=payload)})
    out = asyncio.run(rf._title_candidates(client, "Attention Is All You Need"))
    assert len(out) == 1
    assert out[0]["title"] == "Attention Is All You Need"
    assert out[0]["doi"] == "10.1/a"
    assert out[0]["url"] == "https://doi.org/10.1/a"    # item 无 URL 时用(已小写的)DOI 拼
    assert out[0]["similarity"] >= 0.99
    assert out[0]["kind"] == "landing" and out[0]["source"] == "crossref"


ARXIV_ATOM = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <id>https://arxiv.org/abs/2410.12345v1</id>
    <link href="https://arxiv.org/abs/2410.12345v1" rel="alternate"/>
    <link href="https://arxiv.org/pdf/2410.12345v1" rel="related" type="application/pdf"/>
  </entry>
  <entry>
    <id>https://arxiv.org/abs/2410.99999v1</id>
    <link href="https://arxiv.org/abs/2410.99999v1" rel="alternate"/>
  </entry>
</feed>"""


def test_arxiv_candidates_requires_pdf_link_and_keeps_landing():
    """只有带 pdf 链接的条目才算候选;landing 单独记到 landingUrl。

    只给 /abs/ 的条目下载不到 PDF,把它当候选会让用户点了 404。
    """
    client = _Client({"export.arxiv.org": _Resp(text=ARXIV_ATOM)})
    out = asyncio.run(rf._arxiv_candidates(client, "2410.12345"))
    assert len(out) == 1
    assert out[0]["url"] == "https://arxiv.org/pdf/2410.12345v1"
    assert out[0]["landingUrl"] == "https://arxiv.org/abs/2410.12345v1"
    assert out[0]["kind"] == "pdf" and out[0]["source"] == "arxiv"
    assert out[0]["isPreprint"] is True and out[0]["hostType"] == "preprint"


def test_arxiv_candidates_degrades_on_bad_status_and_bad_xml():
    """arXiv 返回 5xx 或坏 XML:返回空候选,不抛解析异常。"""
    assert asyncio.run(rf._arxiv_candidates(
        _Client({"export.arxiv.org": _Resp(status_code=503)}), "x")) == []
    assert asyncio.run(rf._arxiv_candidates(
        _Client({"export.arxiv.org": _Resp(text="<feed><entry>")}), "x")) == []


def test_pmc_candidates_normalizes_fulltext_links():
    """Europe PMC:fullTextUrl 可能是 dict 或 list;缺 url / 非 dict 的链接跳过。"""
    assert asyncio.run(rf._pmc_candidates(_Client({}), "", "")) == []

    payload = {"resultList": {"result": [
        "not-a-dict",
        {"fullTextUrlList": {"fullTextUrl": {
            "url": "https://europepmc.org/articles/PMC1/pdf",
            "documentStyle": "pdf", "availability": "Open access",
            "availabilityCode": "OA", "site": "Europe_PMC"}}},
        {"fullTextUrlList": {"fullTextUrl": [
            {"url": "https://example.org/landing"},
            {"url": ""},
            "dirty",
        ]}},
    ]}}
    client = _Client({"ebi.ac.uk": _Resp(payload=payload)})
    out = asyncio.run(rf._pmc_candidates(client, "123", "PMC1"))
    assert [c["url"] for c in out] == [
        "https://europepmc.org/articles/PMC1/pdf",
        "https://example.org/landing",
    ]
    assert out[0]["kind"] == "pdf"
    assert out[0]["source"] == "europepmc"
    assert out[0]["hostType"] == "repository"
    assert out[1]["kind"] == "landing"
    # 非 200 → 空成交(不抛)
    assert asyncio.run(rf._pmc_candidates(
        _Client({"ebi.ac.uk": _Resp(status_code=500)}), "123", "")) == []


def test_cache_ttl_differs_for_negative_results(monkeypatch):
    """缓存 TTL:有结果留 24h,"没有合法副本"只留 1h(作者可能刚挂预印本)。

    负结果缓存太久,用户今天传的新预印本明天还查不到。
    """
    rf._CACHE.clear()
    key = "doi=10.1/x"
    rf._CACHE[key] = (100.0, {"status": "oa_pdf"})
    monkeypatch.setattr(rf.time, "monotonic", lambda: 100.0 + rf._NEGATIVE_TTL + 1)
    assert rf._cache_get(key) == {"status": "oa_pdf"}     # 正结果不受 1h 影响

    rf._CACHE[key] = (100.0, {"status": "no_legal_copy"})
    monkeypatch.setattr(rf.time, "monotonic", lambda: 100.0 + rf._NEGATIVE_TTL + 1)
    assert rf._cache_get(key) is None                     # 负结果过期
    assert key not in rf._CACHE                           # 过期即删,不占位

    rf._CACHE[key] = (100.0, {"status": "oa_pdf"})
    monkeypatch.setattr(rf.time, "monotonic", lambda: 100.0 + rf._CACHE_TTL + 1)
    assert rf._cache_get(key) is None
    assert rf._cache_get("missing-key") is None
    rf._CACHE.clear()


def test_cache_put_skips_empty_key_and_ambiguous(monkeypatch):
    """不缓存空键与 ambiguous:ambiguous 依赖当次候选集,缓存会永久错答。"""
    rf._CACHE.clear()
    rf._cache_put("", {"status": "oa_pdf"})
    rf._cache_put("doi=1", {"status": "ambiguous"})
    assert rf._CACHE == {}

    rf._cache_put("doi=1", {"status": "oa_pdf", "best": {"url": "https://e.org/1"}})
    assert rf._CACHE["doi=1"][1]["status"] == "oa_pdf"
    # 取出来是深拷贝:调用方改它不会污染缓存
    cached = rf._cache_get("doi=1")
    cached["best"]["url"] = "https://evil.example"
    assert rf._cache_get("doi=1")["best"]["url"] == "https://e.org/1"
    rf._CACHE.clear()


def test_cache_put_evicts_oldest_when_full(monkeypatch):
    """缓存超过上限时逐出最旧条目,防止长期跑下去内存只涨不落。"""
    rf._CACHE.clear()
    monkeypatch.setattr(rf, "_CACHE_MAX", 2)
    monkeypatch.setattr(rf.time, "monotonic", lambda: 10.0)
    rf._cache_put("a", {"status": "oa_pdf"})
    monkeypatch.setattr(rf.time, "monotonic", lambda: 20.0)
    rf._cache_put("b", {"status": "oa_pdf"})
    monkeypatch.setattr(rf.time, "monotonic", lambda: 30.0)
    rf._cache_put("c", {"status": "oa_pdf"})
    assert sorted(rf._CACHE) == ["b", "c"]
    rf._CACHE.clear()


def test_resolve_queries_pmc_when_pmid_present(monkeypatch):
    """给了 pmid 就要问 Europe PMC,并把结果记进 matchedIdentifiers。"""
    async def pmc(client, pmid, pmcid):
        return [rf.make_candidate(
            "https://europepmc.org/articles/PMC1/pdf", kind="pdf",
            source="europepmc", server_downloadable=True)]

    monkeypatch.setattr(rf, "_pmc_candidates", pmc)
    rf._CACHE.clear()
    result = asyncio.run(rf.resolve(_Client({}), pmid="123", pmcid="PMC1"))
    assert result["status"] == "oa_pdf"
    assert result["best"]["url"] == "https://europepmc.org/articles/PMC1/pdf"
    assert {item["type"] for item in result["matchedIdentifiers"]} == {"pmid", "pmcid"}
    rf._CACHE.clear()


def test_resolve_title_match_on_arxiv_doi_also_fetches_arxiv_pdf(monkeypatch):
    """标题命中且 DOI 是 10.48550/arxiv.* 时,要顺带补 arXiv 的 PDF 候选。

    只走 DOI 解析器常常只拿到落地页,补一次 arXiv 才能给出"能直接下载"的链接。
    """
    async def title_candidates(client, title, limit=5):
        item = rf.make_candidate("https://doi.org/10.48550/arXiv.2410.12345",
                                 kind="landing", source="crossref")
        item["doi"] = "10.48550/arxiv.2410.12345"
        item["similarity"] = 0.99
        return [item]

    async def doi_candidates(client, doi, errors):
        return [rf.make_candidate("https://doi.org/10.48550/arxiv.2410.12345",
                                  kind="landing", source="openalex")]

    seen: list[str] = []

    async def arxiv_candidates(client, arxiv_id):
        seen.append(arxiv_id)
        return [rf.make_candidate("https://arxiv.org/pdf/2410.12345", kind="pdf",
                                  source="arxiv", is_preprint=True)]

    monkeypatch.setattr(rf, "_title_candidates", title_candidates)
    monkeypatch.setattr(rf, "_doi_candidates", doi_candidates)
    monkeypatch.setattr(rf, "_arxiv_candidates", arxiv_candidates)
    rf._CACHE.clear()
    result = asyncio.run(rf.resolve(_Client({}), title="Spectral gaps"))
    assert seen == ["2410.12345"]
    assert result["best"]["source"] == "arxiv"
    assert result["status"] == "oa_pdf"
    rf._CACHE.clear()


def test_fulltext_endpoint_rejects_empty_query_and_rate_limit(monkeypatch):
    """端点:一个标识符都没有 → 400;超过频率 → 429。

    400 是"你少填了参数",429 是"慢一点",前端文案与重试策略都不同。
    """
    from starlette.applications import Starlette
    from starlette.routing import Route
    from starlette.testclient import TestClient

    monkeypatch.setattr(rf, "require_auth", lambda request: {"uid": "u"})
    monkeypatch.setattr(rf, "_limiter", rf.SlidingWindowLimiter(100, 60))

    async def fake_resolve(client, **kwargs):
        return {"status": "no_legal_copy", "identifier": None,
                "matchedIdentifiers": [], "best": None, "alternatives": [],
                "candidates": [], "reason": ""}

    monkeypatch.setattr(rf, "resolve", fake_resolve)   # 零网络:不碰外部 API
    app = Starlette(routes=[Route("/api/research/fulltext", rf.fulltext_lookup)])
    client = TestClient(app)
    assert client.get("/api/research/fulltext").status_code == 400
    assert client.get("/api/research/fulltext?doi=%20%20").status_code == 400

    monkeypatch.setattr(rf, "_limiter", rf.SlidingWindowLimiter(1, 60))
    assert client.get("/api/research/fulltext?doi=10.1/a").status_code == 200
    assert client.get("/api/research/fulltext?doi=10.1/b").status_code == 429


def test_fulltext_endpoint_passes_all_identifiers_through(monkeypatch):
    """端点把 5 个标识符全部交给 resolve(各自截断到上限),不做自己的拼装判断。"""
    from starlette.applications import Starlette
    from starlette.routing import Route
    from starlette.testclient import TestClient

    captured: dict = {}

    async def fake_resolve(client, **kwargs):
        captured.update(kwargs)
        return {"status": "no_legal_copy", "identifier": None,
                "matchedIdentifiers": [], "best": None, "alternatives": [],
                "candidates": [], "reason": ""}

    monkeypatch.setattr(rf, "resolve", fake_resolve)
    monkeypatch.setattr(rf, "require_auth", lambda request: {"uid": "u-pass"})
    monkeypatch.setattr(rf, "_limiter", rf.SlidingWindowLimiter(100, 60))
    app = Starlette(routes=[Route("/ft", rf.fulltext_lookup)])
    client = TestClient(app)
    res = client.get("/ft?doi=10.1/x&arxivId=2410.1&pmid=9&pmcid=pmc9&title=T" + "t" * 400)
    assert res.status_code == 200
    assert res.json()["status"] == "no_legal_copy"
    assert captured["doi"] == "10.1/x"
    assert captured["arxiv_id"] == "2410.1"
    assert captured["pmid"] == "9"
    assert captured["pmcid"] == "pmc9"
    assert len(captured["title"]) == 300      # title 截断上限



