/**
 * 知识图谱服务:GET /api/graph(节点、依赖边、章节与个人掌握度)。
 */
import { get, post } from '@/api/http'
import { getToken } from '@/stores/user'

export type MasteryStatus = 'mastered' | 'weak' | 'new'

export interface GraphNode {
  id: string
  name: string
  chapter: string
  difficulty: number
  descendantCount: number
  prerequisites: string[]
  mastery: number | null
  status: MasteryStatus
}

export interface GraphEdge {
  source: string
  target: string
}

export interface GraphData {
  nodes: GraphNode[]
  edges: GraphEdge[]
  chapters: string[]
}

export type RecommendStrategy = 'difficulty' | 'coreness'

export interface RecommendationItem {
  pointId: string
  name: string
  chapter: string
  difficulty: number
  descendantCount: number
  reason: 'new' | 'review'
  mastery: number | null
  prerequisites: string[]
}

export interface Recommendation {
  strategy: RecommendStrategy
  mastered: number
  items: RecommendationItem[]
}

export interface DiagnosisResult {
  ok: boolean
  pointId: string
  score: number
  comment: string
  source: 'llm' | 'self'
  at: string
}

function authHeaders(): Record<string, string> {
  const token = getToken()
  return token ? { Authorization: `Bearer ${token}` } : {}
}

export function fetchGraph(): Promise<GraphData> {
  return get<GraphData>('/api/graph', authHeaders())
}

export function fetchRecommendation(
  strategy: RecommendStrategy = 'difficulty',
  limit = 5,
): Promise<Recommendation> {
  return get<Recommendation>(
    `/api/recommendation?strategy=${strategy}&limit=${limit}`,
    authHeaders(),
  )
}

export function submitSelfRating(pointId: string, selfRating: number): Promise<DiagnosisResult> {
  return post<DiagnosisResult>('/api/diagnosis', { pointId, selfRating }, authHeaders())
}
