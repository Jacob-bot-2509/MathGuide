/**
 * 统一请求层:后端接入后所有网络请求经由这里发出。
 * - baseURL 由 VITE_API_BASE_URL 配置(默认同源 → vite 代理 /api)
 * - postSSE 解析 OpenAI 兼容的流式响应(data: 行 / [DONE] 结束标记)
 * - 非 2xx 响应抛 HttpError(status 字段),服务层可区分 401/404/409
 */
import type { StreamCallbacks } from './types'

const BASE_URL = (import.meta.env.VITE_API_BASE_URL as string | undefined) ?? ''

export interface HttpError extends Error {
  status: number
}

export function httpError(res: { status: number }): HttpError {
  const e = new Error(`HTTP ${res.status}`) as HttpError
  e.status = res.status
  return e
}

/** 读取错误上的 HTTP 状态码(非本层抛出的错误返回 undefined)。
 * 服务层判 401/429 一律走这里:先前各处自行 `as { status?: number }`,
 * 同一个形状散落多份,改契约时必然漏改 */
export function statusOf(err: unknown): number | undefined {
  return typeof (err as HttpError | null)?.status === 'number' ? (err as HttpError).status : undefined
}

export async function post<T>(path: string, body: unknown, headers?: Record<string, string>): Promise<T> {
  const res = await fetch(`${BASE_URL}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...(headers ?? {}) },
    body: JSON.stringify(body),
  })
  if (!res.ok) throw httpError(res)
  return (await res.json()) as T
}

export interface PostSSEOptions {
  headers?: Record<string, string>
  controller?: AbortController
}

export async function postSSE(
  path: string,
  body: unknown,
  cb: StreamCallbacks,
  opts?: PostSSEOptions,
): Promise<void> {
  const ac = opts?.controller ?? new AbortController()
  const res = await fetch(`${BASE_URL}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...(opts?.headers ?? {}) },
    body: JSON.stringify(body),
    signal: ac.signal,
  })
  if (!res.ok) throw httpError(res)
  if (!res.body) throw httpError(res)

  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  let full = ''
  // 后端每条 SSE 流都以 [DONE] 收尾(见 backend/chat.py 的 _sse)。
  // 收到它才算这次回答完整 —— 连接干净地关上、但没有 [DONE],
  // 意味着流是在中途断的,手里的 full 只是半截
  let terminated = false

  try {
    for (;;) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      const lines = buffer.split('\n')
      buffer = lines.pop() ?? ''
      for (const line of lines) {
        if (!line.startsWith('data:')) continue
        const payload = line.slice(5).trim()
        if (payload === '[DONE]') {
          terminated = true
          continue
        }
        if (!payload) continue
        // 后端按 OpenAI 惯例用 JSON 字符串包裹增量(换行转义 \\n);
        // 解析失败视为纯文本(兼容旧实现与第三方流)
        let chunk: string = payload
        try {
          const parsed: unknown = JSON.parse(payload)
          if (typeof parsed === 'string') chunk = parsed
        } catch {
          /* plain text, keep as-is */
        }
        full += chunk
        cb.onDelta(chunk)
      }
    }
  } catch (err) {
    if (!ac.signal.aborted) {
      cb.onError?.(err)
      throw err
    }
  } finally {
    // 用户主动取消(abort)不算被中断:那是调用方自己掐的,不是连接断的
    cb.onDone(full, terminated || ac.signal.aborted)
  }
}
