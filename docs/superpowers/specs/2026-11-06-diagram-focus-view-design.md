# 图解放大视图设计

日期：2026-11-06
状态：待确认
关联：[图解不变量](../../DIAGRAM_INVARIANTS.md) · [表示形式契约](../../REPRESENTATION_CONTRACT.md)

## 一、目标

聊天区当前图解最大宽度约 560px，复杂 2D/3D 图在消息流里偏小。增加一个“图解放大视图”：

- 聊天框内的图解本身也改为近黑背景，和放大舞台一致。
- 桌面端双击图解，进入左右分屏；聊天区被压缩，右侧是深色图解舞台。
- 移动端双击图解，弹出浮层窗口；浮层默认不铺满屏幕。
- 两端都保留图内拖拽、滚轮/双指缩放、3D 旋转、节点点击、重置视图。
- 关闭放大后回到原消息、原滚动位置。

## 二、非目标

- 不做第二个聊天窗口，不改变消息内容。
- 不重新生成图解，不改变 DiagramSpec。
- 不用 `window.open` 浏览器弹窗。
- 不持久化放大状态；刷新或关闭页面后恢复普通消息流。
- 不改变科研检索分栏的默认行为。

## 三、交互约定

### 桌面端（宽 ≥ 900px）

- 双击图解进入分屏。
- 左侧聊天区默认 38%，右侧图解区默认 62%。
- 中间分隔条可左右拖拽；支持左右键微调、双击复位。
- 分栏比例单独存 `mg-diagram-split`，不与 `mg-research-split` 混用。
- 最小宽度：聊天 360px，图解 420px；空间不足时按比例压缩。
- 点击左侧聊天区任意位置、点击右上角关闭、按 `Esc` 结束放大。
- 图内点击不关闭；拖拽、缩放、3D 旋转不关闭。

### 移动端（宽 < 900px）

- 双击屏幕图解进入浮层。
- 初始窗口约 `90vw × 82vh`，居中，四周留边，背景遮罩压暗。
- 单指拖标题栏：左右移动窗口，限制在屏幕内。
- 标题栏/边缘双指：缩放窗口；最小约 `70vw × 60vh`。
- 宽达到约 `95vw` 或高达到约 `92vh` 时，自动吸附为 `100vw × 100vh` 全屏，带短过渡。
- 全屏后不再缩小或移动；图内双指缩放/平移、3D 旋转照常。
- 点击遮罩、右上角关闭结束；全屏时用右上角关闭或下滑手势结束。
- 图内双指只缩放图内容，不缩放窗口；窗口缩放只在标题栏/边缘手势区发生。

### 两端共同

- 双击判定带移动阈值：按下后移动超过约 8px 视为拖拽，不触发放大。
- 移动端双点判定：两次轻点间隔 ≤ 300ms、位置差 ≤ 10px、期间没有多指。
- `Esc` 关闭桌面分屏；移动端不依赖键盘。
- 放大区外点击才关闭；图内交互不关闭。

## 四、布局

```text
桌面：
┌──────────────────────────────────────────────┐
│ ChatWorkspace header                          │
├───────────────────────┬──────────────────────┤
│ chat-pane             │ diagram-focus-pane    │
│ 38%                   │ 62%                   │
│                       │ ┌ title     [×] ┐    │
│                       │ │                │    │
│                       │ │   diagram      │    │
│                       │ │                │    │
├───────────────────────┴──────────────────────┤
│ input-bar                                    │
└──────────────────────────────────────────────┘

移动：
┌──────────────────────────────┐
│ 聊天页(压暗)                 │
│    ┌────────────────────┐    │
│    │ title          [×] │    │
│    │                    │    │
│    │      diagram       │    │
│    │                    │    │
│    └────────────────────┘    │
└──────────────────────────────┘
```

- 右侧舞台背景统一用近黑 `#05070a`，图解容器透明。
- 聊天框内的图解容器同样用 `#05070a`，不再跟随聊天卡片的 `--bg-card`。
- 图解容器建立局部深色 token 作用域：`--bg-card/--bg-panel/--text/--text-dim/--line/--cyan` 使用深色主题值，保证浅色主题下坐标轴、标签、节点仍可读。
- 桌面 `diagram-focus-pane` 是 `workspace-body` 的 flex 子项，和现有 `search-pane` 同级。
- 移动端 `diagram-focus-pane` 用 `position: fixed`，`focus-backdrop` 在它下面。
- 焦点舞台 `min-height: 0; overflow: hidden; display: flex;`，图填充剩余高度。

## 五、组件与状态

### ChatWorkspace

新增状态：

- `focusDiagram: DiagramBlock | null`：当前放大的图。
- `focusOrigin: { msgId: number; scrollTop: number } | null`：关闭后回滚位置。
- `diagramSplitRatio`、`diagramSplitResizing`。
- `isNarrow`：`matchMedia('(max-width: 899px)')` 响应式。
- `focusPanel: { x: number; w: number; h: number; fullscreen: boolean }`：移动端窗口几何。
- `searchWasOpen`：放大前科研检索分栏是否打开。

行为：

- `openDiagramFocus(block)`：记录来源、关闭 `searchOpen`（记住状态）、设置 `focusDiagram`。
- `closeDiagramFocus()`：清空 focus、恢复检索分栏、回滚 `listEl.scrollTop`。
- `startDiagramSplitDrag` / `nudgeDiagramSplit` / `resetDiagramSplit`：复用现有 split 逻辑，独立 key。
- `isNarrow` 变化时切换布局；进入窄屏时重置移动窗口几何。
- 如果当前消息被删除，自动关闭 focus。

### 单实例与 Teleport

不复制 `DiagramSvg` / `Diagram3D` / GeoGebra 内核实例：

- `ChatWorkspace` 始终渲染一个空舞台 `#mg-diagram-focus-stage`（`v-show` 控制面板显示）。
- 消息里的 `DiagramBlock` 用 `<Teleport to="#mg-diagram-focus-stage" :disabled="!isFocused">`。
- 未放大时 Teleport 禁用，图留在消息内；放大时同一组件移动到右侧舞台。
- 消息内保留占位，避免布局跳动。
- 组件实例不销毁，2D viewBox、3D 相机/缩放、GeoGebra 内核结果都保留。
- 关闭时 Teleport 禁用，组件回到原位。

### DiagramBlock / Diagram3D

- `DiagramBlock` 新增 `focused?: boolean`：
  - 去掉 `max-width: 560px`，改为 `height: 100%`。
  - 2D 容器 `max-height: none`，SVG 填充舞台。
  - 焦点模式隐藏图注重复或保留单份标题。
- `Diagram3D` 新增 `focused?: boolean`：
  - `.diagram-3d-wrap` 取消 `max-width: 480px`，宽高 100%。
  - `.diagram-3d` 高度 100%，最小高度 0。
  - 复用现有 `ResizeObserver`，分栏拖动后自动 `setSize`、更新 aspect。
- `GeoGebra3DKernelBlock` 透传 `focused` 给 `Diagram3D`。
- `GeoGebraKernelBlock` 的加载态/失败态在焦点模式下取消 560px 上限。

### 手势工具

新增 `frontend/src/utils/diagramFocus.ts`（纯函数，便于测试）：

- `clampDiagramSplit(value, width, { chatMin, diagramMin })`
- `clampFocusPanel(panel, viewport)`
- `nextFocusPanel(panel, gesture)`：处理移动端左右移动/双指缩放/全屏吸附。
- `isDoubleTap(previous, next)`：时间、位移、多指判定。

组件只负责事件采集和样式，纯几何计算放在工具里。

## 六、与现有分栏的关系

- `searchOpen` 与 `focusDiagram` 互斥。
- 打开图解放大时：
  - 若科研检索分栏打开，记录 `searchWasOpen=true`，关闭检索。
  - 图解关闭后恢复检索分栏。
- 窄屏下科研检索本来就切独立页，不参与此互斥。
- 两个分栏使用各自的比例 key 和拖拽函数，互不覆盖。

## 七、可访问性

- 桌面分隔条保留 `role="separator"`、`aria-orientation="vertical"`、`tabindex="0"`。
- 关闭按钮有 `aria-label`；移动浮层加 `role="dialog"` 和 `aria-modal="true"`。
- 打开时焦点移到关闭按钮；关闭后焦点回到原图解。
- `Esc` 关闭。
- 双击/双点之外，保留键盘可触发的关闭和分隔条微调。

## 八、边界与失败处理

- 3D 上下文丢失：沿用现有错误提示，不因放大崩溃。
- 图解渲染失败：`DiagramBoundary` 仍只影响这一张图，焦点舞台显示失败提示。
- 窗口尺寸小于最小分栏宽：桌面自动回退移动端浮层；不出现负宽。
- 浏览器不支持 `matchMedia`：按桌面处理。
- 全屏浮层没有“区外”：必须保留关闭按钮；下滑手势作为补充。
- 焦点状态下用户继续发消息：消息流正常更新，焦点图不随流式内容重排。

## 九、测试

纯函数测试（`diagram-test.ts`）：

- `clampDiagramSplit` 在空间不足时的比例。
- `clampFocusPanel` 不越界。
- 双指缩放达到阈值时 `fullscreen=true`。
- 双击/双点判定：移动超阈值不触发，多指不触发。

手动/浏览器验证：

- 桌面 2D：双击放大、拖分隔条、图内缩放、点左侧关闭、Esc 关闭、回到原滚动位置。
- 桌面 3D：双击放大、OrbitControls 旋转、分栏拖动后画面不拉伸、关闭恢复。
- 桌面 GeoGebra 2D/3D：放大不重复触发内核/不出现两个画布。
- 移动端 2D/3D：双击打开、图内双指缩放、标题栏左右移动、双指放大到阈值自动全屏、遮罩关闭、全屏关闭。
- 科研区：检索分栏打开时放图，关闭后检索分栏恢复。
- 浅色主题：聊天内图解和放大舞台均为黑底，坐标轴/标签/节点对比度正常。
- `vue-tsc --noEmit`、Vite build、现有全量测试。

## 十、实施顺序

1. `diagramFocus.ts` 纯函数与测试。
2. `DiagramBlock` / `Diagram3D` focus 样式与 props。
3. ChatWorkspace 分屏、分隔条、Teleport、状态与关闭回滚。
4. 移动端浮层、手势、全屏吸附。
5. 科研检索分栏互斥与恢复。
6. 浏览器验证、文档、发布。

## 十一、已定决策

- 桌面分屏，移动浮层。
- 双击/双点打开，放大区外关闭。
- 桌面分隔条可拖拽；移动窗口可左右移动、双指缩放、达到阈值全屏。
- 图内手势与窗口手势分区。
- 单实例 Teleport，不复制 3D/GeoGebra。
- 聊天内图解和放大舞台统一黑底，浅色主题下用局部深色 token 保证可读性。

## 十二、留给实现的选择

- 移动端全屏下滑关闭的触发距离（建议 60–80px）。
- 焦点标题是否隐藏 `DiagramBlock` 内部图注，避免与头部标题重复。
- 分栏拖动时是否对 3D resize 做帧节流（建议交给 `ResizeObserver`，必要时加 `requestAnimationFrame`）。
