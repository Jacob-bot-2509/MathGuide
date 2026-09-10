/**
 * 前后端接口契约。
 * 后端接入时参照此文件实现接口,前端不再改动;
 * 消息 / 流式回调 / 认证数据结构以这里为准。
 */

/* ---------- 聊天 ---------- */

/** 历史对话条目(多轮上下文,只传文本;服务端会再做条数/长度截断) */
export interface ChatHistoryItem {
  role: 'user' | 'assistant'
  content: string
}

/** 发送给后端的聊天请求 */
export interface ChatRequest {
  /** 会话 id(上下文栈) */
  sessionId?: number
  /** 板块 key */
  categoryKey?: string
  prompt: string
  cmd?: string
  /** 最近几轮历史对话(供模型理解上下文;直答/闲聊路径不受影响) */
  history?: ChatHistoryItem[]
  /** 研究型提问的搜索范围(平台名列表;缺省 = 全平台) */
  sources?: string[]
}

/** 流式回调(OpenAI 兼容 SSE 的通用形态) */
export interface StreamCallbacks {
  onDelta: (text: string) => void
  onDone: (full: string) => void
  /** 流请求失败(网络 / HTTP 错误;用户主动取消不触发)。可选,用于界面提示错误态 */
  onError?: (err: unknown) => void
}

export interface ChatStreamHandle {
  cancel(): void
}

/* ---------- 认证 ---------- */

export type AuthMethod = 'phone-pass' | 'phone-code' | 'wechat' | 'qq'

export interface AuthUserDto {
  nickname: string
  avatar: string
  authMethod: AuthMethod
  phone?: string
}

export interface LoginResponse {
  user: AuthUserDto
  token: string
}
