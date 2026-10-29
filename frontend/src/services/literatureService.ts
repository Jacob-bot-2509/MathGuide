/** 外部文献发现:Crossref / arXiv / Europe PMC / OpenAlex / Semantic Scholar */
import { get, post } from '@/api/http'
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
}

export interface OpenPdfResult {
  ok: boolean
  opened: boolean
  file: string
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
}

export async function searchLiterature(
  query: string,
  limit = 10,
): Promise<LiteratureSearchResult> {
  return get<LiteratureSearchResult>(
    `/api/research/literature?q=${encodeURIComponent(query)}&limit=${limit}`,
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
