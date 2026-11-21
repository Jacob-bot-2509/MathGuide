import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.stubGlobal('indexedDB', undefined)

import {
  clearBooks,
  getCachedGuide,
  getCachedToc,
  loadBook,
  pruneBooks,
  resetBookStoreForTests,
  saveBook,
  saveGuide,
  saveToc,
  touchBook,
} from '@/utils/bookStore'

function book(hash: string, lastUsedAt = 1) {
  return {
    hash,
    name: `${hash}.pdf`,
    pageCount: 3,
    pages: ['一', '二', '三'],
    outline: [],
    createdAt: lastUsedAt,
    lastUsedAt,
    size: 3,
  }
}

beforeEach(() => {
  resetBookStoreForTests()
})

describe('bookStore:IndexedDB 不可用时回退内存', () => {
  it('保存与读取原文', async () => {
    await saveBook(book('a'))
    const loaded = await loadBook('a')
    expect(loaded?.pages).toEqual(['一', '二', '三'])
    expect((await loadBook('missing'))?.hash).toBeUndefined()
  })

  it('目录与章节指引按版本号隔离', async () => {
    await saveToc('a', 1, '[第一章](cmd://chapter/x)')
    expect(await getCachedToc('a', 1)).toContain('第一章')
    expect(await getCachedToc('a', 2)).toBeNull()

    await saveGuide('a', '第一章@0-1', 1, '指引')
    expect(await getCachedGuide('a', '第一章@0-1', 1)).toBe('指引')
    expect(await getCachedGuide('a', '第一章@0-1', 2)).toBeNull()
    expect(await getCachedGuide('a', '第二章@2-2', 1)).toBeNull()
  })

  it('LRU 超过上限淘汰最久未用', async () => {
    await saveBook(book('old', 1))
    await saveBook(book('mid', 2))
    await saveBook(book('new', 3))
    await pruneBooks(2, 1024 * 1024)
    expect(await loadBook('old')).toBeNull()
    expect(await loadBook('mid')).not.toBeNull()
    expect(await loadBook('new')).not.toBeNull()
  })

  it('touch 后重新计算 LRU', async () => {
    await saveBook(book('old', 1))
    await saveBook(book('new', 2))
    await touchBook('old')
    await pruneBooks(1, 1024 * 1024)
    expect(await loadBook('old')).not.toBeNull()
    expect(await loadBook('new')).toBeNull()
  })

  it('clear 清空全部书库', async () => {
    await saveBook(book('a'))
    await saveToc('a', 1, '目录')
    await saveGuide('a', 'k', 1, '指引')
    await clearBooks()
    expect(await loadBook('a')).toBeNull()
    expect(await getCachedToc('a', 1)).toBeNull()
    expect(await getCachedGuide('a', 'k', 1)).toBeNull()
  })
})
