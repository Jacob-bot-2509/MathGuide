<script setup lang="ts">
/**
 * 搜索范围面板:研究型提问前勾选要检索的平台(数据源范围)。
 * 全选 = 全平台;取消的平台本轮一个请求都不发。
 */
import { computed } from 'vue'
import { t } from '@/utils/i18n'
import { settingsState } from '@/stores/settings'
import {
  ALL_SOURCE_KEYS,
  SOURCE_OPTIONS,
  isAllSelected,
  onlySource,
  selectAllSources,
  selectedSources,
  toggleSource,
} from '@/stores/researchScope'

const emit = defineEmits<{ close: [] }>()

const en = computed(() => settingsState.language === 'en')
const allOn = computed(() => isAllSelected())
const count = computed(() => selectedSources.value.length)

function label(s: (typeof SOURCE_OPTIONS)[number]): string {
  return en.value ? s.labelEn : s.label
}
function hint(s: (typeof SOURCE_OPTIONS)[number]): string {
  return en.value ? s.hintEn : s.hint
}

// left/width:「搜索范围」按钮的左缘与宽度(LearnView 量取);
// 面板水平居中于按钮,在其正上方展开
const props = defineProps<{ left?: number; width?: number }>()
</script>

<template>
  <!-- 外层定位:锚在按钮中心;动画 transform 由 Transition 加在外层,
       与内层的 translateX 居中互不干扰 -->
  <div
    class="scope-wrap"
    :style="{ left: props.left !== undefined && props.width !== undefined ? `${props.left + props.width / 2}px` : '50%' }"
  >
  <section class="scope-panel">
    <header class="panel-head">
      <span class="tech-label panel-title">{{ t('scope.title') }}</span>
      <span class="panel-total tech-label">{{ t('scope.picked', { n: count, total: ALL_SOURCE_KEYS.length }) }}</span>
      <button class="all-btn" :class="{ on: allOn }" @click="selectAllSources()">
        {{ t('scope.all') }}
      </button>
      <button class="close" aria-label="close" @click="emit('close')">✕</button>
    </header>
    <p class="hint">{{ t('scope.hint') }}</p>

    <ul class="src-list">
      <li v-for="s in SOURCE_OPTIONS" :key="s.key" class="src-item">
        <button class="src-row" :class="{ off: !selectedSources.includes(s.key) }" @click="toggleSource(s.key)">
          <span class="box" :class="{ on: selectedSources.includes(s.key) }">
            {{ selectedSources.includes(s.key) ? '✓' : '' }}
          </span>
          <span class="src-label">{{ label(s) }}</span>
          <span class="src-hint">{{ hint(s) }}</span>
        </button>
        <button
          v-if="selectedSources.length > 1 && selectedSources.includes(s.key)"
          class="only-btn"
          :title="t('scope.only')"
          @click="onlySource(s.key)"
        >
          {{ t('scope.onlyShort') }}
        </button>
      </li>
    </ul>
  </section>
  </div>
</template>

<style scoped>
/* 外层定位:锚在按钮中心正上方(按钮在底部指令栏);内层 translateX(-50%)
   水平居中,与 Transition 的位移动画互不覆盖 */
.scope-wrap {
  position: absolute;
  bottom: 100%;
  margin-bottom: 10px;
  z-index: 45;
  width: 0;
}

.scope-panel {
  transform: translateX(-50%);
  width: min(340px, calc(100vw - 32px));
  background: var(--bg-panel);
  border: 1px solid var(--line);
  border-radius: 12px;
  box-shadow: 0 12px 34px rgba(0, 0, 0, 0.45);
  padding: 12px 14px;
  max-height: 46vh;
  overflow-y: auto;
}

.panel-head {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 10px;
}

.panel-title {
  color: var(--cyan);
  font-size: 11px;
}

.panel-total {
  font-size: 11px;
}

.all-btn {
  background: transparent;
  border: 1px solid var(--line);
  color: var(--text-dim);
  border-radius: 4px;
  padding: 3px 10px;
  font-size: 11px;
  cursor: pointer;
  transition: all var(--dur-fast) var(--ease-out);
}

.all-btn:hover,
.all-btn.on {
  color: var(--cyan);
  border-color: var(--line-bright);
}

.close {
  margin-left: auto;
  background: transparent;
  border: 1px solid var(--line);
  color: var(--text-dim);
  width: 24px;
  height: 24px;
  border-radius: 4px;
  cursor: pointer;
  font-size: 12px;
  line-height: 1;
  transition: all var(--dur-fast) var(--ease-out);
}

.close:hover {
  color: var(--cyan);
  border-color: var(--line-bright);
}

.hint {
  color: var(--text-dim);
  font-size: 11px;
  margin: 0 0 6px;
}

.src-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.src-item {
  display: flex;
  align-items: center;
  gap: 6px;
}

.src-row {
  flex: 1;
  min-width: 0;
  display: flex;
  align-items: center;
  gap: 10px;
  background: transparent;
  border: none;
  padding: 7px 10px;
  border-radius: 6px;
  cursor: pointer;
  color: var(--text);
  font-size: 13px;
  text-align: left;
  transition: background var(--dur-fast);
}

.src-row:hover {
  background: rgba(96, 165, 250, 0.08);
}

.src-row.off .src-label {
  color: var(--text-dim);
}

.box {
  width: 15px;
  height: 15px;
  flex-shrink: 0;
  display: grid;
  place-items: center;
  border: 1px solid var(--line-bright);
  border-radius: 3px;
  font-size: 10px;
  color: transparent;
}

.box.on {
  color: #0b1220;
  background: var(--cyan);
  border-color: var(--cyan);
}

.src-label {
  flex-shrink: 0;
  width: 132px;
  color: var(--text-hi);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.src-hint {
  flex: 1;
  min-width: 0;
  color: var(--text-dim);
  font-size: 11.5px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.only-btn {
  flex-shrink: 0;
  background: transparent;
  border: 1px solid var(--line);
  color: var(--text-dim);
  border-radius: 4px;
  padding: 2px 8px;
  font-size: 11px;
  cursor: pointer;
  opacity: 0;
  transition: all var(--dur-fast) var(--ease-out);
}

.src-item:hover .only-btn {
  opacity: 1;
}

.only-btn:hover {
  color: var(--cyan);
  border-color: var(--line-bright);
}
</style>
