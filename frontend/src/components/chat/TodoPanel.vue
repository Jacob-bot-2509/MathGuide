<script setup lang="ts">
/**
 * 待办清单指令面板:新建/编辑任务、草稿/日程两个 Tab。
 * 新建时可直接「保存到日程」或「保存到草稿」;草稿永不触发提醒,
 * 点「设置好了」才进入日程。
 */
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import { showToast } from '@/utils/toast'
import { settingsState } from '@/stores/settings'
import {
  allExpired,
  deleteTask,
  dueText,
  markDone,
  moveAllToSchedule,
  moveToDraft,
  moveToSchedule,
  repeatLabel,
  saveTask,
  taskStatus,
  togglePause,
  todoState,
  validateDraft,
} from '@/stores/todo'
import {
  WEEKDAYS,
  dateKeyOf,
  formatDue,
  pad2,
  type InstanceStatus,
  type RepeatMode,
  type TodoTask,
} from '@/utils/todoTime'
import { t } from '@/utils/i18n'

const props = defineProps<{ left?: number; width?: number }>()
const emit = defineEmits<{ close: [] }>()

const en = computed(() => settingsState.language === 'en')
const tab = ref<'draft' | 'schedule'>('draft')
const content = ref('')
const date = ref('')
const time = ref('')
const repeat = ref<RepeatMode>('once')
const weekdays = ref<number[]>([])
const editingId = ref<string | null>(null)
const editingStatus = ref<'draft' | 'scheduled' | null>(null)
const formError = ref<string | null>(null)
const contentEl = ref<HTMLTextAreaElement | null>(null)
const nowTick = ref(Date.now())
let clock: number | null = null

const draftTasks = computed(() => todoState.data.tasks.filter((task) => task.status === 'draft'))
const scheduledTasks = computed(() => todoState.data.tasks.filter((task) => task.status === 'scheduled'))
const expiredItems = computed(() => {
  // nowTick 参与依赖:面板打开期间到点也能重新计算过期/状态
  void nowTick.value
  return allExpired().slice(0, 20)
})

function nextDefault(): { date: string; time: string } {
  const next = new Date(Date.now() + 60 * 60 * 1000)
  next.setSeconds(0, 0)
  return { date: dateKeyOf(next), time: `${pad2(next.getHours())}:${pad2(next.getMinutes())}` }
}

function resetForm(): void {
  const next = nextDefault()
  content.value = ''
  date.value = next.date
  time.value = next.time
  repeat.value = 'once'
  weekdays.value = []
  editingId.value = null
  editingStatus.value = null
  formError.value = null
}

function startEdit(task: TodoTask): void {
  editingId.value = task.id
  editingStatus.value = task.status
  content.value = task.content
  date.value = task.date
  time.value = task.time
  repeat.value = task.repeat
  weekdays.value = [...task.weekdays]
  formError.value = null
  tab.value = 'draft'
  nextTick(() => contentEl.value?.focus())
}

function saveCurrent(target: 'draft' | 'schedule' | 'keep' = 'draft'): void {
  const error = validateDraft({
    content: content.value,
    date: date.value,
    time: time.value,
    repeat: repeat.value,
    weekdays: weekdays.value,
  })
  if (error) {
    formError.value = error
    return
  }
  const task = saveTask({
    content: content.value,
    date: date.value,
    time: time.value,
    repeat: repeat.value,
    weekdays: weekdays.value,
  }, editingId.value)
  if (target === 'schedule') {
    ensureNotificationPermission()
    moveToSchedule(task.id)
    showToast(t('todo.savedSchedule'))
    tab.value = 'schedule'
  } else if (target === 'draft') {
    showToast(t('todo.savedDraft'))
    tab.value = 'draft'
  } else {
    showToast(t('todo.savedEdit'))
  }
  resetForm()
}

function ensureNotificationPermission(): void {
  if (typeof Notification === 'undefined') return
  if (Notification.permission === 'denied') {
    showToast(t('todo.notifyDenied'))
    return
  }
  if (Notification.permission === 'default') {
    Notification.requestPermission().then((permission) => {
      if (permission !== 'granted') showToast(t('todo.notifyDenied'))
    }).catch(() => { /* 浏览器拒绝请求时保持页面内提醒 */ })
  }
}

function confirmDraft(task: TodoTask): void {
  ensureNotificationPermission()
  moveToSchedule(task.id)
  showToast(t('todo.movedSchedule'))
  tab.value = 'schedule'
}

function moveAllDrafts(): void {
  if (!draftTasks.value.length) return
  ensureNotificationPermission()
  const count = moveAllToSchedule()
  showToast(t('todo.movedAll', { n: count }))
  tab.value = 'schedule'
}

function onDelete(task: TodoTask): void {
  if (!window.confirm(t('todo.deleteConfirm'))) return
  deleteTask(task.id)
}

function onStatus(task: TodoTask): void {
  if (taskStatus(task, new Date(nowTick.value)) !== 'in_progress') return
  markDone(task.id)
  showToast(t('todo.doneToast'))
}

function isInProgress(task: TodoTask): boolean {
  return taskStatus(task, new Date(nowTick.value)) === 'in_progress'
}

function statusText(task: TodoTask): string {
  const status: InstanceStatus = taskStatus(task, new Date(nowTick.value))
  return t({
    pending: 'todo.statusPending',
    in_progress: 'todo.statusInProgress',
    done: 'todo.statusDone',
    expired: 'todo.statusExpired',
    paused: 'todo.statusPaused',
    upcoming: 'todo.statusUpcoming',
  }[status])
}

function statusClass(task: TodoTask): string {
  const status: InstanceStatus = taskStatus(task, new Date(nowTick.value))
  return `todo-status todo-status--${status}`
}

onMounted(() => {
  resetForm()
  clock = window.setInterval(() => { nowTick.value = Date.now() }, 15000)
})

onBeforeUnmount(() => {
  if (clock) clearInterval(clock)
})
</script>

<template>
  <div
    class="todo-wrap"
    :style="{ left: props.left !== undefined && props.width !== undefined ? `${props.left + props.width / 2}px` : '50%' }"
  >
    <section class="todo-panel">
      <header class="panel-head">
        <span class="tech-label panel-title">☑ {{ t('todo.title') }}</span>
        <span class="panel-total tech-label">{{ draftTasks.length }} / {{ scheduledTasks.length }}</span>
        <button class="close" aria-label="close" @click="emit('close')">✕</button>
      </header>

      <div class="todo-tabs">
        <button class="todo-tab" :class="{ on: tab === 'draft' }" @click="tab = 'draft'">
          {{ t('todo.tabDraft') }} <span>{{ draftTasks.length }}</span>
        </button>
        <button class="todo-tab" :class="{ on: tab === 'schedule' }" @click="tab = 'schedule'">
          {{ t('todo.tabSchedule') }} <span>{{ scheduledTasks.length }}</span>
        </button>
      </div>

      <div class="todo-body">
        <div class="todo-form">
          <textarea
            ref="contentEl"
            v-model="content"
            class="todo-content"
            rows="2"
            :placeholder="t('todo.contentPh')"
            maxlength="300"
          ></textarea>
          <div class="todo-row">
            <label class="todo-field">
              <span>{{ t('todo.date') }}</span>
              <input v-model="date" type="date" class="todo-input" />
            </label>
            <label class="todo-field">
              <span>{{ t('todo.time') }}</span>
              <input v-model="time" type="time" class="todo-input" />
            </label>
            <label class="todo-field todo-field--repeat">
              <span>{{ t('todo.repeat') }}</span>
              <select v-model="repeat" class="todo-input">
                <option value="once">{{ t('todo.repeatOnce') }}</option>
                <option value="daily">{{ t('todo.repeatDaily') }}</option>
                <option value="weekly">{{ t('todo.repeatWeekly') }}</option>
              </select>
            </label>
          </div>
          <div v-if="repeat === 'weekly'" class="todo-weekdays">
            <label v-for="day in WEEKDAYS" :key="day.value" class="todo-weekday">
              <input v-model="weekdays" type="checkbox" :value="day.value" />
              <span>{{ en ? day.en : day.zh }}</span>
            </label>
          </div>
          <p v-if="formError" class="todo-error">{{ t(formError) }}</p>
          <div class="todo-form-actions">
            <template v-if="editingId && editingStatus === 'scheduled'">
              <button class="todo-btn todo-btn--primary" @click="saveCurrent('keep')">
                {{ t('todo.saveEdit') }}
              </button>
            </template>
            <template v-else>
              <button class="todo-btn todo-btn--primary" @click="saveCurrent('schedule')">
                {{ t('todo.saveSchedule') }}
              </button>
              <button class="todo-btn" @click="saveCurrent('draft')">
                {{ t('todo.save') }}
              </button>
            </template>
            <button v-if="editingId" class="todo-btn" @click="resetForm">{{ t('todo.cancelEdit') }}</button>
          </div>
        </div>

        <div v-if="tab === 'draft'" class="todo-list">
          <div v-if="draftTasks.length" class="todo-bulk">
            <button class="todo-btn todo-btn--primary" @click="moveAllDrafts">{{ t('todo.moveAll') }}</button>
          </div>
          <p v-if="!draftTasks.length" class="todo-empty">{{ t('todo.emptyDraft') }}</p>
          <div v-for="task in draftTasks" :key="task.id" class="todo-item">
            <div class="todo-item-main">
              <span class="todo-item-content">{{ task.content }}</span>
              <span class="todo-item-meta">{{ dueText(task) }} · {{ repeatLabel(task, en) }}</span>
            </div>
            <div class="todo-item-actions">
              <button class="todo-mini" @click="startEdit(task)">{{ t('todo.edit') }}</button>
              <button class="todo-mini todo-mini--primary" @click="confirmDraft(task)">{{ t('todo.setScheduled') }}</button>
              <button class="todo-mini todo-mini--danger" @click="onDelete(task)">{{ t('todo.delete') }}</button>
            </div>
          </div>
        </div>

        <div v-else class="todo-list">
          <p v-if="!scheduledTasks.length" class="todo-empty">{{ t('todo.emptySchedule') }}</p>
          <div v-for="task in scheduledTasks" :key="task.id" class="todo-item">
            <div class="todo-item-main">
              <span class="todo-item-content">{{ task.content }}</span>
              <span class="todo-item-meta">{{ dueText(task) }} · {{ repeatLabel(task, en) }}</span>
            </div>
            <div class="todo-item-actions">
              <button
                :class="statusClass(task)"
                :disabled="!isInProgress(task)"
                @click="onStatus(task)"
              >{{ statusText(task) }}</button>
              <button class="todo-mini" @click="togglePause(task.id)">
                {{ task.paused ? t('todo.resume') : t('todo.pause') }}
              </button>
              <button class="todo-mini" @click="moveToDraft(task.id)">{{ t('todo.toDraft') }}</button>
              <button class="todo-mini todo-mini--danger" @click="onDelete(task)">{{ t('todo.delete') }}</button>
            </div>
          </div>

          <div v-if="expiredItems.length" class="todo-expired">
            <p class="todo-section-title">{{ t('todo.expiredSection') }}</p>
            <div v-for="entry in expiredItems" :key="`${entry.taskId}-${entry.date}`" class="todo-item todo-item--expired">
              <div class="todo-item-main">
                <span class="todo-item-content">{{ entry.content }}</span>
                <span class="todo-item-meta">{{ formatDue(entry.date, entry.time) }} · {{ t('todo.statusExpired') }}</span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </section>
  </div>
</template>

<style scoped>
.todo-wrap {
  position: absolute;
  bottom: 100%;
  margin-bottom: 10px;
  z-index: 45;
  width: 0;
}

.todo-panel {
  transform: translateX(-50%);
  display: flex;
  flex-direction: column;
  width: min(560px, calc(100vw - 32px));
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
}

.close:hover {
  color: var(--cyan);
  box-shadow: var(--glow-cyan);
}

.todo-tabs {
  display: flex;
  gap: 4px;
  padding: 8px 12px 0;
  border-bottom: 1px solid var(--line);
}

.todo-tab {
  flex: 1;
  background: transparent;
  border: none;
  border-bottom: 2px solid transparent;
  color: var(--text-dim);
  padding: 7px 8px 8px;
  cursor: pointer;
  font-size: 12.5px;
}

.todo-tab span {
  font-family: var(--font-tech);
  font-size: 10px;
  color: var(--text-dim);
}

.todo-tab.on {
  color: var(--cyan);
  border-bottom-color: var(--cyan);
}

.todo-body {
  overflow-y: auto;
  padding: 10px 12px 12px;
}

.todo-form {
  border: 1px solid var(--line);
  border-radius: 8px;
  padding: 9px;
  background: var(--bg-card);
  margin-bottom: 10px;
}

.todo-content {
  width: 100%;
  box-sizing: border-box;
  resize: vertical;
  min-height: 44px;
  max-height: 90px;
  background: var(--bg-void);
  border: 1px solid var(--line);
  border-radius: 6px;
  color: var(--text);
  padding: 7px 9px;
  font: inherit;
  font-size: 12.5px;
  outline: none;
}

.todo-content:focus,
.todo-input:focus {
  border-color: var(--line-bright);
}

.todo-row {
  display: flex;
  gap: 7px;
  margin-top: 7px;
}

.todo-field {
  display: flex;
  flex-direction: column;
  gap: 3px;
  font-size: 10.5px;
  color: var(--text-dim);
  min-width: 0;
}

.todo-field--repeat {
  flex: 1;
}

.todo-input {
  background: var(--bg-void);
  border: 1px solid var(--line);
  border-radius: 5px;
  color: var(--text);
  padding: 5px 6px;
  font: inherit;
  font-size: 12px;
  outline: none;
  min-width: 0;
}

.todo-weekdays {
  display: flex;
  flex-wrap: wrap;
  gap: 7px;
  margin-top: 7px;
}

.todo-weekday {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  font-size: 11.5px;
  color: var(--text-dim);
  cursor: pointer;
}

.todo-weekday input {
  accent-color: var(--cyan);
}

.todo-error {
  color: var(--danger);
  font-size: 11.5px;
  margin: 7px 0 0;
}

.todo-form-actions {
  display: flex;
  gap: 7px;
  margin-top: 8px;
}

.todo-btn,
.todo-mini {
  background: transparent;
  border: 1px solid var(--line);
  border-radius: 5px;
  color: var(--text-dim);
  cursor: pointer;
  font-size: 11.5px;
  padding: 4px 9px;
}

.todo-btn--primary,
.todo-mini--primary {
  color: var(--cyan);
  border-color: var(--line-bright);
  background: color-mix(in srgb, var(--cyan) 8%, transparent);
}

.todo-mini--danger {
  color: var(--danger);
  border-color: color-mix(in srgb, var(--danger) 40%, transparent);
}

.todo-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.todo-bulk {
  display: flex;
  justify-content: flex-end;
  padding-bottom: 2px;
}

.todo-empty {
  color: var(--text-dim);
  font-size: 12px;
  text-align: center;
  padding: 14px 8px;
}

.todo-item {
  display: flex;
  align-items: center;
  gap: 8px;
  border: 1px solid var(--line);
  border-radius: 7px;
  padding: 7px 9px;
  background: var(--bg-card);
}

.todo-item--expired {
  opacity: 0.72;
}

.todo-item-main {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
  flex: 1;
}

.todo-item-content {
  color: var(--text-hi);
  font-size: 12.5px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.todo-item-meta {
  color: var(--text-dim);
  font-size: 10.5px;
}

.todo-item-actions {
  display: flex;
  align-items: center;
  gap: 4px;
  flex-shrink: 0;
  flex-wrap: wrap;
  justify-content: flex-end;
}

.todo-status {
  border: 1px solid var(--line);
  border-radius: 999px;
  background: transparent;
  color: var(--text-dim);
  font-size: 10.5px;
  padding: 3px 8px;
}

.todo-status--in_progress {
  color: #ff7b7b;
  border-color: rgba(255, 77, 79, 0.55);
  background: rgba(255, 77, 79, 0.18);
  cursor: pointer;
}

.todo-status--done {
  color: #4dffb8;
  border-color: rgba(77, 255, 184, 0.5);
  background: rgba(77, 255, 184, 0.16);
}

.todo-status--expired {
  color: var(--text-dim);
  border-color: rgba(120, 130, 150, 0.35);
  background: rgba(120, 130, 150, 0.18);
}

.todo-status--paused {
  color: var(--text-dim);
  background: rgba(120, 130, 150, 0.1);
}

.todo-section-title {
  color: var(--text-dim);
  font-size: 10.5px;
  margin: 10px 0 5px;
}

.todo-expired {
  border-top: 1px dashed var(--line);
  margin-top: 4px;
}
</style>
