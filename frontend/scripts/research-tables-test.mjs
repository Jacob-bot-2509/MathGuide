// Exercise the actual table view persistence functions with delayed and failed requests.
import { readFileSync } from 'node:fs'
import assert from 'node:assert/strict'
import ts from 'typescript'
import { parse } from '@vue/compiler-sfc'

const source = readFileSync(new URL('../src/views/ResearchTablesView.vue', import.meta.url), 'utf8')
const script = parse(source).descriptor.scriptSetup.content
const ast = ts.createSourceFile('view.ts', script, ts.ScriptTarget.Latest, true, ts.ScriptKind.TS)
const names = ['payload', 'openTable', 'saveNow', 'scheduleSave', 'onCompute', 'onExport', 'currentRegressionSpec', 'runRegression']
const bodies = names.map((name) => {
  const node = ast.statements.find((s) => ts.isFunctionDeclaration(s) && s.name?.text === name)
  assert.ok(node, `Missing ${name}`)
  return node.getText(ast)
}).join('\n')
const js = ts.transpileModule(bodies, { compilerOptions: { target: ts.ScriptTarget.ES2022 } }).outputText
const factory = new Function('env', `
  const { table, activeProject, dirty, saving, computing, printing, switching, computed, errors,
    getResearchTable, saveResearchTable, computeResearchTable, downloadResearchTable,
    normalize, nextTick, showToast, t, setTimeout, clearTimeout,
    regressionX, regressionY, regressionModel, regressionDegree, regressionLoading, regressionError,
    regression, regressionKey, regressionSpecUsed, regressResearchTable } = env;
  let saveTimer = null, suppressWatch = false;
  ${js}
  return { openTable, saveNow, onCompute, onExport, runRegression };
`)
const ref = (value) => ({ value })
const makeTable = (id, cell = 'original') => ({
  id, title: id, columns: [], rows: [[cell]], formulas: {}, rowLabels: [],
  merges: [], colWidths: [], rowHeights: [], projectId: null,
})
const deferred = () => {
  let resolve, reject
  const promise = new Promise((yes, no) => { resolve = yes; reject = no })
  return { promise, resolve, reject }
}
function harness(overrides = {}) {
  const env = {
    table: ref(makeTable('A')), activeProject: ref(''), dirty: ref(true),
    saving: ref(false), computing: ref(false), printing: ref(false), switching: ref(false),
    computed: ref({}), errors: ref([]),
    regressionX: ref(['X']), regressionY: ref('Y'), regressionModel: ref('ols'),
    regressionDegree: ref(2), regressionLoading: ref(false), regressionError: ref(''),
    regression: ref(null), regressionKey: ref(''), regressionSpecUsed: ref(null),
    regressResearchTable: async () => ({}),
    getResearchTable: async (id) => makeTable(id),
    saveResearchTable: async (id) => ({ updatedAt: 1 }),
    computeResearchTable: async (id, value) => ({ table: { id, ...value }, computed: {}, errors: [] }),
    downloadResearchTable: async () => {}, normalize: (v) => v, nextTick: async () => {},
    showToast: () => {}, t: (key) => key, setTimeout: () => 1, clearTimeout: () => {},
    ...overrides,
  }
  return { env, api: factory(env) }
}
{
  const { env, api } = harness({ saveResearchTable: async () => { throw Error('offline') } })
  await api.openTable('B')
  assert.equal(env.table.value.id, 'A', 'failed save must prevent switching')
  assert.equal(env.dirty.value, true)
}
{
  const saved = []
  const { env, api } = harness({ saveResearchTable: async (id, data) => { saved.push([id, data]); return { updatedAt: 1 } } })
  await api.openTable('B')
  assert.equal(saved[0][0], 'A')
  assert.equal(saved[0][1].rows[0][0], 'original')
  assert.equal(env.table.value.id, 'B')
}
{
  const request = deferred()
  const { env, api } = harness({ saveResearchTable: () => request.promise })
  const pending = api.saveNow(true)
  env.table.value.rows[0][0] = 'new edit'
  request.resolve({ updatedAt: 1 })
  assert.equal(await pending, false)
  assert.equal(env.dirty.value, true)
  assert.equal(env.table.value.rows[0][0], 'new edit')
}
{
  const request = deferred()
  const { env, api } = harness({ computeResearchTable: () => request.promise })
  const pending = api.onCompute()
  env.table.value.rows[0][0] = 'new edit'
  request.resolve({ table: makeTable('A', 'old result'), computed: {}, errors: [] })
  await pending
  assert.equal(env.table.value.rows[0][0], 'new edit')
  assert.equal(env.dirty.value, true)
}
{
  let downloads = 0
  const { api } = harness({
    saveResearchTable: async () => { throw Error('offline') },
    downloadResearchTable: async () => { downloads++ },
  })
  await api.onExport('csv')
  assert.equal(downloads, 0, 'failed save must prevent export')
}
{
  let saved
  const { api } = harness({
    activeProject: ref('project-filter'),
    saveResearchTable: async (id, data) => { saved = data; return { updatedAt: 1 } },
  })
  await api.saveNow(true)
  assert.equal(saved.projectId, null, 'filtering must not assign an unassigned table to a project')
}
{
  const request = deferred()
  const { env, api } = harness({ regressResearchTable: () => request.promise })
  const pending = api.runRegression()
  env.table.value.rows[0][0] = 'changed while computing'
  env.regressionY.value = 'Z'
  request.resolve({ equation: 'Y = X' })
  await pending
  const snapshot = JSON.parse(env.regressionKey.value)
  assert.equal(snapshot.table.rows[0][0], 'original', 'request snapshot must not include later edits')
  assert.equal(snapshot.spec.y, 'Y', 'request snapshot must keep original variables')
  assert.equal(env.regressionSpecUsed.value.y, 'Y', 'chart label must describe returned result')
  assert.notEqual(snapshot.table.rows[0][0], env.table.value.rows[0][0])
}
{
  const { env, api } = harness({ regressResearchTable: async () => { throw Error('singular') } })
  await api.runRegression()
  assert.equal(env.regressionError.value, 'tables.regressionError.singular')
}
{
  const httpSource = readFileSync(new URL('../src/api/http.ts', import.meta.url), 'utf8')
  const httpAst = ts.createSourceFile('http.ts', httpSource, ts.ScriptTarget.Latest, true, ts.ScriptKind.TS)
  const httpBodies = ['httpError', 'post'].map((name) => {
    const node = httpAst.statements.find((s) => ts.isFunctionDeclaration(s) && s.name?.text === name)
    assert.ok(node, `Missing ${name}`)
    return node.getText(httpAst).replace(/^export /, '')
  }).join('\n')
  const httpJs = ts.transpileModule(httpBodies, { compilerOptions: { target: ts.ScriptTarget.ES2022 } }).outputText
  const createPost = new Function('fetch', `const BASE_URL = ''; ${httpJs}; return post`)
  for (const body of ['singular', JSON.stringify({ detail: 'singular' })]) {
    const post = createPost(async () => new Response(body, { status: 400 }))
    await assert.rejects(post('/regression', {}, {}, true), (err) => err.status === 400 && err.message === 'singular')
    await assert.rejects(post('/other', {}), (err) => err.status === 400 && err.message === 'HTTP 400')
  }
}
console.log('研究表格保存、回归竞态及错误反馈自测: 9/9 通过')
