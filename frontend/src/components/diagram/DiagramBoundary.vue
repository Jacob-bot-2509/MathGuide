<script setup lang="ts">
/** 单张图解的崩溃边界:渲染失败只丢这一张图,不影响消息和会话。 */
import { onErrorCaptured, ref } from 'vue'
import { t } from '@/utils/i18n'

defineProps<{ title?: string; notes?: string[] }>()
const failed = ref(false)

onErrorCaptured(() => {
  failed.value = true
  return false
})
</script>

<template>
  <div v-if="failed" class="diagram-boundary-fallback">
    <p>{{ t('diagram.renderFail') }}</p>
    <p v-if="title" class="diagram-fallback-title">{{ title }}</p>
    <ul v-if="notes && notes.length">
      <li v-for="(note, index) in notes" :key="index">{{ note }}</li>
    </ul>
  </div>
  <slot v-else />
</template>

<style scoped>
.diagram-boundary-fallback {
  margin: 8px 0 12px;
  padding: 10px 12px;
  border: 1px dashed var(--line);
  border-radius: 8px;
  color: var(--text-dim);
  font-size: 11px;
}

.diagram-boundary-fallback p {
  margin: 0 0 4px;
}

.diagram-fallback-title {
  color: var(--text);
}

.diagram-boundary-fallback ul {
  margin: 0;
  padding-left: 16px;
}
</style>
