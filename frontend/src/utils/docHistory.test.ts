import { describe, expect, it } from 'vitest'

import type { ChatSession } from '@/stores/sessions'
import { historyQa } from '@/utils/docHistory'

function session(over: Partial<ChatSession> & { id: number }): ChatSession {
  return { cat: { key: 'analysis', label: '数学分析', color: '#0ff' }, messages: [], ...over }
}

describe('historyQa:问题归纳里的历史问答', () => {
  it('把用户问题与紧随其后的回答配成一条', () => {
    const list = historyQa([
      session({
        id: 1,
        messages: [
          { id: 11, role: 'user', content: '求极限' },
          { id: 12, role: 'assistant', content: '极限是 1' },
        ],
      }),
    ])
    expect(list).toEqual([{ key: 'h:1:11', question: '求极限', answer: '极限是 1' }])
  })

  it('没有回答的问题不进列表', () => {
    const list = historyQa([
      session({
        id: 1,
        messages: [
          { id: 11, role: 'user', content: '求极限' },
          { id: 12, role: 'user', content: '再问一题' },
          { id: 13, role: 'assistant', content: '这是第二题的回答' },
        ],
      }),
    ])
    expect(list.map((item) => item.question)).toEqual(['再问一题'])
  })

  it('寒暄与未分类会话不进列表(与问题归纳面板同口径)', () => {
    const list = historyQa([
      session({
        id: 1,
        messages: [
          { id: 11, role: 'user', content: '你好', chitchat: true },
          { id: 12, role: 'assistant', content: '你好' },
        ],
      }),
      session({
        id: 2,
        cat: undefined,
        messages: [
          { id: 21, role: 'user', content: '未分类问题' },
          { id: 22, role: 'assistant', content: '回答' },
        ],
      }),
    ])
    expect(list).toEqual([])
  })

  it('流式中的空回答不进列表', () => {
    const list = historyQa([
      session({
        id: 1,
        messages: [
          { id: 11, role: 'user', content: '求极限' },
          { id: 12, role: 'assistant', content: '   ', streaming: true },
        ],
      }),
    ])
    expect(list).toEqual([])
  })
})
