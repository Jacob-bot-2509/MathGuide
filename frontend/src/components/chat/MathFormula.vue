<script setup lang="ts">
/**
 * 可动画的 LaTeX 公式组件。
 *
 * 用 MathJax 把公式转成 SVG 后,对每个字形 path 做"描边书写"动画
 * (stroke-dashoffset 逐笔绘制),完成后回填填充色并进入漂浮状态。
 * trigger 变为 true 时开始绘制,delay 用于多公式错峰。
 */
import { nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import gsap from 'gsap'

const props = withDefaults(
  defineProps<{
    latex: string
    color?: string
    trigger: boolean
    delay?: number
    duration?: number
  }>(),
  { color: '#4dd6ff', delay: 0, duration: 1.4 },
)

const rootRef = ref<HTMLDivElement | null>(null)
const svgHtml = ref('')

// tex2svg 所在分块较大,动态加载,避免阻塞开场动画首屏
const texReady = import('@/utils/tex2svg').then((m) => m.texToSvg)

onMounted(async () => {
  const texToSvg = await texReady
  svgHtml.value = texToSvg(props.latex)
})

watch(
  () => props.trigger,
  async (on) => {
    if (!on) return
    await texReady
    await nextTick()
    const root = rootRef.value
    if (!root) return

    const paths = Array.from(root.querySelectorAll('path')).filter((p) => p.getTotalLength() > 0)
    if (paths.length === 0) {
      root.classList.add('is-drawn')
      return
    }

    const lengths = paths.map((p) => p.getTotalLength())
    gsap.set(paths, {
      fill: 'transparent',
      stroke: 'currentColor',
      strokeWidth: 1.4,
      strokeLinecap: 'round',
      strokeLinejoin: 'round',
    })
    gsap.fromTo(
      paths,
      {
        strokeDasharray: (i: number) => `${lengths[i]} ${lengths[i]}`,
        strokeDashoffset: (i: number) => lengths[i],
        opacity: 0,
      },
      {
        strokeDashoffset: 0,
        opacity: 1,
        duration: props.duration,
        delay: props.delay,
        stagger: { each: 0.012, from: 'start' },
        ease: 'power1.inOut',
        onComplete: () => {
          gsap.to(paths, { fill: 'currentColor', stroke: 'none', duration: 0.3 })
          root.classList.add('is-drawn')
        },
      },
    )
  },
)

onBeforeUnmount(() => {
  // 卸载(如 SKIP 跳过开场)时终止仍在进行的描边动画,避免在游离 DOM 上继续补间
  const root = rootRef.value
  if (root) gsap.killTweensOf(Array.from(root.querySelectorAll('path')))
})
</script>

<template>
  <div ref="rootRef" class="math-formula" :style="{ color: color }" v-html="svgHtml"></div>
</template>

<style scoped>
.math-formula {
  opacity: 0;
  color: var(--cyan);
  /* SVG 字形使用 currentColor,发光色跟随 color */
  filter: drop-shadow(0 0 7px color-mix(in srgb, currentColor 65%, transparent));
  pointer-events: none;
}

.math-formula :deep(svg) {
  width: auto;
  height: auto;
  max-width: 100%;
}

/* 绘制完成后进入漂浮状态 */
.math-formula.is-drawn {
  animation: mg-float 7s ease-in-out infinite;
}
</style>
