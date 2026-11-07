# 科研区专业研究工具与合法全文 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在科研区接入合法全文获取、五学科来源、独立回归计算与科研图解，学习辅助区保持不变。

**Architecture:** P0 把现有 `research_lit`/`research_oa` 扩展成 `research_fulltext`，用可信 OA 域注册表守住下载边界；P1 用独立 analysis worker 承载 statsmodels/SciPy/pandas，主服务只传结构化请求；P2 复用现有图解渲染器，只增加科研规划器和服务端确定性数据图。P3 只做学科包能力探测，不默认安装。

**Tech Stack:** Python 3.11+、Starlette、httpx、pytest、statsmodels/SciPy/pandas（独立 worker venv）；Vue 3 `<script setup>`、TypeScript、Vite、现有 Node/esbuild 测试。

**Spec:** `docs/superpowers/specs/2026-11-06-research-tools-integration-design.md`

## Global Constraints

- 只改科研区；学习辅助区的布局、入口、图解提示词和功能边界不动。
- 不接 Sci-Hub，不绕付费墙，不批量下载，不分享订阅 PDF。
- 不保存 CARSI cookie、机构账号密码、出版社会话。
- 服务端可下载 PDF 只由可信 OA 域注册表决定；`Content-Type: application/pdf` 不能单独放行任意 host。
- 未配置 `MG_UNPAYWALL_EMAIL` 时跳过 Unpaywall，不阻断 OpenAlex/Europe PMC/arXiv。
- 回归首版只做 OLS、多元线性、单 X 多项式 2–4 次；listwise 缺失；必须有截距；不做指数/对数/幂函数。
- statsmodels/SciPy/pandas 只装在独立 worker venv；主服务不装；不安装 matplotlib。
- 回归结果不落库；聊天携带 `regressionSpec`，服务端按当前表重算。
- 科研数据图由服务端按计算结果确定性生成；模型不得写数据点或拟合系数。
- 数值输出沿用现有 4 位小数规则；模型只解释，不计算。
- 现有后端 pytest、前端 `npm test`、`vue-tsc` 与 build 必须全过。

## Review Focus

- DOI 无全文但同一记录的 arXiv 有 PDF：必须返回 `oa_pdf`，不能因为主标识符 closed 就丢弃合法副本。
- 标题检索并列候选或相似度不足：必须返回 `ambiguous`，不能自动取第一条。
- 私有地址、localhost、重定向到内网、非 PDF 响应：必须拒绝，不能进入下载路径。
- 缺失值、共线矩阵、n 不足：必须返回错误码，不能输出系数、p 值或图。
- 回归运行后表格被编辑：聊天必须按当前表重算并给 `table_changed` 警告，不能引用旧结果。
- 科研区新增能力不得出现在学习区；学习区现有图解回归测试必须保持通过。

---

### Task 0: 基线确认

**Files:**
- Read: `backend/pytest.ini`, `frontend/package.json`
- No code changes.

**Interfaces:**
- Consumes: none.
- Produces: clean baseline for later tasks.

- [ ] **Step 1: Check worktree state**

Run:

```bash
git status --short
git branch --show-current
```

Expected: know exactly which files are already modified. Do not mix unrelated worktree changes into this feature; commit them as WIP or use a fresh worktree before Task 1.

- [ ] **Step 2: Run backend baseline**

Run:

```bash
cd backend && python -m pytest -q
```

Expected: all existing tests pass. If not, stop and report the failing tests before changing code.

- [ ] **Step 3: Run frontend baseline**

Run:

```bash
cd frontend && npm test
```

Expected: all suites pass.

- [ ] **Step 4: Run type/build baseline**

Run:

```bash
cd frontend && npm run build
```

Expected: `vue-tsc` and Vite build pass.

- [ ] **Step 5: Commit only if the user asked for commits**

Do not commit baseline-only changes. If the worktree needed a WIP commit to separate existing changes, use a message that names the existing feature, not this plan.

---

### Task 1: 计算机学科与 DBLP 来源

**Files:**
- Modify: `backend/research_sources.py`
- Modify: `backend/research_lit.py`
- Modify: `frontend/src/services/literatureService.ts`
- Modify: `frontend/src/views/ResearchSearchView.vue`
- Modify: `frontend/src/utils/i18n.ts`
- Test: `backend/tests/test_research_sources.py`
- Test: `backend/tests/test_research_lit.py`

**Interfaces:**
- Consumes: existing `SourceSpec`, `_result`, `_clean`, `_run_providers`.
- Produces:
  - `ALL_FIELDS = ("general", "math", "physics", "chemistry", "biology", "computer")`
  - `SPECS["dblp"]` with `domains=("computer",)`, `tier="discovery"`, `fulltext="landing"`
  - `_dblp(client: httpx.AsyncClient, query: str, limit: int, filters: dict | None) -> list[dict]`
  - `LiteratureQuery.field` includes `'computer'`.

- [ ] **Step 1: Write failing backend tests**

Add to `backend/tests/test_research_sources.py`:

```python
def test_computer_sources_route_by_field():
    ids = {s.id for s in rs.specs_for("computer", True)}
    assert {"dblp", "crossref", "arxiv", "openalex", "semanticscholar"} <= ids
    assert "pubmed" not in ids
    assert "zbmath" not in ids
    assert rs.SPECS["dblp"].domains == ("computer",)
```

Add to `backend/tests/test_research_lit.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
cd backend && python -m pytest tests/test_research_sources.py::test_computer_sources_route_by_field tests/test_research_lit.py::test_dblp_parses_hit_list -v
```

Expected: FAIL because `computer`, `dblp`, and `_dblp` do not exist.

- [ ] **Step 3: Implement source registry and provider**

In `backend/research_sources.py`:

- Add `"computer"` to `ALL_FIELDS`.
- Add `computer` to `domains` for `crossref`, `arxiv`, `openalex`, `semanticscholar`, and `doaj`.
- Add:

```python
"dblp": SourceSpec(
    "dblp", "DBLP",
    ("computer",),
    "discovery", False, fulltext="landing"),
```

In `backend/research_lit.py`:

- Add `"dblp": _dblp` to `_provider_funcs`.
- Implement `_dblp` using `https://dblp.org/search/publ/api` with `q`, `format=json`, `h=limit`.
- Normalize `info.authors.author` whether it is a dict or list.
- Use `_result(title=..., authors=..., year=..., venue=..., doi=..., url=..., pdfUrl="", abstract="", sources=["dblp"], sourceTier="discovery", peerReviewed=False, articleType="article", landingUrl=...)`.
- Add `computer` weights to `_sort_results` (same as `general` for DBLP; arXiv stays preprint).

- [ ] **Step 4: Run backend tests to verify they pass**

Run:

```bash
cd backend && python -m pytest tests/test_research_sources.py::test_computer_sources_route_by_field tests/test_research_lit.py::test_dblp_parses_hit_list -v
```

Expected: PASS.

- [ ] **Step 5: Update frontend field selector**

In `frontend/src/services/literatureService.ts`, change the union to include `'computer'`.

In `frontend/src/views/ResearchSearchView.vue`:

```ts
const litField = ref<'general' | 'math' | 'physics' | 'chemistry' | 'biology' | 'computer'>('general')
```

Add under the biology option:

```html
<option value="computer">{{ t('search.fieldComputer') }}</option>
```

In `frontend/src/utils/i18n.ts`, add the Chinese key in the Chinese block and the English key in the English block:

```ts
// 中文块
'search.fieldComputer': '计算机',
// English block
'search.fieldComputer': 'Computer science',
```

- [ ] **Step 6: Run frontend checks**

Run:

```bash
cd frontend && npm test && npm run build
```

Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add backend/research_sources.py backend/research_lit.py backend/tests/test_research_sources.py backend/tests/test_research_lit.py frontend/src/services/literatureService.ts frontend/src/views/ResearchSearchView.vue frontend/src/utils/i18n.ts
git commit -m "feat: 科研区增加计算机学科与 DBLP 来源"
```

---

### Task 2: 全文解析核心与 DOI 适配

**Files:**
- Create: `backend/research_fulltext.py`
- Create: `backend/tests/test_research_fulltext.py`
- Read: `backend/research_oa.py`

**Interfaces:**
- Consumes: `research_oa.resolve_doi(client, doi)`.
- Produces:
  - `STATUSES = {"oa_pdf", "oa_landing", "preprint", "institutional", "no_legal_copy", "unknown", "ambiguous"}`
  - `def normalize_identifiers(*, doi="", arxiv_id="", pmid="", pmcid="", title="") -> dict[str, str]`
  - `def make_candidate(url: str, *, kind: str, source: str, host_type: str = "", version: str = "", license: str = "", server_downloadable: bool = False, is_preprint: bool = False) -> dict`
  - `def dedupe_candidates(candidates: list[dict]) -> list[dict]`
  - `def choose_status(candidates: list[dict], source_errors: list[str]) -> str`
  - `async def _doi_candidates(client: httpx.AsyncClient, doi: str, source_errors: list[str]) -> list[dict]`
  - `async def resolve(client: httpx.AsyncClient, *, doi="", arxiv_id="", pmid="", pmcid="", title="") -> dict`

- [ ] **Step 1: Write failing tests**

Create `backend/tests/test_research_fulltext.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
cd backend && python -m pytest tests/test_research_fulltext.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'research_fulltext'`.

- [ ] **Step 3: Implement core data model**

In `backend/research_fulltext.py`:

- `normalize_identifiers` strips whitespace; DOI lowercased; arXiv ID preserved with version suffix; PMID/PMCID trimmed.
- `make_candidate` returns exactly:

```python
{
    "url": url,
    "kind": kind,                 # "pdf" | "landing" | "html"
    "source": source,
    "hostType": host_type,
    "version": version or "unknown",
    "license": license,
    "serverDownloadable": bool(server_downloadable),
    "isPreprint": bool(is_preprint),
}
```

- `dedupe_candidates` dedupes by URL; prefers `kind == "pdf"`, then `serverDownloadable`, then source priority.
- `choose_status` order: any `pdf`/`serverDownloadable` → `oa_pdf`; any `landing`/`html` → `oa_landing`; any `isPreprint` → `preprint`; else `no_legal_copy` if no source errors, `unknown` if errors.

- [ ] **Step 4: Implement DOI resolve path**

`_doi_candidates(client, doi, source_errors)`:

1. Call `research_oa.resolve_doi(client, doi)`.
2. Map non-empty `oaUrl` to a candidate:
   - `kind="pdf"` if URL path ends with `.pdf` (case-insensitive), else `"landing"`.
   - `source=result.get("resolver") or "openalex"`.
   - `host_type=result.get("oaSource")`.
   - `version=result.get("version") or "unknown"`.
   - `license=result.get("license")`.
   - `server_downloadable` is set in Task 3 by URL safety; for now `False`.
3. If resolver `error` is true, append `"doi: resolver error"` to `source_errors`.

`resolve` should:

1. Normalize identifiers.
2. Initialize `candidates = []` and `source_errors = []`.
3. If DOI: `candidates += await _doi_candidates(client, doi, source_errors)`.
4. Return:

```python
{
    "status": choose_status(candidates, source_errors),
    "identifier": {"type": "doi", "value": doi} if doi else None,
    "matchedIdentifiers": [{"type": "doi", "value": doi}] if doi else [],
    "best": candidates[0] if candidates else None,
    "alternatives": candidates[1:],
    "candidates": [],
    "reason": "; ".join(source_errors)[:300],
}
```

- [ ] **Step 5: Run tests to verify they pass**

Run:

```bash
cd backend && python -m pytest tests/test_research_fulltext.py -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/research_fulltext.py backend/tests/test_research_fulltext.py
git commit -m "feat: 全文解析核心与 DOI 候选归一化"
```

---

### Task 3: 多标识符、标题歧义与 URL 安全

**Files:**
- Modify: `backend/research_fulltext.py`
- Create: `backend/research_urls.py`
- Modify: `backend/research_lit.py`
- Modify: `backend/research_papers.py`
- Test: `backend/tests/test_research_fulltext.py`
- Test: `backend/tests/test_research_literature_urls.py`

**Interfaces:**
- Consumes: Task 2 `make_candidate`, `dedupe_candidates`, `choose_status`.
- Produces:
  - `research_urls.is_https_url(url: str) -> bool`
  - `research_urls.is_trusted_pdf_host(url: str) -> bool`
  - `research_urls.is_safe_pdf_url(url: str) -> bool`
  - `research_urls.is_forbidden_host(host: str) -> bool`
  - `research_fulltext.title_similarity(a: str, b: str) -> float`
  - `research_fulltext._arxiv_candidates(client, arxiv_id: str) -> list[dict]`
  - `research_fulltext._pmc_candidates(client, pmid: str, pmcid: str) -> list[dict]`
  - `research_fulltext._title_candidates(client, title: str, limit: int = 5) -> list[dict]`

- [ ] **Step 1: Write failing URL safety tests**

Add to `backend/tests/test_research_literature_urls.py`:

```python
import research_urls as ru


def test_private_and_local_urls_are_rejected():
    for url in (
        "http://example.org/a.pdf",
        "https://localhost/a.pdf",
        "https://127.0.0.1/a.pdf",
        "https://10.0.0.1/a.pdf",
        "https://192.168.1.2/a.pdf",
        "https://169.254.1.1/a.pdf",
        "https://user:pass@example.org/a.pdf",
    ):
        assert not ru.is_safe_pdf_url(url)


def test_trusted_pdf_host_allows_subdomains_only_for_known_hosts():
    assert ru.is_trusted_pdf_host("https://arxiv.org/pdf/2410.12345")
    assert ru.is_trusted_pdf_host("https://export.arxiv.org/pdf/2410.12345")
    assert ru.is_trusted_pdf_host("https://pmc.ncbi.nlm.nih.gov/articles/PMC1/pdf")
    assert not ru.is_trusted_pdf_host("https://link.springer.com/content/pdf/1.pdf")
    assert not ru.is_trusted_pdf_host("https://evil-arxiv.org/a.pdf")
```

- [ ] **Step 2: Write failing resolver tests**

Add to `backend/tests/test_research_fulltext.py`:

```python
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
```

- [ ] **Step 3: Implement URL safety**

Create `backend/research_urls.py`:

- `TRUSTED_PDF_HOSTS = ("arxiv.org", "europepmc.org", "ebi.ac.uk", "ncbi.nlm.nih.gov", "plos.org", "mdpi.com", "frontiersin.org", "biomedcentral.com")`
- `is_trusted_pdf_host` matches exact host or `host.endswith("." + suffix)`.
- `is_forbidden_host` rejects `localhost`, `*.localhost`, `*.local`, bracketed IPv6 literals, and any IPv4/IPv6 literal that is loopback, private, link-local, multicast, reserved, or unspecified.
- `is_https_url` checks scheme, hostname, no username/password, no whitespace/control chars.
- `is_safe_pdf_url` = `is_https_url` and not forbidden and trusted host.
- Keep DNS resolution out of the pure function; the fulltext fetch path will resolve host before download in Task 5.

Modify `research_lit._pdf_url_allowed` to return `research_urls.is_safe_pdf_url(url)`.
Modify `research_papers.create_temp` to use the same (it already calls `lit._pdf_url_allowed`, so no change needed if delegation works).

- [ ] **Step 4: Implement arXiv, PMC, and title adapters**

In `research_fulltext.py`:

- `title_similarity` uses `difflib.SequenceMatcher` on normalized lowercase alphanumeric tokens.
- `_title_candidates` calls Crossref `https://api.crossref.org/works` with `query.title`, `rows=5`; returns candidate dicts with `title`, `doi`, `url`, `kind="landing"`, `source="crossref"`, `serverDownloadable=False`.
- `_arxiv_candidates` calls `https://export.arxiv.org/api/query?id_list=...`; parse Atom XML; return a PDF candidate only when a link to `arxiv.org/pdf/` exists.
- `_pmc_candidates` calls Europe PMC `https://www.ebi.ac.uk/europepmc/webservices/rest/search?query=EXT_ID:...&format=json`; return landing/PDF candidates from `fullTextUrlList`.
- `resolve` merges candidates from all supplied identifiers, not just the first.
- Title-only resolution:
  - If exactly one candidate with `title_similarity >= 0.92` → use it.
  - If top two similarities differ by `< 0.03` or top `< 0.92` → `ambiguous` with up to 5 candidates.
- `matchedIdentifiers` includes every supplied identifier; `identifier` is DOI if present, else arXiv, else PMID/PMCID, else the title candidate's DOI.

- [ ] **Step 5: Mark downloadability**

After candidates are built, set `serverDownloadable = research_urls.is_safe_pdf_url(candidate["url"]) and candidate["kind"] == "pdf"`.
A publisher landing page never becomes downloadable even if it returns PDF later.

- [ ] **Step 6: Run tests**

Run:

```bash
cd backend && python -m pytest tests/test_research_fulltext.py tests/test_research_literature_urls.py -v
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add backend/research_fulltext.py backend/research_urls.py backend/research_lit.py backend/research_papers.py backend/tests/test_research_fulltext.py backend/tests/test_research_literature_urls.py
git commit -m "feat: 多标识符全文解析与安全下载域"
```

---

### Task 4: 全文 API 与兼容接口

**Files:**
- Modify: `backend/research_fulltext.py`
- Modify: `backend/research_lit.py`
- Modify: `backend/main.py`
- Test: `backend/tests/test_research_fulltext.py`

**Interfaces:**
- Consumes: Task 3 `resolve`.
- Produces:
  - `async def fulltext_lookup(request: Request) -> JSONResponse`
  - `GET /api/research/fulltext`
  - legacy `GET /api/research/literature/oa?doi=` returns the old fields plus `status`.

- [ ] **Step 1: Write failing endpoint test**

Add to `backend/tests/test_research_fulltext.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
cd backend && python -m pytest tests/test_research_fulltext.py::test_fulltext_endpoint_returns_status -v
```

Expected: FAIL because `fulltext_lookup` is missing.

- [ ] **Step 3: Implement endpoint**

In `research_fulltext.py`:

- `fulltext_lookup` authenticates with `require_auth`, reads query params, rejects empty identifiers with 400, applies a module-level `SlidingWindowLimiter` (or lazily imports `research_lit._limiter` inside the function to avoid a circular import), creates `httpx.AsyncClient` with 8s timeout and a MathGuide user agent, calls `resolve`, returns JSON with `Cache-Control: no-store`.
- Accept `doi`, `arxivId`, `pmid`, `pmcid`, `title`.
- Limit title to 300 chars, identifiers to 100 chars.

In `backend/main.py`, add:

```python
Route("/api/research/fulltext", research_fulltext.fulltext_lookup),
```

and import `research_fulltext`.

- [ ] **Step 4: Update legacy OA endpoint**

In `research_lit.oa_lookup`:

- Call `research_oa.resolve_doi` as before, then call `research_fulltext.resolve` for status/candidates only when needed; or map legacy result to the new status.
- Keep response fields `isOa`, `oaStatus`, `oaUrl`, `license`, `oaSource`, `version`, `resolver`, `error` for compatibility.
- Add `status`: `oa_pdf` if `isOa` and `serverDownloadable`; `oa_landing` if `isOa` and not downloadable; `no_legal_copy` if resolver reached sources but no OA; `unknown` if resolver error.
- Do not require `MG_UNPAYWALL_EMAIL`; existing `research_oa.resolve_doi` already falls back to OpenAlex.

- [ ] **Step 5: Run tests**

Run:

```bash
cd backend && python -m pytest tests/test_research_fulltext.py tests/test_research_sources.py tests/test_research_lit.py -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/research_fulltext.py backend/research_lit.py backend/main.py backend/tests/test_research_fulltext.py
git commit -m "feat: 合法全文解析接口"
```

---

### Task 5: 前端全文状态与访问操作

**Files:**
- Create: `frontend/src/utils/fulltextAccess.ts`
- Create: `frontend/scripts/fulltext-access-test.ts`
- Modify: `frontend/scripts/run-tests.mjs`
- Modify: `frontend/src/services/literatureService.ts`
- Modify: `frontend/src/views/ResearchSearchView.vue`
- Modify: `frontend/src/utils/i18n.ts`

**Interfaces:**
- Consumes: `GET /api/research/fulltext`.
- Produces:
  - `type FullTextStatus = 'oa_pdf' | 'oa_landing' | 'preprint' | 'institutional' | 'no_legal_copy' | 'unknown' | 'ambiguous'`
  - `interface FullTextCandidate { url: string; kind: 'pdf' | 'landing' | 'html'; source: string; hostType: string; version: string; license: string; serverDownloadable: boolean; isPreprint: boolean }`
  - `interface FullTextResult { status: FullTextStatus; best: FullTextCandidate | null; candidates: FullTextCandidate[]; matchedIdentifiers: {type:string;value:string}[]; reason: string }`
  - `function canOpenInReader(result: FullTextResult): boolean`
  - `function accessAction(result: FullTextResult): 'reader' | 'external' | 'upload' | 'retry' | 'choose'`
  - `function accessLabelKey(result: FullTextResult): string`

- [ ] **Step 1: Write failing helper test**

Create `frontend/scripts/fulltext-access-test.ts`:

```ts
import { accessAction, canOpenInReader } from '../src/utils/fulltextAccess'

let passed = 0
const failed: string[] = []
function check(name: string, ok: boolean) {
  if (ok) passed++
  else failed.push(name)
}

check('oa_pdf opens reader', canOpenInReader({
  status: 'oa_pdf', best: { url: 'https://arxiv.org/pdf/1', serverDownloadable: true },
  candidates: [], matchedIdentifiers: [], reason: '',
}))
check('oa_landing is external', accessAction({
  status: 'oa_landing', best: { url: 'https://example.org/a', serverDownloadable: false },
  candidates: [], matchedIdentifiers: [], reason: '',
}) === 'external')
check('no_legal_copy asks upload', accessAction({
  status: 'no_legal_copy', best: null, candidates: [], matchedIdentifiers: [], reason: '',
}) === 'upload')
check('unknown asks retry', accessAction({
  status: 'unknown', best: null, candidates: [], matchedIdentifiers: [], reason: '',
}) === 'retry')
check('ambiguous asks choose', accessAction({
  status: 'ambiguous', best: null, candidates: [], matchedIdentifiers: [], reason: '',
}) === 'choose')

if (failed.length) {
  console.error(`FAIL ${failed.length}: ${failed.join(', ')}`)
  process.exit(1)
}
console.log(`fulltext access: ${passed} passed`)
```

- [ ] **Step 2: Register test**

In `frontend/scripts/run-tests.mjs`, add a case:

```js
{
  name: '合法全文访问状态',
  bundle: 'npx esbuild scripts/fulltext-access-test.ts --bundle --format=cjs --platform=node --outfile=.fulltext-access-test.cjs',
  run: 'node .fulltext-access-test.cjs',
  artifact: '.fulltext-access-test.cjs',
},
```

- [ ] **Step 3: Run test to verify it fails**

Run:

```bash
cd frontend && npx esbuild scripts/fulltext-access-test.ts --bundle --format=cjs --platform=node --outfile=.fulltext-access-test.cjs && node .fulltext-access-test.cjs
```

Expected: FAIL because `fulltextAccess.ts` is missing.

- [ ] **Step 4: Implement helper**

`canOpenInReader` returns true only when `status === 'oa_pdf'` and `best.serverDownloadable === true`.
`accessAction` mapping:

```text
oa_pdf -> reader
oa_landing -> external
preprint -> external
institutional -> external
no_legal_copy -> upload
unknown -> retry
ambiguous -> choose
```

`accessLabelKey` returns an i18n key per status.

- [ ] **Step 5: Add service call and UI**

In `literatureService.ts`:

```ts
export async function resolveFullText(input: {
  doi?: string; arxivId?: string; pmid?: string; pmcid?: string; title?: string;
}): Promise<FullTextResult> {
  const params = new URLSearchParams()
  Object.entries(input).forEach(([key, value]) => {
    if (value) params.set(key, value)
  })
  return get<FullTextResult>(`/api/research/fulltext?${params.toString()}`, authHeaders())
}
```

In `ResearchSearchView.vue`:

- Replace local `readerUrl` host checks with `resolveFullText` + `canOpenInReader`.
- `findFreeCopy(item)` calls `resolveFullText({ doi: item.doi })`; if `oa_pdf`, call `openPdfInReader(item, result.best.url)`; if `oa_landing`/`preprint`/`institutional`, show preview with an explicit external link button; if `no_legal_copy`, show upload button; if `unknown`, show retry; if `ambiguous`, show candidate list.
- `openPdfInReader` requires `canOpenInReader`; otherwise show preview.
- Do not auto-open external URLs.
- Add i18n keys for each status and action: `search.fullTextOaPdf`, `search.fullTextOaPage`, `search.fullTextPreprint`, `search.fullTextInstitutional`, `search.fullTextNone`, `search.fullTextUnknown`, `search.fullTextAmbiguous`, `search.openExternal`, `search.uploadOwnCopy`, `search.retryResolve`, `search.choosePaper`.

- [ ] **Step 6: Run frontend tests and build**

Run:

```bash
cd frontend && npm test && npm run build
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/utils/fulltextAccess.ts frontend/scripts/fulltext-access-test.ts frontend/scripts/run-tests.mjs frontend/src/services/literatureService.ts frontend/src/views/ResearchSearchView.vue frontend/src/utils/i18n.ts
git commit -m "feat: 科研全文状态与合法访问操作"
```

---

### Task 6: 全文入库边界与来源能力信息

**Files:**
- Modify: `backend/research_papers.py`
- Modify: `backend/research_lit.py`
- Modify: `backend/tests/test_research_papers.py`
- Modify: `backend/tests/test_research_sources.py`

**Interfaces:**
- Consumes: `research_urls.is_safe_pdf_url`.
- Produces:
  - `create_temp` rejects non-`is_safe_pdf_url` targets with 400.
  - `sources_info` response adds `capabilities`: `{"metadata": True, "oa": bool, "download": bool, "linkOut": bool}`.

- [ ] **Step 1: Write failing tests**

Add to `backend/tests/test_research_papers.py`:

```python
def test_temp_paper_rejects_publisher_host(monkeypatch):
    import research_papers as rp
    from starlette.testclient import TestClient
    from starlette.applications import Starlette
    from starlette.routing import Route

    monkeypatch.setattr(rp, "require_auth", lambda request: {"uid": "u"})
    app = Starlette(routes=[Route("/api/research/papers/temp", rp.create_temp, methods=["POST"])])
    client = TestClient(app)
    res = client.post("/api/research/papers/temp", json={
        "url": "https://link.springer.com/content/pdf/1.pdf",
    })
    assert res.status_code == 400
```

Add to `backend/tests/test_research_sources.py`:

```python
def test_sources_info_exposes_capabilities(monkeypatch):
    monkeypatch.setattr(rl, "require_auth", lambda request: {"uid": "u"})
    from starlette.applications import Starlette
    from starlette.routing import Route
    from starlette.testclient import TestClient
    app = Starlette(routes=[Route("/api/research/sources", rl.sources_info)])
    body = TestClient(app).get("/api/research/sources").json()
    dblp = next(item for item in body["sources"] if item["id"] == "dblp")
    assert dblp["capabilities"]["metadata"] is True
    assert dblp["capabilities"]["download"] is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
cd backend && python -m pytest tests/test_research_papers.py::test_temp_paper_rejects_publisher_host tests/test_research_sources.py::test_sources_info_exposes_capabilities -v
```

Expected: FAIL.

- [ ] **Step 3: Implement boundary and capabilities**

- `research_papers.create_temp` should already use `lit._pdf_url_allowed`; after Task 3 that delegates to `research_urls.is_safe_pdf_url`, so `link.springer.com` is rejected. Add an explicit test only.
- In `research_lit.sources_info`, add `capabilities` per source:
  - `metadata: True` for all.
  - `oa: spec.fulltext in ("pdf", "oa")`.
  - `download: spec.id in trusted host sources` or `spec.fulltext == "pdf"`.
  - `linkOut: True`.

- [ ] **Step 4: Run tests**

```bash
cd backend && python -m pytest tests/test_research_papers.py tests/test_research_sources.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/research_papers.py backend/research_lit.py backend/tests/test_research_papers.py backend/tests/test_research_sources.py
git commit -m "feat: 全文入库边界与来源能力信息"
```

---

### Task 7: Analysis worker 骨架与依赖隔离

**Files:**
- Create: `backend/analysis_worker.py`
- Create: `backend/analysis_client.py`
- Create: `backend/requirements-analysis.txt`
- Modify: `.gitignore`
- Create: `backend/tests/test_analysis_worker.py`

**Interfaces:**
- Produces:
  - worker line protocol: request `{"id": "1", "op": "regression", "payload": {...}}`; response `{"id": "1", "ok": true, "result": {...}}` or `{"id": "1", "ok": false, "error": {"code": "...", "message": "..."}}`.
  - `async def run_analysis(payload: dict, timeout: float = 30.0) -> dict` in `analysis_client.py`.
  - `class AnalysisError(Exception)` with `code: str`.
  - `def analysis_python() -> str` resolves `MG_ANALYSIS_PYTHON`, else `backend/.venv-analysis/Scripts/python.exe` on Windows, else `backend/.venv-analysis/bin/python`.

- [ ] **Step 1: Write failing protocol test**

Create `backend/tests/test_analysis_worker.py`:

```python
import json
from analysis_worker import handle_request


def test_worker_rejects_unknown_op():
    response = handle_request({"id": "1", "op": "eval", "payload": {}})
    assert response["ok"] is False
    assert response["error"]["code"] == "unsupported_op"


def test_worker_rejects_missing_id():
    response = handle_request({"op": "ping", "payload": {}})
    assert response["ok"] is False
    assert response["error"]["code"] == "bad_request"


def test_worker_ping():
    response = handle_request({"id": "1", "op": "ping", "payload": {}})
    assert response == {"id": "1", "ok": True, "result": {"pong": True}}
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd backend && python -m pytest tests/test_analysis_worker.py -v
```

Expected: FAIL because module missing.

- [ ] **Step 3: Implement worker skeleton**

`analysis_worker.py`:

- Read JSON lines from stdin; write JSON lines to stdout.
- `handle_request(request: dict) -> dict` handles `ping` and `regression`; unknown ops return `unsupported_op`.
- Validate `id` is a non-empty string.
- Import regression implementation lazily inside `regression`.
- `main()` loops, catches exceptions, writes error JSON, flushes.
- No network, no shell.

`requirements-analysis.txt`:

```text
statsmodels==0.14.4
scipy==1.14.1
pandas==2.2.3
```

Pin exact versions available in the deployment environment. If these versions are unavailable, use the nearest compatible pinned versions and record them.

`.gitignore` add:

```text
backend/.venv-analysis/
```

- [ ] **Step 4: Implement client**

`analysis_client.py`:

- `analysis_python()` as above.
- `async def run_analysis(payload, timeout=30.0)` uses `asyncio.create_subprocess_exec` with `analysis_worker.py`, sends one JSON line, reads one line, kills on timeout.
- Map subprocess failure/timeout to `AnalysisError("unavailable", ...)`.
- Do not shell-expand; pass args as list.
- `AnalysisError` carries `code`, `message`.

- [ ] **Step 5: Run tests**

```bash
cd backend && python -m pytest tests/test_analysis_worker.py -v
```

Expected: PASS for protocol; `regression` tests come in Task 8.

- [ ] **Step 6: Commit**

```bash
git add backend/analysis_worker.py backend/analysis_client.py backend/requirements-analysis.txt backend/tests/test_analysis_worker.py .gitignore
git commit -m "feat: 独立 analysis worker 协议"
```

---

### Task 8: 回归计算

**Files:**
- Create: `backend/analysis_regression.py`
- Modify: `backend/analysis_worker.py`
- Create: `backend/tests/test_analysis_regression.py`

**Interfaces:**
- Consumes: `research_tables.compute` / `_numeric_columns` semantics.
- Produces:
  - `def fit_regression(columns: list[dict], rows: list[list[str]], formulas: dict[str, str], spec: dict) -> dict`
  - Error codes: `unsupported`, `insufficient_n`, `singular`, `empty`, `bad_column`.

- [ ] **Step 1: Write failing regression tests**

Create `backend/tests/test_analysis_regression.py`:

```python
import pytest

pytest.importorskip("statsmodels")

from analysis_regression import fit_regression

COLS = [
    {"key": "X", "type": "number"},
    {"key": "Y", "type": "number"},
]

COLS_COLLINEAR = [
    {"key": "X1", "type": "number"},
    {"key": "X2", "type": "number"},
    {"key": "Y", "type": "number"},
]


def test_ols_matches_known_values():
    rows = [["1", "2"], ["2", "4"], ["3", "5"], ["4", "4"], ["5", "5"]]
    result = fit_regression(COLS, rows, {}, {"x": ["X"], "y": "Y", "model": "ols"})
    coef = {item["term"]: item for item in result["coefficients"]}
    assert coef["const"]["estimate"] == pytest.approx(2.2, abs=1e-6)
    assert coef["X"]["estimate"] == pytest.approx(0.6, abs=1e-6)
    assert coef["X"]["se"] == pytest.approx(0.2828427, abs=1e-6)
    assert result["r2"] == pytest.approx(0.6, abs=1e-6)
    assert result["n"] == 5
    assert len(result["points"]) == 5
    assert result["points"][0]["x"] == pytest.approx(1.0)


def test_listwise_deletion_reports_missing_rows():
    rows = [["1", "2"], ["", "4"], ["3", "5"]]
    result = fit_regression(COLS, rows, {}, {"x": ["X"], "y": "Y", "model": "ols"})
    assert result["n"] == 2
    assert result["missing"] == 1
    assert result["points"][0]["row"] == 0
    assert result["points"][1]["row"] == 2


def test_polynomial_degree_two_is_exact():
    rows = [["-2", "4"], ["-1", "1"], ["0", "0"], ["1", "1"], ["2", "4"]]
    result = fit_regression(COLS, rows, {}, {
        "x": ["X"], "y": "Y", "model": "poly", "degree": 2})
    terms = {item["term"]: item["estimate"] for item in result["coefficients"]}
    assert terms["const"] == pytest.approx(0, abs=1e-8)
    assert terms["X"] == pytest.approx(0, abs=1e-8)
    assert terms["X^2"] == pytest.approx(1, abs=1e-8)
    assert result["r2"] == pytest.approx(1, abs=1e-8)


def test_collinear_columns_return_singular():
    rows = [["1", "2", "3"], ["2", "4", "5"], ["3", "6", "6"],
            ["4", "8", "7"], ["5", "10", "8"]]
    with pytest.raises(ValueError, match="singular"):
        fit_regression(COLS_COLLINEAR, rows, {}, {
            "x": ["X1", "X2"], "y": "Y", "model": "ols"})


def test_missing_intercept_is_unsupported():
    with pytest.raises(ValueError, match="unsupported"):
        fit_regression(COLS, [["1", "2"], ["2", "3"], ["3", "4"]], {}, {
            "x": ["X"], "y": "Y", "model": "ols", "options": {"intercept": False}})
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd backend && python -m pytest tests/test_analysis_regression.py -v
```

Expected: FAIL because `analysis_regression` is missing.

- [ ] **Step 3: Implement regression**

`analysis_regression.py`:

- Use `research_tables.compute` to expand computed columns.
- Build a list of rows with `y` and all `x`; drop any row with missing/non-finite values; record original row index.
- For `ols`: design matrix `[1, x1, ...]`; for `poly`: require exactly one x; design matrix `[1, x, x^2, ..., x^degree]`; degree must be 2–4.
- Reject `intercept=False` with `ValueError("unsupported")`.
- Reject unknown model with `ValueError("unsupported")`.
- Require `n >= p + 2`; else `ValueError("insufficient_n")`.
- Use `statsmodels.api.OLS` with `sm.add_constant`; check `np.linalg.matrix_rank` before fitting; raise `ValueError("singular")` if rank < p.
- Output:
  - `coefficients` terms: `const`, `X`, `X^2`, ...; estimate, se, t, p, ciLow, ciHigh.
  - `r2`, `adjR2`, `f`, `pF` from statsmodels (guard non-finite).
  - `points`: row, x (one-X models only), actual, fitted, residual.
  - `fitCurve`: for one x, 200 evenly spaced points across observed x range; evaluate coefficients; else `[]`.
  - `warnings`: `extrapolation` only if the UI requests prediction outside data; P1 default none.
- Round floats to 6 decimals for JSON stability; frontend displays 4 decimals.

- [ ] **Step 4: Wire worker op**

In `analysis_worker.handle_request`, `op == "regression"` calls `fit_regression` with `payload["columns"]`, `payload["rows"]`, `payload["formulas"]`, `payload["spec"]`.
Catch `ValueError` and return `{"ok": False, "error": {"code": str(exc), "message": ...}}`.

- [ ] **Step 5: Run tests**

Create the worker venv if it does not exist:

```bash
cd backend && python -m venv .venv-analysis
# Windows:
.\.venv-analysis\Scripts\pip install -r requirements-analysis.txt
# POSIX:
# .venv-analysis/bin/pip install -r requirements-analysis.txt
```

Then run:

```bash
cd backend && .venv-analysis/Scripts/python.exe -m pytest tests/test_analysis_regression.py -v
```

Expected: PASS. The tests call `pytest.importorskip("statsmodels")`, so the main backend suite skips them when statsmodels is absent; the worker venv must run them for real coverage. On POSIX use `.venv-analysis/bin/python`.

- [ ] **Step 6: Commit**

```bash
git add backend/analysis_regression.py backend/analysis_worker.py backend/tests/test_analysis_regression.py
git commit -m "feat: OLS 多元线性与多项式回归"
```

---

### Task 9: 回归 API

**Files:**
- Modify: `backend/research_tables.py`
- Modify: `backend/main.py`
- Modify: `backend/tests/test_research_tables.py`
- Modify: `frontend/src/services/researchTableService.ts`

**Interfaces:**
- Produces:
  - `async def regression_table(request: Request) -> JSONResponse`
  - `POST /api/research/tables/{table_id}/regression`
  - frontend `regressResearchTable(tableId, payload, spec): Promise<RegressionResult>`.

- [ ] **Step 1: Write failing API test**

Add to `backend/tests/test_research_tables.py`:

```python
def test_regression_endpoint_returns_worker_result(monkeypatch, tables):
    import research_tables as rt
    from starlette.applications import Starlette
    from starlette.routing import Route
    from starlette.testclient import TestClient

    monkeypatch.setattr(rt, "require_auth", lambda request: {"uid": "u-reg"})
    monkeypatch.setattr(rt, "_get_table", lambda uid, tid: {"id": tid, "title": "T"})

    async def fake_run(payload, timeout=30.0):
        assert payload["spec"]["model"] == "ols"
        return {"model": "ols", "n": 3, "points": [], "coefficients": []}

    monkeypatch.setattr(rt, "_run_analysis", fake_run)
    app = Starlette(routes=[Route(
        "/api/research/tables/{table_id}/regression",
        rt.regression_table, methods=["POST"])])
    body = {
        "columns": [
            {"key": "X", "label": "x", "type": "number"},
            {"key": "Y", "label": "y", "type": "number"},
        ],
        "rows": [["1", "2"], ["2", "3"], ["3", "4"]],
        "formulas": {},
        "regression": {"x": ["X"], "y": "Y", "model": "ols"},
    }
    res = TestClient(app).post(
        "/api/research/tables/t1/regression", json=body)
    assert res.status_code == 200
    assert res.json()["model"] == "ols"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd backend && python -m pytest tests/test_research_tables.py::test_regression_endpoint_returns_worker_result -v
```

Expected: FAIL because endpoint/helper missing.

- [ ] **Step 3: Implement endpoint**

In `research_tables.py`:

- Import `analysis_client`.
- Add `_run_analysis = analysis_client.run_analysis` module-level indirection for tests.
- `regression_table`:
  - auth, get table, 404 if missing.
  - Read full table payload plus `regression` spec; run `_validate_table_payload` so unsaved edits are analyzed.
  - Validate spec: `model` in `{"ols","poly"}`; `x` is 1–8 unique column keys; `y` is one existing column key; `degree` 2–4 only for `poly`; reject `intercept=false` and unknown fields.
  - Build worker payload with validated `columns`, `rows`, `formulas`, and `spec`.
  - `await _run_analysis(payload, timeout=30)`.
  - Map `AnalysisError` to 503 `{"code": "analysis_unavailable"}`; `ValueError` to 400 with code.
  - Return JSON, `Cache-Control: no-store`.

Add route in `main.py`:

```python
Route("/api/research/tables/{table_id}/regression",
      research_tables.regression_table, methods=["POST"]),
```

- [ ] **Step 4: Add frontend service types**

In `researchTableService.ts`:

```ts
export interface RegressionCoefficient {
  term: string; estimate: number; se: number; t: number; p: number
  ciLow: number; ciHigh: number
}
export interface RegressionPoint {
  row: number; x?: number; actual: number; fitted: number; residual: number
}
export interface RegressionResult {
  model: 'ols' | 'poly'; n: number; missing: number; equation: string
  coefficients: RegressionCoefficient[]
  r2: number; adjR2: number; f: number; pF: number
  points: RegressionPoint[]; fitCurve: { x: number; y: number }[]
  warnings: string[]
}
export async function regressResearchTable(
  tableId: string, payload: TablePayload,
  spec: { x: string[]; y: string; model: 'ols' | 'poly'; degree?: number },
): Promise<RegressionResult> {
  return post<RegressionResult>(
    `/api/research/tables/${encodeURIComponent(tableId)}/regression`,
    { ...payload, regression: spec },
    authHeaders(),
  )
}
```

- [ ] **Step 5: Run tests and build**

```bash
cd backend && python -m pytest tests/test_research_tables.py -v
cd frontend && npm run build
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/research_tables.py backend/main.py backend/tests/test_research_tables.py frontend/src/services/researchTableService.ts
git commit -m "feat: 数据表回归接口"
```

---

### Task 10: 回归 UI 与图表

**Files:**
- Create: `frontend/src/components/research/RegressionChart.vue`
- Create: `frontend/src/utils/regressionChart.ts`
- Create: `frontend/scripts/regression-chart-test.ts`
- Modify: `frontend/scripts/run-tests.mjs`
- Modify: `frontend/src/views/ResearchTablesView.vue`
- Modify: `frontend/src/utils/i18n.ts`

**Interfaces:**
- Consumes: Task 9 `RegressionResult`, `regressResearchTable`.
- Produces:
  - `RegressionChart.vue` props: `result: RegressionResult`, `xLabel: string`, `yLabel: string`, `mode: 'fit' | 'residual'`.
  - `regressionChart.ts` `fitSegments(result)` and `residualSegments(result)` return SVG coordinate-ready arrays.
  - Table analysis tab adds `'regression'`.

- [ ] **Step 1: Write failing chart helper test**

Create `frontend/scripts/regression-chart-test.ts`:

```ts
import { fitSegments, residualSegments } from '../src/utils/regressionChart'

let passed = 0
const failed: string[] = []
function check(name: string, ok: boolean) {
  if (ok) passed++
  else failed.push(name)
}

const result = {
  points: [
    { row: 0, x: 1, actual: 2, fitted: 2.2, residual: -0.2 },
    { row: 1, x: 2, actual: 4, fitted: 3.8, residual: 0.2 },
  ],
  fitCurve: [{ x: 1, y: 2.2 }, { x: 2, y: 3.8 }],
} as never

check('fit curve returns one segment', fitSegments(result).length === 1)
check('residuals keep two points', residualSegments(result).length === 2)

if (failed.length) {
  console.error(`FAIL ${failed.length}: ${failed.join(', ')}`)
  process.exit(1)
}
console.log(`regression chart: ${passed} passed`)
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd frontend && npx esbuild scripts/regression-chart-test.ts --bundle --format=cjs --platform=node --outfile=.regression-chart-test.cjs && node .regression-chart-test.cjs
```

Expected: FAIL.

- [ ] **Step 3: Implement chart helper and component**

`regressionChart.ts`:

- `fitSegments(result)` returns `Array<{ points: {x:number;y:number}[] }>` from `fitCurve`.
- `residualSegments(result)` returns points with `row`, `actual`, `fitted`.
- Keep pure; no DOM.

`RegressionChart.vue`:

- SVG 760×380; dark background `#0b1220` consistent with `TableChart`.
- `mode='fit'`: scatter of `actual` vs `x` when every point has an `x`, plus fit curve; otherwise plot `actual` vs `fitted` (multiple regression).
- `mode='residual'`: residual vs fitted, zero line.
- Expose `downloadSvg`/`downloadPng` like `TableChart`.

- [ ] **Step 4: Add regression tab**

In `ResearchTablesView.vue`:

- `analysisTab` union add `'regression'`.
- State: `regressionY`, `regressionX`, `regressionModel`, `regressionDegree`, `regression`, `regressionLoading`, `regressionError`.
- Controls: Y select, X multi-select, model select (`ols`/`poly`), degree select 2–4.
- Run button calls `regressResearchTable(table.id, payload(), spec)`.
- Results: equation, coefficient table, R²/adjR²/F/n/missing, warnings, `RegressionChart` fit + residual.
- On table change, clear `regression` and show “请重新运行”.
- Add i18n keys under `tables.regression*`.

- [ ] **Step 5: Register test and run**

Add test case to `run-tests.mjs`; run:

```bash
cd frontend && npm test && npm run build
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/research/RegressionChart.vue frontend/src/utils/regressionChart.ts frontend/scripts/regression-chart-test.ts frontend/scripts/run-tests.mjs frontend/src/views/ResearchTablesView.vue frontend/src/utils/i18n.ts
git commit -m "feat: 数据表回归分析与图表"
```

---

### Task 11: 聊天携带回归规格并重算

**Files:**
- Modify: `frontend/src/views/ResearchTablesView.vue`
- Modify: `frontend/src/components/chat/ChatWorkspace.vue`
- Modify: `backend/research_tables.py`
- Modify: `backend/chat.py`
- Test: `backend/tests/test_research_tables.py`
- Test: `backend/tests/test_chat_helpers.py`

**Interfaces:**
- Consumes: Task 9 `regressResearchTable`; Task 7 `analysis_client.run_analysis`.
- Produces:
  - `research_tables.context_text(table, regression_summary: str = "")`.
  - `chat._regression_summary(result: dict, stale: bool) -> str`.
  - `chat` body accepts `tableRegression: {x: string[]; y: string; model: string; degree?: number; tableUpdatedAt?: number}`.
  - Chat cache key includes hash of `tableRegression` + table `updatedAt`.

- [ ] **Step 1: Write failing context test**

Add to `backend/tests/test_research_tables.py`:

```python
def test_context_text_includes_regression_summary_only_when_passed():
    table = {
        "title": "T",
        "columns": [{"key": "X", "label": "x", "type": "number"},
                    {"key": "Y", "label": "y", "type": "number"}],
        "rows": [["1", "2"], ["2", "3"]],
        "formulas": {},
        "rowLabels": [],
    }
    plain = rt.context_text(table)
    with_reg = rt.context_text(table, "回归: Y=1+0.5X, R²=0.9")
    assert "回归" not in plain
    assert "回归: Y=1+0.5X" in with_reg


def test_regression_summary_flags_changed_table():
    import chat
    result = {
        "model": "ols", "n": 5, "equation": "Y=1+0.5X", "r2": 0.9,
        "coefficients": [{"term": "X", "estimate": 0.5, "p": 0.01}],
        "warnings": [],
    }
    summary = chat._regression_summary(result, stale=True)
    assert "table_changed" in summary
    assert "Y=1+0.5X" in summary
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd backend && python -m pytest tests/test_research_tables.py::test_context_text_includes_regression_summary_only_when_passed -v
```

Expected: FAIL because signature lacks the optional argument.

- [ ] **Step 3: Implement backend context and chat parse**

- `context_text(table, regression_summary="")` appends the summary as a separate line before the final data-source warning.
- Implement `chat._regression_summary(result: dict, stale: bool) -> str`: one line with model, n, equation, R², coefficient summaries, and warnings; prefix `table_changed: ` when stale.
- `chat.py` after `table_context` load: parse `body.get("tableRegression")`; validate keys; load table; call `analysis_client.run_analysis` with `{"columns": table["columns"], "rows": table["rows"], "formulas": table["formulas"], "spec": regression_spec}`; build a short summary with `_regression_summary`; if `tableUpdatedAt` differs from table's `updatedAt`, set `stale=True`, which prefixes `table_changed`; pass summary to `context_text`.
- Cache key: include `hashlib.sha256(json.dumps(regression_spec, sort_keys=True).encode()).hexdigest()[:16]` and table stamp.
- If worker fails, omit regression summary and add a short note; do not fail chat. Do not import statsmodels in the main process.

- [ ] **Step 4: Implement frontend handoff**

In `ResearchTablesView.onChat`:

- If `regression` exists, save `{x, y, model, degree, tableUpdatedAt: table.updatedAt}` to `sessionStorage` key `mg-regression-${table.id}`.
- Push `/research?tableId=...&regression=1`.

In `ChatWorkspace.loadTableContext`:

- Change `tableContext` type to `{ id: string; title: string; regression?: RegressionSpec }`.
- If `route.query.regression === '1'`, read sessionStorage; set `tableContext.value = { id, title, regression }`.
- When sending, add `tableRegression: tableContext.value?.regression` to the request metadata/body.

- [ ] **Step 5: Run tests and build**

```bash
cd backend && python -m pytest tests/test_research_tables.py tests/test_chat_helpers.py -v
cd frontend && npm test && npm run build
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/research_tables.py backend/chat.py backend/tests/test_research_tables.py backend/tests/test_chat_helpers.py frontend/src/views/ResearchTablesView.vue frontend/src/components/chat/ChatWorkspace.vue
git commit -m "feat: 聊天按回归规格重算"
```

---

### Task 12: P0/P1 验收

**Files:**
- No code changes.

**Interfaces:**
- Consumes: Tasks 1–11.
- Produces: verified baseline.

- [ ] **Step 1: Run backend full suite**

```bash
cd backend && python -m pytest -q
```

Expected: all pass.

- [ ] **Step 2: Run frontend tests**

```bash
cd frontend && npm test
```

Expected: all pass.

- [ ] **Step 3: Run build**

```bash
cd frontend && npm run build
```

Expected: pass.

- [ ] **Step 4: Manual smoke test**

Start backend and frontend; verify:

- Search `field=computer` returns CS results from Crossref/OpenAlex/Semantic Scholar/arXiv; DBLP may return a `bot challenge` warning because its public API now serves an Anubis challenge (do not bypass).
- A DOI with closed publisher + arXiv OA returns `oa_pdf` and opens in reader.
- A title with two close matches returns `ambiguous` and requires selection.
- A table with known data runs OLS and shows coefficients/R²/fit/residual.
- Editing the table after regression and sending chat produces `table_changed` and recomputed values.
- A private URL is rejected with 400.

- [ ] **Step 5: Commit only verification notes if requested**

Do not commit generated test artifacts or local data.

---

### Task 13: 科研图解规划器模式

**Files:**
- Modify: `backend/research_diagrams.py`
- Modify: `backend/tests/test_research_diagrams.py`

**Interfaces:**
- Produces:
  - `plan_diagram(..., mode: str = "learn", table_context: str = "")`
  - `plan_diagram_auto(..., mode: str = "learn", table_context: str = "")`
  - `_PLAN_SYSTEM_RESEARCH` prompt.
  - `build_data_plot(table_id: str, x: str, y: str, fit_result: dict) -> dict | None`.

- [ ] **Step 1: Write failing research prompt test**

Add to `backend/tests/test_research_diagrams.py`:

```python
def test_research_mode_requires_data_grounding(monkeypatch):
    seen = {}

    async def fake_stream(system, context, **kwargs):
        seen["system"] = system
        seen["context"] = context
        yield '{"type":"flow","nodes":[{"id":"a","label":"方法"}],"edges":[]}'

    monkeypatch.setattr(rd.llm, "is_configured", lambda role=None: True)
    monkeypatch.setattr(rd.llm, "stream_chat", fake_stream)
    result = asyncio.run(rd.plan_diagram(
        "画出实验流程", "先取样，再测量", [], "flow", mode="research"))
    assert result is not None
    assert "科研" in seen["system"] or "research" in seen["system"].lower()
    assert "数据点" in seen["system"] or "data points" in seen["system"].lower()
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd backend && python -m pytest tests/test_research_diagrams.py::test_research_mode_requires_data_grounding -v
```

Expected: FAIL because `mode` is not accepted.

- [ ] **Step 3: Implement research prompt and parameter**

- Add `mode` and `table_context` kwargs to `plan_diagram` and `plan_diagram_auto`; default `"learn"`.
- Select `_PLAN_SYSTEM_RESEARCH` when `mode == "research"`.
- Research prompt must state: only draw from excerpts/table/computed results; no fabricated points; data plots require deterministic builder; if insufficient, return no diagram.
- Keep all existing learn behavior unchanged when `mode == "learn"`.

- [ ] **Step 4: Run tests**

```bash
cd backend && python -m pytest tests/test_research_diagrams.py -v
```

Expected: PASS, including existing learn tests.

- [ ] **Step 5: Commit**

```bash
git add backend/research_diagrams.py backend/tests/test_research_diagrams.py
git commit -m "feat: 科研图解规划模式"
```

---

### Task 14: 确定性数据图构建

**Files:**
- Modify: `backend/research_diagrams.py`
- Modify: `backend/tests/test_research_diagrams.py`

**Interfaces:**
- Consumes: Task 8 `fit_regression` output; Task 9 regression API data.
- Produces:
  - `build_data_plot(table_id: str, x: str, y: str, fit_result: dict) -> dict | None`
  - Returns a `plot2d` DiagramSpec with point shapes, optional fit curve, axes, and at most 200 points.

- [ ] **Step 1: Write failing test**

```python
def test_data_plot_uses_fit_points_not_model_values():
    fit = {
        "points": [
            {"row": 0, "actual": 1.0, "fitted": 1.1, "residual": -0.1},
            {"row": 1, "actual": 2.0, "fitted": 2.1, "residual": -0.1},
        ],
        "fitCurve": [{"x": 0, "y": 1.0}, {"x": 3, "y": 4.0}],
    }
    spec = rd.build_data_plot("t1", "X", "Y", fit)
    assert spec["type"] == "plot2d"
    points = [s for s in spec["shapes"] if s["kind"] == "point"]
    assert len(points) == 2
    assert points[0]["x"] == 0
    assert points[0]["y"] == 1.0
    assert any(s["kind"] == "curve" for s in spec["shapes"])
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd backend && python -m pytest tests/test_research_diagrams.py::test_data_plot_uses_fit_points_not_model_values -v
```

Expected: FAIL.

- [ ] **Step 3: Implement builder**

- Points use `row` index as x (or x value if provided) and `actual` as y.
- Fit curve from `fitCurve`; no model-supplied points.
- Axes labeled with x/y column names.
- Return `None` if `points` is empty or > 200 after downsampling.
- Validate through existing `prepare_diagram` so schema limits apply.

- [ ] **Step 4: Run tests**

```bash
cd backend && python -m pytest tests/test_research_diagrams.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/research_diagrams.py backend/tests/test_research_diagrams.py
git commit -m "feat: 科研数据图确定性构建"
```

---

### Task 15: 手动科研图解与 tableId

**Files:**
- Modify: `backend/research_diagrams.py`
- Modify: `backend/tests/test_research_diagrams.py`
- Modify: `frontend/src/services/diagramService.ts`
- Modify: `frontend/src/components/chat/ChatWorkspace.vue`

**Interfaces:**
- Consumes: Task 14 `build_data_plot`; Task 9 regression result.
- Produces:
  - `plan_endpoint` accepts `tableId` and `mode`.
  - `planDiagram({ question, answer, paperId, tableId, mode })`.
  - `ChatWorkspace.requestDiagram` passes `tableContext.id` and `mode: 'research'` in research workspace.

- [ ] **Step 1: Write failing endpoint test**

```python
def test_plan_endpoint_accepts_table_id(monkeypatch):
    import research_diagrams as rd
    from starlette.applications import Starlette
    from starlette.routing import Route
    from starlette.testclient import TestClient

    seen = {}
    monkeypatch.setattr(rd, "require_auth", lambda request: {"uid": "u"})
    monkeypatch.setattr(rd, "_get_table", lambda uid, tid: {
        "columns": [{"key": "X", "label": "x"}],
        "rows": [["1"]], "formulas": {},
    }, raising=False)

    async def fake_plan(question, answer, excerpts, kind, **kwargs):
        seen["table_context"] = kwargs.get("table_context")
        seen["mode"] = kwargs.get("mode")
        return {"type": "flow", "nodes": [{"id": "a", "label": "A"}], "edges": []}

    monkeypatch.setattr(rd, "plan_diagram", fake_plan)
    app = Starlette(routes=[Route(
        "/api/research/diagrams/plan", rd.plan_endpoint, methods=["POST"])])
    res = TestClient(app).post("/api/research/diagrams/plan", json={
        "question": "画出实验流程", "answer": "先取样，再测量",
        "tableId": "t1", "mode": "research",
    })
    assert res.status_code == 200
    assert "X" in seen["table_context"]
    assert seen["mode"] == "research"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd backend && python -m pytest tests/test_research_diagrams.py::test_plan_endpoint_accepts_table_id -v
```

Expected: FAIL.

- [ ] **Step 3: Implement backend and frontend**

- `plan_endpoint` reads `tableId`; if present, loads the table via a module-level `_get_table` indirection (`research_tables._get_table`) so tests can monkeypatch it; builds `table_context` text; passes `mode="research"` when requested.
- If the request includes a regression spec/result, call `build_data_plot`; otherwise use `plan_diagram` with table context.
- `diagramService.ts` adds `tableId` and `mode` to `PlanDiagramInput` and request body.
- `ChatWorkspace.requestDiagram` passes `tableContext.value?.id` and `mode: isResearch.value ? 'research' : 'learn'`.

- [ ] **Step 4: Run tests and build**

```bash
cd backend && python -m pytest tests/test_research_diagrams.py -v
cd frontend && npm test && npm run build
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/research_diagrams.py backend/tests/test_research_diagrams.py frontend/src/services/diagramService.ts frontend/src/components/chat/ChatWorkspace.vue
git commit -m "feat: 科研手动图解绑定数据表"
```

---

### Task 16: 研究综述图解显式开关

**Files:**
- Modify: `backend/chat.py`
- Modify: `backend/research_diagrams.py`
- Modify: `frontend/src/components/chat/ChatWorkspace.vue`
- Test: `backend/tests/test_research_diagrams.py`

**Interfaces:**
- Consumes: Task 13 research mode, Task 15 manual path.
- Produces:
  - `def _diagram_requested(body: dict) -> bool` in `chat.py`; true only when `body.get("diagrams") is True`.
  - `_gen_research(..., diagrams: bool = False)`.
  - Research answer can emit `[[MG_DIAGRAM:...]]` only when `diagrams=True`.
  - Default `diagrams=False`.

- [ ] **Step 1: Write failing test**

```python
def test_research_diagram_switch_defaults_off():
    import chat
    assert chat._diagram_requested({}) is False
    assert chat._diagram_requested({"diagrams": False}) is False
    assert chat._diagram_requested({"diagrams": True}) is True
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd backend && python -m pytest tests/test_research_diagrams.py::test_research_diagram_switch_defaults_off -v
```

Expected: FAIL because `_diagram_requested` is missing.

- [ ] **Step 3: Implement explicit switch**

- `_gen_research` default `diagrams=False`; when true, use `MarkerStream` and research planner, max 2 diagrams, citations preserved.
- Frontend adds a research-only toggle “生成图解” next to the send button, default off; sends `diagrams: true` in body.
- If the user asks “画图/图解” explicitly, set `diagrams=True` for that message.

- [ ] **Step 4: Run tests and build**

```bash
cd backend && python -m pytest tests/test_research_diagrams.py -v
cd frontend && npm test && npm run build
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/chat.py backend/research_diagrams.py frontend/src/components/chat/ChatWorkspace.vue backend/tests/test_research_diagrams.py
git commit -m "feat: 研究综述图解显式开关"
```

---

### Task 17: 学科包能力探测与 P2/P3 验收

**Files:**
- Create: `backend/analysis_capabilities.py`
- Create: `backend/tests/test_analysis_capabilities.py`
- Modify: `backend/analysis_worker.py`
- Modify: `README.md` or `backend/README.md`

**Interfaces:**
- Produces:
  - `def available_packs() -> dict[str, bool]` for `rdkit`, `biopython`, `astropy`, `networkx`.
  - `op="capabilities"` in the worker returns the same map.
  - API response includes `capabilities` for the current environment; missing packs are false.

- [ ] **Step 1: Write failing test**

```python
def test_capabilities_default_false_without_packages(monkeypatch):
    import analysis_capabilities as ac
    monkeypatch.setattr(ac.importlib.util, "find_spec", lambda name: None)
    assert ac.available_packs() == {
        "rdkit": False, "biopython": False, "astropy": False, "networkx": False,
    }
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd backend && python -m pytest tests/test_analysis_capabilities.py -v
```

Expected: FAIL.

- [ ] **Step 3: Implement capability detection and docs**

- Use `importlib.util.find_spec` for each package.
- No package installs; document optional install commands in `backend/README.md`.
- Worker returns capabilities; main service can expose them via an endpoint or include them in regression errors.

- [ ] **Step 4: P2/P3 acceptance**

```bash
cd backend && python -m pytest -q
cd frontend && npm test && npm run build
```

Manual:

- Research manual diagram with table data shows points matching table.
- Research review diagram toggle off by default; on produces at most 2 diagrams.
- Missing domain pack shows disabled capability, not crash.

- [ ] **Step 5: Commit**

```bash
git add backend/analysis_capabilities.py backend/tests/test_analysis_capabilities.py backend/analysis_worker.py backend/README.md
git commit -m "feat: 学科包能力探测与科研图解验收"
```

---

## Self-Review

**Spec coverage:**

- Legal full text: Tasks 2–6.
- Trusted hosts / no Sci-Hub / no paywall bypass: Tasks 3, 6, Global Constraints.
- Five disciplines and DBLP: Task 1.
- Independent analysis worker: Tasks 7–9.
- Regression UI and charts: Task 10.
- Chat regression spec recompute: Task 11.
- Research diagrams: Tasks 13–16.
- Domain packs: Task 17.
- Tests and acceptance: Tasks 12, 17.

**Type consistency:**

- `FullTextStatus` / `FullTextResult` defined in Task 5, used by UI.
- `RegressionResult` defined in Task 9, used by Task 10/11.
- `fit_regression` signature fixed in Task 8; Task 9 worker payload uses `columns/rows/formulas/spec`.
- `build_data_plot` fixed in Task 14; Task 15 calls it.

**Review Focus tests:**

- DOI closed + arXiv OA: Task 3 test.
- Ambiguous title: Task 3 test.
- Private/localhost URL: Task 3 test.
- Missing/singular regression: Task 8 tests.
- Table edited after regression: Task 11 behavior and test.
- Learning area isolation: existing regression tests plus Task 12/17 full suites.

**Open execution notes:**

- The plan uses commits; the user must explicitly authorize commits before execution.
- The analysis worker venv must be created before Task 8 tests; it is not committed.
- The current worktree has pre-existing uncommitted diagram-focus changes; separate them before Task 1.
