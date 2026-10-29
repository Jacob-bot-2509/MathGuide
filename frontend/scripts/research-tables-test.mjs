// Exercise the actual table view persistence functions with delayed and failed requests.
import { readFileSync } from 'node:fs'
import assert from 'node:assert/strict'
import ts from 'typescript'
import { parse } from '@vue/compiler-sfc'

const source = readFileSync(new URL('../src/views/ResearchTablesView.vue', import.meta.url), 'utf8')
const script = parse(source).descriptor.scriptSetup.content
const ast = ts.createSourceFile('view.ts', script, ts.ScriptTarget.Latest, true, ts.ScriptKind.TS)
const names = ['payload', 'openTable', 'saveNow', 'scheduleSave', 'onCompute', 'onExport']
const bodies = names.map((name) => {
  const node = ast.statements.find((s) => ts.isFunctionDeclaration(s) && s.name?.text === name)
  assert.ok(node, `Missing ${name}`)
  return node.getText(ast)
}).join('\n')
const js = ts.transpileModule(bodies, { compilerOptions: { target: ts.ScriptTarget.ES2022 } }).outputText
const factory = new Function('env', `
  const { table, activeProject, dirty, saving, computing, printing, switching, computed, errors,
    getResearchTable, saveResearchTable, computeResearchTable, downloadResearchTable,
    normalize, nextTick, showToast, t, setTimeout, clearTimeout } = env;
  let saveTimer = null, suppressWatch = false;
  ${js}
  return { openTable, saveNow, onCompute, onExport };
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
console.log('研究表格保存竞态自测: 6/6 通过')
