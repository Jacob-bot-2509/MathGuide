/**
 * 待办时间规则测试(纯函数)。
 *
 * 全部用例注入固定 now,不用 sleep/fake timers:日期口径(本地 YYYY-MM-DD)、
 * 重复规则与「到点/未到点」判定错一天,提醒就会漏或重复弹。
 */
import { describe, expect, it } from 'vitest'
import {
  WEEKDAYS,
  activeOn,
  addDays,
  dateKeyOf,
  formatDue,
  isDue,
  minutesOfDay,
  pad2,
  parseDateKey,
  parseDue,
  statusFor,
  todayKey,
  type TodoTask,
} from '@/utils/todoTime'

function task(patch: Partial<TodoTask> = {}): TodoTask {
  return {
    id: 't1',
    content: '复习极限',
    date: '2026-03-10',
    time: '09:30',
    repeat: 'once',
    weekdays: [],
    status: 'scheduled',
    paused: false,
    createdAt: 0,
    updatedAt: 0,
    ...patch,
  }
}

describe('日期/时间基础换算', () => {
  it('pad2 补齐两位', () => {
    expect(pad2(0)).toBe('00')
    expect(pad2(7)).toBe('07')
    expect(pad2(31)).toBe('31')
  })

  it('dateKeyOf / todayKey 用本地日期而不是 UTC', () => {
    expect(dateKeyOf(new Date(2026, 0, 5))).toBe('2026-01-05')
    expect(todayKey(new Date(2026, 11, 31, 23, 59))).toBe('2026-12-31')
    // 不传参时取系统当前时间
    expect(todayKey()).toBe(dateKeyOf(new Date()))
  })

  it('parseDateKey 解析成本地当天 00:00,残缺键退回月初/1 号', () => {
    const full = parseDateKey('2026-03-10')
    expect([full.getFullYear(), full.getMonth(), full.getDate()]).toEqual([2026, 2, 10])
    expect(full.getHours()).toBe(0)
    const monthOnly = parseDateKey('2026-07')
    expect(monthOnly.getMonth()).toBe(6)
    expect(monthOnly.getDate()).toBe(1)
    expect(parseDateKey('2026').getMonth()).toBe(0)
  })

  it('parseDue 组装本地时间,格式非法返回 Invalid Date', () => {
    const due = parseDue('2026-03-10', '09:30')
    expect(due.getTime()).toBe(new Date(2026, 2, 10, 9, 30, 0, 0).getTime())
    expect(Number.isNaN(parseDue('2026-3-10', '09:30').getTime())).toBe(true)
    expect(Number.isNaN(parseDue('2026-03-10', '9:30').getTime())).toBe(true)
    expect(Number.isNaN(parseDue('2026-03-10', '24:00').getTime())).toBe(true)
    expect(Number.isNaN(parseDue('2026-03-10', '09:60').getTime())).toBe(true)
  })

  it('minutesOfDay 校验范围,非法返回 null', () => {
    expect(minutesOfDay('00:00')).toBe(0)
    expect(minutesOfDay('09:30')).toBe(570)
    expect(minutesOfDay('23:59')).toBe(23 * 60 + 59)
    expect(minutesOfDay('24:00')).toBeNull()
    expect(minutesOfDay('12:60')).toBeNull()
    expect(minutesOfDay('12')).toBeNull()
  })

  it('formatDue 把连字符换成斜杠,便于展示', () => {
    expect(formatDue('2026-03-10', '09:30')).toBe('2026/03/10 09:30')
  })

  it('addDays 跨月/跨年/负数都按本地日历推进', () => {
    expect(addDays('2026-03-10', 1)).toBe('2026-03-11')
    expect(addDays('2026-02-28', 1)).toBe('2026-03-01')
    expect(addDays('2026-12-31', 1)).toBe('2027-01-01')
    expect(addDays('2026-01-01', -1)).toBe('2025-12-31')
  })
})

describe('activeOn / 重复规则', () => {
  it('开始日期之前一律不出现', () => {
    expect(activeOn(task(), '2026-03-09')).toBe(false)
  })

  it('一次性任务只在当天出现', () => {
    expect(activeOn(task(), '2026-03-10')).toBe(true)
    expect(activeOn(task(), '2026-03-11')).toBe(false)
  })

  it('每天任务从起始日起天天出现', () => {
    const daily = task({ repeat: 'daily' })
    expect(activeOn(daily, '2026-03-10')).toBe(true)
    expect(activeOn(daily, '2026-03-17')).toBe(true)
    expect(activeOn(daily, '2026-03-09')).toBe(false)
  })

  it('周期性任务只命中登记的星期', () => {
    // 2026-03-10 是周二(2)
    const weekly = task({ repeat: 'weekly', weekdays: [2, 4] })
    expect(activeOn(weekly, '2026-03-10')).toBe(true)
    expect(activeOn(weekly, '2026-03-11')).toBe(false)
    expect(activeOn(weekly, '2026-03-12')).toBe(true)
  })

  it('WEEKDAYS 展示顺序为周一…周日,value 与 getDay() 同口径', () => {
    expect(WEEKDAYS.map((d) => d.value)).toEqual([1, 2, 3, 4, 5, 6, 0])
    expect(WEEKDAYS[0]).toEqual({ value: 1, zh: '周一', en: 'Mon' })
    expect(WEEKDAYS[6].value).toBe(0)
  })
})

describe('statusFor / 实例状态', () => {
  const now = new Date(2026, 2, 10, 10, 0)

  it('暂停优先于一切', () => {
    expect(statusFor(task({ paused: true }), '2026-03-10', now, false)).toBe('paused')
    expect(statusFor(task({ paused: true }), '2026-03-10', now, true)).toBe('paused')
  })

  it('已完成优先于时间判定', () => {
    expect(statusFor(task(), '2026-03-10', now, true)).toBe('done')
  })

  it('一次性任务过了当天记为过期', () => {
    expect(statusFor(task(), '2026-03-11', now, false)).toBe('expired')
  })

  it('未到起始日/今天不重复 → upcoming', () => {
    expect(statusFor(task({ date: '2026-04-01' }), '2026-03-10', now, false)).toBe('upcoming')
    expect(statusFor(task({ repeat: 'weekly', weekdays: [5] }), '2026-03-10', now, false)).toBe('upcoming')
  })

  it('到点前 pending,到点后 in_progress', () => {
    expect(statusFor(task({ time: '11:00' }), '2026-03-10', now, false)).toBe('pending')
    expect(statusFor(task({ time: '10:00' }), '2026-03-10', now, false)).toBe('in_progress')
  })

  it('时间格式非法时按 pending 处理,不抛异常', () => {
    expect(statusFor(task({ time: '9:5' }), '2026-03-10', now, false)).toBe('pending')
  })

  it('isDue 以今天的时间点判定', () => {
    expect(isDue(task({ time: '09:00' }), now)).toBe(true)
    expect(isDue(task({ time: '09:00' }), new Date(2026, 2, 10, 8, 59))).toBe(false)
    expect(isDue(task({ time: 'bad' }), now)).toBe(false)
  })
})
