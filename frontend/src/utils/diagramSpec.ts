/** 图解协议:后端只送结构化数据,前端只接受白名单字段与边界值。 */

export type DiagramType =
  | 'tree'
  | 'relation'
  | 'flow'
  | 'geometry2d'
  | 'plot2d'
  | 'geometry3d'
  | 'surface3d'

export interface DiagramNode {
  id: string
  label: string
  kind?: string
  page?: number
}

export interface DiagramEdge {
  from: string
  to: string
  label?: string
  kind?: string
}

export interface DiagramShape {
  kind: string
  [key: string]: unknown
}

export interface DiagramAnnotation {
  x: number
  y: number
  text: string
}

export interface DiagramView {
  x: number
  y: number
  zoom: number
}

export interface DiagramSpec {
  type: DiagramType
  title?: string
  nodes: DiagramNode[]
  edges: DiagramEdge[]
  shapes: DiagramShape[]
  annotations: DiagramAnnotation[]
  view?: DiagramView
}

export interface DiagramBlock {
  id: string
  anchorIndex: number
  spec: DiagramSpec
}

export type MessageBlock =
  | { kind: 'text'; text: string }
  | { kind: 'diagram'; diagram: DiagramBlock }

const TYPES = new Set<DiagramType>([
  'tree', 'relation', 'flow', 'geometry2d', 'plot2d', 'geometry3d', 'surface3d',
])
const MAX_NODES = 40
const MAX_EDGES = 80
const MAX_SHAPES = 100
const MAX_ANNOTATIONS = 40
const MAX_COORD = 1e4

function text(value: unknown, limit: number): string {
  return typeof value === 'string' ? value.trim().slice(0, limit) : ''
}

function number(value: unknown, fallback = 0): number | null {
  const parsed = Number(value)
  if (!Number.isFinite(parsed) || parsed < -MAX_COORD || parsed > MAX_COORD) {
    return null
  }
  return parsed
}

function point(value: unknown): number[] | null {
  if (!Array.isArray(value) || value.length < 2 || value.length > 3) return null
  const parsed = value.map((item) => number(item))
  return parsed.every((item) => item !== null) ? parsed as number[] : null
}

function sanitizeShape(raw: unknown): DiagramShape | null {
  if (!raw || typeof raw !== 'object') return null
  const item = raw as Record<string, unknown>
  const kind = text(item.kind, 40)
  if (!kind) return null
  const out: DiagramShape = { kind }
  for (const key of ['x', 'y', 'z', 'r', 'radius', 'width', 'height', 'label',
    'expr', 'domain', 'color', 'points']) {
    if (!(key in item)) continue
    const value = item[key]
    if (key === 'label' || key === 'expr' || key === 'color') {
      const cleaned = text(value, 200)
      if (cleaned) out[key] = cleaned
    } else if (key === 'points') {
      if (Array.isArray(value) && value.length <= 200) {
        const pts = value.map(point)
        if (pts.every((p) => p !== null)) out.points = pts
      }
    } else if (key === 'domain') {
      if (Array.isArray(value) && value.length === 2) {
        const parsed = value.map((n) => number(n))
        if (parsed.every((n) => n !== null)) out.domain = parsed
      }
    } else {
      const parsed = number(value)
      if (parsed === null) return null
      out[key] = parsed
    }
  }
  for (const key of ['from', 'to']) {
    if (key in item) {
      const parsed = point(item[key])
      if (!parsed) return null
      out[key] = parsed
    }
  }
  return out
}

export function parseDiagramSpec(raw: unknown): DiagramSpec | null {
  if (!raw || typeof raw !== 'object') return null
  const item = raw as Record<string, unknown>
  const type = text(item.type, 40) as DiagramType
  if (!TYPES.has(type)) return null

  const nodes: DiagramNode[] = []
  const nodeIds = new Set<string>()
  if (Array.isArray(item.nodes)) {
    for (const entry of item.nodes.slice(0, MAX_NODES + 1)) {
      if (!entry || typeof entry !== 'object') continue
      const node = entry as Record<string, unknown>
      const id = text(node.id, 64)
      const label = text(node.label, 200)
      if (!id || !label || nodeIds.has(id)) continue
      nodeIds.add(id)
      const out: DiagramNode = { id, label }
      const kind = text(node.kind, 40)
      if (kind) out.kind = kind
      const page = Number(node.page)
      if (Number.isInteger(page) && page > 0) out.page = page
      nodes.push(out)
    }
    if (nodes.length > MAX_NODES) return null
  }

  const edges: DiagramEdge[] = []
  if (Array.isArray(item.edges)) {
    for (const entry of item.edges.slice(0, MAX_EDGES + 1)) {
      if (!entry || typeof entry !== 'object') continue
      const edge = entry as Record<string, unknown>
      const from = text(edge.from, 64)
      const to = text(edge.to, 64)
      if (!from || !to) continue
      if (nodeIds.size && (!nodeIds.has(from) || !nodeIds.has(to))) continue
      const out: DiagramEdge = { from, to }
      const label = text(edge.label, 200)
      if (label) out.label = label
      const kind = text(edge.kind, 40)
      if (kind) out.kind = kind
      edges.push(out)
    }
    if (edges.length > MAX_EDGES) return null
  }

  const shapes: DiagramShape[] = []
  if (Array.isArray(item.shapes)) {
    for (const entry of item.shapes.slice(0, MAX_SHAPES + 1)) {
      const shape = sanitizeShape(entry)
      if (shape) shapes.push(shape)
    }
    if (shapes.length > MAX_SHAPES) return null
    if (item.shapes.length > 0 && shapes.length !== Math.min(item.shapes.length, MAX_SHAPES)) {
      return null
    }
  }

  const annotations: DiagramAnnotation[] = []
  if (Array.isArray(item.annotations)) {
    for (const entry of item.annotations.slice(0, MAX_ANNOTATIONS + 1)) {
      if (!entry || typeof entry !== 'object') continue
      const note = entry as Record<string, unknown>
      const x = number(note.x)
      const y = number(note.y)
      const body = text(note.text, 400)
      if (x === null || y === null || !body) continue
      annotations.push({ x, y, text: body })
    }
    if (annotations.length > MAX_ANNOTATIONS) return null
  }

  if (!nodes.length && !shapes.length && !annotations.length) return null

  const spec: DiagramSpec = { type, nodes, edges, shapes, annotations }
  const title = text(item.title, 200)
  if (title) spec.title = title
  if (item.view && typeof item.view === 'object') {
    const view = item.view as Record<string, unknown>
    const x = number(view.x)
    const y = number(view.y)
    const zoom = number(view.zoom)
    if (x !== null && y !== null && zoom !== null && zoom > 0) {
      spec.view = { x, y, zoom: Math.min(8, Math.max(0.1, zoom)) }
    }
  }
  return spec
}

export function parseDiagramEvent(payload: unknown): DiagramBlock | null {
  if (!payload || typeof payload !== 'object') return null
  const frame = payload as Record<string, unknown>
  if (frame.mg_event !== 'diagram') return null
  const id = text(frame.anchorId, 80)
  const anchor = Number(frame.anchorIndex)
  const spec = parseDiagramSpec(frame.diagram)
  if (!id || !spec || !Number.isInteger(anchor) || anchor < 0) return null
  return { id, anchorIndex: anchor, spec }
}

export function splitMessageBlocks(
  content: string,
  diagrams: DiagramBlock[] | undefined,
): MessageBlock[] {
  const blocks: MessageBlock[] = []
  const sorted = [...(diagrams || [])]
    .filter((item) => item && item.spec)
    .sort((a, b) => a.anchorIndex - b.anchorIndex)
  let cursor = 0
  for (const diagram of sorted) {
    const at = Math.max(cursor, Math.min(content.length, Math.trunc(diagram.anchorIndex)))
    if (at > cursor) {
      blocks.push({ kind: 'text', text: content.slice(cursor, at) })
      cursor = at
    }
    blocks.push({ kind: 'diagram', diagram })
  }
  if (cursor < content.length) {
    blocks.push({ kind: 'text', text: content.slice(cursor) })
  }
  if (!blocks.length) blocks.push({ kind: 'text', text: content })
  return blocks
}
