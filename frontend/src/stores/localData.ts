/**
 * 本机学习数据清理统一入口。
 *
 * 会话、归纳本、回收站与语音转写缓存都只存在 localStorage,不带服务端归属;
 * 退出登录或用户主动「清除本地数据」时必须一起清掉,否则同一台设备换账号
 * 登录会看到上一位用户的聊天与题目(串号)。
 */
import { clearConvertCache } from '@/utils/speechMath'
import { clearNotebook } from './notebook'
import { clearAllSessions } from './sessions'
import { clearTrash } from './trash'

/** 本机学习数据当前归属的 accountKey;只存 16 位 uid 哈希,不含账号原文 */
const OWNER_KEY = 'mg-data-owner'

export function clearLearningData(): void {
  clearAllSessions()
  clearTrash()
  clearNotebook()
  clearConvertCache()
  try {
    localStorage.removeItem(OWNER_KEY)
  } catch {
    /* 隐私模式下不可写,本就不存在标记 */
  }
}

/**
 * 登录后认领本机数据。
 *
 * - 标记属于另一个 accountKey → 先清空上一位用户的会话/归纳本/回收站/语音缓存;
 * - 标记相同(含 token 过期后同账号重登)→ 保留;
 * - 没有标记(旧版本升级)→ 认领但不删,避免一升级就丢历史。
 *
 * 这样 401 回登录页后换账号也不会串数据,同时不会误伤同账号重登。
 */
export function claimLocalData(accountKey?: string): void {
  if (!accountKey) return
  let owner: string | null = null
  try {
    owner = localStorage.getItem(OWNER_KEY)
  } catch {
    return
  }
  if (owner && owner !== accountKey) clearLearningData()
  try {
    localStorage.setItem(OWNER_KEY, accountKey)
  } catch {
    /* 配额/隐私模式:只影响下次换账号识别,不影响本次使用 */
  }
}
