// @vitest-environment happy-dom
/**
 * researchService:科研语料库的请求构造与错误映射。
 *
 * 关注三件容易出错的事:
 *   1. 路径里的 docId 必须 encodeURIComponent(论文 id 来自服务端,可能带 / 或空格);
 *   2. 上传走原始字节 + ?name=,Content-Type 不能退化成 multipart,
 *      文件名必须转义(中文/空格文件名);
 *   3. 错误映射:非 2xx 时要么抛带 status 的 HttpError,要么把后端 detail
 *      透传成消息;非 JSON 响应绝不能变成「JSON 解析失败」这种无效提示。
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import * as research from '@/services/researchService'
import { login, userState } from '@/stores/user'

const USER = {
  accountKey: 'acct-research',
  nickname: 'r',
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
  vi.stubGlobal('URL', Object.assign(globalThis.URL, {
    createObjectURL: vi.fn(() => 'blob:research'),
    revokeObjectURL: vi.fn(),
  }))
  vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => undefined)
})

function signIn(token = 'tk-research') {
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
    clone() {
      return this
    },
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


describe('语料库读取:GET 请求构造', () => {
  it('列表 / 元数据 / 分页正文 / 存储用量各自命中正确路径并解包', async () => {
    signIn('tk-list')
    const stub = mockFetch(okJson({ docs: [{ id: 'd1' }] }))
    await expect(research.listResearchDocs()).resolves.toEqual([{ id: 'd1' }])
    const first = lastCall(stub)
    let url = first[0]
    const init = first[1]
    expect(url).toBe('/api/research/docs')
    expect(init.credentials).toBe('include')
    expect(init.headers).toEqual({ Authorization: 'Bearer tk-list' })

    stub.mockResolvedValue(okJson({ doc: { id: 'a/b c' } }))
    await expect(research.getResearchDocMeta('a/b c')).resolves.toEqual({ id: 'a/b c' })
    ;[url] = lastCall(stub)
    // docId 必须转义,否则带 / 的 id 会切到别的路由
    expect(url).toBe('/api/research/docs/a%2Fb%20c')

    stub.mockResolvedValue(okJson({ text: '正文', total: 9, page: 3 }))
    await expect(research.getResearchDocPageText('d1', 3))
      .resolves.toEqual({ text: '正文', total: 9, page: 3 })
    ;[url] = lastCall(stub)
    expect(url).toBe('/api/research/docs/d1/text?page=3')

    stub.mockResolvedValue(okJson({ docs: 2, totalBytes: 1024 }))
    await expect(research.getResearchStorage())
      .resolves.toEqual({ docs: 2, totalBytes: 1024 })
    ;[url] = lastCall(stub)
    expect(url).toBe('/api/research/storage')
  })

  it('章节树 / 洞察按契约发请求', async () => {
    const stub = mockFetch(okJson({ docId: 'd1', nodes: [{ id: 'n1' }] }))
    await expect(research.getResearchTree('d1')).resolves.toEqual([{ id: 'n1' }])
    expect(lastCall(stub)[0]).toBe('/api/research/tree?docId=d1')

    stub.mockResolvedValue(okJson({ docId: 'd1', cached: true, structure: null }))
    await expect(research.getResearchDocInsights('d1'))
      .resolves.toMatchObject({ cached: true })

    stub.mockResolvedValue(okJson({ docId: 'd1', cached: false, structure: null }))
    await research.generateResearchDocInsights('d1', true)
    const [url, init] = lastCall(stub)
    expect(url).toBe('/api/research/docs/d1/insights')
    expect(init.method).toBe('POST')
    expect(JSON.parse(String(init.body))).toEqual({ refresh: true })
  })

  it('项目列表与清缓存:POST 空体 + Bearer', async () => {
    const stub = mockFetch(okJson({ projects: [{ id: 'p1' }] }))
    await expect(research.listResearchProjects()).resolves.toEqual([{ id: 'p1' }])
    expect(lastCall(stub)[0]).toBe('/api/research/projects')

    stub.mockResolvedValue(okJson({ ok: true }))
    await expect(research.purgeResearchCaches()).resolves.toBeUndefined()
    const [url, init] = lastCall(stub)
    expect(url).toBe('/api/research/cache/purge')
    expect(init.method).toBe('POST')
    expect(init.body).toBe('{}')
  })
})


describe('语料库写入:POST/DELETE 请求构造', () => {
  it('检索默认 topK=8、tree=true,其余过滤条件按需带上', async () => {
    signIn('tk-search')
    const stub = mockFetch(okJson({
      hits: [], total: 0, query: 'q', mode: 'bm25', tree: true, elapsed: 1,
    }))

    await research.searchResearch('梯度下降')

    const [url, init] = lastCall(stub)
    expect(url).toBe('/api/research/search')
    expect(init.method).toBe('POST')
    expect(init.headers).toEqual({
      'Content-Type': 'application/json',
      Authorization: 'Bearer tk-search',
    })
    expect(JSON.parse(String(init.body))).toEqual({
      query: '梯度下降',
      topK: 8,
      tree: true,
    })
  })

  it('检索可指定范围与关闭章节树', async () => {
    const stub = mockFetch(okJson({ hits: [] }))
    await research.searchResearch('q', { topK: 3, docIds: ['d1'], projectId: 'p1', tree: false })
    expect(JSON.parse(String(lastCall(stub)[1].body))).toEqual({
      query: 'q', topK: 3, docIds: ['d1'], projectId: 'p1', tree: false,
    })
  })

  it('阅读进度 / 定位段落 / 截图解释 / 表格抽取都带上 docId 与正文', async () => {
    const stub = mockFetch(okJson({ ok: true }))
    await research.saveReadingProgress('d/1', 12)
    let [url, init] = lastCall(stub)
    expect(url).toBe('/api/research/docs/d%2F1/progress')
    expect(JSON.parse(String(init.body))).toEqual({ page: 12 })

    stub.mockResolvedValue(okJson({ passages: [{ page: 2 }] }))
    await expect(research.locatePaperPassages('d1', '目标函数'))
      .resolves.toEqual({ passages: [{ page: 2 }] })
    ;[url, init] = lastCall(stub)
    expect(url).toBe('/api/research/papers/d1/locate')
    expect(JSON.parse(String(init.body))).toEqual({ query: '目标函数' })

    stub.mockResolvedValue(okJson({ answer: '这张图说明……' }))
    await expect(research.explainRegion('d1', { mime: 'image/png', data: 'AAA' }))
      .resolves.toEqual({ answer: '这张图说明……' })
    ;[url, init] = lastCall(stub)
    expect(url).toBe('/api/research/papers/d1/explain-region')
    expect(JSON.parse(String(init.body))).toEqual({
      image: { mime: 'image/png', data: 'AAA' }, question: '',
    })

    stub.mockResolvedValue(okJson({ table: { title: 'T' }, docId: 'd1', page: 4 }))
    await research.extractPaperTable('d1', { mime: 'image/png', data: 'AAA' }, 4)
    ;[url, init] = lastCall(stub)
    expect(url).toBe('/api/research/papers/d1/extract-table')
    expect(JSON.parse(String(init.body))).toEqual({
      image: { mime: 'image/png', data: 'AAA' }, page: 4,
    })
  })
})


describe('项目增删改、清空论文库与多文献对比', () => {
  it('创建/更新项目、清空论文库、删除项目、对比文献', async () => {
    const stub = mockFetch(okJson({ project: { id: 'p1', title: '新项目' } }))
    await expect(research.createResearchProject('新项目'))
      .resolves.toEqual({ id: 'p1', title: '新项目' })
    let [url, init] = lastCall(stub)
    expect(url).toBe('/api/research/projects')
    expect(JSON.parse(String(init.body))).toEqual({ title: '新项目' })

    stub.mockResolvedValue(okJson({ project: { id: 'p1', status: 'done' } }))
    await research.updateResearchProject('p 1', { status: 'done' })
    ;[url, init] = lastCall(stub)
    expect(url).toBe('/api/research/projects/p%201')
    expect(JSON.parse(String(init.body))).toEqual({ status: 'done' })

    stub.mockResolvedValue(okJson({ ok: true, removed: 3 }))
    await expect(research.clearResearchDocs()).resolves.toBe(3)
    ;[url, init] = lastCall(stub)
    expect(url).toBe('/api/research/docs')
    expect(init.method).toBe('DELETE')

    stub.mockResolvedValue(okJson({ ok: true }))
    await expect(research.deleteResearchProject('p1')).resolves.toBeUndefined()
    ;[url, init] = lastCall(stub)
    expect(url).toBe('/api/research/projects/p1')
    expect(init.method).toBe('DELETE')

    stub.mockResolvedValue(okJson({ title: '对比表', rows: [] }))
    await expect(research.compareResearchDocs(['d1', 'd2']))
      .resolves.toMatchObject({ title: '对比表' })
    ;[url, init] = lastCall(stub)
    expect(url).toBe('/api/research/literature/compare')
    expect(JSON.parse(String(init.body))).toEqual({ docIds: ['d1', 'd2'] })
  })

  it('删除论文与旧档案导入', async () => {
    const stub = mockFetch(okJson({ ok: true }))
    await expect(research.deleteResearchDoc('d 1')).resolves.toBeUndefined()
    const [url, init] = lastCall(stub)
    expect(url).toBe('/api/research/docs/d%201')
    expect(init.method).toBe('DELETE')

    stub.mockResolvedValue(okJson({ duplicate: false, projects: 1, files: 2 }))
    await expect(research.importLegacyResearchArchive({ projects: [] }))
      .resolves.toEqual({ duplicate: false, projects: 1, files: 2 })
    expect(JSON.parse(String(lastCall(stub)[1].body))).toEqual({ projects: [] })
  })
})

describe('上传:原始字节 + ?name=', () => {
  it('PDF 上传按文件类型与文件名转义发请求,可带 projectId', async () => {
    signIn('tk-up')
    const stub = mockFetch(okJson({ docId: 'd9', duplicate: false, pages: 3 }))
    const file = new File(['%PDF-1.7'], '论文 一.pdf', { type: '' })

    const result = await research.uploadResearchDoc(file, 'proj/1')

    expect(result).toEqual({ docId: 'd9', duplicate: false, pages: 3 })
    const [url, init] = lastCall(stub)
    expect(url).toBe(
      '/api/research/docs?name=%E8%AE%BA%E6%96%87%20%E4%B8%80.pdf&projectId=proj%2F1',
    )
    expect(init.method).toBe('POST')
    expect(init.credentials).toBe('include')
    // 类型缺省时按扩展名推断,不能退化成 multipart
    expect(init.headers).toEqual({
      'Content-Type': 'application/pdf',
      Authorization: 'Bearer tk-up',
    })
    expect(init.body).toBe(file)
  })

  it('临时语料上传加 temp=1,文本论文用 text/plain', async () => {
    const stub = mockFetch(okJson({ docId: 'tmp1', duplicate: true, status: 'parsed' }))
    const file = new File(['hello'], 'note.txt', { type: '' })

    await research.uploadTempPaper(file)

    const [url, init] = lastCall(stub)
    expect(url).toBe('/api/research/docs?name=note.txt&temp=1')
    expect((init.headers as Record<string, string>)['Content-Type']).toBe('text/plain')
  })

  it('上传失败时把后端 detail 透传成消息', async () => {
    mockFetch(errorResponse(400, { json: { detail: '不支持的格式' } }))

    await expect(research.uploadResearchDoc(new File(['x'], 'a.pdf', { type: 'application/pdf' })))
      .rejects.toMatchObject({ status: 400, message: '不支持的格式' })
  })

  it('上传失败且响应不是 JSON → 保持状态码提示,不抛解析错', async () => {
    mockFetch(errorResponse(413, { body: '<html>too large</html>' }))

    await expect(research.uploadResearchDoc(new File(['x'], 'a.pdf', { type: 'application/pdf' })))
      .rejects.toMatchObject({ status: 413, message: 'HTTP 413' })
  })

describe('错误映射', () => {
  it('404 + JSON 错误体 → 抛带 status 的 HttpError(调用方可区分未找到)', async () => {
    mockFetch(errorResponse(404, { json: { detail: 'doc not found' } }))

    await expect(research.getResearchDocMeta('missing'))
      .rejects.toMatchObject({ status: 404, message: 'HTTP 404' })
  })

  it('502 + 非 JSON 体 → 消息仍是状态码,不会冒出 JSON 解析错', async () => {
    mockFetch(errorResponse(502, { body: '<html>bad gateway</html>' }))

    const error = await research.getResearchStorage().catch((err: Error) => err)
    expect(error).toBeInstanceOf(Error)
    expect((error as Error & { status: number }).status).toBe(502)
    expect((error as Error).message).toBe('HTTP 502')
  })

  it('409 冲突(重名项目)原样上抛给调用方处理', async () => {
    mockFetch(errorResponse(409, { json: { detail: 'exists' } }))

    await expect(research.createResearchProject('重复'))
      .rejects.toMatchObject({ status: 409 })
  })

  it('401 → 状态码可被 statusOf 识别(上层据此回登录页)', async () => {
    mockFetch(errorResponse(401, { json: { detail: 'unauthorized' } }))

    await expect(research.listResearchDocs()).rejects.toMatchObject({ status: 401 })
  })

  it('网络异常 → 原样抛出,不会被当成空结果', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => {
      throw new TypeError('Failed to fetch')
    }))

    await expect(research.listResearchDocs()).rejects.toThrow('Failed to fetch')
    await expect(research.searchResearch('q')).rejects.toThrow('Failed to fetch')
  })
})

describe('研究报告下载', () => {
  it('按项目导出 DOCX,文件名从 Content-Disposition 解码', async () => {
    signIn('tk-report')
    const blob = new Blob(['docx-bytes'], {
      type: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    })
    const stub = mockFetch({
      ok: true,
      status: 200,
      blob: async () => blob,
      headers: {
        get: (name: string) => (name === 'Content-Disposition'
          ? "attachment; filename*=UTF-8''%E7%A0%94%E7%A9%B6%E6%8A%A5%E5%91%8A.docx"
          : null),
      },
    })

    await expect(research.downloadResearchReport('p1', ['t1'])).resolves.toBeUndefined()

    const [url, init] = lastCall(stub)
    expect(url).toBe('/api/research/report')
    expect(init.method).toBe('POST')
    expect(init.credentials).toBe('include')
    expect(init.headers).toEqual({
      'Content-Type': 'application/json',
      Authorization: 'Bearer tk-report',
    })
    expect(JSON.parse(String(init.body))).toEqual({ projectId: 'p1', tableIds: ['t1'] })
    expect(URL.createObjectURL).toHaveBeenCalled()
    expect(HTMLAnchorElement.prototype.click).toHaveBeenCalled()
  })

  it('没有 Content-Disposition 时用默认文件名', async () => {
    mockFetch({
      ok: true,
      status: 200,
      blob: async () => new Blob(['x']),
      headers: { get: () => null },
    })
    const anchors: string[] = []
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function (
      this: HTMLAnchorElement,
    ) {
      anchors.push(this.download)
    })

    await research.downloadResearchReport('p1')

    expect(anchors).toEqual(['研究报告.docx'])
  })

  it('非 2xx 时不生成文件,抛带状态码的错误', async () => {
    mockFetch({
      ok: false,
      status: 500,
      blob: async () => new Blob([]),
      headers: { get: () => null },
    })

    await expect(research.downloadResearchReport('p1'))
      .rejects.toThrow('HTTP 500')
  })
})

})
