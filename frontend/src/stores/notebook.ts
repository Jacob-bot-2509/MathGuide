/**
 * 问题记录(归纳本):收纳用户确认过的题目与解答,不分类,一条即一档。
 * - 单个问题 → 一档;一次性提问若干问题 → 统一收纳在同一档;
 * - 按工作区隔离:学习辅助与科学研究各持一份,互不相通;
 * - 持久化于 localStorage;条目保留原会话与消息定位,可跳回温故知新。
 */
import { reactive } from 'vue'
import type { Workspace } from './sessions'

export interface NotebookEntry {
  id: number
  question: string
  answer: string
  sessionId: number
  msgId: number
  createdAt: number
}

/** 学习区沿用旧键,升级后历史记录不丢 */
const NOTEBOOK_KEYS: Record<Workspace, string> = {
  learn: 'mg-notebook',
  research: 'mg-research-notebook',
}

const Q_MAX = 400   // 题目截断上限
const A_MAX = 3000  // 解答截断上限(含参考思路)

export interface NotebookStore {
  readonly state: { entries: NotebookEntry[] }
  addEntry(question: string, answer: string, sessionId: number, msgId: number): boolean
  removeEntry(id: number): void
  clear(): void
}

function load(key: string): NotebookEntry[] {
  try {
    const raw = localStorage.getItem(key)
    if (raw) {
      const p = JSON.parse(raw) as unknown
      if (Array.isArray(p)) return p as NotebookEntry[]
    }
  } catch {
    /* 数据损坏时重置 */
  }
  return []
}

function createNotebookStore(workspace: Workspace): NotebookStore {
  const storageKey = NOTEBOOK_KEYS[workspace]
  const state = reactive<{ entries: NotebookEntry[] }>({ entries: load(storageKey) })

  function persist(): boolean {
    try {
      localStorage.setItem(storageKey, JSON.stringify(state.entries.slice(-200)))
      return true
    } catch {
      return false
    }
  }

  function addEntry(question: string, answer: string, sessionId: number, msgId: number): boolean {
    const entry: NotebookEntry = {
      id: Date.now() + Math.floor(Math.random() * 1000),
      question: question.slice(0, Q_MAX),
      answer: answer.slice(0, A_MAX),
      sessionId,
      msgId,
      createdAt: Date.now(),
    }
    state.entries.push(entry)
    return persist()
  }

  function removeEntry(id: number): void {
    state.entries = state.entries.filter((e) => e.id !== id)
    persist()
  }

  function clear(): void {
    state.entries = []
    localStorage.removeItem(storageKey)
  }

  return { state, addEntry, removeEntry, clear }
}

const registry: Record<Workspace, NotebookStore> = {
  learn: createNotebookStore('learn'),
  research: createNotebookStore('research'),
}

/** 按工作区取归纳本;两个工作区的记录互不相通 */
export function notebookStore(workspace: Workspace): NotebookStore {
  return registry[workspace]
}

/** 清空全部工作区的归纳本(设置 → 隐私与安全使用) */
export function clearNotebook(): void {
  registry.learn.clear()
  registry.research.clear()
}

/* 兼容旧引用:默认指向学习区。新代码请显式使用 notebookStore(workspace) */
export const notebookState = registry.learn.state
export const addNotebookEntry = registry.learn.addEntry
export const removeNotebookEntry = registry.learn.removeEntry
