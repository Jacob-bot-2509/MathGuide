/** 图解文字布局:先量文字,再在锚点四周找不压图形、不压其他标签的位置。 */

import type { DiagramShape } from './diagramSpec'

export type Side = 'top' | 'bottom' | 'left' | 'right'

export interface Rect {
  x: number
  y: number
  w: number
  h: number
}

export interface LabelRequest {
  id: string
  text: string
  anchorX: number
  anchorY: number
  role?: 'annotation' | 'shape' | 'axis' | 'edge'
  fontSize?: number
  maxWidth?: number
  maxLines?: number
  priority?: number
  /** 主体图形的包围盒;标注优先排到它外面。 */
  figure?: Rect | null
  /** 与 figure 相交的惩罚权重;0 表示不关心。 */
  figureWeight?: number
  preferred?: Side[]
  /** 轴名等固定标签:不移动,只占位。 */
  fixed?: boolean
}

export interface PlacedLabel {
  id: string
  text: string
  role: 'annotation' | 'shape' | 'axis' | 'edge'
  lines: string[]
  x: number
  y: number
  w: number
  h: number
  anchorX: number
  anchorY: number
  fontSize: number
  lineHeight: number
  side: Side | 'center'
  leader: boolean
}

export interface ScreenLabelRequest {
  id: string
  anchorX: number
  anchorY: number
  width: number
  height: number
  priority?: number
  fixed?: boolean
  avoidRect?: Rect | null
  avoidWeight?: number
  preferred?: Side[]
}

export interface ScreenLabelPlacement {
  id: string
  x: number
  y: number
  w: number
  h: number
  centerX: number
  centerY: number
  side: Side | 'center'
  leader: boolean
  overlapsAvoid: boolean
  overlapsLabel: boolean
}

const CJK_RE = /[　-鿿＀-￯]/
const ELLIPSIS = '…'

export function charWidth(ch: string, fontSize: number): number {
  if (CJK_RE.test(ch)) return fontSize
  if (ch === ' ') return fontSize * 0.34
  if (/[.,:;']/u.test(ch)) return fontSize * 0.32
  if ('()[]{}<>+-*/=^_|'.includes(ch)) return fontSize * 0.48
  return fontSize * 0.6
}

export function measureTextWidth(text: string, fontSize: number): number {
  let width = 0
  for (const ch of Array.from(text)) width += charWidth(ch, fontSize)
  return width
}

function truncateLine(text: string, maxWidth: number, fontSize: number): string {
  const chars = Array.from(text)
  const dotWidth = charWidth(ELLIPSIS, fontSize)
  let width = 0
  let out = ''
  for (const ch of chars) {
    const next = charWidth(ch, fontSize)
    if (out && width + next > Math.max(1, maxWidth - dotWidth)) break
    out += ch
    width += next
  }
  return out.length < chars.length ? `${out}${ELLIPSIS}` : out
}

export interface MeasuredLabel {
  lines: string[]
  w: number
  h: number
  fontSize: number
  lineHeight: number
}

export function measureLabel(request: LabelRequest): MeasuredLabel {
  const fontSize = Math.max(8, request.fontSize ?? 10)
  const lineHeight = Math.round(fontSize * 1.28)
  const maxWidth = Math.max(fontSize * 2, request.maxWidth ?? 160)
  const maxLines = Math.max(1, Math.floor(request.maxLines ?? 3))
  const chars = Array.from(request.text.trim())
  const lines: string[] = []
  let current = ''
  let currentWidth = 0
  for (let index = 0; index < chars.length; index += 1) {
    const ch = chars[index]
    const width = charWidth(ch, fontSize)
    if (current && currentWidth + width > maxWidth) {
      lines.push(current)
      current = ''
      currentWidth = 0
      if (lines.length >= maxLines) {
        lines[maxLines - 1] = truncateLine(
          `${lines[maxLines - 1]}${chars.slice(index).join('')}`,
          maxWidth,
          fontSize,
        )
        return {
          lines,
          w: Math.max(1, ...lines.map((line) => measureTextWidth(line, fontSize))) + 4,
          h: lines.length * lineHeight + 2,
          fontSize,
          lineHeight,
        }
      }
    }
    current += ch
    currentWidth += width
  }
  if (current) lines.push(current)
  if (!lines.length) lines.push('')
  return {
    lines,
    w: Math.max(1, ...lines.map((line) => measureTextWidth(line, fontSize))) + 4,
    h: lines.length * lineHeight + 2,
    fontSize,
    lineHeight,
  }
}

export function overlapArea(a: Rect, b: Rect): number {
  const left = Math.max(a.x, b.x)
  const right = Math.min(a.x + a.w, b.x + b.w)
  const top = Math.max(a.y, b.y)
  const bottom = Math.min(a.y + a.h, b.y + b.h)
  return Math.max(0, right - left) * Math.max(0, bottom - top)
}

export function pointRectDistance(rect: Rect, x: number, y: number): number {
  const dx = Math.max(rect.x - x, 0, x - (rect.x + rect.w))
  const dy = Math.max(rect.y - y, 0, y - (rect.y + rect.h))
  return Math.hypot(dx, dy)
}

function clamp(value: number, low: number, high: number): number {
  return Math.min(high, Math.max(low, value))
}

function sideOf(dx: number, dy: number): Side {
  if (Math.abs(dx) >= Math.abs(dy)) return dx < 0 ? 'left' : 'right'
  return dy < 0 ? 'top' : 'bottom'
}

interface Candidate {
  rect: Rect
  side: Side | 'center'
  distance: number
}

function localCandidates(
  request: LabelRequest,
  label: MeasuredLabel,
  gaps: number[],
): Candidate[] {
  const out: Candidate[] = []
  const { anchorX: ax, anchorY: ay } = request
  const { w, h } = label
  for (const gap of gaps) {
    const boxes: Array<[number, number, Side]> = [
      [ax - w / 2, ay - gap - h, 'top'],
      [ax - w / 2, ay + gap, 'bottom'],
      [ax - gap - w, ay - h / 2, 'left'],
      [ax + gap, ay - h / 2, 'right'],
      [ax - gap - w, ay - gap - h, 'left'],
      [ax + gap, ay - gap - h, 'right'],
      [ax - gap - w, ay + gap, 'left'],
      [ax + gap, ay + gap, 'right'],
    ]
    for (const [x, y, side] of boxes) {
      const rect = { x, y, w, h }
      out.push({
        rect,
        side,
        distance: pointRectDistance(rect, ax, ay),
      })
    }
  }
  return out
}

function figureCandidates(
  request: LabelRequest,
  label: MeasuredLabel,
  gaps: number[],
): Candidate[] {
  const figure = request.figure
  if (!figure) return []
  const out: Candidate[] = []
  const { anchorX: ax, anchorY: ay } = request
  const { w, h } = label
  const centerX = figure.x + figure.w / 2
  const centerY = figure.y + figure.h / 2
  for (const gap of gaps) {
    // 优先落在主体外围的上/下/左/右,让多条说明自然分散。
    const boxes: Array<[number, number, Side]> = [
      [
        clamp(ax, figure.x + w / 2, figure.x + figure.w - w / 2) - w / 2,
        figure.y - gap - h,
        'top',
      ],
      [
        clamp(ax, figure.x + w / 2, figure.x + figure.w - w / 2) - w / 2,
        figure.y + figure.h + gap,
        'bottom',
      ],
      [
        figure.x - gap - w,
        clamp(ay, figure.y + h / 2, figure.y + figure.h - h / 2) - h / 2,
        'left',
      ],
      [
        figure.x + figure.w + gap,
        clamp(ay, figure.y + h / 2, figure.y + figure.h - h / 2) - h / 2,
        'right',
      ],
    ]
    for (const [x, y, side] of boxes) {
      const rect = { x, y, w, h }
      out.push({
        rect,
        side,
        distance: pointRectDistance(rect, ax, ay),
      })
    }
    // 锚点离主体中心越远,越应该从对应角落排出,避免所有标签挤同一侧。
    const cornerX = ax < centerX ? figure.x - gap - w : figure.x + figure.w + gap
    const cornerY = ay < centerY ? figure.y - gap - h : figure.y + figure.h + gap
    out.push({
      rect: { x: cornerX, y: cornerY, w, h },
      side: sideOf(cornerX + w / 2 - ax, cornerY + h / 2 - ay),
      distance: pointRectDistance({ x: cornerX, y: cornerY, w, h }, ax, ay),
    })
  }
  return out
}

function scoreCandidate(
  candidate: Candidate,
  request: LabelRequest,
  bounds: Rect,
  obstacles: Rect[],
  placed: Rect[],
  sideUse: Record<Side, number>,
): number {
  const rect = candidate.rect
  let score = candidate.distance * 0.2
  const overflowX = Math.max(0, bounds.x - rect.x)
    + Math.max(0, rect.x + rect.w - (bounds.x + bounds.w))
  const overflowY = Math.max(0, bounds.y - rect.y)
    + Math.max(0, rect.y + rect.h - (bounds.y + bounds.h))
  score += (overflowX + overflowY) * 1e7
  for (const other of placed) {
    const area = overlapArea(rect, other)
    if (area > 0) score += 1e6 + area * 1e4
    else if (pointRectDistance(other, rect.x, rect.y) < 2) score += 200
  }
  for (const obstacle of obstacles) {
    const area = overlapArea(rect, obstacle)
    if (area > 0) score += 40000 + area * 200
  }
  if (request.figure && (request.figureWeight ?? 0) > 0) {
    const area = overlapArea(rect, request.figure)
    if (area > 0) score += (request.figureWeight ?? 0) * (area + 240)
  }
  if (rect.x <= request.anchorX && request.anchorX <= rect.x + rect.w
    && rect.y <= request.anchorY && request.anchorY <= rect.y + rect.h) {
    score += 50000
  }
  if (request.preferred?.length) {
    const index = request.preferred.indexOf(candidate.side as Side)
    if (index < 0) score += 80
    else score += index * 24
  }
  if (candidate.side !== 'center') score += (sideUse[candidate.side] || 0) * 7
  return score
}

export function placeLabels(
  requests: LabelRequest[],
  obstacles: Rect[],
  bounds: Rect,
): PlacedLabel[] {
  const ordered = [...requests].sort((a, b) => (
    (b.priority ?? 1) - (a.priority ?? 1) || a.id.localeCompare(b.id)
  ))
  const placed: Rect[] = []
  const sideUse: Record<Side, number> = { top: 0, bottom: 0, left: 0, right: 0 }
  const byId = new Map<string, PlacedLabel>()
  const gaps = [8, 16, 26, 40, 60]

  for (const request of ordered) {
    const label = measureLabel(request)
    const role = request.role ?? 'annotation'
    if (request.fixed) {
      const rect = {
        x: request.anchorX - label.w / 2,
        y: request.anchorY - label.h / 2,
        w: label.w,
        h: label.h,
      }
      placed.push(rect)
      byId.set(request.id, {
        id: request.id,
        text: request.text,
        role,
        lines: label.lines,
        ...rect,
        anchorX: request.anchorX,
        anchorY: request.anchorY,
        fontSize: label.fontSize,
        lineHeight: label.lineHeight,
        side: 'center',
        leader: false,
      })
      continue
    }
    const candidates = [
      ...localCandidates(request, label, gaps),
      ...figureCandidates(request, label, [8, 16, 26, 40]),
    ]
    let best = candidates[0]
    let bestScore = Number.POSITIVE_INFINITY
    for (const candidate of candidates) {
      const score = scoreCandidate(
        candidate, request, bounds, obstacles, placed, sideUse,
      )
      if (score < bestScore) {
        best = candidate
        bestScore = score
      }
    }
    placed.push(best.rect)
    if (best.side !== 'center') sideUse[best.side] += 1
    byId.set(request.id, {
      id: request.id,
      text: request.text,
      role,
      lines: label.lines,
      ...best.rect,
      anchorX: request.anchorX,
      anchorY: request.anchorY,
      fontSize: label.fontSize,
      lineHeight: label.lineHeight,
      side: best.side,
      leader: pointRectDistance(best.rect, request.anchorX, request.anchorY) > 1,
    })
  }

  return requests
    .map((request) => byId.get(request.id))
    .filter((item): item is PlacedLabel => item !== undefined)
}

export function screenCandidates(
  request: ScreenLabelRequest,
  gaps: number[],
): Candidate[] {
  const out: Candidate[] = []
  const { anchorX: ax, anchorY: ay, width: w, height: h } = request
  for (const gap of gaps) {
    const boxes: Array<[number, number, Side]> = [
      [ax - w / 2, ay - gap - h, 'top'],
      [ax - w / 2, ay + gap, 'bottom'],
      [ax - gap - w, ay - h / 2, 'left'],
      [ax + gap, ay - h / 2, 'right'],
      [ax - gap - w, ay - gap - h, 'left'],
      [ax + gap, ay - gap - h, 'right'],
      [ax - gap - w, ay + gap, 'left'],
      [ax + gap, ay + gap, 'right'],
    ]
    for (const [x, y, side] of boxes) {
      const rect = { x, y, w, h }
      out.push({ rect, side, distance: pointRectDistance(rect, ax, ay) })
    }
  }
  const avoid = request.avoidRect
  if (avoid) {
    for (const gap of [8, 18, 32, 52, 80]) {
      const boxes: Array<[number, number, Side]> = [
        [
          clamp(ax, avoid.x + w / 2, avoid.x + avoid.w - w / 2) - w / 2,
          avoid.y - gap - h,
          'top',
        ],
        [
          clamp(ax, avoid.x + w / 2, avoid.x + avoid.w - w / 2) - w / 2,
          avoid.y + avoid.h + gap,
          'bottom',
        ],
        [
          avoid.x - gap - w,
          clamp(ay, avoid.y + h / 2, avoid.y + avoid.h - h / 2) - h / 2,
          'left',
        ],
        [
          avoid.x + avoid.w + gap,
          clamp(ay, avoid.y + h / 2, avoid.y + avoid.h - h / 2) - h / 2,
          'right',
        ],
      ]
      for (const [x, y, side] of boxes) {
        const rect = { x, y, w, h }
        out.push({ rect, side, distance: pointRectDistance(rect, ax, ay) })
      }
    }
  }
  return out
}

export function placeScreenLabels(
  requests: ScreenLabelRequest[],
  viewport: { width: number; height: number },
  fixedRects: Rect[] = [],
): ScreenLabelPlacement[] {
  const bounds = {
    x: 4,
    y: 4,
    w: Math.max(1, viewport.width - 8),
    h: Math.max(1, viewport.height - 8),
  }
  const ordered = [...requests].sort((a, b) => (
    (b.priority ?? 1) - (a.priority ?? 1) || a.id.localeCompare(b.id)
  ))
  const placed: Rect[] = [...fixedRects]
  const sideUse: Record<Side, number> = { top: 0, bottom: 0, left: 0, right: 0 }
  const byId = new Map<string, ScreenLabelPlacement>()

  for (const request of ordered) {
    const w = Math.max(1, request.width)
    const h = Math.max(1, request.height)
    if (request.fixed) {
      const rect = {
        x: request.anchorX - w / 2,
        y: request.anchorY - h / 2,
        w,
        h,
      }
      placed.push(rect)
      byId.set(request.id, {
        id: request.id,
        ...rect,
        centerX: rect.x + w / 2,
        centerY: rect.y + h / 2,
        side: 'center',
        leader: false,
        overlapsAvoid: false,
        overlapsLabel: false,
      })
      continue
    }
    const candidates = screenCandidates(request, [8, 16, 28, 44, 64, 88, 120])
    let best = candidates[0]
    let bestScore = Number.POSITIVE_INFINITY
    for (const candidate of candidates) {
      const rect = candidate.rect
      let score = candidate.distance * 0.2
      const overflowX = Math.max(0, bounds.x - rect.x)
        + Math.max(0, rect.x + rect.w - (bounds.x + bounds.w))
      const overflowY = Math.max(0, bounds.y - rect.y)
        + Math.max(0, rect.y + rect.h - (bounds.y + bounds.h))
      score += (overflowX + overflowY) * 1e7
      for (const other of placed) {
        const area = overlapArea(rect, other)
        if (area > 0) score += 1e6 + area * 1e4
      }
      if (request.avoidRect) {
        const area = overlapArea(rect, request.avoidRect)
        if (area > 0) {
          score += (request.avoidWeight ?? 1) * (area + 320)
        }
      }
      if (request.preferred?.length) {
        const index = request.preferred.indexOf(candidate.side as Side)
        if (index < 0) score += 80
        else score += index * 24
      }
      if (candidate.side !== 'center') score += (sideUse[candidate.side] || 0) * 7
      if (score < bestScore) {
        bestScore = score
        best = candidate
      }
    }
    const overlapsLabel = placed.some(
      (other) => overlapArea(best.rect, other) > 0,
    )
    const overlapsAvoid = request.avoidRect
      ? overlapArea(best.rect, request.avoidRect) > 0
      : false
    placed.push(best.rect)
    if (best.side !== 'center') sideUse[best.side] += 1
    byId.set(request.id, {
      id: request.id,
      ...best.rect,
      centerX: best.rect.x + w / 2,
      centerY: best.rect.y + h / 2,
      side: best.side,
      leader: pointRectDistance(best.rect, request.anchorX, request.anchorY) > 2,
      overlapsAvoid,
      overlapsLabel,
    })
  }

  return requests
    .map((request) => byId.get(request.id))
    .filter((item): item is ScreenLabelPlacement => item !== undefined)
}

function sampleLine(
  from: [number, number],
  to: [number, number],
  out: Rect[],
  step = 10,
): void {
  const dx = to[0] - from[0]
  const dy = to[1] - from[1]
  const length = Math.hypot(dx, dy)
  const count = Math.max(1, Math.ceil(length / step))
  for (let index = 0; index <= count; index += 1) {
    const t = index / count
    out.push({
      x: from[0] + dx * t - 2,
      y: from[1] + dy * t - 2,
      w: 4,
      h: 4,
    })
  }
}

export function shapeObstacleRects(shapes: DiagramShape[], pad = 2): Rect[] {
  const out: Rect[] = []
  for (const shape of shapes) {
    const kind = shape.kind
    if (kind === 'point') {
      const r = Math.max(3, Math.abs(Number(shape.r) || 3)) + pad
      out.push({
        x: Number(shape.x) - r,
        y: Number(shape.y) - r,
        w: r * 2,
        h: r * 2,
      })
    } else if (kind === 'circle') {
      const cx = Number(shape.x)
      const cy = Number(shape.y)
      const r = Math.abs(Number(shape.r) || Number(shape.radius) || 1)
      for (let index = 0; index < 24; index += 1) {
        const angle = (Math.PI * 2 * index) / 24
        out.push({
          x: cx + Math.cos(angle) * r - 2,
          y: cy + Math.sin(angle) * r - 2,
          w: 4,
          h: 4,
        })
      }
    } else if (['segment', 'line', 'vector', 'axis'].includes(kind)) {
      const from = Array.isArray(shape.from) ? shape.from : [0, 0]
      const to = Array.isArray(shape.to) ? shape.to : [0, 0]
      sampleLine(
        [Number(from[0]) || 0, Number(from[1]) || 0],
        [Number(to[0]) || 0, Number(to[1]) || 0],
        out,
      )
    } else if (Array.isArray(shape.points)) {
      const points = shape.points
        .filter((point): point is number[] => (
          Array.isArray(point) && point.length >= 2
        ))
      const step = Math.max(1, Math.floor(points.length / 160))
      for (let index = 0; index + step < points.length; index += step) {
        const from = points[index]
        const to = points[index + step]
        sampleLine(
          [Number(from[0]) || 0, Number(from[1]) || 0],
          [Number(to[0]) || 0, Number(to[1]) || 0],
          out,
          8,
        )
      }
      if (kind === 'polygon' && points.length > 1) {
        const first = points[0]
        const last = points[points.length - 1]
        sampleLine(
          [Number(last[0]) || 0, Number(last[1]) || 0],
          [Number(first[0]) || 0, Number(first[1]) || 0],
          out,
          8,
        )
      }
    }
  }
  return out
}

export function figureRectOfShapes(shapes: DiagramShape[]): Rect | null {
  const relevant = shapes.filter((shape) => shape.kind !== 'axis')
  const source = relevant.length ? relevant : shapes
  let minX = Number.POSITIVE_INFINITY
  let minY = Number.POSITIVE_INFINITY
  let maxX = Number.NEGATIVE_INFINITY
  let maxY = Number.NEGATIVE_INFINITY
  const add = (x: number, y: number): void => {
    if (!Number.isFinite(x) || !Number.isFinite(y)) return
    minX = Math.min(minX, x)
    minY = Math.min(minY, y)
    maxX = Math.max(maxX, x)
    maxY = Math.max(maxY, y)
  }
  for (const shape of source) {
    if (shape.kind === 'point' || shape.kind === 'circle') {
      const r = Math.abs(Number(shape.r) || Number(shape.radius) || 3)
      add(Number(shape.x) - r, Number(shape.y) - r)
      add(Number(shape.x) + r, Number(shape.y) + r)
    } else if (['segment', 'line', 'vector', 'axis'].includes(shape.kind)) {
      const from = Array.isArray(shape.from) ? shape.from : []
      const to = Array.isArray(shape.to) ? shape.to : []
      if (from.length >= 2) add(Number(from[0]), Number(from[1]))
      if (to.length >= 2) add(Number(to[0]), Number(to[1]))
    } else if (Array.isArray(shape.points)) {
      for (const point of shape.points) {
        if (Array.isArray(point) && point.length >= 2) {
          add(Number(point[0]), Number(point[1]))
        }
      }
    }
  }
  if (!Number.isFinite(minX) || !Number.isFinite(minY)) return null
  return { x: minX, y: minY, w: Math.max(1, maxX - minX), h: Math.max(1, maxY - minY) }
}

export function outwardSides(anchor: { x: number; y: number }, figure: Rect | null): Side[] {
  if (!figure) return []
  const cx = figure.x + figure.w / 2
  const cy = figure.y + figure.h / 2
  const dx = anchor.x - cx
  const dy = anchor.y - cy
  if (Math.abs(dx) >= Math.abs(dy)) {
    return dx < 0
      ? ['left', 'top', 'bottom', 'right']
      : ['right', 'top', 'bottom', 'left']
  }
  return dy < 0
    ? ['top', 'left', 'right', 'bottom']
    : ['bottom', 'left', 'right', 'top']
}
