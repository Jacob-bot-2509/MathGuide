<script setup lang="ts">
/**
 * 科研实验数据表:导入模板 → 录入数据 → 公式计算 → 导出。
 * 表格不是模型生成的代码,而是结构化 schema 由固定组件渲染;
 * 公式计算全部在服务端(Decimal + 白名单 AST),前端只展示结果。
 */
import { computed as vueComputed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { onBeforeRouteLeave, useRoute, useRouter } from 'vue-router'
import { t } from '@/utils/i18n'
import { showToast } from '@/utils/toast'
import FormulaImportDialog from '@/components/chat/FormulaImportDialog.vue'
import FormulaMatchDialog from '@/components/research/FormulaMatchDialog.vue'
import TableChart from '@/components/research/TableChart.vue'
import {
  createResearchTable,
  computeResearchTable,
  deleteResearchTable,
  downloadResearchTable,
  getResearchTable,
  importResearchTable,
  listResearchTables,
  printResearchTable,
  saveResearchTable,
  statsResearchTable,
  suggestTableTopic,
  type FormulaCandidate,
  type ResearchTable,
  type TableColumn,
  type TableError,
  type TableMerge,
  type TableStatsResult,
  type TableSummary,
} from '@/services/researchTableService'
import { listResearchProjects, downloadResearchReport, type ResearchProject } from '@/services/researchService'

const router = useRouter()
const route = useRoute()
const tables = ref<TableSummary[]>([])
const projects = ref<ResearchProject[]>([])
const table = ref<ResearchTable | null>(null)
const computed = ref<Record<string, string[]>>({})
const errors = ref<TableError[]>([])
const activeProject = ref('')
const importing = ref(false)
const exportingReport = ref(false)
const saving = ref(false)
const computing = ref(false)
const printing = ref(false)
const switching = ref(false)
const fileEl = ref<HTMLInputElement | null>(null)
const gridEl = ref<HTMLTableElement | null>(null)
const formulaDialogOpen = ref(false)
const formulaMatchOpen = ref(false)
const formulaMatchSnapshot = ref<{ id: string; data: string } | null>(null)
const suggestingTopic = ref(false)
const dirty = ref(false)

/* ---------- 左侧列表重命名 ---------- */
const renamingId = ref('')
const renameValue = ref('')
const renameSaving = ref(false)

function startRename(item: TableSummary, event: Event): void {
  event.stopPropagation()
  renamingId.value = item.id
  renameValue.value = item.title
  nextTick(() => {
    const el = document.querySelector<HTMLInputElement>('.table-item .ti-rename')
    el?.focus()
    el?.select()
  })
}

function cancelRename(): void {
  renamingId.value = ''
  renameValue.value = ''
}

async function commitRename(item: TableSummary): Promise<void> {
  if (renamingId.value !== item.id || renameSaving.value) return
  const title = renameValue.value.trim().slice(0, 120)
  if (!title || title === item.title) {
    cancelRename()
    return
  }
  // 正在编辑同一张表:先把草稿落库,避免重命名用旧数据覆盖未保存内容
  if (table.value?.id === item.id && dirty.value && !(await saveNow(true))) return
  renameSaving.value = true
  try {
    const full = await getResearchTable(item.id)
    const saved = await saveResearchTable(item.id, {
      title,
      columns: full.columns,
      rows: full.rows,
      formulas: full.formulas,
      rowLabels: full.rowLabels,
      merges: full.merges,
      colWidths: full.colWidths,
      rowHeights: full.rowHeights,
      projectId: full.projectId ?? null,
      source: full.source ?? null,
    })
    item.title = saved.title
    if (table.value?.id === item.id) {
      suppressWatch = true
      table.value.title = saved.title
      await nextTick()
      suppressWatch = false
      dirty.value = false
    }
    cancelRename()
  } catch {
    showToast(t('tables.renameFail'))
  } finally {
    renameSaving.value = false
  }
}

/* ---------- 统计与图表 ---------- */
const analysisOpen = ref(false)
const analysisTab = ref<'stats' | 'chart'>('stats')
const analysisLoading = ref(false)
const analysis = ref<TableStatsResult | null>(null)
const analysisKey = ref('')
const chartType = ref<'line' | 'scatter' | 'bar'>('line')
const chartX = ref('row')
const chartY = ref<string[]>([])
const chartRef = ref<{
  downloadSvg: (name?: string) => void
  downloadPng: (name?: string) => Promise<void>
} | null>(null)

const numericSeries = vueComputed(() => analysis.value?.series ?? [])
const chartSeries = vueComputed(() => {
  const chosen = numericSeries.value.filter((s) => chartY.value.includes(s.key))
  return chosen.length ? chosen : numericSeries.value.slice(0, 2)
})
const chartXValues = vueComputed<number[] | null>(() => {
  if (chartX.value === 'row') return null
  const series = numericSeries.value.find((s) => s.key === chartX.value)
  return series ? series.values.map((v) => (typeof v === 'number' ? v : Number.NaN)) : null
})

let saveTimer: ReturnType<typeof setTimeout> | null = null
let suppressWatch = false

const computedColumns = vueComputed(() =>
  table.value ? table.value.columns.filter((c) => c.type === 'computed') : [])

/** 表格总宽 = 行名列 120 + 各列宽,保证拖拽列宽时像素级生效 */
const gridWidth = vueComputed(() => {
  if (!table.value) return 0
  return table.value.columns.reduce(
    (sum, _col, i) => sum + (Number(table.value?.colWidths[i]) || 120),
    120,
  )
})

/* ---------- 合并单元格与选区 ---------- */
interface Rect { r1: number; c1: number; r2: number; c2: number }
const selectionStart = ref<{ r: number; c: number } | null>(null)
const selectionEnd = ref<{ r: number; c: number } | null>(null)
const menu = ref<{ x: number; y: number } | null>(null)
let dragging = false

const mergeMap = vueComputed(() => {
  const anchors = new Map<string, TableMerge>()
  const covered = new Set<string>()
  for (const m of table.value?.merges ?? []) {
    anchors.set(`${m.r1}-${m.c1}`, m)
    for (let r = m.r1; r <= m.r2; r++) {
      for (let c = m.c1; c <= m.c2; c++) {
        if (r !== m.r1 || c !== m.c1) covered.add(`${r}-${c}`)
      }
    }
  }
  return { anchors, covered }
})

function mergeAt(r: number, c: number): TableMerge | null {
  for (const m of table.value?.merges ?? []) {
    if (r >= m.r1 && r <= m.r2 && c >= m.c1 && c <= m.c2) return m
  }
  return null
}

function isCovered(r: number, c: number): boolean {
  return mergeMap.value.covered.has(`${r}-${c}`)
}

function spanRows(r: number, c: number): number {
  const m = mergeMap.value.anchors.get(`${r}-${c}`)
  return m ? m.r2 - m.r1 + 1 : 1
}

function spanCols(r: number, c: number): number {
  const m = mergeMap.value.anchors.get(`${r}-${c}`)
  return m ? m.c2 - m.c1 + 1 : 1
}

function expandPoint(r: number, c: number): { r: number; c: number } {
  const m = mergeAt(r, c)
  return m ? { r: m.r1, c: m.c1 } : { r, c }
}

const selection = vueComputed<Rect | null>(() => {
  if (!selectionStart.value || !selectionEnd.value) return null
  const a = expandPoint(selectionStart.value.r, selectionStart.value.c)
  const b = expandPoint(selectionEnd.value.r, selectionEnd.value.c)
  return {
    r1: Math.min(a.r, b.r), c1: Math.min(a.c, b.c),
    r2: Math.max(a.r, b.r), c2: Math.max(a.c, b.c),
  }
})

function intersects(a: Rect, b: TableMerge): boolean {
  return a.r1 <= b.r2 && a.r2 >= b.r1 && a.c1 <= b.c2 && a.c2 >= b.c1
}

function isSelected(r: number, c: number): boolean {
  const sel = selection.value
  if (!sel) return false
  if (r < sel.r1 || r > sel.r2 || c < sel.c1 || c > sel.c2) return false
  return true
}

const canMerge = vueComputed(() => {
  const sel = selection.value
  if (!sel || (sel.r1 === sel.r2 && sel.c1 === sel.c2)) return false
  return !(table.value?.merges ?? []).some((m) => intersects(sel, m))
})

const canSplit = vueComputed(() => {
  const sel = selection.value
  if (!sel) return false
  return (table.value?.merges ?? []).some((m) => intersects(sel, m))
})

/** 输入框内的原生文本选择会吞掉 mouseover,横向拖不清;用 elementFromPoint 解析指针所在格 */
function onDragSelect(e: MouseEvent): void {
  if (!dragging || (e.buttons & 1) === 0) {
    endDragSelect()
    return
  }
  const el = document.elementFromPoint(e.clientX, e.clientY) as HTMLElement | null
  const td = el?.closest?.('td[data-r]') as HTMLElement | null
  if (!td) return
  const r = Number(td.dataset.r)
  const c = Number(td.dataset.c)
  if (Number.isNaN(r) || Number.isNaN(c)) return
  const end = selectionEnd.value
  if (end?.r !== r || end?.c !== c) selectionEnd.value = { r, c }
  e.preventDefault()
}

function endDragSelect(): void {
  dragging = false
  window.removeEventListener('mousemove', onDragSelect)
  window.removeEventListener('mouseup', endDragSelect)
}

function onCellMouseDown(e: MouseEvent, r: number, c: number): void {
  if (e.button !== 0) return
  selectionStart.value = { r, c }
  selectionEnd.value = { r, c }
  menu.value = null
  dragging = true
  window.addEventListener('mousemove', onDragSelect)
  window.addEventListener('mouseup', endDragSelect)
}

function onCellContextMenu(e: MouseEvent, r: number, c: number): void {
  e.preventDefault()
  const sel = selection.value
  if (!sel || r < sel.r1 || r > sel.r2 || c < sel.c1 || c > sel.c2) {
    selectionStart.value = { r, c }
    selectionEnd.value = { r, c }
  }
  menu.value = { x: e.clientX, y: e.clientY }
}

function closeMenu(): void {
  menu.value = null
}

function doMerge(): void {
  const sel = selection.value
  if (!sel || !canMerge.value || !table.value) return
  if ((table.value.merges ?? []).some((m) => intersects(sel, m))) {
    showToast(t('tables.mergeOverlap'))
    return
  }
  const coveredValues = table.value.rows
    .slice(sel.r1, sel.r2 + 1)
    .flatMap((row, ri) => row.slice(sel.c1, sel.c2 + 1)
      .filter((v, ci) => !(sel.r1 + ri === sel.r1 && sel.c1 + ci === sel.c1) && v !== ''))
  if (coveredValues.length && !window.confirm(t('tables.mergeDiscard'))) return
  for (let r = sel.r1; r <= sel.r2; r++) {
    for (let c = sel.c1; c <= sel.c2; c++) {
      if (r !== sel.r1 || c !== sel.c1) table.value.rows[r][c] = ''
    }
  }
  table.value.merges = [...(table.value.merges ?? []), sel]
  menu.value = null
  computed.value = {}
  errors.value = []
}

function doSplit(): void {
  const sel = selection.value
  if (!sel || !table.value) return
  table.value.merges = (table.value.merges ?? []).filter((m) => !intersects(sel, m))
  menu.value = null
  computed.value = {}
  errors.value = []
}

function focusCell(row: number, col: number): void {
  if (!table.value) return
  const point = expandPoint(
    Math.max(0, Math.min(row, table.value.rows.length - 1)),
    Math.max(0, Math.min(col, table.value.columns.length - 1)),
  )
  let r = point.r
  let c = point.c
  const cols = table.value.columns
  let guard = 0
  while (cols[c]?.type === 'computed' && guard < cols.length) {
    c += 1
    if (c >= cols.length) {
      c = 0
      r += 1
      if (r >= table.value.rows.length) {
        table.value.rows.push(Array(cols.length).fill(''))
        table.value.rowLabels.push('')
        table.value.rowHeights.push(30)
      }
    }
    guard += 1
  }
  nextTick(() => {
    const el = gridEl.value?.querySelector<HTMLInputElement>(`[data-cell="${r}-${c}"]`)
    el?.focus()
    el?.select()
  })
}

function indexToCol(index: number): string {
  let n = index + 1
  let out = ''
  while (n > 0) {
    n -= 1
    out = String.fromCharCode(65 + (n % 26)) + out
    n = Math.floor(n / 26)
  }
  return out
}

function normalize(tableValue: ResearchTable): ResearchTable {
  const width = tableValue.columns.length
  const rows = tableValue.rows.map((row) => {
    const copy = [...row]
    while (copy.length < width) copy.push('')
    return copy.slice(0, width)
  })
  const rowLabels = Array.isArray(tableValue.rowLabels)
    ? tableValue.rowLabels.slice(0, rows.length).map((v) => String(v))
    : []
  while (rowLabels.length < rows.length) rowLabels.push('')
  const merges = Array.isArray(tableValue.merges)
    ? tableValue.merges.filter((m) => m && m.r1 <= m.r2 && m.c1 <= m.c2 &&
      m.r1 >= 0 && m.c1 >= 0 && m.r2 < rows.length && m.c2 < width)
    : []
  const colWidths = Array.from({ length: width }, (_, i) => {
    const value = Number(tableValue.colWidths?.[i])
    return Number.isFinite(value) ? Math.min(600, Math.max(40, value)) : 120
  })
  const rowHeights = Array.from({ length: rows.length }, (_, i) => {
    const value = Number(tableValue.rowHeights?.[i])
    return Number.isFinite(value) ? Math.min(300, Math.max(24, value)) : 30
  })
  const rowSources = Array.from({ length: rows.length }, (_, i) => {
    const source = tableValue.rowSources?.[i]
    return source?.docId ? source : null
  })
  return { ...tableValue, rows, rowLabels, merges, colWidths, rowHeights, rowSources }
}

function payload() {
  const value = table.value
  return {
    title: value?.title ?? '',
    columns: value?.columns ?? [],
    rows: value?.rows ?? [],
    formulas: value?.formulas ?? {},
    rowLabels: value?.rowLabels ?? [],
    merges: value?.merges ?? [],
    colWidths: value?.colWidths ?? [],
    rowHeights: value?.rowHeights ?? [],
    projectId: value ? value.projectId : (activeProject.value || null),
    source: value?.source ?? null,
    rowSources: value?.rowSources ?? [],
  }
}

async function loadLists(): Promise<void> {
  try {
    const [ts, ps] = await Promise.all([
      listResearchTables(activeProject.value || undefined),
      listResearchProjects(),
    ])
    tables.value = ts
    projects.value = ps
  } catch {
    /* 未登录/后端不可达时保持空列表 */
  }
}

async function openTable(id: string): Promise<void> {
  if (switching.value || saving.value || computing.value || printing.value || table.value?.id === id) return
  switching.value = true
  try {
    if (dirty.value && !(await saveNow(true))) return
    const value = normalize(await getResearchTable(id))
    suppressWatch = true
    table.value = value
    computed.value = {}
    errors.value = []
    dirty.value = false
    await nextTick()
    suppressWatch = false
    if (Object.keys(value.formulas).length) await onCompute(true)
  } catch {
    showToast(t('tables.loadFail'))
  } finally {
    suppressWatch = false
    switching.value = false
  }
}

async function onImport(e: Event): Promise<void> {
  const input = e.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''
  if (!file || importing.value || switching.value || saving.value || computing.value || printing.value) return
  switching.value = true
  importing.value = true
  try {
    if (dirty.value && !(await saveNow(true))) return
    const created = normalize(await importResearchTable(
      file, activeProject.value || undefined))
    suppressWatch = true
    table.value = created
    computed.value = {}
    errors.value = []
    await nextTick()
    suppressWatch = false
    await loadLists()
    showToast(t('tables.imported'))
  } catch {
    showToast(t('tables.importFail'))
  } finally {
    importing.value = false
    switching.value = false
  }
}

async function onCreate(): Promise<void> {
  if (switching.value || saving.value || computing.value || printing.value) return
  switching.value = true
  try {
    if (dirty.value && !(await saveNow(true))) return
    const columns: TableColumn[] = [
      { key: 'A', label: 'A', type: 'text' },
      { key: 'B', label: 'B', type: 'text' },
    ]
    const created = normalize(await createResearchTable({
      title: t('tables.defaultTitle'),
      columns,
      rows: Array.from({ length: 5 }, () => ['', '']),
      formulas: {},
      rowLabels: Array.from({ length: 5 }, () => ''),
      merges: [],
      colWidths: [120, 120],
      rowHeights: Array.from({ length: 5 }, () => 30),
      projectId: activeProject.value || null,
    }))
    suppressWatch = true
    table.value = created
    computed.value = {}
    errors.value = []
    await nextTick()
    suppressWatch = false
    dirty.value = false
    await loadLists()
  } catch {
    showToast(t('tables.saveFail'))
  } finally {
    switching.value = false
  }
}

async function saveNow(silent = false): Promise<boolean> {
  if (!table.value) return true
  if (saving.value || computing.value || printing.value) return false
  if (saveTimer) { clearTimeout(saveTimer); saveTimer = null }
  const id = table.value.id
  const snapshot = JSON.stringify(payload())
  saving.value = true
  try {
    const saved = await saveResearchTable(id, JSON.parse(snapshot))
    if (!table.value || table.value.id !== id || JSON.stringify(payload()) !== snapshot) {
      if (table.value?.id === id) scheduleSave()
      return false
    }
    suppressWatch = true
    table.value = { ...table.value, updatedAt: saved.updatedAt }
    dirty.value = false
    await nextTick()
    suppressWatch = false
    if (!silent) showToast(t('tables.saved'))
    return true
  } catch {
    showToast(t('tables.saveFail'))
    return false
  } finally {
    saving.value = false
  }
}

function scheduleSave(): void {
  dirty.value = true
  if (saveTimer) clearTimeout(saveTimer)
  saveTimer = setTimeout(() => {
    saveTimer = null
    void saveNow(true)
  }, 1500)
}

async function onCompute(silent = false): Promise<void> {
  if (!table.value || computing.value || saving.value || printing.value) return
  if (saveTimer) { clearTimeout(saveTimer); saveTimer = null }
  const id = table.value.id
  const snapshot = JSON.stringify(payload())
  computing.value = true
  try {
    const result = await computeResearchTable(id, JSON.parse(snapshot))
    if (!table.value || table.value.id !== id || JSON.stringify(payload()) !== snapshot) {
      if (table.value?.id === id) scheduleSave()
      return
    }
    suppressWatch = true
    table.value = normalize({
      ...result.table,
      columns: (result.columns ?? result.table.columns) as TableColumn[],
    })
    computed.value = result.computed
    errors.value = result.errors
    dirty.value = false
    await nextTick()
    suppressWatch = false
    if (!silent) {
      showToast(result.errors.length
        ? t('tables.computeWithErrors', { n: result.errors.length })
        : t('tables.computeDone'))
    }
  } catch {
    if (!silent) showToast(t('tables.computeFail'))
    if (dirty.value) scheduleSave()
  } finally {
    computing.value = false
  }
}

async function suggestTopic(): Promise<void> {
  if (!table.value || suggestingTopic.value || saving.value || computing.value || printing.value || switching.value) return
  suggestingTopic.value = true
  try {
    const id = table.value.id
    if (dirty.value && !(await saveNow(true))) return
    if (!table.value || table.value.id !== id) return
    const snapshot = JSON.stringify(payload())
    const res = await suggestTableTopic(id)
    if (!table.value || table.value.id !== id || JSON.stringify(payload()) !== snapshot) {
      showToast(t('tables.suggestionStale'))
      return
    }
    if (!res.title || res.confidence < 0.7) {
      showToast(t('tables.topicUnclear'))
      return
    }
    const current = table.value.title.trim()
    if (current && current !== t('tables.defaultTitle')
        && !window.confirm(t('tables.topicReplaceConfirm', { title: res.title }))) {
      return
    }
    table.value.title = res.title
    dirty.value = true
    showToast(t('tables.topicSuggested', { title: res.title }))
  } catch {
    showToast(t('tables.topicFail'))
  } finally {
    suggestingTopic.value = false
  }
}

async function deleteTableById(id: string, hard = false): Promise<void> {
  if (switching.value || saving.value || computing.value || printing.value) return
  const confirmKey = hard ? 'tables.purgeConfirm' : 'tables.deleteConfirm'
  if (!window.confirm(t(confirmKey))) return
  switching.value = true
  try {
    await deleteResearchTable(id, hard)
    if (table.value?.id === id) {
      if (saveTimer) { clearTimeout(saveTimer); saveTimer = null }
      table.value = null
      dirty.value = false
      computed.value = {}
      errors.value = []
    }
    await loadLists()
  } catch {
    showToast(t('tables.deleteFail'))
  } finally {
    switching.value = false
  }
  if (!table.value && tables.value.length) await openTable(tables.value[0].id)
}

function onDelete(): Promise<void> {
  return table.value ? deleteTableById(table.value.id) : Promise.resolve()
}

function onPurge(): Promise<void> {
  return table.value ? deleteTableById(table.value.id, true) : Promise.resolve()
}

async function onExport(format: 'csv' | 'xlsx'): Promise<void> {
  if (!table.value) return
  try {
    if (dirty.value && !(await saveNow(true))) return
    await downloadResearchTable(table.value.id, format, table.value.title)
  } catch {
    showToast(t('tables.exportFail'))
  }
}

async function onExportReport(): Promise<void> {
  if (!activeProject.value || exportingReport.value) return
  if (dirty.value && !(await saveNow(true))) return
  exportingReport.value = true
  try {
    await downloadResearchReport(activeProject.value)
  } catch {
    showToast(t('archive.exportFail'))
  } finally {
    exportingReport.value = false
  }
}

/** 保存草稿并交给本机 WPS/Excel,由用户调整后打印 */
async function onPrint(): Promise<void> {
  if (!table.value || printing.value || saving.value || computing.value || switching.value) return
  const id = table.value.id
  const snapshot = JSON.stringify(payload())
  printing.value = true
  try {
    const res = await printResearchTable(id, JSON.parse(snapshot))
    if (table.value?.id === id && JSON.stringify(payload()) === snapshot) dirty.value = false
    else if (table.value?.id === id) scheduleSave()
    if (res.opened) {
      showToast(t('tables.printOpened'))
    } else {
      showToast(t('tables.printFallback'))
      await downloadResearchTable(id, 'xlsx', table.value?.title ?? '')
    }
  } catch {
    showToast(t('tables.printFail'))
    if (dirty.value) scheduleSave()
  } finally {
    printing.value = false
  }
}

async function openMatchDialog(): Promise<void> {
  if (!table.value || saving.value || computing.value || printing.value || switching.value) return
  if (dirty.value && !(await saveNow(true))) return
  if (!table.value) return
  formulaMatchSnapshot.value = { id: table.value.id, data: JSON.stringify(payload()) }
  formulaMatchOpen.value = true
}

async function openFormulaDialog(): Promise<void> {
  if (!table.value || saving.value || computing.value || printing.value || switching.value) return
  if (dirty.value && !(await saveNow(true))) return
  formulaDialogOpen.value = true
}

async function onChat(): Promise<void> {
  if (!table.value) return
  if (dirty.value && !(await saveNow(true))) return
  await router.push({ path: '/research', query: { tableId: table.value.id } })
}

function openSource(): void {
  const source = table.value?.source
  if (source?.docId) openSourceLink(source)
}

function openRowSource(rowIndex: number): void {
  const source = table.value?.rowSources?.[rowIndex]
  if (source?.docId) openSourceLink(source)
}

function openSourceLink(source: { docId: string; docName?: string; page?: number }): void {
  const query: Record<string, string> = { docId: source.docId }
  if (source.page) query.page = String(source.page)
  if (source.docName) query.title = source.docName
  void router.push({ path: '/research/search', query })
}

async function refreshAnalysis(): Promise<void> {
  if (!table.value || analysisLoading.value) return
  const id = table.value.id
  const snapshot = JSON.stringify(payload())
  analysisLoading.value = true
  try {
    const res = await statsResearchTable(id, payload())
    if (!table.value || table.value.id !== id) return
    analysis.value = res
    analysisKey.value = snapshot
    computed.value = res.computed
    errors.value = res.errors
    if (!chartY.value.length) {
      chartY.value = res.series.slice(0, 2).map((s) => s.key)
    }
    if (chartX.value !== 'row' && !res.series.some((s) => s.key === chartX.value)) {
      chartX.value = 'row'
    }
  } catch {
    showToast(t('tables.statsFail'))
  } finally {
    analysisLoading.value = false
  }
}

async function openAnalysis(tab: 'stats' | 'chart'): Promise<void> {
  analysisTab.value = tab
  analysisOpen.value = true
  if (!analysis.value || analysisKey.value !== JSON.stringify(payload())) {
    await refreshAnalysis()
  }
}

function toggleChartY(key: string): void {
  chartY.value = chartY.value.includes(key)
    ? chartY.value.filter((k) => k !== key)
    : [...chartY.value, key]
}

function onChartXChange(): void {
  if (chartX.value !== 'row') {
    chartY.value = chartY.value.filter((k) => k !== chartX.value)
  }
}

/** 恢复默认布局:清除合并、列宽行高回到初始值;单元格内容与公式保留 */
function resetLayout(): void {
  if (!table.value) return
  if (!window.confirm(t('tables.resetConfirm'))) return
  table.value.merges = []
  table.value.colWidths = table.value.columns.map(() => 120)
  table.value.rowHeights = table.value.rows.map(() => 30)
  selectionStart.value = null
  selectionEnd.value = null
  menu.value = null
  computed.value = {}
  errors.value = []
  dirty.value = true
  showToast(t('tables.resetDone'))
}

function addRow(): void {
  if (!table.value) return
  if (table.value.rows.length >= 200) {
    showToast(t('tables.rowLimit'))
    return
  }
  table.value.rows.push(Array(table.value.columns.length).fill(''))
  table.value.rowLabels.push('')
  table.value.rowHeights.push(30)
}

function addColumn(kind: 'text' | 'computed'): void {
  if (!table.value) return
  if (table.value.columns.length >= 30) {
    showToast(t('tables.colLimit'))
    return
  }
  const key = indexToCol(table.value.columns.length)
  table.value.columns.push({
    key,
    label: kind === 'computed' ? t('tables.computedCol') : key,
    type: kind,
  })
  for (const row of table.value.rows) row.push('')
  table.value.colWidths.push(120)
  if (kind === 'computed') {
    table.value.formulas[key] = '=A2'
  }
}

/** 图片公式写入:目标列不存在时自动新建计算列 */
function ensureComputedColumn(label: string): string {
  if (!table.value) return ''
  const wanted = label.trim() || t('tables.computedCol')
  const existing = table.value.columns.find(
    (c) => c.type === 'computed' && c.label === wanted)
  if (existing) return existing.key
  const key = indexToCol(table.value.columns.length)
  if (table.value.columns.length >= 30) {
    showToast(t('tables.colLimit'))
    return ''
  }
  table.value.columns.push({ key, label: wanted, type: 'computed' })
  for (const row of table.value.rows) row.push('')
  table.value.colWidths.push(120)
  return key
}

function applyExtracted(
  items: {
    targetLabel: string
    formula: string
    targetColumnKey: string | null
    mapping: Record<string, string>
  }[],
): void {
  if (!table.value) return
  for (const item of items) {
    const key = item.targetColumnKey || ensureComputedColumn(item.targetLabel)
    if (!key) continue
    table.value.formulas[key] = item.formula
    const target = table.value.columns.find((c) => c.key === key)
    if (target) {
      target.type = 'computed'
      target.role = 'calculated'
    }
    for (const colKey of Object.values(item.mapping)) {
      if (!colKey || colKey === key) continue
      const source = table.value.columns.find((c) => c.key === colKey)
      if (source && !source.role) source.role = 'measured'
    }
  }
  formulaDialogOpen.value = false
  computed.value = {}
  errors.value = []
  dirty.value = true
}

function applyMatched(candidate: FormulaCandidate): void {
  if (!candidate.formula) return
  if (!table.value || !formulaMatchSnapshot.value || table.value.id !== formulaMatchSnapshot.value.id ||
      JSON.stringify(payload()) !== formulaMatchSnapshot.value.data) {
    formulaMatchOpen.value = false
    showToast(t('tables.suggestionStale'))
    return
  }
  if (candidate.handwriting !== false && !window.confirm(t(
    candidate.handwriting ? 'formula.handwritingConfirm' : 'formula.handwritingUnknownConfirm',
  ))) return
  applyExtracted([{
    targetLabel: candidate.target,
    formula: candidate.formula,
    targetColumnKey: candidate.columnKey || null,
    mapping: candidate.mapping,
  }])
  formulaMatchOpen.value = false
  void onCompute()
}

function applyMatchedMany(candidates: FormulaCandidate[]): void {
  const usable = candidates.filter((c) => c.formula)
  if (!usable.length) return
  if (!table.value || !formulaMatchSnapshot.value || table.value.id !== formulaMatchSnapshot.value.id ||
      JSON.stringify(payload()) !== formulaMatchSnapshot.value.data) {
    formulaMatchOpen.value = false
    showToast(t('tables.suggestionStale'))
    return
  }
  const uncertain = usable.some((c) => c.handwriting !== false)
  if (uncertain && !window.confirm(t('formula.handwritingConfirm'))) return
  applyExtracted(usable.map((candidate) => ({
    targetLabel: candidate.target,
    formula: candidate.formula,
    targetColumnKey: candidate.columnKey || null,
    mapping: candidate.mapping,
  })))
  formulaMatchOpen.value = false
  void onCompute()
}

function cellError(col: string, row: number): string {
  return errors.value.find((e) => e.col === col && e.row === row)?.error ?? ''
}

/** 方向键移动单元格;左右键在文本内还有位置时先移动文本光标 */
function onCellKeydown(e: KeyboardEvent, ri: number, ci: number): void {
  if (!table.value) return
  if (e.key === 'ArrowUp' || e.key === 'ArrowDown') {
    e.preventDefault()
    moveCellFocus(ri, ci, e.key === 'ArrowUp' ? -1 : 1, 0)
    return
  }
  if (e.key !== 'ArrowLeft' && e.key !== 'ArrowRight') return
  // 带修饰键时保留原生文本操作(Shift 选择、Ctrl 按词跳)
  if (e.shiftKey || e.ctrlKey || e.metaKey || e.altKey) return
  const input = e.target as HTMLInputElement
  const start = input.selectionStart ?? 0
  const end = input.selectionEnd ?? 0
  if (start !== end) return
  if (e.key === 'ArrowLeft' && start > 0) return
  if (e.key === 'ArrowRight' && start < input.value.length) return
  e.preventDefault()
  moveCellFocus(ri, ci, 0, e.key === 'ArrowLeft' ? -1 : 1)
}

/** 朝指定方向移动一格,跨过合并覆盖区与计算列 */
function moveCellFocus(ri: number, ci: number, dr: number, dc: number): void {
  if (!table.value) return
  const rows = table.value.rows.length
  const cols = table.value.columns.length
  let r = ri + dr
  let c = ci + dc
  let guard = 0
  // 目标被合并覆盖:若属于别的合并块就落到其锚点;若就是当前块则继续朝该方向跨出去
  while (r >= 0 && r < rows && c >= 0 && c < cols && isCovered(r, c) && guard < rows + cols) {
    const anchor = expandPoint(r, c)
    if (anchor.r !== ri || anchor.c !== ci) {
      r = anchor.r
      c = anchor.c
      break
    }
    r += dr
    c += dc
    guard += 1
  }
  if (r < 0 || r >= rows || c < 0 || c >= cols) return
  focusCell(r, c)
}

/** TSV 解析:支持 Excel 对含制表符/换行单元格的引号包裹 */
function parseTsv(text: string): string[][] {
  const rows: string[][] = []
  let row: string[] = []
  let cell = ''
  let quoted = false
  for (let i = 0; i < text.length; i++) {
    const ch = text[i]
    if (quoted) {
      if (ch === '"') {
        if (text[i + 1] === '"') {
          cell += '"'
          i++
        } else {
          quoted = false
        }
      } else {
        cell += ch
      }
      continue
    }
    if (ch === '"' && cell === '') {
      quoted = true
    } else if (ch === '\t') {
      row.push(cell)
      cell = ''
    } else if (ch === '\n') {
      row.push(cell)
      rows.push(row)
      row = []
      cell = ''
    } else if (ch !== '\r') {
      cell += ch
    }
  }
  row.push(cell)
  rows.push(row)
  while (rows.length && rows[rows.length - 1].every((v) => !v)) rows.pop()
  return rows
}

/** Excel 多单元格粘贴:TSV 按行列铺开,计算列只跳过不覆盖 */
function onCellPaste(e: ClipboardEvent, ri: number, ci: number): void {
  if (!table.value) return
  const text = e.clipboardData?.getData('text/plain') ?? ''
  if (!text.includes('\t') && !text.includes('\n')) return
  e.preventDefault()
  const grid = parseTsv(text)
  if (!grid.length) return
  const width = Math.max(...grid.map((row) => row.length))

  const needRows = Math.min(ri + grid.length, 200)
  while (table.value.rows.length < needRows) addRow()
  const needCols = Math.min(ci + width, 30)
  while (table.value.columns.length < needCols) addColumn('text')

  for (let r = 0; r < grid.length && ri + r < table.value.rows.length; r++) {
    for (let c = 0; c < grid[r].length && ci + c < table.value.columns.length; c++) {
      if (table.value.columns[ci + c].type === 'computed') continue
      if (isCovered(ri + r, ci + c)) continue
      table.value.rows[ri + r][ci + c] = grid[r][c]
    }
  }
  dirty.value = true
}

function deleteRow(ri: number): void {
  if (!table.value) return
  if (table.value.rows.length <= 1) {
    table.value.rows[0] = Array(table.value.columns.length).fill('')
    table.value.rowLabels[0] = ''
    table.value.rowHeights[0] = 30
    return
  }
  table.value.rows.splice(ri, 1)
  table.value.rowLabels.splice(ri, 1)
  table.value.rowHeights.splice(ri, 1)
  table.value.merges = (table.value.merges ?? [])
    .filter((m) => !(m.r1 <= ri && ri <= m.r2))
    .map((m) => (m.r1 > ri ? { ...m, r1: m.r1 - 1, r2: m.r2 - 1 } : m))
  selectionStart.value = null
  selectionEnd.value = null
  computed.value = {}
  errors.value = []
}

/** 删除列:后面的列左移并重新编号,公式里的列引用同步改写。
 * 引用了被删列的公式一并移除,避免留下必定出错的公式。 */
function deleteColumn(ci: number): void {
  if (!table.value || table.value.columns.length <= 1) return
  if (!window.confirm(t('tables.deleteColConfirm'))) return

  const oldKeys = table.value.columns.map((c) => c.key)
  const removed = oldKeys[ci]
  const kept = oldKeys.filter((_, i) => i !== ci)
  const mapping: Record<string, string> = {}
  kept.forEach((key, i) => {
    mapping[key] = indexToCol(i)
  })

  const rewrite = (expr: string): string | null => {
    let invalid = false
    const out = expr.replace(
      /(?<![A-Za-z])(\$?)([A-Za-z]{1,2})(\$?)(\d+)(?![A-Za-z0-9])/g,
      (all, d1: string, letters: string, d2: string, digits: string) => {
        const key = letters.toUpperCase()
        if (key === removed) invalid = true
        const next = mapping[key]
        return next ? `${d1}${next}${d2}${digits}` : all
      },
    )
    return invalid ? null : out
  }

  const newFormulas: Record<string, string> = {}
  const broken: string[] = []
  for (const [target, expr] of Object.entries(table.value.formulas)) {
    if (target === removed) continue
    const nextTarget = mapping[target]
    if (!nextTarget) continue
    const rewritten = rewrite(expr)
    if (rewritten !== null) {
      newFormulas[nextTarget] = rewritten
    } else {
      broken.push(nextTarget)
    }
  }

  table.value.columns.splice(ci, 1)
  table.value.columns.forEach((col, i) => {
    col.key = indexToCol(i)
    if (broken.includes(col.key)) col.type = 'text'
  })
  table.value.rows.forEach((row) => row.splice(ci, 1))
  table.value.colWidths.splice(ci, 1)
  table.value.merges = (table.value.merges ?? [])
    .filter((m) => !(m.c1 <= ci && ci <= m.c2))
    .map((m) => (m.c1 > ci ? { ...m, c1: m.c1 - 1, c2: m.c2 - 1 } : m))
  table.value.formulas = newFormulas
  selectionStart.value = null
  selectionEnd.value = null
  computed.value = {}
  errors.value = []
}

function valueFor(col: TableColumn, rowIndex: number): string {
  if (col.type === 'computed') return computed.value[col.key]?.[rowIndex] ?? ''
  return table.value?.rows[rowIndex]?.[table.value.columns.indexOf(col)] ?? ''
}

/** 拖拽列右边界调整宽度 */
function startColResize(e: MouseEvent, ci: number): void {
  if (!table.value) return
  e.preventDefault()
  e.stopPropagation()
  const startX = e.clientX
  const startWidth = table.value.colWidths[ci] ?? 120
  const move = (ev: MouseEvent) => {
    if (!table.value) return
    table.value.colWidths[ci] = Math.max(40, Math.min(600, startWidth + ev.clientX - startX))
  }
  const up = () => {
    window.removeEventListener('mousemove', move)
    window.removeEventListener('mouseup', up)
  }
  window.addEventListener('mousemove', move)
  window.addEventListener('mouseup', up, { once: true })
}

/** 拖拽行下边界调整高度 */
function startRowResize(e: MouseEvent, ri: number): void {
  if (!table.value) return
  e.preventDefault()
  e.stopPropagation()
  const startY = e.clientY
  const startHeight = table.value.rowHeights[ri] ?? 30
  const move = (ev: MouseEvent) => {
    if (!table.value) return
    table.value.rowHeights[ri] = Math.max(24, Math.min(300, startHeight + ev.clientY - startY))
  }
  const up = () => {
    window.removeEventListener('mousemove', move)
    window.removeEventListener('mouseup', up)
  }
  window.addEventListener('mousemove', move)
  window.addEventListener('mouseup', up, { once: true })
}

function setValue(col: TableColumn, rowIndex: number, value: string): void {
  if (!table.value || col.type === 'computed') return
  const idx = table.value.columns.indexOf(col)
  if (idx < 0) return
  table.value.rows[rowIndex][idx] = value
}

watch(table, () => {
  if (suppressWatch || !table.value) return
  scheduleSave()
}, { deep: true })

watch(() => table.value?.id, () => {
  analysisOpen.value = false
  analysis.value = null
  analysisKey.value = ''
  chartY.value = []
  chartX.value = 'row'
})

function closeMenuOnClick(): void {
  closeMenu()
}

function warnBeforeUnload(event: BeforeUnloadEvent): void {
  if (!dirty.value && !saving.value && !computing.value && !printing.value) return
  event.preventDefault()
  event.returnValue = ''
}

onMounted(async () => {
  window.addEventListener('beforeunload', warnBeforeUnload)
  window.addEventListener('click', closeMenuOnClick)
  if (typeof route.query.projectId === 'string') activeProject.value = route.query.projectId
  await loadLists()
  const wanted = typeof route.query.tableId === 'string' ? route.query.tableId : ''
  if (wanted && tables.value.some((item) => item.id === wanted)) {
    await openTable(wanted)
  } else if (tables.value.length) {
    await openTable(tables.value[0].id)
  }
})

onBeforeRouteLeave(async () => {
  if (saving.value || computing.value || printing.value || switching.value) return false
  return !dirty.value || await saveNow(true)
})

onBeforeUnmount(() => {
  window.removeEventListener('beforeunload', warnBeforeUnload)
  window.removeEventListener('click', closeMenuOnClick)
  if (saveTimer) clearTimeout(saveTimer)
  if (dirty.value && table.value) void saveNow(true)
})
</script>

<template>
  <div class="rt" :inert="computing || printing || switching">
    <header class="rt-head">
      <button class="back" @click="router.push('/research')">{{ t('tables.back') }}</button>
      <div class="title-box">
        <span class="title">{{ t('tables.title') }}</span>
        <span class="tech-label sub">MODULE 02 · DATA TABLE</span>
      </div>
      <div class="head-right">
        <select v-model="activeProject" class="project-select" @change="loadLists">
          <option value="">{{ t('search.allProjects') }}</option>
          <option v-for="p in projects" :key="p.id" :value="p.id">{{ p.title }}</option>
        </select>
        <button class="act" :disabled="importing" @click="fileEl?.click()">
          {{ importing ? t('tables.importing') : t('tables.import') }}
        </button>
        <button class="act" @click="onCreate">{{ t('tables.newTable') }}</button>
        <button
          v-if="activeProject"
          class="act"
          :disabled="exportingReport"
          @click="onExportReport"
        >{{ exportingReport ? t('archive.exportingReport') : t('archive.exportReport') }}</button>
        <input
          ref="fileEl"
          type="file"
          hidden
          accept=".xlsx,.csv,.docx,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,application/vnd.openxmlformats-officedocument.wordprocessingml.document,text/csv"
          @change="onImport"
        />
      </div>
    </header>

    <main class="rt-main">
      <aside class="side">
        <p class="side-title tech-label">{{ t('tables.list') }} · {{ tables.length }}</p>
        <div
          v-for="item in tables"
          :key="item.id"
          class="table-item"
          :class="{ on: table?.id === item.id }"
          role="button"
          tabindex="0"
          @click="openTable(item.id)"
          @keydown.enter.prevent="openTable(item.id)"
          @keydown.space.prevent="openTable(item.id)"
        >
          <input
            v-if="renamingId === item.id"
            v-model="renameValue"
            class="ti-rename"
            maxlength="120"
            @click.stop
            @dblclick.stop
            @keydown.enter.prevent="commitRename(item)"
            @keydown.esc.prevent="cancelRename"
            @blur="commitRename(item)"
          />
          <span v-else class="ti-title" :title="item.title" @dblclick.stop="startRename(item, $event)">
            {{ item.title }}
          </span>
          <span class="ti-meta">{{ item.rows }} × {{ item.columns }}</span>
          <button
            v-if="renamingId !== item.id"
            class="ti-edit"
            :title="t('tables.rename')"
            @click.stop="startRename(item, $event)"
          >✎</button>
          <button
            class="ti-del"
            :title="t('tables.delete')"
            @click.stop="deleteTableById(item.id)"
          >✕</button>
        </div>
        <p v-if="!tables.length" class="side-empty">{{ t('tables.emptyList') }}</p>
      </aside>

      <section v-if="table" class="editor">
        <div class="editor-bar">
          <input v-model="table.title" class="title-input" :placeholder="t('tables.defaultTitle')" />
          <button class="mini" :disabled="suggestingTopic || saving || computing || printing || switching" @click="suggestTopic">
            {{ suggestingTopic ? t('tables.suggestingTopic') : t('tables.suggestTopic') }}
          </button>
          <span class="dirty" :class="{ on: dirty }">{{ dirty ? t('tables.unsaved') : t('tables.savedShort') }}</span>
          <button class="mini" :disabled="saving" @click="saveNow()">{{ t('tables.save') }}</button>
          <button class="mini primary" :disabled="computing" @click="onCompute()">
            {{ computing ? t('tables.computing') : t('tables.complete') }}
          </button>
          <button class="mini" @click="openAnalysis('stats')">{{ t('tables.stats') }}</button>
          <button class="mini" @click="openAnalysis('chart')">{{ t('tables.chart') }}</button>
          <button class="mini" @click="onChat">{{ t('tables.chat') }}</button>
          <button class="mini" @click="onExport('csv')">CSV</button>
          <button class="mini" @click="onExport('xlsx')">XLSX</button>
          <button class="mini" :disabled="printing" @click="onPrint">
            {{ printing ? t('tables.printing') : t('tables.print') }}
          </button>
          <button class="mini danger" @click="onDelete">{{ t('tables.delete') }}</button>
          <button class="mini danger purge" @click="onPurge">{{ t('tables.purge') }}</button>
        </div>

        <div v-if="table.source?.docId" class="source-bar">
          <span class="source-label">{{ t('tables.source') }}</span>
          <button class="source-chip" :title="t('tables.openSource')" @click="openSource">
            {{ table.source.docName || table.source.docId }}
            <template v-if="table.source.page"> · {{ t('viewer.pageNo', { n: table.source.page }) }}</template>
          </button>
        </div>

        <div class="grid-wrap">
          <table ref="gridEl" class="grid" :style="{ width: `${gridWidth}px` }">
            <colgroup>
              <col style="width: 120px" />
              <col
                v-for="(col, ci) in table.columns"
                :key="col.key"
                :style="{ width: `${table.colWidths[ci] ?? 120}px` }"
              />
            </colgroup>
            <thead>
              <tr>
                <th class="row-no">{{ t('tables.rowName') }}</th>
                <th v-for="(col, ci) in table.columns" :key="col.key">
                  <div class="th-box">
                    <span class="col-key tech-label">{{ col.key }}</span>
                    <input v-model="col.label" class="col-label" />
                    <span v-if="col.role === 'measured'" class="role-tag measured">{{ t('tables.measured') }}</span>
                    <span v-else-if="col.role === 'calculated'" class="role-tag calculated">{{ t('tables.calculated') }}</span>
                    <span v-else-if="col.type === 'computed'" class="computed-tag">{{ t('tables.computed') }}</span>
                  </div>
                  <button
                    v-if="table.columns.length > 1"
                    class="col-del"
                    :title="t('tables.deleteCol')"
                    @click="deleteColumn(ci)"
                  >✕</button>
                  <span
                    class="col-resize"
                    :title="t('tables.resizeCol')"
                    @mousedown.stop.prevent="startColResize($event, ci)"
                  ></span>
                </th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="(row, ri) in table.rows"
                :key="ri"
                :data-cols="row.length"
                :style="{ height: `${table.rowHeights[ri] ?? 30}px` }"
              >
                <td class="row-no">
                  <input
                    v-model="table.rowLabels[ri]"
                    class="row-label-input"
                    :placeholder="String(ri + 1)"
                  />
                  <button
                    v-if="table.rowSources?.[ri]?.docId"
                    class="row-src"
                    :title="t('tables.openSource')"
                    @click.stop="openRowSource(ri)"
                  >↗</button>
                  <button class="row-del" :title="t('tables.deleteRow')" @click="deleteRow(ri)">✕</button>
                  <span
                    class="row-resize"
                    :title="t('tables.resizeRow')"
                    @mousedown.stop.prevent="startRowResize($event, ri)"
                  ></span>
                </td>
                <template v-for="(col, ci) in table.columns" :key="col.key">
                  <td
                    v-if="!isCovered(ri, ci)"
                    :rowspan="spanRows(ri, ci)"
                    :colspan="spanCols(ri, ci)"
                    :data-r="ri"
                    :data-c="ci"
                    :class="{
                      'cell-error': cellError(col.key, ri),
                      'cell-selected': isSelected(ri, ci),
                    }"
                    :title="cellError(col.key, ri)"
                    @mousedown="onCellMouseDown($event, ri, ci)"
                    @contextmenu.prevent="onCellContextMenu($event, ri, ci)"
                  >
                    <span v-if="col.type === 'computed'" class="computed-value">
                      {{ valueFor(col, ri) }}
                    </span>
                    <input
                      v-else
                      class="cell"
                      :data-cell="`${ri}-${ci}`"
                      :value="valueFor(col, ri)"
                      @input="setValue(col, ri, ($event.target as HTMLInputElement).value)"
                      @keydown="onCellKeydown($event, ri, ci)"
                      @paste="onCellPaste($event, ri, ci)"
                    />
                    <span
                      class="col-resize"
                      :title="t('tables.resizeCol')"
                      @mousedown.stop.prevent="startColResize($event, ci + spanCols(ri, ci) - 1)"
                    ></span>
                  </td>
                </template>
              </tr>
            </tbody>
          </table>
        </div>

        <section v-if="analysisOpen" class="analysis">
          <header class="analysis-head">
            <button
              class="analysis-tab"
              :class="{ on: analysisTab === 'stats' }"
              @click="openAnalysis('stats')"
            >{{ t('tables.stats') }}</button>
            <button
              class="analysis-tab"
              :class="{ on: analysisTab === 'chart' }"
              @click="openAnalysis('chart')"
            >{{ t('tables.chart') }}</button>
            <span class="analysis-spacer"></span>
            <button class="mini" :disabled="analysisLoading" @click="refreshAnalysis">
              {{ analysisLoading ? t('tables.computing') : t('tables.refresh') }}
            </button>
            <button class="mini" @click="analysisOpen = false">{{ t('common.close') }}</button>
          </header>

          <div v-if="analysisLoading" class="analysis-empty">{{ t('tables.computing') }}</div>

          <template v-else-if="analysisTab === 'stats'">
            <div v-if="!analysis?.stats.length" class="analysis-empty">
              {{ t('tables.noNumeric') }}
            </div>
            <div v-else class="stats-wrap">
              <table class="stats-table">
                <thead>
                  <tr>
                    <th>{{ t('tables.column') }}</th>
                    <th>n</th>
                    <th>{{ t('tables.missing') }}</th>
                    <th>{{ t('tables.mean') }}</th>
                    <th>{{ t('tables.median') }}</th>
                    <th>{{ t('tables.stdev') }}</th>
                    <th>{{ t('tables.min') }}</th>
                    <th>{{ t('tables.max') }}</th>
                    <th>Q1</th>
                    <th>Q3</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="s in analysis.stats" :key="s.key">
                    <td class="stat-label">{{ s.key }} · {{ s.label }}</td>
                    <td>{{ s.n }}</td>
                    <td>{{ s.missing }}</td>
                    <td>{{ s.mean }}</td>
                    <td>{{ s.median }}</td>
                    <td>{{ s.stdev || '—' }}</td>
                    <td>{{ s.min }}</td>
                    <td>{{ s.max }}</td>
                    <td>{{ s.q1 }}</td>
                    <td>{{ s.q3 }}</td>
                  </tr>
                </tbody>
              </table>
              <div v-if="analysis.correlations.length" class="correlations">
                <span class="corr-title">{{ t('tables.correlations') }}</span>
                <span v-for="c in analysis.correlations" :key="`${c.x}-${c.y}`" class="corr">
                  r({{ c.x }}, {{ c.y }}) = {{ c.r }}
                </span>
              </div>
            </div>
          </template>

          <template v-else>
            <div v-if="!numericSeries.length" class="analysis-empty">
              {{ t('tables.noNumeric') }}
            </div>
            <template v-else>
              <div class="chart-controls">
                <label class="ctl">
                  <span>{{ t('tables.chartType') }}</span>
                  <select v-model="chartType">
                    <option value="line">{{ t('tables.chartLine') }}</option>
                    <option value="scatter">{{ t('tables.chartScatter') }}</option>
                    <option value="bar">{{ t('tables.chartBar') }}</option>
                  </select>
                </label>
                <label class="ctl">
                  <span>{{ t('tables.chartX') }}</span>
                  <select v-model="chartX" @change="onChartXChange">
                    <option value="row">{{ t('tables.chartRow') }}</option>
                    <option v-for="s in numericSeries" :key="s.key" :value="s.key">
                      {{ s.key }} · {{ s.label }}
                    </option>
                  </select>
                </label>
                <div class="y-picks">
                  <span>{{ t('tables.chartY') }}</span>
                  <button
                    v-for="s in numericSeries"
                    :key="s.key"
                    class="y-pick"
                    :class="{ on: chartY.includes(s.key) }"
                    @click="toggleChartY(s.key)"
                  >{{ s.key }} · {{ s.label }}</button>
                </div>
                <div class="chart-actions">
                  <button class="mini" @click="chartRef?.downloadSvg(`${table.title || 'chart'}.svg`)">SVG</button>
                  <button class="mini" @click="chartRef?.downloadPng(`${table.title || 'chart'}.png`)">PNG</button>
                </div>
              </div>
              <TableChart
                ref="chartRef"
                :labels="analysis?.rowLabels ?? []"
                :series="chartSeries"
                :chart-type="chartType"
                :x-values="chartXValues"
              />
            </template>
          </template>
        </section>

        <div
          v-if="menu"
          class="ctx-menu"
          :style="{ left: `${menu.x}px`, top: `${menu.y}px` }"
          @click.stop
        >
          <button :disabled="!canMerge" @click="doMerge">{{ t('tables.merge') }}</button>
          <button :disabled="!canSplit" @click="doSplit">{{ t('tables.split') }}</button>
        </div>

        <div class="editor-foot">
          <button class="mini" @click="addRow">{{ t('tables.addRow') }}</button>
          <button class="mini" @click="addColumn('text')">{{ t('tables.addColumn') }}</button>
          <button class="mini" @click="addColumn('computed')">{{ t('tables.addComputed') }}</button>
          <button class="mini" @click="resetLayout">{{ t('tables.reset') }}</button>
          <span class="hint">{{ t('tables.inputHint') }}</span>
          <span class="hint">{{ t('tables.formulaHint') }}</span>
        </div>

        <div class="formulas">
          <div class="formulas-head">
            <p class="side-title tech-label">{{ t('tables.formulas') }}</p>
            <button
              class="mini"
              :disabled="saving || computing || printing || switching"
              @click="openMatchDialog"
            >{{ t('formula.match') }}</button>
            <button class="mini" :disabled="saving || computing || printing || switching" @click="openFormulaDialog">{{ t('formula.add') }}</button>
          </div>
          <p v-if="!computedColumns.length" class="hint">{{ t('formula.emptyHint') }}</p>
          <div v-for="col in computedColumns" :key="col.key" class="formula-row">
            <span class="f-col">{{ col.key }} · {{ col.label }}</span>
            <input
              v-model="table.formulas[col.key]"
              class="f-input"
              placeholder="=A2*B2"
              spellcheck="false"
            />
          </div>
        </div>

        <div v-if="errors.length" class="errors">
          <p class="side-title tech-label">{{ t('tables.errors') }} · {{ errors.length }}</p>
          <p v-for="(e, i) in errors.slice(0, 20)" :key="i" class="error-line">
            {{ e.row >= 0 ? t('tables.rowNo', { n: e.row + 1 }) : '' }} {{ e.col }}: {{ e.error }}
          </p>
        </div>
      </section>

      <section v-else class="empty-editor">
        <p>{{ t('tables.emptyEditor') }}</p>
      </section>
    </main>

    <FormulaImportDialog
      v-if="formulaDialogOpen && table"
      :columns="table.columns"
      :source-doc-id="table.source?.docId"
      :source-page="table.source?.page"
      :table-id="table.id"
      @close="formulaDialogOpen = false"
      @apply="applyExtracted"
    />

    <FormulaMatchDialog
      v-if="formulaMatchOpen && table"
      :table-id="table.id"
      :doc-id="table.source?.docId"
      @close="formulaMatchOpen = false"
      @apply="applyMatched"
      @apply-many="applyMatchedMany"
    />
  </div>
</template>

<style scoped>
.rt {
  min-height: 100vh;
  display: flex;
  flex-direction: column;
}

.rt-head {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 12px 22px;
  border-bottom: 1px solid var(--line);
  background: var(--bg-panel);
  backdrop-filter: blur(8px);
}

.back {
  background: transparent;
  border: 1px solid var(--line);
  color: var(--text);
  padding: 7px 16px;
  border-radius: 4px;
  font-size: 13px;
  cursor: pointer;
}

.back:hover {
  color: var(--cyan);
  border-color: var(--line-bright);
}

.title-box {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.title {
  color: var(--text-hi);
  font-size: 15px;
  letter-spacing: 0.06em;
}

.sub {
  font-size: 10px;
}

.head-right {
  margin-left: auto;
  display: flex;
  align-items: center;
  gap: 8px;
}

.project-select,
.title-input,
.col-label,
.cell,
.f-input {
  background: var(--bg-card);
  border: 1px solid var(--line);
  border-radius: 6px;
  color: var(--text);
  outline: none;
  font-family: var(--font-ui);
}

.project-select {
  padding: 6px 8px;
  font-size: 12px;
  max-width: 180px;
}

.act {
  background: color-mix(in srgb, var(--cyan) 8%, transparent);
  border: 1px solid var(--line-bright);
  color: var(--cyan);
  padding: 6px 14px;
  border-radius: 6px;
  font-size: 12px;
  cursor: pointer;
}

.act.ghost {
  background: transparent;
  color: var(--text-dim);
  border-color: var(--line);
}

.act:disabled {
  opacity: 0.55;
  cursor: wait;
}

.rt-main {
  flex: 1;
  display: flex;
  min-height: 0;
}

.side {
  width: 220px;
  flex-shrink: 0;
  border-right: 1px solid var(--line);
  padding: 14px 10px;
  overflow-y: auto;
}

.side-title {
  color: var(--text-dim);
  font-size: 10.5px;
  letter-spacing: 0.06em;
  margin: 0 0 8px 6px;
}

.table-item {
  position: relative;
  display: flex;
  flex-direction: column;
  gap: 2px;
  width: 100%;
  text-align: left;
  background: transparent;
  border: 1px solid transparent;
  border-radius: 7px;
  padding: 7px 42px 7px 9px;
  cursor: pointer;
  margin-bottom: 4px;
}

.ti-edit,
.ti-del {
  position: absolute;
  top: 5px;
  background: transparent;
  border: none;
  color: var(--text-dim);
  cursor: pointer;
  font-size: 10px;
  padding: 0 3px;
  opacity: 0;
  transition: opacity var(--dur-fast), color var(--dur-fast);
}

.ti-edit {
  right: 21px;
}

.ti-del {
  right: 5px;
}

.table-item:hover .ti-edit,
.table-item:hover .ti-del,
.table-item:focus-within .ti-edit,
.table-item:focus-within .ti-del {
  opacity: 1;
}

.ti-edit:hover {
  color: var(--cyan);
}

.ti-del:hover {
  color: #ff8a8a;
}

.ti-rename {
  width: 100%;
  box-sizing: border-box;
  background: var(--bg-card);
  border: 1px solid var(--line-bright);
  border-radius: 4px;
  color: var(--text-hi);
  font-size: 12.5px;
  padding: 3px 5px;
  outline: none;
}

.table-item.on {
  border-color: var(--line-bright);
  background: color-mix(in srgb, var(--cyan) 6%, transparent);
}

.ti-title {
  color: var(--text-hi);
  font-size: 12.5px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.ti-meta {
  color: var(--text-dim);
  font-size: 10.5px;
}

.side-empty {
  color: var(--text-dim);
  font-size: 11.5px;
  line-height: 1.6;
  padding: 8px;
}

.editor {
  flex: 1;
  min-width: 0;
  padding: 14px 18px 40px;
  overflow-y: auto;
}

.editor-bar {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.title-input {
  flex: 1;
  min-width: 160px;
  padding: 8px 10px;
  font-size: 14px;
}

.dirty {
  color: var(--text-dim);
  font-size: 10.5px;
}

.dirty.on {
  color: #ffd166;
}

.mini {
  background: transparent;
  border: 1px solid var(--line-bright);
  color: var(--cyan);
  border-radius: 6px;
  padding: 5px 10px;
  font-size: 11.5px;
  cursor: pointer;
}

.mini:hover {
  box-shadow: var(--glow-cyan);
}

.mini:disabled {
  opacity: 0.5;
  cursor: wait;
}

.mini.primary {
  background: color-mix(in srgb, var(--cyan) 12%, transparent);
}

.mini.danger {
  color: #ff8a8a;
  border-color: rgba(255, 138, 138, 0.4);
}

.mini.purge {
  background: rgba(255, 138, 138, 0.12);
  border-color: rgba(255, 138, 138, 0.65);
}

.source-bar {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 10px;
}

.source-label {
  color: var(--text-dim);
  font-family: var(--font-tech);
  font-size: 10.5px;
  letter-spacing: 0.06em;
}

.source-chip {
  max-width: min(520px, 70vw);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  background: color-mix(in srgb, var(--cyan) 7%, transparent);
  border: 1px solid var(--line-bright);
  border-radius: 999px;
  color: var(--cyan);
  padding: 4px 12px;
  font-size: 11px;
  cursor: pointer;
}

.source-chip:hover {
  box-shadow: var(--glow-cyan);
}

.analysis {
  margin-top: 12px;
  border: 1px solid var(--line);
  border-radius: 10px;
  background: var(--bg-card);
  overflow: hidden;
}

.analysis-head {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  border-bottom: 1px solid var(--line);
}

.analysis-tab {
  background: transparent;
  border: 1px solid var(--line);
  border-radius: 999px;
  color: var(--text-dim);
  padding: 4px 14px;
  font-size: 11.5px;
  cursor: pointer;
}

.analysis-tab.on {
  color: var(--cyan);
  border-color: var(--line-bright);
}

.analysis-spacer {
  flex: 1;
}

.analysis-empty {
  padding: 28px 12px;
  text-align: center;
  color: var(--text-dim);
  font-size: 12px;
}

.stats-wrap {
  padding: 10px 12px 12px;
  overflow-x: auto;
}

.stats-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 11.5px;
  color: var(--text);
}

.stats-table th,
.stats-table td {
  border-bottom: 1px solid var(--line);
  padding: 6px 8px;
  text-align: right;
  white-space: nowrap;
}

.stats-table th {
  color: var(--text-dim);
  font-weight: 500;
  font-family: var(--font-tech);
  font-size: 10px;
}

.stats-table th:first-child,
.stats-table td:first-child {
  text-align: left;
}

.stat-label {
  color: var(--text-hi);
}

.correlations {
  display: flex;
  flex-wrap: wrap;
  gap: 8px 16px;
  margin-top: 10px;
  padding-top: 8px;
  border-top: 1px dashed var(--line);
  font-size: 11px;
  color: var(--text-dim);
}

.corr-title {
  color: var(--cyan);
  font-family: var(--font-tech);
  font-size: 10px;
  letter-spacing: 0.05em;
}

.corr {
  font-family: var(--font-tech);
}

.chart-controls {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 10px 14px;
  padding: 10px 12px 4px;
}

.ctl {
  display: flex;
  align-items: center;
  gap: 6px;
  color: var(--text-dim);
  font-size: 11px;
}

.ctl select {
  background: var(--bg-panel);
  border: 1px solid var(--line);
  border-radius: 5px;
  color: var(--text);
  padding: 4px 6px;
  font-size: 11.5px;
}

.y-picks {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
  color: var(--text-dim);
  font-size: 11px;
}

.y-pick {
  background: transparent;
  border: 1px solid var(--line);
  border-radius: 999px;
  color: var(--text-dim);
  padding: 3px 10px;
  font-size: 10.5px;
  cursor: pointer;
}

.y-pick.on {
  color: var(--cyan);
  border-color: var(--line-bright);
  background: color-mix(in srgb, var(--cyan) 9%, transparent);
}

.chart-actions {
  display: flex;
  gap: 6px;
  margin-left: auto;
}

.analysis :deep(.chart-box) {
  padding: 4px 12px 12px;
}

.grid-wrap {
  margin-top: 12px;
  overflow: auto;
  max-height: 56vh;
  border: 1px solid var(--line);
  border-radius: 8px;
}

.grid {
  border-collapse: collapse;
  table-layout: fixed;
}

.grid th,
.grid td {
  border-right: 1px solid var(--line);
  border-bottom: 1px solid var(--line);
  padding: 0;
  vertical-align: middle;
  position: relative;
}

.grid th {
  background: var(--bg-panel);
  position: sticky;
  top: 0;
  z-index: 1;
}

.th-box {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 5px 18px 5px 6px;
  min-width: 0;
  overflow: hidden;
}

.col-key {
  color: var(--cyan);
  font-size: 9.5px;
}

.col-label {
  flex: 1 1 auto;
  width: auto;
  min-width: 0;
  padding: 3px 5px;
  font-size: 12px;
}

.computed-tag {
  flex: none;
  color: #ffd166;
  font-size: 9px;
  border: 1px solid rgba(255, 209, 102, 0.4);
  border-radius: 999px;
  padding: 0 5px;
}

.role-tag {
  flex: none;
  font-size: 9px;
  border-radius: 999px;
  padding: 0 5px;
  border: 1px solid var(--line);
}

.role-tag.measured {
  color: var(--cyan);
  border-color: color-mix(in srgb, var(--cyan) 40%, transparent);
}

.role-tag.calculated {
  color: #ffd166;
  border-color: rgba(255, 209, 102, 0.4);
}

.row-no {
  width: 120px;
  min-width: 120px;
  text-align: center;
  color: var(--text-dim);
  font-size: 10.5px;
  background: var(--bg-panel);
  position: sticky;
  left: 0;
  z-index: 2;
}

.row-label-input {
  width: calc(100% - 38px);
  background: transparent;
  border: none;
  color: var(--text);
  font-size: 11.5px;
  padding: 5px 4px;
  outline: none;
}

.row-label-input:focus {
  background: color-mix(in srgb, var(--cyan) 8%, transparent);
}

.col-resize,
.row-resize {
  position: absolute;
  z-index: 3;
}

.col-resize {
  top: 0;
  right: -3px;
  width: 7px;
  height: 100%;
  cursor: col-resize;
}

.row-resize {
  left: 0;
  bottom: -3px;
  width: 100%;
  height: 7px;
  cursor: row-resize;
}

.col-resize:hover,
.row-resize:hover {
  background: color-mix(in srgb, var(--cyan) 45%, transparent);
}

.cell-selected {
  background: color-mix(in srgb, var(--cyan) 14%, transparent);
  box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--cyan) 55%, transparent);
}

.ctx-menu {
  position: fixed;
  z-index: 90;
  display: flex;
  flex-direction: column;
  min-width: 120px;
  padding: 5px;
  background: var(--bg-panel);
  border: 1px solid var(--line-bright);
  border-radius: 8px;
  box-shadow: 0 10px 28px rgba(0, 0, 0, 0.45);
}

.ctx-menu button {
  background: transparent;
  border: none;
  color: var(--text);
  text-align: left;
  padding: 7px 10px;
  border-radius: 5px;
  font-size: 12.5px;
  cursor: pointer;
}

.ctx-menu button:hover:not(:disabled) {
  background: color-mix(in srgb, var(--cyan) 9%, transparent);
  color: var(--cyan);
}

.ctx-menu button:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

.row-del,
.col-del {
  flex: none;
  position: absolute;
  top: 3px;
  right: 5px;
  z-index: 4;
  background: transparent;
  border: none;
  color: var(--text-dim);
  cursor: pointer;
  font-size: 10px;
  padding: 0 2px;
  opacity: 0;
  transition: opacity var(--dur-fast), color var(--dur-fast);
}

.row-src {
  position: absolute;
  top: 3px;
  right: 20px;
  z-index: 4;
  background: transparent;
  border: none;
  color: var(--cyan);
  cursor: pointer;
  font-size: 10px;
  padding: 0 2px;
  opacity: 0;
  transition: opacity var(--dur-fast);
}

.row-no:hover .row-src {
  opacity: 1;
}

.row-src:hover {
  text-shadow: var(--glow-cyan);
}

.row-no:hover .row-del,
.grid th:hover .col-del {
  opacity: 1;
}

.row-del:hover,
.col-del:hover {
  color: #ff8a8a;
}

.cell {
  width: 100%;
  min-width: 100px;
  padding: 6px 7px;
  border: none;
  border-radius: 0;
  background: transparent;
  font-size: 12.5px;
}

.cell:focus {
  background: color-mix(in srgb, var(--cyan) 6%, transparent);
}

.computed-value {
  display: block;
  padding: 6px 7px;
  min-width: 100px;
  color: #ffd166;
  font-family: var(--font-tech);
  font-size: 12.5px;
}

.cell-error {
  background: rgba(255, 107, 107, 0.12);
  box-shadow: inset 0 0 0 1px rgba(255, 107, 107, 0.5);
}

.editor-foot {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 10px;
  flex-wrap: wrap;
}

.hint {
  color: var(--text-dim);
  font-size: 10.5px;
}

.formulas,
.errors {
  margin-top: 14px;
}

.formulas-head {
  display: flex;
  align-items: center;
  gap: 10px;
}

.formulas-head .mini {
  margin-left: auto;
}

.formula-row {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 6px;
}

.f-col {
  width: 150px;
  flex-shrink: 0;
  color: var(--text);
  font-size: 12px;
}

.f-input {
  flex: 1;
  padding: 6px 9px;
  font-family: var(--font-tech);
  font-size: 12.5px;
}

.error-line {
  color: #ff8a8a;
  font-size: 11.5px;
  margin: 3px 0;
}

.empty-editor {
  flex: 1;
  display: grid;
  place-items: center;
  color: var(--text-dim);
  font-size: 13px;
}

@media (max-width: 760px) {
  .side {
    width: 150px;
  }
  .head-right {
    flex-wrap: wrap;
  }
}
</style>
