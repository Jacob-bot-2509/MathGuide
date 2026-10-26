<script setup lang="ts">
/**
 * 待办提醒层:只在 LearnView 挂载,因此天然满足
 * “开场动画结束 + 已登录 + 进入学习辅助”之后才提醒。
 *
 * 四路检查:挂载后、定时器、window focus、visibilitychange。
 * 页面隐藏时优先发浏览器系统通知;回到页面再弹面板。
 * 面板没有关闭按钮,只能点底部按钮结束。
 */
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import {
  ackAllExpired,
  ackDaily,
  dueDailyTasks,
  notificationKey,
  taskStatus,
  unackExpired,
} from '@/stores/todo'
import { formatDue, type ExpiredEntry, type TodoTask } from '@/utils/todoTime'
import { t } from '@/utils/i18n'

type Mode = 'daily' | 'expired'

const mode = ref<Mode | null>(null)
const dailyTasks = ref<TodoTask[]>([])
const expiredItems = ref<ExpiredEntry[]>([])
const buttonEl = ref<HTMLButtonElement | null>(null)
const nowTick = ref(Date.now())
let timer: number | null = null
let bootTimer: number | null = null

const title = computed(() => mode.value === 'daily'
  ? t('todo.modalDailyTitle')
  : t('todo.modalExpiredTitle'))
const hint = computed(() => mode.value === 'daily'
  ? t('todo.modalDailyHint')
  : t('todo.modalExpiredHint'))

function focusButton(): void {
  buttonEl.value?.focus()
}

function openDaily(tasks: TodoTask[]): void {
  if (mode.value) return
  dailyTasks.value = tasks
  expiredItems.value = []
  mode.value = 'daily'
  nextTick(focusButton)
}

function openExpired(items: ExpiredEntry[]): void {
  if (mode.value) return
  dailyTasks.value = []
  expiredItems.value = items
  mode.value = 'expired'
  nextTick(focusButton)
}

function notifyDaily(tasks: TodoTask[]): void {
  if (typeof Notification === 'undefined' || Notification.permission !== 'granted') return
  const key = notificationKey()
  try {
    if (localStorage.getItem(key)) return
    localStorage.setItem(key, '1')
  } catch {
    /* 隐私模式仍可弹面板 */
  }
  try {
    const body = `${t('todo.notifyBody', { n: tasks.length })} ${tasks[0]?.content ?? ''}`.trim()
    const notification = new Notification(t('todo.notifyTitle'), { body, tag: key })
    notification.onclick = () => {
      window.focus()
      notification.close()
      check()
    }
  } catch {
    /* 通知失败降级为页面内面板 */
  }
}

function check(): void {
  nowTick.value = Date.now()
  if (mode.value) return
  const due = dueDailyTasks()
  if (due.length) {
    if (typeof document !== 'undefined' && document.visibilityState === 'hidden') {
      notifyDaily(due)
      return
    }
    openDaily(due)
    return
  }
  const expired = unackExpired()
  if (expired.length) openExpired(expired)
}

function onDailyAck(): void {
  ackDaily()
  mode.value = null
  dailyTasks.value = []
  // 关闭当天面板后再看过期任务
  window.setTimeout(check, 300)
}

function onExpiredAck(): void {
  ackAllExpired()
  mode.value = null
  expiredItems.value = []
  window.setTimeout(check, 300)
}

function onVisibility(): void {
  if (document.visibilityState === 'visible') check()
}

onMounted(() => {
  // 等页面/问候流先渲染,避免提醒面板抢首屏
  bootTimer = window.setTimeout(check, 900)
  timer = window.setInterval(check, 15000)
  window.addEventListener('focus', check)
  document.addEventListener('visibilitychange', onVisibility)
})

onBeforeUnmount(() => {
  if (bootTimer) clearTimeout(bootTimer)
  if (timer) clearInterval(timer)
  window.removeEventListener('focus', check)
  document.removeEventListener('visibilitychange', onVisibility)
})
</script>

<template>
  <Teleport to="body">
    <div v-if="mode" class="todo-overlay">
      <section
        class="todo-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="todo-reminder-title"
        @keydown.tab.prevent="focusButton"
        @keydown.esc.prevent
      >
        <p class="tech-label todo-kicker">{{ t('todo.reminderTag') }}</p>
        <h2 id="todo-reminder-title">{{ title }}</h2>
        <p class="todo-hint">{{ hint }}</p>

        <ul v-if="mode === 'daily'" class="todo-reminder-list">
          <li v-for="task in dailyTasks" :key="task.id" class="todo-reminder-item">
            <span class="todo-reminder-time">{{ task.time }}</span>
            <span class="todo-reminder-content">{{ task.content }}</span>
            <span class="todo-reminder-state">{{
              taskStatus(task, new Date(nowTick)) === 'in_progress' ? t('todo.statusInProgress') : t('todo.statusPending')
            }}</span>
          </li>
        </ul>
        <ul v-else class="todo-reminder-list">
          <li v-for="entry in expiredItems" :key="`${entry.taskId}-${entry.date}`" class="todo-reminder-item">
            <span class="todo-reminder-time">{{ formatDue(entry.date, entry.time) }}</span>
            <span class="todo-reminder-content">{{ entry.content }}</span>
            <span class="todo-reminder-state todo-reminder-state--expired">{{ t('todo.statusExpired') }}</span>
          </li>
        </ul>

        <button ref="buttonEl" type="button" class="todo-ack" @click="mode === 'daily' ? onDailyAck() : onExpiredAck()">
          {{ mode === 'daily' ? t('todo.startNow') : t('todo.ackExpired') }}
        </button>
      </section>
    </div>
  </Teleport>
</template>

<style scoped>
.todo-overlay {
  position: fixed;
  inset: 0;
  z-index: 80;
  display: grid;
  place-items: center;
  padding: 20px;
  background: rgba(3, 6, 12, 0.72);
  backdrop-filter: blur(3px);
}

.todo-dialog {
  width: min(460px, calc(100vw - 32px));
  max-height: min(68vh, 560px);
  overflow-y: auto;
  box-sizing: border-box;
  padding: 22px 22px 18px;
  background: var(--bg-panel);
  border: 1px solid var(--line-bright);
  border-radius: 14px;
  box-shadow: 0 0 42px rgba(77, 214, 255, 0.22), 0 18px 48px rgba(0, 0, 0, 0.55);
  text-align: center;
}

.todo-kicker {
  color: var(--cyan);
  font-size: 10px;
  letter-spacing: 0.18em;
  margin: 0 0 7px;
}

.todo-dialog h2 {
  margin: 0;
  color: var(--text-hi);
  font-size: 19px;
  letter-spacing: 0.04em;
}

.todo-hint {
  margin: 7px 0 13px;
  color: var(--text-dim);
  font-size: 12px;
  line-height: 1.6;
}

.todo-reminder-list {
  list-style: none;
  margin: 0 0 16px;
  padding: 0;
  max-height: 34vh;
  overflow-y: auto;
  border-top: 1px solid var(--line);
}

.todo-reminder-item {
  display: flex;
  align-items: baseline;
  gap: 9px;
  padding: 9px 2px;
  border-bottom: 1px solid var(--line);
  text-align: left;
}

.todo-reminder-time {
  flex-shrink: 0;
  color: var(--cyan);
  font-family: var(--font-tech);
  font-size: 11.5px;
}

.todo-reminder-content {
  flex: 1;
  min-width: 0;
  color: var(--text-hi);
  font-size: 13px;
  overflow-wrap: break-word;
}

.todo-reminder-state {
  flex-shrink: 0;
  color: var(--text-dim);
  font-size: 10.5px;
}

.todo-reminder-state--expired {
  color: var(--danger);
}

.todo-ack {
  min-width: 210px;
  padding: 10px 24px;
  border: 1px solid var(--line-bright);
  border-radius: 8px;
  background: color-mix(in srgb, var(--cyan) 12%, transparent);
  color: var(--cyan);
  font-family: var(--font-ui);
  font-size: 13.5px;
  letter-spacing: 0.05em;
  cursor: pointer;
}

.todo-ack:hover {
  background: color-mix(in srgb, var(--cyan) 20%, transparent);
  box-shadow: var(--glow-cyan);
}
</style>
