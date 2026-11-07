/** 图解服务:手动“图解此段”与理解型兜底共用。 */
import { post } from '@/api/http'
import { getToken } from '@/stores/user'
import { parseDiagramSpec, type DiagramSpec } from '@/utils/diagramSpec'
import { diagramSuppressed, needsDiagram } from '@/utils/diagramIntent'

export { diagramSuppressed, needsDiagram }

export interface PlanDiagramInput {
  question: string
  answer: string
  paperId?: string
  tableId?: string
  mode?: 'learn' | 'research'
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
      tableId: input.tableId || undefined,
      mode: input.mode,
      kind: input.kind || undefined,
    },
    authHeaders(),
  )
  return parseDiagramSpec(res.diagram)
}
