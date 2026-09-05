<script setup lang="ts">
/**
 * 开场动画 —— 以 MG(MathGuide)标志为中心,黑客/科幻电影风格登场:
 * 1. 星空背景淡入 + 圆环展开
 * 2. MG 以"故障乱码"方式闪现(RGB 分裂 + 抖动),最终定格为完整标志
 * 3. 标题 MATHGUIDE 以乱码逐字解码还原,副标题浮现
 * 4. 六条高等数学经典公式环绕,逐笔描边书写
 * 5. 点击 CONTINUE 进入首页(不自动跳转);右上角可随时 SKIP
 *
 * 同一会话内看过一次后不再播放;URL 加 ?replay=1 强制重播。
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
const bootText = ref('MG CORE · BOOTING')
const bootWarn = ref(false)

let entered = false
let tl: gsap.core.Timeline | null = null
let scrambleIntervals: Array<ReturnType<typeof setInterval>> = []
let scrambleTimeouts: Array<ReturnType<typeof setTimeout>> = []

/* 公式颜色引用主题变量,深浅色自动适配 */
const FORMULAS = [
  { latex: String.raw`e^{i\pi} + 1 = 0`, color: 'var(--cyan)', pos: 'tl', size: 'md' },
  {
    latex: String.raw`\int_a^b f(x)\,\mathrm{d}x = \lim_{n\to\infty}\sum_{i=1}^{n} f(x_i^{*})\,\Delta x`,
    color: 'var(--magenta)',
    pos: 'tr',
    size: 'sm',
  },
  { latex: String.raw`f(x) = \sum_{n=0}^{\infty} \frac{f^{(n)}(a)}{n!}\,(x-a)^n`, color: 'var(--violet)', pos: 'l', size: 'md' },
  {
    latex: String.raw`\hat{f}(\xi) = \int_{-\infty}^{\infty} f(x)\,e^{-2\pi i x \xi}\,\mathrm{d}x`,
    color: 'var(--cyan)',
    pos: 'r',
    size: 'md',
  },
  { latex: String.raw`\int_{-\infty}^{\infty} e^{-x^2}\,\mathrm{d}x = \sqrt{\pi}`, color: 'var(--magenta)', pos: 'bl', size: 'lg' },
  { latex: String.raw`\lim_{x \to 0} \frac{\sin x}{x} = 1`, color: 'var(--violet)', pos: 'br', size: 'md' },
]

/* 乱码字符集 */
const GLYPHS = '!<>-_\\/[]{}—=+*^?#@%&$01'

/** 乱码解码:每个字符先随机滚动乱码,再按序还原为目标字符(定时器登记在册,卸载时统一清理) */
function scrambleLetters(spans: HTMLSpanElement[], word: string, opts: { delay: number; duration: number }) {
  const settleStep = opts.duration / word.length
  spans.forEach((span, idx) => {
    const settleAt = (opts.delay + idx * settleStep) * 1000
    const tick = setInterval(() => {
      span.textContent = GLYPHS[Math.floor(Math.random() * GLYPHS.length)]
    }, 45)
    scrambleIntervals.push(tick)
    const to = setTimeout(() => {
      clearInterval(tick)
      span.textContent = word[idx]
    }, settleAt)
    scrambleTimeouts.push(to)
  })
}

/** 故障闪烁:随机可见性 + 随机位移/拉伸,结束时隐藏 */
function makeGlitch(target: gsap.TweenTarget, duration: number) {
  const t = gsap.timeline()
  const steps = Math.floor(duration / 0.08)
  for (let i = 0; i < steps; i++) {
    t.set(target, {
      opacity: gsap.utils.random(0, 0.85),
      x: gsap.utils.random(-9, 9),
      y: gsap.utils.random(-4, 4),
      scaleX: gsap.utils.random(0.985, 1.015),
    })
    t.to(target, { duration: 0.08 })
  }
  t.set(target, { x: 0, y: 0, scaleX: 1, opacity: 0 })
  return t
}

/** 主体标志的闪现:偶尔露出,最终完全定格 */
function makeRevealFlicker(target: gsap.TweenTarget, duration: number) {
  const t = gsap.timeline()
  const steps = Math.floor(duration / 0.1)
  for (let i = 0; i < steps; i++) {
    t.set(target, { opacity: Math.random() < 0.22 ? 1 : 0 })
    t.to(target, { duration: 0.1 })
  }
  t.set(target, { opacity: 1 })
  return t
}

function enter() {
  if (entered) return
  entered = true
  sessionStorage.setItem('mg-intro-done', '1')
  // 未登录先进登录页,已登录直达首页
  router.push(isLoggedIn() ? '/home' : '/login')
}

function skip() {
  if (entered) return
  entered = true
  tl?.kill()
  sessionStorage.setItem('mg-intro-done', '1')
  router.push(isLoggedIn() ? '/home' : '/login')
}

onMounted(() => {
  // 本会话已播放过则直接进入首页
  if (sessionStorage.getItem('mg-intro-done') && !new URLSearchParams(window.location.search).has('replay')) {
    enter()
    return
  }

  // 标题乱码解码(与主时间线并行的独立动画)
  const letters = Array.from(document.querySelectorAll<HTMLSpanElement>('.wordmark-letter'))
  scrambleLetters(letters, 'MATHGUIDE', { delay: 2.0, duration: 1.5 })

  tl = gsap.timeline({ defaults: { ease: 'power2.out' } })

  tl.fromTo('.intro-bg', { opacity: 0 }, { opacity: 1, duration: 1.4 }, 0)
  tl.fromTo('.mg-ring', { scale: 0.4, opacity: 0 }, { scale: 1, opacity: 0.55, duration: 1.4 }, 0.2)

  // MG 故障登场:RGB 分裂副本闪烁 + 主体闪现 → 定格 + 闪光
  tl.add(makeGlitch('.mg-copy--cyan', 1.25), 0.6)
  tl.add(makeGlitch('.mg-copy--magenta', 1.25), 0.6)
  tl.add(makeRevealFlicker('.mg-logo--main', 1.25), 0.6)
  tl.fromTo(
    '.flash',
    { opacity: 0 },
    { opacity: 0.5, duration: 0.12, yoyo: true, repeat: 1, ease: 'power1.out' },
    1.85,
  )

  tl.fromTo('.skip', { opacity: 0 }, { opacity: 1, duration: 0.6 }, 1.2)

  // 标题(乱码解码由 scrambleLetters 并行完成)
  tl.fromTo('.wordmark', { opacity: 0 }, { opacity: 1, duration: 0.4 }, 2.0)
  tl.fromTo('.tagline', { opacity: 0, y: 12 }, { opacity: 1, y: 0, duration: 0.7 }, 3.6)

  // 公式开始描边
  tl.call(
    () => {
      formulasReady.value = true
    },
    undefined,
    2.8,
  )

  // BOOTING 叙事:拒绝 → 覆盖 → 就绪
  tl.call(
    () => {
      bootText.value = 'ACCESS DENIED'
      bootWarn.value = true
    },
    undefined,
    0.7,
  )
  tl.call(
    () => {
      bootText.value = 'OVERRIDE ACCEPTED'
    },
    undefined,
    1.6,
  )
  tl.call(
    () => {
      bootText.value = 'MG CORE · READY'
      bootWarn.value = false
    },
    undefined,
    2.5,
  )
  tl.fromTo('.boot', { opacity: 0 }, { opacity: 1, duration: 0.6 }, 0.8)

  tl.fromTo('.hud', { opacity: 0 }, { opacity: 1, duration: 0.8, stagger: 0.1 }, 3.6)
  tl.fromTo('.enter', { opacity: 0, y: 14 }, { opacity: 1, y: 0, duration: 0.6 }, 6.0)
})

onBeforeUnmount(() => {
  tl?.kill()
  // 乱码解码的定时器与主时间线无关:SKIP/路由跳转时须一并清掉,避免空转
  for (const t of scrambleTimeouts) clearTimeout(t)
  scrambleTimeouts = []
  for (const i of scrambleIntervals) clearInterval(i)
  scrambleIntervals = []
})
</script>

<template>
  <div class="intro">
    <Starfield class="intro-bg" />

    <!-- HUD 装饰 -->
    <div class="hud hud-tl tech-label">MG SYSTEM · v0.1.0</div>
    <div class="hud hud-bl tech-label">EST. 2026 · HIGHER MATHEMATICS</div>
    <div class="hud hud-br tech-label">AI ASSISTANT · ONLINE</div>

    <!-- 定格闪光 -->
    <div class="flash"></div>

    <button class="skip tech-label" @click="skip">SKIP ⏭</button>

    <!-- 中心:MG 标志(故障登场)+ 标题 -->
    <div class="center">
      <div class="logo-stage">
        <svg class="mg-logo mg-logo--main" viewBox="0 0 240 120" aria-label="MG 标志">
          <g class="mg-ring-wrap">
            <circle
              class="mg-ring"
              cx="120"
              cy="60"
              r="52"
              fill="none"
              stroke-width="1"
              stroke-dasharray="5 9"
            />
          </g>
          <path
            id="mg-path-m"
            d="M 12 108 V 14 L 62 86 L 112 14 V 108"
            fill="none"
            stroke="currentColor"
            stroke-width="3.5"
            stroke-linecap="round"
            stroke-linejoin="round"
          />
          <path
            id="mg-path-g"
            d="M 182 16 A 40 40 0 1 0 182 96 A 40 40 0 0 1 222 56 H 178"
            fill="none"
            stroke="currentColor"
            stroke-width="3.5"
            stroke-linecap="round"
            stroke-linejoin="round"
          />
        </svg>
        <!-- RGB 分裂副本(仅故障期显示,screen 混合) -->
        <svg class="mg-copy mg-copy--cyan" viewBox="0 0 240 120" aria-hidden="true">
          <path
            d="M 12 108 V 14 L 62 86 L 112 14 V 108"
            fill="none"
            stroke="currentColor"
            stroke-width="3.5"
            stroke-linecap="round"
            stroke-linejoin="round"
          />
          <path
            d="M 182 16 A 40 40 0 1 0 182 96 A 40 40 0 0 1 222 56 H 178"
            fill="none"
            stroke="currentColor"
            stroke-width="3.5"
            stroke-linecap="round"
            stroke-linejoin="round"
          />
        </svg>
        <svg class="mg-copy mg-copy--magenta" viewBox="0 0 240 120" aria-hidden="true">
          <path
            d="M 12 108 V 14 L 62 86 L 112 14 V 108"
            fill="none"
            stroke="currentColor"
            stroke-width="3.5"
            stroke-linecap="round"
            stroke-linejoin="round"
          />
          <path
            d="M 182 16 A 40 40 0 1 0 182 96 A 40 40 0 0 1 222 56 H 178"
            fill="none"
            stroke="currentColor"
            stroke-width="3.5"
            stroke-linecap="round"
            stroke-linejoin="round"
          />
        </svg>
      </div>

      <h1 class="wordmark" aria-label="MathGuide">
        <span v-for="(ch, i) in 'MATHGUIDE'" :key="i" class="wordmark-letter">{{ ch }}</span>
      </h1>
      <p class="tagline">{{ t('intro.tagline') }}</p>
      <p class="boot tech-label" :class="{ 'boot-warn': bootWarn }">{{ bootText }}<span class="cursor">_</span></p>

      <button class="enter" @click="enter">
        <span>CONTINUE</span>
        <span class="enter-arrow">⏎</span>
      </button>
    </div>

    <!-- 环绕公式 -->
    <div class="formulas">
      <div
        v-for="(f, i) in FORMULAS"
        :key="f.pos"
        class="f-slot"
        :class="[`f-pos-${f.pos}`, `f-size-${f.size}`]"
      >
        <MathFormula :latex="f.latex" :color="f.color" :trigger="formulasReady" :delay="i * 0.35" />
      </div>
    </div>
  </div>
</template>

<style scoped>
.intro {
  position: fixed;
  inset: 0;
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
  font-size: 11px;
}

.hud-tl {
  top: 18px;
  left: 22px;
}

.hud-bl {
  bottom: 18px;
  left: 22px;
}

.hud-br {
  bottom: 18px;
  right: 22px;
}

.flash {
  position: fixed;
  inset: 0;
  z-index: 6;
  pointer-events: none;
  opacity: 0;
  /* 闪光颜色跟随主题,白底用青色光晕 */
  background: radial-gradient(circle at 50% 45%, color-mix(in srgb, var(--cyan) 40%, transparent), transparent 60%);
}

.skip {
  position: fixed;
  top: 14px;
  right: 18px;
  z-index: 5;
  opacity: 0;
  background: transparent;
  border: 1px solid var(--line);
  color: var(--text-dim);
  padding: 6px 14px;
  cursor: pointer;
  transition: all var(--dur-fast) var(--ease-out);
}

.skip:hover {
  color: var(--cyan);
  border-color: var(--line-bright);
  box-shadow: var(--glow-cyan);
}

.center {
  position: absolute;
  z-index: 2;
  inset: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 6px;
}

/* ---------- MG 标志:故障登场 ---------- */
.logo-stage {
  position: relative;
  width: min(46vw, 420px);
}

.mg-logo {
  display: block;
  width: 100%;
}

.mg-logo--main {
  opacity: 0;
}

.mg-copy {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  mix-blend-mode: screen;
  opacity: 0;
}

/* 圆环:外层 g 持续旋转,内层 circle 由 GSAP 控制展开 */
.mg-ring-wrap {
  animation: mg-spin 40s linear infinite;
  transform-box: fill-box;
  transform-origin: center;
}

/* MG 颜色与辉光全部引用主题变量,深浅色自动适配 */
.mg-ring {
  opacity: 0;
  stroke: color-mix(in srgb, var(--blue) 40%, transparent);
}

#mg-path-m {
  color: var(--cyan);
  filter: drop-shadow(0 0 6px color-mix(in srgb, var(--cyan) 70%, transparent));
}

#mg-path-g {
  color: var(--magenta);
  filter: drop-shadow(0 0 6px color-mix(in srgb, var(--magenta) 70%, transparent));
}

.mg-copy--cyan {
  color: var(--cyan);
}

.mg-copy--cyan path {
  filter: drop-shadow(0 0 6px color-mix(in srgb, var(--cyan) 70%, transparent));
}

.mg-copy--magenta {
  color: var(--magenta);
}

.mg-copy--magenta path {
  filter: drop-shadow(0 0 6px color-mix(in srgb, var(--magenta) 70%, transparent));
}

/* ---------- 标题 ---------- */
.wordmark {
  margin: 18px 0 0;
  opacity: 0;
  font-family: var(--font-tech);
  font-size: clamp(30px, 5.4vw, 56px);
  font-weight: 600;
  letter-spacing: 0.16em;
  background: linear-gradient(92deg, var(--cyan), var(--violet) 55%, var(--magenta));
  -webkit-background-clip: text;
  background-clip: text;
  color: transparent;
  /* 解码完成后才进入呼吸动画(动画延迟避免与入场透明度冲突) */
  animation: mg-pulse 4s ease-in-out 3.2s infinite;
}

.wordmark-letter {
  display: inline-block;
}

.tagline {
  margin: 10px 0 0;
  opacity: 0;
  color: var(--text);
  font-size: 16px;
  letter-spacing: 0.24em;
}

.boot {
  margin: 14px 0 0;
  opacity: 0;
  font-size: 12px;
  color: var(--text-dim);
}

.boot-warn {
  color: var(--danger);
}

.cursor {
  animation: mg-blink 1.1s steps(1) infinite;
  color: var(--cyan);
}

.enter {
  margin-top: 30px;
  opacity: 0;
  display: inline-flex;
  align-items: center;
  gap: 12px;
  background: color-mix(in srgb, var(--cyan) 8%, transparent);
  border: 1px solid var(--line-bright);
  color: var(--cyan);
  font-family: var(--font-tech);
  letter-spacing: 0.22em;
  padding: 13px 36px;
  cursor: pointer;
  border-radius: 4px;
  transition: all var(--dur-fast) var(--ease-out);
}

.enter:hover {
  background: color-mix(in srgb, var(--cyan) 16%, transparent);
  box-shadow: var(--glow-cyan);
}

.enter-arrow {
  transition: transform var(--dur-fast) var(--ease-out);
}

.enter:hover .enter-arrow {
  transform: translateX(5px);
}

/* ---------- 环绕公式 ---------- */
.formulas {
  position: absolute;
  inset: 0;
  z-index: 1;
  pointer-events: none;
}

.f-slot {
  position: absolute;
}

.f-pos-tl {
  top: 15%;
  left: 5%;
}

.f-pos-tr {
  top: 16%;
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
  bottom: 17%;
  left: 6%;
}

.f-pos-br {
  bottom: 17%;
  right: 6%;
}

.f-size-sm {
  font-size: 15px;
}

.f-size-md {
  font-size: 19px;
}

.f-size-lg {
  font-size: 23px;
}

@media (max-width: 900px) {
  .formulas {
    display: none;
  }

  .hud {
    display: none;
  }
}
</style>
