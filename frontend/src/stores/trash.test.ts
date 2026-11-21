// @vitest-environment happy-dom
/**
 * 回收站测试。
 *
 * 保留期 30 天是「可恢复」的承诺:少一天用户找不回,多一天就是隐私问题。
 * 另外恢复要写回原工作区的会话档案,不能都塞进学习区。
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const memory = new Map<string, string>()

function installStorage() {
  vi.stubGlobal('localStorage', {
    getItem: (key: string) => memory.get(key) ?? null,
    setItem: (key: string, value: string) => {
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

function seedTrash(items: unknown) {
  memory.set('mg-trash', JSON.stringify(items))
}

async function boot() {
  const trash = await import('@/stores/trash')
  const sessions = await import('@/stores/sessions')
  return { trash, sessions }
}

const DAY = 86400000

function item(patch: Record<string, unknown> = {}) {
  return {
    id: 1,
    question: '问题',
    answer: '回答',
    cat: { key: 'analysis', label: '数学分析', color: '#4dd6ff' },
    sessionId: 5,
    deletedAt: Date.now(),
    ...patch,
  }
}

beforeEach(() => {
  memory.clear()
  vi.resetModules()
  vi.unstubAllGlobals()
  installStorage()
})

afterEach(() => {
  vi.useRealTimers()
  vi.restoreAllMocks()
})

describe('daysLeft', () => {
  it('刚删除显示 30 天,越接近过期越小', async () => {
    const { trash } = await boot()
    const now = Date.now()
    expect(trash.daysLeft(now)).toBe(30)
    expect(trash.daysLeft(now - 10 * DAY)).toBe(20)
    expect(trash.daysLeft(now - 29.5 * DAY)).toBe(1)
  })

  it('已过期显示 0 而不是负数', async () => {
    const { trash } = await boot()
    expect(trash.daysLeft(Date.now() - 40 * DAY)).toBe(0)
    expect(trash.daysLeft(0)).toBe(0)
  })
})


describe('加载与清理', () => {
  it('没有存档时是空列表', async () => {
    const { trash } = await boot()
    expect(trash.trashState.items).toEqual([])
  })

  it('脏 JSON 回退空列表', async () => {
    memory.set('mg-trash', '{not json')
    const { trash } = await boot()
    expect(trash.trashState.items).toEqual([])
  })

  it('导入时自动清理超过 30 天的记录并回写', async () => {
    const now = Date.now()
    seedTrash([
      item({ id: 1, deletedAt: now }),
      item({ id: 2, deletedAt: now - 31 * DAY }),
      item({ id: 3, deletedAt: now - 40 * DAY }),
    ])
    const { trash } = await boot()
    expect(trash.trashState.items.map((t) => t.id)).toEqual([1])
    expect(JSON.parse(memory.get('mg-trash') ?? '[]').map((t: { id: number }) => t.id)).toEqual([1])
  })

  it('没有超期记录时不写盘', async () => {
    seedTrash([item({ id: 1, deletedAt: Date.now() })])
    const before = memory.get('mg-trash')
    await boot()
    expect(memory.get('mg-trash')).toBe(before)
  })
})

describe('增删查', () => {
  it('addToTrash 插到最前并落盘', async () => {
    const { trash } = await boot()
    trash.addToTrash(item({ id: 1 }))
    trash.addToTrash(item({ id: 2 }))
    expect(trash.trashState.items.map((t) => t.id)).toEqual([2, 1])
    expect(JSON.parse(memory.get('mg-trash') ?? '[]')).toHaveLength(2)
  })

  it('removeFromTrash 按 id 移除并落盘', async () => {
    const { trash } = await boot()
    trash.addToTrash(item({ id: 1 }))
    trash.addToTrash(item({ id: 2 }))
    trash.removeFromTrash(1)
    expect(trash.trashState.items.map((t) => t.id)).toEqual([2])
    expect(JSON.parse(memory.get('mg-trash') ?? '[]').map((t: { id: number }) => t.id)).toEqual([2])
  })

  it('purgeExpired 只保留保留期内的记录,重复调用无副作用', async () => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2099-03-10T00:00:00'))
    const now = Date.now()
    const { trash } = await boot()
    trash.trashState.items = [
      item({ id: 1, deletedAt: now }),
      item({ id: 2, deletedAt: now - 31 * DAY }),
    ]
    trash.purgeExpired()
    expect(trash.trashState.items.map((t) => t.id)).toEqual([1])
    const snapshot = memory.get('mg-trash')
    trash.purgeExpired()
    expect(memory.get('mg-trash')).toBe(snapshot)
  })

  it('恰好到保留期边界的那一天仍然保留(与 daysLeft=0 同口径)', async () => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2099-03-10T00:00:00'))
    const now = Date.now()
    const { trash } = await boot()
    trash.trashState.items = [item({ id: 1, deletedAt: now - 30 * DAY })]
    expect(trash.daysLeft(now - 30 * DAY)).toBe(0)
    trash.purgeExpired()
    expect(trash.trashState.items.map((t) => t.id)).toEqual([1])
  })

  it('写盘异常不影响内存操作(隐私模式)', async () => {
    const { trash } = await boot()
    const setItem = vi.fn(() => {
      throw new Error('quota')
    })
    vi.stubGlobal('localStorage', { ...(globalThis.localStorage as object), setItem })
    expect(() => trash.addToTrash(item({ id: 3 }))).not.toThrow()
    expect(trash.trashState.items.map((t) => t.id)).toEqual([3])
  })

  it('clearTrash 清空内存与 localStorage', async () => {
    const { trash } = await boot()
    trash.addToTrash(item({ id: 1 }))
    trash.clearTrash()
    expect(trash.trashState.items).toEqual([])
    expect(memory.has('mg-trash')).toBe(false)
  })

describe('恢复', () => {
  it('恢复到原会话(学习区),并从回收站移除', async () => {
    const { trash, sessions } = await boot()
    const learn = sessions.sessionStore('learn')
    learn.state.sessions = [{ id: 5, messages: [] }]
    trash.addToTrash(item({ id: 1, sessionId: 5 }))

    expect(trash.restoreTrashItem(1)).toBe(true)

    expect(trash.trashState.items).toEqual([])
    expect(learn.state.sessions[0].messages.map((m) => m.content)).toEqual(['问题', '回答'])
  })

  it('旧记录没有 workspace 字段时按学习区处理', async () => {
    const { trash, sessions } = await boot()
    sessions.sessionStore('learn').state.sessions = []
    sessions.sessionStore('research').state.sessions = []
    trash.addToTrash(item({ id: 7, sessionId: 42, workspace: undefined }))

    expect(trash.restoreTrashItem(7)).toBe(true)
    expect(sessions.sessionStore('learn').state.sessions[0].id).toBe(42)
    expect(sessions.sessionStore('research').state.sessions).toEqual([])
  })

  it('workspace=research 的记录写回科研区', async () => {
    const { trash, sessions } = await boot()
    sessions.sessionStore('learn').state.sessions = []
    sessions.sessionStore('research').state.sessions = []
    trash.addToTrash(item({ id: 8, sessionId: 11, workspace: 'research' }))

    expect(trash.restoreTrashItem(8)).toBe(true)
    expect(sessions.sessionStore('research').state.sessions[0].id).toBe(11)
    expect(sessions.sessionStore('learn').state.sessions).toEqual([])
  })

  it('id 不存在时返回 false 且不动数据', async () => {
    const { trash } = await boot()
    trash.addToTrash(item({ id: 1 }))
    expect(trash.restoreTrashItem(99)).toBe(false)
    expect(trash.trashState.items).toHaveLength(1)
  })

  it('保留期常量与一天毫秒数可被视图复用', async () => {
    const { trash } = await boot()
    expect(trash.TRASH_RETENTION_DAYS).toBe(30)
    expect(trash.DAY_MS).toBe(DAY)
  })
})

})
