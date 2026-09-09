/**
 * 问题记录(归纳本):收纳用户确认过的题目与解答,不分类,一条即一档。
 * - 单个问题 → 一档;一次性提问若干问题 → 统一收纳在同一档;
 * - 持久化于 localStorage;条目保留原会话与消息定位,可跳回温故知新。
 */
import { reactive } from 'vue'

export interface NotebookEntry {
  id: number
  question: string
  answer: string
  sessionId: number
  msgId: number
  createdAt: number
}

const KEY = 'mg-notebook'
const Q_MAX = 400   // 题目截断上限
const A_MAX = 3000  // 解答截断上限(含参考思路)

function load(): NotebookEntry[] {
  try {
    const raw = localStorage.getItem(KEY)
    if (raw) {
      const p = JSON.parse(raw) as unknown
      if (Array.isArray(p)) return p as NotebookEntry[]
    }
  } catch {
    /* 数据损坏时重置 */
  }
  return []
}

export const notebookState = reactive<{ entries: NotebookEntry[] }>({ entries: load() })

function persist(): boolean {
  try {
    localStorage.setItem(KEY, JSON.stringify(notebookState.entries.slice(-200)))
    return true
  } catch {
    return false
  }
}

export function addNotebookEntry(question: string, answer: string, sessionId: number, msgId: number): boolean {
  const entry: NotebookEntry = {
    id: Date.now() + Math.floor(Math.random() * 1000),
    question: question.slice(0, Q_MAX),
    answer: answer.slice(0, A_MAX),
    sessionId,
    msgId,
    createdAt: Date.now(),
  }
  notebookState.entries.push(entry)
  return persist()
}

export function removeNotebookEntry(id: number): void {
  notebookState.entries = notebookState.entries.filter((e) => e.id !== id)
  persist()
}

export function clearNotebook(): void {
  notebookState.entries = []
  localStorage.removeItem(KEY)
}
