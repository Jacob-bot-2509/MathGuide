/**
 * 文件正文抽取测试。
 *
 * PDF 解析依赖 pdfjs 的懒加载,这里用模块替身接管,重点钉住三件真实事故:
 *   1. 页数上限 80(超大 PDF 会卡死页面);
 *   2. 正文上限 max 字(截断而不是失败);
 *   3. 非文本 item 不能把整页拼成 "undefined"。
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const getDocument = vi.fn()

vi.mock('pdfjs-dist', () => ({
  GlobalWorkerOptions: { workerSrc: '' },
  getDocument,
}))
vi.mock('pdfjs-dist/build/pdf.worker.min.mjs?url', () => ({ default: 'worker-stub-url' }))

import { TEXT_FILE_EXT, extractPdfText, readTextFile } from '@/utils/fileText'

type PageItem = { str?: string } | { type: string }

function makeDoc(pages: PageItem[][], numPages = pages.length) {
  return {
    numPages,
    getPage: vi.fn(async (index: number) => ({
      getTextContent: async () => ({ items: pages[index - 1] ?? [] }),
    })),
  }
}

function pdfFile(name = 'paper.pdf'): File {
  return new File([new Uint8Array([1, 2, 3])], name, { type: 'application/pdf' })
}

beforeEach(() => {
  getDocument.mockReset()
})

afterEach(() => {
  vi.clearAllMocks()
})

describe('extractPdfText', () => {
  it('拼接每页文本、压缩空白,并设置 worker 地址', async () => {
    const doc = makeDoc([
      [{ str: '第一页  a' }, { type: 'markedContent' }, { str: 'b' }],
      [{ str: '第二页' }],
    ])
    getDocument.mockReturnValue({ promise: Promise.resolve(doc) })

    const text = await extractPdfText(pdfFile())

    expect(text).toBe('第一页 a b 第二页')
    expect(doc.getPage).toHaveBeenCalledTimes(2)
    const pdfjs = await import('pdfjs-dist')
    expect(pdfjs.GlobalWorkerOptions.workerSrc).toBe('worker-stub-url')
  })

  it('页数上限 80:超大 PDF 只读前 80 页', async () => {
    const pages = Array.from({ length: 120 }, (_, i) => [{ str: `p${i + 1}` }])
    const doc = makeDoc(pages)
    getDocument.mockReturnValue({ promise: Promise.resolve(doc) })

    const text = await extractPdfText(pdfFile())

    expect(doc.getPage).toHaveBeenCalledTimes(80)
    expect(text).toContain('p80')
    expect(text).not.toContain('p81')
  })

  it('正文上限 max,超限截断而不是报错', async () => {
    const doc = makeDoc([[{ str: 'x'.repeat(500) }]])
    getDocument.mockReturnValue({ promise: Promise.resolve(doc) })

    expect(await extractPdfText(pdfFile(), 100)).toHaveLength(100)
    // 默认 30000 上限
    expect((await extractPdfText(pdfFile())).length).toBe(500)
  })

  it('没有文本层的扫描件返回空串', async () => {
    const doc = makeDoc([[], []])
    getDocument.mockReturnValue({ promise: Promise.resolve(doc) })
    expect(await extractPdfText(pdfFile())).toBe('')
  })

  it('解析失败时向上抛错,由调用方提示用户', async () => {
    getDocument.mockReturnValue({ promise: Promise.reject(new Error('broken pdf')) })
    await expect(extractPdfText(pdfFile())).rejects.toThrow('broken pdf')
  })
})

describe('readTextFile', () => {
  it('读取纯文本并 trim', async () => {
    const file = new File(['  正文内容  '], 'a.txt', { type: 'text/plain' })
    expect(await readTextFile(file)).toBe('正文内容')
  })

  it('超过 max 截断', async () => {
    const file = new File(['y'.repeat(50)], 'a.md', { type: 'text/markdown' })
    expect(await readTextFile(file, 10)).toBe('y'.repeat(10))
  })

  it('空文件返回空串', async () => {
    expect(await readTextFile(new File([''], 'e.txt'))).toBe('')
  })
})

describe('TEXT_FILE_EXT', () => {
  it('识别文本类扩展名(大小写不敏感)', () => {
    for (const name of ['a.txt', 'a.md', 'a.markdown', 'a.tex', 'a.csv', 'a.json']) {
      expect(TEXT_FILE_EXT.test(name)).toBe(true)
    }
    expect(TEXT_FILE_EXT.test('A.TXT')).toBe(true)
  })

  it('不误判二进制/图片', () => {
    for (const name of ['a.pdf', 'a.png', 'a.docx', 'txt', 'a.txtx']) {
      expect(TEXT_FILE_EXT.test(name)).toBe(false)
    }
  })
})
