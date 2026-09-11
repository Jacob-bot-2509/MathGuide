<script setup lang="ts">
/**
 * 问题归纳面板:按高等数学板块归纳所有会话中的用户问题。
 * 每行直接显示问题数量;展开后点击问题可跳转到当时所在的对话上下文。
 */
import { ref } from 'vue'
import { t } from '@/utils/i18n'

export interface PanelQuestion {
  id: number
  text: string
}

export interface CategoryItem {
  key: string
  label: string
  color: string
  count: number
  questions: PanelQuestion[]
}

const props = defineProps<{
  items: CategoryItem[]
  total: number
  /** 对齐按钮的位置(LearnView 量取,px) */
  left?: number
  top?: number
  width?: number
}>()
const emit = defineEmits<{ close: []; jump: [id: number]; delete: [id: number] }>()

const open = ref<string | null>(null)

function toggle(key: string) {
  open.value = open.value === key ? null : key
}
</script>

<template>
  <section
    class="cat-panel"
    :style="{
      left: props.left !== undefined ? `${props.left}px` : '16px',
      top: props.top !== undefined ? `${props.top}px` : '58px',
      width: props.width !== undefined ? `${props.width}px` : undefined,
    }"
  >
    <header class="panel-head">
      <span class="tech-label panel-title">{{ t('panel.title') }}</span>
      <span class="panel-total tech-label">{{ t('panel.total', { n: total }) }}</span>
      <button class="close" aria-label="close" @click="emit('close')">✕</button>
    </header>
    <p class="hint">{{ t('panel.hint') }}</p>

    <ul class="cat-list">
      <li v-for="it in items" :key="it.key" class="cat-item">
        <!-- 有问题:可展开 -->
        <button v-if="it.count > 0" class="cat-row" @click="toggle(it.key)">
          <span class="dot" :style="{ background: it.color }"></span>
          <span class="cat-label">{{ it.label }}</span>
          <span class="count">{{ it.count }}</span>
          <span class="chev" :class="{ open: open === it.key }">▾</span>
        </button>
        <!-- 尚无问题:置灰显示 0 -->
        <div v-else class="cat-row cat-row--empty">
          <span class="dot" :style="{ background: it.color, opacity: 0.3 }"></span>
          <span class="cat-label cat-label--dim">{{ it.label }}</span>
          <span class="count count--zero">0</span>
        </div>
        <Transition name="fold">
          <ul v-if="open === it.key" class="q-list">
            <li v-for="q in it.questions" :key="q.id" class="q-line">
              <button class="q-item" :title="t('panel.jump')" @click="emit('jump', q.id)">
                <span class="q-idx">▸</span>{{ q.text }}
              </button>
              <button class="q-del" :title="t('panel.del')" @click="emit('delete', q.id)">✕</button>
            </li>
          </ul>
        </Transition>
      </li>
    </ul>
  </section>
</template>

<style scoped>
/* 浮层形态:对齐「问题归纳」按钮,从按钮下方展开(left/top/width 由 LearnView
   量取按钮位置传入);z-index 高于全屏遮罩(40),呈两层效果 */
.cat-panel {
  position: absolute;
  left: 16px;
  top: 58px;
  width: min(320px, calc(100vw - 32px));
  z-index: 45;
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
  gap: 14px;
  margin-bottom: 10px;
}

.panel-title {
  color: var(--cyan);
  font-size: 11px;
}

.panel-total {
  font-size: 11px;
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

.cat-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.cat-row {
  display: flex;
  align-items: center;
  gap: 10px;
  width: 100%;
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

.cat-row:hover {
  background: rgba(96, 165, 250, 0.08);
}

.cat-row--empty {
  cursor: default;
}

.cat-row--empty:hover {
  background: transparent;
}

.cat-label--dim {
  color: var(--text-dim);
}

.count--zero {
  color: var(--text-dim);
}

.dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  flex-shrink: 0;
}

.cat-label {
  flex: 1;
  color: var(--text-hi);
}

/* 直接显示问题数字 */
.count {
  font-family: var(--font-tech);
  font-size: 15px;
  color: var(--cyan);
  text-align: right;
}

.chev {
  color: var(--text-dim);
  font-size: 10px;
  transition: transform var(--dur-fast) var(--ease-out);
}

.chev.open {
  transform: rotate(180deg);
}

.q-list {
  list-style: none;
  margin: 2px 0 8px 28px;
  padding: 0 10px;
  border-left: 1px solid var(--line);
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.q-line {
  display: flex;
  align-items: center;
  gap: 4px;
}

.q-item {
  flex: 1;
  min-width: 0;
  display: block;
  text-align: left;
  background: transparent;
  border: none;
  padding: 5px 8px;
  border-radius: 4px;
  color: var(--text-dim);
  font-size: 12.5px;
  line-height: 1.6;
  cursor: pointer;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  transition:
    color var(--dur-fast),
    background var(--dur-fast);
}

.q-item:hover {
  color: var(--cyan);
  background: rgba(77, 214, 255, 0.06);
}

.q-idx {
  font-family: var(--font-tech);
  margin-right: 6px;
  color: var(--text-dim);
}

.q-del {
  flex-shrink: 0;
  width: 20px;
  height: 20px;
  display: grid;
  place-items: center;
  background: transparent;
  border: none;
  border-radius: 4px;
  color: var(--text-dim);
  font-size: 10px;
  cursor: pointer;
  opacity: 0;
  transition: all var(--dur-fast) var(--ease-out);
}

.q-line:hover .q-del {
  opacity: 1;
}

.q-del:hover {
  color: var(--danger);
  background: color-mix(in srgb, var(--danger) 10%, transparent);
}

.fold-enter-active,
.fold-leave-active {
  transition:
    opacity var(--dur-med) var(--ease-out),
    transform var(--dur-med) var(--ease-out);
}

.fold-enter-from,
.fold-leave-to {
  opacity: 0;
  transform: translateY(-6px);
}
</style>
