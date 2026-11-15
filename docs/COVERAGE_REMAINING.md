# 覆盖率剩余工作草稿（54 个文件）

> **2026-11-14 更新：全部收口。** 本文列出的 54 个文件已全部达标（后端 13 + 前端 41），
> 实测与逐文件记录见 [`COVERAGE_PLAN.md`](COVERAGE_PLAN.md) §12。
> 本文保留作为「当时怎么拆、按什么顺序做」的原始工单，不再有未完成项。
> **2026-11-15（v1.26.1）：基线为后端 1506 passed / 89.89%**，下方 1504 / 90% 是收口当轮快照。
> **2026-11-15（部署前收口轮）：最新基线 1537 passed / 90.06%**（16291 语句），+31 条用例见 `COVERAGE_PLAN.md` §2。
> **2026-11-15（部署工具轮）：1577 passed / 90.06%**，+40 条（`tools/` 不进覆盖率分母，百分比不变）。

日期：2026-11-14 ｜ 基线：`6916e04` ｜ 配套：[覆盖率方案](COVERAGE_PLAN.md)（定线规则与台账）

现状（2026-11-15，部署工具轮）：**后端 1577 passed，总覆盖 90.06%**；前端 vitest 51 文件 1021 条，覆盖 97.7%。
达标 **146 / 146**；剩余 **0**。

> 这份草稿只回答两件事：**还剩什么**、**每个怎么补**。
> 验收口径仍按 `COVERAGE_PLAN.md` §2 —— 单文件达到它所属类别的线，不看总百分比。

---

## 组 G1 · 小 rag（2 个文件，缺口 ~67 行）—— 我可独立完成

| 文件 | 现状 | 线 | 缺口 | 解法 |
| --- | ---: | ---: | ---: | --- |
| `rag/__init__.py` | 74.3% | 80 | 26 行 | 读 `is_math_question` / `search` 的早退分支（空查询、未初始化索引、top-k 截断），用现有 fixture 语料直接打 |
| `rag/llm.py` | 57.3% | 80 | 41 行 | **纯错误映射**：`resolve()` 找不到角色、`stream_chat` 的 401/429/超时/空响应、`fallback` 切 backup 的条件。全部用假 client，不出网 |

要点：这两个文件是检索链路的入口，判错的表现是"检索静默返回空"而不是报错。

## 组 G2 · research 中等（5 个文件，缺口 ~390 行）—— 我可独立完成

| 文件 | 现状 | 线 | 缺口 | 解法 |
| --- | ---: | ---: | ---: | --- |
| `research_formats.py` | 67.9% | 85 | 108 行 | 六种格式 × (魔数 / 扩展名冲突) × 损坏文件；`_split_long` 边界；`_sections` 无标题文档。现有 `test_research_formats.py` 可扩展 |
| `rag/research/sources.py` | 46.8% | 80 | 100 行 | 每个源的字段归一化（缺字段/类型错/重复合并）+ 聚合层（单源失败不影响其余）。用录制的响应片段 |
| `research_compare.py` | 60.2% | 80 | 53 行 | 全部抽取失败(502) / 部分失败 / 字段缺失 / 空选择 |
| `research_papers.py` | 70.2% | 80 | 65 行 | 临时论文的下载失败(502)、非 PDF 拒绝、重复导入 |
| `research_fulltext.py` | 71.3% | 80 | 66 行 | 无全文时的降级、许可不允许、OA 链接不可解析 |

## 组 G3 · research 大件（4 个文件，缺口 ~1248 行）—— 需按端点分批，最慢

| 文件 | 现状 | 线 | 缺口 | 解法 |
| --- | ---: | ---: | ---: | --- |
| `chat.py` | 52.2% | 80 | 415 行 | **只补决策分支**：`_route_chat` 的 deep/main/backup 选择、闲聊直答、澄清、复核三态与"更正块"、图解校验回退。不补提示词常量 |
| `research_lit.py` | 65.4% | 80 | 348 行 | 纯映射先做（查询构造/归一化/去重/许可与撤稿标记），网络部分用 JSON fixture 补 429/超时/畸形 |
| `research_tables.py` | 77.3% | 80 | 294 行 | 逐个端点补未覆盖分支：`/compute` 表达式非法、`/stats` 空表、`/regression` 样本不足、`/validate-formula` 不匹配 |
| `research_vision.py` | 52.1% | 80 | 191 行 | fake httpx：请求体构造、401/429/5xx、超时、返回缺字段/非 JSON |

## 组 G4 · 需要 Chromium（1 个文件，部分不可本地完成）

| 文件 | 现状 | 线 | 缺口 | 解法 |
| --- | ---: | ---: | ---: | --- |
| `doc.py` | 72.6% | 80 | 55 行 | 其中 **350–392 是 `render_pdf_bytes`**（依赖 Chromium 打印）。本机没有 Chromium → 只能：① 桩掉 `_html_to_pdf` 验前置逻辑；② 或在 CI 装 chromium 后跑真渲染。**建议：桩掉前置 + 把真实渲染留给 CI 冒烟** |

## 组 G5 · 前端大字（8 个文件，缺口 ~2100 语句）—— 占前端未覆盖一半以上

| 文件 | 语句 | 现状 | 解法 |
| --- | ---: | ---: | --- |
| `utils/geogebraSpec.ts` | 483 | 0% | 纯解析/构造：spec 校验、命令拼装、非法输入。**node 环境即可测**，不需要 three.js |
| `utils/diagramSpec.ts` | 345 | 9% | `parseDiagramSpec` 的畸形 JSON、缺字段、未知 kind、版本迁移（已有 diagram-test.ts 可迁移） |
| `utils/diagramLabels.ts` | 329 | 1.5% | 标签排布纯几何：碰撞、边界、空标签 |
| `utils/diagramLayout.ts` | 245 | 1.6% | 布局纯函数：分列、缩放、视口裁剪 |
| `utils/mathArrays.ts` | 192 | 0% | KaTeX 不支持的列规则 → HTML 表格：井号/`\multicolumn`/`\hline`/`@{}` |
| `utils/geogebra3dSpec.ts` | 192 | 0% | 同 geogebraSpec（3D 变体） |
| `utils/mathIsolation.ts` | 175 | 12% | 公式隔离与切分：行内/块级、转义、不闭合 |
| `utils/speechMath.ts` | 166 | 7% | 语音转写：数字/符号映射、大小写归一、缓存读写 |

## 组 G6 · 前端中字（~10 个文件）

`paperActions`(83, 3.6%) `graphLayout`(68, 0%) `avatar`(42, 2.4%) `fileText`(17, 5.9%)
`aboutContent`(12, 0%) `tex2svg`(15, 0%) `fulltextAccess`(24, 0%) `cmdLink` 已达标
＋ stores：`settings` `researchScope` `todo` `trash` `notebook` `localData`（多为 localStorage 逻辑，stub 即可）

## 组 G7 · 前端 services（13 个，全部未达标）

`accountService` `authService`(18.8%) `chatService` `researchService` `docService`
`diagramService` `literatureService` `researchTableService` `settingsService` …
解法统一：**stub `fetch`，断言请求构造（URL/方法/体）与错误映射（401/404/409/429）**，
`authService.test.ts` 已有范例，可复制。

---

## 执行顺序（按"缺口 ÷ 需要读的代码量"排）

1. **G1**（67 行 / 2 文件）→ 预计 2 小时内，可立即做
2. **G2**（390 行 / 5 文件）→ 1 天，零网络
3. **G7 + G6 小件**（前端 13+7 文件）→ 1.5 天，模式化
4. **G5**（前端大字 8 个）→ 2–3 天，纯函数为主但体量大
5. **G3**（后端大件 4 个）→ 4–5 天，最大块
6. **G4**（doc 的 Chromium 段）→ 与 CI 一起做

## 本机不可完成 / 需替代方案

| 项 | 原因 | 替代 |
| --- | --- | --- |
| `doc.render_pdf_bytes`(43 行) | 依赖 Chromium | 桩掉前置 + CI 装 chromium 做真渲染冒烟 |
| `research_lit` / `research_vision` 的实网分支 | 无 API key + 不出网 | 录制 JSON fixture；真实链路留给真机验证 |
| 会话轮换、语音输入全链路 | 需真时间/真麦克风 | 已有单测覆盖（`COVERAGE_PLAN.md` §0.1 已标注） |

## 验收（每组做完都要过）

1. `pytest --cov=<module> --cov-report=term-missing` 单文件 ≥ 类别线；
2. 主要公开函数至少被调用一次；
3. **改坏验证**：挑一条断言，把被测分支改坏，测试必须变红；
4. `ruff check .` 全绿、全量 `pytest -q` 无回归；
5. 在 `COVERAGE_PLAN.md` §11 追加一行记录（之前→之后 / 测试文件 / 改坏验证）。

---

## 附:执行工单(五大组,可机械照做)

> 现状数值取自首次全量统计(2026-11-14)。**开工前先刷新**:重跑一次 coverage,把下表"现状"换成实测值,
> 否则你会对着过时数字干活(`COVERAGE_PLAN.md` §3/§4 的台账同理)。
> 每个文件都走同一套三步:① 取缺口行 ② 写测试 ③ 验收+记录。

### 通用三步(复制即用)

```powershell
# ① 取缺口行(把 <模块> 换成文件名去扩展名,如 research_formats)
cd backend; & 'D:\Works\code\.venv\Scripts\python.exe' -m pytest -q --cov=<模块> --cov-report=term-missing
# ② 写测试:tests/test_<模块>.py(已有同名文件的就追加,不要新建重复文件)
# ③ 验收:单文件达标 + 改坏验证 + 全量绿 + ruff + 在 COVERAGE_PLAN §11 记一行
cd backend; & 'D:\Works\code\.venv\Scripts\ruff.exe' check .
```

### G2 · research 中等(5 个,零网络,建议先做)

| 文件 | 现状 | 线 | 缺行 | 新建/追加测试 | 首批断言要点 |
| --- | ---: | ---: | ---: | --- | --- |
| `research_formats.py` | 67.9% | 85 | 108 | 追加 `test_research_formats.py` | `_detect_format` 六格式 + 扩展名/魔数冲突;`_split_long` 边界;`_sections` 无标题文档 |
| `rag/research/sources.py` | 46.8% | 80 | 100 | 新建 | 每个源的字段归一化(缺失/类型错/重复合并);单源失败不影响其余 |
| `research_compare.py` | 60.2% | 80 | 53 | 追加 `test_research_compare_report.py` | 全失败 502 / 部分失败 / 字段缺失 / 空选择 |
| `research_papers.py` | 70.2% | 80 | 65 | 追加 `test_research_papers.py` | 临时论文下载失败 502、非 PDF 拒绝、重复导入 |
| `research_fulltext.py` | 71.3% | 80 | 66 | 追加 `test_research_fulltext.py` | 无全文降级、许可不允许、OA 链接不可解析 |

### G3 · research 大件(4 个,最慢)

| 文件 | 现状 | 线 | 缺行 | 策略 |
| --- | ---: | ---: | ---: | --- |
| `chat.py` | 52.2% | 80 | 415 | **只补决策分支**:`_route_chat` 选型、闲聊直答、澄清、复核三态、图解校验回退。**不补提示词常量** |
| `research_lit.py` | 65.4% | 80 | 348 | 先做纯映射(查询构造/归一化/去重/许可与撤稿标记),网络部分用 JSON fixture 补 429/超时/畸形 |
| `research_tables.py` | 77.3% | 80 | 294 | 逐端点补未覆盖分支:`/compute` 非法表达式、`/stats` 空表、`/regression` 样本不足、`/validate-formula` 不匹配 |
| `research_vision.py` | 52.1% | 80 | 191 | fake httpx:请求体、401/429/5xx、超时、缺字段、非 JSON |

### G5 · 前端大字(8 个,纯函数,node 环境)

| 文件 | 语句 | 现状 | 线 | 测试文件 |
| --- | ---: | ---: | ---: | --- |
| `utils/geogebraSpec.ts` | 483 | 0% | 80 | `src/utils/geogebraSpec.test.ts` |
| `utils/diagramSpec.ts` | 345 | 9% | 80 | `src/utils/diagramSpec.test.ts` |
| `utils/diagramLabels.ts` | 329 | 1.5% | 80 | `src/utils/diagramLabels.test.ts` |
| `utils/diagramLayout.ts` | 245 | 1.6% | 80 | `src/utils/diagramLayout.test.ts` |
| `utils/mathArrays.ts` | 192 | 0% | 80 | `src/utils/mathArrays.test.ts` |
| `utils/geogebra3dSpec.ts` | 192 | 0% | 80 | 与 geogebraSpec 同文件或独立 |
| `utils/mathIsolation.ts` | 175 | 12% | 80 | `src/utils/mathIsolation.test.ts` |
| `utils/speechMath.ts` | 166 | 7% | 80 | `src/utils/speechMath.test.ts` |

> 全部可在 `// @vitest-environment node`(默认)下测,不需要 happy-dom;`speechMath` 涉及 localStorage 时自行 stub(`authService.test.ts` 有范例)。

### G6 · 前端中字 + stores(约 10 个)

顺序按语句数:`paperActions`(83) → `graphLayout`(68) → `avatar`(42) → `fileText`(17) → `aboutContent`(12) →
`tex2svg`(15) → `fulltextAccess`(24),然后 stores:`settings` `researchScope` `todo` `trash` `notebook` `localData`(线 70)。

### G7 · 前端 services(13 个,线 60)

统一套路:**stub `fetch`,断言请求构造(URL/方法/body)与错误映射(401/404/409/429)**。
范例照抄 `src/services/authService.test.ts`(已有 4 条,含 stub 写法)。

### 验收记录模板(每个文件都填)

```
- [x] <文件>  之前% → 之后%  tests/<测试文件>(N 条)
      改坏验证:把 <某分支> 改坏 → <用例名> 变红 ✅
```

**红线**:不写只调用不断言的测试;不为凑数测工具脚本;`pragma: no cover` 只用于真不可达;
难测是设计耦合 → 记结构债,不改产品代码。