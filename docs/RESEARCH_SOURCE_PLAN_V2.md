# MathGuide 科研文献源制作方案 V2

日期：2026-10-30
范围：只做免费/开放文献源，不做校园图书馆与 CARSI
状态：实施版方案，替代 `docs/RESEARCH_SOURCE_PLAN.md` 中的机构访问部分
基线：v1.12.0（`3456b4d`）

## 0. 本版结论

1. 校园图书馆、CARSI、订阅 PDF 暂不做。
2. 先接当前网络实测可用的免费源：Crossref、INSPIRE、PubMed、Europe PMC、zbMATH、DOAJ。
3. bioRxiv/medRxiv 的搜索走 Europe PMC 预印本检索，直连 API 只做 DOI/日期补充。
4. OpenAlex 免费但按网络共享每日额度；免费 key 可提高额度。Semantic Scholar 可选 key，Unpaywall 需要 email。
5. ChemRxiv 公共 API 被 Cloudflare 403；用 Crossref 取元数据，PDF 只做外链。
6. ChinaXiv、CAS IR Grid 当前网络受限，暂不进入默认检索；换国内网络验证后再接。
7. 权威性是学科内的权威：综合顶刊、领域顶刊、领域强刊、预印本、用户上传分开标记。

## 1. 实测来源矩阵

实测时间：2026-10-30，当前开发网络。

| 来源 | 实测 | 是否需要 key | 本版决策 |
| --- | --- | --- | --- |
| Crossref | 已接入，200 | 否 | 保留，补 ISSN/出版社/文章类型 |
| INSPIRE-HEP | 200 | 否 | P1 接入 |
| PubMed E-utilities | 200 | 否（可选 key） | P1 接入 |
| Europe PMC | 200 | 否 | 保留，补预印本与 OA 地址 |
| zbMATH Open | 200 | 否 | P1 接入 |
| DOAJ | 200 | 否 | P2 接入，作为 OA 期刊目录 |
| bioRxiv API | 200 | 否 | P2 接入，按 DOI/日期补充；搜索走 Europe PMC |
| OpenAlex | 单条 200；搜索 429 | 免费；keyless 共享每日额度 | 已启用 keyless，建议配免费 key |
| Semantic Scholar | 单条 200；搜索 429 | 需要 key | P2 配 key 后启用 |
| Unpaywall | 422（缺 email） | 需要 email | P1 配 `MG_UNPAYWALL_EMAIL` 后启用 |
| NASA ADS | 未测 | 需要 token | P3 有 token 再接 |
| ChinaXiv OAI | 权限拒绝 | 否 | 暂缓，国内网络复测 |
| CAS IR 单所 OAI | 200 | 否 | P3 按院所列表接入 |
| CAS IR Grid 聚合站 | 连接失败 | 否 | 暂缓 |
| ChemRxiv API | Cloudflare 403 | 否 | 用 Crossref 元数据 + 外链 PDF |
| CORE | 未测 | 需要 key | P3 可选 |

## 2. 目标与非目标

### 目标

- 搜索结果带稳定标识、venue、ISSN、文章类型、同行评审、OA 状态与许可。
- 默认只返回同行评审来源；预印本需要显式开启。
- 自动解析合法 OA PDF；没有就跳出版社页面，不误标“免费”。
- 按学科权重排序，综合顶刊与领域顶刊都识别。
- 保持现有检索、阅读、批注、数据表链路不变。

### 非目标

- 校园图书馆、CARSI、订阅 PDF、机构身份验证。
- Sci-Hub、付费墙绕过、批量下载、公共全文库。
- Web of Science、Scopus、MathSciNet、SciFinder、Reaxys、JCR、中科院分区。
- 全学科一次性铺开。

## 3. 总体架构

```text
查询
  → 学科判定（math/physics/chemistry/biology/general）
  → 来源路由（默认权威源；预印本开关）
  → provider 并行检索（超时/失败隔离）
  → 统一归一化（标识、venue、ISSN、类型、许可）
  → 去重与版本关联
  → OA 解析（Unpaywall/OpenAlex/Europe PMC/S2）
  → 撤稿/更正检查
  → 学科 venue 排序
  → 前端徽标/筛选/阅读/导入
```

### 新增模块

- `backend/research_sources.py`：来源注册表、启停、key、限速。
- `backend/research_venues.py`：venue/ISSN 匹配与学科层级。
- `backend/research_oa.py`：OA 解析与 PDF 合法性校验。
- `backend/research_fields.py`：学科判定与来源路由。
- `backend/data/venues.json`：可版本化 venue registry。
- `backend/tools/probe_literature_sources.py`：来源连通性与字段探针。

### 改造模块

- `backend/research_lit.py`：provider 适配、统一字段、分学科、OA 状态。
- `backend/research_corpus.py`：文档元数据补 ISSN/文章类型/许可/来源。
- `backend/research_papers.py`：临时论文与导入来源标记。
- `backend/main.py`：新增 OA/venue 路由。
- `frontend/src/services/literatureService.ts`：字段与接口。
- `frontend/src/views/ResearchSearchView.vue`：徽标、筛选、按钮。
- `frontend/src/components/research/DocumentViewer.vue`：许可与来源提示。
- `frontend/src/utils/i18n.ts`：文案。

## 4. 统一数据模型

### 4.1 检索结果

```text
title, authors, year, venue, issn, publisher
doi, pmid, pmcid, arxivId, adsBibcode, inspireId, zbmathId
url, pdfUrl
abstract, citations
fields[]
source
sourceTier        # authority | discovery | preprint | repository
venueTier         # T0 | T1 | T2 | T3 | P | U
peerReviewed
articleType       # research | review | editorial | letter | erratum | retraction
oaStatus          # gold | diamond | hybrid | green | bronze | closed | unknown
oaSource          # publisher | pmc | repository | preprint
license
retractionStatus  # none | retracted | corrected | expression_of_concern
versionOf
retrievedAt
```

### 4.2 本地文档

`docs` 表新增列：

```text
issn, publisher, article_type, peer_reviewed
oa_status, license, access_source   # oa | user_upload
landing_url, source_url
retraction_status, version_of
```

迁移：

- `ALTER TABLE` 补列，默认空值。
- 旧文档 `access_source=user_upload`，`oa_status=unknown`。
- 自动保存不覆盖已有来源字段。

### 4.3 venue registry

`backend/data/venues.json`：

```json
{
  "version": "2026-10-30.1",
  "venues": [
    {
      "issn": ["0028-0836", "1476-4687"],
      "name": "Nature",
      "aliases": ["Nature"],
      "publisher": "Springer Nature",
      "scope": ["general"],
      "tiers": {"general": "T0"},
      "peer_reviewed": true,
      "source": "curated",
      "note": "综合顶刊"
    }
  ]
}
```

规则：

- ISSN 去连字符、X 大写；无 ISSN 用规范化名称 + 系列。
- 综合顶刊跨学科高先验；领域顶刊只在对应学科加权。
- Nature 子刊单独定级，不自动继承 Nature。
- 每条记录保留依据与版本；授权数据不入公开仓库。

## 5. Provider 适配规格

所有 provider 统一签名：

```python
async def search(client, query, limit, filters) -> list[dict]
```

返回统一 `_result` 结构；异常由路由层降级为 warning。

### 5.1 INSPIRE-HEP（物理）

- URL：`https://inspirehep.net/api/literature`
- 参数：`q`, `size`, `sort=mostrecent`, `fields=...`
- 字段：`metadata.titles[0].title`、`authors[].full_name`、
  `publication_info.year/journal_title`、`dois[].value`、
  `arxiv_eprints[].value`、`citation_count`、`abstracts[0].value`、
  `document_type`、`control_number`。
- `articleType`：article/thesis/review 等映射。
- `pdfUrl`：优先 arXiv PDF；`documents[]` 中的合法 URL 作为候选。
- 只用于物理/高能物理；不参与生物/化学默认排序。

### 5.2 PubMed E-utilities（生物医学）

- 搜索：`esearch.fcgi?db=pubmed&term=...&retmode=json&retmax=...`
- 详情：`efetch.fcgi?db=pubmed&id=...&retmode=xml`
- 字段：PMID、DOI、PMCID、title、authors、journal、year、abstract、
  publication type、MeSH。
- 撤稿：`Retracted Publication` / `Retraction of Publication`。
- 速率：无 key 3 req/s；有 `MG_NCBI_API_KEY` 10 req/s。
- 缓存：按 PMID 缓存 24h。

### 5.3 zbMATH Open（数学）

- URL：`https://api.zbmath.org/v1/document/_search`
- 参数：`search_string`, `results_per_page`, 分页。
- 字段：`title.title`、`contributors.authors[].name`、`year`、`source`、
  `identifier`、`zbmath_url`、`links`、`msc`、`document_type`。
- `fields`：MSC 一级分类映射到数学子领域。
- 无 key；低频调用，结果缓存。

### 5.4 Europe PMC（生物 + 预印本 + OA）

- 保留现有搜索；增加：
  - `SRC:PPR` 预印本检索开关；
  - `fullTextUrlList` → `oaStatus/oaUrl/license`；
  - `pubType` → `articleType/retractionStatus`。
- 生物默认源；也用于 bioRxiv/medRxiv 关键词搜索。

### 5.5 bioRxiv / medRxiv

- URL：`https://api.biorxiv.org/details/{server}/{dateFrom}/{dateTo}/{cursor}`
- 限制：按日期区间返回，不是关键词搜索。
- 用途：
  - 已知 DOI 的单篇补充；
  - Europe PMC 命中预印本后补 PDF/许可/版本；
  - 不作为默认关键词源。
- 字段：title、authors、doi、date、version、license、category、abstract、published。

### 5.6 Crossref（全学科）

- 保留；补：
  - `ISSN`、`publisher`、`type` → `articleType`；
  - `update-to`/`relation` → 撤稿/更正；
  - `license`。
- 仍是 DOI 权威元数据与 landingUrl 主源。

### 5.7 DOAJ（OA 期刊）

- URL：`https://doaj.org/api/search/articles/{query}`
- 用途：OA 期刊状态、许可、期刊资质；不替代 Crossref。
- 只作补充源，避免结果膨胀。

### 5.8 Unpaywall（OA 解析）

- URL：`https://api.unpaywall.org/v2/{doi}?email=...`
- 字段：`is_oa`、`oa_status`、`best_oa_location.url_for_pdf`、
  `best_oa_location.license`、`best_oa_location.host_type`。
- 必须配置 `MG_UNPAYWALL_EMAIL`；未配置时跳过并 warning。
- 只对 DOI 查询；批量时按 DOI 去重、缓存 24 小时。

### 5.9 OpenAlex（OA + 引用）

- 单条：`https://api.openalex.org/works/doi:{doi}`
- 搜索：`https://api.openalex.org/works?search=...`
- 当前搜索 429；配置 `MG_OPENALEX_API_KEY` 后再启用搜索。
- 字段：`best_oa_location`、`oa_status`、`is_retracted`、`primary_location.source.issn_l`。
- 单条查询可作为 OA/撤稿补充。

### 5.10 Semantic Scholar（OA 补充）

- URL：`https://api.semanticscholar.org/graph/v1/paper/search`
- 字段：`openAccessPdf`、`externalIds`、`citationCount`。
- 当前搜索 429；配 `MG_S2_API_KEY` 后启用。
- 只作发现/OA 补充，不作权威依据。

### 5.11 ChemRxiv（化学预印本）

- 公共 API 当前 Cloudflare 403。
- 元数据走 Crossref（ChemRxiv DOI，前缀 `10.26434`）。
- PDF 只做外链：`https://chemrxiv.org/doi/pdf/{doi}`；不可下载时跳转。
- 不在默认检索里高频调用。

### 5.12 ChinaXiv / CAS IR（暂缓）

- ChinaXiv OAI 当前返回权限拒绝；国内网络复测后再接。
- CAS IR 用各所 OAI：`https://{institute}/casirgrid-oai/request`，
  `metadataPrefix=oai_dc`；`cas_dc` 需授权。
- 维护院所列表与限速；只取元数据与开放全文链接。

## 6. 学科判定与排序

### 6.1 判定

- 规则优先：数学符号/术语、物理分类、化学术语、生物医学术语。
- 轻量模型分类作补充；结果可多学科。
- 用户可手动切换学科。

### 6.2 排序

```text
score = relevance
      × venue_weight(field, venue.tiers)
      × article_type_weight
      × preprint_penalty
      × (retracted ? 0 : 1)
```

- 被引数只作 tie-breaker。
- 默认 `peerReviewed=true`；预印本开关打开才参与。
- 撤稿/表达关注降权或阻断。
- 预印本与正式版按 DOI/标题+作者+年份关联，合并展示。

## 7. 前端改造

### 7.1 结果卡片

徽标：

- `Nature · 综合顶刊`
- `PRL · 物理顶刊`
- `arXiv 预印本`
- `免费 PDF`
- `出版社页面`
- `已撤稿`

按钮：

- `查看原文`：landingUrl。
- `免费 PDF`：应用内阅读器。
- `导入`：已有；OA 临时论文。
- `对比` / `相关`：保留。

筛选：

- 仅同行评审 / 含预印本
- 仅免费全文
- 学科
- 来源层级

### 7.2 阅读器

- 顶部显示 venue、许可、OA 状态。
- 撤稿显示阻断提示。
- 无 OA PDF 时只显示出版社跳转，不显示“查看 PDF”。

### 7.3 结果为空

- 区分“没有命中”与“来源不可用”。
- 来源 429/超时显示可重试提示，不伪造结果。

## 8. 后端接口

### 8.1 改造

`GET /api/research/literature`

新增参数：

```text
field=math|physics|chemistry|biology|general
peerReviewed=true|false
includePreprints=true|false
oaOnly=true|false
tier=T0,T1,T2,T3
```

返回新增字段见 4.1。

### 8.2 新增

- `GET /api/research/literature/oa?doi=`：OA 解析。
- `GET /api/research/venues?issn=|name=`：venue 查询。
- `GET /api/research/sources`：来源状态与 warnings（可选，调试用）。

### 8.3 配置

```text
MG_LITERATURE_MAILTO
MG_NCBI_API_KEY
MG_UNPAYWALL_EMAIL
MG_OPENALEX_API_KEY
MG_S2_API_KEY
MG_ADS_API_KEY
MG_CORE_API_KEY
```

## 9. 分阶段实施

### P0：字段与 registry（1–2 周）

- `research_sources.py`、`research_venues.py`、`venues.json` 初版。
- 结果补 ISSN/出版社/文章类型/同行评审/OA/许可字段。
- `docs` 表迁移。
- 前端类型与徽标骨架。
- 单元测试：ISSN 归一化、venue 匹配、字段清洗。

完成标准：

- 现有 350 条后端测试全过。
- 所有结果都有 landingUrl。
- venue registry 至少覆盖四学科各 20 本核心期刊。
- 无来源注册表之外的网站进入结果。

### P1：物理、生物、数学免费源（2–3 周）

- INSPIRE、PubMed、zbMATH 适配。
- Europe PMC 预印本开关与 OA 地址。
- Unpaywall（配置 email 后）。
- 学科判定与来源路由。
- 前端徽标、筛选、免费 PDF 按钮。

完成标准：

- 物理查询命中 INSPIRE；生物命中 PubMed/Europe PMC；数学命中 zbMATH。
- 每条结果有稳定标识；预印本不冒充满同行评审。
- OA 状态不误报；没有合法 PDF 时只给出版社页面。
- 每学科 30 条冒烟查询通过。

### P2：化学、OA 增强与排序（2–3 周）

- OpenAlex 已无 key 启用；建议配置免费 key 提高每日额度；S2 配 key 后启用。
- ChemRxiv 走 Crossref 元数据 + 外链。
- DOAJ 补 OA 期刊状态。
- venue 学科排序、综合顶刊跨学科加权。
- 撤稿/更正检查。
- 对比表与报告补 venue/许可字段。

完成标准：

- 化学查询不被预印本淹没；出版社白名单生效。
- 撤稿样本 100% 标记。
- 预印本/正式版关联准确率 ≥90%（样本集）。
- Top-10 领域顶刊占比达到目标（建议 ≥60%）。

### P3：可选与暂缓（条件触发）

- ADS（有 token）。
- ChinaXiv/CAS IR（国内网络复测通过）。
- CORE（有 key）。
- 授权索引适配位（WoS/Scopus/MathSciNet/SciFinder/Reaxys）只留接口，不实现抓取。
- 校园图书馆/CARSI：不在本版范围。

## 10. 测试与验收

### 10.1 自动化

- Provider 单元测试：用固定 JSON 样本，不调外网。
- 归一化测试：ISSN、venue、文章类型、许可、撤稿。
- 去重/版本关联测试。
- OA 校验测试：HTTPS、重定向、大小、`%PDF-`、许可。
- 回归：现有 pytest 全量、前端 npm test、vue-tsc、build。

### 10.2 冒烟与金标准

- 每学科 30–50 条查询。
- 指标：
  - `authority_precision@10`：Top-10 中 T0/T1 占比。
  - `oa_resolution_accuracy`：OA 状态与真实许可一致率。
  - `retraction_recall`：撤稿识别率。
  - `version_link_rate`：预印本/正式版关联率。
  - `false_free_rate`：误标免费全文比例，目标 0。
  - `p95_latency`、`error_rate`。

### 10.3 手工验证

- 物理：INSPIRE 检索 → arXiv PDF → 阅读器。
- 生物：PubMed 检索 → PMC OA → 阅读器。
- 数学：zbMATH 检索 → 出版社/arXiv。
- 化学：Crossref/ChemRxiv 元数据 → 出版社外链。
- 无 OA：只显示出版社页面，不显示“查看 PDF”。

## 11. 安全与合规

- 不绕过付费墙；不接 Sci-Hub。
- 不保存任何学校账号/Cookie。
- 不下载许可不明 PDF；不转存公共库。
- 遵守来源 API 条款与频率限制。
- 用户上传仍按 uid 隔离。
- 授权数据只在授权环境使用，不入公开仓库。

## 12. 运维

- 来源 key 只放 `backend/.env.local`。
- 每来源限速、缓存、熔断。
- OA 状态缓存 24 小时；venue registry 版本化。
- 日志不记录全文与密钥。
- 监控来源成功率、429 率、OA 解析率、阅读器打开率。

## 13. 风险与应对

| 风险 | 影响 | 应对 |
| --- | --- | --- |
| OpenAlex/S2 429 | 搜索不可用 | 配免费 key、缓存、单条查询 |
| Unpaywall 缺 email | OA 解析不可用 | 配 `MG_UNPAYWALL_EMAIL`，缺省跳过 |
| PubMed XML 复杂 | 解析错误 | 固定样本测试、宽松字段降级 |
| zbMATH 字段变化 | 结果缺失 | 适配层容错、warning |
| bioRxiv 无关键词搜索 | 覆盖不足 | 走 Europe PMC 预印本 |
| ChemRxiv 403 | 无法接 API | Crossref 元数据 + 外链 |
| ChinaXiv 权限拒绝 | 中文预印本缺失 | 国内网络复测，不默认启用 |
| venue 分级主观 | 排序争议 | 公开依据、版本化、可申诉 |
| 出版社页面反爬 | 阅读中断 | 只跳转，不代理 |

## 14. 文件级任务清单

新增：

```text
backend/research_sources.py
backend/research_venues.py
backend/research_oa.py
backend/research_fields.py
backend/data/venues.json
backend/tools/probe_literature_sources.py
backend/tests/test_research_sources.py
backend/tests/test_research_venues.py
backend/tests/test_research_oa.py
frontend/src/components/research/SourceBadge.vue
```

修改：

```text
backend/research_lit.py
backend/research_corpus.py
backend/research_papers.py
backend/main.py
backend/README.md
frontend/src/services/literatureService.ts
frontend/src/views/ResearchSearchView.vue
frontend/src/components/research/DocumentViewer.vue
frontend/src/utils/i18n.ts
```

## 15. 最小可行版本（MVP）

只做 P0 + P1 的一半：

1. 结果补 `venue/issn/peerReviewed/articleType/oaStatus/landingUrl`。
2. 接 INSPIRE + PubMed + zbMATH。
3. Unpaywall 配 email 后解析 OA。
4. 前端显示 `免费 PDF` / `出版社页面` / `预印本` 徽标。

这一步不依赖任何付费授权，不改动现有阅读器与数据表链路，风险最低。

## 16. 实现进度（2026-10-30）

已完成：

- `research_sources.py`、`research_venues.py`、`research_oa.py`。
- `registry/venues.json` 109 条场所记录，覆盖四学科与综合顶刊。
- DOAJ 适配与检索缓存（5 分钟）、OA 解析缓存（24 小时）。
- 临时论文来源元数据写入 `docs` 表。
- INSPIRE、PubMed E-utilities、zbMATH、DOAJ 适配。
- Crossref/arXiv/Europe PMC/OpenAlex/Semantic Scholar 字段补齐。
- 学科路由、预印本开关、仅同行评审、仅免费全文。
- OA 查询接口与前端「查找免费全文」。
- `docs` 表来源元数据列；临时论文入库时可携带检索元数据。
- OpenAlex 免费 key 配置；`oa_status` 误读与无效 `select` 字段修复。
- Semantic Scholar 改为无 key 也尝试，key 只提升额度。
- Unpaywall email 配置。
- `GET /api/research/venues`、`GET /api/research/sources`、`GET /api/research/docs/{id}`。
- 阅读器顶部显示场所、同行评审、OA、许可、撤稿与出版社页面。
- 前端默认仅同行评审、预印本默认关闭。
- bioRxiv/medRxiv 按 DOI 补充预印本元数据（关键词搜索仍走 Europe PMC）。
- `tools/lit_smoke.py`：分学科冒烟与金标准指标。
- 后端 378 条测试、前端自测、`vue-tsc`、`npm run build` 通过。

冒烟基线（2026-10-30，每学科 3 查询 × Top-10）：

| 学科 | 结果 | authority_precision | peer | oa | source_errors |
| --- | --- | --- | --- | --- | --- |
| general | 30 | 10% | 100% | 43% | 3 |
| math | 30 | 10% | 100% | 10% | 3 |
| physics | 30 | 30% | 100% | 27% | 3 |
| chemistry | 30 | 57% | 100% | 27% | 3 |
| biology | 30 | 80% | 100% | 57% | 3 |

未完成：

- Semantic Scholar 免费 key 的生产配置（当前无 key 走公共池）。
- ChinaXiv、CAS IR Grid、ChemRxiv API 的网络验证。
- ADS、CORE。
- 授权索引（WoS/Scopus/MathSciNet/SciFinder/Reaxys）。
- 校园图书馆与 CARSI。
- authority_precision 在 general/math/physics 偏低，排序权重仍需用更大样本调参。

