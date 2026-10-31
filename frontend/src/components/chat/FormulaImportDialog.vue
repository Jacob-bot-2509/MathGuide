<script setup lang="ts">
/**
 * 图片公式识别弹窗。
 * 流程:上传 1~4 张照片 → 视觉模型提取 → 用户确认独立公式组与列映射 → 写入表格公式。
 * 图片只在内存中转为 base64 发给后端,不落盘。
 */
import { computed, onMounted, ref, watch } from 'vue'
import { t } from '@/utils/i18n'
import { showToast } from '@/utils/toast'
import { getResearchDocPageText } from '@/services/researchService'
import {
  analyzeResearchPage,
  extractFormulas,
  listSavedFormulas,
  validateTableFormula,
  type ExtractedFormula,
  type FormulaExtractResult,
  type FormulaValidation,
  type PageBlock,
  type SavedFormula,
  type TableColumn,
} from '@/services/researchTableService'

const props = defineProps<{
  columns: TableColumn[]
  sourceDocId?: string
  sourcePage?: number
  tableId?: string
}>()
const emit = defineEmits<{
  close: []
  apply: [items: {
    targetLabel: string
    formula: string
    targetColumnKey: string | null
    mapping: Record<string, string>
  }[]]
}>()

interface ImageItem {
  name: string
  mime: string
  data: string
  url: string
}

const images = ref<ImageItem[]>([])
const extracting = ref(false)
const result = ref<FormulaExtractResult | null>(null)
const contextText = ref('')
const savedFormulas = ref<SavedFormula[]>([])
const validations = ref<Record<string, FormulaValidation>>({})
const validating = ref('')
const pageAnalyzing = ref(false)
const pageBlocks = ref<PageBlock[]>([])
const handwritingConfirmed = ref<Set<string>>(new Set())

async function loadSavedFormulas(): Promise<void> {
  if (!props.tableId && !props.sourceDocId) return
  try {
    savedFormulas.value = await listSavedFormulas(props.tableId, props.sourceDocId)
  } catch {
    savedFormulas.value = []
  }
}

/** 按表头匹配度排序,最多展示 3 条历史候选。 */
const sortedSavedFormulas = computed(() => {
  const labels = props.columns.map((c) => `${c.label} ${c.key}`.toLowerCase())
  function score(item: SavedFormula): number {
    let value = 0
    if (props.columns.some((c) => c.label === item.target)) value += 4
    for (const variable of item.variables) {
      const v = variable.toLowerCase()
      if (labels.some((label) => label.includes(v) || v.includes(label))) value += 2
    }
    if (item.variableMap && Object.keys(item.variableMap).length) value += 1
    return value
  }
  return [...savedFormulas.value]
    .sort((a, b) => score(b) - score(a))
    .slice(0, 3)
})

onMounted(async () => {
  void loadSavedFormulas()
  if (!props.sourceDocId || contextText.value) return
  try {
    const page = await getResearchDocPageText(props.sourceDocId, props.sourcePage || 1)
    if (!contextText.value && page.text) contextText.value = page.text
  } catch {
    /* 来源页读取失败时保留手动输入 */
  }
})

function useSavedFormula(saved: SavedFormula): void {  const formula: ExtractedFormula = {
    id: saved.id,
    target: saved.target,
    expr: saved.expr,
    variables: saved.variables,
    variableMap: saved.variableMap,
    units: saved.units,
    handwriting: saved.handwriting ?? null,
    note: '',
  }
  result.value = {
    formulas: [formula],
    groups: [[formula.id]],
    master: null,
    warnings: [],
  }
  mappings.value = { [formula.id]: {} }
  for (const variable of formula.variables) {
    mappings.value[formula.id][variable] = defaultMapping(formula, variable)
  }
  targetKeys.value[formula.id] = defaultTarget(formula)
  selectedGroups.value = new Set([0])
}
const selectedGroups = ref<Set<number>>(new Set())
const mappings = ref<Record<string, Record<string, string>>>({})
const targetKeys = ref<Record<string, string>>({})
watch([mappings, targetKeys, result], () => {
  validations.value = {}
  handwritingConfirmed.value = new Set()
}, { deep: true, flush: 'sync' })
const fileEl = ref<HTMLInputElement | null>(null)

const MAX_IMAGES = 4

const activeIds = computed(() => {
  const res = result.value
  if (!res) return []
  if (res.master) return res.formulas.map((f) => f.id)
  const ids = new Set<string>()
  res.groups.forEach((group, i) => {
    if (selectedGroups.value.has(i)) group.forEach((id) => ids.add(id))
  })
  return [...ids]
})

const activeFormulas = computed(() =>
  (result.value?.formulas ?? []).filter((f) => activeIds.value.includes(f.id)))

const needsGroupChoice = computed(() =>
  !!result.value && !result.value.master && result.value.groups.length > 1)

function formulaById(id: string): ExtractedFormula | undefined {
  return result.value?.formulas.find((f) => f.id === id)
}

function pickFiles(): void {
  fileEl.value?.click()
}

async function onFiles(e: Event): Promise<void> {
  const input = e.target as HTMLInputElement
  const files = Array.from(input.files ?? [])
  input.value = ''
  for (const file of files) {
    if (images.value.length >= MAX_IMAGES) {
      showToast(t('formula.maxImages', { n: MAX_IMAGES }))
      break
    }
    if (!file.type.startsWith('image/')) {
      showToast(t('formula.imageOnly'))
      continue
    }
    if (file.size > 8 * 1024 * 1024) {
      showToast(t('formula.imageTooLarge'))
      continue
    }
    const dataUrl = await readAsDataURL(file)
    const comma = dataUrl.indexOf(',')
    images.value.push({
      name: file.name,
      mime: file.type,
      data: dataUrl.slice(comma + 1),
      url: dataUrl,
    })
  }
}

function readAsDataURL(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => resolve(String(reader.result ?? ''))
    reader.onerror = () => reject(reader.error)
    reader.readAsDataURL(file)
  })
}

function removeImage(index: number): void {
  images.value.splice(index, 1)
}

function defaultMapping(formula: ExtractedFormula, variable: string): string {
  const suggested = formula.variableMap[variable]
  if (suggested) {
    const exact = props.columns.find((c) => c.label === suggested || c.key === suggested)
    if (exact) return exact.key
  }
  const partial = props.columns.find(
    (c) => c.label.includes(variable) || variable.includes(c.label),
  )
  return partial?.key ?? ''
}

function defaultTarget(formula: ExtractedFormula): string {
  const existing = props.columns.find((c) => c.label === formula.target)
  return existing?.key ?? '__new__'
}

async function analyzePage(): Promise<void> {
  if (!images.value.length || pageAnalyzing.value) return
  pageAnalyzing.value = true
  pageBlocks.value = []
  try {
    const res = await analyzeResearchPage(
      images.value.map((i) => ({ mime: i.mime, data: i.data })),
      contextText.value,
      { docId: props.sourceDocId, page: props.sourcePage },
    )
    pageBlocks.value = res.blocks
  } catch {
    showToast(t('formula.pageAnalyzeFail'))
  } finally {
    pageAnalyzing.value = false
  }
}

function blockLabel(kind: PageBlock['kind']): string {
  return t(`formula.block_${kind}`)
}

async function doExtract(): Promise<void> {
  if (!images.value.length || extracting.value) return
  extracting.value = true
  result.value = null
  try {
    const res = await extractFormulas(
      images.value.map((i) => ({ mime: i.mime, data: i.data })),
      props.columns,
      contextText.value,
      {
        docId: props.sourceDocId,
        tableId: props.tableId,
        page: props.sourcePage,
      },
    )
    result.value = res
    const nextMappings: Record<string, Record<string, string>> = {}
    const nextTargets: Record<string, string> = {}
    for (const formula of res.formulas) {
      nextMappings[formula.id] = {}
      for (const variable of formula.variables) {
        nextMappings[formula.id][variable] = defaultMapping(formula, variable)
      }
      nextTargets[formula.id] = defaultTarget(formula)
    }
    mappings.value = nextMappings
    targetKeys.value = nextTargets
    const all = new Set(res.groups.map((_, i) => i))
    selectedGroups.value = res.master || res.groups.length <= 1 ? all : new Set()
  } catch {
    showToast(t('formula.extractFail'))
  } finally {
    extracting.value = false
  }
}

const FUNC_NAMES: Record<string, string> = {
  sqrt: 'SQRT', abs: 'ABS', ln: 'LN', log: 'LOG', exp: 'EXP',
  round: 'ROUND', sum: 'SUM', avg: 'AVERAGE', mean: 'AVERAGE',
  min: 'MIN', max: 'MAX', power: 'POWER',
}

function escapeRegExp(text: string): string {
  return text.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
}

/** 符号公式 → Excel 风格:变量替换为列字母+第 2 行,函数名转大写 */
function compileExpr(formula: ExtractedFormula): string {
  let expr = formula.expr.trim()
  if (expr.includes('=')) expr = expr.slice(expr.lastIndexOf('=') + 1)
  expr = expr
    .replace(/×/g, '*')
    .replace(/÷/g, '/')
    .replace(/[−–]/g, '-')
    .replace(/·/g, '*')
    .replace(/²/g, '^2')
    .replace(/³/g, '^3')
  for (const [name, target] of Object.entries(FUNC_NAMES)) {
    expr = expr.replace(new RegExp(`\\b${name}\\s*\\(`, 'gi'), `${target}(`)
  }
  const map = mappings.value[formula.id] ?? {}
  const variables = Object.keys(map).filter((v) => v && map[v]).sort((a, b) => b.length - a.length)
  if (variables.length) {
    const patterns = variables.map((variable) => {
      const escaped = escapeRegExp(variable)
      return /^[A-Za-z0-9_]+$/.test(variable)
        ? `(?<![A-Za-z0-9_])${escaped}(?![A-Za-z0-9_])`
        : escaped
    })
    const functions = [...new Set(Object.values(FUNC_NAMES))].join('|')
    const tokens = new RegExp(`(\\b(?:${functions})\\s*\\()|(${patterns.join('|')})`, 'g')
    expr = expr.replace(tokens, (_match, fn: string | undefined, variable: string) =>
      fn ?? `${map[variable]}2`)
  }
  return `=${expr}`
}

function mappingComplete(formula: ExtractedFormula): boolean {
  const map = mappings.value[formula.id] ?? {}
  return formula.variables.every((v) => !!map[v])
}

async function runValidation(formula: ExtractedFormula): Promise<void> {
  const target = targetKeys.value[formula.id]
  if (!props.tableId || !target || target === '__new__' || validating.value) return
  const expression = compileExpr(formula)
  const sourceResult = result.value
  delete validations.value[formula.id]
  validating.value = formula.id
  try {
    const validation = await validateTableFormula(props.tableId, target, expression)
    if (result.value === sourceResult && targetKeys.value[formula.id] === target &&
        compileExpr(formula) === expression) {
      validations.value[formula.id] = validation
    }
  } catch {
    showToast(t('formula.validateFail'))
  } finally {
    validating.value = ''
  }
}

const canApply = computed(() =>
  activeFormulas.value.length > 0
  && activeFormulas.value.every((f) => mappingComplete(f)
    && (f.handwriting === false || handwritingConfirmed.value.has(f.id))))

function toggleHandwritingConfirmed(id: string): void {
  const next = new Set(handwritingConfirmed.value)
  if (next.has(id)) next.delete(id)
  else next.add(id)
  handwritingConfirmed.value = next
}

function onApply(): void {
  if (!canApply.value) {
    showToast(t('formula.mapFirst'))
    return
  }
  emit('apply', activeFormulas.value.map((formula) => {
    const key = targetKeys.value[formula.id]
    return {
      targetLabel: formula.target,
      formula: compileExpr(formula),
      targetColumnKey: key && key !== '__new__' ? key : null,
      mapping: { ...(mappings.value[formula.id] ?? {}) },
    }
  }))
}
</script>

<template>
  <div class="fd-overlay" @click.self="emit('close')">
    <section class="fd">
      <header class="fd-head">
        <span class="tech-label">{{ t('formula.title') }}</span>
        <button class="close" @click="emit('close')">✕</button>
      </header>

      <div class="fd-body">
        <div class="upload-row">
          <button class="mini" :disabled="images.length >= MAX_IMAGES" @click="pickFiles">
            {{ t('formula.addImages') }}
          </button>
          <input
            ref="fileEl"
            type="file"
            hidden
            multiple
            accept="image/*"
            @change="onFiles"
          />
          <span class="hint">{{ t('formula.imageHint', { n: MAX_IMAGES }) }}</span>
        </div>

        <div v-if="images.length" class="thumbs">
          <div v-for="(img, i) in images" :key="i" class="thumb">
            <img :src="img.url" :alt="img.name" />
            <button class="thumb-del" @click="removeImage(i)">✕</button>
          </div>
        </div>

        <label class="context-label">{{ t('formula.contextLabel') }}</label>
        <textarea
          v-model="contextText"
          class="context-input"
          rows="3"
          :placeholder="t('formula.contextHint')"
        ></textarea>

        <div v-if="sortedSavedFormulas.length && !result" class="saved-formulas">
          <p class="context-label">{{ t('formula.savedTitle') }}</p>
          <button
            v-for="saved in sortedSavedFormulas"
            :key="saved.id"
            class="saved-formula"
            type="button"
            @click="useSavedFormula(saved)"
          >
            <span class="sf-target">{{ saved.target }}</span>
            <span class="sf-expr">{{ saved.expr }}</span>
          </button>
        </div>

        <button class="mini extract" :disabled="!images.length || pageAnalyzing" @click="analyzePage">
          {{ pageAnalyzing ? t('formula.pageAnalyzing') : t('formula.pageAnalyze') }}
        </button>
        <button class="mini primary extract" :disabled="!images.length || extracting" @click="doExtract">
          {{ extracting ? t('formula.extracting') : t('formula.extract') }}
        </button>

        <div v-if="pageBlocks.length" class="page-blocks">
          <p v-for="(block, index) in pageBlocks" :key="index" class="page-block">
            <span class="pb-kind">{{ blockLabel(block.kind) }}</span>
            <span class="pb-text">{{ block.latex || block.text }}</span>
            <span class="pb-conf">{{ Math.round(block.confidence * 100) }}%</span>
          </p>
        </div>

        <template v-if="result">
          <p v-if="result.master" class="master-note">{{ t('formula.masterDetected') }}</p>
          <p v-if="result.warnings.length" class="warn">{{ result.warnings.join(' · ') }}</p>

          <div v-if="needsGroupChoice" class="groups">
            <p class="section-label">{{ t('formula.pickGroups') }}</p>
            <label v-for="(group, gi) in result.groups" :key="gi" class="group-row">
              <input
                type="checkbox"
                :checked="selectedGroups.has(gi)"
                @change="selectedGroups.has(gi) ? selectedGroups.delete(gi) : selectedGroups.add(gi)"
              />
              <span>{{ t('formula.group', { n: gi + 1 }) }}:</span>
              <span class="group-items">
                {{ group.map((id) => formulaById(id)?.target).filter(Boolean).join('、') }}
              </span>
            </label>
          </div>

          <div class="formula-list">
            <div v-for="formula in activeFormulas" :key="formula.id" class="formula-card">
              <div class="f-head">
                <span class="f-target">{{ formula.target }}</span>
                <span class="f-expr">{{ formula.expr }}</span>
                <span v-if="formula.handwriting !== false" class="f-hand">{{ t(formula.handwriting ? 'formula.handwriting' : 'formula.handwritingUnknown') }}</span>
              </div>
              <label v-if="formula.handwriting !== false" class="f-confirm">
                <input
                  type="checkbox"
                  :checked="handwritingConfirmed.has(formula.id)"
                  @change="toggleHandwritingConfirmed(formula.id)"
                />
                <span>{{ t(formula.handwriting ? 'formula.handwritingConfirm' : 'formula.handwritingUnknownConfirm') }}</span>
              </label>
              <div class="f-row">
                <span class="f-label">{{ t('formula.targetColumn') }}</span>
                <select v-model="targetKeys[formula.id]" class="f-select">
                  <option value="__new__">{{ t('formula.newColumn') }}</option>
                  <option v-for="c in props.columns" :key="c.key" :value="c.key">
                    {{ c.label }} ({{ c.key }}{{ c.type === 'computed' ? ' · ' + t('formula.computed') : '' }})
                  </option>
                </select>
              </div>
              <div
                v-for="variable in formula.variables"
                :key="variable"
                class="f-row"
              >
                <span class="f-label">{{ variable }} →</span>
                <select v-model="mappings[formula.id][variable]" class="f-select">
                  <option value="">{{ t('formula.pickColumn') }}</option>
                  <option v-for="c in columns" :key="c.key" :value="c.key">
                    {{ c.label }} ({{ c.key }})
                  </option>
                </select>
              </div>
              <div class="preview">
                <span class="f-label">{{ t('formula.preview') }}</span>
                <code>{{ compileExpr(formula) }}</code>
              </div>
              <div v-if="tableId && targetKeys[formula.id] && targetKeys[formula.id] !== '__new__'" class="validate">
                <button
                  class="validate-btn"
                  type="button"
                  :disabled="validating === formula.id"
                  @click="runValidation(formula)"
                >{{ validating === formula.id ? t('formula.validating') : t('formula.validate') }}</button>
                <span v-if="validations[formula.id]" class="validate-result">
                  <template v-if="validations[formula.id].compared">
                    {{ t('formula.validateResult', {
                      m: validations[formula.id].matched,
                      n: validations[formula.id].compared,
                      e: validations[formula.id].maxError,
                    }) }}
                  </template>
                  <template v-else>{{ t('formula.validateNoData') }}</template>
                  <span v-for="(error, i) in validations[formula.id].errors" :key="i">
                    · {{ error.col }}{{ error.row >= 0 ? error.row + 2 : '' }}: {{ error.error }}
                  </span>
                </span>
              </div>
            </div>
          </div>

          <button class="mini primary apply" :disabled="!canApply" @click="onApply">
            {{ t('formula.apply') }}
          </button>
        </template>
      </div>
    </section>
  </div>
</template>

<style scoped>
.fd-overlay {
  position: fixed;
  inset: 0;
  z-index: 80;
  background: rgba(3, 6, 12, 0.62);
  backdrop-filter: blur(2px);
  display: grid;
  place-items: center;
  padding: 16px;
}

.fd {
  width: min(760px, 100%);
  max-height: 86vh;
  display: flex;
  flex-direction: column;
  background: var(--bg-panel);
  border: 1px solid var(--line);
  border-radius: 12px;
  box-shadow: 0 18px 48px rgba(0, 0, 0, 0.5);
  overflow: hidden;
}

.fd-head {
  display: flex;
  align-items: center;
  padding: 12px 16px;
  border-bottom: 1px solid var(--line);
  color: var(--cyan);
  font-size: 12px;
}

.close {
  margin-left: auto;
  background: transparent;
  border: none;
  color: var(--text-dim);
  font-size: 14px;
  cursor: pointer;
}

.fd-body {
  padding: 14px 16px 18px;
  overflow-y: auto;
}

.upload-row {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.hint {
  color: var(--text-dim);
  font-size: 10.5px;
}

.thumbs {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  margin-top: 10px;
}

.thumb {
  position: relative;
  width: 92px;
  height: 68px;
  border: 1px solid var(--line);
  border-radius: 7px;
  overflow: hidden;
  background: var(--bg-card);
}

.thumb img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.thumb-del {
  position: absolute;
  top: 2px;
  right: 2px;
  border: none;
  background: rgba(0, 0, 0, 0.55);
  color: #fff;
  border-radius: 4px;
  font-size: 10px;
  cursor: pointer;
}

.context-label {
  display: block;
  margin: 12px 0 5px;
  color: var(--text-dim);
  font-family: var(--font-tech);
  font-size: 10.5px;
}

.context-input {
  width: 100%;
  box-sizing: border-box;
  resize: vertical;
  min-height: 64px;
  background: var(--bg-card);
  border: 1px solid var(--line);
  border-radius: 6px;
  color: var(--text);
  font-family: var(--font-ui);
  font-size: 12px;
  line-height: 1.55;
  padding: 7px 9px;
  outline: none;
}

.context-input:focus {
  border-color: var(--line-bright);
}

.saved-formulas {
  display: flex;
  flex-direction: column;
  gap: 5px;
  margin-top: 10px;
}

.saved-formula {
  display: flex;
  align-items: baseline;
  gap: 8px;
  width: 100%;
  text-align: left;
  background: var(--bg-card);
  border: 1px solid var(--line);
  border-radius: 6px;
  color: var(--text);
  padding: 6px 8px;
  cursor: pointer;
}

.saved-formula:hover {
  border-color: var(--line-bright);
}

.sf-target {
  flex: none;
  color: var(--cyan);
  font-size: 11.5px;
}

.sf-expr {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--text-dim);
  font-size: 11px;
}

.extract {
  margin-top: 12px;
}

.page-blocks {
  margin-top: 10px;
  border: 1px solid var(--line);
  border-radius: 7px;
  background: var(--bg-card);
  max-height: 180px;
  overflow-y: auto;
}

.page-block {
  display: flex;
  align-items: baseline;
  gap: 7px;
  margin: 0;
  padding: 5px 8px;
  border-bottom: 1px solid var(--line);
  font-size: 11px;
  line-height: 1.45;
}

.page-block:last-child {
  border-bottom: none;
}

.pb-kind {
  flex: none;
  color: var(--cyan);
  font-family: var(--font-tech);
  font-size: 9.5px;
}

.pb-text {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--text);
}

.pb-conf {
  margin-left: auto;
  flex: none;
  color: var(--text-dim);
  font-size: 9px;
}

.master-note {
  margin: 12px 0 0;
  color: #ffd166;
  font-size: 11.5px;
}

.warn {
  margin: 8px 0 0;
  color: #ff8a8a;
  font-size: 11.5px;
  line-height: 1.6;
}

.section-label {
  margin: 14px 0 6px;
  color: var(--text-dim);
  font-size: 10.5px;
}

.group-row {
  display: flex;
  align-items: center;
  gap: 7px;
  font-size: 12px;
  color: var(--text);
  margin-bottom: 4px;
}

.group-items {
  color: var(--text-dim);
}

.formula-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
  margin-top: 12px;
}

.formula-card {
  padding: 10px 12px;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: var(--bg-card);
}

.f-head {
  display: flex;
  gap: 10px;
  align-items: baseline;
  margin-bottom: 7px;
}

.f-hand {
  margin-left: auto;
  color: #ffd166;
  border: 1px solid rgba(255, 209, 102, 0.45);
  border-radius: 999px;
  padding: 0 6px;
  font-size: 9.5px;
}

.f-confirm {
  display: flex;
  align-items: center;
  gap: 6px;
  margin: 0 0 7px;
  color: #ffd166;
  font-size: 11px;
  cursor: pointer;
}

.f-target {
  color: var(--cyan);
  font-size: 13px;
}

.f-expr {
  color: var(--text);
  font-family: var(--font-tech);
  font-size: 12px;
  word-break: break-all;
}

.f-row,
.preview {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 5px;
}

.f-label {
  width: 90px;
  flex-shrink: 0;
  color: var(--text-dim);
  font-size: 11px;
}

.f-select {
  flex: 1;
  min-width: 0;
  background: var(--bg-panel);
  color: var(--text);
  border: 1px solid var(--line);
  border-radius: 6px;
  padding: 5px 7px;
  font-size: 12px;
}

.preview code {
  color: #ffd166;
  font-family: var(--font-tech);
  font-size: 12px;
  word-break: break-all;
}

.validate {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 6px;
  flex-wrap: wrap;
}

.validate-btn {
  background: transparent;
  border: 1px solid var(--line);
  color: var(--cyan);
  border-radius: 5px;
  font-size: 10.5px;
  padding: 2px 8px;
  cursor: pointer;
}

.validate-btn:disabled {
  opacity: 0.55;
  cursor: wait;
}

.validate-result {
  color: var(--text-dim);
  font-size: 10.5px;
}

.mini {
  background: transparent;
  border: 1px solid var(--line-bright);
  color: var(--cyan);
  border-radius: 6px;
  padding: 6px 12px;
  font-size: 11.5px;
  cursor: pointer;
}

.mini.primary {
  background: color-mix(in srgb, var(--cyan) 12%, transparent);
}

.mini:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.apply {
  margin-top: 14px;
}
</style>
