<script setup lang="ts">
/** 图解分发:2D 用 SVG;3D 在 Task 9 接入 Three.js,当前先给明确占位。 */
import type { DiagramSpec } from '@/utils/diagramSpec'
import DiagramSvg from '@/components/diagram/DiagramSvg.vue'

defineProps<{ spec: DiagramSpec }>()
</script>

<template>
  <figure class="diagram-block">
    <figcaption v-if="spec.title" class="diagram-title">{{ spec.title }}</figcaption>
    <DiagramSvg v-if="!['geometry3d', 'surface3d'].includes(spec.type)" :spec="spec" />
    <div v-else class="diagram-3d-placeholder">3D 图解将在后续接入</div>
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

.diagram-3d-placeholder {
  border: 1px dashed var(--line-bright);
  border-radius: 8px;
  padding: 18px;
  color: var(--text-dim);
  font-size: 11px;
  text-align: center;
}
</style>
