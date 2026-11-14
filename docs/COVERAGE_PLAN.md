# MathGuide 覆盖率方案（按文件定线，不追总数）

日期：2026-11-14 ｜ 基线：v1.26.0（`359107a`）
数据来源：`pytest --cov=. --cov-report=json`（本机实跑，995 passed）＋ `vitest --coverage`（9 文件 80 条）
配套：[优化方案](OPTIMIZATION_PLAN.md) §2 度量口径 ｜ [评测报告](EVAL_REPORT.md)

## 0. 这份文档怎么用

**验收单位是「文件」，不是「项目总数」。** 每个文件有自己的合格线、自己的现状、自己的缺口行；
CI 的总覆盖率门槛只有一个用途 —— **防倒退**，不作为"达标"依据。

读法：先看第 2 节的定线规则 → 在台账里找到你要改的文件 → 看它的判定与缺口 → 按第 5 节的配方写测试 →
在第 7 节的批次里勾掉。**不要**用"总数涨了"来宣布完成。

## 1. 为什么按类别定线，而不是一个统一数字

同一把尺子量所有代码，结果一定是"该测的没测够，不该测的被硬凑"：

- `quota.py`（10 语句，纯判断）和 `research_lit.py`（1005 语句，外部检索 + HTML 解析）风险完全不同，
  用 80% 一刀切，前者浪费、后者不足；
- 外部集成靠 mock 堆覆盖率，**数字高但一条网络异常都没验证**，比低覆盖更有害；
- 工具脚本（热重载守护、数据抓取）运行时不在线上，给它写测试纯属给分母注水。

所以规则是：**风险越高、越接近数据与凭据，线越高；越接近外部世界与一次性脚本，线越低或干脆不测**。

## 2. 定线规则与"达标"的判定

| 类别 | 合格线 | 判据 |
| --- | ---: | --- |
| A · 认证 / 凭据 / 数据写入 | **90%** | 错一次就是安全事件或数据丢失 |
| B · 计算 / 格式 / 渲染 | **85%** | 纯函数好测，算错就是给学生错答案 |
| C · 检索与对话主链路 | **80%** | 核心卖点，回归最常发生 |
| D · 科研工作台 | **80%** | 功能面宽，按文件逐个收 |
| E · 文档生成与导出 | **80%** | 输出物直接给用户 |
| F · 题库 | **80%** | 数据正确性依赖它 |
| G · 装配与入口 | **90%** | 80 语句，冒烟就能吃满 |
| H · 评测工具 | **80%** | 影响对外数字的可信度 |
| U · 前端 utils（纯函数） | **80%** | node 环境直接测，不需要 DOM |
| S · 前端 stores | **70%** | 有 localStorage 依赖，stub 成本中等 |
| V · 前端 services | **60%** | 要 stub fetch，主要验请求构造与错误映射 |
| 前端组件 / 模板 | **不设线、不纳入统计** | 断言要靠视觉回归，本项目暂无此手段 |

**单个文件"达标"必须同时满足两条**：

1. 该文件覆盖率 ≥ 它所属类别的线；
2. 该文件的**主要公开函数至少被调用一次**（覆盖率 90% 但某个导出函数从未被调用，视为未达标）。

第 2 条是为了挡住"测了内部小工具函数、主入口没测"这种假达标。

## 3. 后端逐文件台账（刷新于 2026-11-14，1195 passed）

**受管 91 个文件：达标 91 / 未达标 0**（3 个 omit 不计）。
含前端 55/55，项目合计 **146/146 达标、0 未达标**（2026-11-14 G2–G7 收口，实测见 §11）。

| 类 | 线 | 文件数 | 未达标 |
| --- | ---: | ---: | ---: |
| A 认证 / 凭据 / 数据写入 | 90 | 13 | 0 |
| B 计算 / 格式 / 渲染 | 85 | 11 | 0 |
| C 检索与对话主链路 | 80 | 13 | 0 |
| D 科研工作台 | 80 | 27 | 0 |
| E 文档生成与导出 | 80 | 3 | 0 |
| F 题库 | 80 | 16 | 0 |
| G 装配与入口 | 90 | 1 | 0 |
| H 评测工具 | 80 | 7 | 0 |

### 本轮收口的 10 个（之前未达标，现状如下）

| 文件 | 语句 | 之前 | 之后 | 线 |
| --- | ---: | ---: | ---: | ---: |
| `research_formats.py` | 336 | 67.9% | **100.0%** | 85 |
| `rag/research/__init__.py` | 108 | 45.4% | **100.0%** | 80 |
| `rag/research/sources.py` | 188 | 46.8% | **100.0%** | 80 |
| `chat.py` | 869 | 52.2% | **99.4%** | 80 |
| `research_compare.py` | 133 | 60.2% | **99.2%** | 80 |
| `research_fulltext.py` | 230 | 71.3% | **99.6%** | 80 |
| `research_lit.py` | 1005 | 65.4% | **98.2%** | 80 |
| `research_papers.py` | 218 | 70.2% | **99.5%** | 80 |
| `research_tables.py` | 1296 | 77.3% | **93.8%** | 80 |
| `research_vision.py` | 399 | 52.1% | **99.2%** | 80 |

> 数字取自 `pytest --cov=. --cov-report=json`（1504 passed，总覆盖 **90%**），不是分组自测口径。

### 已达标（冻结，改到相关模块时顺带补，不专门开工）

- **A**：`auth.py` 92.8% · `config.py` 92.6% · `db.py` 99.1% · `http_utils.py` 100.0% · `log.py` 100.0% · `origin_guard.py` 97.4% · `profile.py` 100.0% · `quota.py` 100.0% · `rate_limit.py` 97.8% · `security_headers.py` 100.0% · `session_cache.py` 96.4% · `store.py` 91.0% · `usage.py` 93.6%
- **B**：`analysis_capabilities.py` 100.0% · `analysis_client.py` 94.0% · `analysis_regression.py` 98.4% · `analysis_worker.py` 97.7% · `diagram_metrics.py` 100.0% · `diagram_taxonomy.py` 100.0% · `graph_layout.py` 96.2% · `linear_algebra.py` 85.6% · `math_render.py` 90.4% · `math_table_render.py` 100.0%
- **C**：`knowledge_graph/__init__.py` 95.3% · `rag/__init__.py` 94.1% · `rag/documents.py` 93.6% · `rag/embed.py` 86.7% · `rag/index.py` 87.7% · `rag/llm.py` 93.8% · `rag/research/rank.py` 95.7% · `rag/research/rerank.py` 100.0% · `rag/research/synthesize.py` 100.0% · `rag/research/types.py` 95.7% · `rag/route.py` 100.0%
- **D**：`chat_prompts.py` 88.2% · `chat_routing.py` 90.5% · `chat_sse.py` 95.1% · `dashboard_data.py` 96.6% · `diagnosis.py` 84.8% · `diagram_alerts.py` 100.0% · `ebbinghaus.py` 94.4% · `graph_api.py` 100.0% · `learning_analysis.py` 88.4% · `recommendation.py` 90.5% · `research_actions.py` 80.4% · `research_corpus.py` 80.5% · `research_diagrams.py` 86.5% · `research_legacy.py` 88.3% · `research_oa.py` 83.1% · `research_report.py` 91.5% · `research_sources.py` 93.9% · `research_urls.py` 93.3% · `research_venues.py` 95.1% · `retention.py` 100.0%
- **E**：`doc.py` 80.4% · `docgen.py` 82.7% · `exercise_docgen.py` 82.8%
- **F**：`exercises/__init__.py` 100.0% · `exercises/build.py` 98.7% · `exercises/dedupe.py` 93.8% · `exercises/gate.py` 94.0% · `exercises/importers/__init__.py` 100.0% · `exercises/importers/common.py` 87.5% · `exercises/importers/kuttler.py` 90.3% · `exercises/importers/math_dataset.py` 84.3% · `exercises/importers/numinamath.py` 81.0% · `exercises/importers/olympiadbench.py` 82.1% · `exercises/schema.py` 88.9% · `exercises/source_repairs.py` 82.1% · `exercises/store.py` 92.1% · `exercises/tagging.py` 100.0% · `exercises/taxonomy.py` 96.0% · `exercises/translate.py` 82.7%
- **G**：`main.py` 100.0%
- **H**：`evaluation/__init__.py` 100.0% · `evaluation/datasets.py` 83.6% · `evaluation/extract.py` 87.1% · `evaluation/judges.py` 89.6% · `evaluation/metrics.py` 93.5% · `evaluation/report.py` 100.0% · `evaluation/types.py` 100.0%

> 数据来源：`pytest --cov=. --cov-report=json`（1195 passed）。前端台账见 §4（2026-11-14 统计 + 本轮修好 4 个）。

## 4. 前端逐文件台账（55 个文件）

> 统计范围 = `src/utils` / `src/stores` / `src/services`（`vitest.config.ts` 的 `coverage.include`）。
> 组件与模板不在范围内，理由见第 2 节。
>
> **本轮（G5/G6/G7）已把 41 个未达标全部收口**：全量 `vitest run --coverage` 为
> **51 文件 / 1021 条全过，总覆盖 97.7%**（开工基线 12.34%）。下表「现状/判定」是开工基线，
> 保留用于对比；达标后的实测值见 §11。

### U · utils 纯函数（node 环境即可测） —— 合格线 80%（34 个文件，未达标 0）

| 文件 | 语句 | 现状 | 判定 |
| --- | ---: | ---: | --- |
| `src/utils/geogebraSpec.ts` | 483 | 0% | ❌ 差 80.0pp |
| `src/utils/geogebra3dSpec.ts` | 192 | 0% | ❌ 差 80.0pp |
| `src/utils/mathArrays.ts` | 192 | 0% | ❌ 差 80.0pp |
| `src/utils/graphLayout.ts` | 68 | 0% | ❌ 差 80.0pp |
| `src/utils/fulltextAccess.ts` | 24 | 0% | ❌ 差 80.0pp |
| `src/utils/workspace.ts` | 24 | 0% | ❌ 差 80.0pp |
| `src/utils/tex2svg.ts` | 15 | 0% | ❌ 差 80.0pp |
| `src/utils/aboutContent.ts` | 12 | 0% | ❌ 差 80.0pp |
| `src/utils/regressionChart.ts` | 3 | 0% | ❌ 差 80.0pp |
| `src/utils/diagramLabels.ts` | 329 | 1.51% | ❌ 差 78.5pp |
| `src/utils/diagramLayout.ts` | 245 | 1.63% | ❌ 差 78.4pp |
| `src/utils/todoTime.ts` | 44 | 2.27% | ❌ 差 77.7pp |
| `src/utils/avatar.ts` | 42 | 2.38% | ❌ 差 77.6pp |
| `src/utils/paperActions.ts` | 83 | 3.61% | ❌ 差 76.4pp |
| `src/utils/fileText.ts` | 17 | 5.88% | ❌ 差 74.1pp |
| `src/utils/speechMath.ts` | 166 | 7.22% | ❌ 差 72.8pp |
| `src/utils/diagramSpec.ts` | 345 | 8.98% | ❌ 差 71.0pp |
| `src/utils/mathIsolation.ts` | 175 | 12% | ❌ 差 68.0pp |
| `src/utils/cmdLink.ts` | 8 | 12.5% | ❌ 差 67.5pp |
| `src/utils/toast.ts` | 7 | 28.57% | ❌ 差 51.4pp |
| `src/utils/ambiguous.ts` | 25 | 56% | ❌ 差 24.0pp |
| `src/utils/classifier.ts` | 32 | 65.62% | ❌ 差 14.4pp |
| `src/utils/mathBlocks.ts` | 42 | 69.04% | ❌ 差 11.0pp |
| `src/utils/i18n.ts` | 22 | 77.27% | ❌ 差 2.7pp |
| `src/utils/diagramIntent.ts` | 27 | 77.77% | ❌ 差 2.2pp |
| `src/utils/diagramFocus.ts` | 37 | 100% | ✅ 达标 |
| `src/utils/splitPane.ts` | 14 | 100% | ✅ 达标 |
| `src/utils/commands.ts` | 2 | 100% | ✅ 达标 |
| `src/utils/i18n/account.ts` | 2 | 100% | ✅ 达标 |
| `src/utils/i18n/chat.ts` | 2 | 100% | ✅ 达标 |
| `src/utils/i18n/common.ts` | 2 | 100% | ✅ 达标 |
| `src/utils/i18n/learn.ts` | 2 | 100% | ✅ 达标 |
| `src/utils/i18n/research.ts` | 2 | 100% | ✅ 达标 |
| `src/utils/speechTips.ts` | 1 | 100% | ✅ 达标 |

### S · stores 状态与持久化 —— 合格线 70%（8 个文件，未达标 0）

| 文件 | 语句 | 现状 | 判定 |
| --- | ---: | ---: | --- |
| `src/stores/todo.ts` | 225 | 11.11% | ❌ 差 58.9pp |
| `src/stores/trash.ts` | 33 | 36.36% | ❌ 差 33.6pp |
| `src/stores/researchScope.ts` | 30 | 36.66% | ❌ 差 33.3pp |
| `src/stores/notebook.ts` | 32 | 46.87% | ❌ 差 23.1pp |
| `src/stores/localData.ts` | 23 | 52.17% | ❌ 差 17.8pp |
| `src/stores/sessions.ts` | 100 | 56% | ❌ 差 14.0pp |
| `src/stores/user.ts` | 18 | 66.66% | ❌ 差 3.3pp |
| `src/stores/settings.ts` | 15 | 73.33% | ✅ 达标 |

### V · services 接口层（需 stub fetch） —— 合格线 60%（13 个文件，未达标 0）

| 文件 | 语句 | 现状 | 判定 |
| --- | ---: | ---: | --- |
| `src/services/geogebraKernel.ts` | 100 | 0% | ❌ 差 60.0pp |
| `src/services/geogebra3dKernel.ts` | 96 | 0% | ❌ 差 60.0pp |
| `src/services/accountService.ts` | 52 | 0% | ❌ 差 60.0pp |
| `src/services/researchService.ts` | 50 | 0% | ❌ 差 60.0pp |
| `src/services/researchTableService.ts` | 47 | 0% | ❌ 差 60.0pp |
| `src/services/literatureService.ts` | 43 | 0% | ❌ 差 60.0pp |
| `src/services/docgenService.ts` | 13 | 0% | ❌ 差 60.0pp |
| `src/services/graphService.ts` | 10 | 0% | ❌ 差 60.0pp |
| `src/services/researchAnnotationService.ts` | 7 | 0% | ❌ 差 60.0pp |
| `src/services/diagramService.ts` | 4 | 0% | ❌ 差 60.0pp |
| `src/services/docService.ts` | 38 | 2.63% | ❌ 差 57.4pp |
| `src/services/chatService.ts` | 72 | 15.27% | ❌ 差 44.7pp |
| `src/services/authService.ts` | 48 | 18.75% | ❌ 差 41.2pp |

## 5. 缺口最大的文件：逐个说明怎么补

按"缺口语句数 × 可达性"排序。**可达性高的（纯函数、无网络）先做**，这是唯一能既快又真的路径。

| # | 文件 | 现状 | 缺 | 为什么大 | 怎么补（具体到测试点） | 用例量 |
| --- | --- | ---: | ---: | --- | --- | ---: |
| 1 | `analysis_regression.py` | 0% | 125 | 整文件从未被调用（接口测试把它 mock 掉了） | OLS 正常拟合（系数/截距/R²）、多项式 degree=1/2/3、样本不足（n<2）、长度不一致、非数值输入、共线性退化（奇异矩阵）、`Decimal` 非法值、输出字段齐全 | 8–10 |
| 2 | `main.py` | 0% | 80 | 所有测试都用手搭的 Starlette app，**装配从未被执行** | `import main` 后 `app` 存在；`/api/health` 200；未知路径 404；对只支持 POST 的路由发 GET 得 405；CORS 预检带正确头；`assert_safe_demo_mode` 三种拒绝各一条 | 7 |
| 3 | `db.py` | 83.5% | 18 | A 类唯一未达标；连接与迁移的异常路径没人走 | 首次建表、重复 init 幂等、WAL 参数生效、损坏库（写入垃圾字节后 connect）给出明确异常、迁移遇到旧表结构 | 5 |
| 4 | `analysis_client.py` + `analysis_worker.py` | 23.9% / 43.2% | 76 | JSON 行协议，两端各有分支 | 正常往返、worker 提前退出、响应超时、协议错行（非 JSON）、超大行截断、并发两请求 | 6 |
| 5 | `research_formats.py` | 67.9% | 108 | 上一轮刚拆出来的模块，格式分支多 | `_detect_format` 六种格式 ＋ **扩展名与魔数冲突**时以谁为准；`_extract_pages` 各自的空/坏文件；`_split_long` 边界（正好等于上限 / 超一字符）；`_sections` 的编号标题层级与无标题文档 | 10 |
| 6 | `chat.py` | 52.2% | 415 | 1509 行的路由 + 提示词 + 复核 + 图解校验混合体 | **只补决策分支，不补提示词字符串**：`_route_chat` 的 deep/main/backup 选择、闲聊直答、澄清触发、复核三态（correct/wrong/uncertain）与"更正块"追加、图解校验失败回退、论文问答无上下文时降级 | 12–15 |
| 7 | `rag/research/sources.py` + `rag/research/__init__.py` | 46.8% / 45.4% | 159 | 多源结果归一化 | 每个源一条：字段缺失、类型错、重复条目合并、排序键稳定；聚合层：空结果、单源失败不影响其余 | 8 |
| 8 | `research_lit.py` | 65.4% | 348 | 1005 行外部检索 + 解析 | **纯映射部分先测**：查询构造、结果归一化、去重、许可/撤稿标记；网络部分用录制 JSON fixture，补 429/超时/畸形响应 | 10 |
| 9 | `research_vision.py` | 52.1% | 191 | 外部视觉模型 | fake httpx：请求体构造、401/429/5xx 映射、超时、返回缺字段、返回非 JSON | 6 |
| 10 | `research_tables.py` | 77.3% | 294 | 1296 行，端点最多 | 只补未覆盖的端点分支：`/compute` 表达式非法、`/stats` 空表、`/regression` 样本不足、`/validate-formula` 不匹配 | 8 |
| 11 | `research_compare.py` | 60.2% | 53 | 多论文对比 | 全部抽取失败（502）、部分失败、字段缺失、空选择 | 4 |
| 12 | `diagram_alerts.py` / `rag/research/rerank.py` / `rag/research/synthesize.py` | 42.6% / 55.4% / 48.1% | 109 | 三个小文件，各差一半 | 各补 2–3 条：告警阈值边界、rerank 分数并列、synthesize 空片段 | 7 |

**关于"先做谁"**：第 1、2、3 名合起来 223 行缺口，且**零网络、零 mock**，一天内能全部吃完并留断言。
先做它们不只是因为便宜，而是各自对应一个真实空档：回归计算没被测过、装配没被执行过、A 类唯一缺口。

## 6. 按代码家族的测试配方

同一类文件用同一套写法，避免每个文件重新发明。

### 6.1 纯计算（`analysis_regression`、`linear_algebra`、`research_formats`、`math_*`）

- 输入用**最小可判定的结构化数据**（3 行表格、2×2 矩阵、十几个字节的文件），不造大样本；
- 每个函数至少一条**边界**（空、单元素、超上限）与一条**错误**（类型错、奇异、格式不符）；
- 断言看**数值与结构**，不看提示文案（把文案写进断言，改文案就红一片）。

### 6.2 外部 IO（`research_lit`、`research_vision`、`docgen`、`analysis_client`）

- 一律 `monkeypatch` 掉出网函数，喂**录制的真实响应片段**（放 `tests/fixtures/`）；
- 必测四态：**正常 / HTTP 错误码 / 超时 / 畸形响应**；
- 断言"错误怎么映射"（是否 502、是否降级、是否给用户可读提示），而不是"是否抛异常"。

> 这类文件的覆盖率不必追到 90%：mock 出来的分支只证明"我的代码按预期处理了我伪造的数据"。
> 到类别线（80%）即可停手，剩余交给真机验证（见 `OPTIMIZATION_PLAN.md` §0.1）。

### 6.3 状态机（`chat.py` 路由、`session_cache`、`rate_limit`、前端 `useChatStream`）

- 先画状态迁移表，**每条边一条用例**，重点在"非法迁移"：流式中再次发送、停止后立即续写、token 过期后再轮换；
- 时间相关的一律注入假时钟或 `monkeypatch` 时间函数，**不写 `sleep`**（既慢又不稳）。

### 6.4 装配（`main.py`）

- 只做**冒烟 + 契约**：能 import、路由齐、健康检查通、404/405 正确、中间件顺序正确（跨站 403 先于业务）；
- 不做业务断言 —— 业务在各自模块里测。这一层的价值是"证明线上真的挂上了"，我们上次真机验证才发现它从未被执行过。

### 6.5 数据管线（`exercises/*`）

- 用 2–3 条人造样本走完整链路（解析 → 校验 → 入库），断言**产物结构**与**拒收原因**；
- 不测"下载" —— 那是已 omit 的 `fetch.py`。

## 7. 执行批次（按可达性排，不按缺口大小排）

| 批次 | 文件 | 交付 | 完成标准 |
| --- | --- | --- | --- |
| **B1** 零覆盖 + 装配（1 天） | `analysis_regression` `main` `db` `analysis_client` `analysis_worker` | 5 个新测试文件 | 各自 ≥ 类别线；`main` ≥90% |
| **B2** 拆分出的模块（1 天） | `research_formats` `rag/research/sources` `synthesize` `rerank` `diagram_alerts` | 补齐分支 | 全部 ≥80% |
| **B3** 主链路分支（2 天） | `chat` `rag/llm` `rag/route` `research_compare` `research_urls` | 分支级断言 | 全部 ≥80% |
| **B4** 外部集成（2 天，可滞后） | `research_lit` `research_vision` `research_papers` `research_fulltext` `research_oa` | fixture + 四态 | 全部 ≥80% |
| **B5** 前端（2 天） | utils 25 个未达标 → stores 7 个 → services 13 个 | 按语句数从大到小 | 达到 U/S/V 各自的线 |

顺序理由：B1/B2 全是零网络，**不会因为环境失败而假绿**；B3 是"一改就容易坏"的地方；B4 成本最高、收益最不确定，允许滞后。

## 8. CI 门槛抬升节奏（只防倒退）

| 时点 | `--cov-fail-under` | 说明 |
| --- | ---: | --- |
| 现在（v1.26.0） | 75% | 比基线低 2pp，给重构留余量 |
| B1 合并后 | 78% | 零覆盖三件套吃完 |
| B2 合并后 | 80% | 拆分模块补齐 |
| B3/B4 完成后 | 81% | 每次只抬 1pp，宁慢不慌 |

**个体未达标不阻塞合并**：门槛只保证"整体不倒退"。某个文件没到线就挂在批次里，
**不允许用临时 omit 绕过** —— omit 只有第 9 节列出的三个文件，新增任何条目都要在 PR 里写理由。

## 9. 明确不做

1. **不给这三个文件写测试**（已 omit，运行时不在线上）：`dev_reload.py`、`exercises/fetch.py`、`evaluation/runner.py`。
2. **不追 90%+ 的总数**：80% → 90% 边际成本翻倍，抓到的多是防御性 `except`。
3. **不给 `.vue` 模板设覆盖率**：模板断言需要截图对比，本项目没有该手段；组件逻辑已在 composable 层测。
4. **不写"只调用不断言"的测试**：判定方法是"把被测分支改坏，测试必须红"，每个文件收尾时抽一条做这个检查。
5. **不滥用 `# pragma: no cover`**：`pyproject.toml` 已排除 `TYPE_CHECKING` / `NotImplementedError` / `@abstractmethod`，业务代码里再加就是掩盖。
6. **不为覆盖率改产品代码**：若某段代码难测是因为设计耦合，记进 `OPTIMIZATION_PLAN.md` 当结构债，而不是把逻辑搬进测试。

## 10. 每个文件收尾时怎么记录

在批次勾选表里填三件事，缺一不可：

```
- [x] analysis_regression.py   0% → 92%   tests/test_analysis_regression.py（9 条）
      改坏验证：把 degree 上限判断改成恒真 → test_poly_degree_cap 变红 ✅
```

- **覆盖数字**用 `pytest --cov=analysis_regression --cov-report=term-missing` 单独跑，不看总数；
- **改坏验证**是必填项：不写这条就等于没验证断言有效性；
- 提交信息带文件与数字，便于回查（例：`test: analysis_regression 0→92%（B1）`）。

最后重跑一次 coverage，把本文档第 3/4 节台账的"现状/判定"列刷新 —— 文档与代码不同步，比没有文档更糟。

---

## 11. 执行记录

### B1 零覆盖 + 装配（已完成）

| 文件 | 之前 | 之后 | 测试 | 改坏验证 |
| --- | ---: | ---: | --- | --- |
| `analysis_regression.py` | 0% | **98%** | `tests/test_analysis_regression.py`（24 条，新增 18） | 把 `degree not in (2,3,4)` 改成 `> 0` → `test_validate_spec_rejections` 红 |
| `main.py` | 0% | **100%** | `tests/test_main_app.py`（11 条，新文件） | 去掉 `OriginGuardMiddleware` → 跨站 403 用例红 |
| `db.py` | 83.5% | **99%** | `tests/test_db.py`（13 条，新文件） | 去掉 `conn.close()` → `test_connect_closes_connection_when_pragma_fails` 红 |
| `analysis_client.py` | 23.9% | **94%** | `tests/test_analysis_client.py`（12 条，新文件） | 不调 `proc.kill()` → 超时用例红 |
| `analysis_worker.py` | 43.2% | **95%** | `tests/test_analysis_worker.py`（+4 条） | 主循环不 catch `Exception` → 坏行用例红 |

**这一批暴露的三个真问题**（不是覆盖率问题，是工程问题）：

1. **`analysis_regression` 的 0% 是假象**：它其实有 6 条测试，但文件首行 `pytest.importorskip("statsmodels")`
   在缺依赖时**静默跳过** —— 看起来"没测试"，实际是"测试被跳过"。而 CI 只装
   `requirements.txt` + `requirements-dev.txt`，**从不装 `requirements-analysis.txt`**，所以 CI 里永久跳过。
   已在 CI 补装 analysis 依赖（否则这个文件的覆盖率永远是 0，且没人会发现）。
2. **`import main` 会写 `backend/data`**：模块级执行 `store.init()` / 迁移 / 留存清理 / `rag.init()`。
   这就是没人给它写测试的原因。测试改为「先 patch 数据路径再 import」，顺带覆盖了
   "启动期数据迁移失败只能告警、不能阻断服务"这条真实分支（3 条 OSError 降级路径）。
3. **本地 venv 的 numpy 是为 cp314 编译的**，3.13 解释器导入即崩 —— 已重装（numpy 2.2.6 / statsmodels 0.14.4 /
   scipy 1.14.1 / pandas 2.2.3）。这条也解释了为什么"analysis 相关模块覆盖率一直是 0"。

**未覆盖且判定为不可达的 7 行**（已确认不是漏测）：

| 文件 | 行 | 原因 |
| --- | --- | --- |
| `analysis_regression.py` | 85 | `_validate_spec` 已保证列都存在,该防御分支进不来 |
| `analysis_regression.py` | 152 | 常数 X 会先触发 `singular`,进不到 `low == high` |
| `db.py` | 87 | WAL 重试 10s 超时后的 `raise`,需伪造时钟 |
| `analysis_client.py` | 14-17, 37 | posix 专属(`resource.setrlimit` / bin/python),Windows 上不执行 |
| `analysis_worker.py` | 67 | `if __name__ == "__main__"`,import 时不可达 |

**全量回归**：`1062 passed`（B1 前 995，+67），总覆盖率 **77% → 78%**。

### B2 拆分出的模块（部分完成：3 / 5）

| 文件 | 之前 | 之后 | 测试 | 改坏验证 |
| --- | ---: | ---: | --- | --- |
| `rag/research/rerank.py` | 55.4% | **100%** | `tests/test_research_rerank.py`（14 条，新文件） | 去掉 `except` 回退 → 超时/异常用例红 |
| `rag/research/synthesize.py` | 48.1% | **100%** | `tests/test_research_synthesize.py`（5 条，新文件） | 引用区改成打印模型输出 → 元数据断言红 |
| `diagram_alerts.py` | 42.6% | **100%** | `tests/test_diagram_alerts.py`（8 条，新文件） | 去掉冷却判断 → 重复告警用例红 |

**B2 剩下 2 个**（未做）：

| 文件 | 现状 | 线 | 缺口 | 难点 |
| --- | ---: | ---: | ---: | --- |
| `research_formats.py` | 67.9% | 85% | 108 行 | 六种格式 × 魔数/扩展名冲突 × 损坏文件,用例量大但零网络 |
| `rag/research/sources.py` | 46.8% | 80% | 100 行 | 每个源的字段归一化 + 同 key 合并,需要先读各源返回结构 |

**全量回归**：`1089 passed`（B1 后 1062，+27）。

### B3–B5（未开始）

- B3 主链路：`chat`(52.2) `rag/llm`(57.3) `rag/route`(60.0) `research_compare`(60.2) `research_urls`(75.0)
- B4 外部集成：`research_lit`(65.4) `research_vision`(52.1) `research_papers`(70.2) `research_fulltext`(71.3)
- B5 前端：utils 25 个 + stores 7 个 + services 13 个

**还差的近线文件**（差 1–8pp，成本低）：`linear_algebra`(83.9→85) `math_table_render`(81.4→85)
`doc`(72.6→80) `docgen`(78.6→80) `exercise_docgen`(78.8→80) `exercises/build`(75.6→80)
`evaluation/judges`(77.9→80) `research_tables`(77.3→80)。

### 近线补齐（8 个中完成 5 个）

| 文件 | 之前 | 之后 | 线 | 测试 | 补的是什么 |
| --- | ---: | ---: | ---: | --- | --- |
| `math_table_render.py` | 81.4% | **100%** | 85 | 8 条（新文件） | 渲染失败 / 多页 PDF / KaTeX 错误标记 / 位图模式异常 / 全白空图 / 异常包装 —— 全是"公式会在 Word 里凭空消失"的分支 |
| `evaluation/judges.py` | 77.9% | **90%** | 80 | 7 条（新文件） | 围栏 ``` 解析、脏 claims 过滤、`supported` 非布尔记 null、旧 `refused` 兼容 |
| `exercises/build.py` | 75.6% | **99%** | 80 | 4 条（新文件） | CLI 入口 `main()`、未知来源、`--limit 0`、`--source all` |
| `exercise_docgen.py` | 78.8% | **83%** | 80 | 6 条（新文件） | 难度词映射（难/中/易）、显式字段优先、difficulty/count 脏值回退 |
| `docgen.py` | 78.6% | **81%** | 80 | 7 条（新文件） | PDF 渲染失败 500、Word 公式不兼容 422、md 分支、无证据时的兜底大纲与分组上限 |

**近线剩 3 个**：`doc`(72.6，缺 55 行，其中 350-392 是依赖 Chromium 的 `render_pdf_bytes`)、
`linear_algebra`(83.9，缺 14 行才到 85)、`research_tables`(77.3，缺 35 行)。

### 近线补齐（8 个中完成 6 个）

| 文件 | 之前 | 之后 | 线 | 测试 | 补的是什么 |
| --- | ---: | ---: | ---: | --- | --- |
| `linear_algebra.py` | 83.9% | **85.5%** | 85 | 10 条（新文件） | `_num`/`_vec`/`_vectors`/`_matrix`/`_complex`/`_cvec`/`_cmatrix` 的形状与数值校验、`_is_symplectic`/`_is_unitary` 判定、复数投影三种模式 —— 用户填错一格应得 400 而不是 500 |

> 编写时纠正了一个数学误判:我最初断言"单位矩阵不是辛矩阵",实际辛群包含 `I`
> (`IᵀJI = J`)。改成用缩放矩阵 `diag(2,1)` 验证真正的非辛分支。

**近线剩 2 个**：`doc`(72.6，缺 55 行，其中 350-392 依赖 Chromium)、`research_tables`(77.3，缺 35 行)。

### B5 前端（开始：4 个小 utils 达标）

| 文件 | 之前 | 之后 | 线 | 说明 |
| --- | ---: | ---: | ---: | --- |
| `src/utils/cmdLink.ts` | 12.5% | **100%** | 80 | 畸形百分号编码退回原文(不抛 URIError)、空前缀返回 null |
| `src/utils/toast.ts` | 28.6% | **100%** | 80 | 自动消失时长、连续提示清旧定时器 |
| `src/utils/regressionChart.ts` | 0% | **100%** | 80 | 无拟合曲线(多元回归)返回空段、残差散点横轴用 fitted |
| `src/utils/workspace.ts` | 0% | **100%** | 80 | 子域→工作区判定、跨子域跳转保留路径并丢掉查询/锚点、单域恒为同区 |

测试文件 `src/utils/pureHelpers.test.ts`（14 条，happy-dom 环境，用 `window.happyDOM.setURL` 切子域）。

**前端全量**：脚本套件「全部通过」+ vitest **94 条**（此前 80），`eslint` 0 违规。

**前端剩余 41 个**：`geogebraSpec`(483, 0%) `diagramSpec`(345, 9%) `diagramLabels`(329, 1.5%)
`diagramLayout`(245, 1.6%) `mathArrays`(192, 0%) `geogebra3dSpec`(192, 0%) `mathIsolation`(175, 12%)
`speechMath`(166, 7%) `paperActions`(83, 3.6%) `graphLayout`(68, 0%) `avatar`(42, 2.4%) 等。

### B3 起步：链路裁决与下载白名单

| 文件 | 之前 | 之后 | 线 | 说明 |
| --- | ---: | ---: | ---: | --- |
| `rag/route.py` | 60.0% | **100%** | 80 | 四路裁决顺序(研究意图 > 知识命中 > 数学框架 > 会话)、中英研究标记 |
| `research_urls.py` | 75.0% | **93%** | 80 | https/凭据/控制字符校验、`.local` 与私有 IP 拒绝、可信域后缀伪装拦截、DNS 四态(OSError/仅 IPv6/私有 IPv4/公网) |

测试文件 `tests/test_route_and_urls.py`（29 条）。`research_urls` 剩 4 行是 `is_safe_pdf_url` /
`resolves_to_public_host` 里的 `urlparse` ValueError 兜底 —— 前面 `is_https_url` 已经先返回 False，
这两处属不可达防御。

**全量**：`1161 passed`（+28），`ruff` 全绿。

**全量回归**：`1123 passed`（B2 后 1089，+34）。`ruff` 全绿。



### G1 前半：rag 降级与索引重建（已完成）

| 文件 | 之前 | 之后 | 线 | 测试 | 改坏验证 |
| --- | ---: | ---: | ---: | --- | --- |
| `rag/__init__.py` | 74.3% | **89%** | 80 | `tests/test_rag_degrade.py`（7 条，新文件） | 去掉 `_load_index_or_empty` 的兜底 → 重建失败用例红 |

覆盖的是四条降级路径与一次重建:知识库文件在 `glob` 与 `stat` 之间消失、embedding 构造失败降级关键词模式、
`_warm_embedder` 预热失败静默、知识库变更触发重建(双检只重建一次)且重建失败用空索引兜住;
另加数学题使用更低向量门限 `MATH_VECTOR_ONLY_MIN`。

> 测试里加了 autouse fixture 还原 `rag` 模块级全局(`_index/_embedder/_stamp/_terms`),
> 因为 `init()` 会写全局 —— 不还原会污染后续测试文件。

**剩余**:`rag/__init__.py` 173-210(11 行,`terms`/`is_math_question`/统计)不必追;
G1 的另一半 `rag/llm.py`(57.3% → 80%,缺 41 行,主要是 112-174 的流式客户端)未做。

**全量回归**(补跑上一轮欠的验证):`1182 passed, 0 failed`。
### G1 后半：rag/llm 流式客户端（已完成，G1 收口）

| 文件 | 之前 | 之后 | 线 | 测试 | 改坏验证 |
| --- | ---: | ---: | ---: | --- | --- |
| `rag/llm.py` | 57.3% | **92%** | 80 | `tests/test_llm_stream.py`（13 条，新文件） | 把 `if not fallback or emitted` 里的 `emitted` 去掉 → 「半截 A + 完整 B」用例红 |

覆盖:角色解析三态(无冒号/平台未知/缺 key)、`pick` 回退 main、思考开关两种下发口径、
流式帧解析(保活帧/空行/[DONE]/坏 JSON/思考帧不算正文)、`temperature` 透传,
以及四条容灾:**首字超时(保活帧撑过 read 超时)与异常帧持续到达两种超时**、
切换 backup、**已 yield 过内容绝不重放**、无备胎时直接抛。

> 最要紧的一条:`stream_chat` 只在「一字未出」时允许切 backup。已有输出后重放会让用户看到
> 「半截 A + 完整 B」,所以那条 `emitted` 判断就是它的护栏。


---

## 12. G2–G7 全量收口（2026-11-14，一次做完）

**结论：后端 10 个 + 前端 41 个未达标文件全部达标，未达标数归零。**

| 总量 | 之前 | 之后 |
| --- | ---: | ---: |
| 后端 pytest | 1195 passed / 总覆盖 80% | **1504 passed / 90%** |
| 前端 vitest | 10 文件 94 条 / 12.34% | **51 文件 1021 条 / 97.70%** |
| 达标文件 | 95 / 146 | **146 / 146** |
| ruff / eslint / vue-tsc | 0 | **0 / 0 / 0** |
| 产品代码改动 | — | **0**（`git status` 只有测试文件） |

> 验收口径没变：单文件 ≥ 类别线、主要公开函数被调用、每文件一次改坏验证。
> 后端数字取自一次完整 `pytest --cov=. --cov-report=json`（不是分组自测口径）。

### 12.1 G2 · research 中等（5 个，零网络）

| 文件 | 之前 | 之后 | 线 | 测试 | 改坏验证（改坏什么 → 哪个用例红） |
| --- | ---: | ---: | ---: | --- | --- |
| `research_formats.py` | 67.9 | **100.0** | 85 | `test_research_formats.py`（30） | docx 判据 `"word/document.xml" in names` 改坏 → 3 条红（zip 容器识别 / 多格式合并 / 坏 zip 容忍） |
| `rag/research/sources.py` | 46.8 | **100.0** | 80 | `test_research_sources_fields.py`（19，新） | `_is_retryable` 去掉 `408/425/429` → `test_is_retryable_only_retries_rate_limit_and_server_errors` 红 |
| `research_papers.py` | 70.2 | **99.5** | 80 | `test_research_papers.py`（25） | `history_delete` 的 `"days": 0 if hard else TTL` 改恒 0 → 硬/软删除用例红 |
| `research_fulltext.py` | 71.3 | **99.6** | 80 | `test_research_fulltext.py`（31） | 负结果 TTL 改成与正结果一致 → `test_cache_ttl_differs_for_negative_results` 红 |
| `research_compare.py` | 60.2 | **99.2** | 80 | `test_research_compare_report.py`（18） | `_verify_numbers` 的缺失数改成恒空 → 2 条红（未核对数字 / 字段缺失） |

### 12.2 G3 · research 大件（4 个）

| 文件 | 之前 | 之后 | 线 | 测试 | 改坏验证 |
| --- | ---: | ---: | ---: | --- | --- |
| `chat.py` | 52.2 | **99.4** | 80 | `test_chat_routing_branches.py`（98，新） | 7 处逐条改坏全部变红：复核更正块、图解放行、研究缓存 TTL、澄清触发、复核角色错开、当前论文分支、无上下文数学题 |
| `research_lit.py` | 65.4 | **98.2** | 80 | `test_research_lit.py`（73） | `_merge` 去重键 DOI→标题 → 1 条红 |
| `research_vision.py` | 52.1 | **99.2** | 80 | `test_research_vision.py`（37） | `_clean_result` 去掉 `not target` 判断 → 1 条红 |
| `research_tables.py` | 77.3 | **93.8** | 80 | `test_research_tables.py`（54） | `validate_formula` 的 `error > max_error` 改恒假 → 1 条红 |

`chat.py` 只补**决策分支**（路由选型、闲聊直答、澄清、复核三态与更正块、图解闸门、无上下文降级、论文/数据表并行动作），
没有为提示词常量写用例。

### 12.3 编排层 `rag/research/__init__.py`（不属于 G2/G3 清单，顺手收口）

| 文件 | 之前 | 之后 | 线 | 测试 | 改坏验证 |
| --- | ---: | ---: | ---: | --- | --- |
| `rag/research/__init__.py` | 45.4 | **100.0** | 80 | `test_research_pipeline.py`（18，新） | `chosen = picked or None` 改 `chosen = picked` → `test_all_invalid_scope_falls_back_to_everything` 红 |

覆盖：范围过滤（未勾选的源一个请求都不发）、全非法 scope 退回全平台、单源失败只记名不中断、
缓存键含范围 + TTL 过期重检 + LRU 逐出、LLM 改写优先与失败回退规则版、`_llm_expand_terms` 的
200 字截断与 2–60 字过滤、精排只在有外源结果时发生、知识库片段截断 400 字。

**全量**:`1195 passed, 0 failed`(+13),`ruff` 全绿。**G1 两个文件全部达标。**

### 12.4 G5 · 前端大字 utils（8 个，纯函数，node 环境）

| 文件 | 之前 | 之后（语句） | 线 | 测试 | 改坏验证 |
| --- | ---: | ---: | ---: | --- | --- |
| `geogebraSpec.ts` | 0 | **97.10** | 80 | `geogebraSpec.test.ts`（51） | 点去重 `has(key)`→`has(key+'#')` → 同坐标去重用例红 |
| `geogebra3dSpec.ts` | 0 | **94.27** | 80 | `geogebra3dSpec.test.ts`（30） | 包围盒 `*1.4`→`*1` → Line 两点定方向 2 条红 |
| `diagramSpec.ts` | 8.98 | **99.13** | 80 | `diagramSpec.test.ts`（73） | `>= MAX_DIAGRAMS`→`+1` → 「第三张被拒绝」红 |
| `diagramLabels.ts` | 1.51 | **99.69** | 80 | `diagramLabels.test.ts`（64） | 越界惩罚 `*1e7`→`*0` → 4 条夹取用例红 |
| `diagramLayout.ts` | 1.63 | **98.36** | 80 | `diagramLayout.test.ts`（34） | `GAP_Y 26`→`20` → 3 条分层间距红 |
| `mathArrays.ts` | 0 | **95.83** | 80 | `mathArrays.test.ts`（31） | 双线边框 `3px`→`2px` → 3 条表格边框红 |
| `mathIsolation.ts` | 12 | **96.00** | 80 | `mathIsolation.test.ts`（50） | 待定公式闸门改恒假 → 6 条红（金额/纯中文/超长…） |
| `speechMath.ts` | 7.22 | **96.38** | 80 | `speechMath.test.ts`（106） | 平方规则 `'²'`→`'^2'` → 7 条红 |

### 12.5 G6 · 前端中等 utils（13 个）+ stores（8 个）

| 文件 | 之前 | 之后（语句） | 线 | 测试 | 改坏验证 |
| --- | ---: | ---: | ---: | --- | --- |
| `paperActions.ts` | 3.61 | **100** | 80 | `paperActions.test.ts`（23） | `MAX_ACTIONS 16→4` → 单帧上限红 |
| `graphLayout.ts` | 0 | **100** | 80 | `graphLayout.test.ts`（11） | `level+1`→`level` → 5 条红 |
| `todoTime.ts` | 2.27 | **100** | 80 | `todoTime.test.ts`（19） | `>=`→`>`（到点判定）→ 红 |
| `avatar.ts` | 2.38 | **100** | 80 | `avatar.test.ts`（10） | 去掉 `Math.min(1,…)` → 红 |
| `mathBlocks.ts` | 69.04 | **92.85** | 80 | `mathBlocks.test.ts`（15） | 围栏奇偶 `%2===1`→`===0` → 3 条红 |
| `classifier.ts` | 65.62 | **100** | 80 | `classifier.test.ts`（18） | `MATH_STYLE_RE→true` 短路 → 红 |
| `ambiguous.ts` | 56 | **100** | 80 | `ambiguous.test.ts`（16） | 上下文判断短路 → 2 条红 |
| `fulltextAccess.ts` | 0 | **100** | 80 | `fulltextAccess.test.ts`（14） | pdf 拒绝分支放行 → 红 |
| `i18n.ts` | 77.27 | **100** | 80 | `i18nRuntime.test.ts`（14） | `catName` 恒取中文 → 2 条红 |
| `fileText.ts` | 5.88 | **100** | 80 | `fileText.test.ts`（10） | 页数上限 80→200 → 红 |
| `tex2svg.ts` | 0 | **100** | 80 | `tex2svg.test.ts`（6） | `display` 写死 true → 红 |
| `aboutContent.ts` | 0 | **100** | 80 | `aboutContent.test.ts`（16） | 问题反馈 URL 改错 → 红 |
| `diagramIntent.ts` | 77.77 | **96.29** | 80 | `diagramIntent.test.ts`（12） | 无消息兜底 null→true → 7 条红 |
| `todo.ts`（store） | 11.11 | **98.22** | 70 | `stores/todo.test.ts`（40） | `flag === true`→`flag` → 脏 done 容错红 |
| `sessions.ts` | 56 | **97** | 70 | `stores/sessions.test.ts`（20） | 上限 20→21 才裁剪 → 红 |
| `trash.ts` | 36.36 | **100** | 70 | `stores/trash.test.ts`（17） | `>= cutoff`→`>` → 边界当天红 |
| `researchScope.ts` | 36.66 | **100** | 70 | `stores/researchScope.test.ts`（13） | 去掉「至少留一个平台」→ 红 |
| `notebook.ts` | 46.87 | **100** | 70 | `stores/notebook.test.ts`（13） | `A_MAX 3000→2000` → 红 |
| `localData.ts` | 52.17 | **100** | 70 | `stores/localData.test.ts`（10） | 换账号判断 `!==`→`===` → 2 条红 |
| `user.ts` | 66.66 | **100** | 70 | `stores/user.test.ts`（9） | 去掉未登录守卫 → 红 |
| `settings.ts` | 73.33 | **100** | 70 | `stores/settings.test.ts`（8） | 主题写死 `dark` → 3 条红 |

### 12.6 G7 · 前端 services（13 个）

| 文件 | 之前 | 之后（语句） | 线 | 测试 | 改坏验证 |
| --- | ---: | ---: | ---: | --- | --- |
| `geogebraKernel.ts` | 0 | **96.00** | 60 | `geogebraKernel.test.ts`（12） | `setPerspective('G')`→`'T'` → 离屏 applet 用例红 |
| `geogebra3dKernel.ts` | 0 | **95.83** | 60 | `geogebra3dKernel.test.ts`（10） | `'T'`→`'G'` → 3D 离屏用例红 |
| `chatService.ts` | 15.27 | **81.94** | 60 | `chatService.test.ts`（19） | `onDone(full, complete)`→`(full,true)` → 断流用例红 |
| `accountService.ts` | 0 | **100** | 60 | `accountService.test.ts`（11） | `server?'full':'local'`→`'full'` → 3 条本地态红 |
| `researchService.ts` | 0 | **100** | 60 | `researchService.test.ts`（20） | 列表返回 `[]` → 列表/分页用例红 |
| `authService.ts` | 18.75 | **100** | 60 | `authService.test.ts`（21） | `409→exists` 改 `→invite` → 状态码映射红 |
| `researchTableService.ts` | 0 | **100** | 60 | `researchTableService.test.ts`（16） | `hard?'?hard=1':''`→`''` → 硬删除红 |
| `literatureService.ts` | 0 | **100** | 60 | `literatureService.test.ts`（16） | 默认 `limit 10→20` → 默认参数红 |
| `docService.ts` | 2.63 | **100** | 60 | `docService.test.ts`（14） | 文件名兜底 `mg-document`→`document` → 回退用例红 |
| `docgenService.ts` | 0 | **100** | 60 | `docgenService.test.ts`（9） | `slice(-80)`→`slice(-1)` → 会话截断红 |
| `graphService.ts` | 0 | **100** | 60 | `graphService.test.ts`（12） | `limit=${limit}`→`limit=5` → 条数透传红 |
| `researchAnnotationService.ts` | 0 | **100** | 60 | `researchAnnotationService.test.ts`（9） | 去掉 `encodeURIComponent` → id 转义红 |
| `diagramService.ts` | 0 | **100** | 60 | `diagramService.test.ts`（9） | `kind || undefined`→`input.kind` → 空值不进请求红 |

服务层统一覆盖四条非 happy path：非 2xx+JSON 错误体、非 2xx+非 JSON 体、`fetch` 网络异常、

### 12.7 仍未覆盖的行（判定为不可达或低价值，均未用 pragma 掩盖）

| 文件 | 行段 | 判定 |
| --- | --- | --- |
| `chat.py` | 385 / 987 | 累积到 4000/300 字后 `break` 的长度保护，不是决策分支 |
| `chat.py` | 461 | `paper_mode` 追加段是**纯提示词常量**；真实 `_gen_paper_llm` 在用例里被打桩 |
| `chat.py` | 1198 | **不可达**：`_is_feature_question` 只匹配中文关键词，与 `zh=False`（无汉字）互斥 |
| `chat.py` | 1645 | **疑似死代码**：同函数前部只要 `table_context` 非空就已 return，走不到这里（建议后续评估删除） |
| `research_lit.py` | 146-147 / 1470-1471 / 1598-1599 | `urlparse` 极端畸形串、`related` 外层兜底、Windows 上无法稳定构造的删除失败 |
| `research_lit.py` | 1533-1538 / 1555-1556 / 1579-1584 | 真实外网下载与 302 跟随，**按要求不测**；内部 `_download_pdf/_download_page` 已用 fake client 全分支覆盖 |
| `research_tables.py` | 剩余 ~108 行 | 多为对称分支（PDF/HTML 双通道同构）与防御性 `except`，已到 93.8% 远超线 |
| 前端 | 各行 1-7 行零散 | 数据形状兜底（`?? null`）与不可达的 `default` 分支；语句覆盖均 ≥92% |

### 12.8 顺手修掉的三类阻塞项（不修就进不了 CI）

1. **`vue-tsc --noEmit` 65 处类型错误**（全是新测试文件，非产品代码）：
   - `authMethod: 'password'` 不在 `AuthMethod` 联合（`phone-pass|phone-code|wechat|qq`）里 → 改 `'phone-pass'`；
   - `vi.fn(async () => …)` 无参导致 `mock.calls[0]` 是空元组，取 `[1]` 报错 → 显式断言成 `[string, RequestInit]`；
   - `todo.test.ts` 的任务样本缺类型 → 工厂返回 `TodoTask`（`patch` 仍放宽，便于造脏数据）。
2. **`eslint` 4 处 `prefer-const`**：`let [url, init]` 里 `init` 从不重赋值 → 拆成 `const first` + `let url`。
3. **`diagramLayout.test.ts` 的脏 kind**（`'geometria'`）→ 显式注解「故意绕过类型走运行期兜底」，而不是删掉用例。

### 12.9 CI 门槛

`--cov-fail-under` 由 **75 → 85**（实测后端 90%）：只防倒退，不当达标依据；
留 5pp 余量给重构与平台差异（Linux 上 posix 专属分支会多执行几行）。

### 12.10 需要 lead/后续会话决定的两件事（本轮只记录，未改产品代码）

1. `chat.py:1645` 疑似死代码（见 12.7），删不删由结构债评审决定。
2. `research_lit.py` 的真实下载链路（1533-1584）只做了 fake client 覆盖，
   **真机外网验证**仍未做 —— 与部署自检一样，属于"测试到此为止、交给真机"的部分。

401 清登录态并跳登录；另有 409/429 映射与二进制响应（`Content-Disposition` 缺失回退）。
