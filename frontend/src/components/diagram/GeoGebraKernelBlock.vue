<script setup lang="ts">
/** GeoGebra 2D 隐藏内核:命令只用于计算,画面交给 DiagramSvg。 */
import { onBeforeUnmount, onMounted, ref } from 'vue'
import type { DiagramSpec } from '@/utils/diagramSpec'
import { parseDiagramSpec } from '@/utils/diagramSpec'
import { t } from '@/utils/i18n'
import { convertGeoGebraCommands } from '@/services/geogebraKernel'
import { planDiagram } from '@/services/diagramService'
import DiagramSvg from '@/components/diagram/DiagramSvg.vue'

const props = withDefaults(defineProps<{ spec: DiagramSpec; focused?: boolean }>(), {
  focused: false,
})
const converted = ref<DiagramSpec | null>(null)
const error = ref('')
let disposed = false

onMounted(async () => {
  let convertedSpec: DiagramSpec | null = null
  try {
    const result = await convertGeoGebraCommands(
      props.spec.commands || [], props.spec.title,
    )
    if (disposed) return
    convertedSpec = result ? parseDiagramSpec(result) : null
  } catch {
    convertedSpec = null
  }
  if (!convertedSpec && !disposed) {
    // 内核不可用时回退旧规划器,仍然用我们的 SVG 渲染,不显示 GeoGebra 画布。
    try {
      const title = (props.spec.title || '').trim()
      const fallback = await planDiagram({
        question: title || '根据当前讲解画一张图',
        answer: title || (props.spec.commands || []).join('；'),
      })
      convertedSpec = fallback
    } catch {
      convertedSpec = null
    }
  }
  if (disposed) return
  if (!convertedSpec) {
    error.value = t('diagram.renderFail')
    return
  }
  converted.value = convertedSpec
})

onBeforeUnmount(() => {
  disposed = true
})
</script>

<template>
  <DiagramSvg v-if="converted" :spec="converted" />
  <div v-else-if="error" class="ggb-kernel-fallback" :class="{ 'ggb-kernel--focused': focused }">{{ error }}</div>
  <div v-else class="ggb-kernel-loading" :class="{ 'ggb-kernel--focused': focused }" />
</template>

<style scoped>
.ggb-kernel-loading,
.ggb-kernel-fallback {
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

.ggb-kernel--focused {
  max-width: none;
  height: 100%;
  min-height: 0;
  margin: 0;
  border: 0;
  border-radius: 0;
}

@media (max-width: 680px) {
  .ggb-kernel-loading,
  .ggb-kernel-fallback {
    min-height: 180px;
  }
}
</style>
