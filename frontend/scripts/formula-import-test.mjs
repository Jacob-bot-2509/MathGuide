import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import ts from 'typescript'
import { parse } from '@vue/compiler-sfc'

const source = readFileSync(new URL('../src/components/chat/FormulaImportDialog.vue', import.meta.url), 'utf8')
const script = parse(source).descriptor.scriptSetup.content
const ast = ts.createSourceFile('formula.ts', script, ts.ScriptTarget.Latest, true, ts.ScriptKind.TS)
const names = ['escapeRegExp', 'compileExpr']
const functions = names.map((name) => {
  const node = ast.statements.find((s) => ts.isFunctionDeclaration(s) && s.name?.text === name)
  assert.ok(node, `Missing ${name}`)
  return node.getText(ast)
})
const funcs = ast.statements.find((s) => ts.isVariableStatement(s) &&
  s.declarationList.declarations.some((d) => d.name.getText(ast) === 'FUNC_NAMES'))
assert.ok(funcs)
const js = ts.transpileModule([funcs.getText(ast), ...functions].join('\n'), {
  compilerOptions: { target: ts.ScriptTarget.ES2022 },
}).outputText
const mappings = { value: {} }
const compile = new Function('mappings', `${js}\nreturn compileExpr`)(mappings)
function check(expr, map, expected) {
  mappings.value.f = map
  assert.equal(compile({ id: 'f', expr }), expected)
}
check('A+B', { A: 'B', B: 'C' }, '=B2+C2')
check('exp(X)+X', { X: 'A' }, '=EXP(A2)+A2')
check('x+xx', { x: 'B', xx: 'A' }, '=B2+A2')
check('速度/时间', { 速度: 'A', 时间: 'B' }, '=A2/B2')
check('x+extra', { x: 'A' }, '=A2+extra')
// Exercise the dialog's real invalidation and asynchronous response handling.
const { ref, watch } = await import('vue')
const runNode = ast.statements.find((s) => ts.isFunctionDeclaration(s) && s.name?.text === 'runValidation')
const watchNode = ast.statements.find((s) => ts.isExpressionStatement(s) &&
  s.getText(ast).startsWith('watch([mappings, targetKeys, result]'))
assert.ok(runNode && watchNode)
const validationJs = ts.transpileModule([watchNode.getText(ast), runNode.getText(ast)].join('\n'), {
  compilerOptions: { target: ts.ScriptTarget.ES2022 },
}).outputText
const state = {
  mappings: ref({ f: { x: 'A' } }), targetKeys: ref({ f: 'B' }),
  result: ref({ formulas: [{ id: 'f' }] }), validations: ref({ f: { compared: 1 } }),
  validating: ref(''), handwritingConfirmed: ref(new Set(['f'])), props: { tableId: 't' }, watch,
  compileExpr: () => `=${state.mappings.value.f.x}2`,
  validateTableFormula: () => new Promise((resolve) => { state.resolve = resolve }),
  showToast: () => {}, t: (key) => key,
}
const runValidation = new Function('env', `
  const { mappings, targetKeys, result, validations, validating, handwritingConfirmed, props, watch,
    compileExpr, validateTableFormula, showToast, t } = env
  ${validationJs}
  return runValidation
`)(state)
state.mappings.value.f.x = 'C'
assert.deepEqual(state.validations.value, {}, 'changing a mapping invalidates old results')
assert.equal(state.handwritingConfirmed.value.size, 0, 'mapping changes require a new handwriting review')
const pending = runValidation({ id: 'f' })
state.targetKeys.value.f = 'C'
state.resolve({ compared: 1 })
await pending
assert.deepEqual(state.validations.value, {}, 'late results for an old target must be discarded')

const savedNode = ast.statements.find((s) => ts.isFunctionDeclaration(s) && s.name?.text === 'useSavedFormula')
assert.ok(savedNode)
const savedJs = ts.transpileModule(savedNode.getText(ast), {
  compilerOptions: { target: ts.ScriptTarget.ES2022 },
}).outputText
const savedEnv = {
  result: ref(null), mappings: ref({}), targetKeys: ref({}), selectedGroups: ref(new Set()),
  defaultMapping: () => 'A', defaultTarget: () => 'B',
}
const useSavedFormula = new Function('env', `
  const { result, mappings, targetKeys, selectedGroups, defaultMapping, defaultTarget } = env
  ${savedJs}
  return useSavedFormula
`)(savedEnv)
const saved = { id: 'f', target: 'y', expr: 'x', variables: ['x'], variableMap: {} }
useSavedFormula({ ...saved, handwriting: true })
assert.equal(savedEnv.result.value.formulas[0].handwriting, true)
useSavedFormula({ ...saved, handwriting: null })
assert.equal(savedEnv.result.value.formulas[0].handwriting, null, 'unknown origin stays unverified')
useSavedFormula({ ...saved, handwriting: false })
assert.equal(savedEnv.result.value.formulas[0].handwriting, false)

const viewSource = readFileSync(new URL('../src/views/ResearchTablesView.vue', import.meta.url), 'utf8')
const viewScript = parse(viewSource).descriptor.scriptSetup.content
const viewAst = ts.createSourceFile('view.ts', viewScript, ts.ScriptTarget.Latest, true, ts.ScriptKind.TS)
const openNode = viewAst.statements.find((s) => ts.isFunctionDeclaration(s) && s.name?.text === 'openFormulaDialog')
assert.ok(openNode)
const openJs = ts.transpileModule(openNode.getText(viewAst), {
  compilerOptions: { target: ts.ScriptTarget.ES2022 },
}).outputText
const view = {
  table: ref({ id: 't' }), saving: ref(false), computing: ref(false), printing: ref(false),
  switching: ref(false), dirty: ref(true), formulaDialogOpen: ref(false), saveNow: async () => false,
}
const makeOpen = (env) => new Function('env', `
  const { table, saving, computing, printing, switching, dirty, formulaDialogOpen, saveNow } = env
  ${openJs}
  return openFormulaDialog
`)(env)
await makeOpen(view)()
assert.equal(view.formulaDialogOpen.value, false, 'failed save must not validate stale data')
view.saveNow = async () => true
await makeOpen(view)()
assert.equal(view.formulaDialogOpen.value, true)
const applyNode = viewAst.statements.find((s) => ts.isFunctionDeclaration(s) && s.name?.text === 'applyMatched')
assert.ok(applyNode)
const applyJs = ts.transpileModule(applyNode.getText(viewAst), {
  compilerOptions: { target: ts.ScriptTarget.ES2022 },
}).outputText
let applied = 0
let confirmed = false
const applyEnv = {
  window: { confirm: () => confirmed }, t: (key) => key,
  applyExtracted: () => { applied++ }, onCompute: async () => {}, formulaMatchOpen: ref(true),
  table: ref({ id: 't' }), formulaMatchSnapshot: ref({ id: 't', data: '{"title":"saved"}' }),
  payload: () => ({ title: 'saved' }), showToast: () => {},
}
const applyMatched = new Function('env', `
  const { window, t, applyExtracted, onCompute, formulaMatchOpen, table, formulaMatchSnapshot, payload, showToast } = env
  ${applyJs}
  return applyMatched
`)(applyEnv)
const candidate = { formula: '=A2', target: 'y', columnKey: 'B', mapping: {} }
applyMatched({ ...candidate, handwriting: true })
applyMatched({ ...candidate, handwriting: null })
assert.equal(applied, 0, 'handwritten or unknown candidates require confirmation')
confirmed = true
applyMatched({ ...candidate, handwriting: true })
assert.equal(applied, 1)
confirmed = false
applyMatched({ ...candidate, handwriting: false })
assert.equal(applied, 2, 'known printed candidates do not require handwriting review')
applyEnv.table.value = { id: 'other' }
applyMatched({ ...candidate, handwriting: false })
assert.equal(applied, 2, 'a stale candidate must not alter a different table')
const actionNames = ['openMatchDialog', 'suggestTopic']
const actionNodes = actionNames.map((name) => {
  const node = viewAst.statements.find((s) => ts.isFunctionDeclaration(s) && s.name?.text === name)
  assert.ok(node, `Missing ${name}`)
  return node.getText(viewAst)
})
const actionJs = ts.transpileModule(actionNodes.join('\n'), {
  compilerOptions: { target: ts.ScriptTarget.ES2022 },
}).outputText
const actionState = {
  table: ref({ id: 't', title: 'old', rows: [['1']] }), saving: ref(false),
  computing: ref(false), printing: ref(false), switching: ref(false), dirty: ref(true),
  formulaMatchSnapshot: ref(null), formulaMatchOpen: ref(false), suggestingTopic: ref(false),
  saveNow: async () => false, payload: () => ({ title: actionState.table.value?.title, rows: actionState.table.value?.rows }),
  suggestTableTopic: () => new Promise((resolve) => { actionState.resolve = resolve }),
  showToast: () => {}, t: (key) => key, window: { confirm: () => true },
}
const actions = new Function('env', `
  const { table, saving, computing, printing, switching, dirty, formulaMatchSnapshot,
    formulaMatchOpen, suggestingTopic, saveNow, payload, suggestTableTopic, showToast, t, window } = env
  ${actionJs}
  return { openMatchDialog, suggestTopic }
`)(actionState)
await actions.openMatchDialog()
assert.equal(actionState.formulaMatchOpen.value, false, 'failed save prevents matching old data')
actionState.saveNow = async () => true
const actionsAfterSave = new Function('env', `
  const { table, saving, computing, printing, switching, dirty, formulaMatchSnapshot,
    formulaMatchOpen, suggestingTopic, saveNow, payload, suggestTableTopic, showToast, t, window } = env
  ${actionJs}
  return { openMatchDialog, suggestTopic }
`)(actionState)
await actionsAfterSave.openMatchDialog()
assert.equal(actionState.formulaMatchOpen.value, true)
assert.equal(actionState.formulaMatchSnapshot.value.id, 't')
const topicPending = actionsAfterSave.suggestTopic()
await Promise.resolve()
actionState.table.value = { id: 'other', title: 'other', rows: [['2']] }
actionState.resolve({ title: 'wrong table', confidence: 0.9 })
await topicPending
assert.equal(actionState.table.value.title, 'other', 'late topic must not overwrite another table')
const matchSource = readFileSync(new URL('../src/components/research/FormulaMatchDialog.vue', import.meta.url), 'utf8')
const matchScript = parse(matchSource).descriptor.scriptSetup.content
const matchAst = ts.createSourceFile('match.ts', matchScript, ts.ScriptTarget.Latest, true, ts.ScriptKind.TS)
const bestNode = matchAst.statements.find((s) => ts.isVariableStatement(s) &&
  s.declarationList.declarations.some((d) => d.name.getText(matchAst) === 'best'))
assert.ok(bestNode)
const bestJs = ts.transpileModule(bestNode.getText(matchAst), {
  compilerOptions: { target: ts.ScriptTarget.ES2022 },
}).outputText
const { computed } = await import('vue')
const candidates = ref([])
const best = new Function('candidates', 'computed', `${bestJs}\nreturn best`)(candidates, computed)
const strong = { formula: '=A2', score: 10, validation: { compared: 1, matched: 1 } }
candidates.value = [{ ...strong, unitConflicts: [{ variable: 'x', expected: 'm', actual: 'km' }] }]
assert.equal(best.value, null, 'unit conflict must prevent a high-confidence recommendation')
candidates.value.push({ ...strong, unitConflicts: [] })
assert.equal(best.value, candidates.value[1], 'a valid lower-ranked candidate may be recommended')
candidates.value = [{ ...strong }]
assert.equal(best.value, null, 'unknown unit compatibility must not be called high-confidence')
const canApplyNode = ast.statements.find((s) => ts.isVariableStatement(s) &&
  s.declarationList.declarations.some((d) => d.name.getText(ast) === 'canApply'))
assert.ok(canApplyNode)
const canApplyJs = ts.transpileModule(canApplyNode.getText(ast), {
  compilerOptions: { target: ts.ScriptTarget.ES2022 },
}).outputText
const activeFormulas = ref([{ id: 'f', handwriting: null }])
const handwritingConfirmed = ref(new Set())
const canApply = new Function('activeFormulas', 'handwritingConfirmed', 'mappingComplete', 'computed',
  `${canApplyJs}\nreturn canApply`)(activeFormulas, handwritingConfirmed, () => true, computed)
assert.equal(canApply.value, false, 'unknown formula origin must require review')
handwritingConfirmed.value = new Set(['f'])
assert.equal(canApply.value, true)
handwritingConfirmed.value = new Set()
activeFormulas.value = [{ id: 'f', handwriting: false }]
assert.equal(canApply.value, true, 'known printed formulas may be applied without handwriting review')
console.log('Formula mapping and validation tests passed')
