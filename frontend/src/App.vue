<script setup lang="ts">
import { RouterView } from 'vue-router'
import { toast } from '@/utils/toast'
</script>

<template>
  <RouterView v-slot="{ Component }">
    <Transition name="page" mode="out-in">
      <component :is="Component" />
    </Transition>
  </RouterView>

  <!-- 全局轻提示 -->
  <Teleport to="body">
    <Transition name="toast">
      <div v-if="toast.msg" class="mg-toast">{{ toast.msg }}</div>
    </Transition>
  </Teleport>
</template>

<style scoped>
/* 页面过场:淡出 + 失焦虚化,暗场过渡 */
.page-enter-active,
.page-leave-active {
  transition:
    opacity var(--dur-med) ease,
    filter var(--dur-med) ease;
}

.page-enter-from {
  opacity: 0;
  filter: blur(10px) brightness(1.8);
}

.page-leave-to {
  opacity: 0;
  filter: blur(10px);
}
</style>
