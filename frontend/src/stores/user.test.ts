// @vitest-environment happy-dom
/**
 * 用户登录态 store 测试。
 *
 * localStorage 里的 mg-user 是刷新后唯一的登录凭据:读坏必须降级为「未登录」
 * (而不是抛错白屏),写坏也不能影响本次会话。
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const KEY = 'mg-user'
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

const USER = {
  accountKey: 'acct-A',
  nickname: '小明',
  avatar: 'preset:sum',
  authMethod: 'wechat' as const,
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
  it('没有存档时未登录', async () => {
    const user = await import('@/stores/user')
    expect(user.userState.info).toBeNull()
    expect(user.isLoggedIn()).toBe(false)
    expect(user.getToken()).toBeUndefined()
  })

  it('有存档时直接登录,并能取到 token', async () => {
    memory.set(KEY, JSON.stringify({ ...USER, token: 'tk-1' }))
    const user = await import('@/stores/user')
    expect(user.isLoggedIn()).toBe(true)
    expect(user.getToken()).toBe('tk-1')
  })

  it('脏 JSON 降级为未登录,不抛错', async () => {
    memory.set(KEY, '{oops')
    const user = await import('@/stores/user')
    expect(user.userState.info).toBeNull()
  })
})

describe('login / logout', () => {
  it('登录写入内存与 localStorage', async () => {
    const user = await import('@/stores/user')
    user.login({ ...USER, token: 'tk-2' })
    expect(user.isLoggedIn()).toBe(true)
    expect(JSON.parse(memory.get(KEY) ?? '{}')).toMatchObject({ accountKey: 'acct-A', token: 'tk-2' })
  })

  it('写盘失败时仅在本次会话有效', async () => {
    const user = await import('@/stores/user')
    failWrites = true
    expect(() => user.login({ ...USER, token: 'tk-3' })).not.toThrow()
    expect(user.getToken()).toBe('tk-3')
    expect(memory.has(KEY)).toBe(false)
  })

  it('logout 清空内存与存档', async () => {
    const user = await import('@/stores/user')
    user.login({ ...USER, token: 'tk-4' })
    user.logout()
    expect(user.userState.info).toBeNull()
    expect(memory.has(KEY)).toBe(false)
  })
})

describe('updateUser', () => {
  it('未登录时是空操作(不写盘)', async () => {
    const user = await import('@/stores/user')
    user.updateUser({ nickname: '新名字' })
    expect(user.userState.info).toBeNull()
    expect(memory.has(KEY)).toBe(false)
  })

  it('已登录时合并字段并持久化', async () => {
    const user = await import('@/stores/user')
    user.login({ ...USER, token: 'tk-5' })

    user.updateUser({ nickname: '新名字', realName: { name: '张三', idMasked: '110***********1234' } })

    expect(user.userState.info?.nickname).toBe('新名字')
    expect(user.userState.info?.realName?.name).toBe('张三')
    // 未提及的字段保持不变
    expect(user.getToken()).toBe('tk-5')
    expect(JSON.parse(memory.get(KEY) ?? '{}').nickname).toBe('新名字')
  })

  it('写盘失败不影响内存', async () => {
    const user = await import('@/stores/user')
    user.login({ ...USER, token: 'tk-6' })
    failWrites = true
    expect(() => user.updateUser({ avatar: 'preset:int' })).not.toThrow()
    expect(user.userState.info?.avatar).toBe('preset:int')
  })
})
