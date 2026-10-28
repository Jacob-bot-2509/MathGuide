/**
 * 会话上下文栈(共享状态):按工作区独立的多会话档案。
 * - 学习辅助(learn)与科学研究(research)各持一份,互不相通;
 * - 同一套代码由 createSessionStore 按工作区实例化,localStorage 键前缀区分;
 * - 回收站恢复按记录的 workspace 写回对应工作区。
 * 持久化于 localStorage(演示环境)。
 */
import { reactive } from 'vue'

/** 工作区:学习辅助 / 科学研究。两个板块的数据完全隔离,只共享后端基础设施 */
export type Workspace = 'learn' | 'research'

export const SESSIONS_KEYS: Record<Workspace, string> = {
  learn: 'mg-learn-sessions',
  research: 'mg-research-sessions',
}

export interface ChatAttachment {
  kind: 'image' | 'file'
  name: string
  /** 图片缩略 dataURL(文件仅存元信息) */
  url?: string
  size?: number
  /** 粘贴导入的文本文件正文(截断保存,随提示词发给模型阅读理解) */
  text?: string
}

export interface ChatMsg {
  id: number
  role: 'user' | 'assistant'
  content: string
  cmd?: string
  attachment?: ChatAttachment
  /** 非问题语句(寒暄/闲聊):不参与问题归纳统计 */
  chitchat?: boolean
  streaming?: boolean
  thinking?: boolean
  /** 章节导航:标记该回复为章节列表(「返回」跳转目标) */
  nav?: 'list'
  /** 章节指引:记录本回复讲解的章节(重复点击直接跳转,不重新生成) */
  navGuideFor?: string
  /** 回答被中断(连接断在后端 [DONE] 之前),内容可能不完整。
   * 必须随档案一起存:刷新后这半截回答还在,得让用户知道它缺了一段 */
  interrupted?: boolean
  /** 用户主动点「停止生成」截断:保留已生成内容,并显示「回复」续写按钮 */
  stopped?: boolean
  /** 研究型回答(后端 meta 帧标记,非前端猜测):导出 PDF 入口只对它显示 */
  research?: boolean
}

export interface ChatSession {
  id: number
  cat?: { key: string; label: string; color: string }
  messages: ChatMsg[]
}

export interface SessionsState {
  sessions: ChatSession[]
  activeId: number
  msgId: number
  sessionId: number
}

/** 会话档案数量上限(createSession 与 restorePair 共同遵守,勿在多处重定义) */
export const MAX_SESSIONS = 20

interface PersistedMsg {
  id: number
  role: 'user' | 'assistant'
  content: string
  cmd?: string
  attachment?: ChatMsg['attachment']
  chitchat?: boolean
  nav?: ChatMsg['nav']
  navGuideFor?: string
  interrupted?: boolean
  research?: boolean
  stopped?: boolean
}

interface Persisted {
  sessions: Array<{ id: number; cat?: ChatSession['cat']; messages: PersistedMsg[] }>
  activeId: number
  msgId: number
  sessionId: number
}

export interface RestoreItem {
  sessionId: number
  question: string
  answer: string
  cat: ChatSession['cat']
}

export interface SessionStore {
  readonly workspace: Workspace
  readonly state: SessionsState
  persistSessions(): boolean
  flushSessions(): boolean
  nextMsgId(): number
  nextSessionId(): number
  restorePair(item: RestoreItem): void
  clear(): void
}

function load(key: string): Persisted {
  try {
    const raw = localStorage.getItem(key)
    if (raw) {
      const p = JSON.parse(raw) as Partial<Persisted> | null
      // 形状校验:字段缺失/被写坏(手改、旧版本、异常写入)时回退空档案,避免 /learn 挂掉
      if (p && Array.isArray(p.sessions)) {
        return {
          sessions: p.sessions.filter((s) => s && Array.isArray(s.messages)) as Persisted['sessions'],
          activeId: typeof p.activeId === 'number' ? p.activeId : 0,
          msgId: typeof p.msgId === 'number' ? p.msgId : 0,
          sessionId: typeof p.sessionId === 'number' ? p.sessionId : 0,
        }
      }
    }
  } catch {
    /* 数据损坏时重置 */
  }
  return { sessions: [], activeId: 0, msgId: 0, sessionId: 0 }
}

function createSessionStore(workspace: Workspace): SessionStore {
  const storageKey = SESSIONS_KEYS[workspace]
  const state = reactive<SessionsState>(load(storageKey))

  let persistTimer: ReturnType<typeof setTimeout> | null = null
  let pendingPersist = false
  let lastPersistOk = true

  /** 一次完整的序列化 + 写盘;成功/配额失败都更新 lastPersistOk */
  function writeSessionsNow(): boolean {
    try {
      const data: Persisted = {
        sessions: state.sessions.map((s) => ({
          id: s.id,
          cat: s.cat,
          messages: s.messages
            .map((m) => ({
              id: m.id, role: m.role, content: m.content, cmd: m.cmd,
              attachment: m.attachment, chitchat: m.chitchat,
              nav: m.nav, navGuideFor: m.navGuideFor,
              interrupted: m.interrupted, research: m.research,
              stopped: m.stopped,
            }))
            .slice(-120),
        })),
        activeId: state.activeId,
        msgId: state.msgId,
        sessionId: state.sessionId,
      }
      localStorage.setItem(storageKey, JSON.stringify(data))
      lastPersistOk = true
      return true
    } catch {
      /* 存储超限(通常是图片附件)时返回 false,由调用方决定是否提示用户 */
      lastPersistOk = false
      return false
    }
  }

  /* 持久化 debounce:流式结束/切换会话等高频路径不立刻做整份序列化;
     关键节点(附件配额提示、卸载、页面关闭)用 flushSessions() 立即落盘。 */
  const PERSIST_DELAY_MS = 120

  /** 合并写盘(默认 120ms)。返回值是「最近一次实际写盘」的结果,不是本次结果 */
  function persistSessions(): boolean {
    pendingPersist = true
    if (persistTimer !== null) clearTimeout(persistTimer)
    persistTimer = setTimeout(() => {
      persistTimer = null
      if (!pendingPersist) return
      pendingPersist = false
      writeSessionsNow()
    }, PERSIST_DELAY_MS)
    return lastPersistOk
  }

  /** 立即写盘并取消待执行的 debounce;关键路径/卸载前调用 */
  function flushSessions(): boolean {
    if (persistTimer !== null) {
      clearTimeout(persistTimer)
      persistTimer = null
    }
    if (!pendingPersist) return lastPersistOk
    pendingPersist = false
    return writeSessionsNow()
  }

  function nextMsgId(): number {
    return ++state.msgId
  }

  function nextSessionId(): number {
    return ++state.sessionId
  }

  /** 恢复回收站记录:找回原会话;原会话已删除则按原板块重建 */
  function restorePair(item: RestoreItem): void {
    let session = state.sessions.find((s) => s.id === item.sessionId)
    if (!session) {
      session = { id: item.sessionId, cat: item.cat, messages: [] }
      state.sessions.push(session)
      if (state.sessions.length > MAX_SESSIONS) state.sessions.shift()
      state.sessionId = Math.max(state.sessionId, item.sessionId)
    }
    session.messages.push(
      { id: nextMsgId(), role: 'user', content: item.question },
      { id: nextMsgId(), role: 'assistant', content: item.answer },
    )
    persistSessions()
  }

  /** 清空本工作区全部会话档案(内存 + localStorage) */
  function clear(): void {
    // 取消尚未落盘的 debounce,否则清空后定时器会把旧档案重新写回去
    if (persistTimer !== null) {
      clearTimeout(persistTimer)
      persistTimer = null
    }
    pendingPersist = false
    lastPersistOk = true
    state.sessions = []
    state.activeId = 0
    localStorage.removeItem(storageKey)
  }

  if (typeof window !== 'undefined') {
    // 关闭/刷新/移动端切后台时尽量把最后一次变更落盘
    window.addEventListener('beforeunload', () => { flushSessions() })
    window.addEventListener('pagehide', () => { flushSessions() })
  }

  return {
    workspace,
    state,
    persistSessions,
    flushSessions,
    nextMsgId,
    nextSessionId,
    restorePair,
    clear,
  }
}

const registry: Record<Workspace, SessionStore> = {
  learn: createSessionStore('learn'),
  research: createSessionStore('research'),
}

/** 按工作区取会话仓库;两个工作区的状态互不相通 */
export function sessionStore(workspace: Workspace): SessionStore {
  return registry[workspace]
}

/** 清空全部工作区的会话档案(设置 → 隐私与安全使用) */
export function clearAllSessions(): void {
  registry.learn.clear()
  registry.research.clear()
}

/* 兼容旧引用:默认指向学习区。新代码请显式使用 sessionStore(workspace) */
export const sessionsState = registry.learn.state
export const persistSessions = registry.learn.persistSessions
export const flushSessions = registry.learn.flushSessions
export const nextMsgId = registry.learn.nextMsgId
export const nextSessionId = registry.learn.nextSessionId
export function restorePair(item: RestoreItem): void {
  registry.learn.restorePair(item)
}
