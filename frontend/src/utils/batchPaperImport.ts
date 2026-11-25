/**
 * 多篇论文并发批量导入工具(上限 5 篇):
 * - 外部文献:支持复用已入库 docId、直链 PDF、或按 DOI/标题自动解析合法 OA 全文(PDF/落地页)→ 正式入库;
 * - 本地文件:支持一次多选最多 5 个文件并发上传;
 * - 单篇失败只记录原因,不阻断同批其余论文继续导入,便于随后一键触发「横向对比」。
 */
import type { LiteratureItem, TempPaperMeta, TempPaperResult } from '@/services/literatureService'
import { canOpenInReader, pageReaderUrl, type FullTextResult } from '@/utils/fulltextAccess'

export const MAX_BATCH_IMPORT = 5
export const BATCH_CONCURRENCY = 3

export type BatchItemState = 'pending' | 'importing' | 'done' | 'error'

export interface BatchItemResult {
  key: string
  item: LiteratureItem
  ok: boolean
  docId?: string
  duplicate?: boolean
  error?: string
}

export interface BatchExternalOutcome {
  results: BatchItemResult[]
  docIds: string[]
  okCount: number
  failCount: number
  total: number
  truncated: boolean
}

export interface BatchExternalDeps {
  projectId?: string
  keyOf: (item: LiteratureItem) => string
  metaOf: (item: LiteratureItem) => TempPaperMeta
  cachedFullText: (item: LiteratureItem) => FullTextResult | null
  onFullTextResolved?: (key: string, res: FullTextResult) => void
  resolveFullText: (input: { doi?: string; title?: string }) => Promise<FullTextResult>
  createTempPaper: (url: string, meta?: TempPaperMeta) => Promise<TempPaperResult>
  createTempPage: (url: string, meta?: TempPaperMeta) => Promise<TempPaperResult>
  importTempPaper: (
    docId: string,
    projectId?: string,
    keepAnnotations?: boolean,
  ) => Promise<{ docId: string; duplicate: boolean; status: string }>
  noOaMessage: string
  defaultFailMessage: string
  onStateChange?: (key: string, state: BatchItemState, error?: string) => void
  onProgress?: (done: number, total: number) => void
}

async function runPool<T, R>(
  items: T[],
  concurrency: number,
  worker: (item: T, index: number) => Promise<R>,
): Promise<R[]> {
  const results = new Array<R>(items.length)
  let cursor = 0
  async function next(): Promise<void> {
    while (cursor < items.length) {
      const idx = cursor++
      results[idx] = await worker(items[idx], idx)
    }
  }
  const count = Math.min(Math.max(1, concurrency), items.length)
  await Promise.all(Array.from({ length: count }, () => next()))
  return results
}

async function importSingleExternal(
  item: LiteratureItem,
  deps: BatchExternalDeps,
): Promise<BatchItemResult> {
  const key = deps.keyOf(item)
  if (item.imported && item.docId) {
    deps.onStateChange?.(key, 'done')
    return { key, item, ok: true, docId: item.docId, duplicate: true }
  }
  deps.onStateChange?.(key, 'importing')
  try {
    let docId = item.tempDocId || ''
    if (!docId) {
      const cached = deps.cachedFullText(item)
      let pdfUrl = (cached && canOpenInReader(cached) && cached.best?.url)
        ? cached.best.url
        : (item.pdfUrl || '')
      let pageUrl = cached ? pageReaderUrl(cached) : ''

      if (!pdfUrl && !pageUrl && (item.doi || item.title)) {
        const resolved = await deps.resolveFullText(
          item.doi ? { doi: item.doi } : { title: item.title },
        )
        deps.onFullTextResolved?.(key, resolved)
        if (resolved.best?.license) item.license = resolved.best.license
        if (canOpenInReader(resolved) && resolved.best?.url) {
          pdfUrl = resolved.best.url
        } else {
          pageUrl = pageReaderUrl(resolved)
        }
      }

      if (pdfUrl) {
        const temp = await deps.createTempPaper(pdfUrl, deps.metaOf(item))
        docId = temp.docId
        item.tempDocId = docId
        item.readerKind = temp.kind || 'pdf'
      } else if (pageUrl) {
        const temp = await deps.createTempPage(pageUrl, deps.metaOf(item))
        docId = temp.docId
        item.tempDocId = docId
        item.readerKind = temp.kind || 'text'
      } else {
        deps.onStateChange?.(key, 'error', deps.noOaMessage)
        return { key, item, ok: false, error: deps.noOaMessage }
      }
    }

    const res = await deps.importTempPaper(docId, deps.projectId || undefined, true)
    item.imported = true
    item.docId = res.docId || docId
    item.tempDocId = ''
    deps.onStateChange?.(key, 'done')
    return { key, item, ok: true, docId: item.docId, duplicate: res.duplicate }
  } catch (err) {
    const message = err instanceof Error && err.message
      ? err.message
      : deps.defaultFailMessage
    deps.onStateChange?.(key, 'error', message)
    return { key, item, ok: false, error: message }
  }
}

export async function batchImportExternalPapers(
  rawItems: LiteratureItem[],
  deps: BatchExternalDeps,
): Promise<BatchExternalOutcome> {
  const truncated = rawItems.length > MAX_BATCH_IMPORT
  const items = rawItems.slice(0, MAX_BATCH_IMPORT)
  const total = items.length
  let done = 0
  items.forEach((item) => {
    const key = deps.keyOf(item)
    deps.onStateChange?.(key, item.imported && item.docId ? 'done' : 'pending')
  })
  deps.onProgress?.(0, total)

  const results = await runPool(items, BATCH_CONCURRENCY, async (item) => {
    const out = await importSingleExternal(item, deps)
    done += 1
    deps.onProgress?.(done, total)
    return out
  })

  const docIds: string[] = []
  const seen = new Set<string>()
  let okCount = 0
  let failCount = 0
  for (const r of results) {
    if (r.ok && r.docId) {
      okCount += 1
      if (!seen.has(r.docId)) {
        seen.add(r.docId)
        docIds.push(r.docId)
      }
    } else {
      failCount += 1
    }
  }
  return { results, docIds, okCount, failCount, total, truncated }
}

export interface BatchLocalOutcome {
  docIds: string[]
  okCount: number
  failCount: number
  total: number
  truncated: boolean
  firstError: string
}

export async function batchUploadLocalFiles(
  rawFiles: File[],
  uploadFn: (file: File) => Promise<{ docId: string; duplicate?: boolean }>,
  onProgress?: (done: number, total: number) => void,
): Promise<BatchLocalOutcome> {
  const truncated = rawFiles.length > MAX_BATCH_IMPORT
  const files = rawFiles.slice(0, MAX_BATCH_IMPORT)
  const total = files.length
  let done = 0
  onProgress?.(0, total)

  let firstError = ''
  const results = await runPool(files, BATCH_CONCURRENCY, async (file) => {
    try {
      const res = await uploadFn(file)
      return { ok: true as const, docId: res.docId }
    } catch (err) {
      const msg = err instanceof Error && err.message ? err.message : ''
      if (!firstError && msg) firstError = msg
      return { ok: false as const, docId: '' }
    } finally {
      done += 1
      onProgress?.(done, total)
    }
  })

  const docIds: string[] = []
  const seen = new Set<string>()
  let okCount = 0
  let failCount = 0
  for (const r of results) {
    if (r.ok && r.docId) {
      okCount += 1
      if (!seen.has(r.docId)) {
        seen.add(r.docId)
        docIds.push(r.docId)
      }
    } else {
      failCount += 1
    }
  }
  return { docIds, okCount, failCount, total, truncated, firstError }
}
