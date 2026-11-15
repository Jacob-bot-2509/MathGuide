// @vitest-environment happy-dom
/**
 * researchTableService:科研数据表的请求构造与错误映射。
 *
 * 数据表这条链路有几个「静默出错」的地方:
 *   1. 表 id 来自服务端,必须 encodeURIComponent;
 *   2. 没有 tableId/docId 时查已存公式要直接返回空数组(不能发无参请求);
 *   3. 回归接口开启 readErrorDetail —— 后端把「次数过高/样本不足」
 *      放在 detail 里,必须透传成用户能看懂的消息,而不是 HTTP 400;
 *   4. 导出必须带 Bearer 头(不能直接 <a href>),文件名回退不能是 undefined.csv。
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import * as tables from '@/services/researchTableService'
import { login, userState } from '@/stores/user'

const USER = {
  accountKey: 'acct-table',
  nickname: 't',
  avatar: 'preset:sum',
  authMethod: 'phone-pass' as const,
}

const memory = new Map<string, string>()
let downloads: string[] = []

beforeEach(() => {
  memory.clear()
  userState.info = null
  downloads = []
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
  const holder = globalThis.URL as unknown as Record<string, unknown>
  if (typeof holder.createObjectURL !== 'function') holder.createObjectURL = () => 'blob:table'
  if (typeof holder.revokeObjectURL !== 'function') holder.revokeObjectURL = () => {}
  vi.spyOn(URL, 'createObjectURL').mockReturnValue('blob:table')
  vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => undefined)
  vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function (
    this: HTMLAnchorElement,
  ) {
    downloads.push(this.download)
  })
})

function signIn(token = 'tk-table') {
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

const PAYLOAD: tables.TablePayload = {
  title: '测量数据',
  columns: [{ key: 'x', label: 'x', type: 'number' }],
  rows: [['1'], ['2']],
  formulas: {},
  rowLabels: [],
  merges: [],
  colWidths: [],
  rowHeights: [],
}

describe('表的增删改查', () => {
  it('列表可按项目过滤,表 id 会被转义', async () => {
    signIn('tk-table')
    const stub = mockFetch(okJson({ tables: [{ id: 't1' }] }))

    await expect(tables.listResearchTables('p 1')).resolves.toEqual([{ id: 't1' }])
    const first = lastCall(stub)
    let url = first[0]
    const init = first[1]
    expect(url).toBe('/api/research/tables?projectId=p%201')
    expect(init.credentials).toBe('include')
    expect(init.headers).toEqual({ Authorization: 'Bearer tk-table' })

    await tables.listResearchTables()
    ;[url] = lastCall(stub)
    expect(url).toBe('/api/research/tables')

    stub.mockResolvedValue(okJson({ table: { id: 't/1' } }))
    await expect(tables.getResearchTable('t/1')).resolves.toEqual({ id: 't/1' })
    ;[url] = lastCall(stub)
    expect(url).toBe('/api/research/tables/t%2F1')
  })

  it('创建 / 保存 / 计算都把整张表原样提交', async () => {
    const stub = mockFetch(okJson({ table: { id: 't1' } }))
    await tables.createResearchTable(PAYLOAD)
    let [url, init] = lastCall(stub)
    expect(url).toBe('/api/research/tables')
    expect(init.method).toBe('POST')
    expect(JSON.parse(String(init.body))).toEqual(PAYLOAD)

    stub.mockResolvedValue(okJson({ table: { id: 't1' } }))
    await tables.saveResearchTable('t1', PAYLOAD)
    ;[url, init] = lastCall(stub)
    expect(url).toBe('/api/research/tables/t1')
    expect(JSON.parse(String(init.body))).toEqual(PAYLOAD)

    stub.mockResolvedValue(okJson({ table: { id: 't1' }, computed: { c1: ['3'] }, errors: [] }))
    await expect(tables.computeResearchTable('t1', PAYLOAD))
      .resolves.toMatchObject({ computed: { c1: ['3'] } })
    ;[url, init] = lastCall(stub)
    expect(url).toBe('/api/research/tables/t1/compute')
  })

  it('统计 / 打印 / 删除(hard 带查询参数)', async () => {
    const stub = mockFetch(okJson({ stats: [], correlations: [], series: [] }))
    await tables.statsResearchTable('t1', PAYLOAD)
    let [url] = lastCall(stub)
    expect(url).toBe('/api/research/tables/t1/stats')

    stub.mockResolvedValue(okJson({ ok: true, opened: true, file: 'a.xlsx' }))
    await expect(tables.printResearchTable('t1', PAYLOAD))
      .resolves.toEqual({ ok: true, opened: true, file: 'a.xlsx' })
    ;[url] = lastCall(stub)
    expect(url).toBe('/api/research/tables/t1/print')

    stub.mockResolvedValue(okJson({ ok: true }))
    await tables.deleteResearchTable('t1')
    ;[url] = lastCall(stub)
    expect(url).toBe('/api/research/tables/t1')

    await tables.deleteResearchTable('t1', true)
    const [hardUrl, hardInit] = lastCall(stub)
    expect(hardUrl).toBe('/api/research/tables/t1?hard=1')
    expect(hardInit.method).toBe('DELETE')
  })
})

describe('公式识别与校验', () => {
  it('整页分析 / 公式抽取把图片与元数据一起提交', async () => {
    signIn('tk-formula')
    const stub = mockFetch(okJson({ blocks: [], warnings: [], saved: 0 }))

    await tables.analyzeResearchPage([{ mime: 'image/png', data: 'A' }], '正文', { docId: 'd1', page: 2 })
    let [url, init] = lastCall(stub)
    expect(url).toBe('/api/research/pages/analyze')
    expect(JSON.parse(String(init.body))).toEqual({
      images: [{ mime: 'image/png', data: 'A' }], text: '正文', docId: 'd1', page: 2,
    })

    stub.mockResolvedValue(okJson({ formulas: [], groups: [], master: null, warnings: [] }))
    await tables.extractFormulas([{ mime: 'image/png', data: 'A' }], PAYLOAD.columns, 't', { tableId: 't1' })
    ;[url, init] = lastCall(stub)
    expect(url).toBe('/api/research/formulas/extract')
    expect(JSON.parse(String(init.body))).toEqual({
      images: [{ mime: 'image/png', data: 'A' }],
      columns: PAYLOAD.columns,
      text: 't',
      tableId: 't1',
    })
  })

  it('匹配候选公式 / 猜标题 / 校验公式', async () => {
    const stub = mockFetch(okJson({ candidates: [{ formulaId: 'f1' }] }))
    await expect(tables.matchTableFormulas('t1', 'd1'))
      .resolves.toEqual([{ formulaId: 'f1' }])
    let [url, init] = lastCall(stub)
    expect(url).toBe('/api/research/tables/t1/match-formulas')
    expect(JSON.parse(String(init.body))).toEqual({ docId: 'd1' })

    stub.mockResolvedValue(okJson({ title: '自由落体', confidence: 0.9 }))
    await expect(tables.suggestTableTopic('t1'))
      .resolves.toEqual({ title: '自由落体', confidence: 0.9 })
    ;[url, init] = lastCall(stub)
    expect(url).toBe('/api/research/tables/t1/suggest-topic')
    expect(init.body).toBe('{}')

    stub.mockResolvedValue(okJson({ columnKey: 'c1', matched: 2, compared: 2 }))
    await tables.validateTableFormula('t1', 'c1', 'x+1')
    ;[url, init] = lastCall(stub)
    expect(url).toBe('/api/research/tables/t1/validate-formula')
    expect(JSON.parse(String(init.body))).toEqual({ columnKey: 'c1', formula: 'x+1' })
  })

  it('已存公式:没有过滤条件时不发请求,直接返回空数组', async () => {
    const stub = mockFetch(okJson({ formulas: [{ id: 'f1' }] }))

    await expect(tables.listSavedFormulas()).resolves.toEqual([])
    expect(stub).not.toHaveBeenCalled()

    await tables.listSavedFormulas('t1', 'd1')
    const [url] = lastCall(stub)
    expect(url).toBe('/api/research/formulas?tableId=t1&docId=d1')
  })
})


describe('回归与错误映射', () => {
  it('回归把表与规格合并提交,并透传后端 detail 作为消息', async () => {
    const stub = mockFetch(errorResponse(400, { json: { detail: '样本量不足' } }))

    await expect(tables.regressResearchTable('t1', PAYLOAD, {
      x: ['x'], y: 'y', model: 'poly', degree: 2,
    })).rejects.toMatchObject({ status: 400, message: '样本量不足' })

    const [url, init] = lastCall(stub)
    expect(url).toBe('/api/research/tables/t1/regression')
    expect(JSON.parse(String(init.body))).toEqual({
      ...PAYLOAD,
      regression: { x: ['x'], y: 'y', model: 'poly', degree: 2 },
    })
  })

  it('回归成功时解包结果', async () => {
    mockFetch(okJson({ model: 'ols', n: 10, equation: 'y = 2x + 1', warnings: [] }))

    await expect(tables.regressResearchTable('t1', PAYLOAD, { x: ['x'], y: 'y', model: 'ols' }))
      .resolves.toMatchObject({ equation: 'y = 2x + 1' })
  })

  it('回归接口返回非 JSON 错误体 → 状态码消息,不抛解析错', async () => {
    // 超过 100 字符的错误体不会被当成用户提示,回落到状态码
    mockFetch(errorResponse(500, { body: `<html>${'x'.repeat(200)}</html>` }))

    await expect(tables.regressResearchTable('t1', PAYLOAD, { x: ['x'], y: 'y', model: 'ols' }))
      .rejects.toMatchObject({ status: 500, message: 'HTTP 500' })
  })

  it('回归接口返回短文本错误体 → 原样作为提示(不是 JSON 解析错误)', async () => {
    mockFetch(errorResponse(400, { body: '样本量不足' }))

    await expect(tables.regressResearchTable('t1', PAYLOAD, { x: ['x'], y: 'y', model: 'ols' }))
      .rejects.toMatchObject({ status: 400, message: '样本量不足' })
  })

  it('404 + JSON 错误体(表已删)→ 带 status 上抛', async () => {
    mockFetch(errorResponse(404, { json: { detail: 'table not found' } }))

    await expect(tables.getResearchTable('t1')).rejects.toMatchObject({ status: 404 })
  })

  it('网络异常 → 原样上抛,不会被当成空表', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => {
      throw new TypeError('Failed to fetch')
    }))

    await expect(tables.getResearchTable('t1')).rejects.toThrow('Failed to fetch')
  })
})

describe('导入导出', () => {
  it('导入:原始字节 + ?name=,#可带 projectId,类型缺省用 octet-stream', async () => {
    const stub = mockFetch(okJson({ table: { id: 't9' } }))
    const file = new File(['a,b'], '数据 表', { type: '' })

    await expect(tables.importResearchTable(file, 'p1')).resolves.toEqual({ id: 't9' })

    const [url, init] = lastCall(stub)
    expect(url).toBe('/api/research/tables/import?name=%E6%95%B0%E6%8D%AE%20%E8%A1%A8&projectId=p1')
    expect(init.method).toBe('POST')
    expect((init.headers as Record<string, string>)['Content-Type']).toBe('application/octet-stream')
    expect(init.body).toBe(file)
  })

  it('导出:必须带 Bearer 头与 credentials,文件名用标题', async () => {
    signIn('tk-dl')
    const stub = mockFetch({
      ok: true,
      status: 200,
      blob: async () => new Blob(['x']),
      headers: { get: () => null },
    })

    await tables.downloadResearchTable('t1', 'csv', '实验一')

    const [url, init] = lastCall(stub)
    expect(url).toBe('/api/research/tables/t1/export?format=csv')
    expect(init.credentials).toBe('include')
    expect(init.headers).toEqual({ Authorization: 'Bearer tk-dl' })
    expect(downloads).toEqual(['实验一.csv'])
    expect(URL.revokeObjectURL).toHaveBeenCalled()
  })

  it('导出:没有标题时回退 table.<format>', async () => {
    mockFetch({
      ok: true,
      status: 200,
      blob: async () => new Blob(['x']),
      headers: { get: () => null },
    })

    await tables.downloadResearchTable('t1', 'xlsx', '')

    expect(downloads).toEqual(['table.xlsx'])
  })

  it('导出失败 → 抛状态码错误,不生成文件', async () => {
    mockFetch({
      ok: false,
      status: 403,
      blob: async () => new Blob([]),
      headers: { get: () => null },
    })

    await expect(tables.downloadResearchTable('t1', 'csv', 'T')).rejects.toThrow('HTTP 403')
    expect(downloads).toEqual([])
  })
})

