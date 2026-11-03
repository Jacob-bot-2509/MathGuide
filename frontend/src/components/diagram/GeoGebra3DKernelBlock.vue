<script setup lang="ts">
/** GeoGebra 3D 隐藏内核:命令只用于精确构造,画面交给 Diagram3D。 */
import { onBeforeUnmount, onMounted, ref } from 'vue'
import type { DiagramSpec } from '@/utils/diagramSpec'
import { parseDiagramSpec } from '@/utils/diagramSpec'
import { t } from '@/utils/i18n'
import { convertGeoGebra3DCommands } from '@/services/geogebra3dKernel'
import { planDiagram } from '@/services/diagramService'
import Diagram3D from '@/components/diagram/Diagram3D.vue'

const props = defineProps<{ spec: DiagramSpec }>()
const converted = ref<DiagramSpec | null>(null)
const error = ref('')
let disposed = false

onMounted(async () => {
  let next: DiagramSpec | null = null
  try {
    const result = await convertGeoGebra3DCommands(
      props.spec.commands || [], props.spec.title,
    )
    if (disposed) return
    next = result ? parseDiagramSpec(result) : null
  } catch {
    next = null
  }
  if (!next && !disposed) {
    // 3D XML 转换失败时回退旧规划器,仍然用自己的 Three.js。
    try {
      const title = (props.spec.title || '').trim()
      next = await planDiagram({
        question: title || '根据当前讲解画一张三维图',
        answer: title || (props.spec.commands || []).join('；'),
      })
    } catch {
      next = null
    }
  }
  if (disposed) return
  if (!next) {
    error.value = t('diagram.renderFail')
    return
  }
  converted.value = next
})

onBeforeUnmount(() => { disposed = true })
</script>

<template>
  <Diagram3D v-if="converted" :spec="converted" />
  <div v-else-if="error" class="ggb3d-fallback">{{ error }}</div>
  <div v-else class="ggb3d-loading" />
</template>

<style scoped>
.ggb3d-loading,
.ggb3d-fallback {
  width: 100%;
  max-width: 480px;
  min-height: 340px;
  margin: 0 auto;
  display: flex;
  align-items: center;
  justify-content: center;
  border: 1px dashed var(--line);
  border-radius: 8px;
  color: var(--text-dim);
  font-size: 12px;
}
</style>
