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
        if (!payload || payload === '[DONE]') continue
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
    cb.onDone(full)
  }
}
