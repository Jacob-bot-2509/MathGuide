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
  options: { topK?: number; docId?: string; projectId?: string; tree?: boolean } = {},
): Promise<ResearchSearchResult> {
  return post<ResearchSearchResult>('/api/research/search', {
    query,
    topK: options.topK ?? 8,
    docId: options.docId,
    projectId: options.projectId,
    tree: options.tree ?? true,
  }, authHeaders())
}

export async function listResearchProjects(): Promise<ResearchProject[]> {
  const res = await get<{ projects: ResearchProject[] }>(
    '/api/research/projects', authHeaders())
  return res.projects
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
