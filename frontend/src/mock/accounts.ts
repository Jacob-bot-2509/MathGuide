/**
 * Mock 账号库(演示环境):手机号 → 密码 的本地注册表。
 * 后端接入后本文件整体废弃,由 services/authService 改调真实接口。
 */

interface AccountRecord {
  password: string
  createdAt: string
}

const ACCOUNTS_KEY = 'mg-accounts'

function loadAccounts(): Record<string, AccountRecord> {
  try {
    const raw = localStorage.getItem(ACCOUNTS_KEY)
    return raw ? (JSON.parse(raw) as Record<string, AccountRecord>) : {}
  } catch {
    return {}
  }
}

/** 注册账号;手机号已存在返回 false */
export function registerAccount(phone: string, password: string): boolean {
  const accounts = loadAccounts()
  if (accounts[phone]) return false
  accounts[phone] = { password, createdAt: new Date().toISOString() }
  localStorage.setItem(ACCOUNTS_KEY, JSON.stringify(accounts))
  return true
}

/** 校验账号密码 */
export function verifyAccount(phone: string, password: string): 'ok' | 'notfound' | 'wrong' {
  const acc = loadAccounts()[phone]
  if (!acc) return 'notfound'
  return acc.password === password ? 'ok' : 'wrong'
}
