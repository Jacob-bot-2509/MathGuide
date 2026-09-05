/**
 * 用户状态:登录态与用户档案(演示环境持久化于 localStorage)。
 * 认证流程统一走 services/authService,这里只负责状态与持久化。
 */
import { reactive } from 'vue'
import type { AuthMethod, AuthUserDto } from '@/api/types'

export type { AuthMethod, AuthUserDto }

export interface UserInfo extends AuthUserDto {
  /** 后端登录令牌(真实后端模式由服务端下发;本地 mock 登录无) */
  token?: string
  realName?: { name: string; idMasked: string }
}

const USER_KEY = 'mg-user'

function loadUser(): UserInfo | null {
  try {
    const raw = localStorage.getItem(USER_KEY)
    return raw ? (JSON.parse(raw) as UserInfo) : null
  } catch {
    return null
  }
}

export const userState = reactive<{ info: UserInfo | null }>({ info: loadUser() })

export function isLoggedIn(): boolean {
  return !!userState.info
}

/** 取当前登录令牌(供请求层加 Authorization 头) */
export function getToken(): string | undefined {
  return userState.info?.token
}

export function login(info: UserInfo) {
  userState.info = info
  try {
    localStorage.setItem(USER_KEY, JSON.stringify(info))
  } catch {
    /* 存储超限时仅本次会话有效 */
  }
}

export function updateUser(patch: Partial<UserInfo>) {
  if (!userState.info) return
  Object.assign(userState.info, patch)
  try {
    localStorage.setItem(USER_KEY, JSON.stringify(userState.info))
  } catch {
    /* 忽略 */
  }
}

export function logout() {
  userState.info = null
  localStorage.removeItem(USER_KEY)
}
