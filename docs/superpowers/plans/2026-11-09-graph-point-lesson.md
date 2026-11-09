# 知识图谱知识点主要内容与“前往讲解”闭环 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 图谱详情页展示每个知识点的主要内容与重点注意点，用户点“前往”后进入学习辅助，模型先讲主干与注意点，再继续回答后续问题。

**Architecture:** 知识点摘要存为 `point_notes.json`，由 `knowledge_graph` 加载并附到 `KnowledgePoint`；`/api/graph` 随节点返回 `summary` / `keyPoints`。图谱详情页在“前置知识”和“后续知识”之间渲染内容块与“前往”按钮。跳转使用 `/learn?point=<id>&start=1`，聊天页消费一次后清掉 query，并把 `pointId` 作为会话级上下文随每次请求发送。后端“知识点讲解”指令用预置摘要与要点生成首轮讲解；后续追问把同一份内容作为高优先级合成资料注入普通问答。

**Tech Stack:** Python 3 / Starlette / SQLite / pytest；Vue 3 / TypeScript / Vite / vue-router。

**Spec:** `docs/knowledge-point-notes-draft.md`（80 条内容草稿，审核通过后作为数据源）。本计划同时落实该草稿的导入契约与界面/聊天闭环。

## Global Constraints

- 内容必须覆盖 CSV 中全部 80 个知识点 id，不得新增、改名或遗漏；id 以 `backend/knowledge_graph/data/knowledge_points.csv` 为准。
- 每条 `summary` 为 2–3 句中文；`keyPoints` 为 3–4 条中文；只写概念、条件、方法与常见错误，不展开例题。
- 内容审核通过前不导入 `point_notes.json`；草稿文件 `docs/knowledge-point-notes-draft.md` 是审核对象。
- `point_notes.json` 是纯数据文件，不引入新依赖；未知 id、非字符串 summary、非字符串数组 keyPoints 一律在加载时报 `KnowledgeGraphError`。
- 缺失摘要必须可降级：图谱显示“暂无摘要”，聊天仍可进入，后端不得崩溃。
- 讲解命令只属于学习辅助；科学研究工作区不得触发。
- 首轮讲解只输出“主干 + 重点注意点”，不展开例题，不输出图解标记；后续追问走正常问答。
- 讲解不得自动改写掌握度或诊断记录。
- 深链 `start=1` 只消费一次；刷新或返回不得重复发送讲解请求。
- 前端沿用现有面板、按钮与 i18n 风格；中英文文案同时补齐。

## Review Focus

- URL 里的 `point` 不存在或笔记缺失：图谱按钮仍可点，聊天给出明确提示，不白屏。
- 用户刷新 `/learn?point=...&start=1`：不得重复创建讲解会话或重复请求。
- 用户在讲解后追问“再讲讲第二步”：后续请求必须仍带该知识点的摘要与要点。
- 科学研究工作区收到 `pointId` 或 `知识点讲解`：必须忽略，不改变科研链路。
- 80 条内容 ids 与 CSV 完全一致，无重复；笔记文件的 JSON 结构在导入时校验。

---

### Task 1: 知识点笔记数据与加载校验

**Files:**
- Create: `backend/knowledge_graph/data/point_notes.json`（审核后由草稿导入）
- Modify: `backend/knowledge_graph/__init__.py`
- Test: `backend/tests/test_knowledge_graph.py`

**Interfaces:**
- Produces: `KnowledgePoint(id, name, chapter, difficulty, prerequisites, summary="", key_points=())`
- Produces: `load_graph(path=DEFAULT_CSV, notes_path=DEFAULT_NOTES) -> KnowledgeGraph`
- Notes JSON shape:

```json
{
  "set-map": {
    "summary": "集合的表示、包含与运算……",
    "keyPoints": ["映射要求每个原像有唯一像。", "逆映射存在要求双射。"]
  }
}
```

- [ ] **Step 1: Write failing loader tests**

Add to `backend/tests/test_knowledge_graph.py`:

```python
def test_loads_point_notes(tmp_path):
    notes = tmp_path / "notes.json"
    notes.write_text(
        '{"set-map": {"summary": "摘要A", "keyPoints": ["要点1", "要点2"]}}',
        encoding="utf-8")
    graph = load_graph(notes_path=notes)
    assert graph.points["set-map"].summary == "摘要A"
    assert graph.points["set-map"].key_points == ("要点1", "要点2")


def test_rejects_unknown_note_id(tmp_path):
    notes = tmp_path / "notes.json"
    notes.write_text('{"missing": {"summary": "x", "keyPoints": []}}', encoding="utf-8")
    with pytest.raises(KnowledgeGraphError, match="笔记.*不存在"):
        load_graph(notes_path=notes)


def test_rejects_bad_note_shape(tmp_path):
    notes = tmp_path / "notes.json"
    notes.write_text('{"set-map": {"summary": 1, "keyPoints": "x"}}', encoding="utf-8")
    with pytest.raises(KnowledgeGraphError):
        load_graph(notes_path=notes)


def test_missing_notes_file_keeps_empty_content(tmp_path):
    graph = load_graph(notes_path=tmp_path / "absent.json")
    assert graph.points["set-map"].summary == ""
    assert graph.points["set-map"].key_points == ()
```

Use a small CSV fixture if the existing tests already have one; otherwise write the same three columns used by current tests.

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && ../.venv/Scripts/python.exe -m pytest tests/test_knowledge_graph.py -q`
Expected: FAIL because `KnowledgePoint` has no `summary`/`key_points`, or `load_graph` rejects `notes_path`.

- [ ] **Step 3: Implement notes loading**

In `backend/knowledge_graph/__init__.py`:
- Add `import json`, `DEFAULT_NOTES = Path(__file__).resolve().parent / "data" / "point_notes.json"`.
- Extend `KnowledgePoint` with `summary: str = ""` and `key_points: tuple[str, ...] = ()`.
- In `load_graph`, read notes before constructing points:
  - If `notes_path` exists, `json.loads`; must be a dict.
  - For each key: must be an existing CSV id, else `KnowledgeGraphError(f"{path.name}: 笔记引用了不存在的知识点: {key}")`.
  - `summary` must be `str`; `keyPoints` must be a list of `str`; trim, cap summary at 800 chars and each point at 200 chars.
  - Attach to the matching `KnowledgePoint`.
- Missing notes file: all points get empty content, no error.
- Add a `note_text(point)` helper only if needed by Task 5; otherwise keep formatting in chat.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && ../.venv/Scripts/python.exe -m pytest tests/test_knowledge_graph.py -q`
Expected: PASS.

- [ ] **Step 5: Import approved draft**

After the user approves `docs/knowledge-point-notes-draft.md`, generate `point_notes.json` with exactly 80 keys. Verify:

```bash
cd backend
../.venv/Scripts/python.exe - <<'PY'
import json
from pathlib import Path
csv_ids = [line.split(',')[0] for line in Path('knowledge_graph/data/knowledge_points.csv').read_text(encoding='utf-8-sig').splitlines()[1:] if line.strip()]
notes = json.loads(Path('knowledge_graph/data/point_notes.json').read_text(encoding='utf-8'))
assert sorted(csv_ids) == sorted(notes), (len(csv_ids), len(notes))
assert all(n['summary'].strip() and n['keyPoints'] for n in notes.values())
print('notes ok:', len(notes))
PY
```

- [ ] **Step 6: Commit**

```bash
git add backend/knowledge_graph/__init__.py backend/knowledge_graph/data/point_notes.json backend/tests/test_knowledge_graph.py docs/knowledge-point-notes-draft.md
git commit -m "feat: add knowledge point notes data and loader"
```

---

### Task 2: Graph API 返回主要内容

**Files:**
- Modify: `backend/graph_api.py`
- Test: `backend/tests/test_graph_api.py`

**Interfaces:**
- Consumes: `KnowledgePoint.summary`, `KnowledgePoint.key_points` from Task 1.
- Produces: `/api/graph` node fields `summary: string`, `keyPoints: string[]`.

- [ ] **Step 1: Write failing API test**

In `backend/tests/test_graph_api.py`, using the existing authenticated client fixture, assert the first node contains:

```python
assert "summary" in node
assert isinstance(node["summary"], str)
assert isinstance(node["keyPoints"], list)
```

Also assert `len(node["keyPoints"]) == len(graph.points[node["id"]].key_points)`.

- [ ] **Step 2: Run it to verify it fails**

Run: `cd backend && ../.venv/Scripts/python.exe -m pytest tests/test_graph_api.py -q`
Expected: FAIL with missing `summary`/`keyPoints`.

- [ ] **Step 3: Add fields**

In `graph_api.graph_data`, add to each node dict:

```python
"summary": point.summary,
"keyPoints": list(point.key_points),
```

Do not change edges, coordinates, mastery or export behavior.

- [ ] **Step 4: Run tests**

Run: `cd backend && ../.venv/Scripts/python.exe -m pytest tests/test_graph_api.py tests/test_knowledge_graph.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/graph_api.py backend/tests/test_graph_api.py
git commit -m "feat: expose knowledge point notes in graph API"
```

---

### Task 3: 图谱详情页“主要内容”与“前往”

**Files:**
- Modify: `frontend/src/services/graphService.ts`
- Modify: `frontend/src/views/GraphView.vue`
- Modify: `frontend/src/utils/i18n.ts`
- Test: `cd frontend && npx vue-tsc --noEmit && npm run build`

**Interfaces:**
- Consumes: `GraphNode.summary?: string`, `GraphNode.keyPoints?: string[]` from Task 2.
- Produces: `goLearn(node: GraphNode)` → `router.push({ path: '/learn', query: { point: node.id, name: node.name, start: '1' } })`.

- [ ] **Step 1: Add TypeScript fields**

In `graphService.ts` `GraphNode`:

```ts
summary?: string
keyPoints?: string[]
```

- [ ] **Step 2: Add the detail block**

In `GraphView.vue`, between the “前置知识” and “后续知识” sections:

```vue
<section>
  <h3>{{ t('graph.mainContent') }}</h3>
  <p v-if="selected.summary" class="summary">{{ selected.summary }}</p>
  <ul v-if="selected.keyPoints?.length" class="key-points">
    <li v-for="item in selected.keyPoints" :key="item">{{ item }}</li>
  </ul>
  <p v-else-if="!selected.summary" class="none">{{ t('graph.noSummary') }}</p>
  <button class="go-learn" @click="goLearn(selected)">{{ t('graph.goLearn') }}</button>
</section>
```

Add `goLearn` in script:

```ts
function goLearn(node: GraphNode) {
  router.push({
    path: '/learn',
    query: { point: node.id, name: node.name, start: '1' },
  })
}
```

Add scoped styles for `.summary`, `.key-points`, `.go-learn` consistent with `.detail` (no new colors beyond tokens).

- [ ] **Step 3: Add i18n keys**

Chinese and English:
- `graph.mainContent`: 主要内容 / Main content
- `graph.noSummary`: 暂无摘要，前往让 MG 讲解 / No summary yet; open Learn to have MG explain
- `graph.goLearn`: 前往 / Go to Learn

- [ ] **Step 4: Verify**

Run: `cd frontend && npx vue-tsc --noEmit && npm run build`
Expected: both pass.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/services/graphService.ts frontend/src/views/GraphView.vue frontend/src/utils/i18n.ts
git commit -m "feat: show point notes and go-to-learn action in graph detail"
```

---

### Task 4: 学习辅助消费深链并保持会话级知识点上下文

**Files:**
- Modify: `frontend/src/api/types.ts`
- Modify: `frontend/src/services/chatService.ts`
- Modify: `frontend/src/stores/sessions.ts`
- Modify: `frontend/src/components/chat/ChatWorkspace.vue`
- Modify: `frontend/src/utils/i18n.ts`
- Test: `cd frontend && npx vue-tsc --noEmit && npm test`

**Interfaces:**
- Consumes: query `point`, `name`, `start` from Task 3.
- Produces: `ChatRequest.pointId?: string`; `ChatMeta.pointId?: string`; `ChatSession.pointId?: string`.
- Produces: `send(text?: string, cmd?: string, extra?: { pointId?: string })`.

- [ ] **Step 1: Extend types**

- `ChatRequest`: add `pointId?: string`.
- `ChatMeta`: add `pointId?: string`.
- `ChatSession`: add `pointId?: string`.
- Persisted session type: carry `pointId` through save/restore so refresh keeps context; if the store rebuilds sessions from messages, add the field to the persisted shape and restore path.

- [ ] **Step 2: Pass pointId in send**

Change `send` signature and the `scheduleStream` meta:

```ts
function send(text?: string, cmd?: string, extra?: { pointId?: string }) {
  // ...
  scheduleStream(session, live, content, 450, {
    // existing fields...
    pointId: extra?.pointId ?? session.pointId,
  })
}
```

When `extra?.pointId` is provided, set `session.pointId = extra.pointId` before sending.

- [ ] **Step 3: Consume the deep link once**

In `onMounted`, after `createSession(); greet();`:

```ts
function consumePointLink() {
  if (isResearch.value) return
  const point = typeof route.query.point === 'string' ? route.query.point : ''
  const start = route.query.start === '1'
  if (!point || !start) return
  const name = typeof route.query.name === 'string' ? route.query.name.slice(0, 40) : point
  router.replace({ path: '/learn' })
  nextTick(() => {
    send(t('learn.pointLessonPrompt', { name }), '知识点讲解', { pointId: point })
  })
}
```

Call it after `greet()` in `onMounted`. `router.replace` clears `point/name/start` before sending, so refresh does not resend.

Add i18n `learn.pointLessonPrompt`: `讲解知识点：{name}` / `Explain the concept: {name}`.

- [ ] **Step 4: Verify**

Run: `cd frontend && npx vue-tsc --noEmit && npm test`
Expected: typecheck passes; all frontend suites pass.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/api/types.ts frontend/src/services/chatService.ts frontend/src/stores/sessions.ts frontend/src/components/chat/ChatWorkspace.vue frontend/src/utils/i18n.ts
git commit -m "feat: consume point deep link and keep lesson context per session"
```

---

### Task 5: 后端“知识点讲解”指令与追问上下文

**Files:**
- Modify: `backend/chat.py`
- Test: `backend/tests/test_chat_helpers.py`（或新建 `backend/tests/test_point_lesson.py`）

**Interfaces:**
- Consumes: `KnowledgePoint.summary`, `key_points`; request `pointId`.
- Produces: `_gen_point_lesson(uid: str, point_id: str, question: str, zh: bool)`.
- Produces: `_point_notes_text(point) -> str`（摘要 + 要点纯文本，Task 5 与追问注入共用）.

- [ ] **Step 1: Write failing tests**

Test command branch with a stub graph:

```python
def test_point_lesson_command_uses_notes(monkeypatch):
    point = KnowledgePoint("p1", "极限", "函数与极限", 3, (), "摘要内容", ("要点一", "要点二"))
    graph = KnowledgeGraph({"p1": point})
    monkeypatch.setattr(chat.diagnosis, "get_graph", lambda: graph)
    captured = {}

    async def fake_stream(system, user, **kwargs):
        captured["system"] = system
        captured["user"] = user
        yield "主干……"

    monkeypatch.setattr(chat.rag.llm, "is_configured", lambda: True)
    monkeypatch.setattr(chat.rag.llm, "stream_chat", fake_stream)
    monkeypatch.setattr(chat.rag, "search", lambda *a, **k: [])

    resp = asyncio.run(chat._route_chat(
        "讲解知识点：极限", "知识点讲解", {"pointId": "p1"}, {"uid": "u"},
        {"role": "main", "research": False}, "learn"))
    text = _joined(resp)

    assert "摘要内容" in captured["system"]
    assert "要点一" in captured["system"]
    assert "主干" in text
```

Add tests:
- `test_point_lesson_unknown_point_returns_friendly_text` → `_route_chat` with `pointId="missing"`, assert "未找到" and no LLM call.
- `test_point_lesson_falls_back_without_llm` → `is_configured` False, assert summary/key points in output.
- `test_point_context_injected_for_followups` → cmd None, body `{"pointId": "p1"}`, capture system, assert summary present in system.
- `test_point_lesson_ignored_in_research_workspace` → workspace "research", assert no lesson branch call (use a forbidden stub on `_gen_point_lesson`).

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && ../.venv/Scripts/python.exe -m pytest tests/test_point_lesson.py -q`
Expected: FAIL because the command branch and helper do not exist.

- [ ] **Step 3: Implement helpers**

In `backend/chat.py`:
- Add `import diagnosis` alongside the existing module imports (chat.py does not import it today).
- Add `_point_notes_text(point) -> str` returning `summary` + numbered key points; empty string when no notes.
- Add `_gen_point_lesson(uid, point_id, question, zh)`:
  - `graph = diagnosis.get_graph()`, `point = graph.points.get(point_id)`.
  - Unknown: yield one SSE frame `"未找到该知识点，请返回图谱重新选择。"` / English equivalent.
  - If no notes: use `rag.search(point.name, 3)` excerpts as fallback; if still empty, say the content is unavailable but ask what the user wants to know.
  - If LLM configured: system prompt includes name/chapter/difficulty, summary, key points, prerequisite names, direct dependent names, and instructions:
    - 先输出“主干”（3–6 条）与“重点注意点”（2–4 条）；
    - 不展开例题、不输出图解标记；
    - 只使用提供的知识点事实；不足时明确说明；
    - 末尾问用户想先听哪一部分。
  - Stream via `rag.llm.stream_chat(..., role="main", thinking=False)`.
  - On model failure or no LLM: deterministic report with summary + key points + “接下来想先听哪一部分？”.
- In `_route_chat`, after `question = _strip_meta(...)` and before RAG:
  ```python
  if cmd == "知识点讲解" and workspace == "learn":
      meta["role"] = "main"
      point_id = str(body.get("pointId") or "")[:64]
      return _sse(_gen_point_lesson(uid, point_id, question, zh))
  ```
- For follow-ups: where `chunks` is built for learn (`chunks = await asyncio.to_thread(rag.search, ...)`), if `workspace == "learn"` and `body.get("pointId")`:
  ```python
  point = diagnosis.get_graph().points.get(str(body["pointId"]))
  note_text = _point_notes_text(point) if point else ""
  if note_text:
      chunks = [(rag.Chunk(f"point:{point.id}", point.name, point.chapter,
                           "知识点主要内容", note_text), 9.0)] + chunks
  ```
  This preserves context for every follow-up in the session.

- [ ] **Step 4: Run tests**

Run: `cd backend && ../.venv/Scripts/python.exe -m pytest tests/test_point_lesson.py tests/test_chat_helpers.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/chat.py backend/tests/test_point_lesson.py
git commit -m "feat: add knowledge point lesson command and follow-up context"
```

---

### Task 6: 全链路验证

**Files:**
- No production changes unless verification finds a defect.

- [ ] **Step 1: Run full backend suite**

Run: `cd backend && ../.venv/Scripts/python.exe -m pytest -q`
Expected: all pass, 1 skip allowed.

- [ ] **Step 2: Run frontend suite and build**

Run: `cd frontend && npm test && npx vue-tsc --noEmit && npm run build`
Expected: all pass.

- [ ] **Step 3: Browser walkthrough**

1. Open `/graph`, click a point with notes.
2. Confirm “主要内容” appears between “前置知识” and “后续知识”, with summary and key points.
3. Click “前往”; confirm URL becomes `/learn` without query and a new session starts with `讲解知识点：<name>`.
4. Confirm first answer has “主干” and “重点注意点”, no worked examples.
5. Ask “再讲讲第二步”; confirm the answer still uses the point context.
6. Refresh `/learn`; confirm the lesson is not resent.
7. Open a point without notes (if any); confirm “暂无摘要” and the lesson still starts with fallback text.
8. Switch to `/research`; confirm graph deep links do not trigger the lesson.

- [ ] **Step 4: Commit verification fixes**

Only if changes are needed:

```bash
git add <changed files>
git commit -m "fix: address point lesson verification failures"
```

---

## Execution Handoff

- 内容草稿：`docs/knowledge-point-notes-draft.md`（80 条，等你审核）。
- 审核通过后先做 Task 1 Step 5 导入，再按 Task 1–6 顺序执行。
- 当前工作区还有未提交的公式渲染改动；本计划不覆盖、不回退这些改动。
