/**
 * 生成文档「在问题归纳中选择」的数据源。
 *
 * 问题归纳面板列出的是所有会话里的用户问题;归纳本(问题记录)只装用户显式
 * 收录过的问答。两者不是同一份数据 —— 弹窗按面板口径补上历史问答,
 * 才不会出现「面板里明明有题,弹窗里却一条都选不了」。
 */
import type { ChatSession } from '@/stores/sessions'

export interface DocHistoryQa {
  key: string
  question: string
  answer: string
}

/** 与问题归纳面板同口径:已分类会话、非寒暄的用户问题,取紧随其后的回答 */
export function historyQa(sessions: ChatSession[]): DocHistoryQa[] {
  const out: DocHistoryQa[] = []
  for (const session of sessions) {
    if (!session.cat) continue
    session.messages.forEach((message, index) => {
      if (message.role !== 'user' || message.chitchat) return
      const answer = answerAfter(session.messages, index)
      if (!answer) return
      out.push({ key: `h:${session.id}:${message.id}`, question: message.content, answer })
    })
  }
  return out
}

function answerAfter(messages: ChatSession['messages'], index: number): string {
  for (let i = index + 1; i < messages.length; i += 1) {
    const message = messages[i]
    if (message.role === 'user') break
    if (message.role === 'assistant' && message.content.trim()) return message.content
  }
  return ''
}
