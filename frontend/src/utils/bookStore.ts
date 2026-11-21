/**
 * 本地书库:教材原文、目录、章节指引缓存。
 *
 * 原文可能几十万字,不能进 localStorage;IndexedDB 不可用(无痕/权限)时
 * 回退到内存,只保证当前页面生命周期,并让调用方按未命中处理。
 * 缓存键都用文件内容哈希,重复上传同一文件不重新解析。
 */
import type { BookChapterLite } from '@/utils/bookChapters'

export const BOOK_CACHE_MAX = 20
export const BOOK_CACHE_BYTES = 200 * 1024 * 1024

export interface StoredBook {
  hash: string
  name: string
  pageCount: number
  pages: string[]
  outline: BookChapterLite[]
  createdAt: number
  lastUsedAt: number
  size: number
}

interface TocRecord {
  key: string
  hash: string
  markdown: string
  createdAt: number
}

interface GuideRecord {
  key: string
  hash: string
  content: string
  createdAt: number
}

type StoreName = 'books' | 'tocs' | 'guides'
type RecordOf<S extends StoreName> =
  S extends 'books' ? StoredBook : S extends 'tocs' ? TocRecord : GuideRecord

const DB_NAME = 'mathguide-books'
const DB_VERSION = 1

const memory: Record<StoreName, Map<string, unknown>> = {
  books: new Map(),
  tocs: new Map(),
  guides: new Map(),
}

let dbPromise: Promise<IDBDatabase | null> | null = null

function keyOf(store: StoreName, value: unknown): string {
  const record = value as { hash?: string; key?: string }
  return store === 'books' ? String(record.hash ?? '') : String(record.key ?? '')
}

function openDb(): Promise<IDBDatabase | null> {
  if (dbPromise) return dbPromise
  dbPromise = new Promise((resolve) => {
    if (typeof indexedDB === 'undefined') {
      resolve(null)
      return
    }
    try {
      const request = indexedDB.open(DB_NAME, DB_VERSION)
      request.onupgradeneeded = () => {
        const db = request.result
        if (!db.objectStoreNames.contains('books')) db.createObjectStore('books', { keyPath: 'hash' })
        if (!db.objectStoreNames.contains('tocs')) db.createObjectStore('tocs', { keyPath: 'key' })
        if (!db.objectStoreNames.contains('guides')) db.createObjectStore('guides', { keyPath: 'key' })
      }
      request.onsuccess = () => resolve(request.result)
      request.onerror = () => resolve(null)
      request.onblocked = () => resolve(null)
    } catch {
      resolve(null)
    }
  })
  return dbPromise
}

function requestResult<T>(request: IDBRequest<T>): Promise<T | null> {
  return new Promise((resolve) => {
    request.onsuccess = () => resolve(request.result)
    request.onerror = () => resolve(null)
  })
}

async function putRecord<S extends StoreName>(store: S, value: RecordOf<S>): Promise<boolean> {
  const db = await openDb()
  if (!db) {
    memory[store].set(keyOf(store, value), value)
    return true
  }
  try {
    const tx = db.transaction(store, 'readwrite')
    tx.objectStore(store).put(value)
    const ok = await new Promise<boolean>((resolve) => {
      tx.oncomplete = () => resolve(true)
      tx.onerror = () => resolve(false)
      tx.onabort = () => resolve(false)
    })
    if (!ok) memory[store].set(keyOf(store, value), value)
    return ok
  } catch {
    memory[store].set(keyOf(store, value), value)
    return true
  }
}

async function getRecord<S extends StoreName>(store: S, key: string): Promise<RecordOf<S> | null> {
  const db = await openDb()
  if (!db) return (memory[store].get(key) as RecordOf<S> | undefined) ?? null
  try {
    const tx = db.transaction(store, 'readonly')
    const result = await requestResult(tx.objectStore(store).get(key) as IDBRequest<RecordOf<S>>)
    return result ?? (memory[store].get(key) as RecordOf<S> | undefined) ?? null
  } catch {
    return (memory[store].get(key) as RecordOf<S> | undefined) ?? null
  }
}

async function deleteRecord(store: StoreName, key: string): Promise<void> {
  const db = await openDb()
  if (!db) {
    memory[store].delete(key)
    return
  }
  try {
    const tx = db.transaction(store, 'readwrite')
    tx.objectStore(store).delete(key)
    await new Promise<void>((resolve) => {
      tx.oncomplete = () => resolve()
      tx.onerror = () => resolve()
      tx.onabort = () => resolve()
    })
  } catch {
    memory[store].delete(key)
  }
}

async function getAll<S extends StoreName>(store: S): Promise<Array<RecordOf<S>>> {
  const db = await openDb()
  if (!db) return [...memory[store].values()] as Array<RecordOf<S>>
  try {
    const tx = db.transaction(store, 'readonly')
    const result = await requestResult(tx.objectStore(store).getAll() as IDBRequest<Array<RecordOf<S>>>)
    return result ?? []
  } catch {
    return [...memory[store].values()] as Array<RecordOf<S>>
  }
}

async function clearStore(store: StoreName): Promise<void> {
  memory[store].clear()
  const db = await openDb()
  if (!db) return
  try {
    const tx = db.transaction(store, 'readwrite')
    tx.objectStore(store).clear()
    await new Promise<void>((resolve) => {
      tx.oncomplete = () => resolve()
      tx.onerror = () => resolve()
      tx.onabort = () => resolve()
    })
  } catch {
    /* 内存已清,IndexedDB 失败不阻塞 UI */
  }
}

export async function saveBook(book: StoredBook): Promise<boolean> {
  const ok = await putRecord('books', book)
  await pruneBooks()
  return ok
}

export async function loadBook(hash: string): Promise<StoredBook | null> {
  return getRecord('books', hash)
}

export async function touchBook(hash: string): Promise<void> {
  const book = await loadBook(hash)
  if (!book) return
  await putRecord('books', { ...book, lastUsedAt: Date.now() })
}

export async function getCachedToc(hash: string, parserVersion: number): Promise<string | null> {
  const record = await getRecord('tocs', `${hash}:${parserVersion}`)
  return record?.markdown ?? null
}

export async function saveToc(hash: string, parserVersion: number, markdown: string): Promise<void> {
  await putRecord('tocs', {
    key: `${hash}:${parserVersion}`,
    hash,
    markdown,
    createdAt: Date.now(),
  })
}

export async function getCachedGuide(
  hash: string,
  chapterKeyValue: string,
  promptVersion: number,
): Promise<string | null> {
  const record = await getRecord('guides', `${hash}:${chapterKeyValue}:${promptVersion}`)
  return record?.content ?? null
}

export async function saveGuide(
  hash: string,
  chapterKeyValue: string,
  promptVersion: number,
  content: string,
): Promise<void> {
  await putRecord('guides', {
    key: `${hash}:${chapterKeyValue}:${promptVersion}`,
    hash,
    content,
    createdAt: Date.now(),
  })
}

/** LRU:按最后使用时间淘汰,同时守住总字节上限 */
export async function pruneBooks(
  maxBooks = BOOK_CACHE_MAX,
  maxBytes = BOOK_CACHE_BYTES,
): Promise<void> {
  const books = await getAll('books')
  books.sort((a, b) => a.lastUsedAt - b.lastUsedAt)
  let total = books.reduce((sum, book) => sum + (book.size || 0), 0)
  while (books.length > maxBooks || total > maxBytes) {
    const oldest = books.shift()
    if (!oldest) break
    total -= oldest.size || 0
    await deleteRecord('books', oldest.hash)
  }
}

/** 清空书库、目录与章节缓存(设置页清除本地数据/注销时调用) */
export async function clearBooks(): Promise<void> {
  await Promise.all([clearStore('books'), clearStore('tocs'), clearStore('guides')])
}

/** 单测用:清内存、关连接、允许重新探测 indexedDB */
export function resetBookStoreForTests(): void {
  memory.books.clear()
  memory.tocs.clear()
  memory.guides.clear()
  if (dbPromise) {
    void dbPromise.then((db) => db?.close())
  }
  dbPromise = null
}
