import { accessAction, canOpenInReader } from '../src/utils/fulltextAccess'

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

if (failed.length) {
  console.error(`FAIL ${failed.length}: ${failed.join(', ')}`)
  process.exit(1)
}
console.log(`fulltext access: ${passed} passed`)
