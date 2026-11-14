// @vitest-environment happy-dom
/**
 * 会话档案 store 测试。
 *
 * 这里守着「用户的聊天记录」:写坏一次就是历史全丢或串号。逐项钉住:
 *   1. 脏数据/半截数据容错(形状校验 + 图解二次解析);
 *   2. 写盘 debounce 与 flush(关页面时不能丢掉最后一次变更);
 *   3. 配额失败保留上一次完整存档,并只提示一次;
 *   4. 会话数上限 20、消息数上限 120。
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

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
  const sessions = await import('@/stores/sessions')
  const toast = await import('@/utils/toast')
  toast.toast.msg = ''
  return { sessions, toast }
}

function seed(key: string, value: unknown) {
  memory.set(key, typeof value === 'string' ? value : JSON.stringify(value))
}

function stored(key: string) {
  const raw = memory.get(key)
  return raw ? JSON.parse(raw) : null
}

const msg = (id: number, content = `m${id}`) => ({ id, role: 'user' as const, content })

beforeEach(() => {
  memory.clear()
  failWrites = false
  vi.resetModules()
  vi.unstubAllGlobals()
  installStorage()
})

afterEach(() => {
  vi.useRealTimers()
  vi.restoreAllMocks()
})


describe('加载 / 脏数据容错', () => {
  it('没有存档时是空状态', async () => {
    const { sessions } = await boot()
    expect(sessions.sessionStore('learn').state).toEqual({
      sessions: [], activeId: 0, msgId: 0, sessionId: 0,
    })
  })

  it('JSON 损坏或形状不对时回退空档案', async () => {
    seed('mg-learn-sessions', '{oops')
    let booted = await boot()
    expect(booted.sessions.sessionStore('learn').state.sessions).toEqual([])

    vi.resetModules()
    seed('mg-learn-sessions', { sessions: 'not-an-array' })
    booted = await boot()
    expect(booted.sessions.sessionStore('learn').state.sessions).toEqual([])
  })

  it('过滤不可渲染的会话/消息,并回填数值默认值', async () => {
    seed('mg-learn-sessions', {
      sessions: [
        { id: 1, messages: [msg(1), null, 'x'] },
        { id: 2, messages: 'broken' },
        null,
        { id: 3, messages: [msg(2)] },
      ],
      activeId: 'x',
      msgId: null,
      sessionId: 9.5,
    })
    const { sessions } = await boot()
    const state = sessions.sessionStore('learn').state
    expect(state.sessions.map((s) => s.id)).toEqual([1, 3])
    expect(state.sessions[0].messages).toHaveLength(1)
    expect(state.activeId).toBe(0)
    expect(state.msgId).toBe(0)
    expect(state.sessionId).toBe(9.5)
  })

  it('pointId 截断到 64 字符,非字符串丢弃', async () => {
    seed('mg-learn-sessions', {
      sessions: [
        { id: 1, pointId: 'p'.repeat(100), messages: [] },
        { id: 2, pointId: 42, messages: [] },
      ],
    })
    const { sessions } = await boot()
    const [first, second] = sessions.sessionStore('learn').state.sessions
    expect(first.pointId).toHaveLength(64)
    expect(second.pointId).toBeUndefined()
  })

  it('图解二次校验:合法保留,非法丢弃,全空时不留字段', async () => {
    const validSpec = { type: 'tree', nodes: [{ id: 'a', label: 'A' }] }
    seed('mg-learn-sessions', {
      sessions: [{
        id: 1,
        messages: [
          { id: 1, role: 'assistant', content: 'ok', diagrams: [{ id: ' d1 ', anchorIndex: 0, spec: validSpec }] },
          { id: 2, role: 'assistant', content: 'bad', diagrams: [{ id: '', anchorIndex: 0, spec: validSpec }] },
          { id: 3, role: 'assistant', content: 'bad2', diagrams: [{ id: 'd2', anchorIndex: -1, spec: validSpec }] },
          { id: 4, role: 'assistant', content: 'bad3', diagrams: [{ id: 'd3', anchorIndex: 0, spec: { type: 'nope' } }] },
          { id: 5, role: 'assistant', content: 'none', diagrams: [{ id: 'd4', anchorIndex: 0, spec: null }] },
          { id: 6, role: 'assistant', content: 'not-array', diagrams: 'x' },
        ],
      }],
    })
    const { sessions } = await boot()
    const messages = sessions.sessionStore('learn').state.sessions[0].messages
    expect(messages[0].diagrams).toHaveLength(1)
    expect(messages[0].diagrams?.[0].id).toBe('d1')
    for (const message of messages.slice(1)) {
      expect(message.diagrams).toBeUndefined()
    }
  })

  it('两个工作区各自独立加载', async () => {
    seed('mg-learn-sessions', { sessions: [{ id: 1, messages: [] }], activeId: 1, msgId: 0, sessionId: 1 })
    seed('mg-research-sessions', { sessions: [{ id: 7, messages: [] }], activeId: 7, msgId: 0, sessionId: 7 })
    const { sessions } = await boot()
    expect(sessions.sessionStore('learn').state.sessions[0].id).toBe(1)
    expect(sessions.sessionStore('research').state.sessions[0].id).toBe(7)
    expect(sessions.sessionStore('learn').workspace).toBe('learn')
  })
})

describe('id 分配', () => {
  it('nextMsgId / nextSessionId 单调递增(从存档里的最大值继续)', async () => {
    seed('mg-learn-sessions', { sessions: [], activeId: 0, msgId: 41, sessionId: 7 })
    const { sessions } = await boot()
    const store = sessions.sessionStore('learn')
    expect(store.nextMsgId()).toBe(42)
    expect(store.nextMsgId()).toBe(43)
    expect(store.nextSessionId()).toBe(8)
  })

describe('写盘:debounce 与 flush', () => {
  beforeEach(() => {
    vi.useFakeTimers()
  })

  it('persistSessions 合并写盘(120ms 内多次只写一次)', async () => {
    const { sessions } = await boot()
    const store = sessions.sessionStore('learn')
    store.state.sessions = [{ id: 1, messages: [msg(1)] }]

    store.persistSessions()
    store.persistSessions()
    expect(memory.has('mg-learn-sessions')).toBe(false)
    vi.advanceTimersByTime(119)
    expect(memory.has('mg-learn-sessions')).toBe(false)
    vi.advanceTimersByTime(1)
    expect(stored('mg-learn-sessions').sessions[0].id).toBe(1)
  })

  it('flushSessions 立即写盘,并在之后取消待执行的 debounce', async () => {
    const { sessions } = await boot()
    const store = sessions.sessionStore('learn')
    store.state.sessions = [{ id: 1, messages: [msg(1)] }]

    expect(store.persistSessions()).toBe(true)
    expect(store.flushSessions()).toBe(true)
    expect(stored('mg-learn-sessions').sessions).toHaveLength(1)

    store.state.sessions.push({ id: 2, messages: [msg(2)] })
    vi.advanceTimersByTime(500)
    // 没有新的 persist 调用 → 定时器不会自己再写
    expect(stored('mg-learn-sessions').sessions).toHaveLength(1)
  })

  it('没有待写内容时 flush 不落盘,force 才写', async () => {
    const { sessions } = await boot()
    const store = sessions.sessionStore('learn')
    store.state.activeId = 5

    expect(store.flushSessions()).toBe(true)
    expect(memory.has('mg-learn-sessions')).toBe(false)
    expect(store.flushSessions(true)).toBe(true)
    expect(stored('mg-learn-sessions').activeId).toBe(5)
  })

  it('只持久化白名单字段,消息数上限 120', async () => {
    const { sessions } = await boot()
    const store = sessions.sessionStore('learn')
    const messages = Array.from({ length: 130 }, (_, i) => ({
      ...msg(i + 1),
      streaming: true, // 瞬态字段,不落盘
    }))
    store.state.sessions = [{ id: 1, messages }]
    store.flushSessions(true)

    const saved = stored('mg-learn-sessions').sessions[0]
    expect(saved.messages).toHaveLength(120)
    expect(saved.messages[0].id).toBe(11)
    expect(saved.messages[0]).not.toHaveProperty('streaming')
  })

  it('写盘失败时保留上次存档并只提示一次', async () => {
    const { sessions, toast } = await boot()
    const store = sessions.sessionStore('learn')
    store.state.sessions = [{ id: 1, messages: [msg(1)] }]
    store.flushSessions(true)
    const snapshot = memory.get('mg-learn-sessions')

    failWrites = true
    expect(store.persistSessions()).toBe(true) // 返回的是「上一次」结果
    expect(store.flushSessions()).toBe(false)
    expect(memory.get('mg-learn-sessions')).toBe(snapshot)
    expect(toast.toast.msg).not.toBe('')

    // 连续失败不再重复弹提示
    toast.toast.msg = ''
    store.persistSessions()
    store.flushSessions()
    expect(toast.toast.msg).toBe('')

    // 恢复写入后重新成功
    failWrites = false
    store.state.sessions.push({ id: 2, messages: [msg(2)] })
    expect(store.flushSessions(true)).toBe(true)
    expect(stored('mg-learn-sessions').sessions).toHaveLength(2)
  })

  it('beforeunload 时把待写内容落盘', async () => {
    const { sessions } = await boot()
    const store = sessions.sessionStore('learn')
    store.state.sessions = [{ id: 1, messages: [msg(1)] }]
    store.persistSessions()

    window.dispatchEvent(new Event('beforeunload'))
    expect(stored('mg-learn-sessions').sessions).toHaveLength(1)
  })
})


describe('回收站恢复 restorePair', () => {
  beforeEach(() => {
    vi.useFakeTimers()
  })

  it('原会话存在时直接追加一问一答', async () => {
    const { sessions } = await boot()
    const store = sessions.sessionStore('learn')
    store.state.sessions = [{ id: 3, cat: { key: 'analysis', label: '数学分析', color: '#4dd6ff' }, messages: [] }]
    store.state.msgId = 10

    store.restorePair({
      sessionId: 3,
      question: '问题',
      answer: '回答',
      cat: { key: 'analysis', label: '数学分析', color: '#4dd6ff' },
    })

    const target = store.state.sessions[0]
    expect(target.messages.map((m) => [m.id, m.role, m.content])).toEqual([
      [11, 'user', '问题'],
      [12, 'assistant', '回答'],
    ])
    vi.advanceTimersByTime(120)
    expect(stored('mg-learn-sessions').sessions[0].messages).toHaveLength(2)
  })

  it('原会话已删除时按原板块重建,并把 sessionId 推高', async () => {
    const { sessions } = await boot()
    const store = sessions.sessionStore('learn')
    store.state.sessionId = 2

    store.restorePair({
      sessionId: 9,
      question: 'q',
      answer: 'a',
      cat: { key: 'algebra', label: '高等代数', color: '#8b5cf6' },
    })

    expect(store.state.sessions).toHaveLength(1)
    expect(store.state.sessions[0].cat?.key).toBe('algebra')
    expect(store.state.sessionId).toBe(9)
  })

  it('重建时超过上限 20 会挤掉最旧的会话', async () => {
    const { sessions } = await boot()
    const store = sessions.sessionStore('learn')
    store.state.sessions = Array.from({ length: 20 }, (_, i) => ({ id: i + 1, messages: [] }))

    store.restorePair({ sessionId: 99, question: 'q', answer: 'a', cat: undefined })

    expect(store.state.sessions).toHaveLength(20)
    expect(store.state.sessions[0].id).toBe(2)
    expect(store.state.sessions.at(-1)?.id).toBe(99)
  })
})

describe('清理', () => {
  beforeEach(() => {
    vi.useFakeTimers()
  })

  it('clear 取消待写定时器,不会把旧档案写回去', async () => {
    const { sessions } = await boot()
    const store = sessions.sessionStore('learn')
    store.state.sessions = [{ id: 1, messages: [msg(1)] }]
    store.persistSessions()

    store.clear()
    vi.advanceTimersByTime(500)

    expect(store.state.sessions).toEqual([])
    expect(store.state.activeId).toBe(0)
    expect(memory.has('mg-learn-sessions')).toBe(false)
  })

  it('clearAllSessions 清空两个工作区', async () => {
    seed('mg-learn-sessions', { sessions: [{ id: 1, messages: [] }], activeId: 1, msgId: 0, sessionId: 1 })
    seed('mg-research-sessions', { sessions: [{ id: 2, messages: [] }], activeId: 2, msgId: 0, sessionId: 2 })
    const { sessions } = await boot()

    sessions.clearAllSessions()

    expect(memory.has('mg-learn-sessions')).toBe(false)
    expect(memory.has('mg-research-sessions')).toBe(false)
    expect(sessions.sessionStore('learn').state.sessions).toEqual([])
    expect(sessions.sessionStore('research').state.sessions).toEqual([])
  })

  it('兼容导出指向学习区', async () => {
    const { sessions } = await boot()
    expect(sessions.sessionsState).toBe(sessions.sessionStore('learn').state)
    expect(sessions.nextMsgId()).toBe(1)
    expect(sessions.nextSessionId()).toBe(1)
    expect(sessions.persistSessions()).toBe(true)
    expect(sessions.flushSessions(true)).toBe(true)

    sessions.restorePair({ sessionId: 1, question: 'q', answer: 'a', cat: undefined })
    expect(sessions.sessionStore('learn').state.sessions[0].messages).toHaveLength(2)
  })

  it('MAX_SESSIONS 常量为 20', async () => {
    const { sessions } = await boot()
    expect(sessions.MAX_SESSIONS).toBe(20)
    expect(sessions.SESSIONS_KEYS).toEqual({
      learn: 'mg-learn-sessions',
      research: 'mg-research-sessions',
    })
  })
})

})
