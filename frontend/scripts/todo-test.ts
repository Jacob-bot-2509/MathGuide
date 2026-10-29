/**
 * 待办清单时间/状态自测(esbuild 打包后 node 执行)。
 *
 * 覆盖:一次性/每天/周期性判定、当天最早提醒、确认后不再弹、完成状态、
 * 跨天过期、草稿/日程转换、退出重登同账号恢复、换账号隔离、清空数据。
 */
/* eslint-disable */
declare const process: { exit(code: number): void }

import type { TodoTask } from '../src/utils/todoTime'

const memory = new Map<string, string>()
const localStorageMock = {
  getItem: (key: string) => memory.get(key) ?? null,
  setItem: (key: string, value: string) => { memory.set(key, String(value)) },
  removeItem: (key: string) => { memory.delete(key) },
  clear: () => memory.clear(),
  key: (index: number) => Array.from(memory.keys())[index] ?? null,
  get length() { return memory.size },
}
;(globalThis as unknown as { localStorage: typeof localStorageMock }).localStorage = localStorageMock

let passed = 0
const failed: string[] = []
function check(name: string, ok: boolean, detail = '') {
  if (ok) passed++
  else failed.push(`${name}${detail ? `: ${detail}` : ''}`)
}

async function main() {
  const time = await import('../src/utils/todoTime')
  const { userState } = await import('../src/stores/user')
  userState.info = {
    accountKey: 'acct-A', nickname: 'A', avatar: 'preset:sum', authMethod: 'wechat',
  }
  const todo = await import('../src/stores/todo')

  const now = new Date(2026, 9, 26, 8, 0, 0) // local 2026-10-26 08:00
  const day = time.dateKeyOf(now)
  const tomorrow = time.addDays(day, 1)
  const yesterday = time.addDays(day, -1)

  // ---- 纯规则 ----
  const once: TodoTask = {
    id: 't-once', content: 'once', date: day, time: '09:00', repeat: 'once',
    weekdays: [], status: 'scheduled', paused: false, createdAt: 0, updatedAt: 0,
  }
  const daily: TodoTask = { ...once, id: 't-daily', repeat: 'daily' }
  const weekday = time.parseDateKey(day).getDay()
  const weekly: TodoTask = { ...once, id: 't-weekly', repeat: 'weekly', weekdays: [weekday] }

  check('一次性只在当天', time.activeOn(once, day) && !time.activeOn(once, tomorrow))
  check('每天从起始日往后', time.activeOn(daily, day) && time.activeOn(daily, tomorrow) && !time.activeOn(daily, yesterday))
  check('周期性只命中选中星期', time.activeOn(weekly, day) && !time.activeOn({ ...weekly, weekdays: [(weekday + 1) % 7] }, day))
  check('08:00 未到 09:00 为在表', time.statusFor(once, day, now, false) === 'pending')
  check('09:01 为进行中', time.statusFor(once, day, new Date(2026, 9, 26, 9, 1), false) === 'in_progress')
  check('完成优先于进行中', time.statusFor(once, day, new Date(2026, 9, 26, 9, 1), true) === 'done')
  check('日期时间格式化', time.formatDue(day, '09:05') === `${day.replaceAll('-', '/')} 09:05`)

  // ---- 草稿 → 日程 / 当天提醒 ----
  const a = todo.saveTask({ content: 'A', date: day, time: '09:00', repeat: 'once', weekdays: [] }, null, now)
  const b = todo.saveTask({ content: 'B', date: day, time: '10:00', repeat: 'once', weekdays: [] }, null, now)
  check('新任务进入草稿', a.status === 'draft' && b.status === 'draft')
  check('草稿不触发提醒', todo.dueDailyTasks(new Date(2026, 9, 26, 9, 30)).length === 0)

  todo.moveToSchedule(a.id)
  todo.moveToSchedule(b.id)
  check('设置好了进入日程', todo.todoState.data.tasks.filter((x) => x.status === 'scheduled').length === 2)
  check('最早时间前不弹', todo.dueDailyTasks(new Date(2026, 9, 26, 8, 59)).length === 0)
  check('最早时间到,一次返回当天全部', todo.dueDailyTasks(new Date(2026, 9, 26, 9, 0)).length === 2)
  todo.ackDaily(new Date(2026, 9, 26, 9, 0))
  check('当天确认后不再弹', todo.dueDailyTasks(new Date(2026, 9, 26, 10, 30)).length === 0)

  todo.markDone(a.id, new Date(2026, 9, 26, 9, 30))
  check('进行中点击后变已完成', todo.taskStatus(a, new Date(2026, 9, 26, 9, 30)) === 'done')

  // ---- 跨天过期 ----
  const old = todo.saveTask({ content: 'old', date: yesterday, time: '09:00', repeat: 'once', weekdays: [] }, null, now)
  todo.moveToSchedule(old.id)
  todo.todoState.data.lastSeenDate = yesterday
  todo.ensureToday(now)
  check('跨天未完成标记过期', todo.allExpired().some((entry) => entry.taskId === old.id))
  check('过期进入待知晓列表', todo.unackExpired().some((entry) => entry.taskId === old.id))
  todo.ackAllExpired()
  check('我已知晓后不再弹', !todo.unackExpired().some((entry) => entry.taskId === old.id))

  // ---- 批量转日程 ----
  const c = todo.saveTask({ content: 'C', date: tomorrow, time: '09:00', repeat: 'daily', weekdays: [] }, null, now)
  const d = todo.saveTask({ content: 'D', date: tomorrow, time: '10:00', repeat: 'daily', weekdays: [] }, null, now)
  check('批量转日程计数', todo.moveAllToSchedule() >= 2)
  check('批量后无草稿', !todo.todoState.data.tasks.some((x) => x.status === 'draft'))
  check('重复标签', todo.repeatLabel(c, false).includes('每天') && todo.repeatLabel(d, true).includes('Daily'))

  // ---- 账号分桶 ----
  userState.info = { accountKey: 'acct-B', nickname: 'B', avatar: 'preset:int', authMethod: 'wechat' }
  await Promise.resolve()
  check('换账号看不到上一位任务', todo.todoState.data.tasks.length === 0)
  userState.info = { accountKey: 'acct-A', nickname: 'A', avatar: 'preset:sum', authMethod: 'wechat' }
  await Promise.resolve()
  check('同账号重登恢复任务', todo.todoState.data.tasks.length > 0)

  // ---- 工作区分桶 ----
  todo.setTodoWorkspace('learn')
  todo.saveTask({ content: 'learn-only', date: day, time: '11:00', repeat: 'once', weekdays: [] }, null, now)
  todo.setTodoWorkspace('research')
  check('科研区看不到学习区任务', !todo.todoState.data.tasks.some((x) => x.content === 'learn-only'))
  todo.saveTask({ content: 'research-only', date: day, time: '12:00', repeat: 'once', weekdays: [] }, null, now)
  todo.setTodoWorkspace('learn')
  check('学习区恢复后仍只有自己的任务',
    todo.todoState.data.tasks.some((x) => x.content === 'learn-only') &&
    !todo.todoState.data.tasks.some((x) => x.content === 'research-only'))
  todo.setTodoWorkspace('research')
  check('科研区任务独立保留',
    todo.todoState.data.tasks.some((x) => x.content === 'research-only') &&
    !todo.todoState.data.tasks.some((x) => x.content === 'learn-only'))

  // ---- 清空 ----
  todo.clearAllTodoData()
  check('清空后内存为空', todo.todoState.data.tasks.length === 0)
  check('清空后 localStorage 无任务键', !Array.from(memory.keys()).some((key) => key.startsWith('mg-todo:')))

  console.log(`\n待办清单自测:${passed}/${passed + failed.length} 通过`)
  for (const item of failed) console.log(`✗ ${item}`)
  if (failed.length) process.exit(1)
}

void main()
