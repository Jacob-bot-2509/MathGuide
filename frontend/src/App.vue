<script setup lang="ts">
import { RouterView } from 'vue-router'
import { toast } from '@/utils/toast'
import CommandPalette from '@/components/common/CommandPalette.vue'
</script>

<template>
  <RouterView v-slot="{ Component }">
    <Transition name="page" mode="out-in">
      <component :is="Component" />
    </Transition>
  </RouterView>

  <CommandPalette />

  <!-- 全局轻提示 -->
  <Teleport to="body">
    <Transition name="toast">
      <div v-if="toast.msg" class="mg-toast">{{ toast.msg }}</div>
    </Transition>
  </Teleport>
</template>

<style scoped>
/* 页面过场：干脆克制的微位移淡入，避免炫光失焦干扰科研专注度 */
.page-enter-active,
.page-leave-active {
  transition:
    opacity var(--dur-fast) var(--ease-out),
    transform var(--dur-fast) var(--ease-out);
}

.page-enter-from {
  opacity: 0;
  transform: translateY(4px);
}

.page-leave-to {
  opacity: 0;
  transform: translateY(-2px);
}
</style>
