/**
 * docgenService:问答导出与「按独立要求生成文档」的请求构造与错误映射。
 *
 * 关注:
 *   1. 会话只取最近 80 条(上下文预算),且只带 role/content/cmd/chitchat;
 *   2. 二进制导出统一走 docService.postBinary —— 401 要清登录态回登录页;
 *   3. 各组装的 body 形状必须与后端契约一致(payload 少一个字段就白等几十秒)。
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'

const hoisted = vi.hoisted(() => ({ push: vi.fn(), toast: vi.fn() }))
vi.mock('@/router', () => ({ default: { push: hoisted.push } }))
vi.mock('@/utils/toast', () => ({ showToast: hoisted.toast }))

import * as docgen from '@/services/docgenService'
import { login, userState } from '@/stores/user'

const USER = {
  accountKey: 'acct-gen',
  nickname: 'g',
  avatar: 'preset:sum',
  authMethod: 'phone-pass' as const,
}

const memory = new Map<string, string>()

beforeEach(() => {
  memory.clear()
  userState.info = null
  hoisted.push.mockClear()
  hoisted.toast.mockClear()
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

function signIn(token = 'tk-gen') {
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

function binaryResponse(filename = 'out.pdf') {
  return {
    ok: true,
    status: 200,
    blob: async () => new Blob(['bytes']),
    headers: {
      get: (name: string) => (name === 'Content-Disposition'
        ? `attachment; filename="${filename}"`
        : null),
    },
  }
}

function errorResponse(status: number, opts: { json?: unknown; body?: string } = {}) {
  const payload = opts.json
  return {
    ok: false,
    status,
    headers: { get: () => null },
    json: async () => {
      if (payload === undefined) throw new SyntaxError('Unexpected token <')
      return payload
    },
    text: async () => opts.body ?? (payload === undefined ? '' : JSON.stringify(payload)),
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

const OUTLINE: docgen.DocOutline = {
  title: '综述',
  sections: [{ heading: '一', points: ['p'], evidence_ids: [], has_evidence: false }],
  gaps: [],
  evidence: [],
}

const DOCUMENT: docgen.StructuredDocument = {
  title: '综述',
  sections: [{ heading: '一', paragraphs: ['正文'] }],
}

describe('fetchDocQuestions', () => {
  it('只取最近 80 条会话,且只带四个字段', async () => {
    signIn('tk-gen')
    const stub = mockFetch(okJson({ items: [{ id: 1, question: 'q', has_answer: true }] }))
    const messages = Array.from({ length: 85 }, (_, index) => ({
      role: index % 2 ? 'assistant' : 'user',
      content: `第${index}条`,
      cmd: 'solve',
      chitchat: false,
      // 界面内部字段不该进请求
      streaming: true,
      id: index,
    }))

    const items = await docgen.fetchDocQuestions(messages as never, 'zh')

    expect(items).toEqual([{ id: 1, question: 'q', has_answer: true }])
    const [url, init] = lastCall(stub)
    expect(url).toBe('/api/doc/questions')
    expect(init.method).toBe('POST')
    expect(init.headers).toEqual({
      'Content-Type': 'application/json',
      Authorization: 'Bearer tk-gen',
    })
    const body = JSON.parse(String(init.body))
    expect(body.lang).toBe('zh')
    expect(body.messages).toHaveLength(80)
    expect(body.messages[0]).toEqual({
      role: 'assistant', content: '第5条', cmd: 'solve', chitchat: false,
    })
  })
})

describe('文档生成的各组请求体', () => {
  it('大纲 / 生成 / 修订', async () => {
    const stub = mockFetch(okJson(OUTLINE))

    await expect(docgen.requestOutline('写一篇综述', 'zh')).resolves.toEqual(OUTLINE)
    let [url, init] = lastCall(stub)
    expect(url).toBe('/api/doc/outline')
    expect(JSON.parse(String(init.body))).toEqual({ request: '写一篇综述', lang: 'zh' })

    stub.mockResolvedValue(okJson({ document: DOCUMENT, gaps: [] }))
    await expect(docgen.generateDocument('写一篇综述', OUTLINE, 'zh'))
      .resolves.toEqual({ document: DOCUMENT, gaps: [] })
    ;[url, init] = lastCall(stub)
    expect(url).toBe('/api/doc/generate')
    expect(JSON.parse(String(init.body))).toEqual({
      request: '写一篇综述', outline: OUTLINE, lang: 'zh',
    })

    stub.mockResolvedValue(okJson({ document: DOCUMENT }))
    await docgen.reviseDocument(DOCUMENT, '把第二节写短一点', 'en')
    ;[url, init] = lastCall(stub)
    expect(url).toBe('/api/doc/revise')
    expect(JSON.parse(String(init.body))).toEqual({
      document: DOCUMENT, request: '把第二节写短一点', lang: 'en',
    })
  })

  it('练习卷:先规划再生成,body 原样提交', async () => {
    const body: docgen.ExercisePlanRequest = {
      topics: ['导数'],
      crossTopics: ['物理'],
      types: ['calc'],
      difficulty: [1, 3],
      count: 5,
      lang: 'both',
      requirement: '带上答案',
      allowPartial: true,
      seed: 42,
    }
    const stub = mockFetch(okJson({
      available: { zh: 3, en: 2, both: 1 }, selected: 5, missing: 0, gaps: [],
    }))

    await expect(docgen.planExercises(body))
      .resolves.toMatchObject({ selected: 5 })
    let [url, init] = lastCall(stub)
    expect(url).toBe('/api/doc/exercise/plan')
    expect(JSON.parse(String(init.body))).toEqual(body)

    stub.mockResolvedValue(okJson({ document: DOCUMENT, selected: 5, missing: 0, gaps: [] }))
    await docgen.generateExercises({ ...body, mode: 'combined' })
    ;[url, init] = lastCall(stub)
    expect(url).toBe('/api/doc/exercise')
    expect(JSON.parse(String(init.body))).toEqual({ ...body, mode: 'combined' })
  })
})

describe('二进制导出', () => {
  it('问答导出走 /api/doc/qa,文件名取自响应头', async () => {
    signIn('tk-gen')
    const stub = mockFetch(binaryResponse('问答.md'))

    const result = await docgen.exportQaDocument(
      [{ question: 'q', answer: 'a', source: 's' }], 'zh', 'md', 'learn',
    )

    const [url, init] = lastCall(stub)
    expect(url).toBe('/api/doc/qa')
    expect(init.method).toBe('POST')
    expect(init.headers).toEqual({
      'Content-Type': 'application/json',
      Authorization: 'Bearer tk-gen',
    })
    expect(JSON.parse(String(init.body))).toEqual({
      items: [{ question: 'q', answer: 'a', source: 's' }],
      lang: 'zh',
      format: 'md',
      source: 'learn',
    })
    expect(result.filename).toBe('问答.md')
  })

  it('结构化文档渲染走 /api/doc/render', async () => {
    const stub = mockFetch(binaryResponse('render.docx'))

    const result = await docgen.renderDocument(DOCUMENT, 'zh', 'docx')

    const [url, init] = lastCall(stub)
    expect(url).toBe('/api/doc/render')
    expect(JSON.parse(String(init.body))).toEqual({
      document: DOCUMENT, lang: 'zh', format: 'docx',
    })
    expect(result.filename).toBe('render.docx')
  })

  it('导出 401 → 清登录态并回登录页(几十秒的等待不能白费)', async () => {
    signIn('tk-expired')
    mockFetch(errorResponse(401, { json: { detail: 'unauthorized' } }))

    await expect(docgen.exportQaDocument([], 'zh', 'pdf', 'learn'))
      .rejects.toMatchObject({ status: 401 })
    expect(userState.info).toBeNull()
    expect(hoisted.push).toHaveBeenCalledWith('/login')
    expect(hoisted.toast).toHaveBeenCalledTimes(1)
  })

  it('导出 500 + 非 JSON 体 → 状态码异常,不抛解析错', async () => {
    mockFetch(errorResponse(500, { body: '<html>gateway</html>' }))

    await expect(docgen.renderDocument(DOCUMENT, 'zh', 'pdf'))
      .rejects.toMatchObject({ status: 500, message: 'HTTP 500' })
  })

  it('大纲请求网络异常 → 原样上抛', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => {
      throw new TypeError('Failed to fetch')
    }))

    await expect(docgen.requestOutline('x', 'zh')).rejects.toThrow('Failed to fetch')
  })

  it('大纲请求 429 → 限流状态交给上层提示', async () => {
    mockFetch(errorResponse(429, { json: { detail: 'too many' } }))

    await expect(docgen.requestOutline('x', 'zh')).rejects.toMatchObject({ status: 429 })
  })
})

