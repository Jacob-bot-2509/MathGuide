# 习题集生成历史与换一批 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在习题集面板内加入“换一批”和仅记录已导出文档的生成历史。

**Architecture:** SQLite 表保存生成时的完整文档快照；生成写 `draft`，前端下载成功后 `confirm` 为 `exported`。换一批用新 seed + `excludeIds` 在服务端抽样，池子不足时补回少量重复。

**Tech Stack:** Python 3.13 / Starlette / SQLite / pytest；Vue 3 + TypeScript / Vite。

**Spec:** `docs/superpowers/specs/2026-11-17-exercise-history-shuffle-design.md`

## Global Constraints

- 历史全部按 `uid` 隔离；任何读写都必须校验归属。
- 只返回 `status='exported'` 的条目；`draft` 不进入历史。
- 草稿保留 24 小时；已导出每用户最多 50 条 / 180 天。
- `excludeIds` 最多 200 个；非法/未知 ID 忽略。
- 生成数量上限 100，沿用现有 `MAX_COUNT`。
- 题库数据不提交；测试不得依赖 `backend/data` 真实题库。
- 写入历史失败不能让已生成的文档丢失；下载成功但 confirm 失败只提示，不回滚文件。

## Review Focus

- 用户 A 不能读取/删除用户 B 的历史（越权）。
- 只预览、不下载时历史必须为空（draft 不泄漏）。
- 题池不足时“换一批”仍返回请求数量，并给出 `reusedCount`。
- 下载成功后 confirm 失败：文件已下载，历史可能缺一条，不能报成生成失败。
- 注销账号后历史必须删除，不能留孤儿快照。

---

### Task 1: 历史存储层

**Files:**
- Modify: `backend/db.py`（SCHEMA 增加 `exercise_documents` 表）
- Create: `backend/exercise_history.py`
- Test: `backend/tests/test_exercise_history.py`

**Interfaces:**
- Produces:
  - `create_draft(uid: str, document: dict, filters: dict, seed: int, exclude_ids: list[str], lang: str, mode: str, title: str) -> str`
  - `confirm(uid: str, doc_id: str) -> bool`
  - `list_documents(uid: str, limit: int = 20) -> list[dict]`
  - `get_document(uid: str, doc_id: str) -> dict | None`
  - `delete_document(uid: str, doc_id: str) -> bool`
  - `delete_user(uid: str) -> None`
  - `_prune(conn, uid: str) -> None`

- [ ] **Step 1: 写失败测试**

`backend/tests/test_exercise_history.py`：

```python
import json
import pytest
import db
import exercise_history as history


@pytest.fixture()
def temp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "mathguide.db")
    db.init()
    yield
    db.reset_for_tests()


def test_draft_not_in_history_and_confirm_promotes(temp_db):
    doc_id = history.create_draft(
        "u1", {"title": "t", "sections": []}, {"topics": ["algebra"]},
        7, [], "zh", "solutions", "习题集 · 代数",
    )
    assert history.list_documents("u1") == []
    assert history.confirm("u1", doc_id) is True
    rows = history.list_documents("u1")
    assert [row["id"] for row in rows] == [doc_id]
    assert rows[0]["count"] == 0


def test_other_user_cannot_read_or_delete(temp_db):
    doc_id = history.create_draft(
        "u1", {"title": "t", "sections": []}, {}, 1, [], "zh", "questions", "t")
    history.confirm("u1", doc_id)
    assert history.get_document("u2", doc_id) is None
    assert history.delete_document("u2", doc_id) is False
    assert history.get_document("u1", doc_id) is not None


def test_delete_user_removes_all(temp_db):
    doc_id = history.create_draft(
        "u1", {"title": "t", "sections": []}, {}, 1, [], "zh", "questions", "t")
    history.confirm("u1", doc_id)
    history.delete_user("u1")
    assert history.list_documents("u1") == []
```

- [ ] **Step 2: 运行并确认失败**

Run: `python -m pytest backend/tests/test_exercise_history.py -v`
Expected: FAIL（`exercise_history` 不存在 / 表不存在）

- [ ] **Step 3: 建表并实现存储层**

在 `db.py` 的 `SCHEMA` 末尾加入：

```sql
CREATE TABLE IF NOT EXISTS exercise_documents (
    id          TEXT PRIMARY KEY,
    uid         TEXT NOT NULL,
    status      TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    exported_at TEXT,
    title       TEXT NOT NULL,
    lang        TEXT NOT NULL,
    mode        TEXT NOT NULL,
    item_count  INTEGER NOT NULL,
    seed        INTEGER NOT NULL,
    exclude_ids TEXT NOT NULL,
    filters     TEXT NOT NULL,
    document    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_exercise_docs_user
    ON exercise_documents(uid, status, created_at DESC);
```

`exercise_history.py` 用 `db.connect()`/`db.transaction()`，`id = secrets.token_hex(12)`，时间用 `datetime.now().astimezone().isoformat(timespec="seconds")`。`item_count = len(document.get("sections", []))` 不够，改为文档元数据里的题目数：优先 `document.get("exercise_meta", {}).get("count", 0)`。

`_prune` 每次写入后执行：
- 删除该 uid 超过 24h 的 draft；
- 已导出按 `created_at DESC` 保留 50 条，其余删除；
- 删除超过 180 天的已导出。

`list_documents` 只查 `status='exported'`，返回字段：`id,title,createdAt,exportedAt,count,lang,mode,filters`（filters 反序列化为 JSON 对象）。

- [ ] **Step 4: 运行测试**

Run: `python -m pytest backend/tests/test_exercise_history.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add backend/db.py backend/exercise_history.py backend/tests/test_exercise_history.py
git commit -m "feat: 习题集历史存储层"
```

---

### Task 2: 抽样排除与预览响应

**Files:**
- Modify: `backend/exercise_docgen.py:171-186`（`_select`）
- Modify: `backend/exercise_docgen.py:310-329`（`plan`）
- Test: `backend/tests/test_exercise_docgen.py`

**Interfaces:**
- Consumes: `ExerciseStore`
- Produces:
  - `_select(store, filters, lang, allow_partial, seed, exclude_ids=()) -> tuple[list[Exercise], int]`
  - plan 响应新增 `seed`, `preview`, `batchIds`, `reusedCount`

- [ ] **Step 1: 写失败测试**

在 `test_exercise_docgen.py` 加：

```python
def test_plan_excludes_previous_batch_and_reports_reuse():
    store = ExerciseStore([make(f"e{i}") for i in range(6)], tiers=("research",))
    filters = exercise_docgen._filters({"topics": ["analysis"], "count": 3})
    first, _ = exercise_docgen._select(store, filters, "zh", False, 1)
    ids = [item.id for item in first]
    second, reused = exercise_docgen._select(store, filters, "zh", False, 2, ids)
    assert len(second) == 3
    assert reused == 0
    assert not ({item.id for item in second} & set(ids))


def test_plan_reuses_when_pool_too_small():
    store = ExerciseStore([make(f"e{i}") for i in range(3)], tiers=("research",))
    filters = exercise_docgen._filters({"topics": ["analysis"], "count": 3})
    first, _ = exercise_docgen._select(store, filters, "zh", False, 1)
    ids = [item.id for item in first]
    second, reused = exercise_docgen._select(store, filters, "zh", False, 2, ids)
    assert len(second) == 3
    assert reused == 3
```

再给 `plan` 响应加断言（沿用现有 TestClient 写法）：

```python
def test_plan_response_contains_seed_preview_batch(client):
    response = client.post("/api/doc/exercise/plan", json={"count": 3, "lang": "zh"})
    body = response.json()
    assert isinstance(body["seed"], int)
    assert isinstance(body["batchIds"], list)
    assert len(body["preview"]) <= 3
    assert body["reusedCount"] == 0
```

- [ ] **Step 2: 运行并确认失败**

Run: `python -m pytest backend/tests/test_exercise_docgen.py -k "exclude or reuse or preview" -v`
Expected: FAIL

- [ ] **Step 3: 实现**

`_select` 改动：
- 新增参数 `exclude_ids: Iterable[str] = ()`。
- 候选先按现有语言/filters 过滤。
- 把候选分成 `fresh`（不在 exclude）和 `seen`（在 exclude）。
- `random.Random(seed).sample` 从 `fresh` 取；不足时从 `seen` 取，返回 `(selected, reused_count)`。
- `allow_partial` 的 `lang="any"` 兜底保留，但新加的题也要排除已选 ID。
- 所有调用点解包二元组。

`plan`：
- 读取 `exclude_ids = body.get("excludeIds", [])`，只保留字符串，截断 200。
- seed 从 body 读，默认 `20261106`。
- 调 `_select` 得到 `selected, reused`。
- 响应加：
  - `seed`
  - `batchIds = [item.id for item in selected]`
  - `preview = [{"id","topic","type","question"[:80]}]` 前 3 条
  - `reusedCount: reused`

- [ ] **Step 4: 运行测试**

Run: `python -m pytest backend/tests/test_exercise_docgen.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add backend/exercise_docgen.py backend/tests/test_exercise_docgen.py
git commit -m "feat: 习题集换批抽样与预览"
```

---

### Task 3: 生成草稿、确认与历史 API

**Files:**
- Modify: `backend/exercise_docgen.py`（`generate` 与新增 handlers）
- Modify: `backend/main.py:194-195`（注册路由）
- Modify: `backend/auth.py:510-519`（注销级联删除）
- Test: `backend/tests/test_exercise_docgen.py`, `backend/tests/test_exercise_history.py`

**Interfaces:**
- Consumes: Task 1 的 `exercise_history.*`；Task 2 的 `_select`
- Produces:
  - `generate` 响应新增 `draftId`
  - `history_list(request)`, `history_get(request)`, `history_delete(request)`, `history_confirm(request)`

- [ ] **Step 1: 写失败测试**

- generate 返回 `draftId`，且该 ID 初始不在历史列表。
- `POST /api/doc/exercise/history/{id}/confirm` 后列表出现。
- A 用户 confirm B 的 ID 返回 404。
- `GET /api/doc/exercise/history/{id}` 返回原 `document` 快照。
- `DELETE` 后列表消失。
- 注销账号后 `exercise_history.list_documents(uid)` 为空（用 monkeypatch 或直接调用 `delete_user`）。

- [ ] **Step 2: 运行并确认失败**

Run: `python -m pytest backend/tests/test_exercise_docgen.py -k history -v`
Expected: FAIL

- [ ] **Step 3: 实现**

`generate`：
- 读取 `excludeIds`，调 `_select`。
- 生成 `document` 后：
  ```python
  draft_id = exercise_history.create_draft(
      uid, document, filters, seed, exclude_ids, lang, mode,
      title=_history_title(filters, lang, len(selected)),
  )
  ```
- 响应加 `draftId`。写历史异常只打印，不阻断下载。

新增 handlers（全部 `require_auth` + `_rate_check`）：
- `history_list`: `GET /api/doc/exercise/history?limit=20`，`limit` 限 1–50。
- `history_get`: `GET /api/doc/exercise/history/{doc_id}`，返回 `{"id",...,"document"}`；不存在/非本人 404。
- `history_delete`: `DELETE`，返回 `{"ok": True}` 或 404。
- `history_confirm`: `POST .../confirm`，返回 `{"ok": True}`；非本人/不存在 404。

`main.py` 注册：
```python
Route("/api/doc/exercise/history", exercise_docgen.history_list),
Route("/api/doc/exercise/history/{doc_id}", exercise_docgen.history_get),
Route("/api/doc/exercise/history/{doc_id}", exercise_docgen.history_delete, methods=["DELETE"]),
Route("/api/doc/exercise/history/{doc_id}/confirm", exercise_docgen.history_confirm, methods=["POST"]),
```

`auth.delete_account` 在 `diagnosis.delete_user(uid)` 后：
```python
import exercise_history
exercise_history.delete_user(uid)
```

- [ ] **Step 4: 运行测试**

Run: `python -m pytest backend/tests/test_exercise_docgen.py backend/tests/test_exercise_history.py backend/tests/test_auth.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add backend/exercise_docgen.py backend/main.py backend/auth.py backend/tests/test_exercise_docgen.py backend/tests/test_exercise_history.py
git commit -m "feat: 习题集历史 API 与注销级联"
```

---

### Task 4: 前端服务与换批状态

**Files:**
- Modify: `frontend/src/services/docgenService.ts`
- Create: `frontend/src/utils/exerciseBatch.ts`
- Test: `frontend/scripts/` 新增纯函数测试（跟随现有 `run-tests.mjs` 风格）

**Interfaces:**
- Produces:
  - `ExercisePlan` 增加 `seed`, `preview`, `batchIds`, `reusedCount`
  - `ExerciseDocument` 增加 `draftId?: string`
  - `ExerciseHistoryItem`, `ExerciseHistoryDetail`
  - `confirmExerciseExport(id)`, `fetchExerciseHistory(limit?)`, `fetchExerciseHistoryDocument(id)`, `deleteExerciseHistory(id)`
  - `mergeExcludeIds(current: string[], batchIds: string[], limit = 200): string[]`
  - `nextShuffleSeed(previous: number): number`

- [ ] **Step 1: 写失败测试**

`frontend/scripts/exercise-batch-test.ts`：

```ts
import { mergeExcludeIds } from '../src/utils/exerciseBatch'

const merged = mergeExcludeIds(['a', 'b'], ['b', 'c', 'd'])
if (merged.join(',') !== 'a,b,c,d') throw new Error(`merge failed: ${merged}`)
const capped = mergeExcludeIds([], Array.from({ length: 250 }, (_, i) => `id${i}`), 200)
if (capped.length !== 200) throw new Error(`cap failed: ${capped.length}`)
console.log('exercise batch tests passed')
```

并把它接入 `frontend/scripts/run-tests.mjs` 的测试列表。

- [ ] **Step 2: 运行并确认失败**

Run: `cd frontend && npm test`
Expected: FAIL（模块不存在）

- [ ] **Step 3: 实现**

`exerciseBatch.ts`：
```ts
export function mergeExcludeIds(current: string[], batchIds: string[], limit = 200): string[] {
  const seen = new Set<string>()
  const out: string[] = []
  for (const id of [...current, ...batchIds]) {
    if (!id || seen.has(id)) continue
    seen.add(id)
    out.push(id)
    if (out.length >= limit) break
  }
  return out
}

export function nextShuffleSeed(previous: number): number {
  return (previous * 1103515245 + 12345) >>> 0
}
```

`docgenService.ts` 按 Interfaces 增加类型与函数；history 详情返回 `document`。

- [ ] **Step 4: 运行测试**

Run: `cd frontend && npm test`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add frontend/src/services/docgenService.ts frontend/src/utils/exerciseBatch.ts frontend/scripts/exercise-batch-test.ts frontend/scripts/run-tests.mjs
git commit -m "feat: 习题集换批前端状态与历史服务"
```

---

### Task 5: 习题集面板预览、换一批与历史 UI

**Files:**
- Modify: `frontend/src/components/chat/DocModal.vue`
- Modify: `frontend/src/utils/i18n.ts`
- Test: 手动 + `npm run build`

**Interfaces:**
- Consumes: Task 4 的 service 与 `exerciseBatch.ts`

- [ ] **Step 1: 增加状态与请求参数**

在 `DocModal.vue` 的 exercise 状态旁加：
```ts
const exerciseSeed = ref(20261106)
const exerciseExcludeIds = ref<string[]>([])
const exercisePreview = ref<ExercisePreviewItem[]>([])
const exerciseBatchIds = ref<string[]>([])
const exerciseReused = ref(0)
const history = ref<ExerciseHistoryItem[]>([])
const historyOpen = ref(false)
const historyBusy = ref('')
```

- `exerciseRequest()` 增加 `seed: exerciseSeed.value`、`excludeIds: exerciseExcludeIds.value`。
- 筛选 watch 里重置 `seed/excludeIds/preview/batchIds/reused`。
- `previewExercises()` 成功后写入 `preview/batchIds/reused/seed`。
- `shuffleExercises()`：
  ```ts
  exerciseExcludeIds.value = mergeExcludeIds(exerciseExcludeIds.value, exerciseBatchIds.value)
  exerciseSeed.value = nextShuffleSeed(exerciseSeed.value)
  previewExercises()
  ```

- [ ] **Step 2: 加界面**

在 exercise step 的预览区域：
- 显示前 3 题：题干截断 + 题型/板块。
- 按钮“换一批”，`busy` 时禁用。
- `reusedCount > 0` 时提示“题库余量不足，本批含 X 道重复题”。

历史区域放在生成按钮下方：
- 标题“生成历史”，点击展开。
- 每行：时间、标题、题数、语言/模式、下载、删除。
- 下载：`fetchExerciseHistoryDocument(id)` → `renderDocument(detail.document, detail.lang, format.value)` → `downloadBlob`。
- 删除：确认后 `deleteExerciseHistory(id)` 并刷新。

- [ ] **Step 3: 下载成功后确认**

`generateExercise()` 的 `downloadBlob` 之后：
```ts
if (result.draftId) {
  try { await confirmExerciseExport(result.draftId) } catch { /* 文件已下载,历史缺失只提示 */ }
}
await loadHistory()
```

进入 exercise step 时 `loadHistory()`。

- [ ] **Step 4: i18n**

新增键（中/英）：预览标题、换一批、重复提示、历史、历史为空、重新下载、删除历史、删除确认、历史加载失败。

- [ ] **Step 5: 构建与手动验收**

Run: `cd frontend && npm run build`
Expected: PASS

手动：
1. 预览 → 换一批 → 前 3 题变化。
2. 只预览不下载 → 历史为空。
3. 生成并下载 → 历史出现一条。
4. 从历史重新下载 → 文档与首次一致。
5. 删除 → 列表消失。

- [ ] **Step 6: 提交**

```bash
git add frontend/src/components/chat/DocModal.vue frontend/src/utils/i18n.ts
git commit -m "feat: 习题集面板换批与生成历史"
```

---

### Task 6: 收尾验证

**Files:**
- Modify: `docs/EXERCISE_BANK_STATUS.md`（补充历史/换批说明）
- Test: 全量

- [ ] **Step 1: 后端全量**

Run: `cd backend && python -m pytest tests/ -q`
Expected: PASS

- [ ] **Step 2: 前端全量**

Run: `cd frontend && npm run build && npm test`
Expected: PASS

- [ ] **Step 3: 数据不进入 git**

Run: `git status --short`
Expected: 无 `backend/data`、无 `.env.local`

- [ ] **Step 4: 提交**

```bash
git add docs/EXERCISE_BANK_STATUS.md
git commit -m "docs: 习题集历史与换批说明"
```
