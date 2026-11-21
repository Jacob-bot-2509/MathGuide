import { describe, expect, it, vi } from 'vitest'

const getDocument = vi.fn()

vi.mock('pdfjs-dist', () => ({
  GlobalWorkerOptions: { workerSrc: '' },
  getDocument,
}))
vi.mock('pdfjs-dist/build/pdf.worker.min.mjs?url', () => ({ default: 'worker-stub-url' }))

import { fallbackHash, readPdfBook } from '@/utils/pdfBook'

type PageItem = { str?: string; hasEOL?: boolean } | { type: string }

function makeDoc(pages: PageItem[][], outline: unknown[] | null = null) {
  return {
    numPages: pages.length,
    getPage: vi.fn(async (index: number) => ({
      getTextContent: async () => ({ items: pages[index - 1] ?? [] }),
    })),
    getOutline: vi.fn(async () => outline),
    getDestination: vi.fn(async (name: string) => (name === 'ch2' ? [{ num: 3, gen: 0 }, { name: 'XYZ' }] : null)),
    getPageIndex: vi.fn(async (ref: { num: number }) => ref.num - 1),
    destroy: vi.fn(async () => {}),
  }
}

function pdfFile(bytes = [1, 2, 3], name = 'book.pdf'): File {
  return new File([new Uint8Array(bytes)], name, { type: 'application/pdf' })
}

describe('readPdfBook', () => {
  it('最多读 500 页,超出的页不解析', async () => {
    const pages = Array.from({ length: 600 }, (_, i) => [{ str: `p${i + 1}` }])
    const doc = makeDoc(pages)
    getDocument.mockReturnValue({ promise: Promise.resolve(doc) })

    const book = await readPdfBook(pdfFile())

    expect(doc.getPage).toHaveBeenCalledTimes(500)
    expect(book.pages).toHaveLength(500)
    expect(book.pages[499]).toContain('p500')
    expect(book.pageCount).toBe(600)
    expect(book.truncated).toBe(true)
  })

  it('解析书签:嵌套层级、字符串命名目标、精确页索引', async () => {
    const doc = makeDoc([[{ str: '第一页' }], [{ str: '第二页' }], [{ str: '第三页' }], [{ str: '第四页' }]], [
      { title: '第一章', dest: [1 + 0], items: [] },
      { title: '第二章', dest: 'ch2', items: [
        { title: '2.1 小节', dest: [{ num: 4, gen: 0 }], items: [] },
      ] },
    ])
    // 数组目标里放 Ref 对象;getPageIndex 按 num-1 返回 0-based 页
    doc.getOutline.mockResolvedValue([
      { title: '第一章', dest: [{ num: 2, gen: 0 }], items: [] },
      { title: '第二章', dest: 'ch2', items: [
        { title: '2.1 小节', dest: [{ num: 4, gen: 0 }], items: [] },
      ] },
    ])
    getDocument.mockReturnValue({ promise: Promise.resolve(doc) })

    const book = await readPdfBook(pdfFile())

    expect(book.outline).toEqual([
      { title: '第一章', depth: 0, startPage: 1 },
      { title: '第二章', depth: 0, startPage: 2 },
      { title: '2.1 小节', depth: 1, startPage: 3 },
    ])
    expect(doc.getDestination).toHaveBeenCalledWith('ch2')
  })

  it('没有书签返回空 outline', async () => {
    const doc = makeDoc([[{ str: '无书签' }]])
    getDocument.mockReturnValue({ promise: Promise.resolve(doc) })

    const book = await readPdfBook(pdfFile())

    expect(book.outline).toEqual([])
  })

  it('HTTP 兜底哈希覆盖整个文件,不忽略抽样区之外的内容', () => {
    const a = new Uint8Array(20000)
    const b = a.slice()
    b[5000] = 1
    expect(fallbackHash(a)).not.toBe(fallbackHash(b))
    expect(fallbackHash(a)).toBe(fallbackHash(a.slice()))
  })

  it('浏览器的 SHA-256 不可用时仍能解析教材', async () => {
    const doc = makeDoc([[{ str: 'x' }]])
    getDocument.mockReturnValue({ promise: Promise.resolve(doc) })
    vi.stubGlobal('crypto', { subtle: { digest: vi.fn().mockRejectedValue(new Error('unavailable')) } })
    try {
      const book = await readPdfBook(pdfFile([1, 2, 3]))
      expect(book.hash).toBe(fallbackHash(new Uint8Array([1, 2, 3])))
    } finally {
      vi.unstubAllGlobals()
    }
  })

  it('同一文件哈希稳定,不同内容哈希不同', async () => {
    const doc = makeDoc([[{ str: 'x' }]])
    getDocument.mockReturnValue({ promise: Promise.resolve(doc) })

    const a = await readPdfBook(pdfFile([1, 2, 3]))
    const b = await readPdfBook(pdfFile([1, 2, 3]))
    const c = await readPdfBook(pdfFile([4, 5, 6]))

    expect(a.hash).toBe(b.hash)
    expect(a.hash).not.toBe(c.hash)
  })

  it('保留页内换行,便于按行识别章节标题', async () => {
    const doc = makeDoc([[
      { str: '第一章 极限' },
      { str: '正文', hasEOL: true },
      { str: '下一行' },
    ]])
    getDocument.mockReturnValue({ promise: Promise.resolve(doc) })

    const book = await readPdfBook(pdfFile())

    expect(book.pages[0]).toContain('\n')
  })
})
