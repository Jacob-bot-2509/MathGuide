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

/* ---------- 登录 / 注册 / 退出:请求构造与错误映射 ---------- */

function stubFetch(body: unknown, status = 200) {
  const stub = vi.fn(async (_url: string, _init?: RequestInit) => ({
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
    text: async () => (typeof body === 'string' ? body : JSON.stringify(body)),
  }))
  vi.stubGlobal('fetch', stub)
  return stub
}

const AUTH_USER = {
  accountKey: 'acct-A',
  nickname: 'A',
  avatar: 'preset:sum',
  authMethod: 'phone-pass' as const,
}

const LOGIN_OK = { user: AUTH_USER, token: 'tk-new' }

describe('getAuthMode', () => {
  it('读取后端模式:demo=false、invite=true 时按后端返回', async () => {
    const stub = stubFetch({ demo: false, invite: true })
    const auth = await import('@/services/authService')

    await expect(auth.getAuthMode()).resolves.toEqual({ demo: false, invite: true })

    const [url, init] = stub.mock.calls[0] as unknown as [string, RequestInit]
    expect(url).toBe('/api/health')
    expect(init.credentials).toBe('include')
  })

  it('后端不可达时退回演示模式(登录页仍可用固定验证码)', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => {
      throw new TypeError('Failed to fetch')
    }))
    const auth = await import('@/services/authService')

    await expect(auth.getAuthMode()).resolves.toEqual({ demo: true, invite: false })
  })
})

describe('loginWithPassword', () => {
  it('成功时提交 password 方案并写入登录态', async () => {
    const stub = stubFetch(LOGIN_OK)
    const user = await import('@/stores/user')
    const auth = await import('@/services/authService')

    await expect(auth.loginWithPassword('13800000000', 'secret')).resolves.toBe('ok')

    const [url, init] = stub.mock.calls[0] as unknown as [string, RequestInit]
    expect(url).toBe('/api/auth/login')
    expect(init.method).toBe('POST')
    expect(init.credentials).toBe('include')
    expect(init.headers).toEqual({ 'Content-Type': 'application/json' })
    expect(JSON.parse(String(init.body))).toEqual({
      method: 'password', phone: '13800000000', password: 'secret',
    })
    expect(user.getToken()).toBe('tk-new')
    expect(JSON.parse(memory.get('mg-user') ?? '{}').token).toBe('tk-new')
  })

  it('404 → notfound(未注册)', async () => {
    stubFetch({ detail: 'not found' }, 404)
    const auth = await import('@/services/authService')

    await expect(auth.loginWithPassword('1', 'p')).resolves.toBe('notfound')
  })

  it('401 → wrong(密码错)', async () => {
    stubFetch({ detail: 'bad password' }, 401)
    const auth = await import('@/services/authService')

    await expect(auth.loginWithPassword('1', 'p')).resolves.toBe('wrong')
  })

  it('500 + 非 JSON 体 → 上抛(交给调用方提示系统故障,不误报密码错)', async () => {
    stubFetch('<html>oops</html>', 500)
    const auth = await import('@/services/authService')

    await expect(auth.loginWithPassword('1', 'p')).rejects.toMatchObject({ status: 500 })
  })

  it('网络异常 → 上抛', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => {
      throw new TypeError('Failed to fetch')
    }))
    const auth = await import('@/services/authService')

    await expect(auth.loginWithPassword('1', 'p')).rejects.toThrow('Failed to fetch')
  })
})

describe('loginWithCode', () => {
  it('提交 code 方案并落登录态', async () => {
    const stub = stubFetch(LOGIN_OK)
    const user = await import('@/stores/user')
    const auth = await import('@/services/authService')

    await expect(auth.loginWithCode('13800000000', auth.DEMO_CODE)).resolves.toBeUndefined()

    const init = stub.mock.calls[0][1] as RequestInit
    expect(JSON.parse(String(init.body))).toEqual({
      method: 'code', phone: '13800000000', code: '123456',
    })
    expect(user.userState.info?.token).toBe('tk-new')
  })
})

describe('registerWithPassword', () => {
  it('成功时提交邀请码(首尾空格被裁掉)', async () => {
    const stub = stubFetch(LOGIN_OK)
    const auth = await import('@/services/authService')

    await expect(auth.registerWithPassword('1', 'p', '  INVITE-9  ')).resolves.toBe('ok')

    const init = stub.mock.calls[0][1] as RequestInit
    expect(JSON.parse(String(init.body))).toEqual({
      phone: '1', password: 'p', invite: 'INVITE-9',
    })
  })

  it('空邀请码不写进请求体(演示模式无需邀请码)', async () => {
    const stub = stubFetch(LOGIN_OK)
    const auth = await import('@/services/authService')

    await auth.registerWithPassword('1', 'p', '   ')

    const init = stub.mock.calls[0][1] as RequestInit
    expect(JSON.parse(String(init.body))).toEqual({ phone: '1', password: 'p' })
  })

  it('409 → exists;403 → invite;400 → closed', async () => {
    const auth = await import('@/services/authService')

    stubFetch({ detail: 'exists' }, 409)
    await expect(auth.registerWithPassword('1', 'p')).resolves.toBe('exists')

    stubFetch({ detail: 'invite' }, 403)
    await expect(auth.registerWithPassword('1', 'p')).resolves.toBe('invite')

    stubFetch({ detail: 'closed' }, 400)
    await expect(auth.registerWithPassword('1', 'p')).resolves.toBe('closed')
  })

  it('500 + 非 JSON 体 → 上抛而不是当成某种业务结果', async () => {
    stubFetch('<html>boom</html>', 500)
    const auth = await import('@/services/authService')

    await expect(auth.registerWithPassword('1', 'p')).rejects.toMatchObject({ status: 500 })
  })
})

describe('loginWithThirdParty', () => {
  it('微信登录提交 method+nickname+avatar 并返回登录态', async () => {
    const stub = stubFetch(LOGIN_OK)
    const user = await import('@/stores/user')
    const auth = await import('@/services/authService')
    const { AVATAR_PRESETS } = await import('@/utils/avatar')

    const info = await auth.loginWithThirdParty('wechat')

    const init = stub.mock.calls[0][1] as RequestInit
    const body = JSON.parse(String(init.body))
    expect(body.method).toBe('wechat')
    expect(body.nickname).toMatch(/^微信用户_\d{4}$/)
    expect(body.avatar).toBe(AVATAR_PRESETS[1].key)
    expect(info.token).toBe('tk-new')
    expect(user.userState.info?.accountKey).toBe('acct-A')
  })

  it('QQ 登录用另一个默认头像', async () => {
    const stub = stubFetch(LOGIN_OK)
    const auth = await import('@/services/authService')
    const { AVATAR_PRESETS } = await import('@/utils/avatar')

    await auth.loginWithThirdParty('qq')

    const init = stub.mock.calls[0][1] as RequestInit
    const body = JSON.parse(String(init.body))
    expect(body.method).toBe('qq')
    expect(body.nickname).toMatch(/^QQ用户_\d{4}$/)
    expect(body.avatar).toBe(AVATAR_PRESETS[2].key)
  })
})

describe('logout', () => {
  it('先清本地登录态,再带 Bearer 尽力撤销服务端 token', async () => {
    const user = await import('@/stores/user')
    user.login({ ...AUTH_USER, token: 'tk-old' })
    const stub = stubFetch({ ok: true })
    const auth = await import('@/services/authService')

    auth.logout()

    expect(user.userState.info).toBeNull()
    expect(memory.has('mg-user')).toBe(false)
    const [url, init] = stub.mock.calls[0] as unknown as [string, RequestInit]
    expect(url).toBe('/api/auth/logout')
    expect(init.headers).toMatchObject({ Authorization: 'Bearer tk-old' })
  })

  it('未登录时不发撤销请求', async () => {
    const stub = stubFetch({ ok: true })
    const auth = await import('@/services/authService')

    auth.logout()

    expect(stub).not.toHaveBeenCalled()
  })

  it('服务端不可达也不影响本地登出', async () => {
    const user = await import('@/stores/user')
    user.login({ ...AUTH_USER, token: 'tk-old' })
    vi.stubGlobal('fetch', vi.fn(async () => {
      throw new TypeError('Failed to fetch')
    }))
    const auth = await import('@/services/authService')

    expect(() => auth.logout()).not.toThrow()
    expect(user.userState.info).toBeNull()
    await new Promise((resolve) => setTimeout(resolve, 0))
  })
})

