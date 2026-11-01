/** 图解服务:手动“图解此段”与理解型兜底共用。 */
import { post } from '@/api/http'
import { getToken } from '@/stores/user'
import { parseDiagramSpec, type DiagramSpec } from '@/utils/diagramSpec'

export interface PlanDiagramInput {
  question: string
  answer: string
  paperId?: string
  kind?: string
}

function authHeaders(): Record<string, string> {
  const token = getToken()
  return token ? { Authorization: `Bearer ${token}` } : {}
}

export async function planDiagram(input: PlanDiagramInput): Promise<DiagramSpec | null> {
  const res = await post<{ diagram: unknown }>(
    '/api/research/diagrams/plan',
    {
      question: input.question,
      answer: input.answer,
      paperId: input.paperId || undefined,
      kind: input.kind || undefined,
    },
    authHeaders(),
  )
  return parseDiagramSpec(res.diagram)
}

/** 用户明显在问“怎么理解/几何直观/关系/区别”时,允许回答结束后补一张图。 */
export function needsDiagram(question: string): boolean {
  return /怎么理解|如何理解|怎么直观|几何直观|直观理解|怎么想|有什么关系|什么关系|有什么区别|为什么会|推导|证明思路|how (?:can|do|to) .*understand|geometric intuition|intuition|relationship|difference/i
    .test(question || '')
}
