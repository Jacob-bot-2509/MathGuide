// @vitest-environment happy-dom
/**
 * 搜索范围 store 测试。
 *
 * 语义有三条硬约束:默认全选、至少保留一个平台、空选择等价于全平台
 * (后端同口径)。判错会让深度搜索静默不发请求,或者漏掉用户取消的平台。
 */
import { nextTick } from 'vue'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const KEY = 'mg-research-scope'
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
  return import('@/stores/researchScope')
}

async function settle() {
  await nextTick()
  await nextTick()
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
  it('没有存档时默认全平台', async () => {
    const scope = await boot()
    expect(scope.selectedSources.value).toEqual(scope.ALL_SOURCE_KEYS)
    expect(scope.isAllSelected()).toBe(true)
  })

  it('平台清单与后端白名单同口径且顺序固定', async () => {
    const scope = await boot()
    expect(scope.SOURCE_OPTIONS.map((s) => s.key)).toEqual([
      '知识库', 'arXiv', 'zbMATH', 'Semantic Scholar', 'OpenAlex', 'StackExchange',
    ])
    for (const option of scope.SOURCE_OPTIONS) {
      expect(option.label.length).toBeGreaterThan(0)
      expect(option.labelEn.length).toBeGreaterThan(0)
      expect(option.hint.length).toBeGreaterThan(0)
    }
  })

  it('脏 JSON / 非数组一律回退全平台', async () => {
    memory.set(KEY, '{oops')
    let scope = await boot()
    expect(scope.selectedSources.value).toEqual(scope.ALL_SOURCE_KEYS)

    vi.resetModules()
    memory.set(KEY, '"arXiv"')
    scope = await boot()
    expect(scope.selectedSources.value).toEqual(scope.ALL_SOURCE_KEYS)
  })

  it('过滤未知平台 key', async () => {
    memory.set(KEY, JSON.stringify(['arXiv', 'ghost', 42, 'OpenAlex']))
    const scope = await boot()
    expect(scope.selectedSources.value).toEqual(['arXiv', 'OpenAlex'])
    expect(scope.isAllSelected()).toBe(false)
  })

  it('存档为空数组时规范成全平台(避免面板显示一个都没勾)', async () => {
    memory.set(KEY, '[]')
    const scope = await boot()
    expect(scope.selectedSources.value).toEqual(scope.ALL_SOURCE_KEYS)
  })
})

describe('请求参数', () => {
  it('全平台时不传 scope(走后端默认全量)', async () => {
    const scope = await boot()
    expect(scope.scopeForRequest()).toBeUndefined()
  })

  it('缩小范围时返回副本', async () => {
    memory.set(KEY, JSON.stringify(['arXiv']))
    const scope = await boot()
    const request = scope.scopeForRequest()
    expect(request).toEqual(['arXiv'])
    expect(request).not.toBe(scope.selectedSources.value)
  })
})

describe('切换平台', () => {
  it('取消勾选保持面板顺序', async () => {
    const scope = await boot()
    scope.toggleSource('arXiv')
    expect(scope.selectedSources.value).toEqual(
      scope.ALL_SOURCE_KEYS.filter((k) => k !== 'arXiv'),
    )
    expect(scope.isAllSelected()).toBe(false)
  })

  it('重新勾选时按全量顺序插回原位', async () => {
    const scope = await boot()
    scope.onlySource('OpenAlex')
    scope.toggleSource('arXiv')
    expect(scope.selectedSources.value).toEqual(['arXiv', 'OpenAlex'])
    scope.toggleSource('知识库')
    expect(scope.selectedSources.value).toEqual(['知识库', 'arXiv', 'OpenAlex'])
  })

  it('至少保留一个平台:取消最后一个不生效', async () => {
    const scope = await boot()
    scope.onlySource('arXiv')
    scope.toggleSource('arXiv')
    expect(scope.selectedSources.value).toEqual(['arXiv'])
  })

  it('selectAllSources 恢复全平台;onlySource 只留一个', async () => {
    const scope = await boot()
    scope.onlySource('zbMATH')
    expect(scope.isAllSelected()).toBe(false)
    scope.selectAllSources()
    expect(scope.isAllSelected()).toBe(true)
    scope.onlySource('StackExchange')
    expect(scope.selectedSources.value).toEqual(['StackExchange'])
  })
})

describe('持久化', () => {
  it('选择变化后写入 localStorage(深监听)', async () => {
    const scope = await boot()
    scope.toggleSource('arXiv')
    await settle()
    expect(JSON.parse(memory.get(KEY) ?? '[]')).not.toContain('arXiv')

    scope.selectAllSources()
    await settle()
    expect(JSON.parse(memory.get(KEY) ?? '[]')).toEqual(scope.ALL_SOURCE_KEYS)
  })

  it('localStorage 不可写时只影响持久化,不影响本次会话', async () => {
    const scope = await boot()
    failWrites = true
    scope.onlySource('OpenAlex')
    await settle()
    expect(memory.has(KEY)).toBe(false)
    expect(scope.selectedSources.value).toEqual(['OpenAlex'])
    expect(scope.scopeForRequest()).toEqual(['OpenAlex'])
  })
})
