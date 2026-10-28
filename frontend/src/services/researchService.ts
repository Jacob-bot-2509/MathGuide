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

export async function uploadResearchDoc(file: File): Promise<{
  docId: string
  duplicate: boolean
  pages?: number
  sections?: number
  chunks?: number
}> {
  const type = file.type || (file.name.toLowerCase().endsWith('.pdf')
    ? 'application/pdf'
    : 'text/plain')
  return upload(
    `/api/research/docs?name=${encodeURIComponent(file.name)}`,
    file,
    type,
    authHeaders(),
  )
}

export async function deleteResearchDoc(docId: string): Promise<void> {
  await del(`/api/research/docs/${encodeURIComponent(docId)}`, authHeaders())
}

export async function searchResearch(
  query: string,
  options: { topK?: number; docId?: string; tree?: boolean } = {},
): Promise<ResearchSearchResult> {
  return post<ResearchSearchResult>('/api/research/search', {
    query,
    topK: options.topK ?? 8,
    docId: options.docId,
    tree: options.tree ?? true,
  }, authHeaders())
}

export async function getResearchTree(docId: string): Promise<ResearchNode[]> {
  const res = await get<{ docId: string; nodes: ResearchNode[] }>(
    `/api/research/tree?docId=${encodeURIComponent(docId)}`,
    authHeaders(),
  )
  return res.nodes
}
