<script setup lang="ts">
/** 图解分发:2D 用 SVG;3D 懒加载 Three.js 静态场景,进入视口才挂载。 */
import { computed, defineAsyncComponent, h, onBeforeUnmount, onMounted, ref } from 'vue'
import type { DiagramSpec } from '@/utils/diagramSpec'
import { t } from '@/utils/i18n'
import DiagramSvg from '@/components/diagram/DiagramSvg.vue'

const props = defineProps<{ spec: DiagramSpec }>()
const is3d = computed(() => ['geometry3d', 'surface3d'].includes(props.spec.type))
const visible = ref(!is3d.value)
const host = ref<HTMLElement | null>(null)
let observer: IntersectionObserver | null = null

const Diagram3D = defineAsyncComponent({
  loader: () => import('@/components/diagram/Diagram3D.vue'),
  delay: 200,
  timeout: 15000,
  loadingComponent: {
    // 图片没出来就不显示占位文字,避免用符号/加载文案干扰阅读。
    render: () => h('div', { class: 'diagram-loading' }),
  },
  errorComponent: {
    render: () => h('div', { class: 'diagram-fallback' }, t('diagram.renderFail')),
  },
})

onMounted(() => {
  if (!is3d.value) return
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
  <figure ref="host" class="diagram-block">
    <figcaption v-if="spec.title" class="diagram-title">{{ spec.title }}</figcaption>
    <Diagram3D v-if="is3d && visible" :spec="spec" />
    <div v-else-if="is3d" class="diagram-loading" />
    <DiagramSvg v-else :spec="spec" />
  </figure>
</template>

<style scoped>
.diagram-block {
  max-width: 560px;
  margin: 12px auto 16px;
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
