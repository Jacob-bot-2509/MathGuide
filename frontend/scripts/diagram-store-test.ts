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

  // 配额不足时:丢掉图解,但正文必须保住。
  failDiagramWrites = true
  if (store.flushSessions(true)) throw new Error('quota fallback should report false')
  const lean = JSON.parse(memory.get('mg-research-sessions') || '{}') as {
    sessions?: Array<{ messages?: Array<{ content?: string; diagrams?: unknown }> }>
  }
  const message = lean.sessions?.[0]?.messages?.[0]
  if (message?.content !== '前文后文' || message?.diagrams) {
    throw new Error(`quota fallback lost text: ${JSON.stringify(lean)}`)
  }
  console.log('图解释放/恢复自测:2/2 通过')
}

main().catch((err) => {
  console.error(err instanceof Error ? err.message : String(err))
  process.exit(1)
})
