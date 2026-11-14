// @vitest-environment happy-dom
/**
 * 问题记录(归纳本)store 测试。
 *
 * 归纳本是「温故知新」的唯一凭据:截断上限、200 条上限与工作区隔离都要钉住,
 * 否则长题解会被截掉关键步骤,或者学习区看到科研区的记录。
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
  return import('@/stores/notebook')
}

function stored(key: string): Array<Record<string, unknown>> {
  const raw = memory.get(key)
  return raw ? JSON.parse(raw) : []
}

beforeEach(() => {
  memory.clear()
  failWrites = false
  vi.resetModules()
  vi.unstubAllGlobals()
  installStorage()
})

afterEach(() => {
  vi.restoreAllMocks()
})

describe('加载', () => {
  it('没有存档时两个工作区都是空的', async () => {
    const notebook = await boot()
    expect(notebook.notebookStore('learn').state.entries).toEqual([])
    expect(notebook.notebookStore('research').state.entries).toEqual([])
  })

  it('脏 JSON / 非数组回退空列表', async () => {
    memory.set('mg-notebook', '{oops')
    let notebook = await boot()
    expect(notebook.notebookStore('learn').state.entries).toEqual([])

    vi.resetModules()
    memory.set('mg-notebook', '{"entries":[]}')
    notebook = await boot()
    expect(notebook.notebookStore('learn').state.entries).toEqual([])
  })

  it('学习区沿用旧键,科研区用独立键(升级不丢历史)', async () => {
    memory.set('mg-notebook', JSON.stringify([{ id: 1, question: 'q1', answer: 'a1', sessionId: 1, msgId: 1, createdAt: 1 }]))
    memory.set('mg-research-notebook', JSON.stringify([{ id: 2, question: 'q2', answer: 'a2', sessionId: 2, msgId: 2, createdAt: 2 }]))
    const notebook = await boot()
    expect(notebook.notebookStore('learn').state.entries[0].id).toBe(1)
    expect(notebook.notebookStore('research').state.entries[0].id).toBe(2)
    expect(notebook.notebookState).toBe(notebook.notebookStore('learn').state)
  })
})


describe('addEntry', () => {
  it('写入条目并落盘,返回 true', async () => {
    const notebook = await boot()
    const ok = notebook.notebookStore('learn').addEntry('题目', '解答', 3, 4)
    expect(ok).toBe(true)
    const [entry] = stored('mg-notebook')
    expect(entry).toMatchObject({ question: '题目', answer: '解答', sessionId: 3, msgId: 4 })
    expect(typeof entry.id).toBe('number')
    expect(typeof entry.createdAt).toBe('number')
  })

  it('题目截断 400 字、解答截断 3000 字', async () => {
    const notebook = await boot()
    notebook.notebookStore('learn').addEntry('q'.repeat(500), 'a'.repeat(4000), 1, 1)
    const [entry] = notebook.notebookStore('learn').state.entries
    expect(entry.question).toHaveLength(400)
    expect(entry.answer).toHaveLength(3000)
  })

  it('落盘只保留最近 200 条(内存不裁剪)', async () => {
    const notebook = await boot()
    const store = notebook.notebookStore('learn')
    store.state.entries = Array.from({ length: 199 }, (_, i) => ({
      id: i + 1, question: 'q', answer: 'a', sessionId: 1, msgId: 1, createdAt: i,
    }))
    store.addEntry('新题', '新解', 2, 2)

    expect(store.state.entries).toHaveLength(200)
    const saved = stored('mg-notebook')
    expect(saved).toHaveLength(200)
    expect(saved.at(-1)?.question).toBe('新题')
  })

  it('写盘失败时返回 false,内存仍保留条目', async () => {
    const notebook = await boot()
    failWrites = true
    const store = notebook.notebookStore('learn')
    expect(store.addEntry('q', 'a', 1, 1)).toBe(false)
    expect(store.state.entries).toHaveLength(1)
    expect(memory.has('mg-notebook')).toBe(false)
  })

  it('两个工作区互不可见', async () => {
    const notebook = await boot()
    notebook.notebookStore('learn').addEntry('学习题', 'a', 1, 1)
    notebook.notebookStore('research').addEntry('科研题', 'a', 2, 2)

    expect(notebook.notebookStore('learn').state.entries.map((e) => e.question)).toEqual(['学习题'])
    expect(notebook.notebookStore('research').state.entries.map((e) => e.question)).toEqual(['科研题'])
    expect(stored('mg-notebook')).toHaveLength(1)
    expect(stored('mg-research-notebook')).toHaveLength(1)
  })
})

describe('删除与清空', () => {
  it('removeEntry 按 id 删除并落盘', async () => {
    const notebook = await boot()
    const store = notebook.notebookStore('learn')
    store.addEntry('a', 'a', 1, 1)
    store.addEntry('b', 'b', 2, 2)
    const first = store.state.entries[0]

    store.removeEntry(first.id)

    expect(store.state.entries.map((e) => e.question)).toEqual(['b'])
    expect(stored('mg-notebook').map((e) => e.question)).toEqual(['b'])
  })

  it('删除不存在的 id 不影响数据', async () => {
    const notebook = await boot()
    const store = notebook.notebookStore('learn')
    store.addEntry('a', 'a', 1, 1)
    store.removeEntry(999)
    expect(store.state.entries).toHaveLength(1)
  })

  it('clear 清空该工作区并移除键', async () => {
    const notebook = await boot()
    const store = notebook.notebookStore('learn')
    store.addEntry('a', 'a', 1, 1)
    store.clear()
    expect(store.state.entries).toEqual([])
    expect(memory.has('mg-notebook')).toBe(false)
  })

  it('clearNotebook 清空两个工作区', async () => {
    const notebook = await boot()
    notebook.notebookStore('learn').addEntry('a', 'a', 1, 1)
    notebook.notebookStore('research').addEntry('b', 'b', 2, 2)

    notebook.clearNotebook()

    expect(memory.has('mg-notebook')).toBe(false)
    expect(memory.has('mg-research-notebook')).toBe(false)
    expect(notebook.notebookStore('learn').state.entries).toEqual([])
    expect(notebook.notebookStore('research').state.entries).toEqual([])
  })

  it('兼容导出指向学习区', async () => {
    const notebook = await boot()
    expect(notebook.notebookState).toBe(notebook.notebookStore('learn').state)
    notebook.addNotebookEntry('旧引用题', 'a', 7, 8)
    expect(notebook.notebookState.entries.map((e) => e.question)).toEqual(['旧引用题'])
    notebook.removeNotebookEntry(notebook.notebookState.entries[0].id)
    expect(notebook.notebookState.entries).toEqual([])
  })
})
