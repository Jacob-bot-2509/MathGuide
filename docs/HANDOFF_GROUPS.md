# 覆盖率剩余工作 · 交接表(2026-11-14)

> 数据来自 `pytest --cov=. --cov-report=json`（开工基线 1195 passed）。项目合计当时 **95/146 达标，51 未达标**。
>
> **2026-11-14 收口：本表 10 + 41 个文件已全部达标（146/146）**，逐文件的「之前→之后 / 测试文件 / 改坏验证」
> 记录见 [`COVERAGE_PLAN.md`](COVERAGE_PLAN.md) §12。本表保留作分组与解法的原始说明。

## 后端（10 个）—— ✅ 已全部达标

| # | 组 | 文件 | 开工现状 | 收口后 |
| ---: | --- | --- | ---: | ---: |
| 1 | G2 | `research_formats.py` | 67.9% | 100.0% |
| 2 | G2 | `rag/research/sources.py` | 46.8% | 100.0% |
| 3 | G2 | `research_papers.py` | 70.2% | 99.5% |
| 4 | G2 | `research_fulltext.py` | 71.3% | 99.6% |
| 5 | G2 | `research_compare.py` | 60.2% | 99.2% |
| 6 | G3 | `chat.py` | 52.2% | 99.5% |
| 7 | G3 | `research_lit.py` | 65.4% | 98.2% |
| 8 | G3 | `research_tables.py` | 77.3% | 93.8% |
| 9 | G3 | `research_vision.py` | 52.1% | 99.2% |
| 10 | — | `rag/research/__init__.py` | 45.4% | 100.0% |

> 下表的「一句话做法」仍是各组实际做法，可直接对照测试文件阅读。

| # | 组 | 文件 | 语句 | 现状 | 线 | 缺行 | 建议测试文件 | 一句话做法 |
| ---: | --- | --- | ---: | ---: | ---: | ---: | --- | --- |
| 1 | G2 | `research_formats.py` | 336 | 67.9% | **85** | 108 | 追加 `test_research_formats.py` | `_detect_format` 六格式 + 扩展名/魔数冲突;`_split_long` 边界;`_sections` 无标题文档 |
| 2 | G2 | `rag/research/sources.py` | 188 | 46.8% | 80 | 100 | 新建 `test_research_sources_fields.py` | 每源字段归一化(缺失/类型错/重复合并);单源失败不影响其余 |
| 3 | G2 | `research_papers.py` | 218 | 70.2% | 80 | 65 | 追加 `test_research_papers.py` | 临时论文下载失败 502、非 PDF 拒绝、重复导入 |
| 4 | G2 | `research_fulltext.py` | 230 | 71.3% | 80 | 66 | 追加 `test_research_fulltext.py` | 无全文降级、许可不允许、OA 链接不可解析 |
| 5 | G2 | `research_compare.py` | 133 | 60.2% | 80 | 53 | 追加 `test_research_compare_report.py` | 全失败 502 / 部分失败 / 字段缺失 / 空选择 |
| 6 | G3 | `chat.py` | 869 | 52.2% | 80 | 415 | 新建 `test_chat_routing_branches.py` | **只补决策分支**:路由选型、闲聊直答、澄清、复核三态、图解校验回退;不补提示词常量 |
| 7 | G3 | `research_lit.py` | 1005 | 65.4% | 80 | 348 | 追加 `test_research_lit.py` | 先做纯映射(查询构造/归一化/去重/许可与撤稿);网络部分用 JSON fixture 补 429/超时/畸形 |
| 8 | G3 | `research_tables.py` | 1296 | 77.3% | 80 | 294 | 追加 `test_research_tables.py` | 逐端点补未覆盖分支:`/compute` 非法表达式、`/stats` 空表、`/regression` 样本不足、`/validate-formula` 不匹配 |
| 9 | G3 | `research_vision.py` | 399 | 52.1% | 80 | 191 | 追加 `test_research_vision.py` | fake httpx:请求体、401/429/5xx、超时、缺字段、非 JSON |
| 10 | — | `rag/research/__init__.py` | 108 | 45.4% | 80 | 59 | 新建 `test_research_pipeline.py` | 四路编排:研究意图→检索→精排→综合;单源失败、空结果、降级直答 |

## 前端（41 个，线：utils 80 / stores 70 / services 60）—— ✅ 已全部达标

> 收口后全量 `vitest run --coverage`：51 文件 / 1021 条全过，总覆盖 **97.70%**（开工 12.34%）。
> 每个文件的最低值：utils 92.85（mathBlocks）、stores 97（sessions）、services 81.94（chatService）。

| 组 | 文件(语句数) | 做法 |
| --- | --- | --- |
| G5 | `geogebraSpec`(483) `diagramSpec`(345) `diagramLabels`(329) `diagramLayout`(245) `mathArrays`(192) `geogebra3dSpec`(192) `mathIsolation`(175) `speechMath`(166) | 全是纯函数,node 环境即可。每文件 6–10 条:畸形 JSON / 缺字段 / 未知 kind / 边界值;`speechMath` 涉及 localStorage 时自行 stub |
| G6 | `paperActions`(83) `graphLayout`(68) `avatar`(42) `fulltextAccess`(24) `fileText`(17) `tex2svg`(15) `aboutContent`(12) + stores `settings` `researchScope` `todo` `trash` `notebook` `localData` | 按语句数降序;stores 线 70,主要测 localStorage 读写与默认值回退 |
| G7 | `accountService` `chatService` `researchService` `docService` `diagramService` `literatureService` `researchTableService` `authService`(18.8%) 等 13 个 | 统一套路:stub `fetch`,断言请求构造(URL/方法/body)与错误映射(401/404/409/429);照抄 `src/services/authService.test.ts` |

## 建议执行顺序（已完成，保留作复盘）

1. ~~**G2 五个**（零网络，一天量级）→ 后端未达标 10 → 5~~ ✅
2. ~~**`rag/research/__init__.py`**（59 行，补齐 C 类）→ 4~~ ✅
3. ~~**G3 `chat.py`**（只补决策分支，别碰提示词）→ 3~~ ✅
4. ~~**G3 其余三个**（lit/vision/tables，fixture + 假 httpx）~~ ✅
5. ~~**G7 → G6 → G5**（前端，模式化，先 services 后纯函数大字）~~ ✅

> 实际做法：六组并行、每组只碰自己的文件；lead 统一跑全量 + lint + 类型检查，
> 并修掉新测试引入的 65 处 `vue-tsc` 类型错误与 4 处 `prefer-const`（产品代码零改动）。

## 红线(不变)

不写只调用不断言的测试;不为凑数测工具脚本;`pragma: no cover` 只用于真不可达;
难测是设计耦合 → 记结构债,不改产品代码。