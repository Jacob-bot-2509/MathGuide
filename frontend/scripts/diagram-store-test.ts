/** 回答图解随会话保存:localStorage 序列化必须保留 anchorIndex/spec。 */
/* eslint-disable */
declare const process: { exit(code: number): void }

const memory = new Map<string, string>()
const localStorageMock = {
  getItem: (key: string) => memory.get(key) ?? null,
  setItem: (key: string, value: string) => memory.set(key, String(value)),
  removeItem: (key: string) => memory.delete(key),
  clear: () => memory.clear(),
  key: (index: number) => Array.from(memory.keys())[index] ?? null,
  get length() { return memory.size },
}
;(globalThis as unknown as { localStorage: typeof localStorageMock }).localStorage = localStorageMock

async function main() {
  const { sessionStore } = await import('../src/stores/sessions')
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
  console.log('图解释放/恢复自测:1/1 通过')
}

main().catch((err) => {
  console.error(err instanceof Error ? err.message : String(err))
  process.exit(1)
})
