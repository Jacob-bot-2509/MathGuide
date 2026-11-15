/**
 * 本机数据清理统一入口(学习辅助与科学研究两区)。
 *
 * 会话、归纳本、回收站与语音转写缓存都只存在 localStorage,不带服务端归属:
 * 它们没有服务端副本,所以只在两种时机删除 ——
 *   1. **换账号登录**时(由 claimLocalData 判断归属,先清上一位用户的,避免串号);
 *   2. 用户主动「清除本地数据」或注销账号时。
 * 退出登录**不删**:同一账号重登必须原样看到自己的历史(曾因登出即清而被当成"数据丢失")。
 */
import { clearConvertCache } from '@/utils/speechMath'
import { clearNotebook } from './notebook'
import { clearAllSessions } from './sessions'
import { clearTrash } from './trash'

/** 本机数据当前归属的 accountKey;只存 16 位 uid 哈希,不含账号原文 */
const OWNER_KEY = 'mg-data-owner'

/** 保留旧研究档案的已知归属,避免换账号后误导入。 */
function rememberLegacyArchiveOwner(): void {
  try {
    const owner = localStorage.getItem(OWNER_KEY)
    if (owner && localStorage.getItem('mg-research-archive') && !localStorage.getItem('mg-research-archive-owner')) {
      localStorage.setItem('mg-research-archive-owner', owner)
    }
  } catch { /* 不影响其他本机数据清理 */ }
}

export function clearLearningData(): void {
  rememberLegacyArchiveOwner()
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
  rememberLegacyArchiveOwner()
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
