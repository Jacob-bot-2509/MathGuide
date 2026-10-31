/**
 * 科研实验数据表接口:模板导入、读写、公式计算、导出。
 * 计算在服务端完成(Decimal + 白名单 AST),前端只负责录入与展示。
 */
import { del, get, post, upload } from '@/api/http'
import { getToken } from '@/stores/user'

export type TableColumnType = 'number' | 'text' | 'computed'
export type TableColumnRole =
  | 'measured' | 'calculated' | 'identifier' | 'unit' | 'note'

export interface TableColumn {
  key: string
  label: string
  type: TableColumnType
  role?: TableColumnRole
  unit?: string
}

export interface TableMerge {
  r1: number
  c1: number
  r2: number
  c2: number
}

/** 数据表来源:论文表格转录后保留原文位置,便于复核 */
export interface TableSource {
  docId: string
  docName: string
  page: number
  quote?: string
  kind?: 'paper'
}

export interface ResearchTable {
  id: string
  projectId?: string | null
  title: string
  columns: TableColumn[]
  rows: string[][]
  formulas: Record<string, string>
  rowLabels: string[]
  merges: TableMerge[]
  colWidths: number[]
  rowHeights: number[]
  source?: TableSource | null
  rowSources?: (TableSource | null)[]
  createdAt?: number
  updatedAt?: number
}

export interface TableSummary {
  id: string
  projectId: string | null
  title: string
  columns: number
  rows: number
  updatedAt: number
}

export interface TableError {
  col: string
  row: number
  error: string
}

export interface TableComputeResult {
  table: ResearchTable
  computed: Record<string, string[]>
  errors: TableError[]
  columns?: TableColumn[]
}

export interface TablePayload {
  title?: string
  columns: TableColumn[]
  rows: string[][]
  formulas: Record<string, string>
  rowLabels: string[]
  merges: TableMerge[]
  colWidths: number[]
  rowHeights: number[]
  projectId?: string | null
  source?: TableSource | null
  rowSources?: (TableSource | null)[]
}

export interface TableStat {
  key: string
  label: string
  n: number
  missing: number
  mean: string
  median: string
  stdev: string
  min: string
  max: string
  q1: string
  q3: string
}

export interface TableCorrelation {
  x: string
  y: string
  r: string
}

export interface TableSeries {
  key: string
  label: string
  values: (number | null)[]
}

export interface TableStatsResult {
  stats: TableStat[]
  correlations: TableCorrelation[]
  series: TableSeries[]
  labels: string[]
  rowLabels: string[]
  computed: Record<string, string[]>
  errors: TableError[]
  columns?: TableColumn[]
}

export interface ExtractedFormula {
  id: string
  target: string
  expr: string
  variables: string[]
  variableMap: Record<string, string>
  units?: Record<string, string>
  handwriting?: boolean | null
  confidence?: number
  note?: string
}

export interface FormulaExtractResult {
  formulas: ExtractedFormula[]
  groups: string[][]
  master: string | null
  warnings: string[]
}

export interface PageBlock {
  kind: 'printed_text' | 'printed_formula' | 'printed_table' | 'handwriting' | 'figure'
  text: string
  latex: string
  confidence: number
}

export async function analyzeResearchPage(
  images: { mime: string; data: string }[],
  text = '',
  meta: { docId?: string; page?: number } = {},
): Promise<{ blocks: PageBlock[]; warnings: string[]; saved: number }> {
  return post(
    '/api/research/pages/analyze',
    { images, text, ...meta },
    authHeaders(),
  )
}

export interface FormulaCandidate {
  formulaId: string
  handwriting?: boolean | null
  target: string
  expr: string
  formula: string
  mapping: Record<string, string>
  units?: Record<string, string>
  unitConflicts?: { variable: string; expected: string; actual: string }[]
  columnKey: string
  score: number
  validation: {
    matched: number
    compared: number
    maxError: string
    samples?: { row: number; actual: string; predicted: string; ok: boolean }[]
  } | null
}

export async function matchTableFormulas(
  tableId: string,
  docId?: string,
): Promise<FormulaCandidate[]> {
  const res = await post<{ candidates: FormulaCandidate[] }>(
    `/api/research/tables/${encodeURIComponent(tableId)}/match-formulas`,
    { docId }, authHeaders())
  return res.candidates
}

export interface TopicSuggestion {
  title: string
  confidence: number
}

export async function suggestTableTopic(tableId: string): Promise<TopicSuggestion> {
  return post<TopicSuggestion>(
    `/api/research/tables/${encodeURIComponent(tableId)}/suggest-topic`,
    {},
    authHeaders(),
  )
}

export interface FormulaValidation {
  columnKey: string
  matched: number
  compared: number
  maxError: string
  samples: { row: number; actual: string; predicted: string; ok: boolean }[]
  errors: TableError[]
}

export async function validateTableFormula(
  tableId: string,
  columnKey: string,
  formula: string,
): Promise<FormulaValidation> {
  return post<FormulaValidation>(
    `/api/research/tables/${encodeURIComponent(tableId)}/validate-formula`,
    { columnKey, formula },
    authHeaders(),
  )
}

export interface SavedFormula {
  id: string
  target: string
  expr: string
  variables: string[]
  variableMap: Record<string, string>
  units?: Record<string, string>
  handwriting?: boolean | null
  createdAt: number
}

export async function listSavedFormulas(
  tableId?: string,
  docId?: string,
): Promise<SavedFormula[]> {
  const params = new URLSearchParams()
  if (tableId) params.set('tableId', tableId)
  if (docId) params.set('docId', docId)
  if (!params.size) return []
  const res = await get<{ formulas: SavedFormula[] }>(
    `/api/research/formulas?${params.toString()}`, authHeaders())
  return res.formulas
}

/** 图片公式识别:图片只以 base64 发送,服务端不落盘 */
export async function extractFormulas(
  images: { mime: string; data: string }[],
  columns: TableColumn[],
  text = '',
  meta: { docId?: string; tableId?: string; page?: number } = {},
): Promise<FormulaExtractResult> {
  return post<FormulaExtractResult>(
    '/api/research/formulas/extract',
    { images, columns, text, ...meta },
    authHeaders(),
  )
}

function authHeaders(): Record<string, string> {
  const token = getToken()
  return token ? { Authorization: `Bearer ${token}` } : {}
}

export async function listResearchTables(projectId?: string): Promise<TableSummary[]> {
  const q = projectId ? `?projectId=${encodeURIComponent(projectId)}` : ''
  const res = await get<{ tables: TableSummary[] }>(
    `/api/research/tables${q}`, authHeaders())
  return res.tables
}

export async function getResearchTable(tableId: string): Promise<ResearchTable> {
  const res = await get<{ table: ResearchTable }>(
    `/api/research/tables/${encodeURIComponent(tableId)}`, authHeaders())
  return res.table
}

export async function createResearchTable(payload: TablePayload): Promise<ResearchTable> {
  const res = await post<{ table: ResearchTable }>(
    '/api/research/tables', payload, authHeaders())
  return res.table
}

export async function saveResearchTable(
  tableId: string,
  payload: TablePayload,
): Promise<ResearchTable> {
  const res = await post<{ table: ResearchTable }>(
    `/api/research/tables/${encodeURIComponent(tableId)}`, payload, authHeaders())
  return res.table
}

export async function computeResearchTable(
  tableId: string,
  payload: TablePayload,
): Promise<TableComputeResult> {
  return post<TableComputeResult>(
    `/api/research/tables/${encodeURIComponent(tableId)}/compute`, payload, authHeaders())
}

export interface TablePrintResult {
  ok: boolean
  opened: boolean
  file: string
}

/** 描述性统计 + 相关性 + 绘图序列;不落库 */
export async function statsResearchTable(
  tableId: string,
  payload: TablePayload,
): Promise<TableStatsResult> {
  return post<TableStatsResult>(
    `/api/research/tables/${encodeURIComponent(tableId)}/stats`, payload, authHeaders())
}

/** 保存草稿并让本机 WPS/Excel 打开,打印选项沿用该程序 */
export async function printResearchTable(
  tableId: string,
  payload: TablePayload,
): Promise<TablePrintResult> {
  return post<TablePrintResult>(
    `/api/research/tables/${encodeURIComponent(tableId)}/print`, payload, authHeaders())
}

export async function deleteResearchTable(
  tableId: string,
  hard = false,
): Promise<void> {
  const query = hard ? '?hard=1' : ''
  await del(`/api/research/tables/${encodeURIComponent(tableId)}${query}`, authHeaders())
}

export async function importResearchTable(
  file: File,
  projectId?: string,
): Promise<ResearchTable> {
  const pid = projectId ? `&projectId=${encodeURIComponent(projectId)}` : ''
  const res = await upload<{ table: ResearchTable }>(
    `/api/research/tables/import?name=${encodeURIComponent(file.name)}${pid}`,
    file,
    file.type || 'application/octet-stream',
    authHeaders(),
  )
  return res.table
}

/** 下载导出文件(需要 Bearer 头,不能直接用 <a href>) */
export async function downloadResearchTable(
  tableId: string,
  format: 'csv' | 'xlsx',
  title: string,
): Promise<void> {
  const res = await fetch(
    `/api/research/tables/${encodeURIComponent(tableId)}/export?format=${format}`,
    { headers: authHeaders(), credentials: 'include' },
  )
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  const blob = await res.blob()
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `${title || 'table'}.${format}`
  document.body.appendChild(a)
  a.click()
  a.remove()
  URL.revokeObjectURL(url)
}
