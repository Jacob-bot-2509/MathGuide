<script setup lang="ts">
/**
 * 问题记录(归纳本)面板:收录过的问答按词条滚动陈列。
 * 点击词条跳回该问答所在的原对话上下文(不往对话框里刷记录列表)。
 * 样式与 CategoryPanel 同族:panel-head / 列表 / ✕ 关闭。
 */
import type { NotebookEntry } from '@/stores/notebook'
import { t } from '@/utils/i18n'

defineProps<{ entries: NotebookEntry[] }>()
const emit = defineEmits<{ close: []; pick: [id: number] }>()

function fmtDate(ts: number): string {
  const d = new Date(ts)
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
}
</script>

<template>
  <section class="nb-panel">
    <header class="panel-head">
      <span class="tech-label panel-title">📓 {{ t('learn.nbPanelTitle') }}</span>
      <span class="panel-total tech-label">{{ t('learn.nbPanelTotal', { n: entries.length }) }}</span>
      <button class="close" aria-label="close" @click="emit('close')">✕</button>
    </header>
    <p class="hint">{{ t('learn.nbPanelHint') }}</p>

    <p v-if="!entries.length" class="empty">{{ t('learn.nbEmpty') }}</p>
    <ul v-else class="nb-list">
      <li v-for="(e, i) in entries" :key="e.id" class="nb-item">
        <button class="nb-row" :title="t('learn.nbJump')" @click="emit('pick', e.id)">
          <span class="nb-idx tech-label">{{ String(i + 1).padStart(2, '0') }}</span>
          <span class="nb-q">{{ e.question.slice(0, 60) }}{{ e.question.length > 60 ? '…' : '' }}</span>
          <span class="nb-date">{{ fmtDate(e.createdAt) }}</span>
          <span class="chev">›</span>
        </button>
      </li>
    </ul>
  </section>
</template>

<style scoped>
.nb-panel {
  display: flex;
  flex-direction: column;
  max-height: 46vh;
  margin: 0 18px 12px;
  background: var(--bg-panel);
  border: 1px solid var(--line);
  border-radius: 12px;
  overflow: hidden;
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

.empty {
  padding: 26px 16px;
  text-align: center;
  color: var(--text-dim);
  font-size: 13px;
}

.nb-list {
  list-style: none;
  margin: 0;
  padding: 8px;
  overflow-y: auto;
  flex: 1;
}

.nb-item {
  margin-bottom: 4px;
}

.nb-row {
  display: flex;
  align-items: center;
  gap: 10px;
  width: 100%;
  text-align: left;
  background: transparent;
  border: 1px solid transparent;
  border-radius: 8px;
  padding: 9px 12px;
  cursor: pointer;
  transition: all var(--dur-fast) var(--ease-out);
}

.nb-row:hover {
  background: rgba(96, 165, 250, 0.08);
  border-color: var(--line);
}

.nb-idx {
  font-size: 11px;
  color: var(--text-dim);
  flex-shrink: 0;
}

.nb-q {
  flex: 1;
  min-width: 0;
  color: var(--text-hi);
  font-size: 13px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.nb-date {
  flex-shrink: 0;
  font-size: 10.5px;
  color: var(--text-dim);
}

.chev {
  flex-shrink: 0;
  color: var(--text-dim);
  font-size: 15px;
}
</style>
