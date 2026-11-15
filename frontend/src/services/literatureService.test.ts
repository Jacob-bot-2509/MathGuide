/**
 * literatureService:外部文献发现与临时论文的请求构造与错误映射。
 *
 * 重点:
 *   1. 检索参数只带用户真的选了的过滤条件(空值不能变成 ?author=undefined);
 *   2. DOI / 标题解析必须做 URL 编码(DOI 里全是 / 和 ());
 *   3. 临时入库接口开启 readErrorDetail —— 抓取失败原因要透传给用户;
 *   4. 401/429 的 status 要能被上层识别,非 JSON 响应不能变成解析错误。
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import * as literature from '@/services/literatureService'
import { login, userState } from '@/stores/user'

const USER = {
  accountKey: 'acct-lit',
  nickname: 'l',
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

function signIn(token = 'tk-lit') {
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

function searchResult() {
  return { query: 'q', results: [], warnings: [], identifier: null }
}

describe('searchLiterature:查询参数构造', () => {
  it('只带 q 与默认 limit,其余过滤条件不出现', async () => {
    signIn('tk-lit')
    const stub = mockFetch(okJson(searchResult()))

    await expect(literature.searchLiterature('graph neural')).resolves.toEqual(searchResult())

    const [url, init] = lastCall(stub)
    expect(url).toBe('/api/research/literature?q=graph+neural&limit=10')
    expect(init.credentials).toBe('include')
    expect(init.headers).toEqual({ Authorization: 'Bearer tk-lit' })
  })

  it('带齐过滤条件时逐项拼进查询串', async () => {
    const stub = mockFetch(okJson(searchResult()))

    await literature.searchLiterature('矩阵', {
      limit: 5,
      author: '张三',
      yearFrom: 2019,
      yearTo: 2024,
      field: 'math',
      includePreprints: false,
      peerReviewed: true,
      oaOnly: true,
    })

    const [url] = lastCall(stub)
    expect(decodeURIComponent(url)).toBe(
      '/api/research/literature?q=矩阵&limit=5&author=张三&yearFrom=2019'
      + '&yearTo=2024&field=math&includePreprints=false&peerReviewed=true&oaOnly=true',
    )
  })

  it('相关文献 / OA 解析 / 全文解析:DOI 与标题都做 URL 编码', async () => {
    const stub = mockFetch(okJson({ isOa: true, oaUrl: 'https://x/y.pdf' }))

    await expect(literature.resolveLiteratureOa('10.1000/a b(c)'))
      .resolves.toMatchObject({ isOa: true })
    let [url] = lastCall(stub)
    expect(url).toBe('/api/research/literature/oa?doi=10.1000%2Fa%20b(c)')

    stub.mockResolvedValue(okJson(searchResult()))
    await literature.relatedLiterature({ doi: '10.1/x', title: 'A Title' })
    ;[url] = lastCall(stub)
    expect(url).toBe('/api/research/literature/related?doi=10.1%2Fx&title=A+Title')

    stub.mockResolvedValue(okJson({ ok: true, url: 'https://x' }))
    await literature.resolveFullText({ doi: '10.1/x', title: '', pmid: '123' })
    ;[url] = lastCall(stub)
    // 空值不进查询串,否则后端会拿空标题去匹配
    expect(url).toBe('/api/research/fulltext?doi=10.1%2Fx&pmid=123')
  })
})

describe('临时论文与入库', () => {
  it('打开外部论文前先临时入库,元数据原样提交', async () => {
    signIn('tk-temp')
    const stub = mockFetch(okJson({ docId: 'tmp1', duplicate: false, status: 'ok', pages: 3 }))

    await expect(literature.createTempPaper('https://x/a.pdf', { title: 'A', oaStatus: 'oa' }))
      .resolves.toMatchObject({ docId: 'tmp1' })

    const [url, init] = lastCall(stub)
    expect(url).toBe('/api/research/papers/temp')
    expect(init.method).toBe('POST')
    expect(init.headers).toEqual({
      'Content-Type': 'application/json',
      Authorization: 'Bearer tk-temp',
    })
    expect(JSON.parse(String(init.body))).toEqual({
      url: 'https://x/a.pdf', metadata: { title: 'A', oaStatus: 'oa' },
    })
  })

  it('落地页抓取走 temp-page', async () => {
    const stub = mockFetch(okJson({ docId: 'tmp2', duplicate: false, status: 'ok', pages: 1 }))

    await literature.createTempPage('https://x/landing')

    const [url, init] = lastCall(stub)
    expect(url).toBe('/api/research/papers/temp-page')
    expect(JSON.parse(String(init.body))).toEqual({ url: 'https://x/landing' })
  })

  it('临时转正式:默认保留批注,无项目时不发 projectId', async () => {
    const stub = mockFetch(okJson({ docId: 'd1', duplicate: false, status: 'imported' }))

    await expect(literature.importTempPaper('tmp1')).resolves.toMatchObject({ docId: 'd1' })

    const [url, init] = lastCall(stub)
    expect(url).toBe('/api/research/papers/import')
    expect(JSON.parse(String(init.body))).toEqual({ docId: 'tmp1', keepAnnotations: true })

    await literature.importTempPaper('tmp1', 'p1', false)
    expect(JSON.parse(String(lastCall(stub)[1].body)))
      .toEqual({ docId: 'tmp1', projectId: 'p1', keepAnnotations: false })
  })

  it('交给本机阅读器打开 PDF', async () => {
    const stub = mockFetch(okJson({ ok: true, opened: true, file: 'a.pdf' }))

    await expect(literature.openLiteraturePdf('https://x/a.pdf'))
      .resolves.toEqual({ ok: true, opened: true, file: 'a.pdf' })

    const [url, init] = lastCall(stub)
    expect(url).toBe('/api/research/literature/open-pdf')
    expect(JSON.parse(String(init.body))).toEqual({ url: 'https://x/a.pdf' })
  })
})

describe('阅读历史与回收站', () => {
  it('列表 / 回收站各自解包 items', async () => {
    signIn('tk-hist')
    const stub = mockFetch(okJson({ items: [{ id: 'd1', annotations: 2 }] }))

    await expect(literature.listPaperHistory()).resolves.toEqual([{ id: 'd1', annotations: 2 }])
    const first = lastCall(stub)
    let url = first[0]
    const init = first[1]
    expect(url).toBe('/api/research/history')
    expect(init.headers).toEqual({ Authorization: 'Bearer tk-hist' })

    stub.mockResolvedValue(okJson({ items: [] }))
    await expect(literature.listPaperTrash()).resolves.toEqual([])
    ;[url] = lastCall(stub)
    expect(url).toBe('/api/research/history/trash')
  })

  it('删除走 DELETE,hard 时带 ?hard=1', async () => {
    const stub = mockFetch(okJson({ ok: true }))

    await literature.deletePaperHistory('d 1')
    let [url, init] = lastCall(stub)
    expect(url).toBe('/api/research/history/d%201')
    expect(init.method).toBe('DELETE')

    await literature.deletePaperHistory('d1', true)
    ;[url, init] = lastCall(stub)
    expect(url).toBe('/api/research/history/d1?hard=1')
    expect(init.method).toBe('DELETE')
  })

  it('从回收站恢复走 POST', async () => {
    const stub = mockFetch(okJson({ ok: true }))

    await expect(literature.restorePaperHistory('d1')).resolves.toBeUndefined()

    const [url, init] = lastCall(stub)
    expect(url).toBe('/api/research/history/d1/restore')
    expect(init.method).toBe('POST')
    expect(init.body).toBe('{}')
  })
})

describe('错误映射', () => {
  it('临时入库失败时把后端 detail 透传(抓取失败原因要给用户看)', async () => {
    mockFetch(errorResponse(422, { json: { detail: '该链接需要登录,无法获取全文' } }))

    await expect(literature.createTempPaper('https://x'))
      .rejects.toMatchObject({ status: 422, message: '该链接需要登录,无法获取全文' })
  })

  it('落地页抓取非 JSON 错误体 → 状态码消息,不抛解析错', async () => {
    mockFetch(errorResponse(502, { body: `<html>${'e'.repeat(200)}</html>` }))

    await expect(literature.createTempPage('https://x'))
      .rejects.toMatchObject({ status: 502, message: 'HTTP 502' })
  })

  it('检索 401 + JSON 错误体 → 带 status 上抛(上层据此回登录页)', async () => {
    mockFetch(errorResponse(401, { json: { detail: 'unauthorized' } }))

    await expect(literature.searchLiterature('q')).rejects.toMatchObject({ status: 401 })
  })

  it('检索 429 → 限流状态交给上层提示', async () => {
    mockFetch(errorResponse(429, { json: { detail: 'rate limited' } }))

    await expect(literature.searchLiterature('q')).rejects.toMatchObject({ status: 429 })
  })

  it('网络异常 → 原样上抛,不会被当成空结果集', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => {
      throw new TypeError('Failed to fetch')
    }))

    await expect(literature.searchLiterature('q')).rejects.toThrow('Failed to fetch')
    await expect(literature.listPaperHistory()).rejects.toThrow('Failed to fetch')
  })

  it('409 冲突(重复入库)上抛给调用方判定', async () => {
    mockFetch(errorResponse(409, { json: { detail: 'already imported' } }))

    await expect(literature.importTempPaper('tmp1'))
      .rejects.toMatchObject({ status: 409 })
  })
})


