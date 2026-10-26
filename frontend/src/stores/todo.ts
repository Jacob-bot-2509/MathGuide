/**
 * 待办清单 store(local-first)。
 *
 * 存储按 accountKey 分桶:`mg-todo:<accountKey>`。同一账号退出重登可重新加载;
 * 换账号只会看到自己的桶,不会串数据。隐私页「清除本地数据」会清空所有桶。
 *
 * 状态规则:
 * - 草稿永不触发提醒;日程到点触发。
 * - 每天只在当天最早任务时间弹一次面板,列出当天全部任务。
 * - 过期实例按「任务 + 日期」记录,只补当天;更早的日期在下次进入时标记过期。
 * - 过期实例的「已过期」不可点击;进行中的任务可点击变为已完成。
 */
import { reactive, watch } from 'vue'
import { userState } from './user'
import {
  activeOn,
  addDays,
  dateKeyOf,
  formatDue,
  minutesOfDay,
  parseDateKey,
  parseDue,
  statusFor,
  todayKey,
  type ExpiredEntry,
  type InstanceStatus,
  type RepeatMode,
  type TodoTask,
} from '../utils/todoTime'

const STORAGE_PREFIX = 'mg-todo:'
const NOTIFIED_PREFIX = 'mg-todo-notified:'
const MAX_EXPIRED_DAYS = 31
const EXPIRE_RETENTION_DAYS = 60

interface TodoData {
  tasks: TodoTask[]
  /** key = taskId|YYYY-MM-DD */
  done: Record<string, true>
  /** key = taskId|YYYY-MM-DD */
  expired: Record<string, ExpiredEntry>
  lastSeenDate: string
  dailyAck: string
}

export interface TodoDraftInput {
  content: string
  date: string
  time: string
  repeat: RepeatMode
  weekdays: number[]
}

function emptyData(): TodoData {
  return { tasks: [], done: {}, expired: {}, lastSeenDate: '', dailyAck: '' }
}

export const todoState = reactive<{ owner: string; data: TodoData }>({
  owner: '',
  data: emptyData(),
})

function currentOwner(): string {
  return userState.info?.accountKey || ''
}

function storageKey(owner: string): string {
  return `${STORAGE_PREFIX}${owner}`
}

function instanceKey(taskId: string, day: string): string {
  return `${taskId}|${day}`
}

function validTask(value: unknown): value is TodoTask {
  if (!value || typeof value !== 'object') return false
  const t = value as Partial<TodoTask>
  return (
    typeof t.id === 'string' && t.id !== '' &&
    typeof t.content === 'string' && t.content.trim() !== '' &&
    typeof t.date === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(t.date) &&
    typeof t.time === 'string' && /^\d{2}:\d{2}$/.test(t.time) &&
    (t.repeat === 'once' || t.repeat === 'daily' || t.repeat === 'weekly') &&
    Array.isArray(t.weekdays) && t.weekdays.every((d) => Number.isInteger(d) && d >= 0 && d <= 6) &&
    (t.status === 'draft' || t.status === 'scheduled') &&
    typeof t.paused === 'boolean' &&
    typeof t.createdAt === 'number' && typeof t.updatedAt === 'number'
  )
}

function validData(value: unknown): TodoData {
  if (!value || typeof value !== 'object') return emptyData()
  const raw = value as Partial<TodoData>
  const tasks = Array.isArray(raw.tasks) ? raw.tasks.filter(validTask) : []
  const done: Record<string, true> = {}
  if (raw.done && typeof raw.done === 'object') {
    for (const [key, flag] of Object.entries(raw.done)) {
      if (flag === true) done[key] = true
    }
  }
  const expired: Record<string, ExpiredEntry> = {}
  if (raw.expired && typeof raw.expired === 'object') {
    for (const [key, entry] of Object.entries(raw.expired)) {
      if (!entry || typeof entry !== 'object') continue
      const e = entry as Partial<ExpiredEntry>
      if (
        typeof e.taskId === 'string' && typeof e.content === 'string' &&
        typeof e.date === 'string' && typeof e.time === 'string' &&
        typeof e.ack === 'boolean'
      ) {
        expired[key] = { taskId: e.taskId, content: e.content, date: e.date, time: e.time, ack: e.ack }
      }
    }
  }
  return {
    tasks,
    done,
    expired,
    lastSeenDate: typeof raw.lastSeenDate === 'string' ? raw.lastSeenDate : '',
    dailyAck: typeof raw.dailyAck === 'string' ? raw.dailyAck : '',
  }
}

function load(): void {
  const owner = currentOwner()
  todoState.owner = owner
  if (!owner) {
    todoState.data = emptyData()
    return
  }
  try {
    const raw = localStorage.getItem(storageKey(owner))
    todoState.data = raw ? validData(JSON.parse(raw) as unknown) : emptyData()
  } catch {
    todoState.data = emptyData()
  }
}

function persist(): void {
  if (!todoState.owner) return
  try {
    localStorage.setItem(storageKey(todoState.owner), JSON.stringify(todoState.data))
  } catch {
    /* 配额/隐私模式:本次内存状态仍可用 */
  }
}

load()
watch(() => userState.info?.accountKey ?? '', () => load(), { flush: 'sync' })

if (typeof window !== 'undefined') {
  window.addEventListener('storage', (event) => {
    if (event.key === storageKey(currentOwner())) load()
  })
}

function pruneExpired(today: string): boolean {
  const cutoff = addDays(today, -EXPIRE_RETENTION_DAYS)
  let changed = false
  for (const key of Object.keys(todoState.data.expired)) {
    const entry = todoState.data.expired[key]
    if (!entry || entry.date < cutoff) {
      delete todoState.data.expired[key]
      changed = true
    }
  }
  return changed
}

/** 跨天检查:把上次进入之后、今天之前的未完成任务记为过期实例。 */
export function ensureToday(now: Date = new Date()): void {
  const today = todayKey(now)
  const data = todoState.data
  if (!data.lastSeenDate) {
    data.lastSeenDate = today
    persist()
    return
  }
  if (data.lastSeenDate >= today) return

  // 只回看最近 31 天,避免长期未打开时生成过多过期记录
  const earliest = addDays(data.lastSeenDate, 0) > addDays(today, -MAX_EXPIRED_DAYS)
    ? data.lastSeenDate
    : addDays(today, -MAX_EXPIRED_DAYS)
  const cursor = parseDateKey(earliest)
  const end = parseDateKey(today)
  while (cursor.getTime() < end.getTime()) {
    const day = dateKeyOf(cursor)
    for (const task of data.tasks) {
      if (task.status !== 'scheduled' || task.paused) continue
      if (!activeOn(task, day)) continue
      const key = instanceKey(task.id, day)
      if (data.done[key] || data.expired[key]) continue
      data.expired[key] = {
        taskId: task.id,
        content: task.content,
        date: day,
        time: task.time,
        ack: false,
      }
    }
    cursor.setDate(cursor.getDate() + 1)
  }
  data.lastSeenDate = today
  pruneExpired(today)
  persist()
}

export function todayTasks(now: Date = new Date()): TodoTask[] {
  const day = todayKey(now)
  return todoState.data.tasks.filter(
    (task) => task.status === 'scheduled' && !task.paused && activeOn(task, day),
  )
}

/**
 * 当天到点后返回当天全部未完成任务;未到最早任务时间返回空。
 * dailyAck 当天已确认后也返回空。
 */
export function dueDailyTasks(now: Date = new Date()): TodoTask[] {
  ensureToday(now)
  const day = todayKey(now)
  if (todoState.data.dailyAck === day) return []
  const tasks = todayTasks(now).filter((task) => !todoState.data.done[instanceKey(task.id, day)])
  if (!tasks.length) return []
  const minutes = minutesOfDay(`${String(now.getHours()).padStart(2, '0')}:${String(now.getMinutes()).padStart(2, '0')}`)
  if (minutes === null) return []
  const times = tasks.map((task) => minutesOfDay(task.time)).filter((m): m is number => m !== null)
  if (!times.length || minutes < Math.min(...times)) return []
  return tasks
}

export function ackDaily(now: Date = new Date()): void {
  todoState.data.dailyAck = todayKey(now)
  persist()
}

export function isDone(taskId: string, day: string): boolean {
  return todoState.data.done[instanceKey(taskId, day)] === true
}

export function taskStatus(task: TodoTask, now: Date = new Date()): InstanceStatus {
  const day = todayKey(now)
  return statusFor(task, day, now, isDone(task.id, day))
}

export function markDone(taskId: string, now: Date = new Date()): void {
  const task = todoState.data.tasks.find((item) => item.id === taskId)
  if (!task) return
  todoState.data.done[instanceKey(taskId, todayKey(now))] = true
  persist()
}

/** 过期提醒:未确认的过期实例,按日期/时间排序。 */
export function unackExpired(): ExpiredEntry[] {
  ensureToday()
  return Object.values(todoState.data.expired)
    .filter((entry) => !entry.ack)
    .sort((a, b) => `${a.date} ${a.time}`.localeCompare(`${b.date} ${b.time}`))
}

/** 日程面板里展示全部过期实例(含已确认)。 */
export function allExpired(): ExpiredEntry[] {
  ensureToday()
  return Object.values(todoState.data.expired)
    .sort((a, b) => `${b.date} ${b.time}`.localeCompare(`${a.date} ${a.time}`))
}

export function ackAllExpired(): void {
  for (const entry of Object.values(todoState.data.expired)) entry.ack = true
  persist()
}

export function saveTask(input: TodoDraftInput, editingId?: string | null, now: Date = new Date()): TodoTask {
  const content = input.content.trim()
  const existing = editingId
    ? todoState.data.tasks.find((task) => task.id === editingId)
    : undefined
  const stamp = now.getTime()
  const task: TodoTask = {
    id: existing?.id ?? `todo-${stamp}-${Math.floor(Math.random() * 1000)}`,
    content,
    date: input.date,
    time: input.time,
    repeat: input.repeat,
    weekdays: input.repeat === 'weekly' ? [...new Set(input.weekdays)].sort((a, b) => a - b) : [],
    status: existing?.status === 'scheduled' ? 'scheduled' : 'draft',
    paused: existing?.paused ?? false,
    createdAt: existing?.createdAt ?? stamp,
    updatedAt: stamp,
  }
  if (existing) {
    Object.assign(existing, task)
  } else {
    todoState.data.tasks.push(task)
  }
  persist()
  return task
}

export function moveToSchedule(id: string): void {
  const task = todoState.data.tasks.find((item) => item.id === id)
  if (!task) return
  task.status = 'scheduled'
  task.paused = false
  task.updatedAt = Date.now()
  persist()
}

export function moveToDraft(id: string): void {
  const task = todoState.data.tasks.find((item) => item.id === id)
  if (!task) return
  task.status = 'draft'
  task.updatedAt = Date.now()
  persist()
}

/** 草稿一键全部转日程;返回转移条数。 */
export function moveAllToSchedule(): number {
  let count = 0
  for (const task of todoState.data.tasks) {
    if (task.status !== 'draft') continue
    task.status = 'scheduled'
    task.paused = false
    task.updatedAt = Date.now()
    count += 1
  }
  if (count) persist()
  return count
}

export function togglePause(id: string): void {
  const task = todoState.data.tasks.find((item) => item.id === id)
  if (!task) return
  task.paused = !task.paused
  task.updatedAt = Date.now()
  persist()
}

export function deleteTask(id: string): void {
  todoState.data.tasks = todoState.data.tasks.filter((task) => task.id !== id)
  for (const key of Object.keys(todoState.data.done)) {
    if (key.startsWith(`${id}|`)) delete todoState.data.done[key]
  }
  for (const key of Object.keys(todoState.data.expired)) {
    if (key.startsWith(`${id}|`)) delete todoState.data.expired[key]
  }
  persist()
}

export function clearAllTodoData(): void {
  if (typeof localStorage !== 'undefined') {
    try {
      const keys: string[] = []
      for (let i = 0; i < localStorage.length; i += 1) {
        const key = localStorage.key(i)
        if (key && (key.startsWith(STORAGE_PREFIX) || key.startsWith(NOTIFIED_PREFIX))) keys.push(key)
      }
      for (const key of keys) localStorage.removeItem(key)
    } catch {
      /* 忽略 */
    }
  }
  todoState.owner = currentOwner()
  todoState.data = emptyData()
}

/** 供提醒组件做跨标签页去重(只压系统通知,不压页面内面板)。 */
export function notificationKey(now: Date = new Date()): string {
  return `${NOTIFIED_PREFIX}${todoState.owner || 'anon'}:${todayKey(now)}`
}

export function repeatLabel(task: TodoTask, en: boolean): string {
  if (task.repeat === 'once') return en ? 'Once' : '一次性'
  if (task.repeat === 'daily') return en ? 'Daily' : '每天'
  const names = task.weekdays
    .slice()
    .sort((a, b) => (a === 0 ? 7 : a) - (b === 0 ? 7 : b))
    .map((d) => {
      const item = { 0: 'Sun', 1: 'Mon', 2: 'Tue', 3: 'Wed', 4: 'Thu', 5: 'Fri', 6: 'Sat' }[d]
      const zh = { 0: '周日', 1: '周一', 2: '周二', 3: '周三', 4: '周四', 5: '周五', 6: '周六' }[d]
      return en ? item : zh
    })
  return (en ? 'Weekly ' : '周期性 ') + names.join(' ')
}

export function dueText(task: TodoTask): string {
  return formatDue(task.date, task.time)
}

/** 用于 UI:一次性任务是否已经彻底过期(不是当天实例)。 */
export function onceExpired(task: TodoTask, now: Date = new Date()): boolean {
  return task.repeat === 'once' && task.date < todayKey(now) && !isDone(task.id, task.date)
}

/** 解析并校验一个草稿输入;返回错误 key 或 null。 */
export function validateDraft(input: TodoDraftInput, now: Date = new Date()): string | null {
  if (!input.content.trim()) return 'todo.errorContent'
  const due = parseDue(input.date, input.time)
  if (Number.isNaN(due.getTime())) return 'todo.errorTime'
  if (input.repeat === 'weekly' && input.weekdays.length === 0) return 'todo.errorWeekdays'
  if (due.getTime() <= now.getTime()) return 'todo.errorPast'
  return null
}
