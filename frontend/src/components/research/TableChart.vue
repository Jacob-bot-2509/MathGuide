<script setup lang="ts">
/**
 * 数据表图表:折线 / 散点 / 柱状,输出 SVG 与 PNG。
 * 不引入图表库,坐标与刻度在前端按服务端统计序列绘制,数值不二次计算。
 */
import { computed, ref } from 'vue'
import type { TableSeries } from '@/services/researchTableService'

const props = withDefaults(defineProps<{
  labels: string[]
  series: TableSeries[]
  chartType: 'line' | 'scatter' | 'bar'
  xValues?: (number | null)[] | null
}>(), { xValues: null })

const W = 760
const H = 380
const PAD = { left: 62, right: 18, top: 42, bottom: 58 }
const PLOT_W = W - PAD.left - PAD.right
const PLOT_H = H - PAD.top - PAD.bottom
const COLORS = ['#4dd6ff', '#f6c85f', '#7ee787', '#ff8a8a', '#c792ea', '#ffa657']

const svgEl = ref<SVGSVGElement | null>(null)

const count = computed(() => Math.max(
  props.labels.length,
  ...props.series.map((s) => s.values.length),
  0,
))

const numericX = computed(() => props.xValues != null)

const xRaw = computed<(number | null)[]>(() => Array.from({ length: count.value }, (_, i) => {
  const value = props.xValues?.[i]
  if (!numericX.value) return i
  return typeof value === 'number' && Number.isFinite(value) ? value : null
}))

const validX = computed(() => xRaw.value.filter((x): x is number => x !== null))

const xMin = computed(() => {
  if (!numericX.value) return -0.5
  return validX.value.length ? Math.min(...validX.value) : 0
})

const xMax = computed(() => {
  if (!numericX.value) return Math.max(count.value - 0.5, 0.5)
  const max = validX.value.length ? Math.max(...validX.value) : 1
  return max === (xMin.value) ? max + 1 : max
})

const yRange = computed(() => {
  const values: number[] = []
  for (const s of props.series) {
    s.values.forEach((v, i) => {
      if (xRaw.value[i] != null && typeof v === 'number' && Number.isFinite(v)) values.push(v)
    })
  }
  if (!values.length) return { min: 0, max: 1 }
  let min = Math.min(...values)
  let max = Math.max(...values)
  if (props.chartType === 'bar') {
    min = Math.min(0, min)
    max = Math.max(0, max)
  }
  if (min === max) {
    const pad = Math.abs(min) * 0.1 || 1
    min -= pad
    max += pad
  }
  const pad = (max - min) * 0.08
  return { min: min - pad, max: max + pad }
})

function sx(x: number): number {
  const span = xMax.value - xMin.value || 1
  return PAD.left + ((x - xMin.value) / span) * PLOT_W
}

function sy(y: number): number {
  const span = yRange.value.max - yRange.value.min || 1
  return PAD.top + PLOT_H - ((y - yRange.value.min) / span) * PLOT_H
}

function fmt(value: number): string {
  if (value === 0) return '0'
  const abs = Math.abs(value)
  if (abs >= 10000 || abs < 0.001) return value.toExponential(2)
  return String(Number(value.toPrecision(4)))
}

const yTicks = computed(() => {
  const { min, max } = yRange.value
  return Array.from({ length: 5 }, (_, i) => min + ((max - min) * i) / 4)
})

const xTicks = computed(() => {
  if (!count.value) return [] as { x: number; label: string }[]
  if (numericX.value) {
    return Array.from({ length: 5 }, (_, i) => {
      const x = xMin.value + ((xMax.value - xMin.value) * i) / 4
      return { x: sx(x), label: fmt(x) }
    })
  }
  const step = Math.max(1, Math.ceil(count.value / 8))
  const out: { x: number; label: string }[] = []
  for (let i = 0; i < count.value; i += step) {
    out.push({ x: sx(i), label: (props.labels[i] || String(i + 1)).slice(0, 12) })
  }
  return out
})

function pointX(i: number): number {
  return sx(xRaw.value[i]!)
}

function pointY(value: number): number {
  return sy(value)
}

const lineSegments = computed(() => props.series.map((s, si) => {
  const segments: string[] = []
  let current: string[] = []
  s.values.forEach((v, i) => {
    if (xRaw.value[i] != null && typeof v === 'number' && Number.isFinite(v)) {
      current.push(`${pointX(i)},${pointY(v)}`)
    } else if (current.length) {
      segments.push(current.join(' '))
      current = []
    }
  })
  if (current.length) segments.push(current.join(' '))
  return { color: COLORS[si % COLORS.length], segments }
}))

const scatterPoints = computed(() => props.series.flatMap((s, si) =>
  s.values.flatMap((v, i) => (xRaw.value[i] != null && typeof v === 'number' && Number.isFinite(v)
    ? [{ x: pointX(i), y: pointY(v), color: COLORS[si % COLORS.length], key: `${si}-${i}` }]
    : []))))

const bars = computed(() => {
  if (!count.value || !props.series.length) return []
  const groupWidth = PLOT_W / Math.max(count.value, 1)
  const barWidth = Math.max(2, (groupWidth * 0.72) / props.series.length)
  const baseline = sy(0)
  const out: { x: number; y: number; w: number; h: number; color: string; key: string }[] = []
  props.series.forEach((s, si) => {
    s.values.forEach((v, i) => {
      if (xRaw.value[i] == null || typeof v !== 'number' || !Number.isFinite(v)) return
      const center = pointX(i) - (groupWidth * 0.72) / 2 + barWidth * si + barWidth / 2
      const y = sy(v)
      out.push({
        x: center - barWidth / 2,
        y: Math.min(y, baseline),
        w: barWidth,
        h: Math.max(1, Math.abs(baseline - y)),
        color: COLORS[si % COLORS.length],
        key: `${si}-${i}`,
      })
    })
  })
  return out
})

const hasData = computed(() => scatterPoints.value.length > 0)

/** 序列化 SVG(补 xmlns,脱离页面样式也能打开) */
function svgText(): string {
  if (!svgEl.value) return ''
  const clone = svgEl.value.cloneNode(true) as SVGSVGElement
  clone.setAttribute('xmlns', 'http://www.w3.org/2000/svg')
  clone.setAttribute('width', String(W))
  clone.setAttribute('height', String(H))
  return new XMLSerializer().serializeToString(clone)
}

function saveBlob(blob: Blob, name: string): void {
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = name
  document.body.appendChild(a)
  a.click()
  a.remove()
  URL.revokeObjectURL(url)
}

function downloadSvg(name = 'chart.svg'): void {
  const text = svgText()
  if (text) saveBlob(new Blob([text], { type: 'image/svg+xml;charset=utf-8' }), name)
}

async function downloadPng(name = 'chart.png'): Promise<void> {
  const text = svgText()
  if (!text) return
  const image = new Image()
  const url = `data:image/svg+xml;charset=utf-8,${encodeURIComponent(text)}`
  await new Promise<void>((resolve, reject) => {
    image.onload = () => resolve()
    image.onerror = () => reject(new Error('chart render failed'))
    image.src = url
  })
  const scale = 2
  const canvas = document.createElement('canvas')
  canvas.width = W * scale
  canvas.height = H * scale
  const ctx = canvas.getContext('2d')
  if (!ctx) return
  ctx.fillStyle = '#0b1220'
  ctx.fillRect(0, 0, canvas.width, canvas.height)
  ctx.drawImage(image, 0, 0, canvas.width, canvas.height)
  const blob = await new Promise<Blob | null>((resolve) =>
    canvas.toBlob(resolve, 'image/png'))
  if (blob) saveBlob(blob, name)
}

defineExpose({ downloadSvg, downloadPng })
</script>

<template>
  <div class="chart-box">
    <svg
      ref="svgEl"
      class="chart"
      :viewBox="`0 0 ${W} ${H}`"
      role="img"
      :aria-label="labels.join(', ')"
    >
      <rect x="0" y="0" :width="W" :height="H" fill="#0b1220" rx="8" />
      <g class="legend">
        <template v-for="(s, si) in series" :key="s.key">
          <rect
            :x="PAD.left + si * 112"
            y="14"
            width="9"
            height="9"
            rx="2"
            :fill="COLORS[si % COLORS.length]"
          />
          <text
            :x="PAD.left + si * 112 + 14"
            y="23"
            fill="#cbd5e1"
            font-size="11"
          >{{ s.label.slice(0, 10) }}</text>
        </template>
      </g>

      <g class="grid">
        <line
          v-for="(tick, i) in yTicks"
          :key="`gy-${i}`"
          :x1="PAD.left"
          :x2="W - PAD.right"
          :y1="sy(tick)"
          :y2="sy(tick)"
          stroke="#263449"
          stroke-width="1"
        />
        <text
          v-for="(tick, i) in yTicks"
          :key="`ty-${i}`"
          :x="PAD.left - 9"
          :y="sy(tick) + 4"
          fill="#94a3b8"
          font-size="10.5"
          text-anchor="end"
        >{{ fmt(tick) }}</text>
        <text
          v-for="(tick, i) in xTicks"
          :key="`tx-${i}`"
          :x="tick.x"
          :y="H - PAD.bottom + 20"
          fill="#94a3b8"
          font-size="10.5"
          text-anchor="middle"
        >{{ tick.label }}</text>
      </g>

      <line
        :x1="PAD.left"
        :x2="W - PAD.right"
        :y1="sy(0)"
        :y2="sy(0)"
        stroke="#475569"
        stroke-width="1"
      />
      <line
        :x1="PAD.left"
        :x2="PAD.left"
        :y1="PAD.top"
        :y2="PAD.top + PLOT_H"
        stroke="#475569"
        stroke-width="1"
      />

      <g v-if="chartType === 'bar'">
        <rect
          v-for="bar in bars"
          :key="bar.key"
          :x="bar.x"
          :y="bar.y"
          :width="bar.w"
          :height="bar.h"
          :fill="bar.color"
          opacity="0.82"
          rx="1.5"
        />
      </g>
      <g v-else>
        <template v-if="chartType === 'line'">
          <template v-for="(line, li) in lineSegments" :key="`ln-${li}`">
            <polyline
              v-for="(segment, i) in line.segments"
              :key="i"
              fill="none"
              :stroke="line.color"
              stroke-width="2"
              :points="segment"
            />
          </template>
          <circle
            v-for="point in scatterPoints"
            :key="`p-${point.key}`"
            :cx="point.x"
            :cy="point.y"
            r="3"
            :fill="point.color"
            stroke="#0b1220"
            stroke-width="1"
          />
        </template>
        <circle
          v-for="point in scatterPoints"
          v-else
          :key="`s-${point.key}`"
          :cx="point.x"
          :cy="point.y"
          r="4"
          :fill="point.color"
          opacity="0.88"
        />
      </g>

      <text
        v-if="!hasData"
        :x="W / 2"
        :y="H / 2"
        fill="#64748b"
        font-size="13"
        text-anchor="middle"
      >无可用数值</text>
    </svg>
  </div>
</template>

<style scoped>
.chart-box {
  width: 100%;
  overflow: hidden;
  border-radius: 8px;
}

.chart {
  display: block;
  width: 100%;
  height: auto;
}
</style>
