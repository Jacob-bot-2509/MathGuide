/** 一条回复的流式生命周期:排队启动、增量节流上屏、正常收尾、中断与续写。
 *
 * 从 ChatWorkspace 抽出的原因:这套状态机同时管 `Map<回复id, 流句柄>`、延时启动的定时器,
 * 以及「正常结束 / 连接断在半途 / 用户主动停止 / 请求直接失败」四种收尾路径的幂等。
 * 它是组件里最容易改坏的一段(改一处就可能让某个气泡永远停在"思考中")。
 *
 * 边界约定:
 * - 会话内容、滚动、落盘、图解追问都由调用方注入,本模块不反向依赖组件;
 * - 依赖写成 thunk(`() => value`),调用方可在 setup 里提前建立本模块,
 *   不必等自己的 computed 初始化完毕。
 */
import { markRaw } from 'vue'
import type { StreamCallbacks } from '@/api/types'
import { needsDiagram } from '@/services/diagramService'
import type { ChatMeta, ChatStreamHandle } from '@/services/chatService'
import type { ChatMsg, ChatSession, Workspace } from '@/stores/sessions'
import { appendDiagram, parseDiagramEvent } from '@/utils/diagramSpec'
import { t } from '@/utils/i18n'

/** 后端通过元信息帧回报的「论文已入库」结果 */
export interface PaperImportInfo {
  docId: string
  title?: string
  status?: string
  reason?: string
}

export interface ChatStreamDeps {
  workspace: () => Workspace
  /** 当前打开的会话:只有它需要跟随滚动;停止生成也作用在它身上 */
  activeSession: () => ChatSession | null
  /** 全部会话(卸载时要把所有会话的 streaming 标记清掉) */
  sessions: () => ChatSession[]
  /** 用户是否贴在底部:上拉阅读时不打扰 */
  pinnedToBottom: () => boolean
  /** 标记为「贴底」(续写后要恢复跟随) */
  pinToBottom: () => void
  scrollBottom: (smooth?: boolean) => void
  /** 合并写盘(调用方传 store 的 persistSessions) */
  persist: () => void
  /** 立即写盘(离开页面/卸载时用) */
  flush: () => void
  toast: (message: string) => void
  history: (session: ChatSession, beforeId?: number) => ChatMeta['history']
  markPaperImported: (info: PaperImportInfo) => void
  /** 回答完整且像「需要配图」时自动补一张图解 */
  requestDiagram: (reply: ChatMsg, prompt: string, auto?: boolean) => void | Promise<void>
  /** 真正发请求的函数:生产环境传 paperChat.stream,测试可直接注入假实现 */
  stream: (prompt: string, callbacks: StreamCallbacks, meta?: ChatMeta) => ChatStreamHandle
}

/** 元信息帧里本模块关心的字段(后端路由才知道的标记) */
interface MetaFlags {
  research?: boolean
  tableChanged?: boolean
  paperImported?: PaperImportInfo
}

export function useChatStream(deps: ChatStreamDeps) {
  const streams = new Map<number, ChatStreamHandle>()
  const timers = new Map<number, ReturnType<typeof setTimeout>>()

  /** 让某会话的一条助手消息开始流式接收回复(输出在所属会话内进行,切换界面不中断) */
  function streamInto(session: ChatSession, reply: ChatMsg, prompt: string, meta?: ChatMeta) {
    // 增量节流:高频 chunk 先攒进 pending,约每 24ms 合并提交一次;
    // MathText 对已闭合公式有渲染缓存,单次提交开销极小,不会随正文增长变慢
    let pending = ''
    let commit: ReturnType<typeof setTimeout> | null = null
    // 本次流是否已由 onError 收过尾:失败路径 chatService 会补一次 onDone,
    // 那是幂等清理,不该再叠一层「已中断」标记
    let failed = false
    const flush = () => {
      commit = null
      if (!pending) return
      reply.content += pending
      pending = ''
      // 贴底才跟随滚动:用户上拉阅读时不打扰
      if (session === deps.activeSession() && deps.pinnedToBottom()) deps.scrollBottom(false)
    }
    const stream = deps.stream(prompt, {
      onMeta: (frame) => {
        const inner = (frame as { mg_meta?: MetaFlags }).mg_meta
        if (inner?.research) reply.research = true
        if (inner?.tableChanged) deps.toast(t('chat.tableChanged'))
        if (inner?.paperImported) deps.markPaperImported(inner.paperImported)
        const diagram = parseDiagramEvent(frame)
        if (diagram) {
          reply.diagrams = markRaw(appendDiagram(reply.diagrams, diagram))
          deps.persist()
        }
      },
      onDelta: (chunk) => {
        reply.thinking = false
        pending += chunk
        if (!reply.content) {
          // 首个增量立即上屏(欢迎语/回复的第一句话即刻出现),后续增量再走节流
          flush()
        } else if (!commit) {
          commit = setTimeout(flush, 24)
        }
      },
      onDone: (_full, complete) => {
        if (commit) {
          clearTimeout(commit)
          commit = null
        }
        flush() // 提交最后的残量,避免丢尾
        reply.streaming = false
        reply.thinking = false
        if (!reply.content) {
          // 一字未出:主动停止给停止提示(此时流已被 cancelReply 移出 streams);
          // 被中断则给连接失败提示,否则气泡空着,用户以为卡住了
          if (!streams.has(reply.id)) reply.content = t('learn.stoppedNote')
          else if (!complete && !failed) reply.content = t('learn.errStream')
        } else if (!complete && !failed) {
          // 连接断在后端 [DONE] 之前(后端重启 / 网络中断):手里的字只是半截。
          // 不标记的话,这半截回答和完整回答在界面上长得一模一样,用户无从察觉
          reply.interrupted = true
        }
        streams.delete(reply.id)
        deps.persist()
        if (!failed && complete && reply.content
          && needsDiagram(prompt, deps.history(session, reply.id))
          && !reply.diagrams?.length) {
          void deps.requestDiagram(reply, prompt, true)
        }
      },
      // 请求失败(典型:后端未启动 / 限流 429)时,若一字未出则显示对应提示,
      // 避免气泡永远停留在"思考中"且无任何反馈。
      // 失败路径 onDone 不再触发(settled 拦截),清理须在此完整收尾,
      // 否则 streaming 永真 → 发送按钮永远"生成中"。
      onError: (err?: unknown) => {
        failed = true
        if (commit) {
          clearTimeout(commit)
          commit = null
        }
        flush() // 先提交已收到的残量,不丢内容
        reply.thinking = false
        if (!reply.content) {
          reply.content = (err as { status?: number })?.status === 429
            ? t('learn.toastRateLimit')
            : t('learn.errStream')
        } else {
          // 已经有内容还报错 = 流断在半途(实测后端被杀时是连接重置,不走干净关闭那条路)。
          // 这半截同样得标记,否则它和完整回答在界面上没有区别
          reply.interrupted = true
        }
        reply.streaming = false
        streams.delete(reply.id)
        deps.persist()
      },
    }, { workspace: deps.workspace(), ...meta })
    streams.set(reply.id, stream)
  }

  /** 延迟后开始流式输出(模拟"思考"阶段);定时器按消息 id 记录,便于精确取消 */
  function scheduleStream(
    session: ChatSession,
    reply: ChatMsg,
    prompt: string,
    delay: number,
    meta?: ChatMeta,
  ) {
    const timer = setTimeout(() => {
      timers.delete(reply.id)
      if (reply.streaming) streamInto(session, reply, prompt, meta)
    }, delay)
    timers.set(reply.id, timer)
  }

  /** 精确取消一条回复:等待中的定时器与进行中的流一并清理(含尚未启动的孤儿流) */
  function cancelReply(id: number) {
    const timer = timers.get(id)
    if (timer) {
      clearTimeout(timer)
      timers.delete(id)
    }
    const stream = streams.get(id)
    if (stream) {
      stream.cancel()
      streams.delete(id)
    }
  }

  /** 停止当前会话的生成:进行中的流中止后走正常收尾(保留已生成内容),
      尚未启动的(思考阶段)同步收尾,避免"生成中"卡死 */
  function stopGenerating() {
    const session = deps.activeSession()
    if (!session) return
    for (const m of session.messages) {
      if (!m.streaming) continue
      const hadContent = !!m.content
      cancelReply(m.id)
      m.thinking = false
      if (!streams.has(m.id)) {
        m.streaming = false
        if (!m.content) m.content = t('learn.stoppedNote')
      }
      // 有已生成内容才允许续写;空回答只显示停止提示
      m.stopped = hadContent && !!m.content
    }
    deps.persist()
  }

  /** 续写被「停止生成」截断的回答:原问题 + 已生成正文发给后端,增量追加到同一条消息 */
  function resumeReply(msg: ChatMsg) {
    const session = deps.activeSession()
    if (!session || msg.streaming || !msg.content) return
    if (session.messages.some((m) => m.streaming)) {
      deps.toast(t('learn.toastBusy'))
      return
    }
    const idx = session.messages.findIndex((m) => m.id === msg.id)
    if (idx < 0) return
    const question = [...session.messages.slice(0, idx)].reverse().find((m) => m.role === 'user')
    if (!question) return

    const partial = msg.content
    msg.stopped = false
    msg.interrupted = false
    msg.thinking = true
    msg.streaming = true
    streamInto(session, msg, question.content, {
      sessionId: session.id,
      categoryKey: session.cat?.key,
      resume: true,
      partial,
    })
    deps.pinToBottom()
    deps.scrollBottom()
    deps.persist()
  }

  /** 页面卸载时:停止全部后台流与定时器,保留已生成内容 */
  function stopAllStreams() {
    for (const s of streams.values()) s.cancel()
    streams.clear()
    for (const timer of timers.values()) clearTimeout(timer)
    timers.clear()
    for (const s of deps.sessions()) {
      for (const m of s.messages) {
        m.streaming = false
        m.thinking = false
      }
    }
    deps.flush() // 离开页面(或切换路由)前立即落盘,不等 debounce
  }

  return {
    streamInto,
    scheduleStream,
    cancelReply,
    stopGenerating,
    resumeReply,
    stopAllStreams,
  }
}
