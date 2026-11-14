/**
 * useChatStream 单测(node 环境):四条收尾路径与停止/续写/卸载。
 *
 * 组件级测试只覆盖了「正常流完」和「用户发问」;这四条分支平时要靠拔网线、
 * 中途点停止才能碰到,现在用假 stream 精确驱动。
 */
import { describe, expect, it } from 'vitest'
import type { StreamCallbacks } from '@/api/types'
import { useChatStream, type ChatStreamDeps } from '@/composables/useChatStream'
import type { ChatMsg, ChatSession, Workspace } from '@/stores/sessions'
import { t } from '@/utils/i18n'

const wait = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms))

function makeHarness(overrides: Partial<ChatStreamDeps> = {}) {
  const session: ChatSession = { id: 1, messages: [] }
  const state = {
    callbacks: null as StreamCallbacks | null,
    cancelled: 0,
    persistCalls: 0,
    flushCalls: 0,
    toasts: [] as string[],
    pinned: true,
  }

  const deps: ChatStreamDeps = {
    workspace: () => 'learn' as Workspace,
    activeSession: () => session,
    sessions: () => [session],
    pinnedToBottom: () => state.pinned,
    pinToBottom: () => { state.pinned = true },
    scrollBottom: () => {},
    persist: () => { state.persistCalls += 1 },
    flush: () => { state.flushCalls += 1 },
    toast: (message) => state.toasts.push(message),
    history: () => [],
    markPaperImported: () => {},
    requestDiagram: () => {},
    stream: (_prompt, callbacks) => {
      state.callbacks = callbacks
      return { cancel: () => { state.cancelled += 1 } }
    },
    ...overrides,
  }

  const api = useChatStream(deps)
  /** 造一条正在流式接收的助手消息,并真的把它挂到流上 */
  function startReply(id = 10): ChatMsg {
    const reply: ChatMsg = { id, role: 'assistant', content: '', streaming: true, thinking: true }
    session.messages.push(reply)
    api.streamInto(session, reply, '问题')
    return reply
  }

  return { session, state, api, startReply }
}

describe('useChatStream 正常收尾', () => {
  it('首个增量立即上屏,后续增量按 24ms 合并', async () => {
    const { state, startReply } = makeHarness()
    const reply = startReply()

    state.callbacks?.onDelta('甲')
    expect(reply.content).toBe('甲')
    expect(reply.thinking).toBe(false)

    state.callbacks?.onDelta('乙')
    state.callbacks?.onDelta('丙')
    // 还没到合并窗口
    expect(reply.content).toBe('甲')
    await wait(40)
    expect(reply.content).toBe('甲乙丙')
  })

  it('完整结束:清除生成中标记并落盘', async () => {
    const { state, startReply } = makeHarness()
    const reply = startReply()
    state.callbacks?.onDelta('答案')
    state.callbacks?.onDone('答案', true)

    expect(reply.streaming).toBe(false)
    expect(reply.thinking).toBe(false)
    expect(reply.interrupted).toBeUndefined()
    expect(state.persistCalls).toBeGreaterThan(0)
  })

  it('连接断在 [DONE] 之前:有内容则标记为半截,而不是当成完整回答', async () => {
    const { state, startReply } = makeHarness()
    const reply = startReply()
    state.callbacks?.onDelta('半句话')
    state.callbacks?.onDone('半句话', false)

    expect(reply.interrupted).toBe(true)
    expect(reply.streaming).toBe(false)
  })

  it('一字未出就断:给出连接失败提示,避免空气泡', async () => {
    const { state, startReply } = makeHarness()
    const reply = startReply()
    state.callbacks?.onDone('', false)

    expect(reply.content).toBe(t('learn.errStream'))
    expect(reply.streaming).toBe(false)
  })
})

describe('useChatStream 失败与中断', () => {
  it('429 直接失败且一字未出:提示限流而不是通用错误', async () => {
    const { state, startReply } = makeHarness()
    const reply = startReply()
    state.callbacks?.onError?.({ status: 429 })

    expect(reply.content).toBe(t('learn.toastRateLimit'))
    expect(reply.streaming).toBe(false)
  })

  it('失败后 chatService 补发的 onDone 不能把半截标成完整', async () => {
    const { state, startReply } = makeHarness()
    const reply = startReply()
    state.callbacks?.onDelta('已经收到的内容')
    state.callbacks?.onError?.(new Error('network'))
    // postSSE 的 finally 会再补一次 onDone(complete=false)
    state.callbacks?.onDone('已经收到的内容', false)

    expect(reply.interrupted).toBe(true)
    expect(reply.content).toBe('已经收到的内容')
  })

  it('主动停止:保留已生成内容、取消底层流,并允许续写', async () => {
    const { state, api, startReply } = makeHarness()
    const reply = startReply()
    state.callbacks?.onDelta('说到一半')

    api.stopGenerating()

    expect(state.cancelled).toBe(1)
    expect(reply.streaming).toBe(false)
    expect(reply.content).toBe('说到一半')
    expect(reply.stopped).toBe(true)
  })

  it('停止时一字未出:显示停止提示且不允许续写', async () => {
    const { api, startReply } = makeHarness()
    const reply = startReply()

    api.stopGenerating()

    expect(reply.content).toBe(t('learn.stoppedNote'))
    expect(reply.stopped).toBe(false)
  })

  it('还在「思考」阶段就被取消:定时器清掉,不会再发出请求', async () => {
    const { state, api, session } = makeHarness()
    const reply: ChatMsg = { id: 11, role: 'assistant', content: '', streaming: true, thinking: true }
    session.messages.push(reply)
    api.scheduleStream(session, reply, '问题', 30)

    api.cancelReply(reply.id)
    await wait(60)

    expect(state.callbacks).toBeNull()
  })

  it('卸载时停止所有流并立即落盘', async () => {
    const { state, api, startReply } = makeHarness()
    const reply = startReply()
    state.callbacks?.onDelta('内容')

    api.stopAllStreams()

    expect(state.cancelled).toBe(1)
    expect(state.flushCalls).toBe(1)
    expect(reply.streaming).toBe(false)
    expect(reply.thinking).toBe(false)
    expect(reply.content).toBe('内容')
  })
})

describe('useChatStream 续写', () => {
  it('续写把原问题与已生成正文一起发给后端', async () => {
    const { state, api, startReply, session } = makeHarness()
    session.messages.push({ id: 9, role: 'user', content: '什么是极限' })
    const reply = startReply()
    state.callbacks?.onDelta('已生成的部分')
    api.stopGenerating()

    // 换一个能观察到请求参数的 stream
    const prompts: string[] = []
    const metas: Array<{ resume?: boolean; partial?: string }> = []
    const api2 = useChatStream({
      ...{
        workspace: () => 'learn' as Workspace,
        activeSession: () => session,
        sessions: () => [session],
        pinnedToBottom: () => true,
        pinToBottom: () => {},
        scrollBottom: () => {},
        persist: () => {},
        flush: () => {},
        toast: () => {},
        history: () => [],
        markPaperImported: () => {},
        requestDiagram: () => {},
      },
      stream: (prompt, _cb, meta) => {
        prompts.push(prompt)
        metas.push(meta as { resume?: boolean; partial?: string })
        return { cancel: () => {} }
      },
    })
    api2.resumeReply(reply)

    expect(prompts[0]).toBe('什么是极限')
    expect(metas[0]?.resume).toBe(true)
    expect(metas[0]?.partial).toBe('已生成的部分')
    expect(reply.streaming).toBe(true)
    expect(reply.stopped).toBe(false)
  })

  it('同一会话已有流在跑时不让续写,只提示忙', async () => {
    const { state, api, startReply, session } = makeHarness()
    session.messages.push({ id: 9, role: 'user', content: '问题' })
    const reply = startReply()
    state.callbacks?.onDelta('半截')
    api.stopGenerating()

    session.messages.push({ id: 12, role: 'assistant', content: '', streaming: true })
    const before = state.toasts.length

    api.resumeReply(reply)

    expect(state.toasts.length).toBe(before + 1)
    expect(reply.streaming).toBe(false)
  })
})
