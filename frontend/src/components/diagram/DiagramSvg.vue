<script setup lang="ts">
/** 2D 图解渲染:结构化节点/形状,支持拖动、缩放、重置,不自动动画。 */
import { computed, ref } from 'vue'
import type { DiagramShape, DiagramSpec } from '@/utils/diagramSpec'
import { layoutForSpec } from '@/utils/diagramLayout'

const props = defineProps<{ spec: DiagramSpec }>()

const svgEl = ref<SVGSVGElement | null>(null)
const view = ref({ x: 0, y: 0, w: 1, h: 1 })
const zoom = ref(1)
let drag: { id: number; x: number; y: number } | null = null

function num(value: unknown, fallback = 0): number {
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed : fallback
}

function pair(value: unknown): [number, number] {
  if (!Array.isArray(value) || value.length < 2) return [0, 0]
  return [num(value[0]), num(value[1])]
}

function boundsOfShapes(shapes: DiagramShape[], annotations: DiagramSpec['annotations']) {
  const xs: number[] = []
  const ys: number[] = []
  for (const shape of shapes) {
    if (shape.kind === 'point') {
      xs.push(num(shape.x)); ys.push(num(shape.y))
    } else if (shape.kind === 'circle') {
      const r = Math.abs(num(shape.r, num(shape.radius)))
      xs.push(num(shape.x) - r, num(shape.x) + r)
      ys.push(num(shape.y) - r, num(shape.y) + r)
    } else if (shape.kind === 'segment' || shape.kind === 'line' || shape.kind === 'vector') {
      const [x1, y1] = pair(shape.from)
      const [x2, y2] = pair(shape.to)
      xs.push(x1, x2); ys.push(y1, y2)
    } else if (shape.kind === 'polygon' && Array.isArray(shape.points)) {
      for (const item of shape.points) {
        const [x, y] = pair(item)
        xs.push(x); ys.push(y)
      }
    } else if (shape.kind === 'curve' && Array.isArray(shape.points)) {
      for (const item of shape.points) {
        const [x, y] = pair(item)
        xs.push(x); ys.push(y)
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

const layout = computed(() => {
  if (props.spec.type === 'tree' || props.spec.type === 'relation' || props.spec.type === 'flow') {
    return layoutForSpec(props.spec)
  }
  const b = boundsOfShapes(props.spec.shapes, props.spec.annotations)
  const pad = 30
  return {
    nodes: [], edges: [],
    width: Math.max(120, b.maxX - b.minX + pad * 2),
    height: Math.max(90, b.maxY - b.minY + pad * 2),
    minX: b.minX - pad,
    minY: b.minY - pad,
  }
})

const worldWidth = computed(() => Math.max(120, layout.value.width))
const worldHeight = computed(() => Math.max(90, layout.value.height))
const minX = computed(() => ('minX' in layout.value ? Number(layout.value.minX) : 0))
const minY = computed(() => ('minY' in layout.value ? Number(layout.value.minY) : 0))

function resetView(): void {
  view.value = { x: minX.value, y: minY.value, w: worldWidth.value, h: worldHeight.value }
  zoom.value = 1
}

function applyViewBox(): void {
  resetView()
}

function onWheel(event: WheelEvent): void {
  event.preventDefault()
  const svg = svgEl.value
  if (!svg) return
  const rect = svg.getBoundingClientRect()
  if (!rect.width || !rect.height) return
  const factor = event.deltaY < 0 ? 1.12 : 1 / 1.12
  const next = Math.min(8, Math.max(0.35, zoom.value * factor))
  const mx = view.value.x + ((event.clientX - rect.left) / rect.width) * view.value.w
  const my = view.value.y + ((event.clientY - rect.top) / rect.height) * view.value.h
  const ratio = next / zoom.value
  view.value = {
    x: mx - (mx - view.value.x) / ratio,
    y: my - (my - view.value.y) / ratio,
    w: view.value.w / ratio,
    h: view.value.h / ratio,
  }
  zoom.value = next
}

function onPointerDown(event: PointerEvent): void {
  if (event.button !== 0) return
  const svg = svgEl.value
  if (!svg) return
  drag = { id: event.pointerId, x: event.clientX, y: event.clientY }
  svg.setPointerCapture(event.pointerId)
}

function onPointerMove(event: PointerEvent): void {
  if (!drag || drag.id !== event.pointerId) return
  const svg = svgEl.value
  if (!svg) return
  const rect = svg.getBoundingClientRect()
  if (!rect.width || !rect.height) return
  const dx = (event.clientX - drag.x) * (view.value.w / rect.width)
  const dy = (event.clientY - drag.y) * (view.value.h / rect.height)
  view.value = { ...view.value, x: view.value.x - dx, y: view.value.y - dy }
  drag = { ...drag, x: event.clientX, y: event.clientY }
}

function onPointerUp(): void {
  drag = null
}

// 首帧与数据变化时重置视图。
resetView()
</script>

<template>
  <div class="diagram-svg-wrap">
    <button class="diagram-reset" type="button" @click="applyViewBox">重置视图</button>
    <svg
      ref="svgEl"
      class="diagram-svg"
      :viewBox="`${view.x} ${view.y} ${view.w} ${view.h}`"
      role="img"
      @wheel="onWheel"
      @pointerdown="onPointerDown"
      @pointermove="onPointerMove"
      @pointerup="onPointerUp"
      @pointercancel="onPointerUp"
    >
      <g v-if="layout.nodes.length">
        <line
          v-for="edge in layout.edges"
          :key="`${edge.from}-${edge.to}`"
          :x1="edge.x1" :y1="edge.y1" :x2="edge.x2" :y2="edge.y2"
          class="diagram-edge"
        />
        <text
          v-for="edge in layout.edges.filter((e) => e.label)"
          :key="`label-${edge.from}-${edge.to}`"
          :x="(edge.x1 + edge.x2) / 2"
          :y="(edge.y1 + edge.y2) / 2 - 4"
          class="diagram-edge-label"
        >{{ edge.label }}</text>
        <g v-for="node in layout.nodes" :key="node.id">
          <rect
            :x="node.x" :y="node.y" :width="node.w" :height="node.h"
            rx="7" class="diagram-node"
          />
          <text
            :x="node.x + node.w / 2" :y="node.y + node.h / 2 + 4"
            text-anchor="middle" class="diagram-node-label"
          >{{ node.label }}</text>
        </g>
      </g>

      <g v-else>
        <g v-for="(shape, i) in spec.shapes" :key="`shape-${i}`">
          <circle
            v-if="shape.kind === 'point'"
            :cx="num(shape.x)" :cy="num(shape.y)" :r="num(shape.r, 4)"
            class="diagram-point"
          />
          <line
            v-else-if="shape.kind === 'segment' || shape.kind === 'line' || shape.kind === 'vector'"
            :x1="pair(shape.from)[0]" :y1="pair(shape.from)[1]"
            :x2="pair(shape.to)[0]" :y2="pair(shape.to)[1]"
            class="diagram-shape-line"
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
          <polyline
            v-else-if="shape.kind === 'curve' && Array.isArray(shape.points)"
            :points="shape.points.map((p) => pair(p).join(',')).join(' ')"
            class="diagram-curve"
          />
          <text
            v-if="shape.label"
            :x="num(shape.x, pair(shape.from)[0])"
            :y="num(shape.y, pair(shape.from)[1]) - 6"
            class="diagram-shape-label"
          >{{ shape.label }}</text>
        </g>
        <text
          v-for="(note, i) in spec.annotations"
          :key="`note-${i}`"
          :x="note.x" :y="note.y"
          class="diagram-annotation"
        >{{ note.text }}</text>
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

.diagram-edge-label {
  fill: var(--text-dim);
  font-size: 9px;
  text-anchor: middle;
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
  fill: #ffd166;
  font-size: 10px;
}
</style>
