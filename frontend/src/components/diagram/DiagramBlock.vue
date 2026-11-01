<script setup lang="ts">
/** 图解分发:2D 用 SVG;3D 懒加载 Three.js 静态场景。 */
import { defineAsyncComponent } from 'vue'
import type { DiagramSpec } from '@/utils/diagramSpec'
import DiagramSvg from '@/components/diagram/DiagramSvg.vue'

const Diagram3D = defineAsyncComponent(() => import('@/components/diagram/Diagram3D.vue'))
defineProps<{ spec: DiagramSpec }>()
</script>

<template>
  <figure class="diagram-block">
    <figcaption v-if="spec.title" class="diagram-title">{{ spec.title }}</figcaption>
    <Diagram3D
      v-if="['geometry3d', 'surface3d'].includes(spec.type)"
      :spec="spec"
    />
    <DiagramSvg v-else :spec="spec" />
  </figure>
</template>

<style scoped>
.diagram-block {
  margin: 8px 0 12px;
}

.diagram-title {
  margin-bottom: 5px;
  color: var(--cyan);
  font-family: var(--font-tech);
  font-size: 10px;
}
</style>
