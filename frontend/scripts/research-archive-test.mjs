// Exercise the actual archive save queue with delayed and failed requests.
import { readFileSync } from 'node:fs'
import assert from 'node:assert/strict'
import ts from 'typescript'
import { parse } from '@vue/compiler-sfc'

const source = readFileSync(new URL('../src/components/chat/ResearchArchivePanel.vue', import.meta.url), 'utf8')
const script = parse(source).descriptor.scriptSetup.content
const ast = ts.createSourceFile('archive.ts', script, ts.ScriptTarget.Latest, true, ts.ScriptKind.TS)
const names = ['save', 'savePending', 'onDelete', 'hasUnsavedChanges', 'confirmClose']
const bodies = names.map((name) => {
  const node = ast.statements.find((s) => ts.isFunctionDeclaration(s) && s.name?.text === name)
  assert.ok(node, `Missing ${name}`)
  return node.getText(ast)
}).join('\n')
const js = ts.transpileModule(bodies, { compilerOptions: { target: ts.ScriptTarget.ES2022 } }).outputText
const factory = new Function('env', `
  const { project, projects, activeId, docs, pendingPatches, savingProjects, failedProjects,
    deletingProjects, updateResearchProject, deleteResearchProject, showToast, t, window } = env;
  ${js}
  return { save, savePending, onDelete, confirmClose };
`)
const deferred = () => {
  let resolve, reject
  const promise = new Promise((yes, no) => { resolve = yes; reject = no })
  return { promise, resolve, reject }
}
const tick = () => new Promise((resolve) => setTimeout(resolve, 0))
function harness(overrides = {}) {
  const env = {
    projects: { value: [
      { id: 'A', title: 'A', goal: 'old', approach: '', notes: '', status: 'active', updatedAt: 1 },
      { id: 'B', title: 'B', goal: '', approach: '', notes: '', status: 'active', updatedAt: 1 },
    ] },
    activeId: { value: 'A' }, docs: { value: [] }, pendingPatches: {}, savingProjects: {}, failedProjects: {}, deletingProjects: {},
    updateResearchProject: async () => { throw Error('not mocked') },
    deleteResearchProject: async () => {}, showToast: () => {}, t: (key) => key,
    window: { confirm: () => true }, ...overrides,
  }
  env.project = { get value() { return env.projects.value.find((p) => p.id === env.activeId.value) ?? null } }
  return { env, api: factory(env) }
}
{
  const first = deferred(), second = deferred(), requests = []
  const { env, api } = harness({ updateResearchProject: (id, patch) => {
    requests.push({ id, patch })
    return requests.length === 1 ? first.promise : second.promise
  } })
  api.save({ goal: 'first' })
  api.save({ goal: 'second' })
  assert.equal(requests.length, 1, 'updates to one project must be serialized')
  first.resolve({ ...env.projects.value[0], goal: 'first', updatedAt: 2 })
  await tick()
  assert.equal(env.projects.value[0].goal, 'second', 'old response must not overwrite newer edit')
  assert.equal(requests[1].patch.goal, 'second')
  second.resolve({ ...env.projects.value[0], updatedAt: 3 })
  await tick()
  assert.equal(env.projects.value[0].goal, 'second')
  assert.equal(env.failedProjects.A, false)
}
{
  let attempts = 0
  const { env, api } = harness({ updateResearchProject: async (id, patch) => {
    if (++attempts === 1) throw Error('offline')
    return { ...env.projects.value[0], ...patch, updatedAt: 2 }
  } })
  api.save({ goal: 'draft' })
  await tick()
  assert.equal(env.projects.value[0].goal, 'draft')
  assert.equal(env.failedProjects.A, true)
  assert.equal(env.pendingPatches.A.goal, 'draft')
  await api.savePending('A')
  assert.equal(env.failedProjects.A, false)
  assert.equal(env.pendingPatches.A, undefined)
}
{
  const request = deferred()
  const { env, api } = harness({ deleteResearchProject: () => request.promise })
  const pending = api.onDelete()
  env.activeId.value = 'B'
  request.resolve()
  await pending
  assert.deepEqual(env.projects.value.map((p) => p.id), ['B'])
  assert.equal(env.activeId.value, 'B', 'switching during deletion must preserve the selected project')
}
{
  const { env, api } = harness({ window: { confirm: () => false } })
  env.pendingPatches.A = { goal: 'draft' }
  assert.equal(api.confirmClose(), false, 'closing must warn before discarding unsaved changes')
  delete env.pendingPatches.A
  assert.equal(api.confirmClose(), true)
}
console.log('研究档案异步保存自测: 4/4 通过')
