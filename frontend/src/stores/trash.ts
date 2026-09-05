/**
 * 回收站:被删除的问答记录保留 30 天。
 * 期限内可从 设置 → 回收站 恢复,恢复后重新分配到原板块;
 * 超期记录自动清除。
 */
import { reactive } from 'vue'
import { restorePair, type ChatSession } from './sessions'

export interface TrashItem {
  /** 原问题消息 id */
  id: number
  question: string
  answer: string
  cat: ChatSession['cat']
  sessionId: number
  deletedAt: number
}

export const TRASH_RETENTION_DAYS = 30

const TRASH_KEY = 'mg-trash'
export const DAY_MS = 24 * 3600 * 1000

/** 剩余保留天数(向上取整,过期显示 0;与 purgeExpired 同一套口径,勿在视图里重算) */
export function daysLeft(deletedAt: number): number {
  return Math.max(0, Math.ceil((deletedAt + TRASH_RETENTION_DAYS * DAY_MS - Date.now()) / DAY_MS))
}

function loadTrash(): TrashItem[] {
  try {
    const raw = localStorage.getItem(TRASH_KEY)
    return raw ? (JSON.parse(raw) as TrashItem[]) : []
  } catch {
    return []
  }
}

export const trashState = reactive<{ items: TrashItem[] }>({ items: loadTrash() })

function persistTrash() {
  try {
    localStorage.setItem(TRASH_KEY, JSON.stringify(trashState.items))
  } catch {
    /* 忽略 */
  }
}

/** 清除超期(超过 30 天)的记录 */
export function purgeExpired() {
  const cutoff = Date.now() - TRASH_RETENTION_DAYS * DAY_MS
  trashState.items = trashState.items.filter((t) => t.deletedAt >= cutoff)
}

export function addToTrash(item: TrashItem) {
  trashState.items.unshift(item)
  persistTrash()
}

export function removeFromTrash(id: number) {
  trashState.items = trashState.items.filter((t) => t.id !== id)
  persistTrash()
}

/** 恢复记录:写回会话档案(原会话或按原板块重建),并从回收站移除 */
export function restoreTrashItem(id: number): boolean {
  const item = trashState.items.find((t) => t.id === id)
  if (!item) return false
  restorePair(item)
  removeFromTrash(id)
  return true
}

/** 清空回收站(内存 + localStorage;设置 → 隐私与安全使用) */
export function clearTrash(): void {
  trashState.items = []
  localStorage.removeItem(TRASH_KEY)
}

purgeExpired()
