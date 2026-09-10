<script setup lang="ts">
/**
 * 设置类页面的统一外壳:返回按钮 + 标题 + 内容容器。
 *
 * 五个设置页原先各自复制了一份根容器 / 头部结构 / `.head .back .title .body` 样式,
 * 五份之间还悄悄长歪了(内容宽度 560 与 620 混用、上边距 22 与 26 混用,
 * 同一层级页面看起来不一样);改一处要动五处。收敛到这里后,
 * 页面只管自己的内容,外壳尺寸由 width 统一控制。
 */
import { useRouter } from 'vue-router'
import { t } from '@/utils/i18n'

withDefaults(defineProps<{
  /** 页面标题(已翻译文案,由调用方 t() 后传入) */
  title: string
  /** 内容区最大宽度(默认 560;列表类页面可放宽) */
  width?: number
}>(), { width: 560 })

const router = useRouter()
</script>

<template>
  <div class="settings-page">
    <header class="head">
      <button class="back" @click="router.back()">{{ t('common.back') }}</button>
      <span class="title">{{ title }}</span>
      <!-- 页眉右侧的补充说明(如设置首页的 MG SYSTEM 标记) -->
      <slot name="extra" />
    </header>

    <main class="body" :style="{ maxWidth: `${width}px` }">
      <slot />
    </main>
  </div>
</template>

<style scoped>
.settings-page {
  min-height: 100vh;
}

.head {
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 16px 26px;
  border-bottom: 1px solid var(--line);
  background: var(--bg-panel);
}

.back {
  background: transparent;
  border: 1px solid var(--line);
  color: var(--text);
  padding: 7px 16px;
  cursor: pointer;
  border-radius: 4px;
  font-size: 13px;
  transition: all var(--dur-fast) var(--ease-out);
}

.back:hover {
  color: var(--cyan);
  border-color: var(--line-bright);
  box-shadow: var(--glow-cyan);
}

.title {
  color: var(--text-hi);
  font-size: 16px;
  letter-spacing: 0.1em;
}

.body {
  margin: 0 auto;
  padding: 26px 24px 60px;
}

/* 分组小标题由外壳统一供给(走插槽的内容只能用 :slotted 命中)。
   先前各页自备一份,值还不一致(上边距 22/26、下边距 8/10,只有一页带颜色),
   同一层级的页面因此看起来不一样 */
.settings-page :slotted(.section) {
  margin: 24px 0 10px;
  font-size: 11px;
  color: var(--text-dim);
}
</style>
