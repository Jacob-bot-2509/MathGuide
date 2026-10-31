/** 论文窗口动作协议:后端 SSE 事件 → 前端只接受白名单字段与边界值。 */
import type { PaperAction } from '@/services/researchService'

export interface PaperActionEvent {
  requestId: string
  docId: string
  actions: PaperAction[]
}

const TYPES = new Set([
  'highlight', 'annotate', 'updateAnnotation', 'deleteAnnotation',
])
const COLORS = new Set(['yellow', 'cyan', 'green', 'red'])
const MAX_ACTIONS = 16

function text(value: unknown, limit: number): string {
  return typeof value === 'string' ? value.trim().slice(0, limit) : ''
}

function page(value: unknown): number {
  const parsed = Math.trunc(Number(value))
  return Number.isFinite(parsed) && parsed > 0 ? parsed : 0
}

function normalize(raw: unknown): PaperAction | null {
  if (!raw || typeof raw !== 'object') return null
  const item = raw as Record<string, unknown>
  const type = text(item.type, 40)
  if (!TYPES.has(type)) return null
  if (type === 'deleteAnnotation') {
    const id = text(item.id, 64)
    return id ? { type, id } : null
  }
  if (type === 'updateAnnotation') {
    const id = text(item.id, 64)
    if (!id) return null
    const action: PaperAction = { type, id }
    const note = text(item.note, 4000)
    if (note) action.note = note
    const color = text(item.color, 20).toLowerCase()
    if (COLORS.has(color)) action.color = color
    return Object.keys(action).length > 2 ? action : null
  }
  const targetPage = page(item.page)
  const quote = text(item.quote, 2000)
  if (!targetPage || !quote) return null
  const action: PaperAction = {
    type: type as PaperAction['type'], page: targetPage, quote,
  }
  if (type === 'annotate') {
    const note = text(item.note, 4000)
    if (note) action.note = note
    const color = text(item.color, 20).toLowerCase()
    action.color = COLORS.has(color) ? color : 'yellow'
  }
  const query = text(item.query, 200)
  if (query) action.query = query
  return action
}

/** 解析新事件帧(mg_event)与旧 meta 帧(mg_meta.paperActions)。 */
export function parsePaperActionEvent(payload: unknown): PaperActionEvent | null {
  if (!payload || typeof payload !== 'object') return null
  const frame = payload as Record<string, unknown>
  let rawActions: unknown
  let requestId = ''
  let docId = ''
  if (frame.mg_event === 'paper_actions') {
    rawActions = frame.actions
    requestId = text(frame.requestId, 80)
    docId = text(frame.docId, 64)
  } else {
    const inner = frame.mg_meta
    if (!inner || typeof inner !== 'object') return null
    const meta = inner as Record<string, unknown>
    rawActions = meta.paperActions
    requestId = text(meta.paperRequestId, 80)
  }
  if (!Array.isArray(rawActions)) return null
  const actions: PaperAction[] = []
  const seen = new Set<string>()
  for (const raw of rawActions.slice(0, MAX_ACTIONS)) {
    const action = normalize(raw)
    if (!action) continue
    const key = paperActionFingerprint(action)
    if (seen.has(key)) continue
    seen.add(key)
    actions.push(action)
  }
  if (!actions.length) return null
  return { requestId: requestId || 'legacy', docId, actions }
}

/** 统一入口:解析动作帧、校验目标论文、交给调用方执行。
 *  已是纯函数,两个聊天界面共用同一套匹配规则,避免各写一份。 */
export function handlePaperActionMeta(
  payload: unknown,
  targetDocId: string,
  apply: (actions: PaperAction[], requestId: string) => void,
): boolean {
  const event = parsePaperActionEvent(payload)
  if (!event || !targetDocId) return false
  if (event.docId && event.docId !== targetDocId) return false
  apply(event.actions, event.requestId)
  return true
}

/** 同一请求重放时用于去重;批注更新按 id,高亮按页码+引文。 */
export function paperActionFingerprint(action: PaperAction): string {
  if (action.type === 'deleteAnnotation' || action.type === 'updateAnnotation') {
    return `${action.type}:${action.id || ''}`
  }
  return `${action.type}:${action.page || 0}:${(action.quote || '').slice(0, 80)}`
}
