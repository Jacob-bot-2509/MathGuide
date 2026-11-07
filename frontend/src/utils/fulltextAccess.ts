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
