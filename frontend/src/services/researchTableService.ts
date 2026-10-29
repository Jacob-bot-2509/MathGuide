/**
 * 科研实验数据表接口:模板导入、读写、公式计算、导出。
 * 计算在服务端完成(Decimal + 白名单 AST),前端只负责录入与展示。
 */
import { del, get, post, upload } from '@/api/http'
import { getToken } from '@/stores/user'

export type TableColumnType = 'number' | 'text' | 'computed'

export interface TableColumn {
  key: string
  label: string
  type: TableColumnType
}

export interface TableMerge {
  r1: number
  c1: number
  r2: number
  c2: number
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
}

export interface ExtractedFormula {
  id: string
  target: string
  expr: string
  variables: string[]
  variableMap: Record<string, string>
  note?: string
}

export interface FormulaExtractResult {
  formulas: ExtractedFormula[]
  groups: string[][]
  master: string | null
  warnings: string[]
}

/** 图片公式识别:图片只以 base64 发送,服务端不落盘 */
export async function extractFormulas(
  images: { mime: string; data: string }[],
  columns: TableColumn[],
): Promise<FormulaExtractResult> {
  return post<FormulaExtractResult>(
    '/api/research/formulas/extract',
    { images, columns },
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

/** 保存草稿并让本机 WPS/Excel 打开,打印选项沿用该程序 */
export async function printResearchTable(
  tableId: string,
  payload: TablePayload,
): Promise<TablePrintResult> {
  return post<TablePrintResult>(
    `/api/research/tables/${encodeURIComponent(tableId)}/print`, payload, authHeaders())
}

export async function deleteResearchTable(tableId: string): Promise<void> {
  await del(`/api/research/tables/${encodeURIComponent(tableId)}`, authHeaders())
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
