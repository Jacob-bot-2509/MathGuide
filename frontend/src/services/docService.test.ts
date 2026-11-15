// @vitest-environment happy-dom
/**
 * docService:文档导出(二进制响应)的请求构造与错误映射。
 *
 * 这层只做三件事,但每件都可能出错:
 *   1. 带 token POST,responseType 是二进制 —— 文件名只能从 Content-Disposition 拿;
 *   2. 401 与聊天的口径一致:清登录态 + 回登录页 + 过期提示,再抛错;
 *   3. 非 2xx 时后端可能把 Word 公式转换失败的原因放在 detail 里(要透传),
 *      也可能返回 HTML 网关错误(不能变成 JSON 解析错误)。
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'

const hoisted = vi.hoisted(() => ({ push: vi.fn(), toast: vi.fn() }))
vi.mock('@/router', () => ({ default: { push: hoisted.push } }))
vi.mock('@/utils/toast', () => ({ showToast: hoisted.toast }))

import { downloadBlob, exportSurveyPdf, postBinary } from '@/services/docService'
import { login, userState } from '@/stores/user'
import { t } from '@/utils/i18n'

const USER = {
  accountKey: 'acct-doc',
  nickname: 'd',
  avatar: 'preset:sum',
  authMethod: 'phone-pass' as const,
}

const memory = new Map<string, string>()
let downloads: string[] = []

beforeEach(() => {
  memory.clear()
  downloads = []
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
  const holder = globalThis.URL as unknown as Record<string, unknown>
  if (typeof holder.createObjectURL !== 'function') holder.createObjectURL = () => 'blob:doc'
  if (typeof holder.revokeObjectURL !== 'function') holder.revokeObjectURL = () => {}
  vi.spyOn(URL, 'createObjectURL').mockReturnValue('blob:doc')
  vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => undefined)
  vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function (
    this: HTMLAnchorElement,
  ) {
    downloads.push(this.download)
  })
})

function signIn(token = 'tk-doc') {
  login({ ...USER, token })
}

function binaryResponse(opts: {
  status?: number
  disposition?: string | null
  res?: Response
} = {}) {
  const status = opts.status ?? 200
  return {
    ok: status >= 200 && status < 300,
    status,
    blob: async () => new Blob(['pdf-bytes'], { type: 'application/pdf' }),
    headers: {
      get: (name: string) => (name === 'Content-Disposition' ? (opts.disposition ?? null) : null),
    },
    json: async () => {
      throw new SyntaxError('Unexpected token <')
    },
    text: async () => '<html>bad gateway</html>',
  }
}

describe('postBinary', () => {
  it('带 token POST JSON,文件名取自 Content-Disposition', async () => {
    signIn('tk-doc')
    const stub = vi.fn(async () => binaryResponse({
      disposition: 'attachment; filename="综述-2026.pdf"',
    }))
    vi.stubGlobal('fetch', stub)

    const result = await postBinary('/api/doc/render', { document: { title: 'T' }, lang: 'zh' })

    const [url, init] = stub.mock.calls[0] as unknown as [string, RequestInit]
    expect(url).toBe('/api/doc/render')
    expect(init.method).toBe('POST')
    expect(init.headers).toEqual({
      'Content-Type': 'application/json',
      Authorization: 'Bearer tk-doc',
    })
    expect(JSON.parse(String(init.body))).toEqual({ document: { title: 'T' }, lang: 'zh' })
    expect(result.filename).toBe('综述-2026.pdf')
    expect(await result.blob.text()).toBe('pdf-bytes')
  })

  it('没有 Content-Disposition 时回退 mg-document(不能是 undefined)', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => binaryResponse()))

    await expect(postBinary('/api/doc/render', {})).resolves.toMatchObject({
      filename: 'mg-document',
    })
  })

  it('未登录时不发空的 Bearer 头', async () => {
    const stub = vi.fn(async () => binaryResponse())
    vi.stubGlobal('fetch', stub)

    await postBinary('/api/doc/qa', {})

    const init = (stub.mock.calls[0] as unknown as [string, RequestInit])[1]
    expect(init.headers).toEqual({ 'Content-Type': 'application/json' })
  })

  it('401 → 清登录态 + 回登录页 + 过期提示,并抛 HttpError', async () => {
    signIn('tk-expired')
    vi.stubGlobal('fetch', vi.fn(async () => binaryResponse({ status: 401 })))

    await expect(postBinary('/api/doc/render', {})).rejects.toMatchObject({ status: 401 })
    expect(userState.info).toBeNull()
    expect(hoisted.push).toHaveBeenCalledWith('/login')
    expect(hoisted.toast).toHaveBeenCalledWith(t('login.toastExpired'))
  })

  it('公式无法转 Word 时透传后端 detail 作为提示', async () => {
    const detail = 'Formula cannot be converted to Word: \\frac 结构不支持'
    vi.stubGlobal('fetch', vi.fn(async () => ({
      ok: false,
      status: 500,
      headers: { get: () => null },
      json: async () => ({ detail }),
    })))

    await expect(postBinary('/api/doc/render', {})).rejects.toMatchObject({ message: detail })
  })

  it('其他 detail 不改消息(保持状态码,避免把内部错误原文给用户)', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => ({
      ok: false,
      status: 500,
      headers: { get: () => null },
      json: async () => ({ detail: 'internal traceback line 42' }),
    })))

    await expect(postBinary('/api/doc/render', {})).rejects.toMatchObject({
      status: 500,
      message: 'HTTP 500',
    })
  })

  it('非 JSON 错误体(网关 HTML)→ 状态码消息,不抛 JSON 解析错', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => binaryResponse({ status: 502 })))

    await expect(postBinary('/api/doc/render', {})).rejects.toMatchObject({
      status: 502,
      message: 'HTTP 502',
    })
  })

  it('网络异常 → 原样上抛', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => {
      throw new TypeError('Failed to fetch')
    }))

    await expect(postBinary('/api/doc/render', {})).rejects.toThrow('Failed to fetch')
  })
})

describe('exportSurveyPdf', () => {
  it('按语言导出综述 PDF,文件名取自响应头', async () => {
    signIn('tk-pdf')
    const stub = vi.fn(async () => binaryResponse({
      disposition: 'attachment; filename="survey.pdf"',
    }))
    vi.stubGlobal('fetch', stub)

    const result = await exportSurveyPdf('# 正文', 'en')

    const [url, init] = stub.mock.calls[0] as unknown as [string, RequestInit]
    expect(url).toBe('/api/doc/export')
    expect(init.method).toBe('POST')
    expect(init.headers).toEqual({
      'Content-Type': 'application/json',
      Authorization: 'Bearer tk-pdf',
    })
    expect(JSON.parse(String(init.body))).toEqual({ content: '# 正文', lang: 'en' })
    expect(result.filename).toBe('survey.pdf')
  })

  it('没有 Content-Disposition 时按语言回退文件名', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => binaryResponse()))

    await expect(exportSurveyPdf('x', 'zh')).resolves.toMatchObject({
      filename: 'mg-survey-zh.pdf',
    })
  })

  it('401 → 清登录态 + 跳登录页 + 提示,异常上抛', async () => {
    signIn('tk-expired')
    vi.stubGlobal('fetch', vi.fn(async () => binaryResponse({ status: 401 })))

    await expect(exportSurveyPdf('x', 'zh')).rejects.toMatchObject({ status: 401 })
    expect(userState.info).toBeNull()
    expect(memory.has('mg-user')).toBe(false)
    expect(hoisted.push).toHaveBeenCalledWith('/login')
    expect(hoisted.toast).toHaveBeenCalledTimes(1)
  })

  it('500 + 非 JSON 错误体 → 状态码异常,不返回空 Blob', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => binaryResponse({ status: 500 })))

    await expect(exportSurveyPdf('x', 'zh')).rejects.toMatchObject({
      status: 500,
      message: 'HTTP 500',
    })
  })

  it('网络异常 → 原样上抛', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => {
      throw new TypeError('Failed to fetch')
    }))

    await expect(exportSurveyPdf('x', 'zh')).rejects.toThrow('Failed to fetch')
  })
})

describe('downloadBlob', () => {
  it('生成临时 URL、触发下载并立即回收', () => {
    downloadBlob(new Blob(['x']), '报告.pdf')

    expect(URL.createObjectURL).toHaveBeenCalledTimes(1)
    expect(downloads).toEqual(['报告.pdf'])
    expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:doc')
  })
})


