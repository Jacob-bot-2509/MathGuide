# MathGuide v1.11.0 — 双工作区、科研语料库、实验数据表与文献发现

发布日期：2026-10-29
发布类型：功能版本（科研工作区独立 + 论文检索 + 实验数据表 + 学习图谱/诊断）
代码快照：`0257ff8`（标签 `v1.11.0` 指向该提交）
基线版本：`v1.10.0`（`13296dc169d840e2cce2964324939a124bb53fac`）

本版本把「学习辅助」和「科学研究」拆成两个互不共享数据的独立工作区，
科研区新增服务端研究档案、按用户隔离的论文语料库、多格式入库、外部文献发现，
实验数据表支持模板导入、Excel 公式、合并拆分、WPS 打印与图片公式识别；
学习区补充知识图谱、掌握度诊断、学习路径推荐和文档生成。
同时修复待办跨区泄漏、表格键盘导航与列宽拖拽等问题。

## 一、双工作区隔离

- 学习区与科研区使用独立子域（`learn.*` / `research.*`）与共享登录 Cookie；
  后端按 Host 判定工作区，页面不能靠前端参数跨区。
- 会话、笔记本、待办、回收站按工作区分别存储：
  学习区沿用旧键，科研区使用 `mg-research-*` / `:research` 后缀，旧数据自动兼容。
- 待办清单修复跨区泄漏：学习区创建的任务不会出现在科研区。
- 科研区指令栏移除「章节知识导航」「公式查询手册」，保留
  「研究档案 / 搜索范围 / 待办清单」；学习区指令保持不变。
- 科研区不再显示「问题归纳」，改为服务端研究档案。

实现：`frontend/src/utils/workspace.ts`、`stores/{sessions,notebook,todo}.ts`、
`router/index.ts`、`components/chat/ChatWorkspace.vue`、`backend/auth.py`。

## 二、科研工作区

### 1. 研究档案

- 项目（标题、研究目标、思路、备注、状态）存服务端 SQLite，按 uid 隔离。
- 论文、实验数据表挂在项目下；删除项目可选择保留或级联删除附件。
- 支持导入旧版浏览器研究档案，原备份不删除；接口幂等，重复导入不重复建项。
- 实现：`backend/research_corpus.py`、`backend/research_legacy.py`、
  `frontend/src/components/chat/ResearchArchivePanel.vue`。

### 2. 论文语料库

- 入库格式：PDF、DOCX、EPUB、HTML/JATS、RTF、TXT/MD/TeX/CSV/JSON。
- 按文件头识别类型，扩展名只兜底：网页另存为 `.pdf` 也能按 HTML 解析。
- PDF 先走 pypdf；抽不到文字自动切 PDFium（`pypdfium2`），并加入 `fonttools`
  处理 CID/子集字体；两者都为空才判定为扫描件并提示 OCR。
- 单文件默认上限 20MB → 100MB（`MG_RESEARCH_MAX_UPLOAD_MB` 可调），
  单篇页数上限 300 → 600，支持百页级长文与学位论文。
- 非分页格式按段落打包成近似页，切片仍带位置与标题；标题中的 Markdown 标记会清理。
- 检索：BM25 + embedding 向量，RRF 融合；未配置 embedding 或服务失败时退化为纯 BM25。
- 章节树：标题层级 + 章节摘要；默认关闭，需要时在检索页勾选或传 `tree=true`。
- 命中结果带论文名、章节、页码与高亮片段，可一键把命中资料作为上下文提问。
- 评测工具：`backend/tools/eval_research.py`，样本集见
  `D:\Works\research-samples`（仓库外）。
- 实现：`backend/research_corpus.py`、`frontend/src/views/ResearchSearchView.vue`。

### 3. 外部文献发现

- 新接口：
  - `GET /api/research/literature?q=&limit=`：Crossref、arXiv、Europe PMC 并行检索，
    DOI 去重、按被引数排序；8 秒死线，慢源自动取消。
  - `GET /api/research/literature/related?doi=|title=`：按 DOI 取 Crossref 参考文献，
    并做标题相似检索。
  - `POST /api/research/literature/open-pdf`：下载开放获取 PDF 并用本机默认程序打开。
- 可选数据源：`MG_OPENALEX_API_KEY`（引用图）、`MG_S2_API_KEY`、
  `MG_LITERATURE_MAILTO`（Crossref 礼貌池）。
- 检索页新增「全网相关论文」面板；库内每篇论文有「相关」按钮。
- PDF 按钮只在有开放获取 PDF 时出现；下载地址仅允许 arXiv/Europe PMC/PMC 白名单、
  仅 HTTPS、限制重定向次数与大小、校验 `%PDF-` 文件头，防止 SSRF。
- 只返回元数据与摘要，不抓取或转存付费全文；本机 `.pdf` 默认关联 WPS 时直接由 WPS 打开。
- 实现：`backend/research_lit.py`、`frontend/src/services/literatureService.ts`。

### 4. 实验数据表

- 模板导入：XLSX / DOCX / CSV；单元格上限 200 行 × 30 列。
- 表格由结构化 schema 渲染，模型不生成表格代码，也不参与数值计算。
- 公式：Excel 风格（`=A2*B2`、`SUM(A2:A10)`、`$A$2:$A$4` 绝对引用），
  后端 `Decimal` + 白名单 AST 执行，禁止 `eval`；中间全精度，
  输出 `ROUND_HALF_UP` 保留 4 位小数。
- 逐格错误：空值、除零、循环引用、指数越界均定位到行列并标红。
- 录入体验：Excel 多格粘贴（含引号/换行单元格）、方向键移动单元格，
  左右键在文本内先移动光标、到行首/行尾再跳格。
- 合并/拆分单元格；合并块可跨方向跳过；列宽/行高可拖拽，表头与表体竖边框都可拖；
  表格总宽按列宽精确计算，拖多少像素变多少。
- 最左列可编辑行名；导出首列即行名。
- 「恢复默认」一键清除合并、列宽回 120px、行高回 30px，保留内容与公式。
- 计算列可手动删除；窄列时删除按钮固定在表头右上角，不会被挤出。
- 导出 CSV / XLSX；「打印」保存草稿后生成 xlsx 并用本机 WPS/Excel 打开，
  打印选项沿用 WPS 原生对话框；远端访问返回 403，避免在服务器弹程序。
- 图片公式识别：最多 4 张图，阿里云兼容接口，默认模型 `qwen3.8-omni-flash`；
  识别结果按组展示、变量映射到列、预览编译后的 Excel 公式后写入。
- 实现：`backend/research_tables.py`、`backend/research_vision.py`、
  `frontend/src/views/ResearchTablesView.vue`、
  `frontend/src/components/chat/FormulaImportDialog.vue`。

## 三、学习辅助

- 知识图谱：`GET /api/graph`，80 个知识点、前置依赖与章节分布；
  前端支持缩放、拖拽、章节聚焦、搜索与点选详情。
- 掌握度诊断：`POST /api/diagnosis`，模型评分或自评，记录按 uid 持久化。
- 学习路径推荐：前置知识点全部达标才进入候选，支持难度/核心度两种策略。
- 学习画像：`GET /api/profile`，返回诊断次数、掌握/薄弱、章节分布与最近记录。
- 文档生成：问答导出、大纲、分节生成，输出 PDF / Markdown / Word；
  前端新增 `DocModal.vue` 与 `docgenService.ts`。
- 实现：`backend/{knowledge_graph,diagnosis,recommendation,profile,docgen}.py`、
  `frontend/src/views/GraphView.vue`。

## 四、评测与工具

- `docs/EVAL_REPORT.md`：course-50 与 hallucination-50 两套评测报告。
  - course-50：正确率 1.000（48/48），检索 hit@3 0.667，答案级幻觉率 0.583。
  - hallucination-50：不可答编造率 0.000（0/50）。
  - 报告明确标注：样本为项目组自编，幻觉指标依赖模型评审，尚未人工盲标与 kappa 校准。
- 新增 `backend/tools/eval_research.py`：科研检索样本评测，支持 `--samples`、
  `--no-embed`、`--tree`。
- 新增 `backend/tools/research_backup.py`：按用户导出/恢复 tar.gz，含 tar 路径安全校验。
- `backend/tools/preflight.py` 增加语料库、数据表接口检查。
- 评测数据集补充 `backend/evaluation/data/hallucination-50.jsonl`。

## 五、修复清单

- 待办清单跨工作区泄漏：科研区不再看到学习区任务。
- 方向键改为四键移动单元格；左右键先移动文本光标，到边界再跳格；
  合并块按方向跨过，不再卡在锚点。
- 列宽拖拽补到表体竖边框；取消表格拉伸，列宽像素级生效。
- 计算列删除按钮不再被计算标签挤出列外。
- 上传失败直接显示后端原因（扫描件、格式不支持、超限等），不再统一提示“检查文本层”。
- 非 PDF 文档标题不再带 Markdown `#`。
- 研究档案从 localStorage 迁到服务端，修复多端不同步与删除不彻底。

## 六、行为变更与配置

| 项目 | 变更 | 默认/迁移 |
| --- | --- | --- |
| 版本号 | `1.10.0` → `1.11.0` | `package.json`、`package-lock.json`、关于页 |
| 论文上传上限 | 20MB → 100MB | `MG_RESEARCH_MAX_UPLOAD_MB` 可调 |
| 论文页数上限 | 300 → 600 | 常量 `MAX_PAGES` |
| 入库格式 | PDF/文本 → PDF/DOCX/EPUB/HTML/JATS/RTF/文本 | 文件头识别 |
| PDF 解析 | 仅 pypdf → pypdf + PDFium 兜底 | 新增依赖 `pypdfium2`、`fonttools` |
| 科研指令 | 移除章节导航、公式查询手册 | 学习区不受影响 |
| 检索默认 | 章节树默认关闭 | 评测显示树筛降召回 |
| 文献发现 | 新增 | `MG_OPENALEX_API_KEY`、`MG_S2_API_KEY`、`MG_LITERATURE_MAILTO` 可选 |
| 图片公式 | 新增 | `MG_VISION_MODEL` 默认 `qwen3.8-omni-flash`，复用 `MG_ALIYUN_*` |
| 本地打印/PDF | 新增 | 仅本机 Host 可用；`MG_PRINT_OPEN=1` 可强制放开 |

## 七、验证

```text
backend pytest                     299 passed
frontend npm test                  9 套自测全部通过
npm run build                      通过（仅 tex2svg 分块 >1800kB 的既有告警）
```

前端自测覆盖：SSE 收尾、MathText 公式渲染、回收站/本地数据隔离/会话持久化、
研究档案异步保存、研究表格保存竞态、待办清单、图谱布局、关于页内容、账号导出。

手工验证：

- 数字版 PDF（Viazovska 2017）入库成功并正确识别标题；扫描版 PDF 被拒绝并提示 OCR。
- HTML 改名 `.pdf` 仍按 HTML 正确解析；DOCX 入库成功。
- 168 页长文本入库、分页与检索正常。
- 外部文献检索返回 20 条结果，arXiv 结果可点「查看 PDF」下载并由本机 WPS 打开。
- 数据表：Excel 粘贴、方向键/光标、合并拆分、行列拖拽、恢复默认、打印、
  计算列删除、图片公式识别均通过浏览器实测。

## 八、完整代码与溯源附件

本版本把**完整源码快照**与**完整变更补丁**一并入库，位于 `releases/v1.11.0/`，
也会作为 GitHub Release 资产上传：

| 附件 | 内容 | SHA-256 |
| --- | --- | --- |
| `MathGuide-v1.11.0-source.tar.gz` | **完整源码快照**（296 个文件，1,412,633 字节），由 `git archive` 从代码提交 `0257ff8` 生成 | `3a3431cd42b852727adea26265e2c575d43d594a189fd4b88d07cd334d70e11f` |
| `v1.11.0.patch` | 相对 `v1.10.0` 的完整二进制补丁（845,629 字节，排除 `releases/` 附件） | `d1b445549168fb3c1472ba817484bbed49c14e0558557b83293eeb773d5bd99f` |
| `MANIFEST.sha256` | 源码快照 296 个文件的逐文件 SHA-256（按归档内真实字节生成） | `a1f36ff757fb95c23e817e18a8f1db6ebf5f65e24b73b04598a87a47457a6487` |
| `SHA256SUMS` | 上述附件 + 校验脚本的 SHA-256 | 见文件本身 |
| `verify_manifest.py` | 跨平台逐文件校验脚本 | `f3f99970b378ec198c63eaff357ee3bcf2c350cab5d5fe50b8950c17c730a6f7` |

复核步骤：

```bash
cd releases/v1.11.0
sha256sum -c SHA256SUMS
tar -xzf MathGuide-v1.11.0-source.tar.gz
python verify_manifest.py MathGuide-v1.11.0   # checked=296 failures=0
```

源码包不包含 `.git`、`backend/.env.local`、`backend/data/`、`.venv/`、`node_modules/`
和运行时缓存；`releases/**` 与 `NEWRELEASE.md` 在 `.gitattributes` 中标记为
`export-ignore`。`MANIFEST.sha256` 按源码包内真实字节生成，Windows 工作树的
CRLF 转换不影响归档校验，请以解压后的源码目录为准。

## 九、已知限制

- 扫描件/纯图片 PDF 仍需先 OCR；当前不会自动识别图片文字。
- 外部文献 PDF：Europe PMC 与 PMC 有反爬（403），目前「查看 PDF」实际只覆盖 arXiv；
  付费墙论文只提供标题/DOI 链接，不给全文。
- 未配置 OpenAlex/Semantic Scholar key 时，引用图与被引数据不完整，相关论文偏标题相似。
- 外部文献检索尚未接入科研对话：只能在 `/research/search` 页面使用；
  自然语言描述也未做检索式改写与相关性重排。
- 本机环境 embedding 端点 403，实际检索为纯 BM25；配置可用 embedding 后自动恢复混合召回。
- 章节树筛选在样本评测中会降低召回，默认关闭；长文定向查找时再开。
- 数据库仍为按用户 SQLite + 单进程缓存，多 worker 部署前需要重新评估锁与缓存一致性。

## 十、升级步骤

1. 拉取 `v1.11.0`，安装依赖：
   `pip install -r backend/requirements.txt`（新增 `pypdfium2`、`fonttools`）
   与 `cd frontend && npm ci`。
2. 在 `backend/.env.local` 按需配置：
   `MG_RESEARCH_MAX_UPLOAD_MB`、`MG_OPENALEX_API_KEY`、`MG_S2_API_KEY`、
   `MG_LITERATURE_MAILTO`、`MG_VISION_MODEL`、`MG_PRINT_OPEN`。
3. 重启后端；语料库/数据表会在首次访问时自动建表。
4. 前端 `npm run build`；按 `deploy/README.md` 配置 HTTPS/CSP 与双域 Cookie。
5. 运行 `python -m pytest` 与 `npm test` 确认环境。
6. 需要核对发布包时，按第八节命令执行 SHA-256 与逐文件校验。
