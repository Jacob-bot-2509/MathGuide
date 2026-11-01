# 静态图解 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 论文工作台提供缓存式可折叠思维导图；学习区/科研主聊天在用户困惑处内联生成临时图解，随会话保存；论文工作台左栏图解随聊天关闭清空。

**Architecture:** 模型只输出结构化图解 JSON 与隐藏标记；后端剥离标记、并行规划图解并通过 SSE `diagram` 事件下发；前端用统一 schema 校验，2D SVG 与 3D Three.js 渲染，按 `anchorIndex` 插入消息对应段落后。论文脑图从 `PaperStructure` 缓存直接生成，不调用模型。

**Tech Stack:** Starlette/Python 3、Vue 3 `<script setup>`、TypeScript、SVG、Three.js（仅 3D，懒加载）、pytest、Node esbuild 自测。

**Spec:** `docs/superpowers/specs/2026-11-01-static-diagrams-design.md`

## Global Constraints

- 模型不得生成图片、HTML、任意 SVG 或 Three.js 代码；只输出白名单结构化数据。
- 回答图解不得写入 `doc_insights`，不得进入论文结构缓存。
- 学习区/科研主聊天图解随 `ChatMsg` 本地会话保存；论文工作台左栏关闭即清空。
- 2D 支持拖动/缩放；3D 支持旋转/缩放；不自动播放动画。
- 单条消息最多 2 张图；节点 ≤40、边 ≤80、2D 形状 ≤100、3D 网格 ≤60×60。
- 图解失败不影响正文回答；图解规划不触发外部文献检索。
- 学习区/科研区隔离、既有论文动作、搜索、表格、公式功能不得改变。
- 所有新增前端纯逻辑必须有 Node 自测入口；后端新增逻辑必须有 pytest。
- 提交前运行：`backend pytest`、`frontend npm test`、`vue-tsc --noEmit`、`npm run build`。

## Review Focus

- 标记跨 SSE chunk 被拆开时，不能把半个标记显示给用户，也不能漏掉图解。
- 图解事件晚于正文到达时，必须插在正确段落，正文不跳、不丢。
- 图解内容不得凭空造出引用资料/论文里不存在的关系。
- 3D 组件切换消息/会话时必须释放渲染器，不能泄漏 WebGL context。
- 论文脑图必须只读缓存，重复打开不得调用模型。

---

### Task 1: 共享图解 schema 与消息分段

**Files:**
- Create: `frontend/src/utils/diagramSpec.ts`
- Create: `frontend/scripts/diagram-test.ts`
- Modify: `frontend/scripts/run-tests.mjs`
- Test: `frontend/scripts/diagram-test.ts`

**Interfaces:**
- Produces:
  - `DiagramType = 'tree'|'relation'|'flow'|'geometry2d'|'plot2d'|'geometry3d'|'surface3d'`
  - `DiagramSpec`, `DiagramBlock`
  - `MessageBlock = { kind: 'text'; text: string } | { kind: 'diagram'; diagram: DiagramBlock }`
  - `parseDiagramSpec(raw: unknown): DiagramSpec | null`
  - `parseDiagramEvent(payload: unknown): DiagramBlock | null`
  - `splitMessageBlocks(content: string, diagrams: DiagramBlock[]): MessageBlock[]`

- [ ] **Step 1: Write the failing test**

In `frontend/scripts/diagram-test.ts`, assert:

```ts
const spec = parseDiagramSpec({
  type: 'relation',
  nodes: [{ id: 'a', label: 'A' }, { id: 'b', label: 'B' }],
  edges: [{ from: 'a', to: 'b', label: '推出' }],
})
check('合法 relation', spec?.nodes?.length === 2)
check('非法类型拒绝', parseDiagramSpec({ type: 'script' }) === null)
check('超限节点拒绝', parseDiagramSpec({ type: 'relation', nodes: Array(41).fill({ id: 'x', label: 'x' }) }) === null)

const blocks = splitMessageBlocks('第一段\n\n第二段', [
  { id: 'd1', anchorIndex: 6, spec: spec! },
])
check('按锚点分段', blocks.length === 3 && blocks[1].kind === 'diagram')
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx esbuild scripts/diagram-test.ts --bundle --format=cjs --platform=node --outfile=.diagram-test.cjs && node .diagram-test.cjs`

Expected: FAIL because `diagramSpec.ts` does not exist.

- [ ] **Step 3: Implement `diagramSpec.ts`**

Expose the interfaces above. Validate:

- type whitelist;
- nodes/edges/shapes cap;
- string lengths: title 200, label 200, note/text 400;
- coordinates finite and within `[-1e4, 1e4]`;
- reject unknown top-level fields? At minimum ignore unknown fields; never pass them to renderer.
- `splitMessageBlocks`: sort diagrams by `anchorIndex`, clamp to `[0, content.length]`, emit `text/diagram/text` blocks; duplicate anchors keep each diagram once.

- [ ] **Step 4: Run test to verify it passes**

Run the command from Step 2; expected: `图解协议自测: ... 通过`.

- [ ] **Step 5: Add test to runner**

Add a `图解协议` case to `frontend/scripts/run-tests.mjs` and run `npm test`.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/utils/diagramSpec.ts frontend/scripts/diagram-test.ts frontend/scripts/run-tests.mjs
git commit -m "feat: 图解协议与消息分段"
```

---

### Task 2: 2D 布局纯函数

**Files:**
- Create: `frontend/src/utils/diagramLayout.ts`
- Modify: `frontend/scripts/diagram-test.ts`

**Interfaces:**
- Consumes: `DiagramSpec` from Task 1.
- Produces:
  - `layoutTree(spec: DiagramSpec): { nodes: PositionedNode[]; edges: PositionedEdge[]; width: number; height: number }`
  - `layoutRelation(spec: DiagramSpec): ...`
  - `layoutFlow(spec: DiagramSpec): ...`
  - `PositionedNode = { id, x, y, w, h, label }`

- [ ] **Step 1: Write failing tests**

Test a 3-node tree and a 2-node relation:

- no overlapping node boxes;
- parent before child vertically for tree;
- width/height positive and bounded;
- missing edge endpoints ignored;
- 40-node spec returns finite coordinates.

- [ ] **Step 2: Run to fail**

Run the Task 1 test command; expected: import error for `diagramLayout.ts`.

- [ ] **Step 3: Implement layouts**

- Tree: simple top-down layered layout; siblings evenly spaced; node width based on label length capped.
- Relation: deterministic grid/ring layout with fixed seed; no physics loop.
- Flow: left-to-right or top-down chain based on edge direction; fallback grid for cycles.
- All coordinates bounded; no DOM access.

- [ ] **Step 4: Run to pass**

Run Task 1 command; expected all checks pass.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/utils/diagramLayout.ts frontend/scripts/diagram-test.ts
git commit -m "feat: 图解 2D 布局算法"
```

---

### Task 3: 2D SVG 渲染组件

**Files:**
- Create: `frontend/src/components/diagram/DiagramSvg.vue`
- Create: `frontend/src/components/diagram/DiagramBlock.vue`
- Modify: `frontend/src/styles` only if shared tokens needed
- Test: build/type-check + browser smoke

**Interfaces:**
- Consumes: `DiagramSpec`, `layoutTree/layoutRelation/layoutFlow`.
- Produces:
  - `DiagramSvg` props `{ spec: DiagramSpec }`
  - `DiagramBlock` props `{ spec: DiagramSpec }`
  - both support pan/zoom/reset via SVG `viewBox`.

- [ ] **Step 1: Implement `DiagramSvg.vue`**

Render:
- `tree/relation/flow`: nodes as rounded rects, labels via `<text>` wrapped, edges as lines/paths with optional labels;
- `geometry2d`: point/segment/line/circle/polygon/vector/annotation shapes;
- `plot2d`: axes, curve polyline from `points`, key points;
- viewport drag and wheel zoom; reset button; no animation.

- [ ] **Step 2: Implement `DiagramBlock.vue`**

Choose `DiagramSvg` for 2D types; if `geometry3d/surface3d`, render a “3D 待启用” fallback until Task 9; never render raw strings as HTML.

- [ ] **Step 3: Type-check and build**

Run: `cd frontend && npx vue-tsc --noEmit && npm run build`

Expected: PASS.

- [ ] **Step 4: Browser smoke**

Render a temporary page with a `relation` spec and a `geometry2d` spec; verify drag/zoom/reset, no console errors. Remove the temporary page before commit.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/diagram
git commit -m "feat: 2D SVG 图解渲染器"
```

---

### Task 4: 论文思维导图接入

**Files:**
- Modify: `frontend/src/components/research/PaperInsights.vue`
- Modify: `frontend/src/services/researchService.ts` (optional `pageStart` on `OutlineNode`)
- Modify: `backend/research_corpus.py` only if page anchors are available
- Test: `frontend npm test`, browser smoke

**Interfaces:**
- Consumes: `PaperStructure` from `getResearchDocInsights`.
- Produces:
  - `buildPaperDiagram(structure: PaperStructure): DiagramSpec` in `frontend/src/utils/diagramSpec.ts`
  - Tree root = paper title; branches = question/methods/conclusions/limitations/outline.

- [ ] **Step 1: Add pure builder test**

In `diagram-test.ts`, assert `buildPaperDiagram` produces root + branches for question/methods/conclusions/limitations/outline and respects node cap.

- [ ] **Step 2: Implement builder**

Create tree spec from cached structure only. No API/model call in the builder.

- [ ] **Step 3: Replace CSS mind map with `DiagramSvg`**

Keep existing question/methods/conclusions/limitations text sections; replace `.mm` block with the tree renderer. Preserve structure loading/error/refresh behavior.

- [ ] **Step 4: Optional node page jump**

If `OutlineNode.pageStart` exists, emit click and call viewer jump via an injected callback; otherwise no click. Do not add model calls.

- [ ] **Step 5: Verify cache behavior**

Open/close/reopen paper workspace; assert no `/insights` POST occurs on cached reopen (network/browser or backend log). Run `npm test`, `vue-tsc`, `build`.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/research/PaperInsights.vue frontend/src/services/researchService.ts frontend/src/utils/diagramSpec.ts frontend/scripts/diagram-test.ts
git commit -m "feat: 论文思维导图接入 SVG 树"
```

---

### Task 5: 后端标记流与图解 schema 校验

**Files:**
- Create: `backend/research_diagrams.py`
- Create: `backend/tests/test_research_diagrams.py`
- Test: `backend/tests/test_research_diagrams.py`

**Interfaces:**
- Produces:
  - `@dataclass DiagramMarker(anchor_id, kind, anchor_index)`
  - `class MarkerStream(request_id: str)` with `feed(text: str) -> str`, `drain() -> list[DiagramMarker]`, `finish() -> str`
  - `validate_diagram(raw: object) -> dict | None`
  - `diagram_event(diagram: dict, request_id: str, anchor_id: str, anchor_index: int) -> str`

- [ ] **Step 1: Write failing tests**

- marker split across feeds `[[MG_DIA` + `GRAM:relation]]`;
- clean text equals surrounding text;
- `anchor_index` equals visible text length before marker;
- multiple markers get stable `anchor_id`s;
- malformed/incomplete marker is stripped at `finish`, no crash;
- valid schema accepted; unknown type/oversize/HTML string rejected.

- [ ] **Step 2: Run to fail**

Run: `cd backend && ../.venv/Scripts/python.exe -m pytest tests/test_research_diagrams.py -v`

Expected: collection error / module missing.

- [ ] **Step 3: Implement marker parser**

Regex `\[\[MG_DIAGRAM:([a-z0-9_]+)\]\]`. Buffer incomplete suffix; never emit raw marker. `feed` returns visible text; `drain` returns complete markers. `finish` strips leftover buffer.

- [ ] **Step 4: Implement schema validation**

Whitelist types; cap nodes/edges/shapes/annotations; clamp/validate numbers; reject non-finite coordinates; truncate strings; drop unknown fields.

- [ ] **Step 5: Run to pass**

Run Step 2; expected PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/research_diagrams.py backend/tests/test_research_diagrams.py
git commit -m "feat: 图解标记流与 schema 校验"
```

---

### Task 6: 图解规划器

**Files:**
- Modify: `backend/research_diagrams.py`
- Modify: `backend/tests/test_research_diagrams.py`

**Interfaces:**
- Consumes: `validate_diagram`.
- Produces: `async def plan_diagram(question: str, before: str, excerpts: list[dict], kind: str, role: str = "main") -> dict | None`

- [ ] **Step 1: Write failing tests**

- fake LLM returns a valid relation JSON → parsed spec;
- fake LLM returns invalid JSON → None;
- fake LLM returns unknown type → None;
- prompt includes question, before text, and excerpts;
- no LLM configured → None.

- [ ] **Step 2: Run to fail**

Run Task 5 test command; expected missing `plan_diagram`.

- [ ] **Step 3: Implement planner**

Use `rag.llm.stream_chat(... role="main", thinking=False, max_tokens=1200)`, collect up to 8000 chars, strip code fences, parse JSON. System prompt: only current answer/question/excerpts; never invent relations; return one diagram; obey type and limits. Truncate `before` to 6000 chars, excerpts to 6000 chars.

- [ ] **Step 4: Run to pass**

Run Task 5 command; expected PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/research_diagrams.py backend/tests/test_research_diagrams.py
git commit -m "feat: 图解规划器"
```

---

### Task 7: 聊天流接入图解事件

**Files:**
- Modify: `backend/chat.py`
- Modify: `backend/tests/test_chat_helpers.py`
- Test: `backend/tests/test_chat_helpers.py`

**Interfaces:**
- Consumes: `MarkerStream`, `plan_diagram`, `diagram_event`.
- Produces: `_gen_llm(..., diagram_mode: bool = False, diagram_question: str = "", diagram_excerpts: list[dict] | None = None, diagram_request_id: str = "")`; emits `mg_event: "diagram"` frames.

- [ ] **Step 1: Write failing tests**

- fake LLM stream contains `[[MG_DIAGRAM:relation]]`; collected frames have clean text, no marker, and one diagram event;
- marker split across fake deltas still yields one event and correct `anchorIndex`;
- planner failure yields no event and text intact;
- two markers produce two events with distinct `anchorId`;
- no diagram_mode leaves text unchanged.

- [ ] **Step 2: Run to fail**

Run: `cd backend && ../.venv/Scripts/python.exe -m pytest tests/test_chat_helpers.py -v`

Expected: test fails/no event.

- [ ] **Step 3: Implement in `_gen_llm`**

Create `MarkerStream`; feed every model delta; yield clean delta frames; when markers drain, schedule `plan_diagram` tasks. After each delta and at stream end, yield completed diagram frames. Ensure `[DONE]` remains last and `answer` excludes markers. Add diagram system prompt only when `diagram_mode`.

- [ ] **Step 4: Enable in routes**

- Normal research/learn LLM path: `diagram_mode=True`, question, excerpts from `chunks`.
- Paper branch: pass same through `_gen_paper_llm`; excerpts from `paper_context`.
- Do not enable when LLM not configured.

- [ ] **Step 5: Run tests**

Run Task 7 command; expected PASS. Run full backend tests.

- [ ] **Step 6: Commit**

```bash
git add backend/chat.py backend/tests/test_chat_helpers.py
git commit -m "feat: 聊天流图解事件"
```

---

### Task 8: 前端图解事件与内联插入

**Files:**
- Create: `frontend/src/components/diagram/DiagramBlock.vue` (if not ready)
- Create: `frontend/src/utils/diagramSpec.ts` (done Task 1)
- Modify: `frontend/src/stores/sessions.ts` (`ChatMsg.diagrams`)
- Modify: `frontend/src/components/chat/ChatWorkspace.vue`
- Modify: `frontend/src/components/research/PaperWorkspace.vue`
- Modify: `frontend/src/services/chatService.ts` only if callback typing needs it
- Test: `frontend/scripts/diagram-test.ts`, `npm test`, browser smoke

**Interfaces:**
- Consumes: `parseDiagramEvent`, `splitMessageBlocks`, `DiagramBlock`.
- Produces:
  - `ChatMsg.diagrams?: DiagramBlock[]`
  - `useDiagrams` optional helper: `appendDiagram(message, event)` with dedupe by `id`.

- [ ] **Step 1: Add persistence test**

In `diagram-test.ts`, assert session serialization includes `diagrams` and restore keeps `anchorIndex/spec`.

- [ ] **Step 2: Implement event handling**

In ChatWorkspace `onMeta`, detect `mg_event === 'diagram'`, call `parseDiagramEvent`, append to current assistant message; dedupe `requestId + anchorId`. In PaperWorkspace `onMeta`, append to local `live` message only.

- [ ] **Step 3: Render inline**

Replace single `<MathText :text="m.content">` with `splitMessageBlocks(m.content, m.diagrams)` loop: text blocks use existing `blocksOf`; diagram blocks render `DiagramBlock`. Preserve streaming, stopped, attachments, clarify cards, paper import cards, export buttons.

- [ ] **Step 4: Late diagram handling**

If `anchorIndex > content.length`, render at current end; once content grows, move to anchor. Do not lose scroll position.

- [ ] **Step 5: Verify persistence/cleanup**

- Learn/research main chat: reload page, diagram remains.
- PaperWorkspace: close/reopen, chat and diagrams gone.
- Delete message/session: diagrams gone.
- No diagram in `doc_insights`.

- [ ] **Step 6: Run tests/build**

Run `npm test`, `vue-tsc`, `npm run build`; browser smoke with a fake diagram event.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/stores/sessions.ts frontend/src/components/chat/ChatWorkspace.vue frontend/src/components/research/PaperWorkspace.vue frontend/src/utils/diagramSpec.ts frontend/scripts/diagram-test.ts
git commit -m "feat: 回答内联图解与会话保存"
```

---

### Task 9: 3D 图解渲染

**Files:**
- Create: `frontend/src/components/diagram/Diagram3D.vue`
- Modify: `frontend/src/components/diagram/DiagramBlock.vue`
- Modify: `frontend/package.json`
- Test: browser smoke + type-check/build

**Interfaces:**
- Consumes: `DiagramSpec` with `geometry3d` / `surface3d`.
- Produces: `Diagram3D` component with rotate/zoom/reset; dispose on unmount.

- [ ] **Step 1: Add dependency**

Add pinned `three` version compatible with Vite; install; verify build.

- [ ] **Step 2: Implement 3D renderer**

- lazy import Three.js;
- points, segments, vectors, planes, sphere, box, cone, cylinder, curve, surface grid, labels;
- OrbitControls; render only on interaction/resize;
- DPR cap 2; dispose geometries/materials/renderer;
- fallback text if WebGL unavailable.

- [ ] **Step 3: Wire into DiagramBlock**

2D types stay SVG; 3D types lazy-load `Diagram3D`; no autoplay.

- [ ] **Step 4: Verify lifecycle**

Switch messages/sessions; assert no WebGL context leak (browser devtools/console); 2D unaffected.

- [ ] **Step 5: Run tests/build**

`npm test`, `vue-tsc`, `npm run build`; browser smoke.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/diagram/Diagram3D.vue frontend/src/components/diagram/DiagramBlock.vue frontend/package.json frontend/package-lock.json
git commit -m "feat: 3D 静态图解渲染"
```

---

### Task 10: 手动图解与兜底

**Files:**
- Create: `frontend/src/services/diagramService.ts`
- Modify: `backend/research_diagrams.py`
- Modify: `backend/main.py`
- Modify: `frontend/src/components/chat/ChatWorkspace.vue`
- Modify: `frontend/src/components/research/PaperWorkspace.vue`
- Test: `frontend npm test`, backend pytest, browser smoke

**Interfaces:**
- Consumes: `plan_diagram`; `parseDiagramEvent`.
- Produces:
  - `POST /api/research/diagrams/plan` request `{question: string, answer: string, paperId?: string, kind?: string}` → `{diagram: object}`
  - `planDiagram(input): Promise<DiagramSpec | null>` in `diagramService.ts`
  - Manual action appends `DiagramBlock { id: "manual-...", anchorIndex: content.length, spec }`.

- [ ] **Step 1: Add backend endpoint test**

In `backend/tests/test_research_diagrams.py`, POST with auth mock and monkeypatched `plan_diagram`; assert 200 `{diagram}`; missing auth/invalid body fails; rate limit applies.

- [ ] **Step 2: Implement endpoint**

Add Starlette handler in `research_diagrams.py`; register in `main.py`. Use `require_auth`, existing limiter, max answer length 12000, no external search; pass `paperId` excerpts from `paper_context` when valid.

- [ ] **Step 3: Add manual button**

Each assistant message with `content` gets “图解此段”; click calls `planDiagram({question, answer: msg.content, paperId?})`, appends one diagram at message end; disable while pending; dedupe by message id.

- [ ] **Step 4: Add understanding-intent fallback**

If user question matches understanding intent and no diagram event arrived after `onDone`, call the same endpoint once. Do not run for chitchat. On failure show no error block.

- [ ] **Step 5: Verify**

- Manual button creates one diagram, no duplicate on retry;
- fallback only for understanding questions;
- chitchat never gets diagrams;
- PaperWorkspace diagram disappears on close; Learn/Research persists.

- [ ] **Step 6: Run full tests/build**

Run all backend/frontend tests, type-check, build.

- [ ] **Step 7: Commit**

```bash
git add backend/research_diagrams.py backend/main.py backend/tests/test_research_diagrams.py frontend/src/services/diagramService.ts frontend/src/components/chat/ChatWorkspace.vue frontend/src/components/research/PaperWorkspace.vue
git commit -m "feat: 手动图解与理解型兜底"
```

---

### Task 11: 回归与发布准备

**Files:**
- Modify: `docs/STATIC_DIAGRAM_PLAN.md` (progress notes only)
- Test: full suite, browser smoke

- [ ] **Step 1: Full automated suite**

```bash
cd backend && ../.venv/Scripts/python.exe -m pytest -q
cd ../frontend && npm test && npx vue-tsc --noEmit && npm run build
```

- [ ] **Step 2: Browser acceptance**

- 论文脑图 cached reopen;
- inline diagram at anchor, no text jump;
- learn/research persistence;
- PaperWorkspace clear;
- 2D/3D interactions;
- chitchat no diagram;
- diagram failure leaves answer.

- [ ] **Step 3: Update progress doc and commit**

```bash
git add docs/STATIC_DIAGRAM_PLAN.md
git commit -m "docs: 静态图解验收记录"
```
