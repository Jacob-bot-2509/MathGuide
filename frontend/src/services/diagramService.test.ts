/**
 * diagramService:图解规划的请求构造、spec 校验与错误映射。
 *
 * planDiagram 是「模型产出 → 前端渲染」的唯一闸门:
 *   - 空字符串的可选字段不能以 '' 发出去(后端会当成有效 id 去查);
 *   - 模型给的 diagram 必须过 parseDiagramSpec 白名单,非法就返回 null
 *     (让界面回退到纯文本,而不是渲染一张坏图);
 *   - 请求失败要抛带 status 的错误,不能返回 null 让界面以为「模型没画」。
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import * as diagram from '@/services/diagramService'
import { login, userState } from '@/stores/user'

const USER = {
  accountKey: 'acct-diagram',
  nickname: 'd',
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

function signIn(token = 'tk-diagram') {
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

const VALID_SPEC = {
  type: 'plot2d',
  shapes: [{ kind: 'point', x: 1, y: 2, label: 'A' }],
}

describe('planDiagram', () => {
  it('把问题、答案与上下文交给后端,并返回白名单校验后的 spec', async () => {
    signIn('tk-diagram')
    const stub = mockFetch(okJson({ diagram: VALID_SPEC }))

    const spec = await diagram.planDiagram({
      question: '这条曲线怎么理解',
      answer: '它是一条抛物线',
      paperId: 'p1',
      tableId: 't1',
      mode: 'research',
      regression: { x: ['t'], y: 'y', model: 'oly' as never, degree: 2 },
      kind: 'plot2d',
    })

    const [url, init] = lastCall(stub)
    expect(url).toBe('/api/research/diagrams/plan')
    expect(init.method).toBe('POST')
    expect(init.credentials).toBe('include')
    expect(init.headers).toEqual({
      'Content-Type': 'application/json',
      Authorization: 'Bearer tk-diagram',
    })
    expect(JSON.parse(String(init.body))).toEqual({
      question: '这条曲线怎么理解',
      answer: '它是一条抛物线',
      paperId: 'p1',
      tableId: 't1',
      mode: 'research',
      regression: { x: ['t'], y: 'y', model: 'oly', degree: 2 },
      kind: 'plot2d',
    })
    expect(spec).toMatchObject({ schemaVersion: 1, type: 'plot2d' })
    expect(spec!.shapes).toHaveLength(1)
  })

  it('空的 paperId / tableId / kind 不进请求(否则后端会拿空 id 去查)', async () => {
    const stub = mockFetch(okJson({ diagram: VALID_SPEC }))

    await diagram.planDiagram({
      question: 'q', answer: 'a', paperId: '', tableId: '', kind: '', mode: 'learn',
    })

    expect(JSON.parse(String(lastCall(stub)[1].body))).toEqual({
      question: 'q', answer: 'a', mode: 'learn',
    })
  })

  it('模型给出非法 spec 时返回 null(界面回退纯文本)', async () => {
    mockFetch(okJson({ diagram: { type: 'plot2d', shapes: [] } }))

    await expect(diagram.planDiagram({ question: 'q', answer: 'a' })).resolves.toBeNull()
  })

  it('后端没有给 diagram 时返回 null', async () => {
    mockFetch(okJson({}))

    await expect(diagram.planDiagram({ question: 'q', answer: 'a' })).resolves.toBeNull()
  })
})

describe('错误映射', () => {
  it('400 + JSON 错误体 → 带 status 上抛(不能当成「没画图」)', async () => {
    mockFetch(errorResponse(400, { json: { detail: 'bad request' } }))

    await expect(diagram.planDiagram({ question: 'q', answer: 'a' }))
      .rejects.toMatchObject({ status: 400 })
  })

  it('500 + 非 JSON 体 → 状态码消息,不抛 JSON 解析错', async () => {
    mockFetch(errorResponse(500, { body: '<html>boom</html>' }))

    await expect(diagram.planDiagram({ question: 'q', answer: 'a' }))
      .rejects.toMatchObject({ status: 500, message: 'HTTP 500' })
  })

  it('401 → 状态可被上层识别(回登录页)', async () => {
    mockFetch(errorResponse(401, { json: { detail: 'unauthorized' } }))

    await expect(diagram.planDiagram({ question: 'q', answer: 'a' }))
      .rejects.toMatchObject({ status: 401 })
  })

  it('网络异常 → 原样上抛', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => {
      throw new TypeError('Failed to fetch')
    }))

    await expect(diagram.planDiagram({ question: 'q', answer: 'a' }))
      .rejects.toThrow('Failed to fetch')
  })
})

describe('转发给界面的意图判断', () => {
  it('needsDiagram / diagramSuppressed 从这里可直接取用', () => {
    expect(diagram.needsDiagram('这条曲线怎么理解?')).toBe(true)
    expect(diagram.diagramSuppressed('这次不要画图')).toBe(true)
    expect(diagram.needsDiagram('今天好热')).toBe(false)
  })
})
