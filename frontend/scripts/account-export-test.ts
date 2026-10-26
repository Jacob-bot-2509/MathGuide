/**
 * 账号导出本机数据自测:token/内部标记不导出,只带当前账号的待办。
 */
/* eslint-disable */
declare const process: { exit(code: number): void }

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

async function main() {
  const profile = {
    nickname: 'n', avatar: 'preset:sum', authMethod: 'wechat',
    accountKey: 'acct-A', token: 'secret-token',
  }
  localStorage.setItem('mg-user', JSON.stringify(profile))
  localStorage.setItem('mg-notebook', JSON.stringify([{ id: 1, title: '题' }]))
  localStorage.setItem('mg-todo:acct-A', JSON.stringify({ tasks: [{ id: 't1' }] }))
  localStorage.setItem('mg-todo:acct-B', JSON.stringify({ tasks: [{ id: 't2' }] }))
  localStorage.setItem('mg-data-owner', 'acct-A')
  localStorage.setItem('mg-settings', '{broken json')

  const { userState } = await import('../src/stores/user')
  userState.info = profile
  const { collectLocalData } = await import('../src/services/accountService')
  const data = collectLocalData()
  const serialized = JSON.stringify(data)

  check('不导出 token', !serialized.includes('secret-token') && !serialized.includes('"token"'))
  check('导出本机会话/归纳', 'mg-notebook' in data)
  check('导出当前账号待办', 'mg-todo:acct-A' in data)
  check('不导出其他账号待办', !('mg-todo:acct-B' in data))
  check('不导出内部归属标记', !('mg-data-owner' in data))
  check('mg-user 被去掉 token', (data['mg-user'] as Record<string, unknown>).token === undefined)
  check('坏 JSON 原样保留', data['mg-settings'] === '{broken json')

  if (failed.length) {
    console.error(`账号导出自测:${passed}/${passed + failed.length} 通过`)
    failed.forEach((item) => console.error(`  ✗ ${item}`))
    process.exit(1)
  }
  console.log(`账号导出自测:${passed}/${passed} 通过`)
}

void main()
