/**
 * diagramSpec:后端图解协议的前端白名单关口。
 *
 * 为什么这条必须硬测:整条链路上只有这里能把关。后端 schema 一旦跑偏、
 * 或者模型吐出 `Execute[...]` 这类 GeoGebra 命令,前端必须在渲染前拦下来;
 * 拦不住就不是“图画得难看”,而是任意命令注入 + 画布卡死。
 * 另外 splitMessageBlocks 决定图插在正文哪一段 —— 插错位置会让
 * “如下图”变成指向上一段,所以方位词校正也要一起锁住。
 */
import { describe, expect, it } from 'vitest'
import {
  appendDiagram,
  buildPaperDiagram,
  filterCollapsed,
  parseDiagramEvent,
  parseDiagramSpec,
  splitMessageBlocks,
  type DiagramBlock,
  type DiagramSpec,
} from '@/utils/diagramSpec'

const point = { kind: 'point', x: 1, y: 2 }

const geoCommands = (commands: unknown[]): unknown => ({
  type: 'geogebra2d',
  commands,
})

describe('parseDiagramSpec:入口校验', () => {
  it('非对象一律拒绝(含 null / 字符串 / 数组外的原始值)', () => {
    expect(parseDiagramSpec(null)).toBeNull()
    expect(parseDiagramSpec(undefined)).toBeNull()
    expect(parseDiagramSpec('tree')).toBeNull()
    expect(parseDiagramSpec(42)).toBeNull()
  })

  it('未知 type 直接拒绝(白名单只有 9 种)', () => {
    expect(parseDiagramSpec({ type: 'mindmap', nodes: [] })).toBeNull()
    expect(parseDiagramSpec({ type: '', nodes: [] })).toBeNull()
  })

  it('schemaVersion 高于当前版本时拒绝,避免按旧规则误解新字段', () => {
    expect(parseDiagramSpec({
      type: 'tree', schemaVersion: 99, nodes: [{ id: 'a', label: 'A' }],
    })).toBeNull()
  })

  it('低版本/缺版本照常解析,并统一回填当前版本号', () => {
    const spec = parseDiagramSpec({
      type: 'tree', schemaVersion: 0, nodes: [{ id: 'a', label: 'A' }],
    })
    expect(spec?.schemaVersion).toBe(1)
  })

  it('树/关系/流程图没有节点时拒绝(渲染会得到空白画布)', () => {
    for (const type of ['tree', 'relation', 'flow']) {
      expect(parseDiagramSpec({ type, nodes: [] })).toBeNull()
    }
  })
})

describe('parseDiagramSpec:节点与边', () => {
  it('节点保留 id/label/kind/page,并 trim + 截断', () => {
    const spec = parseDiagramSpec({
      type: 'tree',
      nodes: [{ id: ' a ', label: '  根节点  ', kind: 'root', page: 3 }],
    })!
    expect(spec.nodes[0]).toEqual({
      id: 'a', label: '根节点', kind: 'root', page: 3,
    })
  })

  it('缺 id/label 或 id 重复的节点被丢弃', () => {
    const spec = parseDiagramSpec({
      type: 'tree',
      nodes: [
        { id: '', label: 'A' },
        { id: 'a' },
        { id: 'a', label: '第一' },
        { id: 'a', label: '重复' },
        'not-an-object',
        null,
      ],
    })!
    expect(spec.nodes).toHaveLength(1)
    expect(spec.nodes[0].label).toBe('第一')
  })

  it('page 必须为正整数,否则不带 page 字段', () => {
    const spec = parseDiagramSpec({
      type: 'tree',
      nodes: [
        { id: 'a', label: 'A', page: 0 },
        { id: 'b', label: 'B', page: 1.5 },
      ],
    })!
    expect(spec.nodes[0].page).toBeUndefined()
    expect(spec.nodes[1].page).toBeUndefined()
  })

  it('超过 40 个节点直接判整图非法(而不是静默截断)', () => {
    const nodes = Array.from({ length: 41 }, (_, i) => ({ id: `n${i}`, label: `N${i}` }))
    expect(parseDiagramSpec({ type: 'tree', nodes })).toBeNull()
  })

  it('边保留 label/kind,指向未知节点的边被丢弃', () => {
    const spec = parseDiagramSpec({
      type: 'tree',
      nodes: [{ id: 'a', label: 'A' }, { id: 'b', label: 'B' }],
      edges: [
        { from: 'a', to: 'b', label: '包含', kind: 'solid' },
        { from: 'a', to: 'ghost' },
        { from: '', to: 'b' },
        null,
      ],
    })!
    expect(spec.edges).toEqual([{ from: 'a', to: 'b', label: '包含', kind: 'solid' }])
  })

  it('没有任何节点时边不做引用校验(独立几何图的连线仍能渲染)', () => {
    const spec = parseDiagramSpec({
      type: 'plot2d', shapes: [point], edges: [{ from: 'x', to: 'y' }],
    })!
    expect(spec.edges).toEqual([{ from: 'x', to: 'y' }])
  })

  it('超过 80 条边判整图非法', () => {
    const nodes = [{ id: 'a', label: 'A' }]
    const edges = Array.from({ length: 81 }, () => ({ from: 'a', to: 'a' }))
    expect(parseDiagramSpec({ type: 'tree', nodes, edges })).toBeNull()
  })
})

describe('parseDiagramSpec:形状白名单', () => {
  const shapesOf = (shapes: unknown[]): DiagramSpec | null =>
    parseDiagramSpec({ type: 'geometry2d', shapes })

  it('只保留白名单字段,未知字段被丢弃', () => {
    const spec = shapesOf([{
      kind: 'circle', x: 1, y: 2, r: 3, evil: '<script>', onclick: 'x()',
    }])!
    expect(spec.shapes[0]).toEqual({ kind: 'circle', x: 1, y: 2, r: 3 })
  })

  it('缺 kind 或 kind 非字符串的形状被丢弃', () => {
    expect(shapesOf([{ x: 1, y: 2 }, null, 'point'])).toBeNull()
  })

  it('坐标超出 ±1e4 或非有限的字段被忽略(不是置 0)', () => {
    // 用不受“必须可渲染”约束的 kind,单看字段清洗结果
    const spec = shapesOf([{ kind: 'note', x: 1e9, y: 2 }])!
    expect(spec.shapes[0]).toEqual({ kind: 'note', y: 2 })
  })

  it('circle 丢了 x 就不可渲染,整图判非法', () => {
    expect(shapesOf([{ kind: 'circle', x: 1e9, y: 2, r: 3 }])).toBeNull()
  })

  it('label 为 "djj" 时被剔除(水印式占位标签不上图)', () => {
    const spec = shapesOf([{ kind: 'point', x: 1, y: 2, label: 'djj' }])!
    expect(spec.shapes[0]).toEqual({ kind: 'point', x: 1, y: 2 })
    const kept = shapesOf([{ kind: 'point', x: 1, y: 2, label: 'A' }])!
    expect(kept.shapes[0].label).toBe('A')
  })

  it('points 里的坏点被过滤,保留合法点', () => {
    const spec = shapesOf([{
      kind: 'curve', points: [[0, 0], [1], ['a', 'b'], [1, 2, 3]],
    }])!
    expect(spec.shapes[0].points).toEqual([[0, 0], [1, 2, 3]])
  })

  it('segments 每段至少两点,共享总点数预算', () => {
    const spec = shapesOf([{
      kind: 'curve',
      points: [[0, 0]],
      segments: [[[0, 0], [1, 1]], [[2, 2]], 'bad', [[3, 3], [4, 4]]],
    }])!
    expect(spec.shapes[0].segments).toEqual([
      [[0, 0], [1, 1]],
      [[3, 3], [4, 4]],
    ])
  })

  it('segments 全都是坏数据时不带 segments 字段', () => {
    const spec = shapesOf([{ kind: 'curve', points: [[0, 0]], segments: [[[1, 1]]] }])!
    expect(spec.shapes[0].segments).toBeUndefined()
  })

  it('domain 只接受 2~4 个数字', () => {
    expect(shapesOf([{ kind: 'curve', points: [[0, 0]], domain: [0, 1] }])!
      .shapes[0].domain).toEqual([0, 1])
    expect(shapesOf([{ kind: 'curve', points: [[0, 0]], domain: [0] }])!
      .shapes[0].domain).toBeUndefined()
    expect(shapesOf([{ kind: 'curve', points: [[0, 0]], domain: [0, 1, 2, 3, 4] }])!
      .shapes[0].domain).toBeUndefined()
  })

  it('rows/cols 被夹到 2~41 且必须是整数', () => {
    const spec = shapesOf([{
      kind: 'matrix', rows: 1, cols: 99,
    }])!
    expect(spec.shapes[0]).toMatchObject({ rows: 2, cols: 41 })
    const bad = shapesOf([{ kind: 'matrix', rows: 2.5 }])!
    expect(bad.shapes[0].rows).toBeUndefined()
  })

  it('segment/line/vector/axis 缺 from 或 to 时整条丢弃', () => {
    expect(shapesOf([{ kind: 'segment', from: [0, 0] }])).toBeNull()
    expect(shapesOf([
      { kind: 'axis', from: [0, 0], to: [1, 1] },
      { kind: 'vector', from: [0, 0], to: [1, 1] },
    ])!.shapes).toHaveLength(2)
  })

  it('point 缺 x/y 时丢弃', () => {
    expect(shapesOf([{ kind: 'point', x: 1 }])).toBeNull()
  })

  it('surface / polygon 缺 points 时丢弃', () => {
    expect(shapesOf([{ kind: 'polygon', from: [0, 0] }])).toBeNull()
    expect(shapesOf([{ kind: 'surface', points: [[0, 0, 0]] }])!.shapes).toHaveLength(1)
  })

  it('只有 axis 这类不可渲染形状时整图判非法', () => {
    expect(shapesOf([{ kind: 'axis', from: [0, 0], to: [1, 1] }])).toBeNull()
  })

  it('curve 的 points 为空数组时不可渲染,整图判非法', () => {
    expect(shapesOf([{ kind: 'curve', points: [] }])).toBeNull()
  })

  it('segment 的 from/to 非数组时不可渲染', () => {
    expect(shapesOf([{ kind: 'segment', from: '0,0', to: '1,1', points: [] }]))
      .toBeNull()
  })

  it('超过 100 个形状判整图非法', () => {
    const shapes = Array.from({ length: 101 }, () => point)
    expect(shapesOf(shapes)).toBeNull()
  })
})

describe('parseDiagramSpec:标注与视图', () => {
  it('标注需要 x/y/text 齐全,可选 z', () => {
    const spec = parseDiagramSpec({
      type: 'plot2d', shapes: [point],
      annotations: [
        { x: 1, y: 2, text: '顶点', z: 3 },
        { x: 1, y: 2 },
        { x: 1, y: 2, text: '   ' },
      ],
    })!
    expect(spec.annotations).toEqual([{ x: 1, y: 2, text: '顶点', z: 3 }])
  })

  it('非树类型只有标注没有形状时判非法(渲染器需要至少一个可画形状)', () => {
    expect(parseDiagramSpec({
      type: 'geometry2d', annotations: [{ x: 0, y: 0, text: '原点' }],
    })).toBeNull()
  })

  it('标注可以和形状共存,并保持顺序', () => {
    const spec = parseDiagramSpec({
      type: 'plot2d', shapes: [point],
      annotations: [{ x: 0, y: 0, text: '原点' }],
    })!
    expect(spec.annotations[0].text).toBe('原点')
  })

  it('超过 40 条标注判整图非法', () => {
    const annotations = Array.from({ length: 41 }, () => ({ x: 0, y: 0, text: 't' }))
    expect(parseDiagramSpec({ type: 'plot2d', shapes: [point], annotations }))
      .toBeNull()
  })

  it('完全没有节点/形状/标注时返回 null', () => {
    expect(parseDiagramSpec({ type: 'plot2d', nodes: [], shapes: [] })).toBeNull()
  })

  it('view 的 zoom 被夹到 0.1~8,非法 zoom 则整段视图丢弃', () => {
    const zoomIn = parseDiagramSpec({
      type: 'plot2d', shapes: [point], view: { x: 1, y: 2, zoom: 100 },
    })!
    expect(zoomIn.view).toEqual({ x: 1, y: 2, zoom: 8 })
    const zoomOut = parseDiagramSpec({
      type: 'plot2d', shapes: [point], view: { x: 1, y: 2, zoom: 0 },
    })!
    expect(zoomOut.view).toBeUndefined()
    const nan = parseDiagramSpec({
      type: 'plot2d', shapes: [point], view: { x: 'a', y: 2, zoom: 1 },
    })!
    expect(nan.view).toBeUndefined()
  })

  it('title 被 trim 且截断到 200 字符', () => {
    const spec = parseDiagramSpec({
      type: 'plot2d', shapes: [point], title: '  函数图像  ',
    })!
    expect(spec.title).toBe('函数图像')
    const long = parseDiagramSpec({
      type: 'plot2d', shapes: [point], title: 'x'.repeat(500),
    })!
    expect((long.title as string).length).toBe(200)
  })
})


describe('parseDiagramSpec:GeoGebra 命令白名单', () => {
  it('合法命令被 trim 后原样保留,节点/形状留空', () => {
    const spec = parseDiagramSpec(geoCommands([' A=(1,2)', 'Circle(A,2)']))!
    expect(spec.type).toBe('geogebra2d')
    expect(spec.commands).toEqual(['A=(1,2)', 'Circle(A,2)'])
    expect(spec.shapes).toEqual([])
    expect(spec.title).toBeUndefined()
  })

  it('geogebra3d 走同一套校验', () => {
    const spec = parseDiagramSpec({ type: 'geogebra3d', commands: ['Cube(A,B)'] })!
    expect(spec.type).toBe('geogebra3d')
  })

  it('命令数量必须在 1~30 之间', () => {
    expect(parseDiagramSpec(geoCommands([]))).toBeNull()
    expect(parseDiagramSpec(geoCommands(Array.from({ length: 31 }, () => 'A=(1,2)'))))
      .toBeNull()
    expect(parseDiagramSpec(geoCommands(Array.from({ length: 30 }, () => 'A=(1,2)'))))
      .not.toBeNull()
  })

  it('非字符串 / 空串 / 超 200 字符的命令整批拒绝', () => {
    expect(parseDiagramSpec(geoCommands([1]))).toBeNull()
    expect(parseDiagramSpec(geoCommands(['   ']))).toBeNull()
    expect(parseDiagramSpec(geoCommands([`A=(${'1'.repeat(300)},0)`]))).toBeNull()
  })

  it('换行 / 回车 / 分号是命令拼接注入的典型手法,一律拒绝', () => {
    expect(parseDiagramSpec(geoCommands(['A=(1,2)\nB=(3,4)']))).toBeNull()
    expect(parseDiagramSpec(geoCommands(['A=(1,2)\rB=(3,4)']))).toBeNull()
    expect(parseDiagramSpec(geoCommands(['A=(1,2);B=(3,4)']))).toBeNull()
  })

  it('危险命令(脚本/网络/文件/视角操作)被关键词拦下', () => {
    const forbidden = [
      'Execute({"A=(1,2)"})',
      'JavaScript("alert(1)")',
      'SetValue(a,1)',
      'StartAnimation(a,true)',
      'Play(a)',
      'Delete(a)',
      'Rename(a,"b")',
      'SetPerspective("3D")',
      'ZoomIn(2)',
      'ZoomOut(2)',
      'Pan(1,2)',
      'Image("http://x/y.png")',
      'Text("hi")',
      'Text["hi"]',
      'Export["a.png"]',
      'Save()',
      'Open("a.ggb")',
      'Load("a.ggb")',
      'Script("x")',
      'SetActiveView(1)',
    ]
    for (const command of forbidden) {
      expect(parseDiagramSpec(geoCommands([command])), command).toBeNull()
    }
  })

  it('单条违规就整批拒绝(不做部分放行)', () => {
    expect(parseDiagramSpec(geoCommands(['A=(1,2)', 'Save()']))).toBeNull()
  })

  it('geogebra 图也接受 title', () => {
    const spec = parseDiagramSpec({ ...geoCommands(['A=(1,2)']) as object, title: ' 抛物线 ' })
    expect(spec?.title).toBe('抛物线')
  })

  it('commands 不是数组时拒绝', () => {
    expect(parseDiagramSpec({ type: 'geogebra2d', commands: 'A=(1,2)' })).toBeNull()
    expect(parseDiagramSpec({ type: 'geogebra2d' })).toBeNull()
  })
})

describe('parseDiagramEvent:流式事件封装', () => {
  const payload = {
    mg_event: 'diagram',
    anchorId: 'd1',
    anchorIndex: 5,
    diagram: { type: 'plot2d', shapes: [point] },
  }

  it('完整事件被解析成图文块', () => {
    const block = parseDiagramEvent(payload)!
    expect(block.id).toBe('d1')
    expect(block.anchorIndex).toBe(5)
    expect(block.spec.shapes).toHaveLength(1)
  })

  it('事件名不匹配 / 缺 anchorId / spec 非法 / anchorIndex 为负都不是图解事件', () => {
    expect(parseDiagramEvent({ ...payload, mg_event: 'text' })).toBeNull()
    expect(parseDiagramEvent({ ...payload, anchorId: '' })).toBeNull()
    expect(parseDiagramEvent({ ...payload, diagram: { type: 'nope' } })).toBeNull()
    expect(parseDiagramEvent({ ...payload, anchorIndex: -1 })).toBeNull()
    expect(parseDiagramEvent({ ...payload, anchorIndex: 1.5 })).toBeNull()
    expect(parseDiagramEvent(null)).toBeNull()
  })
})


describe('splitMessageBlocks:图文切分与方位词校正', () => {
  const block = (id: string, anchorIndex: number): DiagramBlock => ({
    id,
    anchorIndex,
    spec: { type: 'plot2d', nodes: [], edges: [], shapes: [point], annotations: [] },
  })

  it('没有图时整段就是一个文本块', () => {
    expect(splitMessageBlocks('纯文本回答', undefined))
      .toEqual([{ kind: 'text', text: '纯文本回答' }])
  })

  it('空内容也返回一个空文本块,不让调用方拿到空数组', () => {
    expect(splitMessageBlocks('', [])).toEqual([{ kind: 'text', text: '' }])
  })

  it('按 anchorIndex 插图,并按位置切成文本/图/文本', () => {
    const blocks = splitMessageBlocks('ABCDEFG', [block('d1', 3)])
    expect(blocks.map((item) => item.kind)).toEqual(['text', 'diagram', 'text'])
    expect(blocks[0]).toMatchObject({ text: 'ABC' })
    expect(blocks[2]).toMatchObject({ text: 'DEFG' })
  })

  it('anchorIndex 超出正文长度时夹到末尾,不会切出空片段', () => {
    const blocks = splitMessageBlocks('ABC', [block('d1', 999)])
    expect(blocks).toHaveLength(2)
    expect(blocks[1].kind).toBe('diagram')
  })

  it('anchorIndex 乱序时按升序插入并忽略重复位置', () => {
    const blocks = splitMessageBlocks('ABCD', [block('d2', 2), block('d1', 2)])
    expect(blocks.filter((item) => item.kind === 'diagram')).toHaveLength(2)
  })

  it('没有 spec 的图解块被过滤掉(半成品事件不插图)', () => {
    const broken = { id: 'x', anchorIndex: 0 } as unknown as DiagramBlock
    expect(splitMessageBlocks('abc', [broken]))
      .toEqual([{ kind: 'text', text: 'abc' }])
  })

  it('图在正文之后时,把“如上图”改成“如下图所示”', () => {
    const blocks = splitMessageBlocks('如上图所示,函数单调递增。', [block('d1', 13)])
    expect(blocks[0]).toMatchObject({ kind: 'text' })
    expect((blocks[0] as { text: string }).text).toContain('如下图所示')
  })

  it('图在正文之前时,把“如下图”改成“如上图”', () => {
    const blocks = splitMessageBlocks('如下图,函数单调递增。', [block('d1', 0)])
    const text = blocks.find((item) => item.kind === 'text') as { text: string }
    expect(text.text).toContain('如上图')
  })

  it('只改图前后 200 字,远处的“下图”不动(避免误伤别的小节)', () => {
    const head = '开头'.repeat(150) // 300 字,远超 200
    const blocks = splitMessageBlocks(`${head}如下图,见后文。`, [block('d1', 0)])
    const text = blocks.find((item) => item.kind === 'text') as { text: string }
    expect(text.text.slice(0, 4)).toBe('开头开头')
    expect(text.text).toContain('如下图')
  })

  it('中文方位词的整组替换都生效(下图系列 → 上图系列)', () => {
    const after = splitMessageBlocks('见下图所示,以及下面的图。', [block('d1', 0)])
    const text = after.find((item) => item.kind === 'text') as { text: string }
    expect(text.text).toBe('见上图所示,以及上面的图。')
  })

  it('图在正文之后时反向替换(上图系列 → 下图系列)', () => {
    const before = splitMessageBlocks('如上图所示,以及上面的图。', [block('d1', 14)])
    const text = before[0] as { text: string }
    expect(text.text).toBe('如下图所示,以及下面的图。')
  })
})

describe('appendDiagram:追加与资源上限', () => {
  const make = (id: string, points: number): DiagramBlock => ({
    id,
    anchorIndex: 0,
    spec: {
      type: 'plot2d',
      nodes: [],
      edges: [],
      shapes: [{ kind: 'curve', points: Array.from({ length: points }, () => [0, 0]) }],
      annotations: [],
    },
  })

  it('同 id 重复到达时保持原数组不变(流式重放不会重复插图)', () => {
    const existing = [make('d1', 2)]
    expect(appendDiagram(existing, make('d1', 2))).toBe(existing)
  })

  it('最多两张图,第三张被拒绝', () => {
    const two = appendDiagram(appendDiagram([], make('d1', 2)), make('d2', 2))
    expect(two).toHaveLength(2)
    expect(appendDiagram(two, make('d3', 2))).toHaveLength(2)
  })

  it('两张图总点数超过 8000 时拒绝第二张(防止一次回答画出上万点)', () => {
    const first = make('d1', 5000)
    expect(appendDiagram([first], make('d2', 4000))).toHaveLength(1)
    expect(appendDiagram([first], make('d2', 3000))).toHaveLength(2)
  })

  it('existing 为 undefined 时按空数组处理', () => {
    expect(appendDiagram(undefined, make('d1', 2))).toHaveLength(1)
  })
})


describe('filterCollapsed:折叠树/关系图', () => {
  const spec: DiagramSpec = {
    type: 'tree',
    nodes: [
      { id: 'a', label: 'A' },
      { id: 'b', label: 'B' },
      { id: 'c', label: 'C' },
    ],
    edges: [{ from: 'a', to: 'b' }, { from: 'b', to: 'c' }],
    shapes: [],
    annotations: [],
  }

  it('折叠一个节点会隐藏它的全部后代,但保留节点本身', () => {
    const out = filterCollapsed(spec, new Set(['a']))
    expect(out.nodes.map((node) => node.id)).toEqual(['a'])
    expect(out.edges).toEqual([])
  })

  it('折叠中间层只隐藏更深一层', () => {
    const out = filterCollapsed(spec, new Set(['b']))
    expect(out.nodes.map((node) => node.id)).toEqual(['a', 'b'])
    expect(out.edges).toEqual([{ from: 'a', to: 'b' }])
  })

  it('没有折叠集合或非树/关系图时原样返回(不做无谓拷贝)', () => {
    expect(filterCollapsed(spec, new Set())).toBe(spec)
    const flow: DiagramSpec = { ...spec, type: 'flow' }
    expect(filterCollapsed(flow, new Set(['a']))).toBe(flow)
  })

  it('环形关系不会无限递归', () => {
    const cyclic: DiagramSpec = {
      type: 'relation',
      nodes: [{ id: 'a', label: 'A' }, { id: 'b', label: 'B' }],
      edges: [{ from: 'a', to: 'b' }, { from: 'b', to: 'a' }],
      shapes: [],
      annotations: [],
    }
    expect(filterCollapsed(cyclic, new Set(['a'])).nodes.map((node) => node.id))
      .toEqual(['a'])
  })
})

describe('buildPaperDiagram:论文脑图', () => {
  it('按研究问题/方法/结论/局限分组,并连到根节点', () => {
    const spec = buildPaperDiagram({
      question: '如何提升检索质量?',
      methods: ['BM25', '稠密检索'],
      conclusions: ['混合更好'],
      limitations: [],
      outline: [],
    }, '论文标题')
    expect(spec.type).toBe('tree')
    expect(spec.nodes[0]).toMatchObject({ id: 'p0', label: '论文标题', kind: 'root' })
    const labels = spec.nodes.map((node) => node.label)
    expect(labels).toContain('研究问题')
    expect(labels).toContain('方法')
    expect(labels).toContain('结论')
    expect(labels).not.toContain('局限')
    expect(spec.edges.length).toBeGreaterThan(0)
  })

  it('空的 question / 空分组不产生空节点与悬空边', () => {
    const spec = buildPaperDiagram({
      question: '   ', methods: [], conclusions: [], limitations: [], outline: [],
    })
    expect(spec.nodes).toHaveLength(1)
    expect(spec.edges).toEqual([])
    expect(spec.nodes[0].label).toBe('论文')
  })

  it('每个分组最多取 6 条(脑图不能铺满整屏)', () => {
    const spec = buildPaperDiagram({
      question: '',
      methods: Array.from({ length: 12 }, (_, i) => `方法${i}`),
      conclusions: [],
      limitations: [],
      outline: [],
    })
    const items = spec.nodes.filter(
      (node) => node.label.startsWith('方法') && node.label !== '方法',
    )
    expect(items).toHaveLength(6)
  })

  it('章节层级递归,并把 pageStart 记成页码', () => {
    const spec = buildPaperDiagram({
      question: '',
      methods: [],
      conclusions: [],
      limitations: [],
      outline: [{
        title: '第一章',
        pageStart: 3,
        children: [{ title: '1.1 小节', pageStart: 4 }],
      }],
    })
    const chapter = spec.nodes.find((node) => node.label === '第一章')!
    expect(chapter.page).toBe(3)
    expect(chapter.kind).toBe('outline')
    const child = spec.nodes.find((node) => node.label === '1.1 小节')!
    expect(spec.edges.some((edge) => edge.from === chapter.id && edge.to === child.id))
      .toBe(true)
  })

  it('超过 4 层的章节被截断(防止目录深到无法排版)', () => {
    let outline: Array<{ title: string; children?: typeof outline }> = [
      { title: '第 6 层' },
    ]
    for (let depth = 5; depth >= 1; depth -= 1) {
      outline = [{ title: `第 ${depth} 层`, children: outline }]
    }
    const spec = buildPaperDiagram({
      question: '', methods: [], conclusions: [], limitations: [], outline,
    })
    expect(spec.nodes.some((node) => node.label === '第 5 层')).toBe(true)
    expect(spec.nodes.some((node) => node.label === '第 6 层')).toBe(false)
  })

  it('空标题的目录项被跳过,不会插出空节点', () => {
    const spec = buildPaperDiagram({
      question: '', methods: [], conclusions: [], limitations: [],
      outline: [{ title: '   ' }, { title: '有名字' }],
    })
    expect(spec.nodes.some((node) => node.label === '')).toBe(false)
    expect(spec.nodes.some((node) => node.label === '有名字')).toBe(true)
  })

  it('节点总数到 40 就停止继续加(超长论文也只画得下这些)', () => {
    const outline = Array.from({ length: 60 }, (_, i) => ({ title: `节${i}` }))
    const spec = buildPaperDiagram({
      question: '', methods: [], conclusions: [], limitations: [], outline,
    })
    expect(spec.nodes.length).toBeLessThanOrEqual(40)
  })
})

