<script setup lang="ts">
/**
 * 结束对话前处理未入库论文:每篇可选导入 / 仅保留历史 / 忽略。
 * 只收集选择,实际导入由父组件执行。
 */
import { reactive } from 'vue'
import { t } from '@/utils/i18n'

export interface StagedChoicePaper {
  docId: string
  title: string
  pages: number
}

const props = defineProps<{ papers: StagedChoicePaper[] }>()
const emit = defineEmits<{
  confirm: [choices: Record<string, 'import' | 'temp' | 'ignore'>]
  cancel: []
}>()

const choices = reactive<Record<string, 'import' | 'temp' | 'ignore'>>(
  Object.fromEntries(props.papers.map((p) => [p.docId, 'import'])),
)
</script>

<template>
  <div class="pip-overlay" @click.self="emit('cancel')">
    <section class="pip">
      <header class="pip-head">
        <span class="pip-title">{{ t('learn.paperPromptTitle') }}</span>
      </header>
      <p class="pip-hint">{{ t('learn.paperPromptHint') }}</p>
      <ul class="pip-list">
        <li v-for="p in papers" :key="p.docId" class="pip-item">
          <div class="pip-info">
            <span class="pip-name" :title="p.title">{{ p.title }}</span>
            <span class="pip-pages">{{ t('learn.paperPages', { n: p.pages }) }}</span>
          </div>
          <select v-model="choices[p.docId]" class="pip-select">
            <option value="import">{{ t('learn.paperImport') }}</option>
            <option value="temp">{{ t('learn.paperKeepTemp') }}</option>
            <option value="ignore">{{ t('learn.paperIgnore') }}</option>
          </select>
        </li>
      </ul>
      <footer class="pip-actions">
        <button class="pip-btn" type="button" @click="emit('cancel')">
          {{ t('learn.paperCancel') }}
        </button>
        <button class="pip-btn primary" type="button" @click="emit('confirm', choices)">
          {{ t('learn.paperConfirm') }}
        </button>
      </footer>
    </section>
  </div>
</template>

<style scoped>
.pip-overlay {
  position: fixed;
  inset: 0;
  z-index: 1300;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(0, 0, 0, 0.48);
}

.pip {
  width: min(460px, calc(100vw - 32px));
  max-height: 70vh;
  display: flex;
  flex-direction: column;
  background: var(--bg-panel);
  border: 1px solid var(--line-bright);
  border-radius: 10px;
  box-shadow: 0 16px 48px rgba(0, 0, 0, 0.5);
  overflow: hidden;
}

.pip-head {
  padding: 11px 14px;
  border-bottom: 1px solid var(--line);
}

.pip-title {
  color: var(--cyan);
  font-family: var(--font-tech);
  font-size: 11.5px;
  letter-spacing: 0.06em;
}

.pip-hint {
  margin: 9px 14px 4px;
  color: var(--text-dim);
  font-size: 11.5px;
  line-height: 1.55;
}

.pip-list {
  list-style: none;
  margin: 0;
  padding: 6px 14px;
  overflow-y: auto;
}

.pip-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 0;
  border-bottom: 1px solid var(--line);
}

.pip-item:last-child {
  border-bottom: none;
}

.pip-info {
  min-width: 0;
  flex: 1;
}

.pip-name {
  display: block;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--text-hi);
  font-size: 12.5px;
}

.pip-pages {
  color: var(--text-dim);
  font-size: 10.5px;
}

.pip-select {
  flex: none;
  background: var(--bg-card);
  border: 1px solid var(--line);
  border-radius: 5px;
  color: var(--text);
  font-size: 11.5px;
  padding: 4px 6px;
}

.pip-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  padding: 10px 14px;
  border-top: 1px solid var(--line);
}

.pip-btn {
  background: transparent;
  border: 1px solid var(--line);
  color: var(--text-dim);
  border-radius: 6px;
  font-size: 11.5px;
  padding: 5px 12px;
  cursor: pointer;
}

.pip-btn.primary {
  color: var(--cyan);
  border-color: var(--line-bright);
  background: color-mix(in srgb, var(--cyan) 10%, transparent);
}
</style>
