/**
 * 聊天服务:页面唯一依赖的入口。
 * - VITE_USE_MOCK=true(默认)→ 本地 Mock 流式回复;
 * - = false → POST /api/chat/stream(OpenAI 兼容 SSE,带登录令牌)。
 * 页面层无需区分:streamReply 签名不变,可额外携带会话元数据(契约 ChatRequest)。
 */
import type { ChatRequest, ChatStreamHandle, StreamCallbacks } from '@/api/types'
import { postSSE } from '@/api/http'
import { getToken, logout as clearUser } from '@/stores/user'
import router from '@/router'
import { showToast } from '@/utils/toast'
import { t } from '@/utils/i18n'
import { streamMockReply } from '@/mock/assistant'

export type { ChatStreamHandle, StreamCallbacks }

/** 会话元数据:与后端契约 ChatRequest 对齐 */
export interface ChatMeta {
  cmd?: string
  sessionId?: number
  categoryKey?: string
  history?: ChatRequest['history']
}

const USE_MOCK = import.meta.env.VITE_USE_MOCK !== 'false'

function authHeaders(): Record<string, string> {
  const token = getToken()
  return token ? { Authorization: `Bearer ${token}` } : {}
}

export function streamReply(prompt: string, cb: StreamCallbacks, meta?: ChatMeta): ChatStreamHandle {
  if (USE_MOCK) {
    // Mock 路径靠 [cmd] 前缀路由;真实接口用 cmd 字段,后端自行剥离
    const text = meta?.cmd ? `[${meta.cmd}] ${prompt}` : prompt
    return streamMockReply(text, cb)
  }

  const controller = new AbortController()
  let settled = false

  const body: ChatRequest = {
    prompt,
    cmd: meta?.cmd,
    sessionId: meta?.sessionId,
    categoryKey: meta?.categoryKey,
    history: meta?.history,
  }

  postSSE(
    '/api/chat/stream',
    body,
    {
      onDelta: (chunk) => {
        cb.onDelta(chunk)
      },
      // 全文由 postSSE 统一累积(onDone 的 full 参数),这里不再重复拼一遍
      onDone: (full) => {
        if (settled) return
        settled = true
        cb.onDone(full)
      },
      // 读取中途失败:先标记错误态;settled 使 finally 的 onDone 不再重复回调,
      // 完整收尾(清理 streaming / 错误提示)由界面层 onError 负责
      onError: (err) => {
        if (settled) return
        settled = true
        cb.onError?.(err)
      },
    },
    { headers: authHeaders(), controller },
  ).catch((err: unknown) => {
    if (settled) return
    settled = true
    if ((err as { status?: number }).status === 401) {
      // 令牌失效(如服务端数据被清):清除本地登录态并回到登录页
      clearUser()
      router.push('/login')
      showToast(t('login.toastExpired'))
      return
    }
    console.error('[chatService] 流式请求失败:', err)
    cb.onError?.(err)
    cb.onDone('')
  })

  return { cancel: () => controller.abort() }
}
