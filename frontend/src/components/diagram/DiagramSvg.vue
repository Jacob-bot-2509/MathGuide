<script setup lang="ts">
/** 2D 图解渲染:结构化节点/形状,支持拖动、缩放、重置,不自动动画。 */
import { computed, ref, useId, watch } from 'vue'
import type { DiagramShape, DiagramSpec } from '@/utils/diagramSpec'
import { filterCollapsed } from '@/utils/diagramSpec'
import { t } from '@/utils/i18n'
import {
  figureRectOfShapes,
  outwardSides,
  placeLabels,
  shapeObstacleRects,
  type LabelRequest,
  type PlacedLabel,
} from '@/utils/diagramLabels'
import { layoutForSpec } from '@/utils/diagramLayout'

const props = withDefaults(defineProps<{ spec: DiagramSpec; collapsible?: boolean }>(), {
  collapsible: false,
})
const arrowId = `mg-arrow-${useId()}`
const axisArrowId = `mg-axis-arrow-${useId()}`
const interacted = ref(false)
const collapsed = ref<Set<string>>(new Set())

const svgEl = ref<SVGSVGElement | null>(null)
const view = ref({ x: 0, y: 0, w: 1, h: 1 })
const zoom = ref(1)
let drag: { id: number; x: number; y: number } | null = null
const pointers = new Map<number, { x: number; y: number }>()
let pinchDistance = 0

function num(value: unknown, fallback = 0): number {
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed : fallback
}

function pair(value: unknown): [number, number] {
  if (!Array.isArray(value) || value.length < 2) return [0, 0]
  return [num(value[0]), num(value[1])]
}

function glyphWidth(ch: string): number {
  return /[　-鿿＀-￯]/.test(ch) ? 11 : 6.5
}

function labelLines(label: string, width: number): string[] {
  const maxWidth = Math.max(40, width - 18)
  const chars = Array.from(label)
  const lines: string[] = []
  let current = ''
  let currentWidth = 0
  for (const ch of chars) {
    const w = glyphWidth(ch)
    if (current && currentWidth + w > maxWidth) {
      lines.push(current)
      current = ''
      currentWidth = 0
      if (lines.length === 2) break
    }
    current += ch
    currentWidth += w
  }
  if (current && lines.length < 2) lines.push(current)
  if (!lines.length) return [label]
  if (lines.length === 2 && chars.length > lines.join('').length) {
    lines[1] = `${lines[1].slice(0, -1)}…`
  }
  return lines
}

function boundsOfShapes(
  shapes: DiagramShape[],
  annotations: DiagramSpec['annotations'],
  includeOrigin = false,
) {
  const xs: number[] = []
  const ys: number[] = []
  if (includeOrigin) {
    xs.push(0)
    ys.push(0)
  }
  for (const shape of shapes) {
    if (shape.kind === 'point') {
      xs.push(num(shape.x)); ys.push(num(shape.y))
    } else if (shape.kind === 'circle') {
      const r = Math.abs(num(shape.r, num(shape.radius)))
      xs.push(num(shape.x) - r, num(shape.x) + r)
      ys.push(num(shape.y) - r, num(shape.y) + r)
    } else if (shape.kind === 'segment' || shape.kind === 'line'
      || shape.kind === 'vector' || shape.kind === 'axis') {
      const [x1, y1] = pair(shape.from)
      const [x2, y2] = pair(shape.to)
      xs.push(x1, x2); ys.push(y1, y2)
    } else if (shape.kind === 'polygon' && Array.isArray(shape.points)) {
      for (const item of shape.points) {
        const [x, y] = pair(item)
        xs.push(x); ys.push(y)
      }
    } else if (shape.kind === 'curve' && Array.isArray(shape.points)) {
      const segments = Array.isArray(shape.segments) ? shape.segments : null
      if (segments && segments.length > 1) {
        // 间断曲线(1/x、tan):极端值只出现在渐近线附近,按 1%/99% 分位定范围,
        // 否则整幅图会被几条竖直渐近线压扁。
        const values = shape.points.map((item) => pair(item)[1]).sort((a, b) => a - b)
        const lo = values[Math.floor(values.length * 0.01)]
        const hi = values[Math.min(values.length - 1, Math.floor(values.length * 0.99))]
        for (const item of shape.points) xs.push(pair(item)[0])
        ys.push(lo, hi)
      } else {
        for (const item of shape.points) {
          const [x, y] = pair(item)
          xs.push(x); ys.push(y)
        }
      }
    }
  }
  for (const note of annotations) {
    xs.push(note.x); ys.push(note.y)
  }
  if (!xs.length) return { minX: 0, minY: 0, maxX: 400, maxY: 260 }
  return {
    minX: Math.min(...xs), minY: Math.min(...ys),
    maxX: Math.max(...xs), maxY: Math.max(...ys),
  }
}

const visibleSpec = computed(() => filterCollapsed(props.spec, collapsed.value))
const isShapeType = computed(() => visibleSpec.value.type === 'geometry2d'
  || visibleSpec.value.type === 'plot2d')

/** 几何/曲线图用数学坐标;先映射到像素坐标,否则 11px 字号会被放大成整屏。 */
const shapeGeometry = computed(() => {
  if (!isShapeType.value) return null
  const spec = visibleSpec.value
  const dataBounds = boundsOfShapes(
    spec.shapes.filter((shape) => shape.kind !== 'axis'),
    [], true,
  )
  const normalized = spec.shapes.map((shape) => {
    if (shape.kind !== 'axis') return shape
    const label = String(shape.label || '').toLowerCase()
    if (/^x\b|^x[ (]|横轴/.test(label)) {
      return { ...shape, from: [dataBounds.minX, 0], to: [dataBounds.maxX, 0] }
    }
    if (/^y\b|^y[ (]|纵轴/.test(label)) {
      return { ...shape, from: [0, dataBounds.minY], to: [0, dataBounds.maxY] }
    }
    return shape
  })
  const b = boundsOfShapes(normalized, [], spec.type === 'plot2d')
  const pad = 30
  const spanX = Math.max(1e-6, b.maxX - b.minX)
  const spanY = Math.max(1e-6, b.maxY - b.minY)
  const scale = Math.min(620 / spanX, 360 / spanY, 120)
  const width = Math.max(180, spanX * scale + pad * 2)
  const height = Math.max(140, spanY * scale + pad * 2)
  const tx = (x: number): number => pad + (x - b.minX) * scale
  const ty = (y: number): number => height - pad - (y - b.minY) * scale
  const point2 = (value: unknown): number[] | null => {
    if (!Array.isArray(value) || value.length < 2) return null
    return [tx(num(value[0])), ty(num(value[1]))]
  }
  const shapes = normalized.map((shape) => {
    const out: DiagramShape = { ...shape }
    if (typeof shape.x === 'number') out.x = tx(shape.x)
    if (typeof shape.y === 'number') out.y = ty(shape.y)
    if (typeof shape.r === 'number') out.r = shape.r * scale
    if (typeof shape.radius === 'number') out.radius = shape.radius * scale
    for (const key of ['from', 'to']) {
      const mapped = point2(shape[key])
      if (mapped) out[key] = mapped
    }
    if (Array.isArray(shape.points)) {
      out.points = shape.points
        .map(point2)
        .filter((item): item is number[] => item !== null)
    }
    if (Array.isArray(shape.segments)) {
      out.segments = shape.segments
        .map((segment: unknown) => Array.isArray(segment)
          ? segment.map(point2).filter((item): item is number[] => item !== null)
          : [])
        .filter((segment: number[][]) => segment.length > 1)
    }
    return out
  })

  const figure = figureRectOfShapes(shapes)
  const obstacles = shapeObstacleRects(shapes)
  const requests: LabelRequest[] = []
  spec.annotations.forEach((note, index) => {
    // 模型偶尔给出远离图形的锚点;夹到主体附近,避免把 viewBox 撑成一张空图。
    const rawX = tx(note.x)
    const rawY = ty(note.y)
    const anchorX = figure
      ? Math.min(Math.max(rawX, figure.x - 60), figure.x + figure.w + 60)
      : rawX
    const anchorY = figure
      ? Math.min(Math.max(rawY, figure.y - 60), figure.y + figure.h + 60)
      : rawY
    requests.push({
      id: `annotation-${index}`,
      text: note.text,
      anchorX,
      anchorY,
      role: 'annotation',
      fontSize: 12,
      maxWidth: 160,
      maxLines: 3,
      priority: 3,
      figure,
      figureWeight: 2.5,
      preferred: outwardSides({ x: anchorX, y: anchorY }, figure),
    })
  })
  shapes.forEach((shape, index) => {
    const label = String(shape.label || '').trim()
    if (!label) return
    const anchor = labelAnchor(shape)
    const fixed = shape.kind === 'axis' && /^[xyz]$/i.test(label)
    requests.push({
      id: `shape-${index}`,
      text: label,
      anchorX: anchor.x,
      anchorY: anchor.y,
      role: fixed ? 'axis' : 'shape',
      fontSize: 13,
      maxWidth: fixed ? 60 : 170,
      maxLines: fixed ? 1 : 2,
      priority: fixed ? 5 : 2,
      figure: fixed ? null : figure,
      figureWeight: 0,
      preferred: fixed ? [] : outwardSides(anchor, figure),
      fixed,
    })
  })
  const hasAxisLabel = shapes.some((shape) => (
    shape.kind === 'axis' && /^[xy]$/i.test(String(shape.label || '').trim())
  ))
  if (spec.type === 'plot2d' && !hasAxisLabel) {
    // 自动坐标轴也要有 x/y 名称;放进同一套占位器,避免和曲线标签打架。
    requests.push({
      id: 'axis-label-x',
      text: 'x',
      anchorX: tx(b.maxX) + 8,
      anchorY: ty(0) + 10,
      role: 'axis',
      fontSize: 10,
      maxWidth: 24,
      maxLines: 1,
      priority: 6,
      fixed: true,
    })
    requests.push({
      id: 'axis-label-y',
      text: 'y',
      anchorX: tx(0) - 8,
      anchorY: ty(b.maxY) - 8,
      role: 'axis',
      fontSize: 10,
      maxWidth: 24,
      maxLines: 1,
      priority: 6,
      fixed: true,
    })
  }
  // 虚拟画布给外围标注留空间;放完再收紧,避免文字被 viewBox 裁掉。
  const placed = placeLabels(requests, obstacles, {
    x: -240, y: -180, w: width + 480, h: height + 360,
  }).filter((label) => {
    // 标注被避让挤得离锚点太远时,引线会横穿整张图、看着像另一条曲线。
    // 宁可少一个标注(图本身仍正确),也不能让文字指错位置。
    if (label.role !== 'annotation') return true
    const dx = label.x + label.w / 2 - label.anchorX
    const dy = label.y + label.h / 2 - label.anchorY
    return Math.hypot(dx, dy) <= 160
  })
  let minLeft = 0
  let minTop = 0
  let maxRight = width
  let maxBottom = height
  for (const label of placed) {
    minLeft = Math.min(minLeft, label.x)
    minTop = Math.min(minTop, label.y)
    maxRight = Math.max(maxRight, label.x + label.w)
    maxBottom = Math.max(maxBottom, label.y + label.h)
  }
  const shiftX = Math.max(0, 8 - minLeft)
  const shiftY = Math.max(0, 8 - minTop)
  const finalWidth = Math.max(width + shiftX, maxRight + shiftX + 8)
  const finalHeight = Math.max(height + shiftY, maxBottom + shiftY + 8)
  const shiftedShapes = shapes.map((shape) => {
    const out: DiagramShape = { ...shape }
    if (typeof out.x === 'number') out.x += shiftX
    if (typeof out.y === 'number') out.y += shiftY
    for (const key of ['from', 'to']) {
      const value = out[key]
      if (Array.isArray(value) && value.length >= 2) {
        out[key] = [num(value[0]) + shiftX, num(value[1]) + shiftY]
      }
    }
    if (Array.isArray(out.points)) {
      out.points = out.points.map((point) => (
        Array.isArray(point) && point.length >= 2
          ? [num(point[0]) + shiftX, num(point[1]) + shiftY]
          : point
      ))
    }
    return out
  })
  const shiftedLabels = placed.map((label) => ({
    ...label,
    x: label.x + shiftX,
    y: label.y + shiftY,
    anchorX: label.anchorX + shiftX,
    anchorY: label.anchorY + shiftY,
  }))
  return {
    shapes: shiftedShapes,
    labels: shiftedLabels,
    width: finalWidth,
    height: finalHeight,
    tx: (x: number): number => tx(x) + shiftX,
    ty: (y: number): number => ty(y) + shiftY,
    dataBounds: b,
  }
})

const displayShapes = computed(() => shapeGeometry.value?.shapes
  || visibleSpec.value.shapes)
const displayLabels = computed(() => shapeGeometry.value?.labels || [])

const layout = computed(() => {
  if (visibleSpec.value.type === 'tree'
    || visibleSpec.value.type === 'relation'
    || visibleSpec.value.type === 'flow') {
    return layoutForSpec(visibleSpec.value)
  }
  const g = shapeGeometry.value
  return {
    nodes: [], edges: [],
    width: g?.width ?? 400,
    height: g?.height ?? 260,
    minX: 0,
    minY: 0,
  }
})

const worldWidth = computed(() => Math.max(120, layout.value.width))
const worldHeight = computed(() => Math.max(90, layout.value.height))
const minX = computed(() => ('minX' in layout.value ? Number(layout.value.minX) : 0))
const minY = computed(() => ('minY' in layout.value ? Number(layout.value.minY) : 0))

const plotAxes = computed(() => {
  if (visibleSpec.value.type !== 'plot2d') return []
  const g = shapeGeometry.value
  if (!g) return []
  const x0 = g.tx(0)
  const y0 = g.ty(0)
  return [
    {
      x1: g.tx(g.dataBounds.minX), y1: y0,
      x2: g.tx(g.dataBounds.maxX), y2: y0,
    },
    {
      x1: x0, y1: g.ty(g.dataBounds.minY),
      x2: x0, y2: g.ty(g.dataBounds.maxY),
    },
  ]
})
const hasUnsampledCurve = computed(() =>
  visibleSpec.value.type === 'plot2d'
  && visibleSpec.value.shapes.some((shape) =>
    shape.kind === 'curve' && (!Array.isArray(shape.points) || !shape.points.length)))

function labelAnchor(shape: DiagramShape): { x: number; y: number } {
  const kind = shape.kind
  if ((kind === 'curve' || kind === 'polygon')
    && Array.isArray(shape.points) && shape.points.length) {
    const [x, y] = pair(shape.points[Math.floor(shape.points.length * 0.62)])
    return { x: x + 4, y: y - 6 }
  }
  if (kind === 'axis') {
    const [x, y] = pair(shape.to)
    return { x, y: y - 6 }
  }
  if (kind === 'vector') {
    const [x1, y1] = pair(shape.from)
    const [x2, y2] = pair(shape.to)
    return {
      x: x1 + (x2 - x1) * 0.72 + 4,
      y: y1 + (y2 - y1) * 0.72 - 6,
    }
  }
  if (kind === 'segment' || kind === 'line') {
    const [x1, y1] = pair(shape.from)
    const [x2, y2] = pair(shape.to)
    return { x: (x1 + x2) / 2, y: (y1 + y2) / 2 - 6 }
  }
  if (kind === 'point') {
    return {
      x: num(shape.x, pair(shape.from)[0]) + 7,
      y: num(shape.y, pair(shape.from)[1]) - 7,
    }
  }
  return {
    x: num(shape.x, pair(shape.from)[0]),
    y: num(shape.y, pair(shape.from)[1]) - 6,
  }
}

function leaderEnd(label: PlacedLabel): { x: number; y: number } {
  return {
    x: Math.min(Math.max(label.anchorX, label.x), label.x + label.w),
    y: Math.min(Math.max(label.anchorY, label.y), label.y + label.h),
  }
}

function showLeader(label: PlacedLabel): boolean {
  if (!label.leader) return false
  if (label.role === 'annotation') return true
  const dx = Math.max(label.x - label.anchorX, 0, label.anchorX - (label.x + label.w))
  const dy = Math.max(label.y - label.anchorY, 0, label.anchorY - (label.y + label.h))
  return Math.hypot(dx, dy) > 12
}

function showEdgeLabel(label: unknown): boolean {
  const text = String(label || '').trim()
  if (!text) return false
  // 箭头已经表达推出方向,不再重复一个“⇒/推出”文字压在线旁。
  return !/^(?:=>|→|⇒|推出|蕴含|可推出)$/.test(text)
}

function resetView(): void {
  view.value = { x: minX.value, y: minY.value, w: worldWidth.value, h: worldHeight.value }
  zoom.value = 1
}

function curveSegments(shape: DiagramShape): number[][][] {
  const segments = Array.isArray(shape.segments) ? shape.segments as number[][][] : null
  if (segments && segments.length) return segments
  const points = Array.isArray(shape.points) ? shape.points as number[][] : null
  return points && points.length > 1 ? [points] : []
}

function hasChildren(id: string): boolean {
  return props.spec.edges.some((edge) => edge.from === id)
}

function toggleNode(id: string): void {
  if (!props.collapsible || !hasChildren(id)) return
  const next = new Set(collapsed.value)
  if (next.has(id)) next.delete(id)
  else next.add(id)
  collapsed.value = next
}

watch(visibleSpec, () => resetView())

function applyViewBox(): void {
  resetView()
}

function zoomAt(factor: number, clientX: number, clientY: number): void {
  interacted.value = true
  const svg = svgEl.value
  if (!svg) return
  const rect = svg.getBoundingClientRect()
  if (!rect.width || !rect.height) return
  const next = Math.min(8, Math.max(0.35, zoom.value * factor))
  const mx = view.value.x + ((clientX - rect.left) / rect.width) * view.value.w
  const my = view.value.y + ((clientY - rect.top) / rect.height) * view.value.h
  const ratio = next / zoom.value
  view.value = {
    x: mx - (mx - view.value.x) / ratio,
    y: my - (my - view.value.y) / ratio,
    w: view.value.w / ratio,
    h: view.value.h / ratio,
  }
  zoom.value = next
}

function onWheel(event: WheelEvent): void {
  event.preventDefault()
  zoomAt(event.deltaY < 0 ? 1.12 : 1 / 1.12, event.clientX, event.clientY)
}

function onPointerDown(event: PointerEvent): void {
  if (event.button !== 0) return
  const svg = svgEl.value
  if (!svg) return
  pointers.set(event.pointerId, { x: event.clientX, y: event.clientY })
  if (pointers.size >= 2) {
    const [a, b] = [...pointers.values()]
    pinchDistance = Math.hypot(a.x - b.x, a.y - b.y)
    drag = null
  } else {
    drag = { id: event.pointerId, x: event.clientX, y: event.clientY }
  }
  svg.setPointerCapture(event.pointerId)
}

function onPointerMove(event: PointerEvent): void {
  pointers.set(event.pointerId, { x: event.clientX, y: event.clientY })
  if (pointers.size >= 2) {
    const [a, b] = [...pointers.values()]
    const distance = Math.hypot(a.x - b.x, a.y - b.y)
    if (pinchDistance > 0 && distance > 0) {
      zoomAt(distance / pinchDistance, (a.x + b.x) / 2, (a.y + b.y) / 2)
    }
    pinchDistance = distance
    return
  }
  if (!drag || drag.id !== event.pointerId) return
  interacted.value = true
  const svg = svgEl.value
  if (!svg) return
  const rect = svg.getBoundingClientRect()
  if (!rect.width || !rect.height) return
  const dx = (event.clientX - drag.x) * (view.value.w / rect.width)
  const dy = (event.clientY - drag.y) * (view.value.h / rect.height)
  view.value = { ...view.value, x: view.value.x - dx, y: view.value.y - dy }
  drag = { ...drag, x: event.clientX, y: event.clientY }
}

function onPointerUp(event: PointerEvent): void {
  pointers.delete(event.pointerId)
  if (pointers.size < 2) pinchDistance = 0
  drag = null
}

// 首帧与数据变化时重置视图。
resetView()
</script>

<template>
  <div class="diagram-svg-wrap">
    <button v-if="interacted" class="diagram-reset" type="button" @click="applyViewBox">重置视图</button>
    <svg
      ref="svgEl"
      class="diagram-svg"
      :viewBox="`${view.x} ${view.y} ${view.w} ${view.h}`"
      role="img"
      :aria-label="props.spec.title || t('diagram.figure')"
      @wheel="onWheel"
      @pointerdown="onPointerDown"
      @pointermove="onPointerMove"
      @pointerup="onPointerUp"
      @pointercancel="onPointerUp"
    >
      <defs>
        <marker
          :id="axisArrowId"
          markerWidth="8" markerHeight="8"
          refX="7" refY="3" orient="auto"
        >
          <path d="M0,0 L7,3 L0,6 z" class="diagram-axis-head" />
        </marker>
        <marker
          v-if="layout.nodes.length"
          :id="arrowId"
          markerWidth="8" markerHeight="8"
          refX="7" refY="3" orient="auto"
        >
          <path d="M0,0 L7,3 L0,6 z" class="diagram-arrow-head" />
        </marker>
      </defs>
      <g v-if="layout.nodes.length">
        <line
          v-for="edge in layout.edges"
          :key="`${edge.from}-${edge.to}`"
          :x1="edge.x1" :y1="edge.y1" :x2="edge.x2" :y2="edge.y2"
          class="diagram-edge"
          :marker-end="layout.nodes.length ? `url(#${arrowId})` : undefined"
        />
        <text
          v-for="edge in layout.edges.filter((e) => showEdgeLabel(e.label))"
          :key="`label-${edge.from}-${edge.to}`"
          :x="edge.labelX ?? (edge.x1 + edge.x2) / 2"
          :y="edge.labelY ?? (edge.y1 + edge.y2) / 2 - 4"
          class="diagram-edge-label"
        >
          <tspan
            v-for="(line, li) in (edge.labelLines || [edge.label])"
            :key="li"
            :x="edge.labelX ?? (edge.x1 + edge.x2) / 2"
            :dy="li === 0 ? 0 : 11"
          >{{ line }}</tspan>
        </text>
        <g
          v-for="node in layout.nodes"
          :key="node.id"
          :class="{ 'diagram-node-group': collapsible && hasChildren(node.id) }"
          @click.stop="toggleNode(node.id)"
        >
          <rect
            :x="node.x" :y="node.y" :width="node.w" :height="node.h"
            rx="7" class="diagram-node"
          />
          <text
            :x="node.x + node.w / 2" :y="node.y + node.h / 2"
            text-anchor="middle" class="diagram-node-label"
          >
            <title>{{ node.label }}</title>
            <tspan
              v-for="(line, li) in labelLines(node.label, node.w)"
              :key="li"
              :x="node.x + node.w / 2"
              :dy="li === 0 ? (labelLines(node.label, node.w).length === 1 ? 4 : -3) : 13"
            >{{ line }}</tspan>
          </text>
          <text
            v-if="collapsible && hasChildren(node.id)"
            :x="node.x + node.w - 9" :y="node.y + 13"
            class="diagram-fold-mark"
          >{{ collapsed.has(node.id) ? '+' : '−' }}</text>
        </g>
      </g>

      <g v-else>
        <line
          v-for="(axis, ai) in plotAxes"
          :key="`axis-${ai}`"
          :x1="axis.x1" :y1="axis.y1" :x2="axis.x2" :y2="axis.y2"
          class="diagram-axis"
          :marker-end="`url(#${axisArrowId})`"
        />
        <text v-if="hasUnsampledCurve" x="8" y="14" class="diagram-warning">
          曲线缺少采样点
        </text>
        <g v-for="(shape, i) in displayShapes" :key="`shape-${i}`">
          <circle
            v-if="shape.kind === 'point'"
            :cx="num(shape.x)" :cy="num(shape.y)"
            :r="Math.min(num(shape.r, 2.6), 6)"
            class="diagram-point"
          />
          <line
            v-else-if="shape.kind === 'segment' || shape.kind === 'line' || shape.kind === 'vector' || shape.kind === 'axis'"
            :x1="pair(shape.from)[0]" :y1="pair(shape.from)[1]"
            :x2="pair(shape.to)[0]" :y2="pair(shape.to)[1]"
            :class="shape.kind === 'axis' ? 'diagram-axis'
              : (shape.label && /切线|y\s*=/i.test(String(shape.label))
                ? 'diagram-tangent' : 'diagram-shape-line')"
            :marker-end="shape.kind === 'axis' ? `url(#${axisArrowId})` : undefined"
          />
          <circle
            v-else-if="shape.kind === 'circle'"
            :cx="num(shape.x)" :cy="num(shape.y)"
            :r="Math.abs(num(shape.r, num(shape.radius, 1)))"
            class="diagram-shape-line"
          />
          <polygon
            v-else-if="shape.kind === 'polygon' && Array.isArray(shape.points)"
            :points="shape.points.map((p) => pair(p).join(',')).join(' ')"
            class="diagram-shape-fill"
          />
          <g v-else-if="shape.kind === 'curve'">
            <polyline
              v-for="(segment, si) in curveSegments(shape)"
              :key="si"
              :points="segment.map((p) => pair(p).join(',')).join(' ')"
              class="diagram-curve"
            />
          </g>
        </g>
        <g v-for="label in displayLabels" :key="label.id">
          <line
            v-if="showLeader(label)"
            :x1="label.anchorX" :y1="label.anchorY"
            :x2="leaderEnd(label).x" :y2="leaderEnd(label).y"
            class="diagram-label-leader"
          />
          <text
            :x="label.x" :y="label.y + label.fontSize"
            :style="{ fontSize: `${label.fontSize}px` }"
            :class="label.role === 'annotation'
              ? 'diagram-annotation' : 'diagram-shape-label'"
          >
            <tspan
              v-for="(line, li) in label.lines"
              :key="li"
              :x="label.x"
              :dy="li === 0 ? 0 : label.lineHeight"
            >{{ line }}</tspan>
          </text>
        </g>
      </g>
    </svg>
  </div>
</template>

<style scoped>
.diagram-svg-wrap {
  position: relative;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: var(--bg-card);
  overflow: hidden;
}

.diagram-svg {
  display: block;
  width: 100%;
  min-height: 180px;
  max-height: 420px;
  touch-action: none;
  cursor: grab;
}

.diagram-svg:active {
  cursor: grabbing;
}

.diagram-node-group {
  cursor: pointer;
}

.diagram-fold-mark {
  fill: var(--text-dim);
  font-size: 10px;
  text-anchor: end;
}

.diagram-reset {
  position: absolute;
  right: 8px;
  top: 8px;
  z-index: 1;
  border: 1px solid var(--line);
  border-radius: 5px;
  background: var(--bg-panel);
  color: var(--text-dim);
  font-size: 10px;
  padding: 2px 7px;
  cursor: pointer;
}

.diagram-node {
  fill: color-mix(in srgb, var(--cyan) 8%, var(--bg-panel));
  stroke: var(--line-bright);
}

.diagram-node-label,
.diagram-edge-label,
.diagram-shape-label,
.diagram-annotation {
  fill: var(--text);
  font-size: 11px;
}

.diagram-edge {
  stroke: var(--line-bright);
  stroke-width: 1.2;
}

.diagram-label-leader {
  stroke: var(--text-dim);
  stroke-width: 0.7;
  stroke-dasharray: 2 3;
  opacity: 0.65;
}

.diagram-arrow-head {
  fill: var(--cyan);
}

.diagram-axis-head {
  fill: var(--text-dim);
}

.diagram-edge-label {
  fill: var(--text-dim);
  font-size: 9px;
  text-anchor: start;
}

.diagram-point {
  fill: var(--cyan);
  stroke: var(--cyan);
}

.diagram-shape-line {
  fill: none;
  stroke: var(--cyan);
  stroke-width: 1.5;
}

.diagram-tangent {
  fill: none;
  stroke: #ff9f43;
  stroke-width: 1.3;
}

.diagram-axis {
  stroke: var(--text-dim);
  stroke-width: 0.9;
  opacity: 0.7;
}

.diagram-warning {
  fill: #ffd166;
  font-size: 10px;
}

.diagram-shape-fill {
  fill: color-mix(in srgb, var(--cyan) 14%, transparent);
  stroke: var(--cyan);
}

.diagram-curve {
  fill: none;
  stroke: #ffd166;
  stroke-width: 1.6;
}

.diagram-annotation {
  fill: var(--text-dim);
  font-size: 10px;
}
</style>
