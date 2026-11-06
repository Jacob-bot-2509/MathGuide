<script setup lang="ts">
/** 图解分发:2D 用 SVG;3D 懒加载 Three.js 静态场景,进入视口才挂载。 */
import { computed, defineAsyncComponent, h, onBeforeUnmount, onMounted, ref } from 'vue'
import type { DiagramSpec } from '@/utils/diagramSpec'
import { t } from '@/utils/i18n'
import DiagramSvg from '@/components/diagram/DiagramSvg.vue'

const props = withDefaults(defineProps<{ spec: DiagramSpec; focused?: boolean }>(), {
  focused: false,
})
const is3d = computed(() => ['geometry3d', 'surface3d'].includes(props.spec.type))
const isGeo2d = computed(() => props.spec.type === 'geogebra2d')
const isGeo3d = computed(() => props.spec.type === 'geogebra3d')
const isGeo = computed(() => isGeo2d.value || isGeo3d.value)
const lazy = computed(() => is3d.value || isGeo.value)
const visible = ref(!lazy.value)
const host = ref<HTMLElement | null>(null)
let observer: IntersectionObserver | null = null

const GeoGebraKernelBlock = defineAsyncComponent({
  loader: () => import('@/components/diagram/GeoGebraKernelBlock.vue'),
  delay: 200,
  timeout: 30000,
  loadingComponent: {
    render: () => h('div', { class: 'diagram-loading' }),
  },
  errorComponent: {
    render: () => h('div', { class: 'diagram-fallback' }, t('diagram.renderFail')),
  },
})

const GeoGebra3DKernelBlock = defineAsyncComponent({
  loader: () => import('@/components/diagram/GeoGebra3DKernelBlock.vue'),
  delay: 200,
  timeout: 30000,
  loadingComponent: {
    render: () => h('div', { class: 'diagram-loading' }),
  },
  errorComponent: {
    render: () => h('div', { class: 'diagram-fallback' }, t('diagram.renderFail')),
  },
})

const Diagram3D = defineAsyncComponent({
  loader: async () => {
    try {
      return await import('@/components/diagram/Diagram3D.vue')
    } catch {
      // 大 chunk 偶发网络失败:短暂等待后重试一次,不让整张图直接变错误。
      await new Promise((resolve) => setTimeout(resolve, 400))
      return import('@/components/diagram/Diagram3D.vue')
    }
  },
  delay: 200,
  timeout: 30000,
  loadingComponent: {
    // 图片没出来就不显示占位文字,避免用符号/加载文案干扰阅读。
    render: () => h('div', { class: 'diagram-loading' }),
  },
  errorComponent: {
    render: () => h('div', { class: 'diagram-fallback' }, t('diagram.renderFail')),
  },
})

onMounted(() => {
  if (!lazy.value) return
  if (typeof IntersectionObserver === 'undefined' || !host.value) {
    visible.value = true
    return
  }
  observer = new IntersectionObserver((entries) => {
    if (!entries.some((entry) => entry.isIntersecting)) return
    // 首次进入视口后保持挂载:滚出视口不能把已生成的图变回“加载中”。
    visible.value = true
    observer?.disconnect()
    observer = null
  }, { rootMargin: '240px' })
  observer.observe(host.value)
})

onBeforeUnmount(() => {
  observer?.disconnect()
  observer = null
})
</script>

<template>
  <figure ref="host" class="diagram-block" :class="{ 'diagram-block--focused': focused }">
    <figcaption v-if="spec.title" class="diagram-title">{{ spec.title }}</figcaption>
    <GeoGebraKernelBlock v-if="isGeo2d && visible" :spec="spec" :focused="focused" />
    <div v-else-if="isGeo2d" class="diagram-loading" />
    <GeoGebra3DKernelBlock v-else-if="isGeo3d && visible" :spec="spec" :focused="focused" />
    <div v-else-if="isGeo3d" class="diagram-loading" />
    <Diagram3D v-else-if="is3d && visible" :spec="spec" :focused="focused" />
    <div v-else-if="is3d" class="diagram-loading" />
    <DiagramSvg v-else :spec="spec" />
  </figure>
</template>

<style scoped>
.diagram-block {
  max-width: 560px;
  margin: 12px auto 16px;
  padding: 8px;
  background: #05070a;
  border: 1px solid rgba(96, 165, 250, 0.18);
  border-radius: 8px;
  --bg-void: #05070a;
  --bg-panel: rgba(13, 18, 30, 0.92);
  --bg-card: #05070a;
  --text-hi: #e8f2ff;
  --text: #c2d2e4;
  --text-dim: #8b9bb0;
  --line: rgba(96, 165, 250, 0.18);
  --line-bright: rgba(96, 165, 250, 0.45);
  --cyan: #4dd6ff;
}

.diagram-block--focused {
  max-width: none;
  height: 100%;
  margin: 0;
  padding: 0;
  border: 0;
  border-radius: 0;
  display: flex;
  flex-direction: column;
  background: transparent;
}

.diagram-block--focused :deep(.diagram-svg-wrap) {
  flex: 1;
  min-height: 0;
  background: #05070a;
}

.diagram-block--focused :deep(.diagram-svg) {
  height: 100%;
  max-height: none;
  min-height: 0;
}

.diagram-block--focused :deep(.diagram-3d-wrap) {
  flex: 1;
  min-height: 0;
}

.diagram-block--focused .diagram-loading,
.diagram-block--focused .diagram-fallback {
  max-width: none;
  min-height: 0;
  flex: 1;
  margin: 0;
}

.diagram-title {
  margin-bottom: 6px;
  color: var(--text);
  font-size: 12px;
  font-weight: 600;
  line-height: 1.4;
}

.diagram-loading,
.diagram-fallback {
  width: 100%;
  aspect-ratio: 16 / 10;
  min-height: 220px;
  max-width: 560px;
  margin: 0 auto;
  display: flex;
  align-items: center;
  justify-content: center;
  border: 1px dashed var(--line);
  border-radius: 8px;
  color: var(--text-dim);
  font-size: 12px;
}

@media (max-width: 680px) {
  .diagram-block {
    max-width: 100%;
  }

  .diagram-loading,
  .diagram-fallback {
    min-height: 180px;
  }
}
</style>
