/** 图解放大:分栏比例、移动浮层几何与双击判定。 */

export interface FocusPanel {
  x: number
  w: number
  h: number
  fullscreen: boolean
}

export interface Viewport {
  width: number
  height: number
}

export interface TapPoint {
  time: number
  x: number
  y: number
}

export const DIAGRAM_SPLIT_DEFAULT = 0.62
export const DIAGRAM_CHAT_MIN = 360
export const DIAGRAM_MIN = 420
export const FOCUS_MIN_W = 70
export const FOCUS_MIN_H = 60
export const FOCUS_FULL_W = 95
export const FOCUS_FULL_H = 92

function clamp(value: number, low: number, high: number): number {
  return Math.min(high, Math.max(low, value))
}

/** 右侧图解分栏比例;空间不足时退回一个中间比例。 */
export function clampDiagramSplit(value: number, width: number): number {
  if (!Number.isFinite(width) || width <= 0) return DIAGRAM_SPLIT_DEFAULT
  if (width < DIAGRAM_CHAT_MIN + DIAGRAM_MIN) return clamp(value, 0.55, 0.7)
  return clamp(value, DIAGRAM_MIN / width, 1 - DIAGRAM_CHAT_MIN / width)
}

function fullscreenPanel(): FocusPanel {
  return { x: 0, w: 100, h: 100, fullscreen: true }
}

/** 移动浮层:限制尺寸和水平位置;达到阈值直接吸附全屏。 */
export function clampFocusPanel(panel: FocusPanel, viewport: Viewport): FocusPanel {
  if (panel.fullscreen || panel.w >= FOCUS_FULL_W || panel.h >= FOCUS_FULL_H) {
    return fullscreenPanel()
  }
  const w = clamp(panel.w, FOCUS_MIN_W, 100)
  const h = clamp(panel.h, FOCUS_MIN_H, 100)
  const maxX = Math.max(0, ((100 - w) * viewport.width) / 200)
  return {
    x: clamp(panel.x, -maxX, maxX),
    w,
    h,
    fullscreen: false,
  }
}

/** 单指左右拖拽浮层;全屏后不再移动。 */
export function moveFocusPanel(
  panel: FocusPanel,
  dx: number,
  viewport: Viewport,
): FocusPanel {
  if (panel.fullscreen) return panel
  return clampFocusPanel({ ...panel, x: panel.x + dx }, viewport)
}

/** 双指缩放浮层;只能放大到全屏,不能在全屏态缩回。 */
export function resizeFocusPanel(
  panel: FocusPanel,
  scale: number,
  viewport: Viewport,
): FocusPanel {
  if (panel.fullscreen) return panel
  if (!Number.isFinite(scale) || scale <= 0) return clampFocusPanel(panel, viewport)
  return clampFocusPanel({
    ...panel,
    w: panel.w * scale,
    h: panel.h * scale,
  }, viewport)
}

/** 两次轻点在时间、位移范围内才算双击/双点。 */
export function isDoubleTap(
  previous: TapPoint | null,
  next: TapPoint,
  maxDelay = 300,
  maxDistance = 10,
): boolean {
  if (!previous) return false
  const delay = next.time - previous.time
  if (delay < 0 || delay > maxDelay) return false
  return Math.hypot(next.x - previous.x, next.y - previous.y) <= maxDistance
}
