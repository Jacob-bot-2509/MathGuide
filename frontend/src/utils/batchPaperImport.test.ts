import { describe, expect, it, vi } from 'vitest'
import type { LiteratureItem } from '@/services/literatureService'
import type { FullTextResult } from '@/utils/fulltextAccess'
import {
  MAX_BATCH_IMPORT,
  batchImportExternalPapers,
  batchUploadLocalFiles,
  type BatchExternalDeps,
} from '@/utils/batchPaperImport'

function makeItem(overrides: Partial<LiteratureItem> & { title: string }): LiteratureItem {
  return {
    authors: 'Author A',
    year: 2025,
    venue: 'NeurIPS',
    doi: '',
    url: '',
    pdfUrl: '',
    abstract: '',
    citations: 0,
    sources: ['arXiv'],
    ...overrides,
  }
}

function makeDeps(overrides: Partial<BatchExternalDeps> = {}): BatchExternalDeps {
  return {
    keyOf: (item) => item.doi || item.title || item.pdfUrl,
    metaOf: (item) => ({ title: item.title }),
    cachedFullText: () => null,
    resolveFullText: vi.fn(async () => ({
      status: 'unknown',
      best: null,
      candidates: [],
      matchedIdentifiers: [],
      reason: '',
    }) satisfies FullTextResult),
    createTempPaper: vi.fn(async (url) => ({
      docId: `doc-${url}`,
      duplicate: false,
      status: 'temp',
      pages: 10,
      kind: 'pdf' as const,
    })),
    createTempPage: vi.fn(async (url) => ({
      docId: `page-${url}`,
      duplicate: false,
      status: 'temp',
      pages: 4,
      kind: 'text' as const,
    })),
    importTempPaper: vi.fn(async (docId) => ({
      docId,
      duplicate: false,
      status: 'imported',
    })),
    noOaMessage: '无开放获取全文',
    defaultFailMessage: '导入失败',
    ...overrides,
  }
}

describe('batchImportExternalPapers (上限 5 篇)', () => {
  it('强制上限 5 篇并标记 truncated,同时支持复用已入库与直链 PDF 并发导入', async () => {
    const items = Array.from({ length: 7 }, (_, i) =>
      makeItem({
        title: `Paper ${i + 1}`,
        pdfUrl: `https://arxiv.org/pdf/2501.0000${i + 1}.pdf`,
        imported: i === 0,
        docId: i === 0 ? 'existing-doc-1' : undefined,
      }),
    )
    const deps = makeDeps()
    const outcome = await batchImportExternalPapers(items, deps)

    expect(MAX_BATCH_IMPORT).toBe(5)
    expect(outcome.truncated).toBe(true)
    expect(outcome.total).toBe(5)
    expect(outcome.okCount).toBe(5)
    expect(outcome.failCount).toBe(0)
    expect(outcome.docIds).toHaveLength(5)
    expect(outcome.docIds[0]).toBe('existing-doc-1')
    // 第 1 篇已入库不再重复下载,仅下载其余 4 篇
    expect(deps.createTempPaper).toHaveBeenCalledTimes(4)
    expect(deps.importTempPaper).toHaveBeenCalledTimes(4)
  })

  it('无直链 pdfUrl 时自动按 DOI 解析 OA PDF 或 OA 落地页,单篇闭源失败不阻断其余论文', async () => {
    const pPdf = makeItem({ title: 'OA PDF via DOI', doi: '10.1000/oa-pdf' })
    const pPage = makeItem({ title: 'OA HTML via DOI', doi: '10.1000/oa-page' })
    const pClosed = makeItem({ title: 'Closed Paper', doi: '10.1000/closed' })

    const deps = makeDeps({
      resolveFullText: vi.fn(async (input) => {
        if (input.doi === '10.1000/oa-pdf') {
          return {
            status: 'oa_pdf',
            best: {
              url: 'https://arxiv.org/pdf/2501.11111.pdf',
              kind: 'pdf',
              source: 'arxiv',
              serverDownloadable: true,
            },
            candidates: [],
            matchedIdentifiers: [],
            reason: '',
          } satisfies FullTextResult
        }
        if (input.doi === '10.1000/oa-page') {
          return {
            status: 'oa_landing',
            best: {
              url: 'https://pmc.ncbi.nlm.nih.gov/articles/PMC12345/',
              kind: 'landing',
              source: 'pmc',
              serverDownloadable: true,
            },
            candidates: [],
            matchedIdentifiers: [],
            reason: '',
          } satisfies FullTextResult
        }
        return {
          status: 'no_legal_copy',
          best: null,
          candidates: [],
          matchedIdentifiers: [],
          reason: 'closed',
        } satisfies FullTextResult
      }),
    })

    const outcome = await batchImportExternalPapers([pPdf, pPage, pClosed], deps)
    expect(outcome.okCount).toBe(2)
    expect(outcome.failCount).toBe(1)
    expect(outcome.docIds).toEqual([
      'doc-https://arxiv.org/pdf/2501.11111.pdf',
      'page-https://pmc.ncbi.nlm.nih.gov/articles/PMC12345/',
    ])
    expect(outcome.results[2].ok).toBe(false)
    expect(outcome.results[2].error).toBe('无开放获取全文')
    expect(pPdf.imported).toBe(true)
    expect(pPage.imported).toBe(true)
    expect(pClosed.imported).toBeFalsy()
  })
})

describe('batchUploadLocalFiles (本地多选上限 5 篇)', () => {
  it('最多上传前 5 个文件并汇总成功 docIds', async () => {
    const files = Array.from({ length: 6 }, (_, i) => new File(['x'], `p${i + 1}.pdf`))
    const uploadFn = vi.fn(async (file: File) => {
      if (file.name === 'p3.pdf') throw new Error('解析失败')
      return { docId: `local-${file.name}` }
    })

    const outcome = await batchUploadLocalFiles(files, uploadFn)
    expect(outcome.truncated).toBe(true)
    expect(outcome.total).toBe(5)
    expect(outcome.okCount).toBe(4)
    expect(outcome.failCount).toBe(1)
    expect(outcome.firstError).toBe('解析失败')
    expect(outcome.docIds).toHaveLength(4)
  })
})
