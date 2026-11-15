// @vitest-environment happy-dom
/**
 * accountService:数据导出与注销。
 *
 * 为什么这条链路值得测:导出文件是「用户自己的数据」,里面绝不能混进 token;
 * 而且后端不可达时也必须把本地数据导出来 —— 用户点「导出」却什么都没拿到
 * 是最让人不放心的失败方式。这里锁死:
 *   1. 白名单取本地键、mg-user 去 token、todo 按 accountKey 取;
 *   2. 服务端成功 → full;任何服务端失败 → 仍然下载本地数据(local + serverError);
 *   3. 注销的 401(密码错/token 失效)映射成 'wrong',其余错误照抛。
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import {
  collectLocalData, deleteAccount, exportAccountData,
} from '@/services/accountService'
import { login, userState } from '@/stores/user'

const memory = new Map<string, string>()
let downloads: Blob[] = []

function installStorage() {
  vi.stubGlobal('localStorage', {
    getItem: (key: string) => memory.get(key) ?? null,
    setItem: (key: string, value: string) => memory.set(key, String(value)),
    removeItem: (key: string) => memory.delete(key),
    clear: () => memory.clear(),
    key: (index: number) => [...memory.keys()][index] ?? null,
    get length() {
      return memory.size
    },
  })
}

const USER = {
  accountKey: 'acct-x',
  nickname: 'x',
  avatar: 'preset:sum',
  authMethod: 'phone-pass' as const,
}

function signIn(token = 'tk-export') {
  login({ ...USER, token })
}

function okJson(body: unknown) {
  return {
    ok: true,
    status: 200,
    json: async () => body,
    text: async () => JSON.stringify(body),
  }
}

function errorResponse(status: number, body?: unknown) {
  return {
    ok: false,
    status,
    json: async () => {
      if (body === undefined) throw new SyntaxError('Unexpected token <')
      return body
    },
    text: async () => (body === undefined ? '<html>error</html>' : JSON.stringify(body)),
  }
}

beforeEach(() => {
  memory.clear()
  installStorage()
  userState.info = null
  downloads = []
  const holder = globalThis.URL as unknown as Record<string, unknown>
  if (typeof holder.createObjectURL !== 'function') holder.createObjectURL = () => 'blob:stub'
  if (typeof holder.revokeObjectURL !== 'function') holder.revokeObjectURL = () => {}
  vi.spyOn(URL, 'createObjectURL').mockImplementation((blob: Blob | MediaSource) => {
    downloads.push(blob as Blob)
    return 'blob:stub'
  })
  vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => undefined)
  vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => undefined)
})

async function exportedPayload(): Promise<Record<string, unknown>> {
  expect(downloads).toHaveLength(1)
  return JSON.parse(await downloads[0].text()) as Record<string, unknown>
}


describe('collectLocalData', () => {
  it('只导出白名单键,token 被摘掉,待办按 accountKey 取', () => {
    signIn('tk-secret')
    memory.set('mg-learn-sessions', '[]')
    memory.set('mg-notebook', JSON.stringify([{ id: 1 }]))
    memory.set('mg-settings', 'not-json')       // 非 JSON 原样带出
    memory.set('mg-trash', '{}')
    memory.set('mg-todo:acct-x', JSON.stringify(['复习']))
    memory.set('mg-todo:other', JSON.stringify(['别人的']))
    memory.set('unrelated-key', 'x')
    memory.set('mg-user', JSON.stringify({ ...USER, token: 'tk-secret' }))

    const local = collectLocalData()

    expect(Object.keys(local)).toEqual([
      'mg-learn-sessions', 'mg-notebook', 'mg-settings', 'mg-trash',
      'mg-user', 'mg-todo:acct-x',
    ])
    // 凭据绝不能进导出文件
    expect((local['mg-user'] as Record<string, unknown>).token).toBeUndefined()
    expect((local['mg-user'] as Record<string, unknown>).nickname).toBe('x')
    expect(local['mg-settings']).toBe('not-json')
    expect(local['mg-todo:acct-x']).toEqual(['复习'])
  })

  it('未登录时不带 todo,缺省的键不产生空字段', () => {
    memory.set('mg-settings', '{"theme":"dark"}')

    expect(collectLocalData()).toEqual({ 'mg-settings': { theme: 'dark' } })
  })

  it('localStorage 不可用时不抛错(隐私模式下也能导出)', () => {
    vi.stubGlobal('localStorage', {
      getItem: () => {
        throw new Error('denied')
      },
    })

    expect(collectLocalData()).toEqual({})
  })
})

describe('exportAccountData:请求构造与下载', () => {
  it('成功时用 POST + Bearer 取服务端数据,连同本地数据一起下载', async () => {
    signIn('tk-export')
    memory.set('mg-notebook', '[]')
    const fetchStub = vi.fn(async () => okJson({
      exportedAt: '2026-01-01T00:00:00Z',
      account: { accountKey: 'acct-x' },
      usage: [{ day: '2026-01-01', ask: 3 }],
    }))
    vi.stubGlobal('fetch', fetchStub)

    await expect(exportAccountData()).resolves.toBe('full')

    const [url, init] = fetchStub.mock.calls[0] as unknown as [string, RequestInit]
    expect(url).toBe('/api/account/export')
    expect(init.method).toBe('POST')
    expect(init.credentials).toBe('include')
    expect(init.headers).toEqual({
      'Content-Type': 'application/json',
      Authorization: 'Bearer tk-export',
    })
    expect(init.body).toBe('{}')

    const payload = await exportedPayload()
    expect(payload.app).toBeTruthy()
    expect(payload.version).toBeTruthy()
    expect(payload.serverError).toBeUndefined()
    expect(payload.server).toMatchObject({ account: { accountKey: 'acct-x' } })
    expect(Object.keys(payload.local as Record<string, unknown>))
      .toEqual(['mg-notebook', 'mg-user'])

    // 下载确实触发过一次
    expect(URL.revokeObjectURL).not.toHaveBeenCalled()
  })

  it('401 + JSON 错误体 → 仍导出本地数据,serverError 记 HTTP 401', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => errorResponse(401, { detail: 'unauthorized' })))

    await expect(exportAccountData()).resolves.toBe('local')

    const payload = await exportedPayload()
    expect(payload.server).toBeNull()
    expect(payload.serverError).toBe('HTTP 401')
  })

  it('500 + 非 JSON 错误体 → 不抛 JSON 解析错,按状态码记错', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => errorResponse(500)))

    await expect(exportAccountData()).resolves.toBe('local')

    const payload = await exportedPayload()
    expect(payload.serverError).toBe('HTTP 500')
  })

  it('网络异常 → 依然给出本地数据(不能什么都拿不到)', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => {
      throw new TypeError('Failed to fetch')
    }))
    memory.set('mg-settings', '{}')

    await expect(exportAccountData()).resolves.toBe('local')

    const payload = await exportedPayload()
    expect(payload.serverError).toBe('Failed to fetch')
    expect(payload.local).toEqual({ 'mg-settings': {} })
  })
})

describe('deleteAccount', () => {
  it('成功注销时把表单原样提交', async () => {
    signIn('tk-del')
    const fetchStub = vi.fn(async () => okJson({ ok: true }))
    vi.stubGlobal('fetch', fetchStub)

    await expect(deleteAccount({ password: 'p@ss', confirm: '注销' })).resolves.toBe('ok')

    const [url, init] = fetchStub.mock.calls[0] as unknown as [string, RequestInit]
    expect(url).toBe('/api/account/delete')
    expect(init.method).toBe('POST')
    expect(init.headers).toEqual({
      'Content-Type': 'application/json',
      Authorization: 'Bearer tk-del',
    })
    expect(JSON.parse(String(init.body))).toEqual({ password: 'p@ss', confirm: '注销' })
  })

  it('401 → 返回 wrong(密码错误与 token 失效同一口径)', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => errorResponse(401, { detail: 'bad password' })))

    await expect(deleteAccount({ password: 'x' })).resolves.toBe('wrong')
  })

  it('500 + 非 JSON 体 → 抛出带状态码的错误(交给调用方提示)', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => errorResponse(500)))

    await expect(deleteAccount({ password: 'x' })).rejects.toMatchObject({ status: 500 })
  })

  it('网络异常 → 异常上抛,不会被当成注销成功', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => {
      throw new TypeError('Failed to fetch')
    }))

    await expect(deleteAccount({ password: 'x' })).rejects.toThrow('Failed to fetch')
  })
})
