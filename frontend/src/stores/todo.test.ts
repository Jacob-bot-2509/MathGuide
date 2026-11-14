// @vitest-environment happy-dom
/**
 * 待办 store 测试(local-first)。
 *
 * 这个 store 绑定三件容易出事故的机制,必须逐个钉住:
 *   1. 按 accountKey 分桶 —— 换账号不能串任务;
 *   2. localStorage 脏数据容错 —— 手改/旧版本写坏后页面不能挂;
 *   3. 跨天结算(ensureToday)—— 过期实例要补记,且有 31/60 天两道上限。
 * localStorage 用内存替身接管,便于注入脏 JSON 与写满配额。
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { TodoTask } from '@/utils/todoTime'

const memory = new Map<string, string>()
let failWrites = false

function installStorage() {
  vi.stubGlobal('localStorage', {
    getItem: (key: string) => memory.get(key) ?? null,
    setItem: (key: string, value: string) => {
      if (failWrites) throw new Error('QuotaExceededError')
      memory.set(key, String(value))
    },
    removeItem: (key: string) => {
      memory.delete(key)
    },
    clear: () => memory.clear(),
    key: (index: number) => [...memory.keys()][index] ?? null,
    get length() {
      return memory.size
    },
  })
}

async function boot() {
  const user = await import('@/stores/user')
  const todo = await import('@/stores/todo')
  return { user, todo }
}

/** 登录替身:todo 只按 accountKey 分桶,其余档案字段用占位值即可 */
function signIn(user: typeof import('@/stores/user'), accountKey: string) {
  user.login({ accountKey, nickname: 't', avatar: 'preset:sum', authMethod: 'phone-pass' })
}

function stored(owner: string) {
  const raw = memory.get(`mg-todo:${owner}`)
  return raw ? JSON.parse(raw) : null
}

/** 合法任务样本(字段全过 validTask);patch 故意放宽,便于构造脏数据 */
function task(patch: Record<string, unknown> = {}): TodoTask {
  return {
    id: 'task-1',
    content: '复习极限',
    date: '2026-03-10',
    time: '09:30',
    repeat: 'once',
    weekdays: [],
    status: 'scheduled',
    paused: false,
    createdAt: 1,
    updatedAt: 1,
    ...patch,
  } as unknown as TodoTask
}

function seedData(owner: string, patch: Record<string, unknown> = {}) {
  memory.set(`mg-todo:${owner}`, JSON.stringify({
    tasks: [],
    done: {},
    expired: {},
    lastSeenDate: '',
    dailyAck: '',
    ...patch,
  }))
}

beforeEach(() => {
  memory.clear()
  failWrites = false
  vi.resetModules()
  vi.unstubAllGlobals()
  installStorage()
  // saveTask 的 id 由 Date.now() + Math.random() 生成:同毫秒内连建两个任务
  // 可能撞号,测试里让时间戳单调递增以固定 id 唯一性。
  let clock = 1_700_000_000_000
  vi.spyOn(Date, 'now').mockImplementation(() => (clock += 1))
})

afterEach(() => {
  vi.restoreAllMocks()
})

describe('加载与分桶', () => {
  it('未登录时是空状态,且不写盘', async () => {
    const { todo } = await boot()
    expect(todo.todoState.owner).toBe('')
    expect(todo.todoState.data.tasks).toEqual([])
    expect(todo.todoState.data.lastSeenDate).toBe('')
  })

  it('登录后读取自己的桶', async () => {
    seedData('acct-A', { tasks: [task()], lastSeenDate: '2026-03-10' })
    const { user, todo } = await boot()
    signIn(user, 'acct-A')
    expect(todo.todoState.owner).toBe('acct-A')
    expect(todo.todoState.data.tasks).toHaveLength(1)
  })

  it('换账号只看自己的桶(不串数据)', async () => {
    seedData('acct-A', { tasks: [task({ id: 'a' })] })
    seedData('acct-B', { tasks: [task({ id: 'b' })] })
    const { user, todo } = await boot()
    signIn(user, 'acct-A')
    expect(todo.todoState.data.tasks.map((t) => t.id)).toEqual(['a'])
    signIn(user, 'acct-B')
    expect(todo.todoState.data.tasks.map((t) => t.id)).toEqual(['b'])
    user.logout()
    expect(todo.todoState.owner).toBe('')
    expect(todo.todoState.data.tasks).toEqual([])
  })

  it('脏 JSON 回退空数据而不是抛错', async () => {
    memory.set('mg-todo:acct-A', '{broken')
    const { user, todo } = await boot()
    expect(() => signIn(user, 'acct-A')).not.toThrow()
    expect(todo.todoState.data.tasks).toEqual([])
  })

  it('字段级校验:非法任务/非法 done/非法 expired 全部丢弃', async () => {
    seedData('acct-A', {
      tasks: [
        task(),
        task({ id: '' }),
        task({ id: 't2', content: '   ' }),
        task({ id: 't3', date: '2026/03/10' }),
        task({ id: 't4', time: '9:30' }),
        task({ id: 't5', repeat: 'monthly' }),
        task({ id: 't6', weekdays: [9] }),
        task({ id: 't7', status: 'done' }),
        task({ id: 't8', paused: 'no' }),
        'not-an-object',
      ],
      done: { 'task-1|2026-03-10': true, 'task-1|2026-03-11': false, 'task-2|2026-03-10': 'yes' },
      expired: {
        good: { taskId: 'task-1', content: 'c', date: '2026-03-09', time: '09:30', ack: false },
        badType: 'text',
        badShape: { taskId: 'task-1', content: 'c', date: '2026-03-09', time: '09:30' },
      },
      lastSeenDate: 123,
      dailyAck: null,
    })
    const { user, todo } = await boot()
    signIn(user, 'acct-A')
    expect(todo.todoState.data.tasks.map((t) => t.id)).toEqual(['task-1'])
    expect(Object.keys(todo.todoState.data.done)).toEqual(['task-1|2026-03-10'])
    expect(Object.keys(todo.todoState.data.expired)).toEqual(['good'])
    expect(todo.todoState.data.lastSeenDate).toBe('')
    expect(todo.todoState.data.dailyAck).toBe('')
  })

  it('非对象数据整份回退', async () => {
    memory.set('mg-todo:acct-A', '"just a string"')
    const { user, todo } = await boot()
    signIn(user, 'acct-A')
    expect(todo.todoState.data.tasks).toEqual([])
  })

  it('写盘失败(配额/隐私模式)时内存状态仍可用', async () => {
    const { user, todo } = await boot()
    signIn(user, 'acct-A')
    failWrites = true
    expect(() => todo.saveTask({ content: '新任务', date: '2099-01-01', time: '10:00', repeat: 'once', weekdays: [] })).not.toThrow()
    expect(todo.todoState.data.tasks).toHaveLength(1)
    expect(memory.has('mg-todo:acct-A')).toBe(false)
  })
})

describe('跨标签页 storage 事件', () => {
  it('同桶被别的标签页改写后重新加载', async () => {
    const { user, todo } = await boot()
    signIn(user, 'acct-A')
    expect(todo.todoState.data.tasks).toHaveLength(0)

    seedData('acct-A', { tasks: [task({ id: 'from-other-tab' })] })
    window.dispatchEvent(new StorageEvent('storage', { key: 'mg-todo:acct-A' }))
    expect(todo.todoState.data.tasks.map((t) => t.id)).toEqual(['from-other-tab'])
  })

  it('其他键的变化不触发重载', async () => {
    const { user, todo } = await boot()
    signIn(user, 'acct-A')
    seedData('acct-A', { tasks: [task({ id: 'x' })] })
    window.dispatchEvent(new StorageEvent('storage', { key: 'unrelated' }))
    expect(todo.todoState.data.tasks).toHaveLength(0)
  })
})


describe('任务增删改', () => {
  it('saveTask 新建为草稿并落盘', async () => {
    const { user, todo } = await boot()
    signIn(user, 'acct-A')
    const created = todo.saveTask(
      { content: '  写作业  ', date: '2099-01-02', time: '10:00', repeat: 'once', weekdays: [3, 1] },
      null,
      new Date(2099, 0, 1, 8, 0),
    )
    expect(created.content).toBe('写作业')
    expect(created.status).toBe('draft')
    expect(created.weekdays).toEqual([]) // 非 weekly 不存星期
    expect(created.createdAt).toBe(new Date(2099, 0, 1, 8, 0).getTime())
    expect(stored('acct-A').tasks).toHaveLength(1)
  })

  it('weekly 任务去重并升序保存星期', async () => {
    const { user, todo } = await boot()
    signIn(user, 'acct-A')
    const created = todo.saveTask({ content: '周课', date: '2099-01-01', time: '08:00', repeat: 'weekly', weekdays: [5, 1, 5, 3] })
    expect(created.weekdays).toEqual([1, 3, 5])
  })

  it('编辑保持 id/createdAt/状态与暂停标记', async () => {
    const { user, todo } = await boot()
    signIn(user, 'acct-A')
    const created = todo.saveTask({ content: '原标题', date: '2099-01-01', time: '08:00', repeat: 'once', weekdays: [] })
    todo.moveToSchedule(created.id)
    todo.togglePause(created.id)

    const edited = todo.saveTask(
      { content: '新标题', date: '2099-01-05', time: '09:00', repeat: 'daily', weekdays: [] },
      created.id,
      new Date(2099, 0, 2, 9, 0),
    )
    expect(edited.id).toBe(created.id)
    expect(edited.content).toBe('新标题')
    expect(edited.status).toBe('scheduled') // 已是日程的编辑后仍是日程
    expect(edited.paused).toBe(true)
    expect(edited.createdAt).toBe(created.createdAt)
    expect(todo.todoState.data.tasks).toHaveLength(1)
  })

  it('编辑不存在的 id 等同于新建', async () => {
    const { user, todo } = await boot()
    signIn(user, 'acct-A')
    const created = todo.saveTask({ content: 'x', date: '2099-01-01', time: '08:00', repeat: 'once', weekdays: [] }, 'ghost-id')
    expect(created.status).toBe('draft')
    expect(todo.todoState.data.tasks).toHaveLength(1)
  })

  it('草稿/日程互转,未知 id 不抛错', async () => {
    const { user, todo } = await boot()
    signIn(user, 'acct-A')
    const a = todo.saveTask({ content: 'a', date: '2099-01-01', time: '08:00', repeat: 'once', weekdays: [] })
    const b = todo.saveTask({ content: 'b', date: '2099-01-02', time: '08:00', repeat: 'once', weekdays: [] })

    expect(() => todo.moveToSchedule('nope')).not.toThrow()
    expect(() => todo.moveToDraft('nope')).not.toThrow()
    expect(() => todo.togglePause('nope')).not.toThrow()
    expect(() => todo.markDone('nope')).not.toThrow()

    todo.moveToSchedule(a.id)
    todo.moveToSchedule(b.id)
    todo.togglePause(a.id)
    todo.moveToDraft(a.id)
    expect(a.status).toBe('draft')
    expect(a.paused).toBe(true) // moveToDraft 不改暂停标记
    todo.moveToSchedule(a.id)
    expect(a.paused).toBe(false) // moveToSchedule 恢复提醒
  })

  it('moveAllToSchedule 只转草稿并返回条数', async () => {
    const { user, todo } = await boot()
    signIn(user, 'acct-A')
    const a = todo.saveTask({ content: 'a', date: '2099-01-01', time: '08:00', repeat: 'once', weekdays: [] })
    const b = todo.saveTask({ content: 'b', date: '2099-01-02', time: '08:00', repeat: 'once', weekdays: [] })
    todo.moveToSchedule(a.id)

    expect(todo.moveAllToSchedule()).toBe(1)
    expect(b.status).toBe('scheduled')
    expect(todo.moveAllToSchedule()).toBe(0)
  })

  it('deleteTask 同时清掉该任务的已完成与过期记录', async () => {
    const { user, todo } = await boot()
    signIn(user, 'acct-A')
    const a = todo.saveTask({ content: 'a', date: '2099-01-01', time: '08:00', repeat: 'daily', weekdays: [] })
    const b = todo.saveTask({ content: 'b', date: '2099-01-02', time: '08:00', repeat: 'daily', weekdays: [] })
    todo.moveToSchedule(a.id)
    todo.moveToSchedule(b.id)
    todo.markDone(a.id, new Date(2099, 0, 3, 9, 0))
    todo.markDone(b.id, new Date(2099, 0, 3, 9, 0))
    expect(Object.keys(todo.todoState.data.done)).toHaveLength(2)

    todo.deleteTask(a.id)
    expect(todo.todoState.data.tasks.map((t) => t.id)).toEqual([b.id])
    expect(Object.keys(todo.todoState.data.done)).toEqual([`${b.id}|2099-01-03`])
    expect(stored('acct-A').tasks).toHaveLength(1)
  })
})


describe('当天视图与到点提醒', () => {
  const now = new Date(2099, 2, 10, 10, 0) // 2099-03-10 10:00

  it('todayTasks 只保留当天生效的日程(排除草稿/暂停/不重复的)', async () => {
    seedData('acct-A', {
      tasks: [
        task({ id: 'once-today', date: '2099-03-10' }),
        task({ id: 'draft', date: '2099-03-10', status: 'draft' }),
        task({ id: 'paused', date: '2099-03-10', paused: true }),
        task({ id: 'future', date: '2099-04-01' }),
        task({ id: 'weekly-other', date: '2099-03-01', repeat: 'weekly', weekdays: [5] }),
        task({ id: 'daily', date: '2099-03-01', repeat: 'daily' }),
      ],
    })
    const { user, todo } = await boot()
    signIn(user, 'acct-A')
    expect(todo.todayTasks(now).map((t) => t.id)).toEqual(['once-today', 'daily'])
  })

  it('dueDailyTasks 未到最早时间返回空,到点后返回当天未完成的全部任务', async () => {
    seedData('acct-A', {
      tasks: [
        task({ id: 'early', date: '2099-03-10', time: '09:00' }),
        task({ id: 'late', date: '2099-03-10', time: '18:00' }),
      ],
    })
    const { user, todo } = await boot()
    signIn(user, 'acct-A')

    expect(todo.dueDailyTasks(new Date(2099, 2, 10, 8, 59))).toEqual([])
    // 只要过了当天最早任务时间,面板就列出全部任务(含更晚的)
    expect(todo.dueDailyTasks(now).map((t) => t.id)).toEqual(['early', 'late'])
  })

  it('已完成的任务不再进提醒', async () => {
    seedData('acct-A', {
      tasks: [task({ id: 'a', date: '2099-03-10', time: '09:00' })],
      done: { 'a|2099-03-10': true },
    })
    const { user, todo } = await boot()
    signIn(user, 'acct-A')
    expect(todo.dueDailyTasks(now)).toEqual([])
  })

  it('当天已确认(dailyAck)后不再提醒', async () => {
    seedData('acct-A', {
      tasks: [task({ id: 'a', date: '2099-03-10', time: '09:00' })],
      dailyAck: '2099-03-10',
    })
    const { user, todo } = await boot()
    signIn(user, 'acct-A')
    expect(todo.dueDailyTasks(now)).toEqual([])
  })

  it('ackDaily 记下当天已确认并落盘', async () => {
    const { user, todo } = await boot()
    signIn(user, 'acct-A')
    todo.ackDaily(now)
    expect(todo.todoState.data.dailyAck).toBe('2099-03-10')
    expect(stored('acct-A').dailyAck).toBe('2099-03-10')
  })

  it('markDone/isDone/taskStatus 一致', async () => {
    seedData('acct-A', { tasks: [task({ id: 'a', date: '2099-03-10', time: '09:00' })] })
    const { user, todo } = await boot()
    signIn(user, 'acct-A')
    const instance = todo.todoState.data.tasks[0]

    expect(todo.isDone('a', '2099-03-10')).toBe(false)
    expect(todo.taskStatus(instance, now)).toBe('in_progress')
    todo.markDone('a', now)
    expect(todo.isDone('a', '2099-03-10')).toBe(true)
    expect(todo.taskStatus(instance, now)).toBe('done')
  })

  it('没有任务时 dueDailyTasks 返回空(不因 Math.min 空参数抛错)', async () => {
    const { user, todo } = await boot()
    signIn(user, 'acct-A')
    expect(todo.dueDailyTasks(now)).toEqual([])
  })

describe('跨天结算 ensureToday', () => {
  it('首次进入只记下当天,不生成过期实例', async () => {
    const { user, todo } = await boot()
    signIn(user, 'acct-A')
    todo.ensureToday(new Date(2099, 2, 10, 8, 0))
    expect(todo.todoState.data.lastSeenDate).toBe('2099-03-10')
    expect(todo.todoState.data.expired).toEqual({})
  })

  it('同一天再次进入不改动(lastSeenDate >= today 直接返回)', async () => {
    seedData('acct-A', { lastSeenDate: '2099-03-10' })
    const { user, todo } = await boot()
    signIn(user, 'acct-A')
    todo.ensureToday(new Date(2099, 2, 10, 23, 0))
    expect(todo.todoState.data.expired).toEqual({})
  })

  it('跨天补记未完成的日程实例,跳过草稿/暂停/已完成', async () => {
    seedData('acct-A', {
      lastSeenDate: '2099-03-10',
      tasks: [
        task({ id: 'daily', date: '2099-03-09', repeat: 'daily', time: '09:00' }),
        task({ id: 'draft', date: '2099-03-09', repeat: 'daily', status: 'draft' }),
        task({ id: 'paused', date: '2099-03-09', repeat: 'daily', paused: true }),
        task({ id: 'done', date: '2099-03-09', repeat: 'daily' }),
      ],
      done: { 'done|2099-03-10': true },
    })
    const { user, todo } = await boot()
    signIn(user, 'acct-A')

    todo.ensureToday(new Date(2099, 2, 11, 7, 0))

    expect(todo.todoState.data.lastSeenDate).toBe('2099-03-11')
    expect(Object.keys(todo.todoState.data.expired).sort()).toEqual(['daily|2099-03-10'])
    expect(todo.todoState.data.expired['daily|2099-03-10']).toMatchObject({
      taskId: 'daily', date: '2099-03-10', time: '09:00', ack: false,
    })
    expect(stored('acct-A').expired['daily|2099-03-10']).toBeTruthy()
  })

  it('只回看最近 31 天,长期未打开也不会灌爆记录', async () => {
    seedData('acct-A', {
      lastSeenDate: '2099-01-01',
      tasks: [task({ id: 'daily', date: '2099-01-01', repeat: 'daily' })],
    })
    const { user, todo } = await boot()
    signIn(user, 'acct-A')
    todo.ensureToday(new Date(2099, 2, 10, 12, 0))
    const keys = Object.keys(todo.todoState.data.expired)
    expect(keys).toHaveLength(31)
    expect(keys).toContain('daily|2099-02-07')
    expect(keys).not.toContain('daily|2099-02-06')
  })

  it('超过 60 天的过期记录在结算时被清理', async () => {
    seedData('acct-A', {
      lastSeenDate: '2099-03-09',
      expired: {
        old: { taskId: 'x', content: 'c', date: '2098-12-01', time: '09:00', ack: true },
        fresh: { taskId: 'y', content: 'c', date: '2099-03-01', time: '09:00', ack: true },
      },
    })
    const { user, todo } = await boot()
    signIn(user, 'acct-A')
    todo.ensureToday(new Date(2099, 2, 10, 12, 0))
    expect(Object.keys(todo.todoState.data.expired)).toEqual(['fresh'])
  })
})

describe('过期提醒', () => {
  it('unackExpired 只列未确认的并按时间升序', async () => {
    seedData('acct-A', {
      lastSeenDate: '2099-03-10',
      expired: {
        b: { taskId: 'b', content: 'b', date: '2099-03-09', time: '18:00', ack: false },
        a: { taskId: 'a', content: 'a', date: '2099-03-08', time: '09:00', ack: false },
        c: { taskId: 'c', content: 'c', date: '2099-03-07', time: '09:00', ack: true },
      },
    })
    const { user, todo } = await boot()
    signIn(user, 'acct-A')
    expect(todo.unackExpired().map((e) => e.taskId)).toEqual(['a', 'b'])
  })

  it('allExpired 含已确认并按时间倒序', async () => {
    seedData('acct-A', {
      lastSeenDate: '2099-03-10',
      expired: {
        b: { taskId: 'b', content: 'b', date: '2099-03-09', time: '18:00', ack: false },
        a: { taskId: 'a', content: 'a', date: '2099-03-08', time: '09:00', ack: true },
      },
    })
    const { user, todo } = await boot()
    signIn(user, 'acct-A')
    expect(todo.allExpired().map((e) => e.taskId)).toEqual(['b', 'a'])
  })

  it('ackAllExpired 把全部标记为已确认并落盘', async () => {
    seedData('acct-A', {
      lastSeenDate: '2099-03-10',
      expired: {
        a: { taskId: 'a', content: 'a', date: '2099-03-08', time: '09:00', ack: false },
        b: { taskId: 'b', content: 'b', date: '2099-03-09', time: '09:00', ack: false },
      },
    })
    const { user, todo } = await boot()
    signIn(user, 'acct-A')
    todo.ackAllExpired()
    expect(todo.unackExpired()).toEqual([])
    expect(stored('acct-A').expired.a.ack).toBe(true)
  })
})

})


describe('工作区隔离', () => {
  it('切到科研区时先落盘学习区,再装载科研区的桶', async () => {
    const { user, todo } = await boot()
    signIn(user, 'acct-A')
    todo.saveTask({ content: '学习任务', date: '2099-01-01', time: '08:00', repeat: 'once', weekdays: [] })
    expect(stored('acct-A').tasks).toHaveLength(1)

    todo.setTodoWorkspace('research')
    expect(todo.todoState.data.tasks).toEqual([])
    todo.saveTask({ content: '科研任务', date: '2099-01-02', time: '09:00', repeat: 'once', weekdays: [] })
    expect(JSON.parse(memory.get('mg-todo:acct-A:research') ?? '{}').tasks).toHaveLength(1)

    todo.setTodoWorkspace('learn')
    expect(todo.todoState.data.tasks.map((t) => t.content)).toEqual(['学习任务'])
  })

  it('切换到当前工作区是空操作', async () => {
    const { user, todo } = await boot()
    signIn(user, 'acct-A')
    todo.saveTask({ content: 'a', date: '2099-01-01', time: '08:00', repeat: 'once', weekdays: [] })
    memory.delete('mg-todo:acct-A')
    todo.setTodoWorkspace('learn') // 已经是 learn,不应写盘
    expect(memory.has('mg-todo:acct-A')).toBe(false)
    expect(todo.todoState.data.tasks).toHaveLength(1)
  })
})

describe('清理与辅助展示', () => {
  it('clearAllTodoData 清掉所有桶与提醒标记', async () => {
    memory.set('mg-todo:acct-A', '{}')
    memory.set('mg-todo:acct-B', '{}')
    memory.set('mg-todo-notified:acct-A:2099-03-10', '1')
    memory.set('mg-other', 'keep')
    const { user, todo } = await boot()
    signIn(user, 'acct-A')

    todo.clearAllTodoData()

    // 登录态(mg-user)不属于待办数据,必须保留
    expect([...memory.keys()].sort()).toEqual(['mg-other', 'mg-user'])
    expect(todo.todoState.data.tasks).toEqual([])
    expect(todo.todoState.owner).toBe('acct-A')
  })

  it('notificationKey 带工作区后缀,学习区沿用旧格式', async () => {
    const { user, todo } = await boot()
    signIn(user, 'acct-A')
    const now = new Date(2099, 2, 10, 9, 0)
    expect(todo.notificationKey(now)).toBe('mg-todo-notified:acct-A:2099-03-10')
    todo.setTodoWorkspace('research')
    expect(todo.notificationKey(now)).toBe('mg-todo-notified:acct-A:research:2099-03-10')
  })

  it('未登录时 notificationKey 用 anon 占位', async () => {
    const { todo } = await boot()
    expect(todo.notificationKey(new Date(2099, 2, 10))).toBe('mg-todo-notified:anon:2099-03-10')
  })

  it('repeatLabel 中英文与周日排序(周日排最后)', async () => {
    const { todo } = await boot()
    const once = task({ repeat: 'once' })
    const daily = task({ repeat: 'daily' })
    const weekly = task({ repeat: 'weekly', weekdays: [0, 3, 1] })

    expect(todo.repeatLabel(once, false)).toBe('一次性')
    expect(todo.repeatLabel(once, true)).toBe('Once')
    expect(todo.repeatLabel(daily, false)).toBe('每天')
    expect(todo.repeatLabel(daily, true)).toBe('Daily')
    expect(todo.repeatLabel(weekly, false)).toBe('周期性 周一 周三 周日')
    expect(todo.repeatLabel(weekly, true)).toBe('Weekly Mon Wed Sun')
  })

  it('dueText 与 onceExpired', async () => {
    const { todo } = await boot()
    const once = task({ date: '2026-03-10', time: '09:30' })
    expect(todo.dueText(once)).toBe('2026/03/10 09:30')
    expect(todo.onceExpired(once, new Date(2026, 2, 11))).toBe(true)
    expect(todo.onceExpired(once, new Date(2026, 2, 10))).toBe(false)
    expect(todo.onceExpired(task({ repeat: 'daily' }), new Date(2026, 2, 11))).toBe(false)
  })

  it('onceExpired 对已完成的实例返回 false', async () => {
    const { user, todo } = await boot()
    signIn(user, 'acct-A')
    const created = todo.saveTask({ content: 'x', date: '2099-01-01', time: '08:00', repeat: 'once', weekdays: [] })
    todo.markDone(created.id, new Date(2099, 0, 1, 9, 0))
    expect(todo.onceExpired(created, new Date(2099, 0, 2))).toBe(false)
  })

  it('validateDraft 逐条校验并返回错误 key', async () => {
    const { todo } = await boot()
    const now = new Date(2099, 2, 10, 10, 0)
    const base = { content: '内容', date: '2099-03-11', time: '09:00', repeat: 'once' as const, weekdays: [] }

    expect(todo.validateDraft(base, now)).toBeNull()
    expect(todo.validateDraft({ ...base, content: '   ' }, now)).toBe('todo.errorContent')
    expect(todo.validateDraft({ ...base, time: '25:00' }, now)).toBe('todo.errorTime')
    expect(todo.validateDraft({ ...base, repeat: 'weekly', weekdays: [] }, now)).toBe('todo.errorWeekdays')
    expect(todo.validateDraft({ ...base, date: '2099-03-09' }, now)).toBe('todo.errorPast')
    expect(todo.validateDraft({ ...base, repeat: 'weekly', weekdays: [3] }, now)).toBeNull()
  })
})
