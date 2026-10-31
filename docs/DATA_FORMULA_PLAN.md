# MathGuide 数据表公式提取与彻底清除执行方案

日期：2026-10-31
状态：实施版方案
范围：公式提取与数据/计算列判定；整页上下文；手写/印刷区分；表格主题命名；彻底清除与缓存治理
不在本版：校园图书馆/CARSI；付费墙；自动写入未确认的公式结果

## 1. 目标

### 1.1 公式提取

- 支持整页截图或论文页面：正文、公式、表格、手写、图注一起解析。
- 模型只负责识别、候选与映射；数值计算仍由服务端 `Decimal`/SymPy 执行。
- 能判断表格列角色：实测数据、计算结果、标识列、单位列、备注列。
- 能从资料中提取公式并匹配到表格列，给出候选与置信度。
- 说明齐全时自动映射并计算；说明缺失、冲突或多义时才询问用户。
- 支持手写/印刷区块标记；低置信度手写必须确认。
- 表格主题明确时自动命名；不确定时留空，不硬编。

### 1.2 彻底清除

- 用户可选择“彻底清除”，跳过回收站，删除论文、批注、结构缓存、公式解析、截图裁剪、向量缓存与索引。
- 删除后数据库文件可回收空间；缓存不再占用磁盘。
- 普通删除保留现有回收站语义；彻底清除不可恢复。

## 2. 现状与缺口

已有：

- `backend/research_vision.py`
  - `extract_formulas(images, columns)`：最多 4 张图，输出 `formulas/groups/master`，含 `variableMap` 建议。
  - `extract_table(mime, data)`：论文表格截图 → 结构化表格。
  - 视觉模型只做识别，不做计算。
- `backend/research_tables.py`
  - 表结构：`columns_json / rows_json / formulas_json / source_json / row_sources_json`。
  - Excel 风格公式（`=A2*B2`），白名单 AST，`Decimal` 计算，四位小数。
- `frontend/src/views/ResearchTablesView.vue`
  - 已有公式栏与“从图片提取公式”入口。
- `backend/research_corpus.py`
  - `docs / nodes / chunks / annotations / doc_insights`；`_delete` 已能删行与文件并弹内存索引。
  - 临时论文回收站 30 天，`purge_expired_history` 到期清理。

缺口：

1. 公式提取只吃图片，不吃整页文字；没有上下文卡、变量定义、适用对象。
2. 公式没有持久化公式库；每次重提取，无法去重、溯源、复用。
3. 没有列角色推断；没有“实测/计算”标记。
4. 没有公式-列映射的多候选排序与反算验证。
5. 没有手写/印刷区块标记。
6. 没有表格主题自动命名。
7. 删除只清当前表与文件；未来的公式库、截图裁剪、OCR 缓存没有级联。
8. 没有缓存占用统计、TTL、LRU、SQLite 空间回收。
9. 没有“彻底清除”接口与前端确认。

## 3. 总体架构

```text
上传整页图片/论文页
  → 版面分块
      printed_text | printed_formula | printed_table | handwriting | figure
  → 公式块转 LaTeX + 变量 + 上下文卡
  → 公式库（规范化、去重、来源、置信度）
  → 表格列角色推断
  → 公式-列候选映射（Top-3）
  → 反算/量纲验证
  → 自动采用 | 用户确认 | 放弃
  → 生成 Excel 公式并交给现有 Decimal 引擎
  → 结果、来源、映射审计
```

删除链路：

```text
普通删除 → 回收站（temp 30 天；正式论文按现有行为）
彻底清除 → 事务删 DB 行 → 删文件/裁剪/OCR → 清内存索引与缓存
        → VACUUM / wal_checkpoint → 审计记录
```

## 4. 数据模型

### 4.1 来源区块

```sql
CREATE TABLE source_blocks(
  id TEXT PRIMARY KEY,
  doc_id TEXT NOT NULL,
  page INTEGER NOT NULL,
  kind TEXT NOT NULL,          -- printed_text | printed_formula | printed_table | handwriting | figure
  bbox_json TEXT NOT NULL DEFAULT '[]',
  text TEXT NOT NULL DEFAULT '',
  latex TEXT NOT NULL DEFAULT '',
  confidence REAL NOT NULL DEFAULT 0,
  asset_path TEXT NOT NULL DEFAULT '',  -- 裁剪图相对路径
  created_at REAL NOT NULL
);
CREATE INDEX idx_source_blocks_doc ON source_blocks(doc_id);
```

### 4.2 公式库

```sql
CREATE TABLE formulas(
  id TEXT PRIMARY KEY,
  doc_id TEXT NOT NULL,
  source_block_id TEXT,
  latex TEXT NOT NULL,
  ast_json TEXT NOT NULL DEFAULT '{}',
  variables_json TEXT NOT NULL DEFAULT '[]',
  units_json TEXT NOT NULL DEFAULT '{}',
  conditions TEXT NOT NULL DEFAULT '',
  confidence REAL NOT NULL DEFAULT 0,
  status TEXT NOT NULL DEFAULT 'candidate', -- candidate | confirmed | rejected
  created_at REAL NOT NULL
);
CREATE INDEX idx_formulas_doc ON formulas(doc_id);
```

### 4.3 公式-表格映射

```sql
CREATE TABLE formula_links(
  id TEXT PRIMARY KEY,
  formula_id TEXT NOT NULL,
  table_id TEXT NOT NULL,
  column_key TEXT NOT NULL,
  mapping_json TEXT NOT NULL DEFAULT '{}',
  confidence REAL NOT NULL DEFAULT 0,
  confirmed INTEGER NOT NULL DEFAULT 0,
  created_at REAL NOT NULL
);
```

### 4.4 表格扩展

`tables` 新增：

```sql
ALTER TABLE tables ADD COLUMN topic TEXT NOT NULL DEFAULT '';
ALTER TABLE tables ADD COLUMN topic_confidence REAL NOT NULL DEFAULT 0;
```

`columns_json` 每列允许：

```json
{
  "key": "C",
  "label": "速度",
  "unit": "m/s",
  "role": "measured | calculated | identifier | unit | note",
  "formulaId": "f_xxx",
  "mapping": {"位移": "A", "时间": "B"},
  "confidence": 0.93,
  "confirmed": true
}
```

兼容：旧表没有这些字段时按 `role=unknown` 处理，不改变现有读写。

### 4.5 派生资产

```text
backend/data/research/<uid>/derived/<doc_id>/
  crops/<block_id>.png
  pages/<page>.json
  formulas/<formula_id>.tex
```

彻底清除时整目录删除。

## 5. API

### 5.1 公式分析

`POST /api/research/formulas/analyze`

```json
{
  "docId": "可选，已有论文",
  "page": 3,
  "images": [{"mime": "image/png", "data": "..."}],
  "tableId": "可选，当前表",
  "columns": [{"key":"A","label":"位移","unit":"m"}],
  "text": "可选，整页文字；缺省从 docId/page 取"
}
```

返回：

```json
{
  "blocks": [{"kind":"printed_formula","latex":"v=d/t","confidence":0.95}],
  "formulas": [{"id":"f1","latex":"v=d/t","variables":["d","t"],
                "units":{"v":"m/s"},"conditions":"","confidence":0.93}],
  "warnings": []
}
```

规则：

- `text` 与 `images` 同时存在时，用文字补变量定义与适用对象；
- 不要把整页所有文字直接塞进一次提示词；按区块与检索片段组合；
- 同一公式规范化后去重；
- 所有结果先落 `formulas`，状态 `candidate`。

### 5.2 表格分析

`POST /api/research/formulas/match`

```json
{
  "tableId": "t1",
  "docIds": ["d1"],
  "autoApply": false
}
```

返回：

```json
{
  "topic": {"title":"自由落体实验","confidence":0.88},
  "columns": [{"key":"C","role":"calculated","confidence":0.91,
               "candidateFormulaId":"f1","mapping":{"速度":"C","位移":"A","时间":"B"}}],
  "candidates": [{"formulaId":"f1","columnKey":"C","score":0.91,"reason":"变量与单位一致"}],
  "needsUser": false
}
```

判定顺序：

1. 列名/单位/表头语义；
2. 变量映射；
3. 量纲检查；
4. 反算：用候选公式计算，与已有数值在容差内比较；
5. 目标列为空且变量全部匹配 → 计算列候选；
6. 多候选冲突 → `needsUser=true`。

### 5.3 应用公式

`POST /api/research/tables/{id}/apply-formula`

```json
{"columnKey":"C","formulaId":"f1","mapping":{"速度":"C","位移":"A","时间":"B"}}
```

- 生成 `=A2/B2` 形式，交给现有 `research_tables.compute`；
- 先返回预览值，不写库；
- 用户确认后再 `POST /api/research/tables/{id}` 保存；
- 保存时记录 `formulaId` 与映射。

### 5.4 彻底清除

```text
DELETE /api/research/docs/{doc_id}?hard=1
DELETE /api/research/history/{doc_id}?hard=1
POST   /api/research/cache/purge
GET    /api/research/storage
```

`hard=1`：

1. 校验文档归属；
2. 事务内删 `doc_insights / source_blocks / formulas / formula_links / chunks / nodes / annotations / docs`；
3. 提交后删 `files/` 与 `derived/<doc_id>/`；
4. `_indexes.pop(uid)`、`_index_paths.pop(uid)`；
5. 清该用户相关检索缓存键；
6. 异步 `VACUUM`/`wal_checkpoint`（每用户限频）；
7. 写审计日志（仅 uid、docId、时间、结果）。

## 6. 公式与数据判定规则

### 6.1 自动采用条件

同时满足才自动：

- 单组公式或明确对应当前表；
- 变量定义齐全，映射唯一；
- 单位/量纲一致；
- 目标列为空，或反算结果与已有值在容差内；
- 公式转写置信度 ≥ 0.85；
- 非低质量手写。

### 6.2 必须询问

- 多组公式/多个实验对象；
- 变量重复或含义冲突；
- 单位缺失或冲突；
- 目标列不明确，反算失败；
- 手写置信度低；
- 正文与表格矛盾。

### 6.3 手写/印刷

- 视觉模型对每个区块输出 `kind` + `confidence`；
- 低置信度区块标“待确认”，不参与自动计算；
- 手写公式即使识别成功，默认不自动套用，用户可确认；
- 保留原图裁剪，前端可对照。

### 6.4 表格主题

- 从文档标题、章节标题、表题、首行/列名推断；
- 置信度 ≥ 0.8 且表名为空时自动填；
- 否则留空，可手动命名；
- 上限 20–40 字，禁止把整段说明当标题。

## 7. 彻底清除与缓存治理

### 7.1 缓存清单

- 内存索引：`research_corpus._indexes`、`_index_paths`；
- 文档结构：`doc_insights`；
- 计划新增：`source_blocks`、`formulas`、`formula_links`、裁剪图、页面 JSON；
- 检索缓存：`research_lit._SEARCH_CACHE`、`research_oa._CACHE`；
- 向量缓存：按文档键的 embedding；
- SQLite WAL 与空闲页；
- 前端会话/本地草稿中引用已删 docId 的条目。

### 7.2 自动治理

- 每用户派生资产上限（例如 2GB）与 TTL（例如 90 天）；
- 未确认的 candidate 公式 30 天清理；
- 无引用的裁剪图随公式/文档删除；
- 内存索引 LRU；
- 每日低频 `VACUUM`，硬删后按需 `VACUUM`；
- 设置页显示占用：论文、派生资产、数据库、缓存。

### 7.3 前端交互

- 删除菜单拆为“删除”和“彻底清除”；
- 彻底清除二次确认，列明范围与不可恢复；
- 危险按钮独立样式，不与普通删除混用；
- 清除后刷新论文列表、数据表来源、公式库；
- 设置页显示“清理缓存”和占用统计。

## 8. 分阶段实施

### P0：基线审计（0.5–1 天）

- 盘点现有缓存与删除路径；
- 为 `_delete` 增加级联测试；
- 加存储占用统计骨架。

### P1：彻底清除与缓存治理（2–3 天）

- 新增 `hard=1` 参数与 `purge_doc`；
- 级联 `doc_insights`、文件、派生目录；
- 弹内存索引与检索缓存；
- `VACUUM` 限频；
- 前端删除菜单与确认弹窗；
- 测试：删后无行、无文件、无索引、搜索不可见。

### P2：来源区块与公式库（3–5 天）

- 新增 `source_blocks`、`formulas`、`formula_links` 表；
- 整页图片+文字分析接口；
- 公式 LaTeX/AST 归一化、去重、置信度；
- 裁剪图落盘与来源回跳；
- 手写/印刷区块标签；
- 测试：公式转录、去重、来源。

### P3：表格列角色与公式匹配（3–5 天）

- 列角色推断；
- 公式候选 Top-3；
- 变量映射与量纲检查；
- 反算验证；
- 自动采用/询问策略；
- 主题命名；
- 前端公式面板、映射编辑器、来源预览。

### P4：计算闭环与评测（2–3 天）

- `apply-formula` 生成 Excel 公式；
- 预览计算、确认保存；
- 计算公式与映射落库；
- 金标准集与指标评测；
- 回归现有数据表、统计、导出。

## 9. 测试与验收

### 9.1 自动化

- 彻底清除：数据库行、文件、派生资产、内存索引、缓存键；
- 公式：LaTeX 解析、AST 等价、重复公式合并；
- 列角色：实测/计算/标识/单位；
- 映射：多候选排序、单位冲突、反算容差；
- 主题：高置信自动、低置信留空；
- 计算：与现有 `research_tables.compute` 一致。

### 9.2 指标

- 公式转写精确率 / AST 等价率；
- 公式 Top-1 / Top-3 命中率；
- 列角色准确率；
- 反算通过率；
- 计算值与人工值误差；
- `false_auto_rate`（错误自动采用率），目标接近 0；
- 彻底清除后残留引用数，目标 0；
- 每用户磁盘占用下降。

### 9.3 金标准样本

- 印刷整页：公式 + 表格 + 变量说明；
- 只有公式截图；
- 手写公式/手写数据；
- 多实验、多表格同页；
- 单位缺失/冲突；
- 同一公式多种写法。

## 10. 风险与对策

| 风险 | 对策 |
| --- | --- |
| 视觉模型误读公式 | LaTeX 解析 + 渲染预览 + 低置信确认 |
| 整页文字噪声 | 按区块/段落检索，不整页硬塞 |
| 公式多解 | Top-3 候选，反算验证，必要时询问 |
| 手写误判 | 置信度 + 原图对照 + 不自动计算 |
| 自动命名错误 | 高阈值自动，否则留空 |
| 硬删残留 | 级联测试、审计、VACUUM、缓存清单 |
| VACUUM 阻塞 | 后台任务 + 每用户限频 |
| 删除影响数据表来源 | 删除前检查 `formula_links`/`row_sources`，提示受影响表 |

## 11. 文件级任务清单

新增：

```text
backend/research_formulas.py        # 公式库、归一化、匹配、反算
backend/research_blocks.py          # 源区块与派生资产
backend/tests/test_formulas.py
backend/tests/test_purge.py
frontend/src/components/research/FormulaPanel.vue
frontend/src/components/research/FormulaMapDialog.vue
frontend/src/components/research/SourceBlockPreview.vue
docs/DATA_FORMULA_PLAN.md
```

修改：

```text
backend/research_vision.py          # 整页/区块/手写标签/上下文
backend/research_tables.py          # 列角色、主题、公式生成、apply
backend/research_corpus.py          # 级联清除、缓存、VACUUM
backend/main.py                     # 新接口与 hard 参数
frontend/src/views/ResearchTablesView.vue
frontend/src/services/researchTableService.ts
frontend/src/services/researchService.ts
frontend/src/utils/i18n.ts
```

## 12. 完成标准

- 整页上传后，能自动识别公式、表格、正文、手写区块；
- 有明确变量说明时自动映射并计算；说明不足时只给候选；
- 不出现无依据的自动计算；
- 表格主题只在明确时自动生成；
- 彻底清除后无数据库行、无文件、无派生资产、无内存索引、无缓存引用；
- 删除后磁盘占用可下降；
- 现有数据表、统计、导出、检索链路全部回归通过。

## 13. 实现进度（2026-10-31）

已完成：

- 数据表/论文/历史彻底清除：`hard=1`、派生目录、内存索引、WAL checkpoint、`VACUUM`。
- 公式库：`formulas` 表、去重、变量映射、单位、手写标记；按 doc/table 查询与复用。
- 整页区块解析：正文/公式/表格/手写/图注，`source_blocks` 按页入库并可替换。
- 公式候选 Top-3、反算校验、单位冲突提示、高置信采用与批量应用。
- 列角色推断：目标计算、引用实测、编号/样本标识。
- 表格主题建议：模型生成短主题，置信度 ≥ 0.7 才采用。
- 手写实验数据导入询问、手写公式确认。
- 设置 → 隐私：科研存储占用与内存缓存清理。
- 金标准：`tools/eval_table_formula.py`，5 类样本全部通过。

待补：

- 真实整页/手写/多表样本金标准。
- 多公式依赖组与批量应用的更复杂场景。
- 部署前并发压测与成本上限。
- 自动采用策略在真实数据上的误采用率评测。
