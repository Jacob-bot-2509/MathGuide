<script setup lang="ts">
/**
 * 问题记录(归纳本)面板:收录过的问答按词条滚动陈列。
 * 点击词条跳回该问答所在的原对话上下文(不往对话框里刷记录列表)。
 * 面板水平居中于「问题记录」按钮,在按钮正上方展开。
 * 样式与 CategoryPanel 同族:panel-head / 列表 / ✕ 关闭。
 */
import type { NotebookEntry } from '@/stores/notebook'
import { t } from '@/utils/i18n'

// left/width:「问题记录」按钮的左缘与宽度(LearnView 量取);
// 按钮中心 = left + width/2,面板以 translateX(-50%) 居中于该点
const props = defineProps<{ entries: NotebookEntry[]; left?: number; width?: number }>()
const emit = defineEmits<{ close: []; pick: [id: number] }>()

/** 词条下方的小日期:只到日,不精确到时间 */
function fmtDate(ts: number): string {
  const d = new Date(ts)
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
}
</script>

<template>
  <!-- 外层定位:anchor 在按钮中心;动画 transform 由 Transition 加在外层,
       与内层的 translateX 居中互不干扰 -->
  <div
    class="nb-wrap"
    :style="{ left: props.left !== undefined && props.width !== undefined ? `${props.left + props.width / 2}px` : '50%' }"
  >
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
            <span class="nb-main">
              <span class="nb-idx tech-label">{{ String(i + 1).padStart(2, '0') }}</span>
              <span class="nb-q">{{ e.question }}</span>
              <span class="chev">›</span>
            </span>
            <span class="nb-date">{{ fmtDate(e.createdAt) }}</span>
          </button>
        </li>
      </ul>
    </section>
  </div>
</template>

<style scoped>
/* 定位:挂在指令栏上方(父容器 .input-bar position:relative),
   由 LearnView 的 <Transition name="nb-rise"> 做从下向上展开 / 从上向下收起。
   z-index 高于 LearnView 的全屏遮罩(.nb-overlay z 40):遮罩压暗其余界面,
   面板浮在遮罩上,呈现「按钮与面板不在一个图层」的效果 */
/* 外层定位:锚在按钮中心正上方;Transition 的位移动画作用于这一层,
   内层 .nb-panel 的 translateX(-50%) 负责水平居中,两者互不覆盖 */
.nb-wrap {
  position: absolute;
  bottom: 100%;
  margin-bottom: 10px;
  z-index: 45;
  width: 0;
}

.nb-panel {
  transform: translateX(-50%);
  display: flex;
  flex-direction: column;
  /* 宽度自适应词条长度:随最长词条伸缩,上下限兜底 */
  width: fit-content;
  min-width: 260px;
  max-width: min(560px, calc(100vw - 32px));
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
  flex-direction: column;
  align-items: stretch;
  gap: 3px;
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

.nb-main {
  display: flex;
  align-items: center;
  gap: 10px;
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
  font-size: 10px;
  color: var(--text-dim);
  padding-left: 26px; /* 与标题起点对齐(序号宽度 + 间距) */
}

.chev {
  flex-shrink: 0;
  color: var(--text-dim);
  font-size: 15px;
}
</style>
