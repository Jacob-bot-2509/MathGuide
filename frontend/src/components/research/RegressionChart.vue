<script setup lang="ts">
/** 回归图:拟合散点 + 拟合曲线,或残差 vs 拟合值。前端 SVG 绘制,不引图表库。 */
import { computed, ref } from 'vue'
import type { RegressionResult } from '@/services/researchTableService'

const props = withDefaults(defineProps<{
  result: RegressionResult
  xLabel: string
  yLabel: string
  mode?: 'fit' | 'residual'
}>(), { mode: 'fit' })

const W = 760
const H = 380
const PAD = { left: 70, right: 20, top: 34, bottom: 56 }
const PLOT_W = W - PAD.left - PAD.right
const PLOT_H = H - PAD.top - PAD.bottom
const svgEl = ref<SVGSVGElement | null>(null)

const hasX = computed(() => props.result.points.every((point) => point.x != null))

const rawPoints = computed(() => {
  if (props.mode === 'residual') {
    return props.result.points.map((point) => ({ x: point.fitted, y: point.residual }))
  }
  if (hasX.value) {
    return props.result.points.map((point) => ({ x: point.x as number, y: point.actual }))
  }
  return props.result.points.map((point) => ({ x: point.fitted, y: point.actual }))
})

const curve = computed(() => {
  if (props.mode !== 'fit' || !hasX.value) return []
  return props.result.fitCurve
})

const xRange = computed(() => {
  const values = [...rawPoints.value.map((point) => point.x),
    ...curve.value.map((point) => point.x)]
  if (!values.length) return { min: 0, max: 1 }
  const min = Math.min(...values)
  const max = Math.max(...values)
  if (min === max) return { min: min - 1, max: max + 1 }
  const pad = (max - min) * 0.06
  return { min: min - pad, max: max + pad }
})

const yRange = computed(() => {
  const values = [...rawPoints.value.map((point) => point.y),
    ...curve.value.map((point) => point.y)]
  if (props.mode === 'residual') values.push(0)
  if (!values.length) return { min: 0, max: 1 }
  let min = Math.min(...values)
  let max = Math.max(...values)
  if (min === max) {
    min -= Math.abs(min) * 0.1 || 1
    max += Math.abs(max) * 0.1 || 1
  }
  const pad = (max - min) * 0.08
  return { min: min - pad, max: max + pad }
})

function sx(value: number): number {
  const span = xRange.value.max - xRange.value.min || 1
  return PAD.left + ((value - xRange.value.min) / span) * PLOT_W
}

function sy(value: number): number {
  const span = yRange.value.max - yRange.value.min || 1
  return PAD.top + PLOT_H - ((value - yRange.value.min) / span) * PLOT_H
}

function fmt(value: number): string {
  if (value === 0) return '0'
  const abs = Math.abs(value)
  if (abs >= 10000 || abs < 0.001) return value.toExponential(2)
  return String(Number(value.toPrecision(4)))
}

const yTicks = computed(() => Array.from({ length: 5 }, (_, index) => {
  const { min, max } = yRange.value
  return min + ((max - min) * index) / 4
}))

const xTicks = computed(() => Array.from({ length: 5 }, (_, index) => {
  const { min, max } = xRange.value
  return min + ((max - min) * index) / 4
}))

const curvePath = computed(() => curve.value
  .map((point) => `${sx(point.x)},${sy(point.y)}`)
  .join(' '))

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

function downloadSvg(name = 'regression.svg'): void {
  const text = svgText()
  if (text) saveBlob(new Blob([text], { type: 'image/svg+xml;charset=utf-8' }), name)
}

async function downloadPng(name = 'regression.png'): Promise<void> {
  const text = svgText()
  if (!text) return
  const image = new Image()
  const url = `data:image/svg+xml;charset=utf-8,${encodeURIComponent(text)}`
  await new Promise<void>((resolve, reject) => {
    image.onload = () => resolve()
    image.onerror = () => reject(new Error('regression chart render failed'))
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
  <div class="regression-chart">
    <svg
      ref="svgEl"
      :viewBox="`0 0 ${W} ${H}`"
      role="img"
      :aria-label="mode === 'fit' ? `${yLabel} vs ${xLabel}` : 'residual plot'"
    >
      <rect x="0" y="0" :width="W" :height="H" fill="#0b1220" rx="8" />

      <g class="grid">
        <line
          v-for="(tick, index) in yTicks"
          :key="`gy-${index}`"
          :x1="PAD.left"
          :x2="W - PAD.right"
          :y1="sy(tick)"
          :y2="sy(tick)"
          stroke="#263449"
          stroke-width="1"
        />
        <text
          v-for="(tick, index) in yTicks"
          :key="`ty-${index}`"
          :x="PAD.left - 10"
          :y="sy(tick) + 4"
          fill="#94a3b8"
          font-size="10.5"
          text-anchor="end"
        >{{ fmt(tick) }}</text>
        <text
          v-for="(tick, index) in xTicks"
          :key="`tx-${index}`"
          :x="sx(tick)"
          :y="H - PAD.bottom + 20"
          fill="#94a3b8"
          font-size="10.5"
          text-anchor="middle"
        >{{ fmt(tick) }}</text>
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

      <polyline
        v-if="curvePath"
        :points="curvePath"
        fill="none"
        stroke="#4dd6ff"
        stroke-width="2.2"
      />
      <circle
        v-for="(point, index) in rawPoints"
        :key="`p-${index}`"
        :cx="sx(point.x)"
        :cy="sy(point.y)"
        r="4"
        fill="#f6c85f"
        opacity="0.9"
      />

      <text
        :x="W - PAD.right"
        :y="H - 12"
        fill="#94a3b8"
        font-size="11"
        text-anchor="end"
      >{{ mode === 'fit' ? xLabel : 'fitted' }}</text>
      <text
        :x="14"
        :y="PAD.top + PLOT_H / 2"
        fill="#94a3b8"
        font-size="11"
        text-anchor="middle"
        :transform="`rotate(-90 14 ${PAD.top + PLOT_H / 2})`"
      >{{ mode === 'fit' ? yLabel : 'residual' }}</text>

      <text
        v-if="!rawPoints.length"
        :x="W / 2"
        :y="H / 2"
        fill="#64748b"
        font-size="13"
        text-anchor="middle"
      >无可用数据</text>
    </svg>
  </div>
</template>

<style scoped>
.regression-chart {
  width: 100%;
  overflow: hidden;
  border-radius: 8px;
}

.regression-chart svg {
  display: block;
  width: 100%;
  height: auto;
}
</style>
