/**
 * PDF 教材解析:逐页文本 + 书签目录 + 内容哈希。
 *
 * 500 页上限;页文本保留换行,便于按行识别章节标题。
 * 哈希只用于本地缓存键:HTTPS/localhost 走 SHA-256;
 * 局域网 HTTP 下 crypto.subtle 不可用,回退到采样 FNV-1a。
 */
import type { BookChapterLite } from '@/utils/bookChapters'

export const MAX_BOOK_PAGES = 500

export interface PdfBookData {
  hash: string
  pages: string[]
  outline: BookChapterLite[]
  /** PDF 实际页数(可能大于解析页数) */
  pageCount: number
  /** 是否因 500 页上限截断 */
  truncated: boolean
}

interface PdfPage {
  getTextContent(): Promise<{ items: Array<{ str?: string; hasEOL?: boolean; type?: string }> }>
}

interface PdfDoc {
  numPages: number
  getPage(index: number): Promise<PdfPage>
  getOutline(): Promise<unknown[] | null>
  getDestination(name: string): Promise<unknown[] | null>
  getPageIndex(ref: unknown): Promise<number>
  destroy?(): Promise<void>
}

function pageText(items: Array<{ str?: string; hasEOL?: boolean }>): string {
  let raw = ''
  for (const item of items) {
    if (typeof item.str !== 'string') continue
    if (raw && !raw.endsWith('\n')) raw += ' '
    raw += item.str
    if (item.hasEOL) raw += '\n'
  }
  return raw
    .replace(/[ \t]+/g, ' ')
    .replace(/\s*\n\s*/g, '\n')
    .replace(/\n{2,}/g, '\n')
    .trim()
}

/** 采样哈希:文件名/大小之外再看头中尾字节,足以区分教材文件 */
export function fallbackHash(bytes: Uint8Array): string {
  let h1 = 0x811c9dc5
  let h2 = 0x01000193
  for (const byte of bytes) {
    h1 = Math.imul(h1 ^ byte, 16_777_619)
    h2 = Math.imul(h2 ^ byte, 2_246_822_519)
  }
  const length = bytes.length.toString(16)
  return `fnvfull1-${(h1 >>> 0).toString(16).padStart(8, '0')}${(h2 >>> 0).toString(16).padStart(8, '0')}-${length}`
}

async function hashBytes(buffer: ArrayBuffer): Promise<string> {
  const bytes = new Uint8Array(buffer)
  const subtle = globalThis.crypto?.subtle
  if (subtle) {
    try {
      const digest = await subtle.digest('SHA-256', bytes)
      return Array.from(new Uint8Array(digest), (b) => b.toString(16).padStart(2, '0')).join('')
    } catch {
      // Some browsers expose Web Crypto but reject digest in the current context.
    }
  }
  return fallbackHash(bytes)
}

async function destPage(doc: PdfDoc, dest: unknown): Promise<number | null> {
  let target = dest
  if (typeof dest === 'string') {
    try {
      target = await doc.getDestination(dest)
    } catch {
      return null
    }
  }
  if (!Array.isArray(target) || !target.length) return null
  const ref = target[0]
  if (typeof ref === 'number' && Number.isInteger(ref)) return ref
  try {
    const index = await doc.getPageIndex(ref)
    return Number.isInteger(index) ? index : null
  } catch {
    return null
  }
}

async function flattenOutline(doc: PdfDoc, nodes: unknown[], depth: number, limit: number): Promise<BookChapterLite[]> {
  const out: BookChapterLite[] = []
  for (const node of nodes) {
    if (!node || typeof node !== 'object') continue
    const item = node as { title?: unknown; dest?: unknown; items?: unknown }
    const title = typeof item.title === 'string' ? item.title.trim() : ''
    if (!title) continue
    const page = await destPage(doc, item.dest)
    if (page !== null && page >= 0 && page < limit) {
      out.push({ title, depth, startPage: page })
    }
    if (Array.isArray(item.items) && item.items.length) {
      out.push(...await flattenOutline(doc, item.items, depth + 1, limit))
    }
  }
  return out
}

export async function readPdfBook(
  file: File,
  options: { maxPages?: number } = {},
): Promise<PdfBookData> {
  const maxPages = options.maxPages ?? MAX_BOOK_PAGES
  const buffer = await file.arrayBuffer()
  const hash = await hashBytes(buffer)

  const pdfjs = await import('pdfjs-dist')
  const worker = await import('pdfjs-dist/build/pdf.worker.min.mjs?url')
  pdfjs.GlobalWorkerOptions.workerSrc = worker.default

  const doc = await pdfjs.getDocument({ data: new Uint8Array(buffer) }).promise as unknown as PdfDoc
  const pageCount = doc.numPages
  const limit = Math.min(pageCount, maxPages)
  try {
    const pages: string[] = []
    for (let i = 1; i <= limit; i += 1) {
      const page = await doc.getPage(i)
      const content = await page.getTextContent()
      pages.push(pageText(content.items))
    }
    let outline: BookChapterLite[] = []
    try {
      const raw = await doc.getOutline()
      if (Array.isArray(raw)) outline = await flattenOutline(doc, raw, 0, limit)
    } catch {
      outline = []
    }
    return { hash, pages, outline, pageCount, truncated: pageCount > limit }
  } finally {
    await doc.destroy?.().catch(() => {})
  }
}
