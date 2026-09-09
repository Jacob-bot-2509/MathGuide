/**
 * 会话上下文栈(共享状态):学习辅助的多会话档案。
 * - LearnView 使用它做会话切换与归档;
 * - 回收站恢复也写入同一份数据,回到聊天页即可见。
 * 持久化于 localStorage(演示环境)。
 */
import { reactive } from 'vue'

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
}

export interface ChatSession {
  id: number
  cat?: { key: string; label: string; color: string }
  messages: ChatMsg[]
}

const SESSIONS_KEY = 'mg-learn-sessions'

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
}

interface Persisted {
  sessions: Array<{ id: number; cat?: ChatSession['cat']; messages: PersistedMsg[] }>
  activeId: number
  msgId: number
  sessionId: number
}

function load(): Persisted {
  try {
    const raw = localStorage.getItem(SESSIONS_KEY)
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

export const sessionsState = reactive<{
  sessions: ChatSession[]
  activeId: number
  msgId: number
  sessionId: number
}>(load())

/** 持久化全部会话;返回是否成功(图片 dataURL 等超出 localStorage 配额时为 false) */
export function persistSessions(): boolean {
  try {
    const data: Persisted = {
      sessions: sessionsState.sessions.map((s) => ({
        id: s.id,
        cat: s.cat,
        messages: s.messages
          .map((m) => ({
            id: m.id, role: m.role, content: m.content, cmd: m.cmd,
            attachment: m.attachment, chitchat: m.chitchat,
            nav: m.nav, navGuideFor: m.navGuideFor,
          }))
          .slice(-120),
      })),
      activeId: sessionsState.activeId,
      msgId: sessionsState.msgId,
      sessionId: sessionsState.sessionId,
    }
    localStorage.setItem(SESSIONS_KEY, JSON.stringify(data))
    return true
  } catch {
    /* 存储超限(通常是图片附件)时返回 false,由调用方决定是否提示用户 */
    return false
  }
}

export function nextMsgId(): number {
  return ++sessionsState.msgId
}

export function nextSessionId(): number {
  return ++sessionsState.sessionId
}

/** 恢复回收站记录:找回原会话;原会话已删除则按原板块重建 */
export function restorePair(item: {
  sessionId: number
  question: string
  answer: string
  cat: ChatSession['cat']
}): void {
  let session = sessionsState.sessions.find((s) => s.id === item.sessionId)
  if (!session) {
    session = { id: item.sessionId, cat: item.cat, messages: [] }
    sessionsState.sessions.push(session)
    if (sessionsState.sessions.length > MAX_SESSIONS) sessionsState.sessions.shift()
    sessionsState.sessionId = Math.max(sessionsState.sessionId, item.sessionId)
  }
  session.messages.push(
    { id: nextMsgId(), role: 'user', content: item.question },
    { id: nextMsgId(), role: 'assistant', content: item.answer },
  )
  persistSessions()
}

/** 清空全部会话档案(内存 + localStorage;设置 → 隐私与安全使用) */
export function clearAllSessions(): void {
  sessionsState.sessions = []
  sessionsState.activeId = 0
  localStorage.removeItem(SESSIONS_KEY)
}
