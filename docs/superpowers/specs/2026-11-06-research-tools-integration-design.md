# 科研区专业研究工具与合法全文接入设计

日期：2026-11-06
状态：已批准，进入实施计划
范围：只改科学研究区；学习辅助区保持现状
关联：[科研文献源方案 V2](../../RESEARCH_SOURCE_PLAN_V2.md) · [数据表与公式方案](../../DATA_FORMULA_PLAN.md) · [图解不变量](../../DIAGRAM_INVARIANTS.md) · [表示形式契约](../../REPRESENTATION_CONTRACT.md)

## 一、目标

科研区要能承担五类学科的专业研究任务：数学、物理、化学、生物医学、计算机。

具体目标：

1. **合法全文获取**：从 DOI、arXiv、PMID、PMCID 或标题出发，找到开放获取 PDF、开放获取落地页、预印本或作者版本；找不到时明确说“没有合法全文”，不伪造免费副本。
2. **五学科来源路由**：数学走 zbMATH/arXiv，物理走 INSPIRE/ADS，生物医学走 PubMed/Europe PMC，化学走 ChemRxiv/Crossref，计算机补 DBLP；综合来源继续用 Crossref、OpenAlex、Semantic Scholar、DOAJ。
3. **专业计算层**：为数据表提供确定性的回归与拟合，输出系数、标准误、t/p、置信区间、R²、残差与诊断。首版固定 OLS、多元线性、单 X 多项式；指数/对数/幂函数非线性拟合按用户确认的范围再排期。
4. **科研图解**：复用学习区已经成熟的图解放大窗口与渲染器，但换成科研规划器；图解必须依据论文、数据表或计算结果，不画教学模板式的空泛关系网。
5. **可审计**：所有数值由服务端计算，所有全文有来源、许可和访问方式；模型只能解释，不能编造回归结果或文献全文。

## 二、非目标

- 不做校园图书馆、CARSI、机构身份代理。
- 不接 Sci-Hub，不绕过付费墙，不批量下载，不分享订阅 PDF。
- 不保存 CARSI cookie、出版社会话、机构账号密码。
- 不接 Google Scholar 抓取、Web of Science、Scopus、MathSciNet、SciFinder、Reaxys 等订阅库的全文；有官方 API 且用户有权限时只做链接跳转或元数据。
- 不让模型执行任意代码，不让模型生成回归系数或显著性。
- 不改学习辅助区的布局、入口和功能边界。
- 不把科研区的论文库、全文获取或学科工具暴露给学习区。

## 三、反目标

以下任一情况视为失败，即使功能“能用”：

- 用户点“获取全文”后，系统静默下载了非开放获取的订阅 PDF。
- 系统保存或转发机构登录凭据、CARSI cookie、出版社会话。
- 回归图上的系数或 p 值来自模型自由生成，而不是计算层。
- 找不到合法全文时，界面暗示“可以免费下载”或引导到 Sci-Hub。
- 为了补计算机学科，直接把订阅库的搜索结果当全文来源。
- 科研图解把教学步骤图、装饰性坐标轴硬套到论文结论上。

## 四、现状与差距

| 能力 | 现状 | 缺口 |
| --- | --- | --- |
| 文献检索 | Crossref、arXiv、Europe PMC、PubMed、INSPIRE-HEP、NASA ADS、zbMATH、OpenAlex、Semantic Scholar、DOAJ、bioRxiv/medRxiv、ChemRxiv | 没有计算机学科字段；没有 DBLP；订阅库只能手工外链 |
| OA 解析 | `research_oa.py` 用 Unpaywall + OpenAlex，返回 `oaUrl`、`oaStatus`、`license` | 只按 DOI；没有多标识符编排；没有候选优先级与“无合法全文”状态 |
| PDF 下载 | `research_lit._pdf_url_allowed` 只允许 arxiv.org、europepmc.org、ebi.ac.uk、ncbi.nlm.nih.gov | 覆盖太窄；OpenAlex 返回的出版社 OA 地址无法站内打开；缺少私有地址/重定向防护 |
| 临时论文 | `research_papers.create_temp` + `research_corpus` 已有 temp/imported、来源、许可、访问方式字段 | 入口只接受白名单 PDF URL；没有“用户上传合法副本”的统一入口 |
| 数据表统计 | 描述统计、Pearson 相关、折线/散点/柱状图 | 没有回归、拟合、残差、置信区间、模型诊断 |
| 科研聊天图解 | 前端共用 `DiagramBlock`、图解放大窗口；手动“图解此段”可用 | 研究意图/数据表回答走 `_gen_research`，没有图解标记；规划器提示词仍是教学口吻 |
| 计算依赖 | 主服务只有标准库、openpyxl、python-docx 等 | 没有 statsmodels/SciPy/SymPy/pandas 等专业计算库 |

## 五、总体方案

```text
科研区
├─ 文献发现
│   ├─ 学科路由（math/physics/chemistry/biology/computer/general）
│   ├─ provider 并行检索
│   └─ 合法全文解析（research_fulltext）
│       ├─ OA PDF → 站内阅读器
│       ├─ OA 落地页/预印本 → 显式外链或站内元数据
│       ├─ 机构入口 → 只跳转，不代理
│       └─ 无合法全文 → 上传自有副本 / 文献传递模板
├─ 数据表
│   ├─ 描述统计（现有）
│   ├─ 回归/拟合（analysis worker）
│   └─ 拟合图、残差图、诊断
└─ 研究聊天
    ├─ RAG 综述 + 引用
    ├─ 科研图解规划器（依据论文/数据/计算结果）
    └─ 图解放大窗口（复用现有）
```

分四条线推进，按风险从低到高：

- **A. 合法全文接入**（P0）：先把“找到合法全文”做对，不接任何绕过渠道。
- **B. 五学科来源**（P1）：补计算机字段与 DBLP，明确各学科来源矩阵。
- **C. 计算与回归**（P1）：独立 analysis worker，数据表回归/拟合。
- **D. 科研图解**（P2）：研究规划器、数据绑定、研究综述自动图解。

## 六、A. 合法全文接入

### A1. 新模块 `backend/research_fulltext.py`

职责：把“一个标识符”变成“一组合法访问候选”，不直接返回任意网页。

输入：

```text
doi
arxivId
pmid
pmcid
title
```

解析顺序：

1. 标识符归一化。DOI 走 Crossref，arXiv ID 走 arXiv，PMID/PMCID 走 Europe PMC；只有标题时先做 Crossref 标题检索。
2. 候选来源：
   - Unpaywall `best_oa_location`（需要 `MG_UNPAYWALL_EMAIL`）
   - OpenAlex `best_oa_location` / `open_access`
   - Europe PMC `fullTextUrlList`
   - arXiv / bioRxiv / medRxiv / ChemRxiv
   - DOAJ / 出版社 OA 页面
3. 候选归一化：

```json
{
  "url": "https://...",
  "kind": "pdf" | "landing" | "html",
  "source": "unpaywall" | "openalex" | "europepmc" | "arxiv" | "biorxiv" | "chemrxiv" | "doaj" | "publisher",
  "hostType": "repository" | "publisher" | "preprint",
  "version": "publishedVersion" | "acceptedVersion" | "submittedVersion" | "unknown",
  "license": "CC BY 4.0",
  "serverDownloadable": true,
  "note": ""
}
```

4. 状态机：

```text
oa_pdf          有可站内下载的合法 PDF
oa_landing      有开放获取落地页，但服务端不代下
preprint        只有预印本落地页，且没有可站内下载的 PDF
institutional   需要机构权限，仅给官方入口
no_legal_copy   没有找到合法全文
unknown         来源不可用或超时
ambiguous       标题检索命中多个候选，需要用户选择
```

5. 多标识符：同时提供 DOI、arXiv、PMID/PMCID 时，逐个解析并合并候选，不因主标识符无全文就丢弃其他标识符的合法副本；响应增加 `matchedIdentifiers`，`identifier` 只表示主标识符。
6. 标题检索：Crossref 返回多个候选时，用归一化标题相似度过滤；只有唯一最高候选且相似度 ≥ 0.92 才自动采用；否则返回 `ambiguous` 和最多 5 个候选，由前端让用户确认。不得默认取第一条。
7. 排序：`oa_pdf` > `oa_landing` > `preprint`；同状态按来源可信度、版本、许可排序。Unpaywall/OpenAlex 的 `best_oa_location` 优先，但必须经过 URL 安全校验。
8. 缓存：按标识符缓存 24 小时；`no_legal_copy` 负缓存 1 小时；最多 512 条；缓存不存用户身份。`ambiguous` 不缓存。
9. 限流：复用 `research_lit._limiter` 或独立滑动窗口；按 uid 限流。

### A2. URL 安全与下载边界

现有 `_safe_url` 只检查 HTTPS 与用户名密码，不够。新增统一校验：

- 必须是 `https`。
- 禁止 URL 内嵌用户名/密码。
- 禁止 IP 字面量、localhost、私有地址、链路本地、保留地址；DNS 解析后再检查一次，防 DNS rebinding。
- 重定向最多 3 次，每次重定向后的 host 重新校验。
- 只接受 `Content-Type: application/pdf` 或 `%PDF-` 魔数。
- 单文件不超过 `MG_FULLTEXT_MAX_MB`（默认 100MB，与现有上传上限一致）。
- 超时、连接数、并发数有上限。
- 只有 `serverDownloadable=true` 的候选允许 `research_papers.create_temp` 下载；其余只返回链接。

`serverDownloadable` 判定：

1. URL 通过上述安全校验。
2. host 在“可信 OA 下载域”注册表中。**注册表是唯一准入条件；`Content-Type: application/pdf` 只是附加验证，不能单独让任意 host 变成可下载。**
3. 可信域允许显式子域，但每个子域重新做 DNS 与私有地址检查；不接受任意 CDN 或把出版社落地页当 PDF。
4. 不使用通用代理、不跟随到登录页、不提交 cookie。

可信 OA 下载域注册表放 `backend/research_sources.py` 或新 `backend/research_fulltext_hosts.py`，首版建议：

```text
arxiv.org / export.arxiv.org
europepmc.org / ebi.ac.uk
ncbi.nlm.nih.gov / pmc.ncbi.nlm.nih.gov
plos.org
mdpi.com
frontiersin.org
biomedcentral.com
```

出版社域名（Nature、Science、Elsevier、Wiley、Springer、SpringerOpen、Taylor & Francis 等）默认只做 `oa_landing`/`institutional` 外链，不进入服务端下载白名单；即使文章是 OA，也不把出版社页面误当 PDF。`link.springer.com` 等实际 PDF 地址只做外链，不走服务端下载。

### A3. 前端交互

检索结果卡片新增访问状态：

```text
开放获取 PDF   → 站内阅读器
开放获取页面   → 显式“在浏览器打开”，复制链接
预印本         → 预印本页面外链；若同一记录有可下载 PDF，按 oa_pdf 处理
机构入口       → 外链，标注“需要机构权限”
无合法全文     → “上传我有权限的副本” + “文献传递/作者索取模板”
来源未知/超时  → “重试”；不显示下载按钮
标题有歧义     → 候选列表，用户选择后才继续解析
```

规则：

- 不再根据 `oaUrl` 是否存在就直接下载；以服务端 `serverDownloadable` 为准。
- `ResearchSearchView.readerUrl`、`pdfReaderAllowed` 改为读取解析结果，不再维护第二份白名单。
- 外部链接必须由用户显式点击；不自动 `window.open`。
- 无合法全文时，不显示“免费全文”徽标，不显示 Sci-Hub 或聚合站入口。
- 上传自有 PDF 走现有 `uploadResearchDoc`，来源标记 `user_upload`；不与他人共享，不进入公共库。
- `preprint` 是“只有预印本落地页”的访问状态，不是版本标签；arXiv 的 PDF 返回 `oa_pdf`，同时带 `version=submittedVersion` 与 `source=arxiv`。

### A4. 接口

新增：

```http
GET /api/research/fulltext?doi=...&arxivId=...&pmid=...&pmcid=...&title=...
```

响应：

```json
{
  "status": "oa_pdf",
  "identifier": {"type": "doi", "value": "10.xxxx/xxxxx"},
  "matchedIdentifiers": [
    {"type": "doi", "value": "10.xxxx/xxxxx"},
    {"type": "arxiv", "value": "2410.xxxxx"}
  ],
  "best": {
    "url": "https://...",
    "kind": "pdf",
    "source": "unpaywall",
    "hostType": "repository",
    "version": "acceptedVersion",
    "license": "CC BY 4.0",
    "serverDownloadable": true,
    "isPreprint": false
  },
  "alternatives": [],
  "candidates": [],
  "reason": "",
  "cached": false
}
```

`ambiguous` 时 `best` 为空，`candidates` 返回最多 5 个标题候选；`unknown` 时 `reason` 说明哪些来源超时。

改造：

- `GET /api/research/literature/oa?doi=` 保留兼容，内部转调新 resolver。
- `POST /api/research/papers/temp` 只接受 `serverDownloadable=true` 的 URL；或接受 resolver 返回的一次性 token，避免前端伪造 URL。
- `GET /api/research/sources` 增加 `fields` 与 `capabilities`（`metadata` / `oa` / `download` / `link-out`）。

### A5. 配置

沿用：

```text
MG_UNPAYWALL_EMAIL
MG_OPENALEX_API_KEY
MG_NCBI_API_KEY
MG_S2_API_KEY
MG_ADS_API_KEY
MG_LITERATURE_MAILTO
```

新增：

```text
MG_FULLTEXT_MAX_MB=100
MG_INSTITUTION_RESOLVER=        # 可选，官方机构入口模板；只跳转，不代理
MG_CORE_API_KEY=                # 可选，CORE 聚合；未验证前不启用
```

约束：

- 所有 key 只放 `backend/.env.local`，不写前端、不写日志、不写文档。
- 机构入口模板只做链接拼接；不保存登录态，不代下订阅 PDF。
- 未配置 `MG_UNPAYWALL_EMAIL` 时，新 resolver 跳过 Unpaywall，继续查 OpenAlex、Europe PMC、arXiv、预印本源；只有所有来源都无法连接时才返回 `unknown`，所有来源都可达但无合法副本时返回 `no_legal_copy`。兼容接口 `/api/research/literature/oa` 同样走这条规则，不再“无 email 即 unknown”。

### A6. 测试

- 解析器优先级：Unpaywall 命中优先于 OpenAlex；PDF 优先于 landing。
- 无合法全文：所有来源返回 closed/空时状态必须是 `no_legal_copy`。
- 安全：`http://`、`localhost`、`127.0.0.1`、`10.*`、`172.16.*`、`192.168.*`、`169.254.*`、带用户名密码、非 PDF content-type、超大文件、重定向到私有地址全部拒绝。
- 禁止 Sci-Hub 域名进入候选或下载路径。
- 负缓存、限流、超时降级。
- 前端状态：`oa_pdf`、`oa_landing`、`preprint`、`institutional`、`no_legal_copy`、`unknown`、`ambiguous` 七种状态各自按钮与徽标正确，无合法全文不出现下载按钮。
- 标题歧义：并列候选返回 `ambiguous`，用户选择前不解析 PDF。
- 多标识符：DOI 无全文但 arXiv 有 PDF 时仍返回 `oa_pdf`，并保留 `matchedIdentifiers`。
- 现有 `tests/test_research_sources.py`、`test_research_lit.py`、`test_research_handwriting_safety.py` 全过。

## 七、B. 五学科来源

### B1. 学科矩阵

| 学科 | 权威/发现来源 | 预印本 | 全文策略 |
| --- | --- | --- | --- |
| 数学 | zbMATH、Crossref、OpenAlex、Semantic Scholar | arXiv | OA PDF 站内；MathSciNet 只外链 |
| 物理 | INSPIRE-HEP、NASA ADS、Crossref、OpenAlex、Semantic Scholar | arXiv | INSPIRE/ADS 的 OA 链接；订阅只外链 |
| 化学 | Crossref、OpenAlex、Semantic Scholar、DOAJ | ChemRxiv | ChemRxiv 落地页/PDF；出版社 OA 只外链 |
| 生物医学 | PubMed、Europe PMC、Crossref、OpenAlex、Semantic Scholar、DOAJ | bioRxiv/medRxiv | PMC/Europe PMC PDF 站内；PubMed 只元数据 |
| 计算机 | DBLP、Crossref、OpenAlex、Semantic Scholar | arXiv | DBLP 元数据；arXiv PDF 站内；ACM/IEEE 只外链 |

### B2. 代码改动

- `backend/research_sources.py`
  - `ALL_FIELDS` 增加 `computer`。
  - `SPECS` 增加 `dblp`：

```python
"dblp": SourceSpec(
    "dblp", "DBLP",
    ("computer",),
    "discovery", False, fulltext="landing"),
```

  - 可选增加 `SourceSpec.capabilities` 字段，标明是否支持 OA/下载/仅链接。
- `backend/research_lit.py`
  - 增加 `_dblp(client, query, limit, filters)`：调用 `https://dblp.org/search/publ/api`，解析 `hit`，归一化为现有 `_result` 字段；只取标题、作者、venue、year、DOI/URL，不抓全文。
  - DBLP 当前对服务器请求返回 `202 + text/html` 的 Anubis 反爬挑战（dblp.org / uni-trier / dagstuhl 三个入口一致）。**不绕过挑战**；`_dblp` 检测到 202/HTML 时抛 `RuntimeError("bot challenge")`，检索层把它记为警告，计算机学科继续走 Crossref/OpenAlex/Semantic Scholar/arXiv。DBLP 保留为可选来源，等官方提供无挑战 API 后再启用。
  - `_provider_funcs` 增加 `"dblp": _dblp`。
  - `_sort_results` 的学科权重表增加 `computer`。
- 前端：
  - `LiteratureQuery.field` 增加 `'computer'`。
  - `ResearchSearchView.vue` 学科下拉增加“计算机”。
  - `i18n.ts` 增加 `search.fieldComputer` 中英文。
- 测试：
  - DBLP 解析、无 DOI 结果的降级、字段路由不把 CS 查询送到 PubMed/zbMATH。
  - `sources_info` 的 `domains` 包含 `computer`。

### B3. 订阅库边界

- ACM DL、IEEE Xplore、SpringerLink、ScienceDirect、Web of Science、Scopus、MathSciNet 不接全文抓取。
- 有 DOI/官方链接时只显示 `institutional` 状态与出版社入口。
- 不解析机构登录页，不保存会话，不代下 PDF。

## 八、C. 专业计算层与回归

### C1. 独立 analysis worker

新增 `backend/analysis_worker.py` 或 `backend/tools/analysis_worker.py`：

- 独立进程，JSON 行协议；主服务通过 stdin/stdout 或本地子进程调用。
- 独立虚拟环境或独立依赖目录，不把 statsmodels/SciPy 装进主服务 venv；worker 无网络、无文件系统写权限、CPU/内存/时间上限。
- 只接受结构化请求，不接受用户代码、`eval`、任意表达式。
- 核心依赖固定版本：

```text
statsmodels
scipy
pandas
```

可选：

```text
sympy          # 符号方程整理；非必需
```

图表由前端 SVG 绘制，不安装 matplotlib。学科包：

```text
RDKit          # 化学
Biopython      # 生物医学
Astropy        # 物理/天文
NetworkX       # 计算机/关系图
```

这些包不默认加载；按学科能力探测后再启用，避免主环境过重。

### C2. 回归接口

P1 范围固定为：

- OLS（一元线性）
- 多元线性（一个 Y，多个 X，含截距）
- 多项式（单个 X，次数 2–4）

P1 不做指数/对数/幂函数非线性拟合；这类模型留到 P1b，等核心 OLS 数值对拍通过后再说。P1 不提供 `intercept=false`，请求里出现则返回 `unsupported`。

新增：

```http
POST /api/research/tables/{table_id}/regression
```

请求：

```json
{
  "x": ["A", "B"],
  "y": "C",
  "model": "ols" | "poly",
  "degree": 2,
  "options": {"missing": "listwise"}
}
```

- `ols`：`y = β0 + β1 A + β2 B + ...`
- `poly`：只允许一个 X；`y = β0 + β1 x + ... + βd x^d`，次数 2–4；不做多 X 交互项。内部可中心化/缩放改善条件数，但系数与方程按原始尺度输出。
- 缺失值：**listwise deletion**，Y 或任一 X 缺失的整行删除，与 statsmodels 默认一致；响应只报一个 `n` 与 `missing`（被删行数），不做 pairwise deletion。
- 至少 `n >= 参数个数 + 2`；否则返回 `insufficient_n`。
- 完全共线/奇异矩阵返回 `singular`，不伪造系数。
- 外推超过数据范围时返回 `extrapolation` 警告。

响应：

```json
{
  "model": "ols",
  "n": 42,
  "missing": 3,
  "equation": "C = 1.23 + 0.45 A - 0.02 B",
  "coefficients": [
    {"term": "const", "estimate": 1.23, "se": 0.1, "t": 12.3, "p": 0.0001,
     "ciLow": 1.0, "ciHigh": 1.4}
  ],
  "r2": 0.87,
  "adjR2": 0.86,
  "f": 120.4,
  "pF": 0.0001,
  "points": [
    {"row": 0, "actual": 1.2, "fitted": 1.15, "residual": 0.05}
  ],
  "fitCurve": [{"x": 0.0, "y": 1.2}],
  "warnings": []
}
```

- `points` 保留源行号、实测值、拟合值、残差；前端不重算。
- `fitCurve` 只对一元 OLS/多项式返回，供散点叠加拟合曲线；多元线性返回空数组，前端改画拟合值 vs 实测值。
- `r2` 与 `adjR2` 按含截距模型定义；P1 不支持无截距。
- 所有输出 4 位小数沿用现有 Decimal 展示规则；内部计算用浮点，前端不再二次计算。

### C3. 数据表 UI

- `ResearchTablesView` 分析面板增加第三个 tab：“回归”。
- 选择 Y（单列）与 X（一列或多列），选择模型；只列数值列。
- 结果区：
  - 方程
  - 系数表（估计、标准误、t、p、95% CI）
  - R²、调整 R²、F、n、缺失
  - 残差图（残差 vs 拟合值）
  - 警告
- 图表：
  - 新建 `RegressionChart.vue`，复用现有 SVG 绘制风格，但独立于 `TableChart.vue`，避免改动现有折线/散点/柱状。
  - 一元线性/多项式：散点 + `fitCurve` 拟合曲线。
  - 多元线性：拟合值 vs 实测值，或偏残差图。
  - 残差图：残差 vs 拟合值。
  - 不把回归线画到没有数据的区域；外推区用虚线或明确标注。
  - 图表由前端 SVG 绘制，不引入 matplotlib，不返回服务端图片。
- 导出：结果表可复制/导出 CSV；图和现有 TableChart 一样支持 SVG/PNG。

### C4. 研究聊天联动

回归结果不落库，也不写进 `research_tables.context_text` 的持久内容。采用“请求携带规格、服务端按当前表重算”：

1. 用户在数据表页跑完回归后，前端只在当前页面状态保留 `regressionSpec`（x、y、model、degree、运行时的 `tableUpdatedAt`）。
2. 点“在对话中分析”时，把 `regressionSpec` 放进 `sessionStorage`（键含 tableId），跳转 `/research?tableId=...&regression=1`；`ChatWorkspace` 读取后，在发送消息的 body 里带 `tableRegression`。
3. 后端收到 `tableId + tableRegression` 后，按当前表重新调用同一个回归函数；不信任前端传来的系数。
4. 如果当前表 `updatedAt` 与 `regressionSpec.tableUpdatedAt` 不同，返回并附上 `table_changed` 警告：“表格已修改，以下结果按当前数据重算”。
5. 聊天缓存键加入 `regressionSpec` 的哈希与当前表 `updatedAt`，防止复用回归前的旧回答。
6. 只有带了 `tableRegression` 的消息才把回归摘要写入上下文；只带 `tableId` 时仍然只有原始数据和描述统计，避免模型臆造“拟合结果”。
7. 回归摘要包含：模型、n、方程、R²、系数与 p 值、警告；提示词明确“不得自行重算或改写”。

### C5. 测试

- 与 statsmodels 固定样本对拍：系数、SE、t、p、R²、调整 R²、CI、F。
- 一元 OLS、多元线性、单 X 多项式 2–4 次；多项式系数按原始尺度复核。
- listwise 缺失处理：Y 或任一 X 缺失整行删除，`n` 与 `missing` 正确。
- 奇异矩阵、单列、常数 Y、n 不足、外推。
- 不支持无截距、模型名未知时返回 `unsupported`。
- worker 超时/崩溃时 API 返回 503，不返回假结果。
- 前端不显示未计算的结果；`fitCurve` 与 `points` 不二次计算。

## 九、D. 科研图解

### D1. 复用边界

- `DiagramBlock`、`Diagram3D`、图解放大窗口、焦点交互全部复用，不复制第二套。
- 只增加“科研模式”的规划器与数据绑定。
- 学习区提示词、图解分类器、教学步骤节奏不改。

### D2. 科研规划器

`research_diagrams.plan_diagram` 增加参数：

```text
mode="learn" | "research"
workspace="learn" | "research"
table_context / paper_excerpts
```

科研模式提示词要点：

- 只画【论文片段】【数据表】【计算结果】中出现的对象或数值。
- 优先类型：
  - 数据关系 → `plot2d`（散点、拟合线、残差）
  - 方法/实验流程 → `flow`
  - 概念/分类 → `tree` / `relation`
  - 模型结构/空间对象 → `geometry3d` / `surface3d`
- 不画“教学步骤图”，不把论文结论画成空泛关系网。
- **数据点与拟合线不由模型写入 JSON**。涉及数据表时，规划器只返回 `dataPlot` 意图（tableId、x、y、fitSpec），服务端用 Track C 的结果确定性生成 `plot2d` 形状；模型手写的数值点一律丢弃。
- 没有数据表或计算结果时，不生成散点/拟合图；资料不足时不画图，正文说明“资料不足，未生成图解”。

### D3. 自动图解接入点

两条路径：

1. **手动“图解此段”**：现有入口，增加 `tableId`，科研区可用。
2. **研究综述自动图解**：`_gen_research` 增加可选图解流。

推荐先做手动 + 显式请求，自动图解默认关闭，避免综述被图打断。自动图解打开时：

- 只对含数据表、实验方法、模型结构的段落调度。
- 每条回答最多 2 张，沿用 `MAX_DIAGRAMS`。
- 图解锚点必须在引用之后，不遮挡引用区。
- 规划失败静默降级为纯文本，不影响综述。
- 数据表图最多 200 个散点（现有表单行上限 200），拟合曲线最多 200 个采样点；超出图预算时降采样并标注，不截断成错误形状。
- 表格被删除或用户切换表后，不复活旧图；按当前 `tableId + updatedAt` 重新生成。

### D4. 测试

- 科研模式不生成无数据依据的拟合线。
- 有数据表时，图中散点与表内数值一致；模型返回的手写点被丢弃。
- 资料不足时不输出图。
- 引用区完整保留。
- 学习模式回归测试全部通过。

## 十、接口与数据模型汇总

### 新增接口

```text
GET  /api/research/fulltext
POST /api/research/tables/{table_id}/regression
POST /api/research/diagrams/plan        # 增加 tableId / mode
```

### 改造接口

```text
GET  /api/research/literature           # field 增加 computer
GET  /api/research/literature/oa        # 转调 fulltext
GET  /api/research/sources              # 增加 capabilities
POST /api/research/papers/temp          # 只接受 serverDownloadable
```

### 数据

- 现有 `docs` 已有 `origin_url`、`access_source`、`license`、`landing_url`、`retraction_status`，不新增表。
- 回归结果不落库，按需计算；用户可导出，不进入公共缓存。
- 全文缓存只存 URL 解析结果，不存订阅 PDF。
- 临时 PDF 沿用现有 20 个/用户保留策略；正式入库由用户确认。

## 十一、安全、合规与隐私

- **合法性**：只使用开放获取、预印本、作者版本、用户自有副本、机构官方入口。
- **禁止**：Sci-Hub、付费墙绕过、批量下载、共享订阅 PDF、抓取登录页。
- **凭据**：不保存机构账号、CARSI cookie、出版社会话；API key 只在后端环境变量。
- **SSRF**：私有地址、重定向、非 PDF、超大文件、DNS rebinding 全部拦截。
- **日志**：不记录带 token 的 URL、不记录用户查询全文；只记录来源、状态、耗时。
- **隔离**：科研区数据、论文库、全文缓存与学习区完全隔离。
- **许可展示**：结果与阅读器显示 license 与 access source；未知许可不标“免费”。
- **失败透明**：没有合法全文就说没有；来源超时说来源不可用；不静默换源。

## 十二、实施顺序与验收

### P0：合法全文与计算机学科

范围：A1–A6、B2 的 `computer`/DBLP 字段、前端状态。

验收：

- DOI/arXiv/PMID/PMCID/标题五类输入都能返回明确状态。
- 有 OA PDF 时站内阅读器可打开；无 OA 时只显示合法替代路径。
- 任何 Sci-Hub 域名、私有地址、非 PDF 响应都进不来。
- 计算机学科检索返回 DBLP 结果，其他学科不被误路由。
- 后端全量测试 + 前端 tsc/build 通过。

### P1：计算 worker 与回归

范围：C1–C5。

验收：

- 数据表可选 X/Y 跑 OLS、多元线性、多项式；系数/SE/t/p/CI/R² 与 statsmodels 对拍。
- 缺失、共线、n 不足、矩阵奇异都有明确提示。
- 拟合图与残差图可导出；研究聊天能引用已计算结果。
- worker 崩溃/超时不产生假结果。

### P2：科研图解

范围：D1–D4。

验收：

- 科研区手动图解可用；有数据表时散点/拟合线来自计算层。
- 研究综述可按显式请求生成图解；资料不足不画。
- 图解放大窗口、焦点交互与学习区一致。
- 学习区图解回归测试全部通过。

### P3：学科包

范围：RDKit、Biopython、Astropy、NetworkX 按需启用。

验收：

- 只有检测到对应能力时才显示相关工具。
- 未安装时不报错，不阻塞主链路。
- 学科包不获得网络与任意代码执行权限。

## 十三、降级策略

| 故障 | 降级 |
| --- | --- |
| Unpaywall 不可用 | 只用 OpenAlex；仍无结果则 `unknown`/`no_legal_copy` |
| OpenAlex 429 | 用 Unpaywall/Europe PMC/arXiv；不重试到死 |
| 出版社链接非 PDF | 标为 `oa_landing`，只外链 |
| DBLP 超时 | 用 arXiv/OpenAlex/S2；警告不阻断 |
| analysis worker 崩溃 | 回归 tab 显示“计算服务不可用”，不显示旧结果 |
| 回归奇异/求解失败 | 返回错误码与原因，不出图 |
| 图解规划器失败 | 纯文本回答，不影响引用 |
| 来源许可未知 | 不标“免费”，只显示元数据 |

## 十四、已确认的范围

用户已确认：

1. **回归首版**：OLS、多元线性、单 X 多项式 2–4 次。指数/对数/幂函数非线性拟合留到 P1b。
2. **计算依赖**：允许新增 statsmodels、SciPy、pandas（可选 sympy），放在独立 worker 与独立虚拟环境；主服务不装重依赖。

以下已由设计决定，不再作为开放问题：

- 机构入口默认关闭，只做官方链接；不保存登录态。
- 研究综述自动图解默认关闭，只在用户明确要求或手动点击时生成。
- 计算 worker 独立进程/独立虚拟环境，主服务不装重依赖。
- 计算机学科与 DBLP 在 P0 一起接；其他学科来源已存在，按字段路由。
- 用户自有 PDF 允许上传，标记 `user_upload`。
- 服务端可下载范围只由可信 OA 域注册表决定，content-type 不能单独放行。
- 无 Unpaywall email 时继续查 OpenAlex/Europe PMC/arXiv，不直接判 unknown。
- 回归缺失值用 listwise deletion；P1 不支持无截距。
- 科研数据图由服务端按计算结果确定性生成，模型不得写数据点。

状态：设计已按上述范围定稿；等待用户整体批准后进入实施计划。

## 十五、方案取舍记录

- **扩展现有 `research_lit`/`research_oa`，不另起全文服务**：现有检索、临时论文、语料库、阅读器已经串通；另起服务会增加部署和鉴权成本。
- **服务端只下载可信 OA 域，其他只外链**：比“任意 URL 代理”安全，避免 SSRF 和误下付费墙页面。
- **回归放独立 worker**：主服务保持轻量；计算库升级不影响聊天链路；worker 无网络、无任意代码执行。
- **科研图解复用渲染器，只换规划器**：避免两套图解剖裂；学习区的交互和回归测试不被破坏。
- **订阅库只做链接/元数据**：符合现有边界，不做 CARSI、不存 cookie、不共享 PDF。

### 审阅后补定的技术决策

- `serverDownloadable` 只由可信域注册表决定；`Content-Type: application/pdf` 只是附加验证，不能单独放行任意 host。
- `preprint` 是“只有预印本落地页”的访问状态；arXiv PDF 归 `oa_pdf`，同时带 `version=submittedVersion`。
- 新增 `ambiguous` 状态：标题检索相似度不足或出现并列候选时让用户选，不自动取第一条。
- Unpaywall 未配置 email 时跳过该源，不阻断 OpenAlex/Europe PMC/arXiv。
- 回归首版只做 OLS、多元线性、单 X 多项式；缺失值 listwise deletion；P1 不支持无截距。
- 回归结果不落库；聊天携带 `regressionSpec`，服务端按当前表重算，表版本变化时给警告。
- 回归图由前端 SVG 绘制，worker 返回 `points` 与 `fitCurve`，不引入 matplotlib。
- 科研数据图由服务端根据 Track C 结果生成，规划器只表达意图，模型不得写数据点。
- 每张数据图最多 200 个散点、200 个拟合采样点，超预算降采样。
