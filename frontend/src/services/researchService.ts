/**
 * 科研语料库接口:论文上传、列表、删除、全文检索与章节树。
 * 上传为原始字节 + ?name=,服务端按内容哈希去重并按用户隔离存储。
 */
import { del, get, post, upload } from '@/api/http'
import { getToken } from '@/stores/user'

export interface ResearchDoc {
  id: string
  name: string
  size: number
  pages: number
  createdAt: number
  projectId: string | null
  doi?: string
  title?: string
  authors?: string
  year?: number
  venue?: string
}

export type ResearchStatus = 'exploring' | 'active' | 'paused' | 'done'

export interface ResearchProject {
  id: string
  title: string
  goal: string
  approach: string
  notes: string
  status: ResearchStatus
  createdAt: number
  updatedAt: number
}

export interface ResearchHit {
  docId: string
  docName: string
  nodeId: string
  section: string
  pageStart: number
  pageEnd: number
  snippet: string
  score: number
}

export interface ResearchSearchResult {
  hits: ResearchHit[]
  total: number
  query: string
  mode: 'bm25' | 'hybrid'
  tree: boolean
  elapsed: number
}

export interface ResearchNode {
  id: string
  parentId: string | null
  title: string
  summary: string
  pageStart: number
  pageEnd: number
}

function authHeaders(): Record<string, string> {
  const token = getToken()
  return token ? { Authorization: `Bearer ${token}` } : {}
}

export async function listResearchDocs(): Promise<ResearchDoc[]> {
  const res = await get<{ docs: ResearchDoc[] }>('/api/research/docs', authHeaders())
  return res.docs
}

export async function uploadResearchDoc(
  file: File,
  projectId?: string,
): Promise<{
  docId: string
  duplicate: boolean
  pages?: number
  sections?: number
  chunks?: number
}> {
  const type = file.type || (file.name.toLowerCase().endsWith('.pdf')
    ? 'application/pdf'
    : 'text/plain')
  const pid = projectId ? `&projectId=${encodeURIComponent(projectId)}` : ''
  return upload(
    `/api/research/docs?name=${encodeURIComponent(file.name)}${pid}`,
    file,
    type,
    authHeaders(),
  )
}

export async function deleteResearchDoc(docId: string): Promise<void> {
  await del(`/api/research/docs/${encodeURIComponent(docId)}`, authHeaders())
}

/** 清空我的论文库(服务端语料与索引) */
export async function clearResearchDocs(): Promise<number> {
  const res = await del<{ ok: boolean; removed: number }>('/api/research/docs', authHeaders())
  return res.removed
}

export async function searchResearch(
  query: string,
  options: {
    topK?: number
    docId?: string
    docIds?: string[]
    projectId?: string
    tree?: boolean
  } = {},
): Promise<ResearchSearchResult> {
  return post<ResearchSearchResult>('/api/research/search', {
    query,
    topK: options.topK ?? 8,
    docId: options.docId,
    docIds: options.docIds,
    projectId: options.projectId,
    tree: options.tree ?? true,
  }, authHeaders())
}

export interface PaperPassage {
  page: number
  pageEnd: number
  quote: string
  section: string
}

/** 当前论文内定位相关段落,供阅读器高亮 */
export async function locatePaperPassages(
  docId: string,
  query: string,
): Promise<{ passages: PaperPassage[] }> {
  return post<{ passages: PaperPassage[] }>(
    `/api/research/papers/${encodeURIComponent(docId)}/locate`,
    { query }, authHeaders())
}

/** 截图解释图表/公式区域:只依据图片,数值以原文为准 */
export async function explainRegion(
  docId: string,
  image: { mime: string; data: string },
  question = '',
): Promise<{ answer: string }> {
  return post<{ answer: string }>(
    `/api/research/papers/${encodeURIComponent(docId)}/explain-region`,
    { image, question }, authHeaders())
}

export interface ExtractedPaperTable {
  title: string
  columns: string[]
  rows: string[][]
  notes: string
  warnings: string[]
}

/** 论文表格截图 → 结构化表格预览(存入数据表由用户确认) */
export async function extractPaperTable(
  docId: string,
  image: { mime: string; data: string },
  page: number,
): Promise<{
  table: ExtractedPaperTable
  docId: string
  docName: string
  page: number
}> {
  return post(
    `/api/research/papers/${encodeURIComponent(docId)}/extract-table`,
    { image, page }, authHeaders())
}

export async function listResearchProjects(): Promise<ResearchProject[]> {
  const res = await get<{ projects: ResearchProject[] }>(
    '/api/research/projects', authHeaders())
  return res.projects
}

export interface ComparedTable {
  title: string
  columns: { key: string; label: string; type: 'text' }[]
  rows: string[][]
  rowLabels: string[]
  rowSources: {
    docId: string
    docName: string
    page: number
    quote?: string
    kind?: 'paper'
  }[]
  warnings: string[]
}

/** 多文献对比:模型只做归纳,每行带回原文来源 */
export async function compareResearchDocs(docIds: string[]): Promise<ComparedTable> {
  return post<ComparedTable>(
    '/api/research/literature/compare', { docIds }, authHeaders())
}

/** 项目研究报告 DOCX(项目档案 + 数据表 + 统计 + 来源) */
export async function downloadResearchReport(
  projectId: string,
  tableIds?: string[],
): Promise<void> {
  const res = await fetch('/api/research/report', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...authHeaders() },
    credentials: 'include',
    body: JSON.stringify({ projectId, tableIds }),
  })
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  const blob = await res.blob()
  const disposition = res.headers.get('Content-Disposition') || ''
  const match = disposition.match(/filename\*=UTF-8''([^;]+)/)
  const filename = match ? decodeURIComponent(match[1]) : '研究报告.docx'
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  a.remove()
  URL.revokeObjectURL(url)
}

/** 仅在用户确认后导入旧版浏览器档案;原始记录留在本机。 */
export async function importLegacyResearchArchive(archive: unknown): Promise<{ duplicate: boolean; projects: number; files: number }> {
  return post('/api/research/legacy-import', archive, authHeaders())
}

export async function createResearchProject(title = ''): Promise<ResearchProject> {
  const res = await post<{ project: ResearchProject }>(
    '/api/research/projects', { title }, authHeaders())
  return res.project
}

export async function updateResearchProject(
  projectId: string,
  patch: Partial<Pick<ResearchProject, 'title' | 'goal' | 'approach' | 'notes' | 'status'>>,
): Promise<ResearchProject> {
  const res = await post<{ project: ResearchProject }>(
    `/api/research/projects/${encodeURIComponent(projectId)}`, patch, authHeaders())
  return res.project
}

export async function deleteResearchProject(projectId: string): Promise<void> {
  await del(`/api/research/projects/${encodeURIComponent(projectId)}`, authHeaders())
}

export async function getResearchTree(docId: string): Promise<ResearchNode[]> {
  const res = await get<{ docId: string; nodes: ResearchNode[] }>(
    `/api/research/tree?docId=${encodeURIComponent(docId)}`,
    authHeaders(),
  )
  return res.nodes
}
