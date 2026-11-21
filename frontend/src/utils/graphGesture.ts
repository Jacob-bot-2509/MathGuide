/**
 * 图谱画布的缩放/平移数学(纯函数,便于单测)。
 *
 * 画布用 SVG viewBox 表达视口:view.w/h 越小,画面越放大。
 * 双指缩放与滚轮缩放共用同一套「围绕某点缩放」的公式,
 * 双指平移直接用两指中点的位移。
 */

export interface GestureView {
  x: number
  y: number
  w: number
  h: number
}

export interface Point {
  x: number
  y: number
}

export interface PinchMetrics {
  /** 两指间距(屏幕坐标) */
  distance: number
  /** 两指中点(屏幕坐标),作缩放锚点与平移基准 */
  mid: Point
}

export function pinchMetrics(a: Point, b: Point): PinchMetrics {
  return {
    distance: Math.hypot(b.x - a.x, b.y - a.y),
    mid: { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 },
  }
}

/** 围绕 point 缩放:factor > 1 缩小(视口变宽),< 1 放大。宽高受上下限夹紧。 */
export function zoomAround(
  view: GestureView,
  point: Point,
  factor: number,
  minWidth: number,
  maxWidth: number,
): void {
  const nextWidth = Math.min(Math.max(minWidth, view.w * factor), maxWidth)
  const scale = nextWidth / view.w
  view.x = point.x - (point.x - view.x) * scale
  view.y = point.y - (point.y - view.y) * scale
  view.w = nextWidth
  view.h *= scale
}

/** 按屏幕位移平移视口(手指右移 = 画布内容右移 = 视口 x 减小)。 */
export function panBy(view: GestureView, dx: number, dy: number): void {
  view.x -= dx
  view.y -= dy
}
