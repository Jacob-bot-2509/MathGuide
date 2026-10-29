/**
 * 文档生成服务:问答导出 + 独立要求的大纲/分节生成。
 * 二进制导出统一走 docService.postBinary,401 处理与聊天/PDF 导出一致。
 */
import { post } from '@/api/http'
import { getToken } from '@/stores/user'
import { postBinary, type ExportResult } from '@/services/docService'
import type { ChatMsg } from '@/stores/sessions'

export type DocFormat = 'pdf' | 'md' | 'docx'

function authHeaders(): Record<string, string> {
  const token = getToken()
  return token ? { Authorization: `Bearer ${token}` } : {}
}

export interface DocQuestion {
  id: number
  question: string
  has_answer: boolean
}

export interface DocItem {
  question: string
  answer: string
  source?: string
}

export interface OutlineSection {
  heading: string
  points: string[]
  evidence_ids: string[]
  has_evidence: boolean
}

export interface DocOutline {
  title: string
  sections: OutlineSection[]
  gaps: string[]
  evidence: Array<{ id: string; title: string; section: string }>
}

export interface StructuredDocument {
  title: string
  abstract?: string
  keywords?: string[]
  sections: Array<{ heading: string; paragraphs: string[] }>
  references?: Array<{ id: number; title: string; source: string; url?: string }>
}

export interface GeneratedDocument {
  document: StructuredDocument
  gaps: string[]
}

export async function fetchDocQuestions(messages: ChatMsg[], lang: 'zh' | 'en'): Promise<DocQuestion[]> {
  const payload = messages.slice(-80).map((message) => ({
    role: message.role,
    content: message.content,
    cmd: message.cmd,
    chitchat: message.chitchat,
  }))
  const res = await post<{ items: DocQuestion[] }>('/api/doc/questions', { messages: payload, lang }, authHeaders())
  return res.items
}

export function exportQaDocument(
  items: DocItem[],
  lang: 'zh' | 'en',
  format: DocFormat,
  source: string,
): Promise<ExportResult> {
  return postBinary('/api/doc/qa', { items, lang, format, source })
}

export function requestOutline(request: string, lang: 'zh' | 'en'): Promise<DocOutline> {
  return post<DocOutline>('/api/doc/outline', { request, lang }, authHeaders())
}

export function generateDocument(
  request: string,
  outline: DocOutline,
  lang: 'zh' | 'en',
): Promise<GeneratedDocument> {
  return post<GeneratedDocument>('/api/doc/generate', { request, outline, lang }, authHeaders())
}

export function renderDocument(
  document: StructuredDocument,
  lang: 'zh' | 'en',
  format: DocFormat,
): Promise<ExportResult> {
  return postBinary('/api/doc/render', { document, lang, format })
}
