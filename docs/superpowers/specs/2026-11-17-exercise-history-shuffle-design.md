# 习题集：生成历史与换一批（设计）

日期：2026-11-17
状态：待确认

## 1. 目标

在文档生成 → 习题集面板内增加：

1. **生成历史**：记录用户实际导出的习题集；只预览不导出不进历史。
2. **换一批**：预览阶段可以换一整批题；同一用户尽量不与上一批重复，池子不足时允许少量重复；不同用户之间不做排除。

## 2. 非目标

- 不做跨用户去重
- 不做历史版本管理/回收站
- 不改变题库内容与质量门
- 不做服务端长期保存用户下载文件

## 3. 现有链路

- 前端 `DocModal.vue`：`previewExercises()` 调 `/api/doc/exercise/plan`，只返回可用数量；`generateExercise()` 调 `/api/doc/exercise`，再用 `/api/doc/render` 下载。
- 后端 `exercise_docgen.py`：`plan`/`generate` 均接受 `seed`，用 `ExerciseStore.sample()` 选固定数量；当前不返回具体题目 ID，也没有排除列表。
- 历史与草稿存储尚无；`db.py` 已有 SQLite 与账户级级联删除机制。

## 4. 方案选择

### 4.1 历史存储

- **A. 服务端 SQLite + 完整文档快照（选定）**：原样重现历史文档；跨设备；可级联删除。
- B. 只存生成参数：轻，但题库/翻译变化后重下会变样。
- C. localStorage：无需后端，但换设备丢失、快照大、无法可靠清理。

### 4.2 换一批

- **A. seed + excludeIds（选定）**：前端保存本批 ID，新 seed 请求排除上一批；池子不足时补重复。
- B. 服务端批次游标：有状态，并发与过期复杂。
- C. 纯新 seed：实现最简单，但不保证少重复。

## 5. 数据模型

新增 SQLite 表 `exercise_documents`：

```sql
CREATE TABLE IF NOT EXISTS exercise_documents (
  id TEXT PRIMARY KEY,
  uid TEXT NOT NULL,
  status TEXT NOT NULL,              -- draft | exported
  created_at TEXT NOT NULL,
  exported_at TEXT,
  title TEXT NOT NULL,
  lang TEXT NOT NULL,
  mode TEXT NOT NULL,
  item_count INTEGER NOT NULL,
  seed INTEGER NOT NULL,
  exclude_ids TEXT NOT NULL,         -- JSON 数组
  filters TEXT NOT NULL,             -- JSON：topics/crossTopics/types/difficulty
  document TEXT NOT NULL             -- 完整 StructuredDocument 快照
);
CREATE INDEX IF NOT EXISTS idx_exercise_docs_user
  ON exercise_documents(uid, status, created_at DESC);
```

- 生成成功即写 `draft`（含快照）。
- 前端下载成功后调 `confirm`，状态改为 `exported` 并写 `exported_at`。
- 历史列表只返回 `exported`；`draft` 24 小时后清理。
- 每用户最多保留 50 条已导出；超出删除最旧。
- 注销账号时级联删除。

## 6. API

### 6.1 预览

`POST /api/doc/exercise/plan`

新增可选字段：

```json
{
  "excludeIds": ["id1", "id2"],
  "seed": 20261117
}
```

响应新增：

```json
{
  "seed": 20261117,
  "preview": [
    {"id": "...", "topic": "algebra", "type": "compute", "question": "前 80 字..."}
  ],
  "batchIds": ["..."],
  "reusedCount": 0
}
```

- `batchIds` 是本批完整 ID，前端保存用于下一次换批排除。
- `preview` 只取前 3–5 题用于面板展示。
- `reusedCount` 表示因池子不足补回的重复题数。

### 6.2 生成

`POST /api/doc/exercise`

新增 `excludeIds`，沿用 `seed`；响应新增 `draftId`。

### 6.3 历史

- `POST /api/doc/exercise/history/{id}/confirm`：标记导出成功。
- `GET /api/doc/exercise/history?limit=20`：已导出列表，不含全文。
- `GET /api/doc/exercise/history/{id}`：取完整快照，用于重新下载。
- `DELETE /api/doc/exercise/history/{id}`：删除。

全部要求登录，并校验 `uid` 归属。

## 7. 抽样规则

```text
base = filter(当前条件)
fresh = base 中排除 excludeIds
if len(fresh) >= count: sample(fresh, seed, count)
else: 取全部 fresh，再从 excludeIds 命中项里 sample 补满
```

- `excludeIds` 只由前端传，服务端限制最多 200 个。
- 同 seed + 同条件 + 同 excludeIds 必然得到同一批。
- 不同用户之间不共享排除列表。

## 8. 界面

习题集面板内：

- **预览区**：显示本批前 3 题、数量、`reusedCount` 提示（如有重复）。
- **换一批**：生成新 seed，`excludeIds = batchIds`，重新调 `plan`。
- **历史**：折叠列表，位于生成按钮下方；显示时间、板块摘要、题数、语言/模式、下载、删除。
- 下载成功后自动 `confirm` 并刷新历史；失败只提示，不影响已下载文件。
- 筛选条件变化时重置 seed、excludeIds、preview。

## 9. 测试

后端：

- draft 不进入历史；confirm 后进入。
- 用户隔离：A 不能读/删 B 的历史。
- 注销账号级联删除。
- 换批：足够池子零重复；不足时 `reusedCount > 0` 且数量补满。
- 同 seed 可复现。
- 快照重新下载与首次文档一致。

前端：

- 预览 → 换一批 → batchIds 更新。
- 只预览不下载不产生历史。
- 下载成功后才出现历史条目。

## 10. 保留策略

- 草稿：24 小时。
- 已导出：每用户 50 条 / 180 天，先到者为准。
- 清理在写入新记录时顺带执行，不额外起定时任务。
