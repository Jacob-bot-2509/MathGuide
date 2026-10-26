/**
 * 认证服务:登录 / 注册 / 第三方登录 / 退出。
 * 全部走真实后端(backend/,契约见 api/types.ts);演示验证码见 DEMO_CODE。
 */
import type { UserInfo } from '@/stores/user'
import { getToken, login as setUser, logout as clearUser } from '@/stores/user'
import { claimLocalData, clearLearningData } from '@/stores/localData'
import type { AuthUserDto, LoginResponse } from '@/api/types'
import { get, post, statusOf } from '@/api/http'
import { AVATAR_PRESETS } from '@/utils/avatar'

/** 演示验证码(与后端 auth.py DEMO_CODE 一致;正式环境由短信服务下发) */
export const DEMO_CODE = '123456'

type LoginResult = 'ok' | 'notfound' | 'wrong'

export interface AuthMode {
  demo: boolean
  invite: boolean
}

/** 登录页读取后端模式:测评环境隐藏固定验证码与游客登录入口。 */
export async function getAuthMode(): Promise<AuthMode> {
  try {
    const res = await get<{ demo?: boolean; invite?: boolean }>('/api/health')
    return { demo: res.demo !== false, invite: res.invite === true }
  } catch {
    return { demo: true, invite: false }
  }
}

/** 写入登录态(token 一并持久化,请求层取用) */
async function applyLogin(user: AuthUserDto, token: string): Promise<UserInfo> {
  const info: UserInfo = { ...user, token }
  setUser(info)
  // 换账号登录时清理上一位用户的本地学习数据;同账号重登(含 401 后)保留
  claimLocalData(user.accountKey)
  return info
}

/** 手机号 + 密码登录 */
export async function loginWithPassword(phone: string, password: string): Promise<LoginResult> {
  try {
    const res = await post<LoginResponse>('/api/auth/login', { method: 'password', phone, password })
    await applyLogin(res.user, res.token)
    return 'ok'
  } catch (err) {
    if (statusOf(err) === 404) return 'notfound'
    if (statusOf(err) === 401) return 'wrong'
    throw err // 网络等错误交由调用方提示
  }
}

/** 手机号 + 验证码登录(未注册自动创建账户) */
export async function loginWithCode(phone: string, code: string): Promise<void> {
  const res = await post<LoginResponse>('/api/auth/login', { method: 'code', phone, code })
  await applyLogin(res.user, res.token)
}

export type RegisterResult = 'ok' | 'exists' | 'invite' | 'closed'

/** 创建账户(注册);非演示模式需要测评邀请码 */
export async function registerWithPassword(
  phone: string,
  password: string,
  invite = '',
): Promise<RegisterResult> {
  try {
    const res = await post<LoginResponse>('/api/auth/register', {
      phone,
      password,
      invite: invite.trim() || undefined,
    })
    await applyLogin(res.user, res.token)
    return 'ok'
  } catch (err) {
    const status = statusOf(err)
    if (status === 409) return 'exists'
    if (status === 403) return 'invite'
    if (status === 400) return 'closed'
    throw err
  }
}

/** 微信 / QQ 登录(演示:模拟与设备账号的授权交接,后端创建 guest 用户) */
export async function loginWithThirdParty(kind: 'wechat' | 'qq'): Promise<UserInfo> {
  const label = kind === 'wechat' ? '微信' : 'QQ'
  const res = await post<LoginResponse>('/api/auth/login', {
    method: kind,
    nickname: `${label}用户_${Math.floor(1000 + Math.random() * 9000)}`,
    avatar: kind === 'wechat' ? AVATAR_PRESETS[1].key : AVATAR_PRESETS[2].key,
  })
  return applyLogin(res.user, res.token)
}

export function logout(): void {
  // 先同步清本地登录态(页面立即生效),再尽力撤销服务端 token;
  // 否则 tokens.json 里会残留可用的孤儿 token
  const token = getToken()
  if (token) {
    post('/api/auth/logout', {}, { Authorization: `Bearer ${token}` }).catch(() => {
      /* 服务端不可达时忽略,本地登出不受影响 */
    })
  }
  clearUser()
  // 会话/归纳本/回收站/语音缓存只存在本机:不清掉的话,
  // 同一台设备换账号登录会看到上一位用户的学习数据
  clearLearningData()
}
