/**
 * researchAnnotationService:论文批注的增删查请求构造与错误映射。
 *
 * 批注是「用户的原始劳动」:读失败无所谓,写失败必须让界面知道(否则
 * 用户以为存上了,关闭阅读器就丢)。所以这里既断言路径/方法,也断言
 * 各种失败都抛出来而不是被吞掉。
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import * as annotations from '@/services/researchAnnotationService'
import { login, userState } from '@/stores/user'

const USER = {
  accountKey: 'acct-note',
  nickname: 'n',
  avatar: 'preset:sum',
  authMethod: 'phone-pass' as const,
}

const memory = new Map<string, string>()

beforeEach(() => {
  memory.clear()
  userState.info = null
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
})

function signIn(token = 'tk-note') {
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

function errorResponse(status: number, opts: { json?: unknown; body?: string } = {}) {
  const payload = opts.json
  return {
    ok: false,
    status,
    json: async () => {
      if (payload === undefined) throw new SyntaxError('Unexpected token <')
      return payload
    },
    text: async () => opts.body ?? '',
  }
}

function mockFetch(response: unknown) {
  const stub = vi.fn(async () => response)
  vi.stubGlobal('fetch', stub)
  return stub
}

function lastCall(stub: ReturnType<typeof mockFetch>): [string, RequestInit] {
  return stub.mock.calls.at(-1) as unknown as [string, RequestInit]
}

const INPUT = {
  page: 3,
  quote: '被引用的原文',
  rects: [[0.1, 0.2, 0.3, 0.4]],
  note: '我的想法',
  color: 'yellow',
}

describe('listAnnotations', () => {
  it('按文档取批注,docId 被转义', async () => {
    signIn('tk-note')
    const stub = mockFetch(okJson({ annotations: [{ id: 'a1', page: 3 }] }))

    await expect(annotations.listAnnotations('d/1')).resolves.toEqual([{ id: 'a1', page: 3 }])

    const [url, init] = lastCall(stub)
    expect(url).toBe('/api/research/docs/d%2F1/annotations')
    expect(init.credentials).toBe('include')
    expect(init.headers).toEqual({ Authorization: 'Bearer tk-note' })
  })

  it('没有批注时返回空数组(不是 undefined)', async () => {
    mockFetch(okJson({ annotations: [] }))

    await expect(annotations.listAnnotations('d1')).resolves.toEqual([])
  })
})

describe('saveAnnotation', () => {
  it('提交批注原文与矩形,返回服务端补全的批注', async () => {
    signIn('tk-note')
    const saved = { id: 'a9', docId: 'd1', ...INPUT, createdAt: 1 }
    const stub = mockFetch(okJson({ annotation: saved }))

    await expect(annotations.saveAnnotation('d1', INPUT)).resolves.toEqual(saved)

    const [url, init] = lastCall(stub)
    expect(url).toBe('/api/research/docs/d1/annotations')
    expect(init.method).toBe('POST')
    expect(init.headers).toEqual({
      'Content-Type': 'application/json',
      Authorization: 'Bearer tk-note',
    })
    expect(JSON.parse(String(init.body))).toEqual(INPUT)
  })

  it('保存失败(413 太长)→ 抛带状态码的错误,不假装成功', async () => {
    mockFetch(errorResponse(413, { json: { detail: 'note too long' } }))

    await expect(annotations.saveAnnotation('d1', INPUT))
      .rejects.toMatchObject({ status: 413 })
  })
})

describe('deleteAnnotation', () => {
  it('DELETE 到具体批注路径(两个 id 都转义)', async () => {
    const stub = mockFetch(okJson({ ok: true }))

    await expect(annotations.deleteAnnotation('d 1', 'a/1')).resolves.toBeUndefined()

    const [url, init] = lastCall(stub)
    expect(url).toBe('/api/research/docs/d%201/annotations/a%2F1')
    expect(init.method).toBe('DELETE')
  })
})

describe('错误映射', () => {
  it('404 + JSON 错误体 → 带 status 上抛', async () => {
    mockFetch(errorResponse(404, { json: { detail: 'doc not found' } }))

    await expect(annotations.listAnnotations('d1')).rejects.toMatchObject({ status: 404 })
  })

  it('500 + 非 JSON 体 → 状态码消息,不抛 JSON 解析错', async () => {
    mockFetch(errorResponse(500, { body: '<html>boom</html>' }))

    await expect(annotations.saveAnnotation('d1', INPUT)).rejects.toMatchObject({
      status: 500,
      message: 'HTTP 500',
    })
  })

  it('401 → 状态可被上层识别(回登录页)', async () => {
    mockFetch(errorResponse(401, { json: { detail: 'unauthorized' } }))

    await expect(annotations.listAnnotations('d1')).rejects.toMatchObject({ status: 401 })
  })

  it('网络异常 → 原样上抛(界面据此保留草稿)', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => {
      throw new TypeError('Failed to fetch')
    }))

    await expect(annotations.saveAnnotation('d1', INPUT)).rejects.toThrow('Failed to fetch')
    await expect(annotations.deleteAnnotation('d1', 'a1')).rejects.toThrow('Failed to fetch')
  })
})
