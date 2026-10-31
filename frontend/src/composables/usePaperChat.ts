/** 论文聊天流式入口:两个聊天界面共用动作帧解析与流式回调包装。
 *
 * 不接管消息状态和布局,只统一:
 * - streamReply 的调用
 * - onMeta 里的 paper_actions 匹配与转交
 * 会话、附件、命令、消息渲染仍由各界面自己负责。
 */
import type { StreamCallbacks } from '@/api/types'
import {
  streamReply,
  type ChatMeta,
  type ChatStreamHandle,
} from '@/services/chatService'
import type { PaperAction } from '@/services/researchService'
import { handlePaperActionMeta } from '@/utils/paperActions'

export interface PaperChatTarget {
  docId: string
  title?: string
}

export interface PaperChatOptions {
  /** 当前界面正在阅读/拖入的论文;没有论文时不处理动作帧。 */
  getTarget: () => PaperChatTarget | null
  /** 动作执行方:主聊天打开右栏执行,论文工作台交给内部阅读器。 */
  applyActions: (
    target: PaperChatTarget,
    actions: PaperAction[],
    requestId: string,
  ) => void | Promise<void>
}

export function usePaperChat(options: PaperChatOptions) {
  function handleMeta(meta: Record<string, unknown>): boolean {
    const target = options.getTarget()
    if (!target) return false
    return handlePaperActionMeta(meta, target.docId, (actions, requestId) => {
      void options.applyActions(target, actions, requestId)
    })
  }

  function stream(
    prompt: string,
    callbacks: StreamCallbacks,
    meta?: ChatMeta,
  ): ChatStreamHandle {
    return streamReply(prompt, {
      ...callbacks,
      onMeta: (frame) => {
        callbacks.onMeta?.(frame)
        handleMeta(frame)
      },
    }, meta)
  }

  return { handleMeta, stream }
}
