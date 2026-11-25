<script setup lang="ts">
/**
 * 开场页 —— AI for Science 克制数学流形与公式描边开场：
 * 1. 精密坐标蓝图基底淡入 + 刻度圆环与双曲流形曲线平稳展开
 * 2. MG 几何标志以 SVG 笔迹逐笔绘出（移除旧版黑客 RGB 故障闪烁与乱码滚动）
 * 3. 衬线标题 MathGuide 与副标题浮现，六条经典高数公式以科学语义色逐笔描边书写
 * 4. 约 2.2s 即可点击 CONTINUE（或按 Enter / 右上角 SKIP）进入登录页或首页
 *
 * 同一会话内看过一次后不再播放；URL 加 ?replay=1 强制重播。
 */
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import gsap from 'gsap'
import Starfield from '@/components/common/Starfield.vue'
import MathFormula from '@/components/chat/MathFormula.vue'
import { isLoggedIn } from '@/stores/user'
import { t } from '@/utils/i18n'

const router = useRouter()

const formulasReady = ref(false)
const statusText = ref('INITIALIZING SYMBOLIC ENGINE')

let entered = false
let tl: gsap.core.Timeline | null = null

/* 公式颜色引用 AI-for-Science 语义令牌，深浅双主题自动适配 */
const FORMULAS = [
  { latex: String.raw`e^{i\pi} + 1 = 0`, color: 'var(--accent-primary)', pos: 'tl', size: 'md' },
  {
    latex: String.raw`\int_a^b f(x)\,\mathrm{d}x = \lim_{n\to\infty}\sum_{i=1}^{n} f(x_i^{*})\,\Delta x`,
    color: 'var(--accent-cite)',
    pos: 'tr',
    size: 'sm',
  },
  { latex: String.raw`f(x) = \sum_{n=0}^{\infty} \frac{f^{(n)}(a)}{n!}\,(x-a)^n`, color: 'var(--accent-proof)', pos: 'l', size: 'md' },
  {
    latex: String.raw`\hat{f}(\xi) = \int_{-\infty}^{\infty} f(x)\,e^{-2\pi i x \xi}\,\mathrm{d}x`,
    color: 'var(--accent-primary)',
    pos: 'r',
    size: 'md',
  },
  { latex: String.raw`\int_{-\infty}^{\infty} e^{-x^2}\,\mathrm{d}x = \sqrt{\pi}`, color: 'var(--accent-cite)', pos: 'bl', size: 'lg' },
  { latex: String.raw`\lim_{x \to 0} \frac{\sin x}{x} = 1`, color: 'var(--accent-proof)', pos: 'br', size: 'md' },
]

function enter() {
  if (entered) return
  entered = true
  tl?.kill()
  sessionStorage.setItem('mg-intro-done', '1')
  router.push(isLoggedIn() ? '/home' : '/login')
}

function onKeydown(e: KeyboardEvent) {
  if (e.key === 'Enter' || e.key === 'Escape') enter()
}

onMounted(() => {
  if (sessionStorage.getItem('mg-intro-done') && !new URLSearchParams(window.location.search).has('replay')) {
    enter()
    return
  }

  window.addEventListener('keydown', onKeydown)

  // 准备 MG 标志与流形曲线的逐笔描边长度
  const drawPaths = Array.from(document.querySelectorAll<SVGPathElement>('.draw-path'))
  for (const p of drawPaths) {
    const len = typeof p.getTotalLength === 'function' ? p.getTotalLength() : 320
    p.style.strokeDasharray = `${len}`
    p.style.strokeDashoffset = `${len}`
  }

  tl = gsap.timeline({ defaults: { ease: 'power2.out' } })

  tl.fromTo('.intro-bg', { opacity: 0 }, { opacity: 1, duration: 0.7 }, 0)
  tl.fromTo('.mg-ring', { scale: 0.82, opacity: 0 }, { scale: 1, opacity: 0.7, duration: 0.9 }, 0.1)
  tl.to('.draw-curve', { strokeDashoffset: 0, duration: 1.0, stagger: 0.12 }, 0.15)
  tl.to('.draw-letter', { strokeDashoffset: 0, duration: 1.05, stagger: 0.16, ease: 'power3.inOut' }, 0.25)

  tl.fromTo('.skip', { opacity: 0 }, { opacity: 1, duration: 0.4 }, 0.4)
  tl.fromTo('.wordmark', { opacity: 0, y: 10 }, { opacity: 1, y: 0, duration: 0.65 }, 0.85)
  tl.fromTo('.tagline', { opacity: 0, y: 8 }, { opacity: 1, y: 0, duration: 0.55 }, 1.15)

  tl.call(() => { formulasReady.value = true }, undefined, 0.9)
  tl.call(() => { statusText.value = 'KNOWLEDGE GRAPH · 80 NODES INDEXED' }, undefined, 1.1)
  tl.call(() => { statusText.value = 'WORKBENCH READY' }, undefined, 1.95)

  tl.fromTo('.boot', { opacity: 0 }, { opacity: 1, duration: 0.45 }, 0.5)
  tl.fromTo('.hud', { opacity: 0 }, { opacity: 1, duration: 0.55, stagger: 0.08 }, 1.2)
  tl.fromTo('.enter', { opacity: 0, y: 10 }, { opacity: 1, y: 0, duration: 0.5 }, 1.75)
})

onBeforeUnmount(() => {
  window.removeEventListener('keydown', onKeydown)
  tl?.kill()
})
</script>

<template>
  <div class="intro">
    <Starfield class="intro-bg" />

    <!-- 精密科研角标 -->
    <div class="hud hud-tl tech-label">MATHGUIDE · v1.31.0</div>
    <div class="hud hud-bl tech-label">AI FOR SCIENCE · HIGHER MATHEMATICS</div>
    <div class="hud hud-br tech-label">OBSERVATORY &amp; PREPRINT</div>

    <button class="skip tech-label" type="button" @click="enter">SKIP →</button>

    <!-- 中心:MG 几何笔迹标志 + 学术衬线标题 -->
    <div class="center">
      <div class="logo-stage">
        <svg class="mg-logo" viewBox="0 0 240 120" aria-label="MathGuide 标志">
          <!-- 精密刻度参考圆环与坐标系十字准线 -->
          <g class="mg-ring-wrap">
            <circle
              class="mg-ring"
              cx="120"
              cy="60"
              r="52"
              fill="none"
              stroke-width="0.9"
              stroke-dasharray="3 7"
            />
          </g>
          <!-- 柔和的数学波函数/流形底线 -->
          <path
            class="draw-path draw-curve manifold-a"
            d="M 10 60 C 56 18, 92 102, 138 60 C 172 28, 204 82, 230 56"
            fill="none"
            stroke-width="1"
          />
          <path
            class="draw-path draw-curve manifold-b"
            d="M 14 76 C 64 42, 118 96, 172 48 C 196 28, 214 42, 228 46"
            fill="none"
            stroke-width="0.9"
          />
          <!-- MG 主字形逐笔绘制 -->
          <path
            id="mg-path-m"
            class="draw-path draw-letter"
            d="M 18 102 V 18 L 64 82 L 110 18 V 102"
            fill="none"
            stroke="currentColor"
            stroke-width="3"
            stroke-linecap="round"
            stroke-linejoin="round"
          />
          <path
            id="mg-path-g"
            class="draw-path draw-letter"
            d="M 180 20 A 38 38 0 1 0 180 96 A 38 38 0 0 1 218 58 H 176"
            fill="none"
            stroke="currentColor"
            stroke-width="3"
            stroke-linecap="round"
            stroke-linejoin="round"
          />
        </svg>
      </div>

      <h1 class="wordmark">MathGuide</h1>
      <p class="tagline">{{ t('intro.tagline') }}</p>
      <p class="boot tech-label">
        <span class="boot-dot"></span>
        <span>{{ statusText }}</span>
      </p>

      <button class="enter" type="button" @click="enter">
        <span>CONTINUE</span>
        <span class="enter-arrow">→</span>
      </button>
    </div>

    <!-- 环绕经典数学公式(逐笔书写) -->
    <div class="formulas">
      <div
        v-for="(f, i) in FORMULAS"
        :key="f.pos"
        class="f-slot"
        :class="[`f-pos-${f.pos}`, `f-size-${f.size}`]"
      >
        <MathFormula :latex="f.latex" :color="f.color" :trigger="formulasReady" :delay="i * 0.24" />
      </div>
    </div>
  </div>
</template>

<style scoped>
.intro {
  position: fixed;
  inset: 0;
  /* iOS Safari 下 fixed 高度可能按含工具栏的布局视口计算,dvh 锁定可见视口 */
  height: 100vh;
  height: 100dvh;
  overflow: hidden;
  background: var(--bg-void);
}

.intro-bg {
  position: absolute;
  inset: 0;
  z-index: 0;
}

.hud {
  position: fixed;
  z-index: 3;
  opacity: 0;
  color: var(--text-dim);
  font-size: 10.5px;
}

.hud-tl {
  top: calc(18px + env(safe-area-inset-top));
  left: calc(22px + env(safe-area-inset-left));
}

.hud-bl {
  bottom: calc(18px + env(safe-area-inset-bottom));
  left: calc(22px + env(safe-area-inset-left));
}

.hud-br {
  bottom: calc(18px + env(safe-area-inset-bottom));
  right: calc(22px + env(safe-area-inset-right));
}

.skip {
  position: fixed;
  top: calc(14px + env(safe-area-inset-top));
  right: calc(18px + env(safe-area-inset-right));
  z-index: 5;
  opacity: 0;
  background: var(--bg-card);
  border: 1px solid var(--line);
  border-radius: 7px;
  color: var(--text-dim);
  padding: 6px 13px;
  cursor: pointer;
  transition: all var(--dur-fast) var(--ease-out);
}

.skip:hover {
  color: var(--text-hi);
  border-color: var(--line-bright);
}

.center {
  position: absolute;
  z-index: 2;
  inset: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 24px;
  text-align: center;
}

.logo-stage {
  position: relative;
  width: min(44vw, 340px);
}

.mg-logo {
  display: block;
  width: 100%;
}

.mg-ring-wrap {
  animation: mg-spin 64s linear infinite;
  transform-box: fill-box;
  transform-origin: center;
}

.mg-ring {
  opacity: 0;
  stroke: color-mix(in srgb, var(--accent-primary) 42%, var(--line));
}

.manifold-a {
  stroke: color-mix(in srgb, var(--accent-primary) 34%, transparent);
}

.manifold-b {
  stroke: color-mix(in srgb, var(--accent-cite) 34%, transparent);
}

#mg-path-m {
  color: var(--accent-primary);
}

#mg-path-g {
  color: var(--accent-cite);
}

.wordmark {
  margin: 12px 0 0;
  opacity: 0;
  font-family: var(--font-serif);
  font-size: clamp(34px, 5vw, 54px);
  font-weight: 500;
  letter-spacing: -0.015em;
  color: var(--text-hi);
}

.tagline {
  margin: 4px 0 0;
  opacity: 0;
  color: var(--text-dim);
  font-size: 15px;
  letter-spacing: 0.08em;
}

.boot {
  margin: 10px 0 0;
  opacity: 0;
  display: inline-flex;
  align-items: center;
  gap: 8px;
  font-size: 11px;
  color: var(--text-dim);
}

.boot-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--accent-proof);
}

.enter {
  margin-top: 22px;
  opacity: 0;
  display: inline-flex;
  align-items: center;
  gap: 10px;
  background: var(--accent-primary);
  border: 1px solid var(--accent-primary);
  color: #ffffff;
  font-family: var(--font-tech);
  font-size: 12.5px;
  font-weight: 600;
  letter-spacing: 0.16em;
  padding: 11px 30px;
  cursor: pointer;
  border-radius: 8px;
  box-shadow: var(--shadow-md);
  transition: filter var(--dur-fast) var(--ease-out), transform var(--dur-fast) var(--ease-out);
}

.enter:hover {
  filter: brightness(1.08);
  transform: translateY(-1px);
}

.enter-arrow {
  transition: transform var(--dur-fast) var(--ease-out);
}

.enter:hover .enter-arrow {
  transform: translateX(4px);
}

/* ---------- 环绕公式 ---------- */
.formulas {
  position: absolute;
  inset: 0;
  z-index: 1;
  pointer-events: none;
  opacity: 0.82;
}

.f-slot {
  position: absolute;
}

.f-pos-tl {
  top: 14%;
  left: 5%;
}

.f-pos-tr {
  top: 15%;
  right: 4%;
}

.f-pos-l {
  top: 44%;
  left: 3.5%;
}

.f-pos-r {
  top: 44%;
  right: 3.5%;
}

.f-pos-bl {
  bottom: 16%;
  left: 6%;
}

.f-pos-br {
  bottom: 16%;
  right: 6%;
}

.f-size-sm {
  font-size: 15px;
}

.f-size-md {
  font-size: 19px;
}

.f-size-lg {
  font-size: 22px;
}

@media (max-width: 900px) {
  .formulas,
  .hud {
    display: none;
  }
}

@media (max-width: 600px) {
  .logo-stage {
    width: min(64vw, 250px);
  }

  .tagline {
    font-size: 13.5px;
    letter-spacing: 0.04em;
    max-width: 30ch;
  }

  .enter {
    min-height: 44px;
    padding: 11px 28px;
  }
}

/* 手机横屏矮视口:压缩徽标与上下间距,确保 CONTINUE 按钮不被裁出屏幕底部 */
@media (max-height: 520px) {
  .center {
    gap: 4px;
    padding: calc(12px + env(safe-area-inset-top)) 20px calc(12px + env(safe-area-inset-bottom));
  }

  .logo-stage {
    width: min(26vw, 180px);
  }

  .wordmark {
    margin-top: 4px;
    font-size: clamp(24px, 4.5vw, 32px);
  }

  .tagline {
    font-size: 12.5px;
  }

  .boot {
    margin-top: 4px;
  }

  .enter {
    margin-top: 10px;
    padding: 8px 24px;
  }
}
</style>
