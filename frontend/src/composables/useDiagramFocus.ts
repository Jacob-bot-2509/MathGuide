/** 图解放大:窄屏浮层几何、触控手势、宽屏右侧分栏,以及关闭后的焦点还原。
 *
 * 抽出来的理由:这块逻辑自带 pointer 手势与 media query,和消息内容、发送流程无关,
 * 却因为「关闭后要滚回原位置」而依赖消息列表 —— 依赖一律由参数注入,
 * 组件只负责把 ref 和模板事件接上。
 *
 * 边界约定:
 * - 几何计算全部在 utils/diagramFocus(有单测),这里只持有响应式状态;
 * - 与右侧检索分栏共用右侧空间,谁打开谁占位,另一个收起(通过 searchOpen 协调)。
 */
import {
  computed,
  nextTick,
  onBeforeUnmount,
  onMounted,
  ref,
  type CSSProperties,
  type Ref,
} from 'vue'
import type { DiagramBlock } from '@/utils/diagramSpec'
import {
  DIAGRAM_SPLIT_DEFAULT,
  clampDiagramSplit,
  isDoubleTap,
  moveFocusPanel,
  resizeFocusPanel,
  tapMoved,
  type FocusPanel,
  type TapPoint,
} from '@/utils/diagramFocus'
import { parseStoredRatio } from '@/utils/splitPane'

const DIAGRAM_SPLIT_KEY = 'mg-diagram-split'
/** 窄屏浮层初始尺寸(vw/vh):留出上下误触边距 */
const PANEL_W = 90
const PANEL_H = 82
/** 全屏态向上滑动超过这个距离才关闭,避免误触 */
const SWIPE_CLOSE_PX = 60

export interface DiagramFocusOptions {
  /** 分栏容器:宽屏时按它的宽度把右栏比例夹到可用区间。 */
  bodyRef: Ref<HTMLElement | null>
  /** 消息列表:放大前记住滚动位置,关闭后滚回并回焦到原图。 */
  listEl: Ref<HTMLElement | null>
  /** 关闭按钮:打开放大后把键盘焦点移过去,方便直接 Esc/回车关闭。 */
  closeEl: Ref<HTMLButtonElement | null>
  /** 右侧检索分栏开关:两者共用右侧,打开一个要让另一个收起来。 */
  searchOpen: Ref<boolean>
}

interface FocusGesture {
  pointers: Map<number, { x: number; y: number }>
  startX: number
  startY: number
  startW: number
  startH: number
  startPanelX: number
  startDistance: number
  fullscreen: boolean
  sawMulti: boolean
}

export function useDiagramFocus(options: DiagramFocusOptions) {
  const focusDiagram = ref<DiagramBlock | null>(null)
  /** 放大来源:关闭后据此滚回原位并回焦到原图 */
  const focusOrigin = ref<{ msgId: number; diagramId: string; scrollTop: number } | null>(null)
  const diagramSplitRatio = ref(loadDiagramSplit())
  const diagramSplitResizing = ref(false)
  /** 进放大前检索栏是否开着:关闭放大后要还原 */
  const searchWasOpen = ref(false)
  const narrowQuery = typeof window.matchMedia === 'function'
    ? window.matchMedia('(max-width: 899px)') : null
  const isNarrow = ref(narrowQuery?.matches ?? false)
  const focusPanel = ref<FocusPanel>(initPanel())
  const lastTap = ref<(TapPoint & { diagramId: string; msgId: number }) | null>(null)
  const touchPointers = new Map<number, { x: number; y: number; moved: boolean }>()
  let touchWasMulti = false
  let focusGesture: FocusGesture | null = null

  function initPanel(): FocusPanel {
    return { x: 0, w: PANEL_W, h: PANEL_H, fullscreen: false }
  }

  function viewport(): { width: number; height: number } {
    return { width: window.innerWidth, height: window.innerHeight }
  }

  const focusPaneStyle = computed<CSSProperties>(() => {
    if (!isNarrow.value) return { width: `${diagramSplitRatio.value * 100}%` }
    if (focusPanel.value.fullscreen) {
      return {
        left: '0',
        top: '0',
        width: '100vw',
        height: '100vh',
        transform: 'none',
        borderRadius: '0',
      }
    }
    return {
      left: `calc(50% + ${focusPanel.value.x}px)`,
      top: '50%',
      width: `${focusPanel.value.w}vw`,
      height: `${focusPanel.value.h}vh`,
      transform: 'translate(-50%, -50%)',
    }
  })

  /* ---------- 宽屏:右侧分栏 ---------- */

  function loadDiagramSplit(): number {
    try {
      return clampDiagramSplitForBody(
        parseStoredRatio(localStorage.getItem(DIAGRAM_SPLIT_KEY), DIAGRAM_SPLIT_DEFAULT),
      )
    } catch {
      return DIAGRAM_SPLIT_DEFAULT
    }
  }

  function clampDiagramSplitForBody(value: number): number {
    return clampDiagramSplit(value, options.bodyRef.value?.clientWidth ?? 0)
  }

  function saveDiagramSplit(): void {
    try {
      localStorage.setItem(DIAGRAM_SPLIT_KEY, String(diagramSplitRatio.value))
    } catch {
      /* 隐私模式/配额写满:记不住不影响当前会话 */
    }
  }

  function startDiagramSplitDrag(e: PointerEvent): void {
    const body = options.bodyRef.value
    if (!body) return
    e.preventDefault()
    diagramSplitResizing.value = true
    const rect = body.getBoundingClientRect()
    const move = (ev: PointerEvent) => {
      diagramSplitRatio.value = clampDiagramSplitForBody(
        (rect.right - ev.clientX) / rect.width,
      )
    }
    const up = () => {
      diagramSplitResizing.value = false
      window.removeEventListener('pointermove', move)
      window.removeEventListener('pointerup', up)
      saveDiagramSplit()
    }
    window.addEventListener('pointermove', move)
    window.addEventListener('pointerup', up)
  }

  function nudgeDiagramSplit(delta: number): void {
    diagramSplitRatio.value = clampDiagramSplitForBody(diagramSplitRatio.value + delta)
    saveDiagramSplit()
  }

  function resetDiagramSplit(): void {
    diagramSplitRatio.value = clampDiagramSplitForBody(DIAGRAM_SPLIT_DEFAULT)
    saveDiagramSplit()
  }

  /** 窗口由窄变宽后重新夹一次(此时才量得到容器宽度)。 */
  function reclampSplitIfWide(): void {
    if (focusDiagram.value && window.innerWidth >= 900) {
      diagramSplitRatio.value = clampDiagramSplitForBody(diagramSplitRatio.value)
    }
  }

  /* ---------- 开关与焦点还原 ---------- */

  function isFocused(block: DiagramBlock): boolean {
    return focusDiagram.value?.id === block.id
  }

  function openDiagramFocus(block: DiagramBlock, msgId: number): void {
    if (focusDiagram.value?.id === block.id) return
    focusOrigin.value = {
      msgId,
      diagramId: block.id,
      scrollTop: options.listEl.value?.scrollTop ?? 0,
    }
    searchWasOpen.value = options.searchOpen.value
    if (options.searchOpen.value) options.searchOpen.value = false
    if (!isNarrow.value) diagramSplitRatio.value = clampDiagramSplitForBody(diagramSplitRatio.value)
    if (isNarrow.value) focusPanel.value = initPanel()
    lastTap.value = null
    focusDiagram.value = block
    nextTick(() => options.closeEl.value?.focus())
  }

  /**
   * 关闭放大,并把滚动位置与键盘焦点还回原图。
   *
   * restoreSearch=false 用于「从放大直接开检索」:此时检索栏由调用方接管,
   * 不该在关闭瞬间又被还原一次(否则刚开的检索会被覆盖)。
   */
  function closeDiagramFocus(opts: { restoreSearch?: boolean } = {}): void {
    if (!focusDiagram.value) return
    const restoreFocus = !!document.activeElement?.closest('.diagram-focus-pane')
    focusDiagram.value = null
    lastTap.value = null
    touchPointers.clear()
    touchWasMulti = false
    focusGesture = null
    if (opts.restoreSearch !== false && searchWasOpen.value && !isNarrow.value) {
      options.searchOpen.value = true
    }
    searchWasOpen.value = false
    const origin = focusOrigin.value
    focusOrigin.value = null
    nextTick(() => {
      const list = options.listEl.value
      if (!origin || !list) return
      list.scrollTop = origin.scrollTop
      if (!restoreFocus) return
      const message = list.querySelector(`[data-msg-id="${origin.msgId}"]`)
      const diagram = [...(message?.querySelectorAll<HTMLElement>('.diagram-embed') ?? [])]
        .find((el) => el.dataset.diagramId === origin.diagramId)
      diagram?.focus({ preventScroll: true })
    })
  }

  function onChatPaneClick(): void {
    if (focusDiagram.value) closeDiagramFocus()
  }

  /** 点浮层外面收起;点浮层内部(.diagram-focus-pane)不处理 */
  function onRootClick(event: MouseEvent): void {
    if (!focusDiagram.value) return
    const target = event.target as HTMLElement | null
    if (target?.closest('.diagram-focus-pane')) return
    closeDiagramFocus()
  }

  function onFocusKeydown(event: KeyboardEvent): void {
    if (event.key === 'Escape' && focusDiagram.value) {
      event.preventDefault()
      closeDiagramFocus()
    }
  }

  function onNarrowChange(event: MediaQueryListEvent): void {
    isNarrow.value = event.matches
    if (event.matches) focusPanel.value = initPanel()
  }

  /* ---------- 消息内嵌图:双击/双指双击放大 ---------- */

  function onDiagramPointerDown(event: PointerEvent): void {
    if (event.pointerType !== 'touch') return
    touchPointers.set(event.pointerId, { x: event.clientX, y: event.clientY, moved: false })
    if (touchPointers.size > 1) {
      touchWasMulti = true
      lastTap.value = null
    }
  }

  function onDiagramPointerMove(event: PointerEvent): void {
    const start = touchPointers.get(event.pointerId)
    if (start && tapMoved(start, { x: event.clientX, y: event.clientY })) start.moved = true
  }

  function onDiagramPointerCancel(event: PointerEvent): void {
    touchPointers.delete(event.pointerId)
    if (!touchPointers.size) touchWasMulti = false
    lastTap.value = null
  }

  function onDiagramPointerUp(
    event: PointerEvent,
    block: DiagramBlock,
    msgId: number,
  ): void {
    if (event.pointerType !== 'touch') return
    const start = touchPointers.get(event.pointerId)
    touchPointers.delete(event.pointerId)
    const invalid = !start || start.moved || tapMoved(start, { x: event.clientX, y: event.clientY })
      || touchWasMulti || !!focusDiagram.value || !isNarrow.value
    if (!touchPointers.size) touchWasMulti = false
    if (invalid) {
      lastTap.value = null
      return
    }
    const tap = {
      time: performance.now(),
      x: event.clientX,
      y: event.clientY,
      diagramId: block.id,
      msgId,
    }
    if (lastTap.value?.diagramId === block.id && lastTap.value.msgId === msgId
      && isDoubleTap(lastTap.value, tap)) {
      lastTap.value = null
      openDiagramFocus(block, msgId)
    } else {
      lastTap.value = tap
    }
  }

  /* ---------- 浮层手势:单指拖动 / 双指缩放 / 全屏下滑关闭 ---------- */

  /** 双指间距,作为缩放基准;不足两指时为 0(调用方据此跳过缩放) */
  function focusDistance(points: Map<number, { x: number; y: number }>): number {
    const values = [...points.values()]
    if (values.length < 2) return 0
    return Math.hypot(values[0].x - values[1].x, values[0].y - values[1].y)
  }

  function onFocusPointerDown(event: PointerEvent): void {
    if (!isNarrow.value) return
    event.preventDefault()
    ;(event.currentTarget as HTMLElement).setPointerCapture?.(event.pointerId)
    if (!focusGesture) {
      focusGesture = {
        pointers: new Map(),
        startX: event.clientX,
        startY: event.clientY,
        startW: focusPanel.value.w,
        startH: focusPanel.value.h,
        startPanelX: focusPanel.value.x,
        startDistance: 0,
        fullscreen: focusPanel.value.fullscreen,
        sawMulti: false,
      }
    }
    focusGesture.pointers.set(event.pointerId, {
      x: event.clientX,
      y: event.clientY,
    })
    if (focusGesture.pointers.size === 1) {
      focusGesture.startX = event.clientX
      focusGesture.startY = event.clientY
      focusGesture.startPanelX = focusPanel.value.x
    } else if (focusGesture.pointers.size === 2) {
      focusGesture.sawMulti = true
      focusGesture.startDistance = focusDistance(focusGesture.pointers)
      focusGesture.startW = focusPanel.value.w
      focusGesture.startH = focusPanel.value.h
    }
  }

  function onFocusPointerMove(event: PointerEvent): void {
    if (!focusGesture || !focusGesture.pointers.has(event.pointerId)) return
    focusGesture.pointers.set(event.pointerId, {
      x: event.clientX,
      y: event.clientY,
    })
    if (focusGesture.pointers.size >= 2) {
      if (focusPanel.value.fullscreen || focusGesture.startDistance <= 0) return
      const scale = focusDistance(focusGesture.pointers) / focusGesture.startDistance
      focusPanel.value = resizeFocusPanel({
        x: focusGesture.startPanelX,
        w: focusGesture.startW,
        h: focusGesture.startH,
        fullscreen: false,
      }, scale, viewport())
      return
    }
    if (focusPanel.value.fullscreen) return
    const dx = event.clientX - focusGesture.startX
    focusPanel.value = moveFocusPanel({
      ...focusPanel.value,
      x: focusGesture.startPanelX,
    }, dx, viewport())
  }

  function onFocusPointerUp(event: PointerEvent): void {
    if (!focusGesture) return
    const gesture = focusGesture
    const point = gesture.pointers.get(event.pointerId)
    gesture.pointers.delete(event.pointerId)
    if (gesture.pointers.size === 1) {
      // 双指退回单指:以剩下的手指为新起点,避免浮层瞬移
      const remaining = [...gesture.pointers.values()][0]
      gesture.startX = remaining.x
      gesture.startY = remaining.y
      gesture.startPanelX = focusPanel.value.x
      gesture.startW = focusPanel.value.w
      gesture.startH = focusPanel.value.h
      gesture.sawMulti = true
    }
    if (gesture.pointers.size === 0) {
      focusGesture = null
      if (gesture.fullscreen && !gesture.sawMulti && point
        && event.clientY - gesture.startY > SWIPE_CLOSE_PX) {
        closeDiagramFocus()
      }
    }
  }

  function onFocusPointerCancel(event: PointerEvent): void {
    if (!focusGesture) return
    focusGesture.pointers.delete(event.pointerId)
    if (focusGesture.pointers.size === 0) focusGesture = null
  }

  /* ---------- 全局监听:Esc 关闭、窗口宽度切换 ---------- */

  onMounted(() => {
    window.addEventListener('keydown', onFocusKeydown)
    narrowQuery?.addEventListener?.('change', onNarrowChange)
  })

  onBeforeUnmount(() => {
    window.removeEventListener('keydown', onFocusKeydown)
    narrowQuery?.removeEventListener?.('change', onNarrowChange)
  })

  return {
    focusDiagram,
    diagramSplitResizing,
    searchWasOpen,
    isNarrow,
    focusPanel,
    focusPaneStyle,
    isFocused,
    openDiagramFocus,
    closeDiagramFocus,
    onChatPaneClick,
    onRootClick,
    startDiagramSplitDrag,
    nudgeDiagramSplit,
    resetDiagramSplit,
    reclampSplitIfWide,
    onDiagramPointerDown,
    onDiagramPointerMove,
    onDiagramPointerUp,
    onDiagramPointerCancel,
    onFocusPointerDown,
    onFocusPointerMove,
    onFocusPointerUp,
    onFocusPointerCancel,
  }
}
