import {
  accessAction,
  canOpenInReader,
  externalPageUrl,
  pageReaderUrl,
  safeHttpUrl,
} from '../src/utils/fulltextAccess'

let passed = 0
const failed: string[] = []
function check(name: string, ok: boolean) {
  if (ok) passed++
  else failed.push(name)
}

check('oa_pdf opens reader', canOpenInReader({
  status: 'oa_pdf', best: { url: 'https://arxiv.org/pdf/1', serverDownloadable: true },
  candidates: [], matchedIdentifiers: [], reason: '',
}))
check('oa_landing is external', accessAction({
  status: 'oa_landing', best: { url: 'https://example.org/a', serverDownloadable: false },
  candidates: [], matchedIdentifiers: [], reason: '',
}) === 'external')
check('no_legal_copy asks upload', accessAction({
  status: 'no_legal_copy', best: null, candidates: [], matchedIdentifiers: [], reason: '',
}) === 'upload')
check('unknown asks retry', accessAction({
  status: 'unknown', best: null, candidates: [], matchedIdentifiers: [], reason: '',
}) === 'retry')
check('ambiguous asks choose', accessAction({
  status: 'ambiguous', best: null, candidates: [], matchedIdentifiers: [], reason: '',
}) === 'choose')

function landing(url: string | undefined) {
  return {
    status: 'oa_landing' as const,
    best: url ? { url, serverDownloadable: false } : null,
    candidates: [],
    matchedIdentifiers: [],
    reason: '',
  }
}
check('https landing navigates', externalPageUrl(landing('https://arxiv.org/abs/1')) === 'https://arxiv.org/abs/1')
check('http landing navigates', externalPageUrl(landing('http://example.org/a')) === 'http://example.org/a')
check('javascript landing rejected', externalPageUrl(landing('javascript:alert(1)')) === null)
check('data landing rejected', externalPageUrl(landing('data:text/html,x')) === null)
check('missing landing rejected', externalPageUrl(landing(undefined)) === null)

check('safe https url', safeHttpUrl('https://arxiv.org/pdf/1') === 'https://arxiv.org/pdf/1')
check('safe http url', safeHttpUrl('http://example.org/a') === 'http://example.org/a')
check('javascript url rejected', safeHttpUrl('javascript:alert(1)') === null)
check('data url rejected', safeHttpUrl('data:text/html,x') === null)
check('relative url rejected', safeHttpUrl('/local/path') === null)
check('empty url rejected', safeHttpUrl('') === null)

function page(status: 'oa_landing' | 'oa_pdf', url: string, kind?: 'pdf' | 'landing') {
  return {
    status,
    best: { url, kind, serverDownloadable: false },
    candidates: [],
    matchedIdentifiers: [],
    reason: '',
  }
}
check('oa landing reads in app',
  pageReaderUrl(page('oa_landing', 'https://arxiv.org/abs/1', 'landing')) === 'https://arxiv.org/abs/1')
check('oa landing without kind reads in app',
  pageReaderUrl(page('oa_landing', 'https://europepmc.org/article/1')) === 'https://europepmc.org/article/1')
check('oa landing pdf link not read as page',
  pageReaderUrl(page('oa_landing', 'https://arxiv.org/pdf/1', 'pdf')) === null)
check('oa_pdf status not read as page',
  pageReaderUrl(page('oa_pdf', 'https://arxiv.org/pdf/1', 'pdf')) === null)
check('unsafe landing page rejected',
  pageReaderUrl(page('oa_landing', 'javascript:alert(1)')) === null)

if (failed.length) {
  console.error(`FAIL ${failed.length}: ${failed.join(', ')}`)
  process.exit(1)
}
console.log(`fulltext access: ${passed} passed`)
