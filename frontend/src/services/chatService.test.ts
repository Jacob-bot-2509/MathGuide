/**
 * chatService:聊天/语音/直观解释三条 SSE 入口的请求构造与错误映射。
 *
 * 为什么这条链路值得测:流式接口的错误不是「抛一个异常」那么局部 ——
 * 401 要在提示的同时清登录态回登录页,429 要按限流提示收尾(不踢人),
 * 断流(没有 [DONE])必须让界面知道回答是半截的。任何一条走错,
 * 用户就会看到「消失的回答」或者被莫名其妙踢回登录页。
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'

const hoisted = vi.hoisted(() => ({ push: vi.fn(), toast: vi.fn() }))
vi.mock('@/router', () => ({ default: { push: hoisted.push } }))
vi.mock('@/utils/toast', () => ({ showToast: hoisted.toast }))

import { requestIntuition, speechToMath, streamReply } from '@/services/chatService'
import { login, userState } from '@/stores/user'
import { t } from '@/utils/i18n'

const memory = new Map<string, string>()

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

/** 构造一个 OpenAI 兼容 SSE 响应(data: 行) */
function sseResponse(frames: string[]) {
  const text = frames.map((frame) => `data: ${frame}\n`).join('')
  const stream = new ReadableStream<Uint8Array>({
    start(controller) {
      controller.enqueue(new TextEncoder().encode(text))
      controller.close()
    },
  })
  return {
    ok: true,
    status: 200,
    body: stream,
    headers: { get: () => null },
  }
}

function errorResponse(status: number, opts: { json?: unknown; text?: string } = {}) {
  return {
    ok: false,
    status,
    body: null,
    headers: { get: () => null },
    json: async () => {
      if (opts.json === undefined) throw new SyntaxError('Unexpected token <')
      return opts.json
    },
    text: async () => opts.text ?? '',
  }
}

const USER = {
  accountKey: 'acct-chat',
  nickname: 'chat',
  avatar: 'preset:sum',
  authMethod: 'phone-pass' as const,
}

function signIn(token = 'tk-chat') {
  login({ ...USER, token })
}

function callbacks() {
  return {
    onDelta: vi.fn(),
    onDone: vi.fn(),
    onError: vi.fn(),
    onMeta: vi.fn(),
  }
}

beforeEach(() => {
  memory.clear()
  installStorage()
  hoisted.push.mockClear()
  hoisted.toast.mockClear()
  userState.info = null
  vi.spyOn(console, 'error').mockImplementation(() => undefined)
})


describe('streamReply:请求构造', () => {
  it('带齐会话元数据时 body 与鉴权头完全按契约发出', async () => {
    const fetchStub = vi.fn(async () => sseResponse([
      '"你好"', '{"kind":"research"}', 'plain 文本', '[DONE]',
    ]))
    vi.stubGlobal('fetch', fetchStub)
    signIn('tk-chat')
    const cb = callbacks()

    streamReply('求导数', cb, {
      cmd: 'solve',
      sessionId: 7,
      workspace: 'research',
      categoryKey: 'derivative',
      history: [{ role: 'user', content: '上一轮' }],
      sources: ['arxiv', 'crossref'],
      resume: true,
      partial: '前半段',
      paperId: 'paper-1',
      tableId: 'table-1',
      tableRegression: { x: ['t'], y: 'y', model: 'ols' },
      diagrams: true,
      pointId: 'chain-rule',
    })

    await vi.waitFor(() => expect(cb.onDone).toHaveBeenCalled())

    const [url, init] = fetchStub.mock.calls[0] as unknown as [string, RequestInit]
    expect(url).toBe('/api/chat/stream')
    expect(init.method).toBe('POST')
    expect(init.credentials).toBe('include')
    expect(init.headers).toEqual({
      'Content-Type': 'application/json',
      Authorization: 'Bearer tk-chat',
    })
    expect(init.signal).toBeInstanceOf(AbortSignal)
    expect(JSON.parse(String(init.body))).toEqual({
      prompt: '求导数',
      cmd: 'solve',
      sessionId: 7,
      workspace: 'research',
      categoryKey: 'derivative',
      history: [{ role: 'user', content: '上一轮' }],
      sources: ['arxiv', 'crossref'],
      resume: true,
      partial: '前半段',
      paperId: 'paper-1',
      tableId: 'table-1',
      tableRegression: { x: ['t'], y: 'y', model: 'ols' },
      diagrams: true,
      pointId: 'chain-rule',
    })

    // 增量、元信息帧、全文累积
    expect(cb.onDelta.mock.calls.map((call) => call[0]))
      .toEqual(['你好', 'plain 文本'])
    expect(cb.onMeta).toHaveBeenCalledWith({ kind: 'research' })
    expect(cb.onDone).toHaveBeenCalledWith('你好plain 文本', true)
    expect(cb.onError).not.toHaveBeenCalled()
  })

  it('不传 meta 时 body 只有 prompt(未选字段不进请求)', async () => {
    const fetchStub = vi.fn(async () => sseResponse(['"ok"', '[DONE]']))
    vi.stubGlobal('fetch', fetchStub)
    const cb = callbacks()

    streamReply('你好', cb)
    await vi.waitFor(() => expect(cb.onDone).toHaveBeenCalled())

    const init = (fetchStub.mock.calls[0] as unknown as [string, RequestInit])[1]
    // 未登录时不加 Authorization 头,不能发出空 Bearer
    expect(init.headers).toEqual({ 'Content-Type': 'application/json' })
    expect(JSON.parse(String(init.body))).toEqual({ prompt: '你好' })
    expect(cb.onDone).toHaveBeenCalledWith('ok', true)
  })

  it('没有收到 [DONE] 就断流 → complete=false(半截回答要能被界面识别)', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => sseResponse(['"半截回答"'])))
    const cb = callbacks()

    streamReply('你好', cb)
    await vi.waitFor(() => expect(cb.onDone).toHaveBeenCalled())

    expect(cb.onDone).toHaveBeenCalledWith('半截回答', false)
    expect(cb.onError).not.toHaveBeenCalled()
  })

  it('cancel() 会中止底层请求的 signal', async () => {
    const fetchStub = vi.fn(async () => sseResponse(['[DONE]']))
    vi.stubGlobal('fetch', fetchStub)

    const handle = streamReply('你好', callbacks())
    const init = (fetchStub.mock.calls[0] as unknown as [string, RequestInit])[1]
    expect((init.signal as AbortSignal).aborted).toBe(false)

    handle.cancel()
    expect((init.signal as AbortSignal).aborted).toBe(true)
  })
})

describe('streamReply:错误映射', () => {
  it('401 → 清登录态 + 回登录页 + 过期提示(不再回调 onDone 叠中断标记)', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => errorResponse(401, { json: { detail: 'unauthorized' } })))
    signIn('tk-expired')
    const cb = callbacks()

    streamReply('你好', cb)

    await vi.waitFor(() => expect(hoisted.push).toHaveBeenCalledWith('/login'))
    expect(userState.info).toBeNull()
    expect(hoisted.toast).toHaveBeenCalledWith(t('login.toastExpired'))
    expect(memory.has('mg-user')).toBe(false)
    expect(cb.onDone).not.toHaveBeenCalled()
    expect(cb.onError).not.toHaveBeenCalled()
  })

  it('429 → 走限流提示(path 的 onError + 空收尾),不踢回登录页', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => errorResponse(429, { json: { detail: 'slow down' } })))
    signIn('tk-chat')
    const cb = callbacks()

    streamReply('你好', cb)

    await vi.waitFor(() => expect(cb.onDone).toHaveBeenCalledWith('', false))
    expect(cb.onError).toHaveBeenCalledTimes(1)
    expect((cb.onError.mock.calls[0][0] as { status: number }).status).toBe(429)
    expect(hoisted.push).not.toHaveBeenCalled()
    expect(userState.info).not.toBeNull()
  })

  it('500 + JSON 错误体 → onError + 空收尾(false),消息带状态码', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => errorResponse(500, { json: { detail: 'boom' } })))
    const cb = callbacks()

    streamReply('你好', cb)

    await vi.waitFor(() => expect(cb.onDone).toHaveBeenCalledWith('', false))
    const err = cb.onError.mock.calls[0][0] as Error & { status: number }
    expect(err.status).toBe(500)
    expect(err.message).toBe('HTTP 500')
  })

  it('502 + 非 JSON 错误体(网关 HTML) → 不抛 JSON 解析错,按状态码收尾', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => errorResponse(502, { text: '<html>bad gateway</html>' })))
    const cb = callbacks()

    streamReply('你好', cb)

    await vi.waitFor(() => expect(cb.onDone).toHaveBeenCalledWith('', false))
    const err = cb.onError.mock.calls[0][0] as Error & { status: number }
    expect(err).toBeInstanceOf(Error)
    expect(err.status).toBe(502)
    expect(err.message).toBe('HTTP 502')
  })

  it('网络异常(fetch 直接抛) → onError + 空收尾', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => {
      throw new TypeError('Failed to fetch')
    }))
    const cb = callbacks()

    streamReply('你好', cb)

    await vi.waitFor(() => expect(cb.onDone).toHaveBeenCalledWith('', false))
    expect((cb.onError.mock.calls[0][0] as Error).message).toBe('Failed to fetch')
  })

  it('响应没有 body → 按 HTTP 错误收尾(不然会挂住)', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => ({
      ok: true, status: 200, body: null, headers: { get: () => null },
    })))
    const cb = callbacks()

    streamReply('你好', cb)

    await vi.waitFor(() => expect(cb.onDone).toHaveBeenCalledWith('', false))
    expect(cb.onError).toHaveBeenCalledTimes(1)
  })
})

describe('requestIntuition', () => {
  it('按需解释:请求体带 refresh 标记并复用鉴权头', async () => {
    const fetchStub = vi.fn(async () => sseResponse(['"换个说法"', '[DONE]']))
    vi.stubGlobal('fetch', fetchStub)
    signIn('tk-chat')
    const cb = callbacks()

    requestIntuition('题目', '答案', true, cb)

    await vi.waitFor(() => expect(cb.onDone).toHaveBeenCalled())

    const [url, init] = fetchStub.mock.calls[0] as unknown as [string, RequestInit]
    expect(url).toBe('/api/chat/intuition')
    expect(init.method).toBe('POST')
    expect(init.headers).toEqual({
      'Content-Type': 'application/json',
      Authorization: 'Bearer tk-chat',
    })
    expect(JSON.parse(String(init.body))).toEqual({
      question: '题目', answer: '答案', refresh: true,
    })
    expect(cb.onDelta).toHaveBeenCalledWith('换个说法')
    expect(cb.onDone).toHaveBeenCalledWith('换个说法', true)
  })

  it('网络异常 → onError 与空收尾各一次(不重复回调)', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => {
      throw new TypeError('Failed to fetch')
    }))
    const cb = callbacks()

    requestIntuition('题目', '答案', false, cb)

    await vi.waitFor(() => expect(cb.onDone).toHaveBeenCalledWith('', false))
    expect(cb.onError).toHaveBeenCalledTimes(1)
    expect(cb.onDone).toHaveBeenCalledTimes(1)
  })

  it('500 + 非 JSON 错误体 → onError 带状态码,空收尾', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => errorResponse(500, { text: 'oops' })))
    const cb = callbacks()

    requestIntuition('题目', '答案', false, cb)

    await vi.waitFor(() => expect(cb.onDone).toHaveBeenCalledWith('', false))
    expect((cb.onError.mock.calls[0][0] as { status: number }).status).toBe(500)
  })
})

describe('speechToMath', () => {
  it('逐帧回调累计转写结果,完整收尾时交出全文', async () => {
    const fetchStub = vi.fn(async () => sseResponse(['"x^2"', '" + 1"', '[DONE]']))
    vi.stubGlobal('fetch', fetchStub)
    signIn('tk-chat')
    const onDelta = vi.fn()
    const onDone = vi.fn()
    const onFail = vi.fn()

    speechToMath('艾克斯平方加一', { onDelta, onDone, onFail })

    await vi.waitFor(() => expect(onDone).toHaveBeenCalled())

    const [url, init] = fetchStub.mock.calls[0] as unknown as [string, RequestInit]
    expect(url).toBe('/api/speech/math')
    expect(init.headers).toEqual({
      'Content-Type': 'application/json',
      Authorization: 'Bearer tk-chat',
    })
    expect(JSON.parse(String(init.body))).toEqual({ text: '艾克斯平方加一' })
    // 每帧都给的是累计全文(输入框逐帧覆盖而不是拼接)
    expect(onDelta.mock.calls.map((call) => call[0])).toEqual(['x^2', 'x^2 + 1'])
    expect(onDone).toHaveBeenCalledWith('x^2 + 1')
    expect(onFail).not.toHaveBeenCalled()
  })

  it('没等到 [DONE] 就断流 → 按失败回退原文(半截转写不能进缓存)', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => sseResponse(['"x^2"'])))
    const onDelta = vi.fn()
    const onDone = vi.fn()
    const onFail = vi.fn()

    speechToMath('艾克斯平方', { onDelta, onDone, onFail })

    await vi.waitFor(() => expect(onFail).toHaveBeenCalled())
    expect(onDone).not.toHaveBeenCalled()
  })

  it('流里一个字都没有 → 也算失败,不留空结果', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => sseResponse(['[DONE]'])))
    const onDone = vi.fn()
    const onFail = vi.fn()

    speechToMath('嗯', { onDelta: vi.fn(), onDone, onFail })

    await vi.waitFor(() => expect(onFail).toHaveBeenCalled())
    expect(onDone).not.toHaveBeenCalled()
  })

  it('读取中途报错 → onFail 只回调一次(不因 onError+onDone 双路径重复)', async () => {
    const encoder = new TextEncoder()
    const broken = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(encoder.encode('data: "半"'))
        controller.error(new Error('stream broken'))
      },
    })
    vi.stubGlobal('fetch', vi.fn(async () => ({
      ok: true, status: 200, body: broken, headers: { get: () => null },
    })))
    const onDone = vi.fn()
    const onFail = vi.fn()

    speechToMath('随便', { onDelta: vi.fn(), onDone, onFail })

    await vi.waitFor(() => expect(onFail).toHaveBeenCalled())
    expect(onFail).toHaveBeenCalledTimes(1)
    expect(onDone).not.toHaveBeenCalled()
  })

  it('接口 5xx → 不产出任何转写结果(错误响应不会被当成结果缓存)', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => errorResponse(503, { text: 'unavailable' })))
    const onDelta = vi.fn()
    const onDone = vi.fn()
    const onFail = vi.fn()

    speechToMath('随便', { onDelta, onDone, onFail })
    await new Promise((resolve) => setTimeout(resolve, 0))

    // 关键:既不逐帧上屏,也不把结果交给缓存;失败通知最多一次(一次性闸门)
    expect(onDelta).not.toHaveBeenCalled()
    expect(onDone).not.toHaveBeenCalled()
    expect(onFail.mock.calls.length).toBeLessThanOrEqual(1)
  })

  it('cancel() 中止识别请求(新旧转换切换时不再回调)', async () => {
    const fetchStub = vi.fn(async () => sseResponse(['[DONE]']))
    vi.stubGlobal('fetch', fetchStub)

    const handle = speechToMath('随便', { onDelta: vi.fn(), onDone: vi.fn(), onFail: vi.fn() })
    const init = (fetchStub.mock.calls[0] as unknown as [string, RequestInit])[1]
    handle.cancel()

    expect((init.signal as AbortSignal).aborted).toBe(true)
  })
})


