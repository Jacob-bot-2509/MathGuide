/**
 * 聊天服务:页面唯一依赖的入口。
 * POST /api/chat/stream(OpenAI 兼容 SSE,带登录令牌)。
 * streamReply 签名固定,可额外携带会话元数据(契约 ChatRequest)。
 */
import type { ChatRequest, ChatStreamHandle, StreamCallbacks } from '@/api/types'
import { postSSE, statusOf } from '@/api/http'
import { getToken, logout as clearUser } from '@/stores/user'
import router from '@/router'
import { showToast } from '@/utils/toast'
import { t } from '@/utils/i18n'

export type { ChatStreamHandle, StreamCallbacks }

/** 会话元数据:与后端契约 ChatRequest 对齐 */
export interface ChatMeta {
  cmd?: string
  sessionId?: number
  categoryKey?: string
  history?: ChatRequest['history']
  /** 研究型提问的搜索范围(平台名列表;缺省 = 全平台) */
  sources?: string[]
}

function authHeaders(): Record<string, string> {
  const token = getToken()
  return token ? { Authorization: `Bearer ${token}` } : {}
}

/** 语音识别文本 → 数学符号转写(SSE 流式):首帧即上屏,逐帧回调累计全文;
    失败走 onFail(由调用方回退原文),不阻断输入;返回 cancel 供新旧转换切换;
    onDone 携带完整精修结果(供调用方缓存) */
export function speechToMath(
  text: string,
  cb: {
    onDelta: (converted: string) => void
    onFail: () => void
    onDone?: (full: string) => void
  },
): { cancel: () => void } {
  const controller = new AbortController()
  let acc = ''
  postSSE(
    '/api/speech/math',
    { text },
    {
      onDelta: (chunk) => {
        acc += chunk
        cb.onDelta(acc)
      },
      onDone: (full, complete) => {
        // 没等到 [DONE] 就断的流不能算数:调用方会把结果按原句键写进转换缓存,
        // 半个表达式的转写一旦入缓存,以后每次念同一句话都返回这半截(持久污染),
        // 而输入框里留着的也是半截结果 —— 一律按失败走,回退原文
        if (!complete) {
          cb.onFail()
          return
        }
        if (acc) cb.onDone?.(full)
        else cb.onFail()
      },
      onError: () => {
        cb.onFail()
      },
    },
    { headers: authHeaders(), controller },
  ).catch(() => {
    /* 网络失败已由 onError 通知 */
  })
  return { cancel: () => controller.abort() }
}

export function streamReply(prompt: string, cb: StreamCallbacks, meta?: ChatMeta): ChatStreamHandle {
  const controller = new AbortController()
  let settled = false

  const body: ChatRequest = {
    prompt,
    cmd: meta?.cmd,
    sessionId: meta?.sessionId,
    categoryKey: meta?.categoryKey,
    history: meta?.history,
    sources: meta?.sources,
  }

  postSSE(
    '/api/chat/stream',
    body,
    {
      onDelta: (chunk) => {
        cb.onDelta(chunk)
      },
      // 全文由 postSSE 统一累积(onDone 的 full 参数),这里不再重复拼一遍
      onDone: (full, complete) => {
        if (settled) return
        settled = true
        cb.onDone(full, complete)
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
    if (statusOf(err) === 401) {
      // 令牌失效(过期或服务端数据被清):清除本地登录态并回到登录页
      clearUser()
      router.push('/login')
      showToast(t('login.toastExpired'))
      return
    }
    if (statusOf(err) === 429) {
      // 限流:不算错误,界面层用提示文案收尾
      // (complete=false:这条流压根没跑完,但错误文案已由 onError 铺好,
      //  界面层认得出这是失败收尾,不会再叠一层「已中断」标记)
      cb.onError?.(err)
      cb.onDone('', false)
      return
    }
    console.error('[chatService] 流式请求失败:', err)
    cb.onError?.(err)
    cb.onDone('', false)
  })

  return { cancel: () => controller.abort() }
}
