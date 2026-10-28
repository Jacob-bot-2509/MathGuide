<script setup lang="ts">
/**
 * 科学研究:与学习辅助界面一致、数据完全独立的聊天工作区。
 * 后端链路只在本区启用研究检索(跨文献库深度搜索、搜索范围面板);
 * 会话、归纳本、回收站记录均按 research 命名空间单独存放。
 */
import ChatWorkspace from '@/components/chat/ChatWorkspace.vue'
</script>

<template>
  <ChatWorkspace workspace="research" />
</template>
