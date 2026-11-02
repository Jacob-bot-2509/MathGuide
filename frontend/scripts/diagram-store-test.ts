/** 回答图解随会话保存:localStorage 序列化必须保留 anchorIndex/spec。 */
/* eslint-disable */
declare const process: { exit(code: number): void }

const memory = new Map<string, string>()
let failDiagramWrites = false
const localStorageMock = {
  getItem: (key: string) => memory.get(key) ?? null,
  setItem: (key: string, value: string) => {
    if (failDiagramWrites && value.includes('"diagrams"')) {
      throw new Error('QuotaExceededError')
    }
    memory.set(key, String(value))
  },
  removeItem: (key: string) => memory.delete(key),
  clear: () => memory.clear(),
  key: (index: number) => Array.from(memory.keys())[index] ?? null,
  get length() { return memory.size },
}
;(globalThis as unknown as { localStorage: typeof localStorageMock }).localStorage = localStorageMock

async function main() {
  // 旧版本/手改数据里可能有“类型与结构不符”的图解;恢复时必须丢弃。
  memory.set('mg-learn-sessions', JSON.stringify({
    sessions: [{
      id: 9,
      messages: [{
        id: 1, role: 'assistant', content: '旧回答',
        diagrams: [
          {
            id: 'bad', anchorIndex: 0,
            spec: { type: 'surface3d', nodes: [{ id: 'a', label: 'A' }],
              edges: [], shapes: [], annotations: [] },
          },
          {
            id: 'ok', anchorIndex: 1,
            spec: { type: 'relation', nodes: [{ id: 'a', label: 'A' }],
              edges: [], shapes: [], annotations: [] },
          },
        ],
      }, null],
    }],
    activeId: 9, msgId: 1, sessionId: 9,
  }))

  const { sessionStore } = await import('../src/stores/sessions')
  const learn = sessionStore('learn')
  if (learn.state.sessions[0]?.messages.length !== 1) {
    throw new Error('invalid message prevented recovery of valid session')
  }
  const restored = learn.state.sessions[0]?.messages[0]?.diagrams
  if (restored?.length !== 1 || restored[0].id !== 'ok') {
    throw new Error(`bad diagram was not rejected: ${JSON.stringify(restored)}`)
  }

  const store = sessionStore('research')
  store.state.sessions.push({
    id: 1,
    messages: [{
      id: 1, role: 'assistant', content: '前文后文',
      diagrams: [{
        id: 'r1-1', anchorIndex: 2,
        spec: {
          type: 'relation',
          nodes: [{ id: 'a', label: 'A' }],
          edges: [], shapes: [], annotations: [],
        },
      }],
    }],
  })
  if (!store.flushSessions(true)) throw new Error('flushSessions failed')
  const raw = memory.get('mg-research-sessions') || '{}'
  const parsed = JSON.parse(raw) as {
    sessions?: Array<{ messages?: Array<{ diagrams?: Array<{ anchorIndex?: number; spec?: { type?: string } }> }> }>
  }
  const diagram = parsed.sessions?.[0]?.messages?.[0]?.diagrams?.[0]
  if (diagram?.anchorIndex !== 2 || diagram?.spec?.type !== 'relation') {
    throw new Error(`diagram not persisted: ${raw}`)
  }

  const first = store.state.sessions[0].messages[0]
  for (let i = 0; i < 25; i++) {
    store.state.sessions[0].messages.push({
      id: i + 2, role: 'assistant', content: '图解', diagrams: first.diagrams,
    })
  }
  if (!store.flushSessions(true)) throw new Error('many diagrams failed to save')
  const saved = memory.get('mg-research-sessions') || ''
  const savedMessages = JSON.parse(saved).sessions[0].messages
  if (savedMessages.filter((m: { diagrams?: unknown[] }) => m.diagrams?.length).length !== 26) {
    throw new Error('saved diagrams were silently discarded')
  }

  // 配额失败不能覆盖上一次完整存档;恢复后可重试保存新内容。
  first.content = '新的回答'
  failDiagramWrites = true
  if (store.flushSessions(true)) throw new Error('quota failure should report false')
  if (memory.get('mg-research-sessions') !== saved) throw new Error('quota failure overwrote archive')
  failDiagramWrites = false
  if (!store.flushSessions(true)) throw new Error('retry failed')
  if (JSON.parse(memory.get('mg-research-sessions') || '{}').sessions[0].messages[0].content !== '新的回答') {
    throw new Error('retry lost new content')
  }
  console.log('图解释放/恢复自测通过')
}

main().catch((err) => {
  console.error(err instanceof Error ? err.message : String(err))
  process.exit(1)
})
