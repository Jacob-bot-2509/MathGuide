<script setup lang="ts">
/**
 * 星空粒子背景:缓慢漂移 + 闪烁的星点,底部透视网格。
 * 全屏 Canvas 动画,开场动画与首页共用。
 */
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { settingsState } from '@/stores/settings'

const canvasRef = ref<HTMLCanvasElement | null>(null)

let raf = 0
let width = 0
let height = 0
let ctx: CanvasRenderingContext2D | null = null
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

function drawGrid(ctx: CanvasRenderingContext2D) {
  // 底部透视网格:消失点位于画面上方;颜色跟随主题
  const horizon = height * 0.62
  ctx.strokeStyle = settingsState.theme === 'light' ? 'rgba(8, 145, 178, 0.1)' : 'rgba(77, 214, 255, 0.07)'
  ctx.lineWidth = 1

  const rows = 9
  for (let i = 0; i < rows; i++) {
    const t = i / rows
    const y = horizon + Math.pow(t, 2.2) * (height - horizon)
    ctx.beginPath()
    ctx.moveTo(0, y)
    ctx.lineTo(width, y)
    ctx.stroke()
  }

  const vx = width / 2
  for (let i = -10; i <= 10; i++) {
    const topX = vx + i * (width / 40)
    const bottomX = vx + i * (width / 8)
    ctx.beginPath()
    ctx.moveTo(topX, horizon)
    ctx.lineTo(bottomX, height)
    ctx.stroke()
  }
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

  drawGrid(ctx)
  raf = requestAnimationFrame(tick)
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
  makeStars(width, height)
}

onMounted(() => {
  resize()
  window.addEventListener('resize', resize)
  raf = requestAnimationFrame(tick)
})

onBeforeUnmount(() => {
  cancelAnimationFrame(raf)
  window.removeEventListener('resize', resize)
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
