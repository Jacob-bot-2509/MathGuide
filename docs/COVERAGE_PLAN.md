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

## 3. 后端逐文件台账（94 个文件）

> 现状 = 本次实跑；缺口行来自 coverage.json 的 `missing_lines`，`…` 表示还有更多段。
> 判定只针对该文件自己，与项目总数无关。

### A · 认证 / 凭据 / 数据写入 —— 合格线 90%（13 个文件，未达标 1）

| 文件 | 语句 | 现状 | 判定 | 缺行数 | 缺口行 |
| --- | ---: | ---: | --- | ---: | --- |
| `db.py` | 109 | 83.5% | ❌ 差 6.5pp | 18 | 85–88, 91–93, 128–129 … |
| `config.py` | 81 | 90.1% | ✅ 达标 | 8 | 20–27 |
| `store.py` | 324 | 91.0% | ✅ 达标 | 29 | 51–52, 54, 90 … |
| `auth.py` | 293 | 92.8% | ✅ 达标 | 21 | 111–112, 163, 165 … |
| `usage.py` | 220 | 93.6% | ✅ 达标 | 14 | 36–37, 39, 49–50 … |
| `session_cache.py` | 84 | 96.4% | ✅ 达标 | 3 | 102, 115, 123 |
| `origin_guard.py` | 39 | 97.4% | ✅ 达标 | 1 | 35 |
| `rate_limit.py` | 46 | 97.8% | ✅ 达标 | 1 | 73 |
| `log.py` | 46 | 100.0% | ✅ 达标 | 0 | — |
| `http_utils.py` | 36 | 100.0% | ✅ 达标 | 0 | — |
| `profile.py` | 30 | 100.0% | ✅ 达标 | 0 | — |
| `security_headers.py` | 23 | 100.0% | ✅ 达标 | 0 | — |
| `quota.py` | 10 | 100.0% | ✅ 达标 | 0 | — |

### B · 计算 / 格式 / 渲染 —— 合格线 85%（11 个文件，未达标 6）

| 文件 | 语句 | 现状 | 判定 | 缺行数 | 缺口行 |
| --- | ---: | ---: | --- | ---: | --- |
| `analysis_regression.py` | 125 | 0.0% | ❌ 差 85.0pp | 125 | 2, 4–5, 7–8 … |
| `analysis_client.py` | 67 | 23.9% | ❌ 差 61.1pp | 51 | 12–15, 17, 28–38 … |
| `analysis_worker.py` | 44 | 43.2% | ❌ 差 41.8pp | 25 | 19, 27–28, 30 … |
| `research_formats.py` | 336 | 67.9% | ❌ 差 17.1pp | 108 | 36, 38–55, 57–61 … |
| `math_table_render.py` | 59 | 81.4% | ❌ 差 3.6pp | 11 | 39–40, 42, 46 … |
| `linear_algebra.py` | 1274 | 83.9% | ❌ 差 1.1pp | 205 | 59–60, 62, 72 … |
| `math_render.py` | 239 | 90.4% | ✅ 达标 | 23 | 49, 51, 53 … |
| `graph_layout.py` | 52 | 96.2% | ✅ 达标 | 2 | 36–37 |
| `diagram_taxonomy.py` | 51 | 100.0% | ✅ 达标 | 0 | — |
| `diagram_metrics.py` | 50 | 100.0% | ✅ 达标 | 0 | — |
| `analysis_capabilities.py` | 5 | 100.0% | ✅ 达标 | 0 | — |

### C · 检索与对话主链路 —— 合格线 80%（13 个文件，未达标 7）

| 文件 | 语句 | 现状 | 判定 | 缺行数 | 缺口行 |
| --- | ---: | ---: | --- | ---: | --- |
| `rag/research/__init__.py` | 108 | 45.4% | ❌ 差 34.6pp | 59 | 73–74, 116, 121–129 … |
| `rag/research/sources.py` | 188 | 46.8% | ❌ 差 33.2pp | 100 | 45, 49, 65 … |
| `rag/research/synthesize.py` | 27 | 48.1% | ❌ 差 31.9pp | 14 | 42–44, 54–55, 57 … |
| `rag/research/rerank.py` | 56 | 55.4% | ❌ 差 24.6pp | 25 | 25–29, 31, 63–67 … |
| `rag/llm.py` | 96 | 57.3% | ❌ 差 22.7pp | 41 | 69, 112–116, 121–126 … |
| `rag/route.py` | 15 | 60.0% | ❌ 差 20.0pp | 6 | 36, 45–49 |
| `rag/__init__.py` | 101 | 74.3% | ❌ 差 5.7pp | 26 | 40, 43, 71–73 … |
| `rag/embed.py` | 98 | 86.7% | ✅ 达标 | 13 | 56, 100–101, 109–110 … |
| `rag/index.py` | 106 | 87.7% | ✅ 达标 | 13 | 66, 147, 157–161 … |
| `rag/documents.py` | 110 | 93.6% | ✅ 达标 | 7 | 67, 71, 77–78 … |
| `knowledge_graph/__init__.py` | 128 | 95.3% | ✅ 达标 | 6 | 110–111, 113, 117 … |
| `rag/research/rank.py` | 47 | 95.7% | ✅ 达标 | 2 | 53, 75 |
| `rag/research/types.py` | 23 | 95.7% | ✅ 达标 | 1 | 34 |

### D · 科研工作台 —— 合格线 80%（27 个文件，未达标 9）

| 文件 | 语句 | 现状 | 判定 | 缺行数 | 缺口行 |
| --- | ---: | ---: | --- | ---: | --- |
| `diagram_alerts.py` | 47 | 42.6% | ❌ 差 37.4pp | 27 | 24–27, 48–52, 54–59 … |
| `research_vision.py` | 399 | 52.1% | ❌ 差 27.9pp | 191 | 70, 79–80, 84–85 … |
| `chat.py` | 869 | 52.2% | ❌ 差 27.8pp | 415 | 152, 156–157, 159–161 … |
| `research_compare.py` | 133 | 60.2% | ❌ 差 19.8pp | 53 | 48–55, 59–61, 65 … |
| `research_lit.py` | 1005 | 65.4% | ❌ 差 14.6pp | 348 | 123, 146–147, 149 … |
| `research_papers.py` | 218 | 70.2% | ❌ 差 9.8pp | 65 | 62–65, 84–87, 101–105 … |
| `research_fulltext.py` | 230 | 71.3% | ❌ 差 8.7pp | 66 | 50–51, 105, 118 … |
| `research_urls.py` | 60 | 75.0% | ❌ 差 5.0pp | 15 | 24–25, 39, 52–53 … |
| `research_tables.py` | 1296 | 77.3% | ❌ 差 2.7pp | 294 | 77, 98–99, 108–109 … |
| `research_corpus.py` | 1572 | 80.3% | ✅ 达标 | 309 | 101, 110, 119 … |
| `research_actions.py` | 189 | 80.4% | ✅ 达标 | 37 | 70–71, 77–78, 89 … |
| `research_oa.py` | 89 | 83.1% | ✅ 达标 | 15 | 24–25, 36, 51 … |
| `diagnosis.py` | 184 | 84.8% | ✅ 达标 | 28 | 68–69, 71, 96–97 … |
| `research_diagrams.py` | 1552 | 86.5% | ✅ 达标 | 209 | 71, 74, 82 … |
| `chat_prompts.py` | 17 | 88.2% | ✅ 达标 | 2 | 69, 78 |
| `research_legacy.py` | 77 | 88.3% | ✅ 达标 | 9 | 21, 27, 30 … |
| `learning_analysis.py` | 164 | 88.4% | ✅ 达标 | 19 | 366, 368, 373 … |
| `chat_routing.py` | 126 | 90.5% | ✅ 达标 | 12 | 154, 156, 158 … |
| `recommendation.py` | 63 | 90.5% | ✅ 达标 | 6 | 45–46, 94, 100 … |
| `research_report.py` | 165 | 91.5% | ✅ 达标 | 14 | 94, 97–98, 105 … |
| `research_sources.py` | 33 | 93.9% | ✅ 达标 | 2 | 100–101 |
| `ebbinghaus.py` | 36 | 94.4% | ✅ 达标 | 2 | 22, 33 |
| `research_venues.py` | 61 | 95.1% | ✅ 达标 | 3 | 38, 72, 82 |
| `chat_sse.py` | 41 | 95.1% | ✅ 达标 | 2 | 31–32 |
| `dashboard_data.py` | 29 | 96.6% | ✅ 达标 | 1 | 79 |
| `graph_api.py` | 53 | 100.0% | ✅ 达标 | 0 | — |
| `retention.py` | 37 | 100.0% | ✅ 达标 | 0 | — |

### E · 文档生成与导出 —— 合格线 80%（3 个文件，未达标 3）

| 文件 | 语句 | 现状 | 判定 | 缺行数 | 缺口行 |
| --- | ---: | ---: | --- | ---: | --- |
| `doc.py` | 201 | 72.6% | ❌ 差 7.4pp | 55 | 53, 63, 67 … |
| `docgen.py` | 393 | 78.6% | ❌ 差 1.4pp | 84 | 83, 169–173, 179–180 … |
| `exercise_docgen.py` | 203 | 78.8% | ❌ 差 1.2pp | 43 | 80, 82, 98–106 … |

### F · 题库 —— 合格线 80%（16 个文件，未达标 1）

| 文件 | 语句 | 现状 | 判定 | 缺行数 | 缺口行 |
| --- | ---: | ---: | --- | ---: | --- |
| `exercises/build.py` | 78 | 75.6% | ❌ 差 4.4pp | 19 | 66, 114, 116 … |
| `exercises/importers/numinamath.py` | 42 | 81.0% | ✅ 达标 | 8 | 64, 70, 72 … |
| `exercises/importers/olympiadbench.py` | 39 | 82.1% | ✅ 达标 | 7 | 56, 72, 90–94 |
| `exercises/source_repairs.py` | 28 | 82.1% | ✅ 达标 | 5 | 18, 24, 29 … |
| `exercises/translate.py` | 225 | 82.7% | ✅ 达标 | 39 | 102–104, 157, 162 … |
| `exercises/importers/math_dataset.py` | 51 | 84.3% | ✅ 达标 | 8 | 41, 56, 61 … |
| `exercises/importers/common.py` | 56 | 87.5% | ✅ 达标 | 7 | 62, 68, 76 … |
| `exercises/schema.py` | 171 | 88.9% | ✅ 达标 | 19 | 136, 142, 144 … |
| `exercises/importers/kuttler.py` | 62 | 90.3% | ✅ 达标 | 6 | 54, 95, 98 … |
| `exercises/store.py` | 114 | 92.1% | ✅ 达标 | 9 | 44–45, 92, 95 … |
| `exercises/dedupe.py` | 65 | 93.8% | ✅ 达标 | 4 | 28, 36, 39 … |
| `exercises/gate.py` | 117 | 94.0% | ✅ 达标 | 7 | 83, 88, 90 … |
| `exercises/taxonomy.py` | 25 | 96.0% | ✅ 达标 | 1 | 84 |
| `exercises/tagging.py` | 17 | 100.0% | ✅ 达标 | 0 | — |
| `exercises/importers/__init__.py` | 4 | 100.0% | ✅ 达标 | 0 | — |
| `exercises/__init__.py` | 3 | 100.0% | ✅ 达标 | 0 | — |

### G · 装配与入口 —— 合格线 90%（1 个文件，未达标 1）

| 文件 | 语句 | 现状 | 判定 | 缺行数 | 缺口行 |
| --- | ---: | ---: | --- | ---: | --- |
| `main.py` | 80 | 0.0% | ❌ 差 90.0pp | 80 | 26, 31–32, 34–36 … |

### H · 评测工具 —— 合格线 80%（7 个文件，未达标 1）

| 文件 | 语句 | 现状 | 判定 | 缺行数 | 缺口行 |
| --- | ---: | ---: | --- | ---: | --- |
| `evaluation/judges.py` | 77 | 77.9% | ❌ 差 2.1pp | 17 | 46–49, 55–56, 59 … |
| `evaluation/datasets.py` | 55 | 83.6% | ✅ 达标 | 9 | 39, 45, 48 … |
| `evaluation/extract.py` | 132 | 87.1% | ✅ 达标 | 17 | 20–21, 32–33, 47–48 … |
| `evaluation/metrics.py` | 124 | 93.5% | ✅ 达标 | 8 | 59, 63, 139–143 … |
| `evaluation/report.py` | 42 | 100.0% | ✅ 达标 | 0 | — |
| `evaluation/types.py` | 29 | 100.0% | ✅ 达标 | 0 | — |
| `evaluation/__init__.py` | 0 | 100.0% | ✅ 达标 | 0 | — |

### 归入 omit（不进分母，不写测试）

| 文件 | 语句 | 现状 | 不测的理由 |
| --- | ---: | ---: | --- |
| `evaluation/runner.py` | 119 | 0.0% | 评测跑批入口,需真实模型与网络 |
| `exercises/fetch.py` | 58 | 0.0% | 从 HuggingFace 拉原始数据,离线数据脚本 |
| `dev_reload.py` | 51 | 0.0% | 开发期热重载守护,运行时不在线上 |

## 4. 前端逐文件台账（55 个文件）

> 统计范围 = `src/utils` / `src/stores` / `src/services`（`vitest.config.ts` 的 `coverage.include`）。
> 组件与模板不在范围内，理由见第 2 节。

### U · utils 纯函数（node 环境即可测） —— 合格线 80%（34 个文件，未达标 25）

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

### S · stores 状态与持久化 —— 合格线 70%（8 个文件，未达标 7）

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

### V · services 接口层（需 stub fetch） —— 合格线 60%（13 个文件，未达标 13）

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


