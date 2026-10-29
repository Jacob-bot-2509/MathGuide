/**
 * 账号数据导出与注销。
 *
 * 导出 = 后端账号/用量元数据 + 浏览器里的学习数据;两部分都是用户自己的数据。
 * 注销 = 后端删除账号、全部 token 与该账号用量;浏览器数据由调用方清理。
 */
import { post, statusOf } from '@/api/http'
import { getToken, userState } from '@/stores/user'
import { APP_NAME, APP_VERSION } from '@/utils/aboutContent'

export type DeleteResult = 'ok' | 'wrong'
export type ExportMode = 'full' | 'local'

interface ServerExport {
  exportedAt: string
  account: Record<string, unknown>
  usage: Array<Record<string, unknown>>
  note?: string
}

interface ExportPayload {
  app: string
  version: string
  exportedAt: string
  server: ServerExport | null
  serverError?: string
  local: Record<string, unknown>
}

function authHeaders(): Record<string, string> {
  const token = getToken()
  return token ? { Authorization: `Bearer ${token}` } : {}
}

function readLocal(key: string): unknown {
  try {
    const raw = localStorage.getItem(key)
    if (raw === null) return undefined
    try {
      return JSON.parse(raw) as unknown
    } catch {
      return raw
    }
  } catch {
    return undefined
  }
}

/** 只导出当前账号自己的本地数据;不含 token 与内部去重标记。
 *  导出与自测共用,单独导出便于验证 token 不会混进文件。 */
export function collectLocalData(): Record<string, unknown> {
  const local: Record<string, unknown> = {}
  const keys = [
    'mg-learn-sessions',
    'mg-research-sessions',
    'mg-notebook',
    'mg-research-notebook',
    'mg-settings',
    'mg-trash',
    'mg-research-scope',
    'mg-speechmath-cache',
  ]
  for (const key of keys) {
    const value = readLocal(key)
    if (value !== undefined) local[key] = value
  }

  // mg-user 里的 token 是凭据,不写进导出文件
  const rawUser = readLocal('mg-user')
  if (rawUser && typeof rawUser === 'object') {
    const profile = { ...(rawUser as Record<string, unknown>) }
    delete profile.token
    local['mg-user'] = profile
  }

  const accountKey = userState.info?.accountKey
  if (accountKey) {
    const todoKey = `mg-todo:${accountKey}`
    const todo = readLocal(todoKey)
    if (todo !== undefined) local[todoKey] = todo
  }
  return local
}

function downloadJson(data: unknown): void {
  const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' })
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = `mathguide-export-${new Date().toISOString().slice(0, 10)}.json`
  document.body.appendChild(anchor)
  anchor.click()
  anchor.remove()
  window.setTimeout(() => URL.revokeObjectURL(url), 0)
}

export async function exportAccountData(): Promise<ExportMode> {
  let server: ServerExport | null = null
  let serverError = ''
  try {
    server = await post<ServerExport>('/api/account/export', {}, authHeaders())
  } catch (err) {
    // 后端不可达/登录失效时仍导出本地数据,不能让用户什么也拿不到
    serverError = err instanceof Error ? err.message : 'server unavailable'
  }

  const payload: ExportPayload = {
    app: APP_NAME,
    version: APP_VERSION,
    exportedAt: new Date().toISOString(),
    server,
    serverError: serverError || undefined,
    local: collectLocalData(),
  }
  downloadJson(payload)
  return server ? 'full' : 'local'
}

export async function deleteAccount(input: { password?: string; confirm?: string }): Promise<DeleteResult> {
  try {
    await post('/api/account/delete', input, authHeaders())
    return 'ok'
  } catch (err) {
    // 401 同时覆盖「密码错误」与「token 已失效」,提示文案两者都提
    if (statusOf(err) === 401) return 'wrong'
    throw err
  }
}
