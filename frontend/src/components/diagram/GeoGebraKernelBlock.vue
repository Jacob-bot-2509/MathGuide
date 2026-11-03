<script setup lang="ts">
/** GeoGebra 2D 隐藏内核:命令只用于计算,画面交给 DiagramSvg。 */
import { onBeforeUnmount, onMounted, ref } from 'vue'
import type { DiagramSpec } from '@/utils/diagramSpec'
import { parseDiagramSpec } from '@/utils/diagramSpec'
import { t } from '@/utils/i18n'
import { convertGeoGebraCommands } from '@/services/geogebraKernel'
import DiagramSvg from '@/components/diagram/DiagramSvg.vue'

const props = defineProps<{ spec: DiagramSpec }>()
const converted = ref<DiagramSpec | null>(null)
const error = ref('')
let disposed = false

onMounted(async () => {
  try {
    const result = await convertGeoGebraCommands(
      props.spec.commands || [], props.spec.title,
    )
    if (disposed) return
    const sanitized = result ? parseDiagramSpec(result) : null
    if (!sanitized) {
      error.value = t('diagram.renderFail')
      return
    }
    converted.value = sanitized
  } catch {
    if (!disposed) error.value = t('diagram.renderFail')
  }
})

onBeforeUnmount(() => {
  disposed = true
})
</script>

<template>
  <DiagramSvg v-if="converted" :spec="converted" />
  <div v-else-if="error" class="ggb-kernel-fallback">{{ error }}</div>
  <div v-else class="ggb-kernel-loading" />
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

@media (max-width: 680px) {
  .ggb-kernel-loading,
  .ggb-kernel-fallback {
    min-height: 180px;
  }
}
</style>
