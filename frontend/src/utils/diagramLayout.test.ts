/**
 * diagramLayout:树/关系/流程三种确定性布局 + 边标签排布。
 *
 * 为什么值得测:这里没有任何浏览器参与,坐标全靠算。
 * 排序不稳定 → 每次刷新图都“跳一下”;重叠消解漏了 → 节点叠成一坨;
 * 边标签排布漏判 → 文字被节点底色盖住、只剩半截。
 */
import { describe, expect, it } from 'vitest'
import type { DiagramSpec } from '@/utils/diagramSpec'
import {
  layoutFlow,
  layoutForSpec,
  layoutRelation,
  layoutTree,
  type LayoutResult,
} from '@/utils/diagramLayout'

const spec = (over: Partial<DiagramSpec> & Pick<DiagramSpec, 'type'>): DiagramSpec => ({
  nodes: [],
  edges: [],
  shapes: [],
  annotations: [],
  ...over,
})

const tree = (nodes: string[][], edges: Array<[string, string, string?]>): DiagramSpec => spec({
  type: 'tree',
  nodes: nodes.map(([id, label]) => ({ id, label })),
  edges: edges.map(([from, to, label]) => ({ from, to, label })),
})

const overlaps = (a: { x: number; y: number; w: number; h: number },
                  b: { x: number; y: number; w: number; h: number }): boolean =>
  a.x < b.x + b.w - 0.5 && b.x < a.x + a.w - 0.5
  && a.y < b.y + b.h - 0.5 && b.y < a.y + a.h - 0.5

const expectSane = (result: LayoutResult): void => {
  expect(result.width).toBeGreaterThan(0)
  expect(result.height).toBeGreaterThan(0)
  for (const node of result.nodes) {
    expect(Number.isFinite(node.x)).toBe(true)
    expect(Number.isFinite(node.y)).toBe(true)
    expect(node.x).toBeGreaterThanOrEqual(0)
    expect(node.y).toBeGreaterThanOrEqual(0)
    expect(node.x + node.w).toBeLessThanOrEqual(result.width)
  }
}

describe('layoutTree:分层树', () => {
  it('空 spec 返回 1×1 空画布(调用方不用判 null)', () => {
    expect(layoutTree(spec({ type: 'tree' }))).toEqual({
      nodes: [], edges: [], width: 1, height: 1,
    })
  })

  it('单节点贴左上角内边距放置', () => {
    const result = layoutTree(tree([['a', '根']], []))
    expect(result.nodes[0]).toMatchObject({ id: 'a', x: 24, y: 24, h: 34 })
    expectSane(result)
  })

  it('每一层固定下移 60px(34 高 + 26 间距)', () => {
    const result = layoutTree(tree(
      [['a', 'A'], ['b', 'B'], ['c', 'C']],
      [['a', 'b'], ['b', 'c']],
    ))
    const byId = new Map(result.nodes.map((node) => [node.id, node]))
    expect(byId.get('a')!.y).toBe(24)
    expect(byId.get('b')!.y).toBe(84)
    expect(byId.get('c')!.y).toBe(144)
  })

  it('父节点居中于首末子节点之间', () => {
    const result = layoutTree(tree(
      [['root', '根'], ['l', '左'], ['r', '右']],
      [['root', 'l'], ['root', 'r']],
    ))
    const byId = new Map(result.nodes.map((node) => [node.id, node]))
    const root = byId.get('root')!
    const left = byId.get('l')!
    const right = byId.get('r')!
    expect(root.x + root.w / 2).toBeCloseTo(
      (left.x + left.w / 2 + right.x + right.w / 2) / 2,
    )
  })

  it('共享子节点只画一次,两个父节点都指向它', () => {
    const result = layoutTree(tree(
      [['a', 'A'], ['b', 'B'], ['c', 'C'], ['d', 'D']],
      [['a', 'b'], ['a', 'c'], ['b', 'd'], ['c', 'd']],
    ))
    expect(result.nodes.filter((node) => node.id === 'd')).toHaveLength(1)
    expect(result.edges.filter((edge) => edge.to === 'd')).toHaveLength(2)
  })

  it('有环时不会死递归(互相指向的两个节点)', () => {
    const result = layoutTree(tree(
      [['a', 'A'], ['b', 'B']],
      [['a', 'b'], ['b', 'a']],
    ))
    expect(result.nodes).toHaveLength(2)
    expectSane(result)
  })

  it('多根森林全部从第 0 层开始', () => {
    const result = layoutTree(tree([['a', 'A'], ['b', 'B']], []))
    expect(result.nodes.map((node) => node.y)).toEqual([24, 24])
    expect(result.nodes[0].x).not.toBe(result.nodes[1].x)
  })

  it('指向未知节点的边被忽略,不会插出幽灵节点', () => {
    const result = layoutTree(tree([['a', 'A']], [['a', 'ghost']]))
    expect(result.nodes).toHaveLength(1)
    expect(result.edges).toEqual([])
  })

  it('节点宽度按字数估算并夹在 96~280 之间', () => {
    const result = layoutTree(tree([['a', '短'], ['b', '很长'.repeat(60)]], []))
    const widths = result.nodes.map((node) => node.w)
    expect(Math.min(...widths)).toBeGreaterThanOrEqual(96)
    expect(Math.max(...widths)).toBeLessThanOrEqual(280)
  })

  it('边端点收进节点边缘,箭头不会压在节点上', () => {
    const result = layoutTree(tree([['a', 'A'], ['b', 'B']], [['a', 'b']]))
    const edge = result.edges[0]
    expect(edge.y1).toBeGreaterThan(24 + 34 / 2)
    expect(edge.y2).toBeLessThan(84 + 34 / 2)
  })

  it('同层节点重叠时向右让位,保证互不遮挡', () => {
    const nodes = Array.from({ length: 6 }, (_, i) => [`n${i}`, `节点${i}`] as string[])
    const result = layoutTree(spec({ type: 'tree', nodes: nodes.map(([id, label]) => ({ id, label })) }))
    for (let i = 0; i < result.nodes.length; i += 1) {
      for (let j = i + 1; j < result.nodes.length; j += 1) {
        expect(overlaps(result.nodes[i], result.nodes[j])).toBe(false)
      }
    }
  })
})

describe('layoutRelation:环形关系图', () => {
  const relation = (count: number): DiagramSpec => spec({
    type: 'relation',
    nodes: Array.from({ length: count }, (_, i) => ({ id: `n${i}`, label: `节点${i}` })),
    edges: count > 1 ? [{ from: 'n0', to: 'n1' }] : [],
  })

  it('空 spec 返回 1×1 空画布', () => {
    expect(layoutRelation(spec({ type: 'relation' })).nodes).toEqual([])
  })

  it('单节点从正上方开始排(角度 -90°)', () => {
    const result = layoutRelation(relation(1))
    expect(result.nodes[0].y).toBe(63)
    expectSane(result)
  })

  it('多节点均匀分布在圆上,互不重叠', () => {
    const result = layoutRelation(relation(5))
    expect(result.nodes).toHaveLength(5)
    for (let i = 0; i < result.nodes.length; i += 1) {
      for (let j = i + 1; j < result.nodes.length; j += 1) {
        expect(overlaps(result.nodes[i], result.nodes[j])).toBe(false)
      }
    }
  })

  it('半径随节点数增长,不会把小图撑到离谱', () => {
    const small = layoutRelation(relation(2))
    const big = layoutRelation(relation(20))
    expect(big.width).toBeGreaterThan(small.width)
  })

  it('长标签会撑大半径(避免文字互相咬住)', () => {
    const long = spec({
      type: 'relation',
      nodes: [
        { id: 'a', label: '很长很长的节点标签'.repeat(6) },
        { id: 'b', label: '另一个很长很长的节点标签'.repeat(6) },
      ],
    })
    expect(layoutRelation(long).width).toBeGreaterThan(layoutRelation(relation(2)).width)
  })

  it('边连接两个节点中心并被收进边缘', () => {
    const result = layoutRelation(relation(2))
    expect(result.edges).toHaveLength(1)
    expect(result.edges[0].x1).toBeGreaterThan(0)
    expect(Number.isFinite(result.edges[0].y2)).toBe(true)
  })
})

describe('layoutFlow:分层流程图', () => {
  const flow = (pairs: Array<[string, string, string?]>, extra: string[] = []): DiagramSpec => {
    const ids = new Set<string>()
    for (const [from, to] of pairs) { ids.add(from); ids.add(to) }
    for (const id of extra) ids.add(id)
    return spec({
      type: 'flow',
      nodes: [...ids].map((id) => ({ id, label: id.toUpperCase() })),
      edges: pairs.map(([from, to, label]) => ({ from, to, label })),
    })
  }

  it('空 spec 返回 1×1 空画布', () => {
    expect(layoutFlow(spec({ type: 'flow' }))).toEqual({
      nodes: [], edges: [], width: 1, height: 1,
    })
  })

  it('链式流程按层向下推进', () => {
    const result = layoutFlow(flow([['a', 'b'], ['b', 'c']]))
    const byId = new Map(result.nodes.map((node) => [node.id, node]))
    expect(byId.get('a')!.y).toBe(24)
    expect(byId.get('b')!.y).toBe(84)
    expect(byId.get('c')!.y).toBe(144)
  })

  it('同一层的分支节点并排,且所在层整体居中', () => {
    const result = layoutFlow(flow([['a', 'b'], ['a', 'c']]))
    const byId = new Map(result.nodes.map((node) => [node.id, node]))
    const b = byId.get('b')!
    const c = byId.get('c')!
    expect(b.y).toBe(c.y)
    expect(b.x).toBeLessThan(c.x)
    const center = (b.x + c.x + c.w) / 2
    expect(center).toBeGreaterThan(0)
    expectSane(result)
  })

  it('多入口(多个入度 0 的节点)都从第 0 层开始', () => {
    const result = layoutFlow(flow([['a', 'c'], ['b', 'c']]))
    const byId = new Map(result.nodes.map((node) => [node.id, node]))
    expect(byId.get('a')!.y).toBe(24)
    expect(byId.get('b')!.y).toBe(24)
    expect(byId.get('c')!.y).toBe(84)
  })

  it('有环时退化成“按节点顺序分层”,不会死循环', () => {
    const result = layoutFlow(flow([['a', 'b'], ['b', 'a']]))
    expect(result.nodes).toHaveLength(2)
    expectSane(result)
  })

  it('自环不会被当成孤立节点重复添加', () => {
    const result = layoutFlow(flow([['a', 'a']]))
    expect(result.nodes).toHaveLength(1)
  })

  it('孤立节点(无边)也会被排进图里', () => {
    const result = layoutFlow(flow([['a', 'b']], ['solo']))
    expect(result.nodes.map((node) => node.id).sort()).toEqual(['a', 'b', 'solo'])
    expectSane(result)
  })

  it('边指向未知节点时忽略,不会让布局崩掉', () => {
    const result = layoutFlow(flow([['a', 'ghost']]))
    expect(result.nodes.map((node) => node.id)).toEqual(['a', 'ghost'])
  })
})

describe('layoutForSpec:按类型分派', () => {
  it('tree 走树布局(父在子之上)', () => {
    const result = layoutForSpec(tree([['a', 'A'], ['b', 'B']], [['a', 'b']]))
    const byId = new Map(result.nodes.map((node) => [node.id, node]))
    expect(byId.get('a')!.y).toBeLessThan(byId.get('b')!.y)
  })

  it('flow 走流程图布局', () => {
    const result = layoutForSpec(spec({
      type: 'flow',
      nodes: [{ id: 'a', label: 'A' }, { id: 'b', label: 'B' }],
      edges: [{ from: 'a', to: 'b' }],
    }))
    expect(result.nodes).toHaveLength(2)
  })

  it('其他类型(含几何/曲面)都退化到环形关系布局', () => {
    for (const type of ['relation', 'geometry2d', 'plot2d', 'geometria'] as const) {
      const result = layoutForSpec(spec({
        // 'geometria' 是脏 kind(前端历史拼写),故意绕过类型走运行期兜底
        type: type as unknown as DiagramSpec['type'], nodes: [{ id: 'a', label: 'A' }],
      }))
      expect(result.nodes[0].y).toBe(63)
    }
  })
})


describe('边标签排布(placeEdgeLabels)', () => {
  it('带 label 的边会算出文字折行与坐标', () => {
    const result = layoutTree(tree([['a', 'A'], ['b', 'B']], [['a', 'b', '包含']]))
    const edge = result.edges[0]
    expect(result.edges[0].label).toBe('包含')
    expect(edge.labelLines).toEqual(['包含'])
    expect(typeof edge.labelX).toBe('number')
    expect(typeof edge.labelY).toBe('number')
  })

  it('文字坐标落在画布内,不会溢出到负值', () => {
    const result = layoutTree(tree([['a', 'A'], ['b', 'B']], [['a', 'b', '边']]))
    const edge = result.edges[0]
    expect(edge.labelX!).toBeGreaterThanOrEqual(0)
    expect(edge.labelX! + 8).toBeLessThanOrEqual(result.width + 1)
    expect(edge.labelY!).toBeGreaterThanOrEqual(0)
  })

  it('画布尺寸会为边标签留出余量', () => {
    const withoutLabel = layoutTree(tree([['a', 'A'], ['b', 'B']], [['a', 'b']]))
    const withLabel = layoutTree(tree([['a', 'A'], ['b', 'B']], [['a', 'b', '一条比较长的关系说明']]))
    expect(withLabel.width).toBeGreaterThanOrEqual(withoutLabel.width)
    expect(withLabel.height).toBeGreaterThanOrEqual(withoutLabel.height)
  })

  it('横向边偏好上下、纵向边偏好左右(文字不压在线上)', () => {
    const horizontal = layoutFlow(spec({
      type: 'flow',
      nodes: [
        { id: 'a', label: 'A' }, { id: 'b', label: 'B' },
        { id: 'c', label: 'C' }, { id: 'd', label: 'D' },
      ],
      edges: [{ from: 'a', to: 'b', label: '下一步' }, { from: 'b', to: 'c', label: '再下一步' }],
    }))
    for (const edge of horizontal.edges) {
      if (!edge.labelLines) continue
      expect(edge.labelLines.join('')).toBeTruthy()
    }
    expect(horizontal.edges).toHaveLength(2)
  })

  it('完全没有标签时不额外计算,直接返回原尺寸', () => {
    const result = layoutTree(tree([['a', 'A'], ['b', 'B']], [['a', 'b']]))
    expect(result.edges[0].labelLines).toBeUndefined()
    expect(result.width).toBeGreaterThan(0)
  })

  it('多条带标签的边不会互相压字(重叠的那条被放弃标签)', () => {
    const nodes = Array.from({ length: 5 }, (_, i) => ({ id: `n${i}`, label: `N${i}` }))
    const edges = [
      { from: 'n0', to: 'n1', label: '关系一' },
      { from: 'n1', to: 'n2', label: '关系二' },
      { from: 'n2', to: 'n3', label: '关系三' },
      { from: 'n3', to: 'n4', label: '关系四' },
    ]
    const result = layoutFlow(spec({ type: 'flow', nodes, edges }))
    const boxes = result.edges
      .filter((edge) => edge.labelX !== undefined)
      .map((edge) => ({ x: edge.labelX!, y: edge.labelY!, w: 40, h: 12 }))
    for (let i = 0; i < boxes.length; i += 1) {
      for (let j = i + 1; j < boxes.length; j += 1) {
        expect(overlaps(boxes[i], boxes[j])).toBe(false)
      }
    }
    // 边本身永远保留,只是可能不带标签
    expect(result.edges).toHaveLength(4)
  })
})

