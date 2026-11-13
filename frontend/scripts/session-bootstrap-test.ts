/**
 * 会话恢复自测(esbuild 打包后 node 执行)。
 *
 * 覆盖 /api/auth/session 回来之后,本地登录态有没有被正确处理:
 *   1. 服务端没轮换(响应不带 token)→ 保留原有 token(曾经的 bug:被 res.user 覆盖成 undefined);
 *   2. 服务端轮换了(响应带 token)→ 内存与 localStorage 都换成新 token;
 *   3. 401 → 清空本地登录态。
 */
/* eslint-disable */
declare const process: { exit(code: number): void }
declare const globalThis: { fetch: unknown; localStorage?: unknown }

const memory = new Map<string, string>()
const localStorageMock = {
  getItem: (key: string) => memory.get(key) ?? null,
  setItem: (key: string, value: string) => { memory.set(key, String(value)) },
  removeItem: (key: string) => { memory.delete(key) },
  clear: () => memory.clear(),
  key: (index: number) => Array.from(memory.keys())[index] ?? null,
  get length() { return memory.size },
}
;(globalThis as unknown as { localStorage: typeof localStorageMock }).localStorage = localStorageMock

let passed = 0
const failed: string[] = []
function check(name: string, ok: boolean, detail = '') {
  if (ok) passed++
  else failed.push(`${name}${detail ? `: ${detail}` : ''}`)
}

type SessionBody = { user?: Record<string, unknown>; token?: string }
let payload: SessionBody | null = null
let status = 200

;(globalThis as unknown as { fetch: unknown }).fetch = async () => ({
  ok: status >= 200 && status < 300,
  status,
  json: async () => payload,
  text: async () => JSON.stringify(payload),
})

const USER = {
  accountKey: 'acct-A',
  nickname: 'A',
  avatar: 'preset:sum',
  authMethod: 'wechat' as const,
}

async function main() {
  const user = await import('../src/stores/user')
  const auth = await import('../src/services/authService')

  // ---- 场景 1:已有 token,服务端未轮换 ----
  user.login({ ...USER, token: 'old-token' })
  payload = { user: USER }
  status = 200
  await auth.bootstrapSession()
  check('未轮换时保留原有 token', user.getToken() === 'old-token', String(user.getToken()))

  // ---- 场景 2:服务端轮换了 token ----
  payload = { user: USER, token: 'new-token' }
  await auth.bootstrapSession()
  check('轮换后内存里是新 token', user.getToken() === 'new-token', String(user.getToken()))
  const stored = JSON.parse(memory.get('mg-user') ?? '{}') as { token?: string }
  check('轮换后 localStorage 同步', stored.token === 'new-token', String(stored.token))

  // ---- 场景 3:凭据失效 ----
  payload = { detail: 'unauthorized' }
  status = 401
  await auth.bootstrapSession()
  check('401 后清空登录态', user.userState.info === null)
  check('401 后 localStorage 不留档案', !memory.has('mg-user'))

  console.log(`\n会话恢复自测:${passed}/${passed + failed.length} 通过`)
  for (const item of failed) console.log(`✗ ${item}`)
  if (failed.length) process.exit(1)
}

void main()
