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
  z?: number
  text: string
}

export interface DiagramView {
  x: number
  y: number
  zoom: number
}

export interface DiagramSpec {
  schemaVersion?: number
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
const MAX_POINTS = 2000
const MAX_DIAGRAMS = 6
const MAX_TOTAL_POINTS = 8000
const MAX_COORD = 1e4
const DIAGRAM_SCHEMA_VERSION = 1

function text(value: unknown, limit: number): string {
  return typeof value === 'string' ? value.trim().slice(0, limit) : ''
}

function number(value: unknown): number | null {
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
  for (const key of ['x', 'y', 'z', 'r', 'radius', 'width', 'height', 'depth', 'label',
    'expr', 'domain', 'color', 'points', 'rows', 'cols']) {
    if (!(key in item)) continue
    const value = item[key]
    if (key === 'label' || key === 'expr' || key === 'color') {
      const cleaned = text(value, 200)
      if (key === 'label' && cleaned.toLowerCase() === 'djj') continue
      if (cleaned) out[key] = cleaned
    } else if (key === 'points') {
      if (Array.isArray(value)) {
        const pts = value.slice(0, MAX_POINTS)
          .map(point)
          .filter((p): p is number[] => p !== null)
        if (pts.length) out.points = pts
      }
    } else if (key === 'domain') {
      if (Array.isArray(value) && value.length >= 2 && value.length <= 4) {
        const parsed = value.map((n) => number(n))
        if (parsed.every((n) => n !== null)) out.domain = parsed
      }
    } else if (key === 'rows' || key === 'cols') {
      const parsed = number(value)
      if (parsed !== null && Number.isInteger(parsed)) {
        out[key] = Math.max(2, Math.min(41, parsed))
      }
    } else {
      const parsed = number(value)
      if (parsed !== null) out[key] = parsed
    }
  }
  for (const key of ['from', 'to', 'normal']) {
    if (key in item) {
      const parsed = point(item[key])
      if (parsed) out[key] = parsed
    }
  }
  if (['segment', 'line', 'vector', 'axis'].includes(kind)
    && (!Array.isArray(out.from) || !Array.isArray(out.to))) {
    return null
  }
  if (kind === 'point' && (typeof out.x !== 'number' || typeof out.y !== 'number')) {
    return null
  }
  if ((kind === 'surface' || kind === 'polygon') && !Array.isArray(out.points)) {
    return null
  }
  return out
}

function renderableShape(shape: DiagramShape): boolean {
  if (shape.kind === 'axis') return false
  if (['curve', 'polygon', 'surface'].includes(shape.kind)) {
    return Array.isArray(shape.points) && shape.points.length > 0
  }
  if (shape.kind === 'point' || shape.kind === 'circle') {
    return typeof shape.x === 'number' && typeof shape.y === 'number'
  }
  if (['segment', 'line', 'vector'].includes(shape.kind)) {
    return Array.isArray(shape.from) && Array.isArray(shape.to)
  }
  return true
}

export function parseDiagramSpec(raw: unknown): DiagramSpec | null {
  if (!raw || typeof raw !== 'object') return null
  const item = raw as Record<string, unknown>
  const type = text(item.type, 40) as DiagramType
  if (!TYPES.has(type)) return null
  const version = Number(item.schemaVersion)
  if (Number.isFinite(version) && version > DIAGRAM_SCHEMA_VERSION) return null

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
      const out: DiagramAnnotation = { x, y, text: body }
      const z = number(note.z)
      if (z !== null) out.z = z
      annotations.push(out)
    }
    if (annotations.length > MAX_ANNOTATIONS) return null
  }

  if (!nodes.length && !shapes.length && !annotations.length) return null
  // 类型与结构必须自洽,避免把关系图数据塞进三维画布渲染成空白。
  if (type === 'tree' || type === 'relation' || type === 'flow') {
    if (!nodes.length) return null
  } else if (!shapes.length || !shapes.some(renderableShape)) {
    return null
  }

  const spec: DiagramSpec = {
    schemaVersion: DIAGRAM_SCHEMA_VERSION,
    type, nodes, edges, shapes, annotations,
  }
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

function specPoints(spec: DiagramSpec): number {
  return spec.shapes.reduce((sum, shape) => (
    sum + (Array.isArray(shape.points) ? shape.points.length : 0)
  ), 0)
}

export function appendDiagram(
  existing: DiagramBlock[] | undefined,
  incoming: DiagramBlock,
): DiagramBlock[] {
  const current = existing || []
  if (current.some((item) => item.id === incoming.id)) return current
  if (current.length >= MAX_DIAGRAMS) return current
  const points = current.reduce((sum, item) => sum + specPoints(item.spec), 0)
  if (points + specPoints(incoming.spec) > MAX_TOTAL_POINTS) return current
  return [...current, incoming]
}

/** 树/关系图折叠:隐藏被折叠节点的全部后代,保留节点本身。 */
export function filterCollapsed(
  spec: DiagramSpec,
  collapsed: Set<string>,
): DiagramSpec {
  if (!collapsed.size || (spec.type !== 'tree' && spec.type !== 'relation')) {
    return spec
  }
  const children = new Map<string, string[]>()
  for (const node of spec.nodes) children.set(node.id, [])
  for (const edge of spec.edges) {
    children.get(edge.from)?.push(edge.to)
  }
  const hidden = new Set<string>()
  const hide = (id: string): void => {
    for (const child of children.get(id) || []) {
      if (hidden.has(child)) continue
      hidden.add(child)
      hide(child)
    }
  }
  for (const id of collapsed) hide(id)
  return {
    ...spec,
    nodes: spec.nodes.filter((node) => !hidden.has(node.id)),
    edges: spec.edges.filter((edge) => !hidden.has(edge.from) && !hidden.has(edge.to)),
  }
}

export interface PaperOutlineLike {
  title: string
  children?: PaperOutlineLike[]
  pageStart?: number
}

export interface PaperStructureLike {
  question: string
  methods: string[]
  conclusions: string[]
  limitations: string[]
  outline: PaperOutlineLike[]
}

/** 论文脑图只读缓存结构,不调用模型。 */
export function buildPaperDiagram(
  structure: PaperStructureLike,
  title = '论文',
): DiagramSpec {
  const nodes: DiagramNode[] = []
  const edges: DiagramEdge[] = []
  let nextId = 0
  const add = (label: string, kind: string, page?: number): string | null => {
    if (nodes.length >= MAX_NODES) return null
    const clean = label.trim().slice(0, 200)
    if (!clean) return null
    const id = `p${nextId++}`
    const node: DiagramNode = { id, label: clean, kind }
    if (page && page > 0) node.page = page
    nodes.push(node)
    return id
  }
  const link = (from: string | null, to: string | null): void => {
    if (from && to && edges.length < MAX_EDGES) edges.push({ from, to })
  }

  const root = add(title, 'root')!
  const question = structure.question.trim()
  if (question) {
    const section = add('研究问题', 'section')
    link(root, section)
    link(section, add(question, 'item'))
  }
  const groups: Array<[string, string[]]> = [
    ['方法', structure.methods],
    ['结论', structure.conclusions],
    ['局限', structure.limitations],
  ]
  for (const [label, items] of groups) {
    if (!items.length) continue
    const section = add(label, 'section')
    link(root, section)
    for (const item of items.slice(0, 6)) link(section, add(item, 'item'))
  }
  if (structure.outline.length) {
    const section = add('章节', 'section')
    link(root, section)
    const walk = (items: PaperOutlineLike[], parent: string | null, depth: number): void => {
      if (depth > 4) return
      for (const item of items) {
        const id = add(item.title, 'outline', item.pageStart)
        link(parent, id)
        if (id && item.children?.length) walk(item.children, id, depth + 1)
      }
    }
    walk(structure.outline, section, 0)
  }
  return { type: 'tree', nodes, edges, shapes: [], annotations: [] }
}
