<script setup lang="ts">
/**
 * 公式查询手册面板:按知识板块陈列词条,点击板块即发一条
 * 「该板块常用公式」的提问走知识检索链路(与指令原语义一致,
 * 只是从"发默认问题"变成"面板选板块")。
 * 定位与 NotebookPanel 同模式:锚在「公式查询手册」按钮中心正上方。
 */
import { CATEGORIES } from '@/utils/classifier'
import { catName, t } from '@/utils/i18n'

const props = defineProps<{ left?: number; width?: number }>()
const emit = defineEmits<{ close: []; pick: [key: string] }>()
</script>

<template>
  <!-- 外层定位:锚在按钮中心;动画 transform 由 Transition 加在外层 -->
  <div
    class="fml-wrap"
    :style="{ left: props.left !== undefined && props.width !== undefined ? `${props.left + props.width / 2}px` : '50%' }"
  >
    <section class="fml-panel">
      <header class="panel-head">
        <span class="tech-label panel-title">∫ {{ t('learn.formulaTitle') }}</span>
        <span class="panel-total tech-label">{{ t('learn.formulaTotal', { n: CATEGORIES.length }) }}</span>
        <button class="close" aria-label="close" @click="emit('close')">✕</button>
      </header>
      <p class="hint">{{ t('learn.formulaHint') }}</p>

      <ul class="fml-list">
        <li v-for="c in CATEGORIES" :key="c.key" class="fml-item">
          <button class="fml-row" :title="t('learn.formulaJump')" @click="emit('pick', c.key)">
            <span class="fml-dot" :style="{ background: c.color }"></span>
            <span class="fml-name">{{ catName(c.key) }}</span>
            <span class="chev">›</span>
          </button>
        </li>
      </ul>
    </section>
  </div>
</template>

<style scoped>
.fml-wrap {
  position: absolute;
  bottom: 100%;
  margin-bottom: 10px;
  z-index: 45;
  width: 0;
}

.fml-panel {
  transform: translateX(-50%);
  display: flex;
  flex-direction: column;
  width: fit-content;
  min-width: 240px;
  max-width: min(420px, calc(100vw - 32px));
  max-height: 46vh;
  background: var(--bg-panel);
  border: 1px solid var(--line);
  border-radius: 12px;
  overflow: hidden;
  box-shadow: 0 12px 34px rgba(0, 0, 0, 0.45);
}

.panel-head {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 12px 16px;
  border-bottom: 1px solid var(--line);
}

.panel-title {
  font-size: 12px;
  letter-spacing: 0.08em;
  color: var(--cyan);
}

.panel-total {
  margin-left: auto;
  font-size: 11px;
  color: var(--text-dim);
}

.close {
  background: transparent;
  border: none;
  color: var(--text-dim);
  font-size: 14px;
  cursor: pointer;
  padding: 2px 6px;
  border-radius: 4px;
  transition: all var(--dur-fast) var(--ease-out);
}

.close:hover {
  color: var(--cyan);
  box-shadow: var(--glow-cyan);
}

.hint {
  margin: 0;
  padding: 8px 16px 0;
  font-size: 11px;
  color: var(--text-dim);
}

.fml-list {
  list-style: none;
  margin: 0;
  padding: 8px;
  overflow-y: auto;
  flex: 1;
}

.fml-item {
  margin-bottom: 2px;
}

.fml-row {
  display: flex;
  align-items: center;
  gap: 10px;
  width: 100%;
  text-align: left;
  background: transparent;
  border: 1px solid transparent;
  border-radius: 8px;
  padding: 8px 12px;
  cursor: pointer;
  transition: all var(--dur-fast) var(--ease-out);
}

.fml-row:hover {
  background: rgba(96, 165, 250, 0.08);
  border-color: var(--line);
}

.fml-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  flex-shrink: 0;
}

.fml-name {
  flex: 1;
  min-width: 0;
  color: var(--text-hi);
  font-size: 13px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.chev {
  flex-shrink: 0;
  color: var(--text-dim);
  font-size: 15px;
}
</style>
