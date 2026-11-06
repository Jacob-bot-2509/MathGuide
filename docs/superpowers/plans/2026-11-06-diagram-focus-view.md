# 图解放大视图 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 给聊天内图解增加双击放大：桌面左右分屏、移动端可缩放浮层，并让聊天内图解统一黑底。

**Architecture:** 复用 `ChatWorkspace` 已有的分栏拖拽；用 `Teleport` 把同一个 `DiagramBlock` 搬到焦点舞台，避免复制 3D/GeoGebra 实例。几何计算抽到 `diagramFocus.ts` 纯函数，组件只采集指针事件和样式。

**Tech Stack:** Vue 3 `<script setup>`、TypeScript、CSS scoped、Three.js、现有 `diagram-test.ts` 自测。

**Spec:** `docs/superpowers/specs/2026-11-06-diagram-focus-view-design.md`

## Global Constraints

- 桌面分屏与移动浮层互斥；小于 900px 一律走移动浮层。
- 图内手势与窗口手势分区：图内缩放/平移，标题栏/边缘缩放窗口。
- 图内交互不关闭放大；只有放大区外点击、关闭按钮、Esc、全屏下滑关闭。
- 不复制 3D/GeoGebra 实例；Teleport 保持组件状态。
- 聊天内图解和焦点舞台统一背景 `#05070a`；浅色主题局部使用深色 token。
- 现有科研检索分栏行为不变；放大时暂时关闭，关闭后恢复。
- 不改 DiagramSpec、不改后端图解生成。

## Review Focus

- 双击/双点与拖拽、双指缩放误触：移动超过阈值不触发放大。
- Teleport 开关是否保留 2D viewBox、3D 相机、GeoGebra 内核结果，且不出现双实例。
- 桌面分栏与科研检索分栏同时存在时的状态恢复。
- 浅色主题下黑底图解的坐标轴、标签、节点对比度。
- 移动端全屏后没有“区外”可点：关闭按钮/下滑必须可用。

---

### Task 1: 焦点几何纯函数

**Files:**
- Create: `frontend/src/utils/diagramFocus.ts`
- Modify: `frontend/scripts/diagram-test.ts`

**Interfaces:**
- Produces:
  - `interface FocusPanel { x: number; w: number; h: number; fullscreen: boolean }`
  - `interface Viewport { width: number; height: number }`
  - `clampDiagramSplit(value: number, width: number): number`
  - `clampFocusPanel(panel: FocusPanel, viewport: Viewport): FocusPanel`
  - `moveFocusPanel(panel: FocusPanel, dx: number, viewport: Viewport): FocusPanel`
  - `resizeFocusPanel(panel: FocusPanel, scale: number, viewport: Viewport): FocusPanel`
  - `isDoubleTap(previous: TapPoint | null, next: TapPoint, maxDelay = 300, maxDistance = 10): boolean`
  - `interface TapPoint { time: number; x: number; y: number }`
  - constants `DIAGRAM_SPLIT_DEFAULT = 0.62`, `DIAGRAM_CHAT_MIN = 360`, `DIAGRAM_MIN = 420`, `FOCUS_MIN_W = 70`, `FOCUS_MIN_H = 60`, `FOCUS_FULL_W = 95`, `FOCUS_FULL_H = 92`.

- [ ] **Step 1: Write failing tests in `diagram-test.ts`**

Add imports and checks:

```ts
import {
  clampDiagramSplit, clampFocusPanel, moveFocusPanel, resizeFocusPanel,
  isDoubleTap, DIAGRAM_SPLIT_DEFAULT,
} from '../src/utils/diagramFocus'

check('图解放大分栏默认 62%', Math.abs(DIAGRAM_SPLIT_DEFAULT - 0.62) < 1e-9)
check('分栏保留聊天与图解最小宽度',
  Math.abs(clampDiagramSplit(0.9, 1000) - 0.64) < 1e-9
  && Math.abs(clampDiagramSplit(0.1, 1000) - 0.42) < 1e-9)
check('窄屏分栏回退中间比例', clampDiagramSplit(0.9, 700) <= 0.7)
check('移动窗口不越界',
  clampFocusPanel({ x: 999, w: 90, h: 82, fullscreen: false },
    { width: 390, height: 844 }).x < 999)
check('双指放大到阈值全屏',
  resizeFocusPanel({ x: 0, w: 90, h: 82, fullscreen: false }, 1.2,
    { width: 390, height: 844 }).fullscreen)
check('全屏窗口不能移动',
  moveFocusPanel({ x: 0, w: 100, h: 100, fullscreen: true }, 40,
    { width: 390, height: 844 }).x === 0)
check('双点判定', isDoubleTap(
  { time: 1000, x: 100, y: 100 }, { time: 1200, x: 104, y: 103 }))
check('拖拽后不触发放大', !isDoubleTap(
  { time: 1000, x: 100, y: 100 }, { time: 1200, x: 140, y: 100 }))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npx esbuild scripts/diagram-test.ts --bundle --format=cjs --platform=node --outfile=.diagram-test.cjs && node .diagram-test.cjs`
Expected: module not found / checks fail.

- [ ] **Step 3: Create `diagramFocus.ts`**

Implement the signatures above. `clampDiagramSplit` treats `value` as the right pane ratio; min = `DIAGRAM_MIN/width`, max = `1 - DIAGRAM_CHAT_MIN/width`; if width < 780 return `0.55..0.7` clamp. `resizeFocusPanel` multiplies `w/h`, clamps minima, and sets `fullscreen` when `w >= FOCUS_FULL_W || h >= FOCUS_FULL_H`; fullscreen returns `{x:0,w:100,h:100,fullscreen:true}`. `moveFocusPanel` clamps `x` by `(100-w)*viewport.width/200` each side and returns unchanged if fullscreen. `isDoubleTap` checks non-null, delay, distance.

- [ ] **Step 4: Run test to verify it passes**

Run: `npx esbuild scripts/diagram-test.ts --bundle --format=cjs --platform=node --outfile=.diagram-test.cjs && node .diagram-test.cjs`
Expected: all checks pass.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/utils/diagramFocus.ts frontend/scripts/diagram-test.ts
git commit -m "feat: 图解放大几何工具"
```

---

### Task 2: 黑底图表面板与 focus 尺寸

**Files:**
- Modify: `frontend/src/components/diagram/DiagramBlock.vue`
- Modify: `frontend/src/components/diagram/Diagram3D.vue`
- Modify: `frontend/src/components/diagram/GeoGebra3DKernelBlock.vue`
- Modify: `frontend/src/components/diagram/GeoGebraKernelBlock.vue`

**Interfaces:**
- `DiagramBlock` props: `{ spec: DiagramSpec; focused?: boolean }` default `focused=false`.
- `Diagram3D` props: `{ spec: DiagramSpec; focused?: boolean }` default `focused=false`.
- `GeoGebra3DKernelBlock` props: `{ spec: DiagramSpec; focused?: boolean }` and passes `:focused` to `Diagram3D`.
- `GeoGebraKernelBlock` props: `{ spec: DiagramSpec; focused?: boolean }`; focus loading/fallback classes fill the stage.

- [ ] **Step 1: Add focus props and classes**

`DiagramBlock.vue`:

```vue
const props = withDefaults(defineProps<{ spec: DiagramSpec; focused?: boolean }>(), {
  focused: false,
})
```

Root figure: `:class="{ 'diagram-block--focused': focused }"`. Pass `:focused="focused"` to `Diagram3D` and `GeoGebra3DKernelBlock`.

`Diagram3D.vue`: same prop; wrapper classes `diagram-3d-wrap--focused`, `diagram-3d--focused`.

- [ ] **Step 2: Apply black diagram surface**

`DiagramBlock.vue` CSS:

```css
.diagram-block {
  background: #05070a;
  border: 1px solid rgba(96, 165, 250, 0.18);
  border-radius: 8px;
  padding: 8px;
  --bg-void: #05070a;
  --bg-panel: rgba(13, 18, 30, 0.92);
  --bg-card: #05070a;
  --text-hi: #e8f2ff;
  --text: #c2d2e4;
  --text-dim: #8b9bb0;
  --line: rgba(96, 165, 250, 0.18);
  --line-bright: rgba(96, 165, 250, 0.45);
  --cyan: #4dd6ff;
}
.diagram-block--focused {
  max-width: none;
  height: 100%;
  margin: 0;
  padding: 0;
  border: 0;
  border-radius: 0;
  display: flex;
  flex-direction: column;
  background: transparent;
}
```

Focus 2D: `:deep(.diagram-svg-wrap) { flex:1; min-height:0; background:#05070a; }` and `:deep(.diagram-svg) { height:100%; max-height:none; min-height:0; }`.

`Diagram3D.vue` focus CSS:

```css
.diagram-3d-wrap--focused { max-width:none; width:100%; height:100%; margin:0; border:0; border-radius:0; flex:1; min-height:0; }
.diagram-3d--focused { height:100%; min-height:0; }
.diagram-block--focused :deep(.diagram-3d-wrap) { flex:1; min-height:0; }
```

- [ ] **Step 3: Verify types/build**

Run: `npx vue-tsc --noEmit`
Expected: PASS.

Run: `npm run build`
Expected: build succeeds.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/diagram/DiagramBlock.vue frontend/src/components/diagram/Diagram3D.vue frontend/src/components/diagram/GeoGebra3DKernelBlock.vue frontend/src/components/diagram/GeoGebraKernelBlock.vue
git commit -m "feat: 图解黑底与焦点尺寸"
```

---

### Task 3: 桌面分屏与 Teleport

**Files:**
- Modify: `frontend/src/components/chat/ChatWorkspace.vue`

**Interfaces:**
- Consumes Task 1 constants/functions.
- Produces local state: `focusDiagram: Ref<DiagramBlock | null>`, `diagramSplitRatio`, `focusPaneStyle: ComputedRef<CSSProperties>`, `isNarrow`.
- `openDiagramFocus(block: DiagramBlock, msgId: number): void`
- `closeDiagramFocus(): void`
- `isFocused(block: DiagramBlock): boolean`

- [ ] **Step 1: Add split/focus state and helpers**

In `ChatWorkspace.vue`:

```ts
const DIAGRAM_SPLIT_KEY = 'mg-diagram-split'
const DIAGRAM_SPLIT_MIN_WIDTH = 900
const focusDiagram = ref<DiagramBlock | null>(null)
const focusOrigin = ref<{ msgId: number; scrollTop: number } | null>(null)
const focusStageEl = ref<HTMLElement | null>(null)
const diagramSplitRatio = ref(loadDiagramSplit())
const diagramSplitResizing = ref(false)
const searchWasOpen = ref(false)
const narrowQuery = window.matchMedia('(max-width: 899px)')
const isNarrow = ref(narrowQuery.matches)
```

Add `loadDiagramSplit`, `saveDiagramSplit`, `clampDiagramSplit` wrapper using `workspaceBodyRef`, `startDiagramSplitDrag`, `nudgeDiagramSplit`, `resetDiagramSplit`, `openDiagramFocus`, `closeDiagramFocus`, `isFocused`, `onChatPaneClick`, `onFocusKeydown`.

`openDiagramFocus`: record `focusOrigin` from `listEl.value?.scrollTop`, remember/close `searchOpen`, set `focusDiagram`, `nextTick` focus close button.

`closeDiagramFocus`: clear focus; if `searchWasOpen` and desktop restore `searchOpen`; `nextTick` restore `listEl.scrollTop`; focus origin message via `data-msg-id`.

Add `narrowQuery.addEventListener('change', ...)` in `onMounted`, remove in `onBeforeUnmount`, plus `keydown` listener.

- [ ] **Step 2: Wire template**

Wrap diagram block:

```vue
<div
  v-else-if="block.diagram"
  class="diagram-embed"
  @dblclick.stop="openDiagramFocus(block.diagram, m.id)"
>
  <Teleport to="#mg-diagram-focus-stage"
    :disabled="focusDiagram?.id !== block.diagram.id">
    <DiagramBoundary ...>
      <DiagramBlockView :spec="block.diagram.spec"
        :focused="focusDiagram?.id === block.diagram.id" />
    </DiagramBoundary>
  </Teleport>
  <div v-if="focusDiagram?.id === block.diagram.id" class="diagram-inline-placeholder" />
</div>
```

Add chat-pane click: `@click="onChatPaneClick"`.

Add focus pane after chat-pane, before/after search pane:

```vue
<div v-if="focusDiagram && !isNarrow" class="split-divider"
  :class="{ dragging: diagramSplitResizing }"
  role="separator" aria-orientation="vertical" tabindex="0"
  @pointerdown="startDiagramSplitDrag"
  @dblclick="resetDiagramSplit"
  @keydown.left.prevent="nudgeDiagramSplit(-0.02)"
  @keydown.right.prevent="nudgeDiagramSplit(0.02)" />
<aside v-show="focusDiagram" class="diagram-focus-pane"
  :class="{ 'diagram-focus-pane--narrow': isNarrow }"
  :style="focusPaneStyle">
  <header class="diagram-focus-head">
    <span class="diagram-focus-title">{{ focusDiagram?.spec.title }}</span>
    <button class="diagram-focus-close" type="button" @click="closeDiagramFocus">×</button>
  </header>
  <div id="mg-diagram-focus-stage" ref="focusStageEl" class="diagram-focus-stage" />
</aside>
```

For Task 3 desktop only, `focusPaneStyle` returns `{ width: `${diagramSplitRatio * 100}%` }`; mobile style in Task 4.

- [ ] **Step 3: Add CSS**

```css
.diagram-embed { position: relative; }
.diagram-inline-placeholder { min-height: 220px; border: 1px dashed var(--line); border-radius: 8px; }
.diagram-focus-pane { flex:none; min-width:0; height:100%; display:flex; flex-direction:column; background:#05070a; border-left:1px solid var(--line); }
.diagram-focus-head { flex:none; display:flex; align-items:center; justify-content:space-between; padding:8px 12px; color:var(--text); }
.diagram-focus-stage { flex:1; min-height:0; overflow:hidden; display:flex; }
.diagram-focus-stage :deep(.diagram-block) { width:100%; height:100%; }
```

- [ ] **Step 4: Verify desktop behavior**

Run: `npx vue-tsc --noEmit && npm run build`
Expected: PASS.

Manual: double-click 2D/3D diagram; drag divider; click chat pane; Esc; confirm no duplicate 3D canvas and scroll returns.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/chat/ChatWorkspace.vue frontend/src/utils/diagramFocus.ts
git commit -m "feat: 桌面图解放大分屏"
```

---

### Task 4: 移动浮层与手势

**Files:**
- Modify: `frontend/src/components/chat/ChatWorkspace.vue`
- Modify: `frontend/src/utils/diagramFocus.ts` only if a pure helper is missing.

**Interfaces:**
- Consumes Task 1 `FocusPanel`, `clampFocusPanel`, `moveFocusPanel`, `resizeFocusPanel`, `isDoubleTap`.
- Produces `focusPanel: Ref<FocusPanel>`, `focusPaneStyle: ComputedRef<CSSProperties>`, `onDiagramPointerUp`, `onFocusPointerDown/Move/Up`.

- [ ] **Step 1: Add mobile state and style**

```ts
const focusPanel = ref<FocusPanel>({ x: 0, w: 90, h: 82, fullscreen: false })
const focusPaneStyle = computed<CSSProperties>(() => {
  if (!isNarrow.value) return { width: `${diagramSplitRatio.value * 100}%` }
  if (focusPanel.value.fullscreen) {
    return { left: '0', top: '0', width: '100vw', height: '100vh', transform: 'none' }
  }
  return {
    left: `calc(50% + ${focusPanel.value.x}px)`,
    top: '50%',
    width: `${focusPanel.value.w}vw`,
    height: `${focusPanel.value.h}vh`,
    transform: 'translate(-50%, -50%)',
  }
})
```

Add backdrop:

```vue
<div v-if="focusDiagram && isNarrow" class="diagram-focus-backdrop"
  @click="closeDiagramFocus" />
```

- [ ] **Step 2: Add double-tap and window gestures**

`onDiagramPointerUp(event, block, msgId)`: only `pointerType === 'touch'`; track active touch count; call `isDoubleTap(lastTap, next)`; if true open focus. Store `lastTap`.

Header handlers: pointer map; one pointer horizontal move via `moveFocusPanel`; two pointers scale via `resizeFocusPanel`; fullscreen swipe-down with `dy > 60` closes. `touch-action:none` on header. `@pointerdown.stop`, `@pointermove.stop`, `@pointerup.stop`, `@pointercancel.stop`.

- [ ] **Step 3: CSS**

```css
.diagram-focus-pane--narrow {
  position: fixed;
  z-index: 45;
  border-radius: 12px;
  overflow: hidden;
  box-shadow: 0 24px 80px rgba(0, 0, 0, 0.6);
}
.diagram-focus-backdrop {
  position: fixed;
  inset: 0;
  z-index: 44;
  background: rgba(3, 6, 12, 0.62);
  backdrop-filter: blur(2px);
}
.diagram-focus-head { touch-action: none; cursor: grab; }
```

When fullscreen, border-radius 0 and safe-area padding. Add transition only when snapping, not while dragging.

- [ ] **Step 4: Verify mobile**

Run: `npx vue-tsc --noEmit && npm run build`
Expected: PASS.

Manual at 390×844: double-tap open; pinch content; drag header; pinch header to 95vw; full screen; close ×; reopen; backdrop close; 3D rotation still works.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/chat/ChatWorkspace.vue frontend/src/utils/diagramFocus.ts
git commit -m "feat: 移动端图解放大浮层"
```

---

### Task 5: 互斥、回归与文档

**Files:**
- Modify: `frontend/src/components/chat/ChatWorkspace.vue`
- Modify: `docs/DIAGRAM_INVARIANTS.md` if behavior notes need updating.
- Test: `frontend/scripts/diagram-test.ts`

- [ ] **Step 1: Add search-pane restore test/manual**

If `searchOpen` and focus opens, `searchWasOpen=true`; close restores. Add a small pure helper if needed; otherwise manual check in research workspace.

- [ ] **Step 2: Run all checks**

```bash
cd frontend
npx vue-tsc --noEmit
npx esbuild scripts/diagram-test.ts --bundle --format=cjs --platform=node --outfile=.diagram-test.cjs
node .diagram-test.cjs
npx esbuild scripts/math-text-test.ts --bundle --format=cjs --platform=node --external:vite --external:vue --external:vue/server-renderer --outfile=.math-text-test.cjs
node .math-text-test.cjs
npm run build
cd ../backend
D:/Works/code/.venv/Scripts/python.exe -m pytest -q
```

Expected: all pass.

- [ ] **Step 3: Update docs**

Add a short section to `docs/DIAGRAM_INVARIANTS.md`: diagram focus is a view, not a new diagram; black surface; Teleport single instance; mobile fullscreen close rules.

- [ ] **Step 4: Commit**

```bash
git add docs/DIAGRAM_INVARIANTS.md frontend/scripts/diagram-test.ts frontend/src/components/chat/ChatWorkspace.vue
git commit -m "docs: 图解放大视图不变量"
```
