/**
 * 知识图谱分层布局(纯函数,无 DOM 依赖)。
 *
 * 按前置依赖做最长路径分层:level(v) = max(level(前置) + 1)。
 * 同层节点按输入顺序纵向排列,适合 80 个左右的知识点直接画成 SVG。
 * 未知前置忽略;数据成环时 Kahn 无法处理的节点统一放到末层之后,保证可见。
 */
export interface GraphNodeInput {
  id: string
  prerequisites?: string[]
}

export interface GraphPosition {
  x: number
  y: number
  level: number
}

export interface GraphLayout {
  positions: Record<string, GraphPosition>
  levels: string[][]
  width: number
  height: number
}

/** 同层节点纵向间距(节点高 36,留 22 给文字与连线) */
export const NODE_GAP = 58
/** 相邻层级横向间距(节点宽 164,留 66 给箭头) */
export const LEVEL_GAP = 230
export const MARGIN = 56

export function layoutGraph(nodes: GraphNodeInput[]): GraphLayout {
  const ids = new Set(nodes.map((node) => node.id))
  const indegree = new Map<string, number>()
  const dependents = new Map<string, string[]>()
  const level = new Map<string, number>()

  for (const node of nodes) {
    indegree.set(node.id, 0)
    dependents.set(node.id, [])
    level.set(node.id, 0)
  }
  for (const node of nodes) {
    for (const prereq of node.prerequisites ?? []) {
      if (!ids.has(prereq)) continue
      indegree.set(node.id, (indegree.get(node.id) ?? 0) + 1)
      dependents.get(prereq)?.push(node.id)
    }
  }

  const ready = nodes
    .filter((node) => (indegree.get(node.id) ?? 0) === 0)
    .map((node) => node.id)
  const processed = new Set<string>()
  while (ready.length) {
    const id = ready.shift()!
    processed.add(id)
    for (const dependent of dependents.get(id) ?? []) {
      level.set(dependent, Math.max(level.get(dependent) ?? 0, (level.get(id) ?? 0) + 1))
      indegree.set(dependent, (indegree.get(dependent) ?? 0) - 1)
      if (indegree.get(dependent) === 0) ready.push(dependent)
    }
  }

  if (processed.size < nodes.length) {
    let maxLevel = 0
    for (const value of level.values()) maxLevel = Math.max(maxLevel, value)
    for (const node of nodes) {
      if (!processed.has(node.id)) level.set(node.id, maxLevel + 1)
    }
  }

  const levels: string[][] = []
  for (const node of nodes) {
    const lv = level.get(node.id) ?? 0
    while (levels.length <= lv) levels.push([])
    levels[lv].push(node.id)
  }

  const positions: Record<string, GraphPosition> = {}
  levels.forEach((column, lv) => {
    column.forEach((id, row) => {
      positions[id] = {
        x: MARGIN + lv * LEVEL_GAP,
        y: MARGIN + row * NODE_GAP,
        level: lv,
      }
    })
  })

  let maxRows = 1
  for (const column of levels) maxRows = Math.max(maxRows, column.length)
  return {
    positions,
    levels,
    width: MARGIN * 2 + Math.max(0, levels.length - 1) * LEVEL_GAP,
    height: MARGIN * 2 + (maxRows - 1) * NODE_GAP,
  }
}
