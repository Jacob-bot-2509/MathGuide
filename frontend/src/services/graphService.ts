/**
 * 知识图谱服务:GET /api/graph(节点、依赖边、章节与个人掌握度)。
 */
import { get, httpError, post } from '@/api/http'
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
  /** 后端 NetworkX 分层布局给出的像素坐标(旧后端可能缺省,前端会本地兜底) */
  x?: number
  y?: number
  level?: number
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

export interface AnalysisPoint {
  pointId: string
  name: string
  chapter: string
  difficulty: number
  score: number | null
  effectiveScore: number | null
  /** 艾宾浩斯记忆保持率 0~1;仅用于复习优先级 */
  retention?: number | null
  /** 记忆强度时间常数(天),由后端计算 */
  tauDays?: number | null
  descendantCount: number
  stale: boolean
  reason: 'review' | 'new' | 'stale'
  why?: {
    code: string
    mastery: number | null
    difficulty: number
    retention: number | null
    tauDays: number | null
    unlocks: number
  }
  at?: string
  days?: number
}

export interface AnalysisChapter {
  chapter: string
  total: number
  diagnosed: number
  mastered: number
  weak: number
  averageScore: number | null
  coverageRatio: number
}

export interface LearningAnalysis {
  generatedAt: string
  dataQuality: 'none' | 'sparse' | 'ok'
  limits: {
    reviewRetention: number
    tauBase: number
    tauStep: number
    minSample: number
  }
  coverage: {
    total: number
    diagnosed: number
    ratio: number
    frontierTotal: number
    frontierDiagnosed: number
    frontierRatio: number
  }
  structure: { mastered: number; weak: number; stale: number; undiagnosed: number }
  chapters: AnalysisChapter[]
  bottlenecks: AnalysisPoint[]
  stale: AnalysisPoint[]
  nextSteps: AnalysisPoint[]
  suggestedDiagnosis: AnalysisPoint[]
}

function authHeaders(): Record<string, string> {
  const token = getToken()
  return token ? { Authorization: `Bearer ${token}` } : {}
}

export function fetchGraph(): Promise<GraphData> {
  return get<GraphData>('/api/graph', authHeaders())
}

/** 学习分析快照:掌握度、覆盖度、瓶颈与下一步,全部由后端计算。 */
export function fetchLearningAnalysis(): Promise<LearningAnalysis> {
  return get<LearningAnalysis>('/api/profile/analysis', authHeaders())
}

/** 下载可独立打开的 Pyvis HTML 图谱(vis 资源内联)。 */
export async function exportGraphHtml(): Promise<Blob> {
  const res = await fetch('/api/graph/export', { headers: authHeaders() })
  if (!res.ok) throw httpError(res)
  return res.blob()
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
