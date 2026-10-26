/**
 * 待办清单的时间/重复规则(纯函数,无 Vue/localStorage 依赖)。
 *
 * 日期统一用本地时区的 YYYY-MM-DD,时间用 HH:mm;所有计算按本地时间,
 * 存储的是绝对日期字符串而不是 UTC,避免跨时区后任务漂移。
 */
export type RepeatMode = 'once' | 'daily' | 'weekly'

export type TaskStatus = 'draft' | 'scheduled'

export type InstanceStatus =
  | 'pending'      // 在表:今天还没到时间
  | 'in_progress'  // 进行中:今天已到时间、未完成
  | 'done'         // 已完成
  | 'expired'      // 已过期:过期实例
  | 'paused'       // 已暂停
  | 'upcoming'     // 未到开始日期 / 今天不重复

export interface TodoTask {
  id: string
  content: string
  /** 生效起始日 YYYY-MM-DD */
  date: string
  /** 每天提醒时间 HH:mm */
  time: string
  repeat: RepeatMode
  /** 周期性:0=周日,1=周一 ... 6=周六 */
  weekdays: number[]
  status: TaskStatus
  paused: boolean
  createdAt: number
  updatedAt: number
}

export interface ExpiredEntry {
  taskId: string
  content: string
  date: string
  time: string
  ack: boolean
}

/** UI 展示顺序:周一 ... 周日;value 用 JS getDay() 的 0=周日。 */
export const WEEKDAYS: Array<{ value: number; zh: string; en: string }> = [
  { value: 1, zh: '周一', en: 'Mon' },
  { value: 2, zh: '周二', en: 'Tue' },
  { value: 3, zh: '周三', en: 'Wed' },
  { value: 4, zh: '周四', en: 'Thu' },
  { value: 5, zh: '周五', en: 'Fri' },
  { value: 6, zh: '周六', en: 'Sat' },
  { value: 0, zh: '周日', en: 'Sun' },
]

export function pad2(value: number): string {
  return String(value).padStart(2, '0')
}

/** Date → 本地 YYYY-MM-DD */
export function dateKeyOf(date: Date): string {
  return `${date.getFullYear()}-${pad2(date.getMonth() + 1)}-${pad2(date.getDate())}`
}

export function todayKey(now: Date = new Date()): string {
  return dateKeyOf(now)
}

/** YYYY-MM-DD → 本地当天 00:00 */
export function parseDateKey(key: string): Date {
  const [year, month, day] = key.split('-').map(Number)
  return new Date(year, (month || 1) - 1, day || 1)
}

/** 本地日期 + HH:mm → Date;格式非法时返回 Invalid Date */
export function parseDue(date: string, time: string): Date {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(date) || !/^\d{2}:\d{2}$/.test(time)) {
    return new Date(Number.NaN)
  }
  const [year, month, day] = date.split('-').map(Number)
  const [hour, minute] = time.split(':').map(Number)
  if (hour > 23 || minute > 59) return new Date(Number.NaN)
  return new Date(year, month - 1, day, hour, minute, 0, 0)
}

export function minutesOfDay(time: string): number | null {
  if (!/^\d{2}:\d{2}$/.test(time)) return null
  const [hour, minute] = time.split(':').map(Number)
  if (hour > 23 || minute > 59) return null
  return hour * 60 + minute
}

export function formatDue(date: string, time: string): string {
  return `${date.replaceAll('-', '/')} ${time}`
}

/** 任务在指定日期是否应出现(不看待办状态/暂停)。 */
export function activeOn(task: TodoTask, dayKey: string): boolean {
  if (dayKey < task.date) return false
  if (task.repeat === 'once') return dayKey === task.date
  if (task.repeat === 'daily') return true
  return task.weekdays.includes(parseDateKey(dayKey).getDay())
}

/** 今天的展示状态;过期实例由 store 的 expired 表单独处理。 */
export function statusFor(
  task: TodoTask,
  dayKey: string,
  now: Date,
  done: boolean,
): InstanceStatus {
  if (task.paused) return 'paused'
  if (done) return 'done'
  if (task.repeat === 'once' && task.date < dayKey) return 'expired'
  if (!activeOn(task, dayKey)) return 'upcoming'
  const due = parseDue(dayKey, task.time)
  if (Number.isNaN(due.getTime())) return 'pending'
  return now.getTime() >= due.getTime() ? 'in_progress' : 'pending'
}

/** 当天该任务是否已经到提醒时间。 */
export function isDue(task: TodoTask, now: Date): boolean {
  const due = parseDue(todayKey(now), task.time)
  return !Number.isNaN(due.getTime()) && now.getTime() >= due.getTime()
}

export function addDays(dayKey: string, days: number): string {
  const date = parseDateKey(dayKey)
  date.setDate(date.getDate() + days)
  return dateKeyOf(date)
}
