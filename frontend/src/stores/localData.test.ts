// @vitest-environment happy-dom
/**
 * 本机数据清理/认领测试。
 *
 * 这是「换账号不串数据」的唯一防线:
 *   - 登录时若本机数据属于另一个 accountKey,必须先清空;
 *   - 同账号重登(401 后)不能误清;
 *   - 旧版本升级(没有归属标记)只能认领,不能删历史。
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const OWNER_KEY = 'mg-data-owner'
const memory = new Map<string, string>()
let readThrows = false

function installStorage() {
  vi.stubGlobal('localStorage', {
    getItem: (key: string) => {
      if (readThrows) throw new Error('SecurityError')
      return memory.get(key) ?? null
    },
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

const USER_DATA_KEYS = [
  'mg-learn-sessions',
  'mg-research-sessions',
  'mg-trash',
  'mg-notebook',
  'mg-research-notebook',
  'mg-speechmath-cache',
  'mg-research-archive',
]

function seedLocalData() {
  for (const key of USER_DATA_KEYS) memory.set(key, '[]')
}

async function boot() {
  return import('@/stores/localData')
}

beforeEach(() => {
  memory.clear()
  readThrows = false
  vi.resetModules()
  vi.unstubAllGlobals()
  installStorage()
})

afterEach(() => {
  vi.restoreAllMocks()
})

describe('clearLearningData', () => {
  it('清空会话/回收站/归纳本/语音缓存与归属标记,保留无关数据', async () => {
    seedLocalData()
    memory.set(OWNER_KEY, 'acct-A')
    memory.set('mg-settings', '{"language":"en"}')
    const localData = await boot()

    localData.clearLearningData()

    for (const key of USER_DATA_KEYS) {
      if (key === 'mg-research-archive') continue // 档案本体保留,只标记归属
      expect(memory.has(key), key).toBe(false)
    }
    expect(memory.has(OWNER_KEY)).toBe(false)
    expect(memory.get('mg-settings')).toBe('{"language":"en"}')
  })

  it('清理旧研究档案前先补记归属,避免换账号后误导入', async () => {
    memory.set(OWNER_KEY, 'acct-A')
    memory.set('mg-research-archive', '{"projects":[]}')
    const localData = await boot()

    localData.clearLearningData()

    expect(memory.get('mg-research-archive-owner')).toBe('acct-A')
  })

  it('已有归属标记时不覆盖', async () => {
    memory.set(OWNER_KEY, 'acct-A')
    memory.set('mg-research-archive', '{"projects":[]}')
    memory.set('mg-research-archive-owner', 'acct-B')
    const localData = await boot()

    localData.clearLearningData()

    expect(memory.get('mg-research-archive-owner')).toBe('acct-B')
  })

  it('没有归属标记或没有档案时不做任何标记', async () => {
    memory.set('mg-research-archive', '{"projects":[]}')
    const localData = await boot()

    localData.clearLearningData()

    expect(memory.has('mg-research-archive-owner')).toBe(false)
  })
})

describe('claimLocalData', () => {
  it('没有 accountKey 时直接返回,不动任何数据', async () => {
    seedLocalData()
    const localData = await boot()

    localData.claimLocalData()

    for (const key of USER_DATA_KEYS) expect(memory.has(key), key).toBe(true)
    expect(memory.has(OWNER_KEY)).toBe(false)
  })

  it('首次认领(旧版本升级)只写标记,不删历史', async () => {
    seedLocalData()
    const localData = await boot()

    localData.claimLocalData('acct-A')

    expect(memory.get(OWNER_KEY)).toBe('acct-A')
    for (const key of USER_DATA_KEYS) expect(memory.has(key), key).toBe(true)
  })

  it('同一账号重登时保留本机数据(401 回登录页不能丢历史)', async () => {
    memory.set(OWNER_KEY, 'acct-A')
    seedLocalData()
    const localData = await boot()

    localData.claimLocalData('acct-A')

    for (const key of USER_DATA_KEYS) expect(memory.has(key), key).toBe(true)
    expect(memory.get(OWNER_KEY)).toBe('acct-A')
  })

  it('换账号时先清空上一位用户的本机数据', async () => {
    memory.set(OWNER_KEY, 'acct-A')
    seedLocalData()
    const localData = await boot()

    localData.claimLocalData('acct-B')

    expect(memory.get(OWNER_KEY)).toBe('acct-B')
    for (const key of USER_DATA_KEYS) {
      if (key === 'mg-research-archive') continue
      expect(memory.has(key), key).toBe(false)
    }
  })

  it('读取归属标记失败时保守退出(不清数据也不写标记)', async () => {
    seedLocalData()
    readThrows = true
    const localData = await boot()

    expect(() => localData.claimLocalData('acct-A')).not.toThrow()
    readThrows = false
    for (const key of USER_DATA_KEYS) expect(memory.has(key), key).toBe(true)
    expect(memory.has(OWNER_KEY)).toBe(false)
  })

  it('换账号清理时同时清掉旧研究档案的归属链', async () => {
    memory.set(OWNER_KEY, 'acct-A')
    memory.set('mg-research-archive', '{"projects":[]}')
    const localData = await boot()

    localData.claimLocalData('acct-B')

    expect(memory.get('mg-research-archive-owner')).toBe('acct-A')
    expect(memory.get(OWNER_KEY)).toBe('acct-B')
  })
})
