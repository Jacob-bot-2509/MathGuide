/**
 * graphService:知识图谱 / 学习分析 / 推荐 / 自评的请求构造与错误映射。
 *
 * 图谱是首屏数据:一次请求失败就不能画出骨架,所以这层的失败方式必须
 * 可预期 —— 抛带 status 的 HttpError(界面据此区分「没登录」与「后端挂了」),
 * 而不是返回 undefined 让渲染层炸在更远的地方。
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import * as graph from '@/services/graphService'
import { login, userState } from '@/stores/user'

const USER = {
  accountKey: 'acct-graph',
  nickname: 'g',
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

function signIn(token = 'tk-graph') {
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

describe('图谱与学习分析', () => {
  it('拉图谱:GET /api/graph,带 Bearer 与 Cookie', async () => {
    signIn('tk-graph')
    const data = { nodes: [{ id: 'k1' }], edges: [], chapters: ['第一章'] }
    const stub = mockFetch(okJson(data))

    await expect(graph.fetchGraph()).resolves.toEqual(data)

    const [url, init] = lastCall(stub)
    expect(url).toBe('/api/graph')
    expect(init.credentials).toBe('include')
    expect(init.headers).toEqual({ Authorization: 'Bearer tk-graph' })
    expect(init.method).toBeUndefined()
  })

  it('未登录时不发空的 Bearer 头', async () => {
    const stub = mockFetch(okJson({ nodes: [], edges: [], chapters: [] }))

    await graph.fetchGraph()

    expect(lastCall(stub)[1].headers).toEqual({})
  })

  it('学习分析快照走 /api/profile/analysis', async () => {
    const stub = mockFetch(okJson({ generatedAt: 'now', dataQuality: 'ok' }))

    await expect(graph.fetchLearningAnalysis())
      .resolves.toMatchObject({ dataQuality: 'ok' })
    expect(lastCall(stub)[0]).toBe('/api/profile/analysis')
  })
})

describe('推荐与自评', () => {
  it('推荐默认 strategy=difficulty、limit=5', async () => {
    const stub = mockFetch(okJson({ strategy: 'difficulty', mastered: 3, items: [] }))

    await expect(graph.fetchRecommendation())
      .resolves.toMatchObject({ strategy: 'difficulty' })

    const [url] = lastCall(stub)
    expect(url).toBe('/api/recommendation?strategy=difficulty&limit=5')
  })

  it('推荐可切换策略与条数', async () => {
    const stub = mockFetch(okJson({ strategy: 'coreness', mastered: 0, items: [] }))

    await graph.fetchRecommendation('coreness', 12)

    expect(lastCall(stub)[0]).toBe('/api/recommendation?strategy=coreness&limit=12')
  })

  it('自评:POST /api/diagnosis 带知识点与评分', async () => {
    signIn('tk-diag')
    const stub = mockFetch(okJson({ ok: true, pointId: 'k1', score: 80, source: 'self' }))

    await expect(graph.submitSelfRating('k1', 80))
      .resolves.toMatchObject({ score: 80, source: 'self' })

    const [url, init] = lastCall(stub)
    expect(url).toBe('/api/diagnosis')
    expect(init.method).toBe('POST')
    expect(init.headers).toEqual({
      'Content-Type': 'application/json',
      Authorization: 'Bearer tk-diag',
    })
    expect(JSON.parse(String(init.body))).toEqual({ pointId: 'k1', selfRating: 80 })
  })
})

describe('导出独立 HTML 图谱', () => {
  it('成功时返回 Blob(带 Bearer 头)', async () => {
    signIn('tk-graph')
    const blob = new Blob(['<html></html>'], { type: 'text/html' })
    const stub = mockFetch({ ok: true, status: 200, blob: async () => blob })

    await expect(graph.exportGraphHtml()).resolves.toBe(blob)

    const [url, init] = lastCall(stub)
    expect(url).toBe('/api/graph/export')
    expect(init.headers).toEqual({ Authorization: 'Bearer tk-graph' })
  })

  it('非 2xx 时抛 HttpError,不返回空 Blob', async () => {
    mockFetch({
      ok: false,
      status: 500,
      blob: async () => new Blob([]),
      json: async () => {
        throw new SyntaxError('Unexpected token <')
      },
    })

    await expect(graph.exportGraphHtml()).rejects.toMatchObject({
      status: 500,
      message: 'HTTP 500',
    })
  })
})

describe('错误映射', () => {
  it('404 + JSON 错误体 → 带 status 上抛', async () => {
    mockFetch(errorResponse(404, { json: { detail: 'graph not found' } }))

    await expect(graph.fetchGraph()).rejects.toMatchObject({ status: 404 })
  })

  it('502 + 非 JSON 体 → 状态码消息,不抛解析错', async () => {
    mockFetch(errorResponse(502, { body: '<html>bad gateway</html>' }))

    await expect(graph.fetchLearningAnalysis()).rejects.toMatchObject({
      status: 502,
      message: 'HTTP 502',
    })
  })

  it('401 → 状态可被上层识别(回登录页)', async () => {
    mockFetch(errorResponse(401, { json: { detail: 'unauthorized' } }))

    await expect(graph.fetchRecommendation()).rejects.toMatchObject({ status: 401 })
  })

  it('网络异常 → 原样上抛,不会被当成空图谱', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => {
      throw new TypeError('Failed to fetch')
    }))

    await expect(graph.fetchGraph()).rejects.toThrow('Failed to fetch')
    await expect(graph.submitSelfRating('k1', 50)).rejects.toThrow('Failed to fetch')
  })
})
