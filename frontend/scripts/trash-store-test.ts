/**
 * 回收站存储自测(esbuild 打包后用 node 执行):
 *   npx esbuild scripts/trash-store-test.ts --bundle --format=cjs --platform=node --outfile=.trash-store-test.cjs && node .trash-store-test.cjs
 *
 * 盯的是:30 天过期清理必须写回 localStorage,否则下次加载旧记录会“复活”。
 */
/* eslint-disable */
declare const process: { exit(code: number): void }

const memory = new Map<string, string>()
const localStorageMock = {
  getItem: (key: string) => memory.get(key) ?? null,
  setItem: (key: string, value: string) => {
    memory.set(key, String(value))
  },
  removeItem: (key: string) => {
    memory.delete(key)
  },
  clear: () => memory.clear(),
  key: (index: number) => Array.from(memory.keys())[index] ?? null,
  get length() {
    return memory.size
  },
}
;(globalThis as unknown as { localStorage: typeof localStorageMock }).localStorage = localStorageMock

function check(name: string, ok: boolean, detail = '') {
  if (!ok) throw new Error(`${name}${detail ? `: ${detail}` : ''}`)
}

async function main() {
  const { DAY_MS, addToTrash, purgeExpired, trashState } =
    await import('../src/stores/trash')

  const now = Date.now()
  addToTrash({
    id: 1, question: 'old', answer: '', cat: undefined,
    sessionId: 1, deletedAt: now - 31 * DAY_MS,
  })
  addToTrash({
    id: 2, question: 'new', answer: '', cat: undefined,
    sessionId: 1, deletedAt: now,
  })

  purgeExpired()

  check('内存只剩未过期记录', trashState.items.length === 1, `实际 ${trashState.items.length}`)
  check('保留的是新记录', trashState.items[0]?.id === 2, `实际 ${trashState.items[0]?.id}`)

  const saved = JSON.parse(memory.get('mg-trash') ?? '[]') as Array<{ id: number }>
  check('过期记录已从 localStorage 删除', saved.length === 1, `实际 ${saved.length}`)
  check('持久化的是新记录', saved[0]?.id === 2, `实际 ${saved[0]?.id}`)

  // 退出登录/主动清理:四类本机学习数据必须一并抹掉,防止共用设备串号
  memory.set('mg-learn-sessions', '{}')
  memory.set('mg-notebook', '[]')
  memory.set('mg-speechmath-cache', '{}')
  memory.set('mg-data-owner', 'acct-old')
  const { claimLocalData, clearLearningData } = await import('../src/stores/localData')
  clearLearningData()
  check('学习数据:会话已删除', !memory.has('mg-learn-sessions'))
  check('学习数据:归纳本已删除', !memory.has('mg-notebook'))
  check('学习数据:回收站已删除', !memory.has('mg-trash'))
  check('学习数据:语音缓存已删除', !memory.has('mg-speechmath-cache'))
  check('学习数据:账号归属标记已删除', !memory.has('mg-data-owner'))

  // 401 过期后同账号重登 → 保留;换账号 → 清空
  memory.set('mg-learn-sessions', '{"sessions":[]}')
  memory.set('mg-data-owner', 'acct-A')
  claimLocalData('acct-A')
  check('同账号重登保留本机数据', memory.has('mg-learn-sessions'))
  claimLocalData('acct-B')
  check('换账号登录清空本机数据', !memory.has('mg-learn-sessions'))
  check('账号归属标记更新', memory.get('mg-data-owner') === 'acct-B')
  // 旧版本没有归属标记:认领但不删历史
  memory.delete('mg-data-owner')
  memory.set('mg-learn-sessions', '{"sessions":[]}')
  claimLocalData('acct-C')
  check('无标记旧数据不被误删', memory.has('mg-learn-sessions'))

  // 会话持久化 debounce:默认合并写,flush 立即写,清空时取消待写
  const {
    clearAllSessions, flushSessions, nextSessionId, persistSessions, sessionsState,
  } = await import('../src/stores/sessions')
  memory.delete('mg-learn-sessions')
  sessionsState.sessions.push({ id: nextSessionId(), messages: [] })
  persistSessions()
  check('debounce:未立即写盘', !memory.has('mg-learn-sessions'))
  await new Promise((resolve) => setTimeout(resolve, 180))
  check('debounce:延时后写盘', memory.has('mg-learn-sessions'))

  memory.delete('mg-learn-sessions')
  sessionsState.sessions.push({ id: nextSessionId(), messages: [] })
  persistSessions()
  flushSessions()
  check('flush:立即写盘', memory.has('mg-learn-sessions'))

  persistSessions()
  clearAllSessions()
  await new Promise((resolve) => setTimeout(resolve, 180))
  check('清空后不会被 debounce 写回', !memory.has('mg-learn-sessions'))

  console.log('回收站过期清理 / 本地数据隔离 / 会话持久化自测:15/15 通过')
}

main().catch((err) => {
  console.error(`✗ ${err instanceof Error ? err.message : String(err)}`)
  process.exit(1)
})
