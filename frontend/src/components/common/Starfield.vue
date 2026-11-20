<script setup lang="ts">
/**
 * 星空粒子背景:缓慢漂移 + 闪烁的星点,底部透视网格。
 * 全屏 Canvas 动画,开场动画与首页共用。
 */
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { settingsState } from '@/stores/settings'

const canvasRef = ref<HTMLCanvasElement | null>(null)

let raf = 0
let resizeRaf = 0
let width = 0
let height = 0
let ctx: CanvasRenderingContext2D | null = null
/** 网格预渲染到离屏画布:每帧省下约 30 次 stroke,手机端收益明显 */
let gridLayer: HTMLCanvasElement | null = null
/** 网格层对应的主题;主题切换时重建 */
let gridTheme = ''
let stars: Array<{ x: number; y: number; z: number; r: number; phase: number; speed: number }> = []

function makeStars(w: number, h: number) {
  const n = Math.min(260, Math.floor((w * h) / 7000))
  stars = Array.from({ length: n }, () => ({
    x: Math.random() * w,
    y: Math.random() * h,
    z: 0.15 + Math.random() * 0.85, // 深度:影响大小与漂移速度
    r: 0.4 + Math.random() * 1.1,
    phase: Math.random() * Math.PI * 2,
    speed: 0.4 + Math.random() * 1.2,
  }))
}

function drawGrid(ctx: CanvasRenderingContext2D, w = width, h = height) {
  // 底部透视网格:消失点位于画面上方;颜色跟随主题
  const horizon = h * 0.62
  ctx.strokeStyle = settingsState.theme === 'light' ? 'rgba(8, 145, 178, 0.1)' : 'rgba(77, 214, 255, 0.07)'
  ctx.lineWidth = 1

  const rows = 9
  for (let i = 0; i < rows; i++) {
    const t = i / rows
    const y = horizon + Math.pow(t, 2.2) * (h - horizon)
    ctx.beginPath()
    ctx.moveTo(0, y)
    ctx.lineTo(w, y)
    ctx.stroke()
  }

  const vx = w / 2
  for (let i = -10; i <= 10; i++) {
    const topX = vx + i * (w / 40)
    const bottomX = vx + i * (w / 8)
    ctx.beginPath()
    ctx.moveTo(topX, horizon)
    ctx.lineTo(bottomX, h)
    ctx.stroke()
  }
}

/** 把网格画进离屏画布(尺寸不变时可直接贴图,不必每帧重画 30 条线) */
function buildGridLayer(dpr: number): HTMLCanvasElement | null {
  const off = document.createElement('canvas')
  off.width = Math.max(1, Math.round(width * dpr))
  off.height = Math.max(1, Math.round(height * dpr))
  const octx = off.getContext('2d')
  if (!octx) return null
  octx.setTransform(dpr, 0, 0, dpr, 0, 0)
  drawGrid(octx)
  return off
}

function tick(now: number) {
  const canvas = canvasRef.value
  if (!canvas || !ctx) return

  ctx.clearRect(0, 0, width, height)
  const t = now / 1000

  // 星点颜色跟随主题:深色=亮星,浅色=深蓝星(rgba 前缀每帧拼一次,星点间复用)
  const starPrefix = settingsState.theme === 'light' ? 'rgba(30, 64, 120,' : 'rgba(190, 230, 255,'

  for (const s of stars) {
    s.x -= s.z * s.speed * 0.12
    if (s.x < -2) {
      s.x = width + 2
      s.y = Math.random() * height
    }
    const alpha = 0.2 + 0.55 * (0.5 + 0.5 * Math.sin(t * s.speed + s.phase)) * s.z
    ctx.fillStyle = `${starPrefix}${alpha.toFixed(3)})`
    ctx.beginPath()
    ctx.arc(s.x, s.y, s.r * s.z, 0, Math.PI * 2)
    ctx.fill()
  }

  // 网格层跟随主题:切换浅色/深色时重建一次,之后每帧只贴图
  if (!gridLayer || gridTheme !== settingsState.theme) {
    gridLayer = buildGridLayer(Math.min(window.devicePixelRatio || 1, 2))
    gridTheme = settingsState.theme
  }
  if (gridLayer) ctx.drawImage(gridLayer, 0, 0, width, height)

  // 页面不可见时停帧,回到前台再续:省电,也避免后台标签页空转
  raf = document.hidden ? 0 : requestAnimationFrame(tick)
}

function resize() {
  const canvas = canvasRef.value
  if (!canvas) return
  const dpr = Math.min(window.devicePixelRatio || 1, 2)
  width = window.innerWidth
  height = window.innerHeight
  canvas.width = width * dpr
  canvas.height = height * dpr
  canvas.style.width = `${width}px`
  canvas.style.height = `${height}px`
  ctx = canvas.getContext('2d')
  ctx?.setTransform(dpr, 0, 0, dpr, 0, 0)
  gridLayer = buildGridLayer(dpr)
  gridTheme = settingsState.theme
  makeStars(width, height)
}

/** resize 合并到一帧:手机端地址栏收缩会连续触发几十次 resize,
    逐次重建星点既掉帧又让星空位置反复跳变 */
function onResize() {
  if (resizeRaf) return
  resizeRaf = requestAnimationFrame(() => {
    resizeRaf = 0
    resize()
  })
}

function onVisibility() {
  if (document.hidden) {
    cancelAnimationFrame(raf)
    raf = 0
    return
  }
  if (!raf) raf = requestAnimationFrame(tick)
}

onMounted(() => {
  resize()
  window.addEventListener('resize', onResize)
  document.addEventListener('visibilitychange', onVisibility)
  raf = requestAnimationFrame(tick)
})

onBeforeUnmount(() => {
  cancelAnimationFrame(raf)
  if (resizeRaf) cancelAnimationFrame(resizeRaf)
  window.removeEventListener('resize', onResize)
  document.removeEventListener('visibilitychange', onVisibility)
})
</script>

<template>
  <canvas ref="canvasRef" class="starfield" aria-hidden="true"></canvas>
</template>

<style scoped>
.starfield {
  position: fixed;
  inset: 0;
  z-index: 0;
}
</style>
