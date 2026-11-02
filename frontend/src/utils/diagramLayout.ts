/** 图解布局:确定性坐标,不依赖 DOM,不做物理动画。 */
import type { DiagramSpec } from './diagramSpec'
import {
  placeLabels,
  type LabelRequest,
  type Rect,
} from './diagramLabels'

export interface PositionedNode {
  id: string
  x: number
  y: number
  w: number
  h: number
  label: string
}

export interface PositionedEdge {
  from: string
  to: string
  x1: number
  y1: number
  x2: number
  y2: number
  label?: string
  labelLines?: string[]
  labelX?: number
  labelY?: number
}

export interface LayoutResult {
  nodes: PositionedNode[]
  edges: PositionedEdge[]
  width: number
  height: number
}

const NODE_H = 34
const GAP_X = 22
const GAP_Y = 26
const MARGIN = 24

function charWidth(ch: string): number {
  return /[　-鿿＀-￯]/.test(ch) ? 11 : 6.5
}

function measuredWidth(label: string): number {
  let width = 0
  for (const ch of Array.from(label)) width += charWidth(ch)
  return width
}

function nodeWidth(label: string): number {
  return Math.min(280, Math.max(96, measuredWidth(label) + 28))
}

function empty(nodes: PositionedNode[], edges: PositionedEdge[]): LayoutResult {
  const width = Math.max(1, ...nodes.map((n) => n.x + n.w + MARGIN))
  const height = Math.max(1, ...nodes.map((n) => n.y + n.h + MARGIN))
  return { nodes, edges, width, height }
}

function finish(nodes: PositionedNode[], edges: PositionedEdge[]): LayoutResult {
  const base = empty(nodes, edges)
  return placeEdgeLabels(nodes, edges, base.width, base.height)
}

function connect(nodes: PositionedNode[], spec: DiagramSpec): PositionedEdge[] {
  const byId = new Map(nodes.map((node) => [node.id, node]))
  const out: PositionedEdge[] = []
  for (const edge of spec.edges) {
    const from = byId.get(edge.from)
    const to = byId.get(edge.to)
    if (!from || !to) continue
    let x1 = from.x + from.w / 2
    let y1 = from.y + from.h / 2
    let x2 = to.x + to.w / 2
    let y2 = to.y + to.h / 2
    const dx = x2 - x1
    const dy = y2 - y1
    const length = Math.hypot(dx, dy)
    if (length > 1) {
      // 线端收进节点边缘,箭头才不会被节点盖住。
      const ux = dx / length
      const uy = dy / length
      x1 += ux * (from.h / 2)
      y1 += uy * (from.h / 2)
      x2 -= ux * (to.h / 2)
      y2 -= uy * (to.h / 2)
    }
    out.push({
      from: edge.from, to: edge.to,
      x1, y1, x2, y2,
      label: edge.label,
    })
  }
  return out
}

function edgeObstacles(edges: PositionedEdge[]): Rect[] {
  const out: Rect[] = []
  for (const edge of edges) {
    const dx = edge.x2 - edge.x1
    const dy = edge.y2 - edge.y1
    const length = Math.hypot(dx, dy)
    const count = Math.max(1, Math.ceil(length / 16))
    for (let index = 0; index <= count; index += 1) {
      const t = index / count
      out.push({
        x: edge.x1 + dx * t - 2,
        y: edge.y1 + dy * t - 2,
        w: 4,
        h: 4,
      })
    }
  }
  return out
}

/** 节点图边标签:沿边分散,避开节点方框、其他边和已经放下的标签。 */
function placeEdgeLabels(
  nodes: PositionedNode[],
  edges: PositionedEdge[],
  width: number,
  height: number,
): LayoutResult {
  if (!edges.some((edge) => edge.label)) {
    return { nodes, edges, width, height }
  }
  const obstacles: Rect[] = nodes.map((node) => ({
    x: node.x - 3,
    y: node.y - 3,
    w: node.w + 6,
    h: node.h + 6,
  }))
  obstacles.push(...edgeObstacles(edges))
  const requests: LabelRequest[] = []
  edges.forEach((edge, index) => {
    if (!edge.label) return
    const horizontal = Math.abs(edge.x2 - edge.x1) >= Math.abs(edge.y2 - edge.y1)
    requests.push({
      id: `edge-${index}`,
      text: edge.label,
      anchorX: (edge.x1 + edge.x2) / 2,
      anchorY: (edge.y1 + edge.y2) / 2,
      role: 'edge',
      fontSize: 9,
      maxWidth: 110,
      maxLines: 2,
      priority: 1,
      preferred: horizontal
        ? ['top', 'bottom', 'left', 'right']
        : ['left', 'right', 'top', 'bottom'],
    })
  })
  const placed = placeLabels(requests, obstacles, { x: 0, y: 0, w: width, h: height })
  const byId = new Map(placed.map((label) => [label.id, label]))
  let finalWidth = width
  let finalHeight = height
  const nextEdges = edges.map((edge, index) => {
    const label = byId.get(`edge-${index}`)
    if (!label) return edge
    finalWidth = Math.max(finalWidth, label.x + label.w + 8)
    finalHeight = Math.max(finalHeight, label.y + label.h + 8)
    return {
      ...edge,
      labelLines: label.lines,
      labelX: label.x,
      labelY: label.y + label.fontSize,
    }
  })
  return { nodes, edges: nextEdges, width: finalWidth, height: finalHeight }
}

function childrenMap(spec: DiagramSpec): Map<string, string[]> {
  const out = new Map<string, string[]>()
  for (const node of spec.nodes) out.set(node.id, [])
  for (const edge of spec.edges) {
    const list = out.get(edge.from)
    if (list && out.has(edge.to) && !list.includes(edge.to)) list.push(edge.to)
  }
  return out
}

export function layoutTree(spec: DiagramSpec): LayoutResult {
  if (!spec.nodes.length) return empty([], [])
  const children = childrenMap(spec)
  const childIds = new Set([...children.values()].flat())
  const roots = spec.nodes.filter((node) => !childIds.has(node.id))
  const rootIds = (roots.length ? roots : [spec.nodes[0]]).map((node) => node.id)
  const labels = new Map(spec.nodes.map((node) => [node.id, node]))
  const positioned: PositionedNode[] = []
  const placed = new Map<string, number>()
  let cursor = 0
  let maxDepth = 0

  function place(id: string, depth: number, seen: Set<string>): number {
    const node = labels.get(id)
    if (!node || seen.has(id)) return cursor
    const existing = placed.get(id)
    if (existing !== undefined) return existing
    seen.add(id)
    maxDepth = Math.max(maxDepth, depth)
    const kids = children.get(id) || []
    const centers: number[] = []
    for (const kid of kids) centers.push(place(kid, depth + 1, new Set(seen)))
    let center: number
    if (centers.length) {
      center = (Math.min(...centers) + Math.max(...centers)) / 2
    } else {
      const w = nodeWidth(node.label)
      center = cursor + w / 2
      cursor += w + GAP_X
    }
    const w = nodeWidth(node.label)
    positioned.push({
      id, label: node.label, w, h: NODE_H,
      x: center - w / 2, y: MARGIN + depth * (NODE_H + GAP_Y),
    })
    placed.set(id, center)
    return center
  }

  for (const root of rootIds) place(root, 0, new Set())
  for (const node of spec.nodes) {
    if (!positioned.some((item) => item.id === node.id)) place(node.id, 0, new Set())
  }
  const minX = Math.min(...positioned.map((n) => n.x))
  const shift = MARGIN - minX
  for (const node of positioned) node.x += shift
  const sorted = [...positioned].sort((a, b) => a.y - b.y || a.x - b.x)
  return finish(sorted, connect(sorted, spec))
}

export function layoutRelation(spec: DiagramSpec): LayoutResult {
  const count = spec.nodes.length
  if (!count) return empty([], [])
  const maxWidth = Math.max(...spec.nodes.map((node) => nodeWidth(node.label)))
  const radius = Math.max(150, count * 46, maxWidth * 1.25)
  const center = radius + 80
  const positioned = spec.nodes.map((node, index) => {
    const angle = (Math.PI * 2 * index) / count - Math.PI / 2
    const w = nodeWidth(node.label)
    return {
      id: node.id, label: node.label, w, h: NODE_H,
      x: center + Math.cos(angle) * radius - w / 2,
      y: center + Math.sin(angle) * radius - NODE_H / 2,
    }
  })
  return finish(positioned, connect(positioned, spec))
}

export function layoutFlow(spec: DiagramSpec): LayoutResult {
  const nodes = spec.nodes
  if (!nodes.length) return empty([], [])
  const indegree = new Map(nodes.map((node) => [node.id, 0]))
  for (const edge of spec.edges) {
    if (indegree.has(edge.to) && indegree.has(edge.from)) {
      indegree.set(edge.to, (indegree.get(edge.to) || 0) + 1)
    }
  }
  const queue = nodes.filter((node) => (indegree.get(node.id) || 0) === 0).map((n) => n.id)
  const order: string[] = []
  const byId = new Map(nodes.map((node) => [node.id, node]))
  const outgoing = new Map<string, string[]>()
  for (const node of nodes) outgoing.set(node.id, [])
  for (const edge of spec.edges) {
    if (outgoing.has(edge.from) && byId.has(edge.to)) outgoing.get(edge.from)!.push(edge.to)
  }
  while (queue.length) {
    const id = queue.shift()!
    order.push(id)
    for (const next of outgoing.get(id) || []) {
      indegree.set(next, (indegree.get(next) || 1) - 1)
      if ((indegree.get(next) || 0) <= 0) queue.push(next)
    }
  }
  for (const node of nodes) {
    if (!order.includes(node.id)) order.push(node.id)
  }
  // 流程图按层布局:同一层并排,下一层居中。单列堆叠会让分支边穿过中间节点。
  const ordered = order.map((id) => byId.get(id)).filter((node) => node !== undefined)
  const depth = new Map<string, number>(ordered.map((node) => [node.id, 0]))
  for (const id of order) {
    const nextDepth = (depth.get(id) || 0) + 1
    for (const next of outgoing.get(id) || []) {
      depth.set(next, Math.max(depth.get(next) || 0, nextDepth))
    }
  }
  const levels: Array<typeof ordered> = []
  for (const node of ordered) {
    const level = depth.get(node.id) || 0
    if (!levels[level]) levels[level] = []
    levels[level].push(node)
  }
  for (let i = 0; i < levels.length; i += 1) {
    if (!levels[i]) levels[i] = []
  }
  const levelWidths = levels.map((level) => (
    level.reduce((sum, node) => sum + nodeWidth(node.label), 0)
    + Math.max(0, level.length - 1) * GAP_X
  ))
  const maxWidth = Math.max(160, ...levelWidths)
  const positioned: PositionedNode[] = []
  levels.forEach((level, levelIndex) => {
    let cursor = MARGIN + (maxWidth - (levelWidths[levelIndex] || 0)) / 2
    for (const node of level) {
      const w = nodeWidth(node.label)
      positioned.push({
        id: node.id, label: node.label, w, h: NODE_H,
        x: cursor,
        y: MARGIN + levelIndex * (NODE_H + GAP_Y),
      })
      cursor += w + GAP_X
    }
  })
  return finish(positioned, connect(positioned, spec))
}

export function layoutForSpec(spec: DiagramSpec): LayoutResult {
  if (spec.type === 'tree') return layoutTree(spec)
  if (spec.type === 'flow') return layoutFlow(spec)
  return layoutRelation(spec)
}
