# MathGuide v1.13.0 — 文献来源权威分级、免费全文与来源溯源

发布日期：2026-10-30
发布类型：功能版本（免费学术源接入 + 学科权威分级 + 开放获取解析）
代码快照：`56572b6`（标签 `v1.13.0` 指向该提交）
基线版本：`v1.12.0`（`3456b4d`）

本版本把「全网文献」从单一检索入口升级为按学科组织、可核验来源的文献发现层：

- 按学科路由到 Crossref、arXiv、Europe PMC、PubMed、INSPIRE-HEP、zbMATH Open、DOAJ、OpenAlex、Semantic Scholar；
- 每条结果带 ISSN、出版社、文章类型、同行评审、撤稿状态与开放获取状态；
- 用人工维护的场所注册表给综合顶刊与领域顶刊标注 T0–T3，预印本单独标 P；
- 通过 Unpaywall 与 OpenAlex 解析合法 OA 地址，只有 HTTPS 且确有全文时才提供免费入口；
- 阅读器顶部显示论文来源、许可与撤稿提示，导入后仍可追溯。

全部来源均为免费或开放接口；本版本不包含校园图书馆、CARSI、订阅 PDF 或任何付费墙绕过。

## 一、学科来源与权威分级

- 新增 `backend/research_sources.py`：来源注册表声明适用学科、权威层级、是否同行评审、
  key 环境变量与全文策略。未登记来源不会进入检索结果。
- 新增 `backend/research_venues.py` 与 `backend/registry/venues.json`：
  109 条人工维护的场所记录，覆盖综合、数学、物理、化学、生物五个方向。
- 场所分级规则：
  - `T0` 综合顶刊：Nature、Science、PNAS 等跨学科高先验；
  - `T1` 领域顶刊：PRL、JACS、Angewandte、Annals of Mathematics 等；
  - `T2` 领域强刊；`T3` 同行评审/索引期刊；`P` 预印本；`U` 用户上传。
- ISSN 归一化（去连字符、X 大写）优先匹配；无 ISSN 时用规范化名称与别名。
- Nature 子刊单独定级，不自动继承 Nature。
- 学科路由：
  - 物理加入 INSPIRE-HEP；
  - 生物医学加入 PubMed E-utilities；
  - 数学加入 zbMATH Open；
  - 综合检索只使用声明了 `general` 的跨学科来源。
- 排序按「场所层级 → 来源优先级 → 被引数 → 年份」，预印本不冒充满同行评审。

## 二、免费全文与开放获取解析

- 新增 `backend/research_oa.py`：Unpaywall 优先，OpenAlex 兜底。
- 只接受 HTTPS 地址；带用户名/密码、空白字符或控制字符的 URL 一律拒绝。
- 未配置 `MG_UNPAYWALL_EMAIL` 时跳过 Unpaywall，不伪造 OA 状态。
- OA 结果缓存 24 小时；检索结果缓存 5 分钟，减少 429 与重复请求。
- 没有合法免费全文时只显示「查看原文」跳转出版社页面，不显示「免费 PDF」。
- 前端新增「查找免费全文」按钮；已知 DOI 可单独解析。
- 不下载许可不明 PDF，不代理全文，不转存公共库。

## 三、检索界面与阅读器

- 检索筛选新增：学科、仅同行评审、含预印本、仅免费全文。
- 结果徽标新增：`T0–T3` / `P` 场所层级、同行评审、预印本、已撤稿、免费全文。
- 标签区分「查看原文」（出版社页面）与「免费全文」（合法 OA）。
- 阅读器顶部新增来源条：
  - 场所名称、同行评审、预印本、开放获取状态、许可、撤稿警告；
  - 「出版社页面」外链使用 `rel="noopener noreferrer"`。
- 切换阅读的论文时重新加载来源元数据，避免残留上一篇的信息。
- 临时论文与正式论文都保留来源元数据；导入正式库时不覆盖已有字段。

## 四、接口与配置

新增接口：

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/research/venues?issn=\|name=&field=` | 场所权威查询；ISSN 支持逗号分隔多值 |
| GET | `/api/research/sources` | 来源、学科、层级、全文策略与 key 配置状态，不探测外网 |
| GET | `/api/research/docs/{doc_id}` | 单篇论文来源元数据，供阅读器顶部显示 |

扩展接口：

- `GET /api/research/literature` 新增 `field`、`peerReviewed`、`includePreprints`、`oaOnly`；
- 结果新增 `issn`、`publisher`、`peerReviewed`、`articleType`、`oaStatus`、`oaUrl`、
  `license`、`retractionStatus`、`versionOf`、`fields`、`sourceTier`、`venueTier`、`landingUrl`；
- DOI 为 bioRxiv/medRxiv 时补充预印本元数据；关键词搜索仍走 Europe PMC。

配置（只放 `backend/.env.local`）：

```bash
MG_OPENALEX_API_KEY=...      # 免费 key，提高每日额度
MG_NCBI_API_KEY=...          # 可选，提高 PubMed 限额
MG_S2_API_KEY=...            # 可选；无 key 走公共池
MG_UNPAYWALL_EMAIL=...       # Unpaywall 要求联系邮箱
MG_LITERATURE_MAILTO=...     # 可选，Crossref 礼貌池
```

无 key 时 OpenAlex 搜索受共享每日额度限制，Semantic Scholar 走公共池，均可能 429；
配置免费 key 后额度独立。

## 五、修复与安全

- 修复 OpenAlex 搜索 `select` 含无效字段 `oa_status` 导致 400。
- 修复 OpenAlex OA 状态读取位置错误：应读 `open_access.oa_status`，此前恒为 unknown。
- 修复 Semantic Scholar 无 key 直接返回空：改为无 key 也请求公共池。
- 修复 INSPIRE `publication_info` 为列表时解析崩溃。
- 修复 zbMATH 许可占位记录进入结果。
- 修复 Crossref 返回 book chapter / front matter 等噪声条目。
- 修复 PubMed 仅按年份上限时 `mindate` 缺失。
- 修复 URL 净化遗漏：OA 地址与 landing URL 均只允许 HTTPS 且无凭据。
- 前端默认改为「仅同行评审、预印本关闭」；需要 arXiv 时手动勾选。
- 测试缓存隔离：来源与检索缓存不再跨测试泄漏。

## 六、验证

```text
backend pytest                     378 passed
frontend npm test                  全部自测通过
npm run build                      通过（仅 tex2svg 分块 >1800kB 的既有告警）
vue-tsc --noEmit                   通过
```

分学科冒烟（2026-10-30，每学科 3 查询 × Top-10，`tools/lit_smoke.py`）：

| 学科 | 结果 | authority_precision | peer | oa | source_errors |
| --- | --- | --- | --- | --- | --- |
| general | 30 | 10% | 100% | 43% | 3 |
| math | 30 | 10% | 100% | 10% | 3 |
| physics | 30 | 30% | 100% | 27% | 3 |
| chemistry | 30 | 57% | 100% | 27% | 3 |
| biology | 30 | 80% | 100% | 57% | 3 |

实时探测：

- Unpaywall 配置邮箱后，Nature Communications 样本解析为 `gold`，返回 `www.nature.com` 的 HTTPS PDF；
- OpenAlex 配置免费 key 后搜索不再 429，OA 状态正确读取；
- Semantic Scholar 无 key 可返回结果，公共池仍可能限流；
- ChemRxiv API 仍被 Cloudflare 403，ChinaXiv 404，CAS IR 连接失败，均未进入默认检索。

## 七、完整代码与溯源附件

本版本把**完整源码快照**与**完整变更补丁**一并入库，位于 `releases/v1.13.0/`，
也会作为 GitHub Release 资产上传：

| 附件 | 内容 | SHA-256 |
| --- | --- | --- |
| `MathGuide-v1.13.0-source.tar.gz` | **完整源码快照**（317 个文件，1,518,902 字节），由 `git archive` 从代码提交 `56572b6` 生成 | `2f3e3403b81095fc3ab8dd49dc4a0bf4be9b262a9a4214f27983a17de54e3333` |
| `v1.13.0.patch` | 相对 `v1.12.0` 的完整二进制补丁（248,646 字节，排除 `releases/` 附件） | `fd8f763de7e6508efa865d9d2fdbc4692ac8a425687ac02e9cba9b8e2d804878` |
| `MANIFEST.sha256` | 源码快照 317 个文件的逐文件 SHA-256（按归档内真实字节生成） | `f534ddfde159c07036aa20528f52297dfcb1ebc2de5541591ee8402baa24f47f` |
| `SHA256SUMS` | 上述附件 + 校验脚本 + 本目录 README 的 SHA-256 | 见文件本身 |
| `verify_manifest.py` | 跨平台逐文件校验脚本 | `0d304ea57b0a76938d55f539f02a0f189b77d1a1496b26e7b84b358ba6fbf01a` |
| `README.md` | 附件说明与复核步骤 | `dc427f87f6992a2fd3db0466cf0c5da5537c1b4a90663a163142d1a4f5b51196` |

复核步骤：

```bash
cd releases/v1.13.0
sha256sum -c SHA256SUMS
tar -xzf MathGuide-v1.13.0-source.tar.gz
python verify_manifest.py MathGuide-v1.13.0   # checked=317 failures=0
```

源码包不包含 `.git`、`backend/.env.local`、`backend/data/`、`.venv/`、`node_modules/`
和运行时缓存；`releases/**` 与 `NEWRELEASE.md` 在 `.gitattributes` 中标记为
`export-ignore`。`MANIFEST.sha256` 按源码包内真实字节生成，Windows 工作树的
CRLF 转换不影响归档校验，请以解压后的源码目录为准。

## 八、已知限制

- `authority_precision` 在综合、数学、物理仍偏低（10%–30%）；场所权重需用更大样本调参。
- Semantic Scholar 无 key 走共享池，可能 429；配置免费 key 后改善。
- OpenAlex 无 key 每日额度按网络共享；正式使用建议配置免费 key。
- Unpaywall 只按 DOI 解析；无 DOI 的结果无法解析 OA。
- 仅接受 HTTPS；出版社只提供 HTTP 链接时不会显示免费全文。
- ChemRxiv API、ChinaXiv、CAS IR、ADS、CORE 尚未接入或网络不可达。
- 不包含校园图书馆、CARSI、订阅 PDF、Sci-Hub 或任何付费墙绕过。
- 场所分级为人工维护的种子表，不是 JCR/中科院分区，也不替代授权索引。

## 九、升级步骤

1. 拉取 `v1.13.0`，安装依赖：
   `pip install -r backend/requirements.txt` 与 `cd frontend && npm ci`。
2. 在 `backend/.env.local` 配置：
   `MG_UNPAYWALL_EMAIL`（必需）、`MG_OPENALEX_API_KEY`（建议）、
   `MG_NCBI_API_KEY` / `MG_S2_API_KEY`（可选）。
3. 重启后端；`docs` 表会自动补充来源元数据列，旧文档字段为空但读写不受影响。
4. 前端 `npm run build`；按 `deploy/README.md` 配置 HTTPS/CSP 与双域 Cookie。
5. 运行 `python -m pytest` 与 `npm test` 确认环境。
6. 需要核对发布包时，按第七节命令执行 SHA-256 与逐文件校验。
