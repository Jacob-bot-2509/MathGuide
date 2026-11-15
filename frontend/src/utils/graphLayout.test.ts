/**
 * 知识图谱布局测试(纯函数)。
 *
 * 分层规则决定 SVG 上每个知识点的坐标:层号错一级,整张图的箭头就会指错;
 * 数据成环时还必须有确定的兜底(否则节点直接从图上消失)。坐标与画布尺寸
 * 都按 MARGIN/LEVEL_GAP/NODE_GAP 常量断言,防止有人改了间距却漏改画布。
 */
import { describe, expect, it } from 'vitest'
import {
  LEVEL_GAP,
  MARGIN,
  NODE_GAP,
  layoutGraph,
  resolveLayout,
  type GraphNodeInput,
} from '@/utils/graphLayout'

describe('layoutGraph / 分层', () => {
  it('空图返回空层级与最小画布', () => {
    const layout = layoutGraph([])
    expect(layout.levels).toEqual([])
    expect(layout.positions).toEqual({})
    expect(layout.width).toBe(MARGIN * 2)
    expect(layout.height).toBe(MARGIN * 2)
  })

  it('单节点落在第 0 层左上角起点', () => {
    const layout = layoutGraph([{ id: 'a' }])
    expect(layout.levels).toEqual([['a']])
    expect(layout.positions.a).toEqual({ x: MARGIN, y: MARGIN, level: 0 })
    expect(layout.width).toBe(MARGIN * 2)
    expect(layout.height).toBe(MARGIN * 2)
  })

  it('链式前置逐级下沉,同层按输入顺序纵向排布', () => {
    const layout = layoutGraph([
      { id: 'c', prerequisites: ['b'] },
      { id: 'a' },
      { id: 'b', prerequisites: ['a'] },
      { id: 'a2' },
    ])
    expect(layout.positions.a.level).toBe(0)
    expect(layout.positions.a2.level).toBe(0)
    expect(layout.positions.b.level).toBe(1)
    expect(layout.positions.c.level).toBe(2)
    // 第 0 层两行;a 在前(a2 在后),纵向差一个 NODE_GAP
    expect(layout.positions.a2.y - layout.positions.a.y).toBe(NODE_GAP)
    expect(layout.positions.a2.x).toBe(layout.positions.a.x)
    // 相邻层横向差一个 LEVEL_GAP
    expect(layout.positions.b.x - layout.positions.a.x).toBe(LEVEL_GAP)
    expect(layout.positions.c.x - layout.positions.b.x).toBe(LEVEL_GAP)
  })

  it('取舍最长路径:菱形结构取最深的层号', () => {
    const layout = layoutGraph([
      { id: 'top' },
      { id: 'left', prerequisites: ['top'] },
      { id: 'right', prerequisites: ['left', 'top'] },
      { id: 'bottom', prerequisites: ['top'] },
      { id: 'end', prerequisites: ['right', 'bottom'] },
    ])
    expect(layout.positions.right.level).toBe(2)
    expect(layout.positions.bottom.level).toBe(1)
    expect(layout.positions.end.level).toBe(3)
  })

  it('未知前置被忽略,不产生虚假层级', () => {
    const layout = layoutGraph([{ id: 'a', prerequisites: ['ghost'] }, { id: 'b', prerequisites: ['a', 'ghost'] }])
    expect(layout.positions.a.level).toBe(0)
    expect(layout.positions.b.level).toBe(1)
    expect(layout.positions.ghost).toBeUndefined()
  })

  it('成环时环上节点放到末层之后,仍然可见', () => {
    const nodes: GraphNodeInput[] = [
      { id: 'root' },
      { id: 'x', prerequisites: ['root', 'y'] },
      { id: 'y', prerequisites: ['x'] },
    ]
    const layout = layoutGraph(nodes)
    expect(layout.positions.root.level).toBe(0)
    // x 永远解不开(x 依赖 y、y 依赖 x) → 两者一起落到解开节点之后的末层
    expect(layout.positions.x.level).toBe(layout.positions.y.level)
    expect(layout.positions.x.level).toBe(2)
    expect(Object.keys(layout.positions)).toHaveLength(3)
  })

  it('画布尺寸覆盖最宽层与最高列', () => {
    const nodes: GraphNodeInput[] = [
      { id: 'a' }, { id: 'b' }, { id: 'c' },
      { id: 'd', prerequisites: ['a'] },
      { id: 'e', prerequisites: ['d'] },
    ]
    const layout = layoutGraph(nodes)
    expect(layout.height).toBe(MARGIN * 2 + (3 - 1) * NODE_GAP)
    expect(layout.width).toBe(MARGIN * 2 + (3 - 1) * LEVEL_GAP)
  })
})

describe('resolveLayout', () => {
  it('后端坐标齐全时原样采用', () => {
    const layout = resolveLayout([
      { id: 'a', x: 10, y: 20, level: 0 },
      { id: 'b', x: 300, y: 40, level: 1 },
    ])
    expect(layout.positions).toEqual({
      a: { x: 10, y: 20, level: 0 },
      b: { x: 300, y: 40, level: 1 },
    })
    expect(layout.levels).toEqual([['a'], ['b']])
    expect(layout.width).toBe(300 + LEVEL_GAP)
    expect(layout.height).toBe(40 + NODE_GAP)
  })

  it('任缺一个坐标就退回本地分层布局', () => {
    const partial = resolveLayout([
      { id: 'a', x: 10, y: 20, level: 0 },
      { id: 'b', prerequisites: ['a'] },
    ])
    expect(partial).toEqual(layoutGraph([
      { id: 'a', x: 10, y: 20, level: 0 },
      { id: 'b', prerequisites: ['a'] },
    ]))
    expect(partial.positions.a).toEqual({ x: MARGIN, y: MARGIN, level: 0 })
  })

  it('层号有空洞时补齐空列,避免后续层错位', () => {
    const layout = resolveLayout([
      { id: 'a', x: 0, y: 0, level: 0 },
      { id: 'b', x: 100, y: 0, level: 2 },
    ])
    expect(layout.levels).toEqual([['a'], [], ['b']])
  })

  it('空数组走本地布局(不抛 Math.max 空参数)', () => {
    expect(resolveLayout([])).toEqual(layoutGraph([]))
  })
})
