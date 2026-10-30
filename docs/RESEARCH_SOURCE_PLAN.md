# MathGuide 科研文献源与机构访问制作方案

日期：2026-10-30
范围：科学研究工作区的文献发现、全文获取、场所权威与广州大学机构访问
状态：方案稿，未开始编码

## 0. 结论摘要

1. 不追求“接更多网站”，先做**来源分级 + 场所权威 + 合法全文解析**。
2. 默认检索只信权威层；预印本、机构库、用户上传单独标记，不与同行评审论文等价。
3. 权威性是**学科内的权威**：Nature/Science 是综合顶刊，PRL、JACS、Cell、Annals 是各自领域顶刊；不能用一张总榜排序所有学科。
4. 全文获取分三条合法链路：
   - 开放获取：arXiv、PMC/Europe PMC、Unpaywall、OpenAlex、机构库；
   - 机构订阅：跳转出版社页面，由用户用“数字广大”登录 CARSI；
   - 用户自行下载：单篇导入，只进本人语料库，不共享。
5. 平台**不做**服务器代登录 CARSI、不保存学校密码/Cookie、不代下订阅 PDF、不转存公共库、不绕过付费墙。
6. 身份验证的可靠方式是 CARSI/Shibboleth SSO；校园邮箱只能做弱提示；学生证/学信网截图不接。
7. 推荐先做“公开机构访问入口 + 手动导入”，再评估 CARSI SP 与浏览器扩展。

## 1. 目标与非目标

### 目标

- 为数学、物理、化学、生物四个学科提供可解释的来源与场所权威排序。
- 每条结果都有稳定标识（DOI/PMID/arXiv/ADS/INSPIRE 等）、落地页、开放获取状态与许可。
- 能自动找到合法 OA PDF；找不到时明确跳转出版社页面，不误导“免费”。
- 广州大学师生可以通过 CARSI 在出版社页面获得订阅全文，并把单篇 PDF 导入自己的私有语料库。
- 检索、阅读、批注、数据表、对比表、报告形成可追溯闭环。

### 非目标

- 不做 Sci-Hub 或任何付费墙绕过。
- 不做学校账号池、共享登录、Cookie 代理。
- 不把订阅 PDF 放进公共/跨用户语料库。
- 不做全学科一次性铺开；按学科分批验收。
- 不把影响因子或中科院分区当作唯一权威指标。

## 2. 现状与差距

### 现状

- 外部检索：Crossref、arXiv、Europe PMC 默认可用；OpenAlex、Semantic Scholar 需 key。
- 聚合：DOI/标题去重，按被引数与年份排序。
- 全文：仅允许 arXiv、Europe PMC、PMC 白名单下载 PDF。
- 语料：用户上传与外部临时论文均进入按用户隔离的 SQLite。
- 前端：`ResearchSearchView.vue`、`DocumentViewer.vue`、`ResearchTablesView.vue` 已形成检索-阅读-数据表链路。

### 差距

- 结果没有 ISSN、出版社、文章类型、同行评审、撤稿状态、许可。
- 没有场所权威 registry，无法区分 Nature 与 Nature Communications、PRL 与普通物理期刊。
- 没有 Unpaywall/OpenAlex OA 解析，很多合法 OA PDF 找不到。
- 付费墙论文只能“查看 PDF”失败，没有清晰的出版社跳转与 CARSI 提示。
- 用户从学校订阅下载的 PDF 没有正式导入入口与来源标记。
- 没有撤稿/更正检查，也没有预印本与正式版的版本关联。
- 没有分学科金标准评测。

## 3. 总体架构

### 3.1 三层权威

| 层 | 含义 | 例子 | 用途 |
| --- | --- | --- | --- |
| 来源权威 | 元数据是否可靠 | Crossref、PubMed、INSPIRE、ADS | 决定是否信任题录信息 |
| 场所权威 | 发表期刊/会议在本学科的地位 | Nature、PRL、JACS、Cell、Annals | 决定排序与徽标 |
| 成果权威 | 单篇是否同行评审、是否撤稿、文章类型、版本 | 研究论文/综述/社论；预印本；撤稿 | 决定能否作为证据 |

三层分开存储、分开展示，不能压成一个“总分”。

### 3.2 数据流

```text
查询
  → 学科判定（math/physics/chemistry/biology/general）
  → 选择来源（权威层 + 可选预印本）
  → 并行检索（超时/失败隔离）
  → 统一归一化（标识、venue、ISSN、文章类型）
  → 去重与版本关联
  → OA 解析（Unpaywall/OpenAlex/Europe PMC/S2）
  → 撤稿/更正检查
  → 权威排序（学科 + venue tier + 类型 + 相关性）
  → 前端徽标/筛选/跳转/导入
```

### 3.3 模块划分

新增：

- `backend/research_sources.py`：来源注册表与启停。
- `backend/research_venues.py`：venue/ISSN registry 与学科层级。
- `backend/research_oa.py`：OA 解析与 PDF 合法性校验。
- `backend/research_fields.py`：学科判定与来源路由。
- `backend/data/venues.json`：可版本化的期刊/会议注册表。

改造：

- `backend/research_lit.py`：provider 适配、统一字段、分学科、OA 状态。
- `backend/research_corpus.py`：论文元数据补 ISSN/文章类型/许可/来源类型。
- `backend/research_papers.py`：机构来源导入、临时论文标记。
- `frontend/src/views/ResearchSearchView.vue`：徽标、筛选、机构访问、导入。
- `frontend/src/components/research/DocumentViewer.vue`：来源与许可提示。
- `frontend/src/services/literatureService.ts`：新字段与接口。

## 4. 来源注册表

### 4.1 来源矩阵

| 来源 | 学科 | 费用 | 稳定标识 | 全文 | 层级 |
| --- | --- | --- | --- | --- | --- |
| Crossref | 全学科 | 免费 | DOI | 元数据/落地页 | 权威元数据 |
| PubMed E-utilities | 生物医学 | 免费 | PMID | 元数据；PMC 链接 | 权威索引 |
| Europe PMC | 生物医学 | 免费 | PMID/PMCID/DOI | PMC OA 全文 | 权威索引 + OA |
| INSPIRE-HEP | 高能物理 | 免费 | arXiv/DOI/recid | 元数据 + arXiv 链接 | 领域权威 |
| NASA ADS | 天文/物理 | 免费 token | bibcode/DOI/arXiv | 元数据 + 链接 | 领域权威 |
| OpenAlex | 全学科 | 免费 | DOI/OpenAlex ID | OA 地址、引用图 | 发现层 |
| Semantic Scholar | 全学科 | 免费 key 可选 | DOI/paperId | `openAccessPdf` | 发现层 |
| Unpaywall | 全学科 | 免费（email） | DOI | 合法 OA 地址 | OA 解析器 |
| arXiv | 物理/数学/CS/部分生物 | 免费 | arXiv ID | PDF | 预印本 |
| bioRxiv/medRxiv | 生物/医学 | 免费 | DOI | PDF | 预印本 |
| ChemRxiv | 化学 | 免费 | DOI | PDF | 预印本 |
| ChinaXiv | 全学科（中文） | 免费 | DOI/CSTR | 开放记录 PDF | 预印本/机构库 |
| CAS IR Grid | 全学科 | 免费元数据 | OAI 标识/DOI | 部分 OA | 机构库 |
| zbMATH Open | 数学 | 免费 | zbMATH ID/DOI | 元数据/链接 | 领域权威 |
| DOAJ | 全学科 OA | 免费 | ISSN/DOI | 链接到期刊 | OA 目录 |
| CORE | 全学科 | 免费 key | DOI/OAI | 机构库全文 | OA 聚合 |
| Web of Science / Scopus | 全学科 | 付费授权 | DOI/UT/WOS | 元数据 | 授权索引 |
| MathSciNet | 数学 | 付费授权 | MR 号/DOI | 元数据/评论 | 授权索引 |
| SciFinder / Reaxys | 化学 | 付费授权 | CAS RN/DOI | 元数据/反应 | 授权索引 |
| JCR / 中科院分区 | 全学科 | 付费授权 | ISSN | 期刊评价 | 授权校准 |

### 4.2 规则

- 来源必须登记后才能启用；未登记来源不得进入检索结果。
- 授权来源只做“元数据可见/跳转”，不抓全文、不二次分发。
- 每个来源有 `enabled`、`requires_key`、`rate_limit`、`fulltext_policy`。
- 检索失败按来源降级并返回 warnings，不拖垮整页。

## 5. 场所权威 registry

### 5.1 分级

| 级别 | 含义 | 示例 |
| --- | --- | --- |
| T0 | 综合顶刊 | Nature、Science |
| T1 | 领域顶刊 | PRL、JACS、Cell、Annals of Mathematics、RMP |
| T2 | 领域强刊/顶会 | PRB、Chem. Sci.、eLife、NeurIPS |
| T3 | 同行评审且被权威索引收录 | 一般 SCI/SCIE、MEDLINE 期刊 |
| P | 预印本 | arXiv、bioRxiv、medRxiv、ChemRxiv、ChinaXiv |
| U | 用户上传/未核验 | 本地 PDF |

### 5.2 学科与跨学科

- venue 记录 `scope` 与 `tiers`：`{general:T0, physics:T1, chemistry:T1, biology:T1, math:T1}`。
- 综合顶刊在所有学科给高先验，但只在论文主题与查询学科匹配时生效。
- Nature 子刊单独定级，不自动继承 Nature；Nature Communications 与 Nature 不同级。
- 计算机等以顶会为主的学科，会议与期刊一样进入 registry。

### 5.3 主键与归一化

- 以 ISSN（去连字符、X 大写）为主键；一个 venue 可有多个 ISSN。
- 无 ISSN 的会议/预印本用规范化名称 + 年份/系列。
- 名称归一化只用于兜底：大小写、`&`/`and`、副标题、出版社前缀。
- 每条 venue 记录 `authority_source`（curated/DOAJ/WoS/Scopus/JCR/CAS）与 `registry_version`。

### 5.4 种子范围

- 数学 30–50：Annals、JAMS、Inventiones、Acta Mathematica、IHES、SIAM 系列、Annals of Applied Probability 等。
- 物理 30–50：PRL、RMP、PRX、Nature Physics、PRB、PRD、ApJ、MNRAS、INSPIRE 核心期刊。
- 化学 30–50：JACS、Angew.、Nature Chemistry、Chemical Reviews、Chem. Sci.、ACS Catalysis、Org. Lett. 等。
- 生物 30–50：Cell、Nature、Science、Nature Medicine、Immunity、Neuron、Cancer Cell、eLife、PLoS Biology、Cell Research 等。
- 医学与交叉：NEJM、Lancet、BMJ、JAMA、Nature Biotechnology、Nature Methods 等。
- 种子表人工维护，每条记录依据与更新日期；后续用授权数据校准。

## 6. 统一数据模型

### 6.1 检索结果字段

```text
title, authors, year, venue, issn, publisher
doi, pmid, pmcid, arxivId, adsBibcode, inspireId, zbmathId
url (landingUrl), pdfUrl
abstract, citations
fields[]                    # 学科标签
source                      # crossref/pubmed/inspire/...
sourceTier                  # authority/discovery/preprint/repository
venueTier                   # T0/T1/T2/T3/P/U
peerReviewed                # bool
articleType                 # research/review/editorial/letter/erratum/retraction
oaStatus                    # gold/hybrid/green/bronze/closed/unknown
oaSource                    # publisher/pmc/repository/preprint
license                     # CC BY/author manuscript/unknown
retractionStatus            # none/retracted/corrected/expression_of_concern
versionOf                   # 正式版 DOI 或预印本 ID
retrievedAt
```

### 6.2 本地语料字段

`docs` 表/文档元数据补充：

```text
issn, publisher, article_type, peer_reviewed
oa_status, license, access_source   # oa / institutional / user_upload
landing_url, source_url
retraction_status, version_of
```

- `access_source=institutional` 的文档只对上传者可见，不进入共享检索。
- 用户上传仍允许；默认标记 `user_upload`，不自动当权威证据。

### 6.3 registry 存储

- 来源与 venue registry 用仓库内 JSON/YAML，启动加载，带版本号。
- 授权数据（WoS/Scopus/JCR/CAS）只存本地授权环境，不入公开仓库。
- 用户级语料仍用现有按 uid SQLite，不把 registry 放进用户库。

## 7. Provider 适配

### 7.1 物理

- **INSPIRE-HEP**：`https://inspirehep.net/api/literature`，免费；取 title/authors/DOI/arXiv/citations/journal。
- **NASA ADS**：需免费 token；`https://api.adsabs.harvard.edu/v1/search/query`；取 bibcode/DOI/arXiv/citation_count。
- **arXiv**：预印本；标记 `P`，不参与同行评审排序。
- Crossref 补出版社与 ISSN。

### 7.2 生物

- **PubMed E-utilities**：`esearch`/`esummary`/`efetch`；取 PMID、MeSH、出版类型、撤稿标记。
- **Europe PMC**：现有；补 `fullTextUrlList` 与许可。
- **bioRxiv/medRxiv**：`api.biorxiv.org`；预印本标记。
- Crossref/DOAJ 补期刊与 OA 状态。

### 7.3 化学

- 免费层：Crossref、PubMed、Europe PMC、OpenAlex、ChemRxiv。
- 权威层：SciFinder/Reaxys 只有授权才接；不抓取、不转存。
- 期刊白名单：ACS、RSC、Wiley、Elsevier、Springer Nature、Nature Chemistry 等；用 venue registry 而不是硬编码出版社。
- PubChem/ChEMBL 是化合物/活性数据，不纳入论文检索。

### 7.4 数学

- **zbMATH Open**：数学专用元数据与评论；免费接口。
- arXiv 数学预印本；Crossref 正式版。
- MathSciNet 只有授权才接。

### 7.5 中文与机构库

- **ChinaXiv**：OAI-PMH 元数据；开放记录 PDF。
- **CAS IR Grid**：各所 OAI `oai_dc` 元数据免费；`cas_dc` 需授权；全文按开放状态。
- **PubScholar**：无公开 API，只做外链，不抓取。
- CNKI/万方/维普：授权；只做元数据/跳转，不抓全文。

## 8. OA 解析与全文策略

### 8.1 解析顺序

1. 结果自带 `pdfUrl` 且为可信 OA（arXiv/PMC/出版社 OA）。
2. Unpaywall（DOI）→ `best_oa_location`。
3. OpenAlex → `best_oa_location`。
4. Europe PMC → `fullTextUrlList`。
5. Semantic Scholar → `openAccessPdf`。
6. 都没有 → `oaStatus=closed`，只给 `landingUrl`。

### 8.2 PDF 校验

- 仅 HTTPS。
- 主机白名单 + 可信解析器返回来源双重校验。
- 重定向最多 3 次，每次重新校验。
- 大小上限、`%PDF-` 文件头、内容类型。
- 许可明确才下载；许可不明只跳转。
- 缓存 OA 状态 7–30 天，记录 `retrievedAt`。

### 8.3 全文展示

- `免费 PDF`：应用内阅读器直接打开。
- `开放获取 HTML`：外跳或文本抽取。
- `出版社页面`：新标签页打开；提示可能需要机构订阅。
- `预印本`：可用，但明确标识未经同行评审。

## 9. 检索路由与排序

### 9.1 学科判定

- 规则 + 模型轻分类：数学符号/术语、物理分类、化学术语、生物医学 MeSH。
- 查询可多学科；结果按主学科与次学科分别排序。
- 用户可手动切换学科范围。

### 9.2 排序

```text
score = relevance
      × venue_weight(field, venue.tiers)
      × article_type_weight
      × preprint_penalty
      × (retracted ? 0 : 1)
```

- 被引数只作 tie-breaker。
- 默认 `peerReviewed=true`；预印本需显式打开。
- 综合顶刊跨学科生效；领域顶刊只在对应学科加权。
- 撤稿/表达关注降权或阻断；更正版本优先。
- 预印本与正式版按 DOI/标题+作者+年份关联，合并展示。

## 10. 广州大学机构访问

### 10.1 授权事实

- 学校订阅授权给广州大学师生本人，不授权给平台服务器。
- 校外访问走 CARSI（`ds.carsi.edu.cn`，选择广州大学，数字广大账号）或 WebVPN。
- 出版社页面确认身份后显示全文；平台不能代登录、不能共享会话。

### 10.2 身份验证

| 方式 | 可靠性 | 用途 | 决策 |
| --- | --- | --- | --- |
| CARSI/Shibboleth SSO | 高 | 身份断言、机构徽标 | 推荐，需学校审批 |
| 校园邮箱 | 中低 | 体验分层 | 可选过渡，不算强授权 |
| 学生证/学信网 | 低/敏感 | 不建议 | 不接 |
| 自报/邀请码 | 无 | 无 | 不做 |

- 如果接 CARSI SP：只存 `affiliation=gzhu`、`verifiedVia=carsi`、`verifiedAt`；不存学号、姓名、证件、密码。
- 未验证用户仍可用免费 OA 与自行上传；不降级。

### 10.3 机构访问流程

1. 结果卡片显示「机构访问（广州大学）」。
2. 点击打开出版社 `landingUrl`，新标签页。
3. 页面提示：使用数字广大登录 CARSI；仅广大师生可完成。
4. 用户下载 PDF 后，点「导入 PDF」或拖入阅读器。
5. 后端解析 DOI/标题，补 Crossref 元数据，存 `access_source=institutional`、`visibility=private`。
6. 阅读器/对话只在本人账号内使用；不进入共享语料。

### 10.4 不做的事

- 服务器保存学校账号密码。
- 服务器模拟 CARSI 登录、复用 Cookie、绕过 MFA/验证码。
- 平台代下订阅 PDF 后给其他用户。
- 批量下载、镜像、转售、公开分享。
- 把订阅全文写入公共缓存或公共检索。

### 10.5 隐私与合规

- 最小化存储：只存机构归属与验证时间。
- 提供删除入口；账号注销时一并删除。
- 对外部大模型处理订阅内容给出提示；必要时提供“仅本地解析/不调用外部模型”选项。
- 遵守出版社订阅协议与学校图书馆规定；收到投诉可关闭机构通道。

## 11. 前端改造

### 11.1 检索结果卡片

新增徽标：

- `Nature · 综合顶刊`
- `PRL · 物理顶刊`
- `arXiv 预印本`
- `免费 PDF`
- `出版社页面`
- `已撤稿`
- `机构可访问（广州大学）`

按钮：

- `查看原文`：打开 landingUrl。
- `免费 PDF`：应用内阅读器。
- `机构访问`：出版社页面 + CARSI 提示。
- `导入 PDF`：本地文件上传。
- `生成对比表`：已有，保留。

筛选：

- 仅同行评审 / 含预印本
- 仅免费全文
- 学科范围
- 来源层级

### 11.2 阅读器

- 顶部显示 venue 徽标、许可、来源类型。
- `access_source=institutional` 显示“机构订阅获取，仅本人可见”。
- 撤稿论文显示阻断提示。

### 11.3 设置/帮助

- CARSI 使用说明页：入口、时间、账号类型、常见问题。
- 说明平台不代登录、不共享 PDF。

## 12. 后端接口

### 12.1 改造

`GET /api/research/literature`

新增参数：

```text
field=math|physics|chemistry|biology|general
peerReviewed=true|false
includePreprints=true|false
oaOnly=true|false
tier=T0,T1,T2,T3
```

返回新增字段：`issn/publisher/peerReviewed/articleType/oaStatus/oaUrl/license/retractionStatus/venueTier/fields/landingUrl`。

### 12.2 新增

- `GET /api/research/literature/oa?doi=`：OA 解析。
- `GET /api/research/venues?issn=|name=`：venue 权威查询（内部/前端徽标）。
- `POST /api/research/docs/import`：用户上传 PDF + 来源元数据（已有上传接口，扩展字段）。
- `GET /api/research/institutions/gzhu`：CARSI 入口配置与说明（静态，不含凭据）。
- 以后：`GET /api/research/affiliation`（CARSI SP 回调后）。

### 12.3 配置

```text
MG_LITERATURE_MAILTO
MG_OPENALEX_API_KEY
MG_S2_API_KEY
MG_ADS_API_KEY
MG_UNPAYWALL_EMAIL
MG_CORE_API_KEY
MG_CARSI_ENTITY_ID
MG_GZHU_CARSI_URL
MG_GZHU_LIBRARY_URL
MG_ENABLE_INSTITUTIONAL=true|false
```

## 13. 分阶段计划

### P0：来源治理与合法全文（1–2 周）

- venue registry 初版（四学科各 20–30 本）。
- 结果补 ISSN/出版社/文章类型/同行评审/OA 状态/许可。
- Unpaywall + OpenAlex OA 解析。
- 出版社落地页 + CARSI 提示 + 手动导入 PDF。
- PDF 校验扩展；保留现有白名单作为基线。
- 单元测试：字段归一化、ISSN 匹配、OA 解析、许可校验。

验收：

- 100% 结果有 landingUrl。
- OA 状态不误报；无合法 PDF 时不显示“免费”。
- 服务器不保存任何学校凭据。
- 现有 350 条后端测试全过。

### P1：物理与生物权威源（2–4 周）

- INSPIRE、ADS、PubMed E-utilities、bioRxiv/medRxiv 适配。
- 学科判定与来源路由。
- venue 权威排序与徽标。
- 每学科 50 条金标准查询。
- 撤稿检查（Crossref/PubMed/OpenAlex）。

验收：

- 物理/生物 Top-10 中领域顶刊占比达到目标（建议 ≥60%）。
- 预印本不与正式版重复计数。
- 撤稿样本 100% 标记。
- 端到端检索 p95 < 8 秒（不含 OA 下载）。

### P2：化学、数学与中文源（3–5 周）

- ChemRxiv、zbMATH Open、ChinaXiv、CAS IR OAI。
- 化学期刊白名单与学科排序。
- 版本关联、更正/表达关注。
- 对比表与报告引用 venue/许可。
- 扩展金标准到化学/数学。

验收：

- 化学免费层可用；授权层只留适配位。
- 数学检索优先 zbMATH/arXiv/Crossref。
- 预印本/正式版关联准确率 ≥90%（样本集）。
- 来源注册表外无结果。

### P3：机构身份与高级访问（依赖学校审批）

- CARSI SP 注册与属性映射（只存 affiliation）。
- 浏览器扩展：用户主动导入自己下载的 PDF。
- 授权索引适配位（WoS/Scopus/MathSciNet/SciFinder/Reaxys）。
- 机构访问审计与投诉处理流程。

验收：

- CARSI 登录不经过平台密码字段。
- 非广大用户无法通过平台服务器获取订阅 PDF。
- 订阅 PDF 仅本人可见，不能分享。
- 扩展只上传用户主动选择的单篇 PDF，不上传 Cookie。

## 14. 测试与验收

### 14.1 金标准

每学科 50 条查询：

- 20 条主题检索
- 10 条作者检索
- 10 条年份/期刊过滤
- 5 条 DOI/arXiv/PMID 精确检索
- 5 条跨学科检索

每条标注：

- 相关论文集合
- 领域顶刊集合
- 预印本/正式版对应关系
- 撤稿样本
- 合法 OA 状态

### 14.2 指标

- `authority_precision@10`：Top-10 中 T0/T1 占比。
- `field_coverage`：目标学科核心期刊覆盖。
- `oa_resolution_accuracy`：OA 状态与真实许可一致率。
- `retraction_recall`：撤稿样本识别率。
- `version_link_rate`：预印本/正式版关联率。
- `false_free_rate`：误标免费全文的比例，目标 0。
- `p95_latency`、`error_rate`。

### 14.3 回归

- 现有后端 pytest 全量。
- 前端 npm test、vue-tsc、build。
- 浏览器手工验证：检索 → 机构访问 → 下载 → 导入 → 阅读 → 批注 → 数据表 → 对比 → 报告。

## 15. 安全、法律与合规

- 不绕过付费墙；不接 Sci-Hub。
- 不保存学校账号、密码、Cookie、MFA。
- 不共享/转售订阅 PDF；不建公共订阅语料库。
- 遵守出版社订阅协议、图书馆规定与 robots/频率限制。
- 用户上传内容按用户隔离；机构来源标记私有。
- 外部大模型处理订阅内容需提示；提供关闭选项。
- 授权索引数据只在授权环境使用，不入公开仓库。
- 建立投诉/下架流程；收到出版社或学校通知可关闭通道。

## 16. 运维与配置

- 来源 key 只放 `backend/.env.local`，不入库。
- OA 状态缓存 7–30 天；venue registry 版本化。
- 每来源限速与熔断；失败返回 warnings。
- 日志不记录论文全文、不记录学校凭据。
- 监控：来源成功率、OA 解析率、跳转点击率、导入成功率。

## 17. 风险与应对

| 风险 | 影响 | 应对 |
| --- | --- | --- |
| 出版社反爬/封 IP | 检索失败 | 官方 API、限速、缓存、降级 |
| CARSI SP 审批慢 | 身份徽标延期 | 先公开机构访问入口，不阻塞 |
| 校园邮箱覆盖不全 | 弱验证误判 | 只做提示，不做授权 |
| 订阅 PDF 被分享 | 合规风险 | 私有标记、禁止共享、审计 |
| venue 分级主观 | 排序争议 | 公开依据、版本化、可申诉 |
| 模型抽取错误 | 对比表失真 | 核对列、人工确认、来源回跳 |
| 授权数据不可用 | 权威性不足 | 免费权威源 + 期刊白名单 + 金标准 |

## 18. 交付物

- 来源注册表与 venue registry（代码 + JSON + 版本号）。
- 新 provider 适配器与 OA resolver。
- 前端徽标、筛选、机构访问、导入流程。
- 分学科金标准集与评测脚本。
- 更新后的 `backend/README.md`、`NEWRELEASE.md`。
- 合规说明：CARSI、订阅全文、隐私与外部模型处理。

## 附录 A：环境变量

```text
MG_LITERATURE_MAILTO=          # Crossref 礼貌池
MG_OPENALEX_API_KEY=           # OpenAlex
MG_S2_API_KEY=                 # Semantic Scholar
MG_ADS_API_KEY=                # NASA ADS
MG_UNPAYWALL_EMAIL=            # Unpaywall
MG_CORE_API_KEY=               # CORE
MG_CARSI_ENTITY_ID=            # 未来 CARSI SP
MG_GZHU_CARSI_URL=https://ds.carsi.edu.cn/wxds/
MG_GZHU_LIBRARY_URL=https://lib.gzhu.edu.cn/
MG_ENABLE_INSTITUTIONAL=false  # 机构通道开关
```

## 附录 B：最小可行版本（MVP）

如果只做一件事：**P0 的 OA 解析 + 出版社落地页 + 手动导入**。

- 不改数据库大结构也能先上：结果卡片加 `oaStatus/landingUrl`，阅读器加「机构访问」「导入 PDF」。
- 先把“免费/可能付费/预印本”说清楚，再逐步加 venue registry 与学科排序。
