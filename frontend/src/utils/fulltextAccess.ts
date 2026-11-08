export type FullTextStatus =
  | 'oa_pdf'
  | 'oa_landing'
  | 'preprint'
  | 'institutional'
  | 'no_legal_copy'
  | 'unknown'
  | 'ambiguous'

export interface FullTextCandidate {
  url: string
  kind?: 'pdf' | 'landing' | 'html'
  source?: string
  hostType?: string
  version?: string
  license?: string
  serverDownloadable: boolean
  isPreprint?: boolean
  title?: string
  doi?: string
  similarity?: number
}

export interface FullTextResult {
  status: FullTextStatus
  best: FullTextCandidate | null
  candidates: FullTextCandidate[]
  matchedIdentifiers: { type: string; value: string }[]
  reason: string
}

export type FullTextAction = 'reader' | 'external' | 'upload' | 'retry' | 'choose'

const LABELS: Record<FullTextStatus, string> = {
  oa_pdf: 'search.fullTextOaPdf',
  oa_landing: 'search.fullTextOaPage',
  preprint: 'search.fullTextPreprint',
  institutional: 'search.fullTextInstitutional',
  no_legal_copy: 'search.fullTextNone',
  unknown: 'search.fullTextUnknown',
  ambiguous: 'search.fullTextAmbiguous',
}

export function canOpenInReader(result: FullTextResult): boolean {
  return result.status === 'oa_pdf' && result.best?.serverDownloadable === true
}

export function accessAction(result: FullTextResult): FullTextAction {
  switch (result.status) {
    case 'oa_pdf':
      return 'reader'
    case 'oa_landing':
    case 'preprint':
    case 'institutional':
      return 'external'
    case 'no_legal_copy':
      return 'upload'
    case 'unknown':
      return 'retry'
    case 'ambiguous':
      return 'choose'
    default:
      return 'retry'
  }
}

export function accessLabelKey(result: FullTextResult): string {
  return LABELS[result.status] || LABELS.unknown
}

/** 只放行可安全导航的 http/https 绝对地址。 */
export function safeHttpUrl(url: string | null | undefined): string | null {
  if (!url) return null
  try {
    const parsed = new URL(url)
    if (parsed.protocol !== 'http:' && parsed.protocol !== 'https:') return null
  } catch {
    return null
  }
  return url
}

/** 允许同标签跳转的开放获取页。 */
export function externalPageUrl(result: FullTextResult): string | null {
  return safeHttpUrl(result.best?.url)
}

/** 可在站内抓成正文阅读的 OA 落地页;PDF 链接不走这条。 */
export function pageReaderUrl(result: FullTextResult): string | null {
  if (result.status !== 'oa_landing') return null
  if (result.best?.kind === 'pdf') return null
  return safeHttpUrl(result.best?.url)
}
