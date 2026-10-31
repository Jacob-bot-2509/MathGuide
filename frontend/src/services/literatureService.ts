/** 外部文献发现:Crossref / arXiv / Europe PMC / OpenAlex / Semantic Scholar */
import { del, get, post } from '@/api/http'
import { getToken } from '@/stores/user'

function authHeaders(): Record<string, string> {
  const token = getToken()
  return token ? { Authorization: `Bearer ${token}` } : {}
}

export interface LiteratureItem {
  title: string
  authors: string
  year: number
  venue: string
  doi: string
  url: string
  pdfUrl: string
  abstract: string
  citations: number
  sources: string[]
  docId?: string
  tempDocId?: string
  imported?: boolean
  issn?: string
  publisher?: string
  peerReviewed?: boolean
  articleType?: string
  oaStatus?: string
  oaUrl?: string
  license?: string
  retractionStatus?: string
  versionOf?: string
  fields?: string[]
  sourceTier?: string
  venueTier?: string
  venueLabel?: string
  landingUrl?: string
}

export interface OpenPdfResult {
  ok: boolean
  opened: boolean
  file: string
}

export interface TempPaperResult {
  docId: string
  duplicate: boolean
  status: string
  pages: number
  title?: string
  doi?: string
}

export interface TempPaperMeta {
  title?: string
  issn?: string
  publisher?: string
  articleType?: string
  peerReviewed?: boolean
  oaStatus?: string
  license?: string
  landingUrl?: string
  retractionStatus?: string
  versionOf?: string
  accessSource?: string
}

/** 打开外部论文前先临时入库,阅读器用同源文件接口 */
export async function createTempPaper(
  url: string,
  metadata?: TempPaperMeta,
): Promise<TempPaperResult> {
  return post<TempPaperResult>(
    '/api/research/papers/temp', { url, metadata }, authHeaders())
}

export interface ImportPaperResult {
  docId: string
  duplicate: boolean
  status: string
  annotationsKept?: boolean
}

/** 临时论文转为正式入库;keepAnnotations=false 时丢弃批注 */
export async function importTempPaper(
  docId: string,
  projectId?: string,
  keepAnnotations = true,
): Promise<ImportPaperResult> {
  return post<ImportPaperResult>('/api/research/papers/import', {
    docId,
    projectId: projectId || undefined,
    keepAnnotations,
  }, authHeaders())
}

/** 下载开放获取 PDF 并交给本机默认阅读器(WPS/PDF 程序)打开 */
export async function openLiteraturePdf(url: string): Promise<OpenPdfResult> {
  return post<OpenPdfResult>(
    '/api/research/literature/open-pdf', { url }, authHeaders())
}

export interface LiteratureSearchResult {
  query: string
  results: LiteratureItem[]
  warnings: string[]
  identifier?: { type: string; value: string } | null
}

export interface LiteratureQuery {
  limit?: number
  author?: string
  yearFrom?: number | null
  yearTo?: number | null
  field?: 'general' | 'math' | 'physics' | 'chemistry' | 'biology'
  includePreprints?: boolean
  peerReviewed?: boolean
  oaOnly?: boolean
}

export async function searchLiterature(
  query: string,
  opts: LiteratureQuery = {},
): Promise<LiteratureSearchResult> {
  const params = new URLSearchParams()
  params.set('q', query)
  params.set('limit', String(opts.limit ?? 10))
  if (opts.author) params.set('author', opts.author)
  if (opts.yearFrom) params.set('yearFrom', String(opts.yearFrom))
  if (opts.yearTo) params.set('yearTo', String(opts.yearTo))
  if (opts.field) params.set('field', opts.field)
  if (opts.includePreprints === false) params.set('includePreprints', 'false')
  if (opts.peerReviewed) params.set('peerReviewed', 'true')
  if (opts.oaOnly) params.set('oaOnly', 'true')
  return get<LiteratureSearchResult>(
    `/api/research/literature?${params.toString()}`,
    authHeaders())
}

export interface LiteratureOaResult {
  isOa: boolean
  oaStatus: string
  oaUrl: string
  license: string
  oaSource: string
  version: string
  resolver: string
  error?: boolean
}

/** 按 DOI 解析合法 OA 地址;只返回链接,不下载 */
export async function resolveLiteratureOa(doi: string): Promise<LiteratureOaResult> {
  return get<LiteratureOaResult>(
    `/api/research/literature/oa?doi=${encodeURIComponent(doi)}`,
    authHeaders())
}

export async function relatedLiterature(
  opts: { doi?: string; title?: string },
): Promise<LiteratureSearchResult> {
  const params = new URLSearchParams()
  if (opts.doi) params.set('doi', opts.doi)
  if (opts.title) params.set('title', opts.title)
  return get<LiteratureSearchResult>(
    `/api/research/literature/related?${params.toString()}`,
    authHeaders())
}

export interface HistoryItem {
  id: string
  title: string
  name: string
  pages: number
  doi: string
  year: number
  createdAt: number
  lastViewedAt: number
  annotations: number
  originUrl: string
  deletedAt?: number
  purgeAfter?: number
  daysLeft?: number
}

export async function listPaperHistory(): Promise<HistoryItem[]> {
  const res = await get<{ items: HistoryItem[] }>(
    '/api/research/history', authHeaders())
  return res.items
}

export async function listPaperTrash(): Promise<HistoryItem[]> {
  const res = await get<{ items: HistoryItem[] }>(
    '/api/research/history/trash', authHeaders())
  return res.items
}

export async function deletePaperHistory(
  docId: string,
  hard = false,
): Promise<void> {
  const query = hard ? '?hard=1' : ''
  await del(
    `/api/research/history/${encodeURIComponent(docId)}${query}`, authHeaders())
}

export async function restorePaperHistory(docId: string): Promise<void> {
  await post(`/api/research/history/${encodeURIComponent(docId)}/restore`, {},
    authHeaders())
}
