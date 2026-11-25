/**
 * 全科研区统一的「待对比论文篮」(上限 5 篇):
 * 外部批量导入、本地论文库、演示台阅读器与独立论文精读工作台共用同一份选中状态，
 * 避免多处清单割裂不同步。
 */
import { ref } from 'vue'
import { MAX_BATCH_IMPORT } from '@/utils/batchPaperImport'

export const MAX_COMPARE_DOCS = MAX_BATCH_IMPORT

export const compareIds = ref<string[]>([])

export function hasCompareId(docId: string): boolean {
  return Boolean(docId && compareIds.value.includes(docId))
}

/** 切换单篇论文是否在对比篮中;超出上限返回 false */
export function toggleCompareId(docId: string): boolean {
  if (!docId) return false
  if (compareIds.value.includes(docId)) {
    compareIds.value = compareIds.value.filter((id) => id !== docId)
    return true
  }
  if (compareIds.value.length >= MAX_COMPARE_DOCS) return false
  compareIds.value = [...compareIds.value, docId]
  return true
}

export function setCompareIds(docIds: string[]): void {
  const seen = new Set<string>()
  const next: string[] = []
  for (const id of docIds) {
    if (!id || seen.has(id)) continue
    seen.add(id)
    next.push(id)
    if (next.length >= MAX_COMPARE_DOCS) break
  }
  compareIds.value = next
}

export function removeCompareId(docId: string): void {
  if (!docId) return
  compareIds.value = compareIds.value.filter((id) => id !== docId)
}

export function clearCompareIds(): void {
  compareIds.value = []
}
