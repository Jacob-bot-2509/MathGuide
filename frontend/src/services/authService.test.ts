/**
 * 会话恢复(vitest):`/api/auth/session` 回来之后本地登录态有没有被正确处理。
 *
 * 三条断言对应三个真实故障:
 *   1. 服务端没轮换 → 必须保留原有 token(旧实现会被 res.user 覆盖成 undefined,
 *      之后所有请求悄悄退化成纯 Cookie 鉴权);
 *   2. 服务端轮换了 → 内存与 localStorage 都要换成新 token(否则下次仍带旧 token);
 *   3. 401 → 清本地登录态。
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'

const USER = {
  accountKey: 'acct-A',
  nickname: 'A',
  avatar: 'preset:sum',
  authMethod: 'wechat' as const,
}

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

function stubSession(body: unknown, status = 200) {
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => ({
      ok: status >= 200 && status < 300,
      status,
      json: async () => body,
      text: async () => JSON.stringify(body),
    })),
  )
}

beforeEach(() => {
  memory.clear()
  vi.resetModules()
  vi.unstubAllGlobals()
  installStorage()
})

describe('bootstrapSession', () => {
  it('未轮换时保留原有 token', async () => {
    const user = await import('@/stores/user')
    user.login({ ...USER, token: 'old-token' })
    stubSession({ user: USER })

    const auth = await import('@/services/authService')
    await auth.bootstrapSession()

    expect(user.getToken()).toBe('old-token')
  })

  it('轮换后写回新 token(内存 + localStorage)', async () => {
    const user = await import('@/stores/user')
    user.login({ ...USER, token: 'old-token' })
    stubSession({ user: USER, token: 'new-token' })

    const auth = await import('@/services/authService')
    await auth.bootstrapSession()

    expect(user.getToken()).toBe('new-token')
    expect(JSON.parse(memory.get('mg-user') ?? '{}').token).toBe('new-token')
  })

  it('401 时清空登录态且不留档', async () => {
    const user = await import('@/stores/user')
    user.login({ ...USER, token: 'old-token' })
    stubSession({ detail: 'unauthorized' }, 401)

    const auth = await import('@/services/authService')
    await auth.bootstrapSession()

    expect(user.userState.info).toBeNull()
    expect(memory.has('mg-user')).toBe(false)
  })

  it('网络错误时保留现状(离线打开不踢回登录页)', async () => {
    const user = await import('@/stores/user')
    user.login({ ...USER, token: 'old-token' })
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => {
        throw new Error('network down')
      }),
    )

    const auth = await import('@/services/authService')
    await auth.bootstrapSession()

    expect(user.getToken()).toBe('old-token')
  })
})
