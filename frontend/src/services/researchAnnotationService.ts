/** 论文批注:按文档存服务端;前端先本地草稿,关闭时统一保存。 */
import { del, get, post } from '@/api/http'
import { getToken } from '@/stores/user'

export interface Annotation {
  id: string
  docId: string
  page: number
  quote: string
  rects: number[][]
  note: string
  color: string
  createdAt?: number
  updatedAt?: number
}

export interface AnnotationInput {
  id?: string
  page: number
  quote: string
  rects: number[][]
  note?: string
  color?: string
}

function authHeaders(): Record<string, string> {
  const token = getToken()
  return token ? { Authorization: `Bearer ${token}` } : {}
}

export async function listAnnotations(docId: string): Promise<Annotation[]> {
  const res = await get<{ annotations: Annotation[] }>(
    `/api/research/docs/${encodeURIComponent(docId)}/annotations`, authHeaders())
  return res.annotations
}

export async function saveAnnotation(
  docId: string,
  input: AnnotationInput,
): Promise<Annotation> {
  const res = await post<{ annotation: Annotation }>(
    `/api/research/docs/${encodeURIComponent(docId)}/annotations`,
    input, authHeaders())
  return res.annotation
}

export async function deleteAnnotation(
  docId: string,
  annotationId: string,
): Promise<void> {
  await del(
    `/api/research/docs/${encodeURIComponent(docId)}/annotations/${encodeURIComponent(annotationId)}`,
    authHeaders())
}
