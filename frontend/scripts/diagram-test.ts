/** 图解协议:白名单、上限、消息锚点分段。 */
/* eslint-disable */
declare const process: { exit(code: number): void }

import {
  appendDiagram,
  buildPaperDiagram,
  filterCollapsed,
  parseDiagramEvent,
  parseDiagramSpec,
  splitMessageBlocks,
  type DiagramBlock,
  type DiagramSpec,
} from '../src/utils/diagramSpec'
import { layoutFlow, layoutRelation, layoutTree } from '../src/utils/diagramLayout'
import { diagramSuppressed, needsDiagram } from '../src/utils/diagramIntent'
import {
  compileExpression,
  diagramFromGeoGebraXml,
} from '../src/utils/geogebraSpec'
import { diagramFromGeoGebra3DXml } from '../src/utils/geogebra3dSpec'
import {
  measureLabel,
  measureTextWidth,
  overlapArea,
  placeLabels,
  placeScreenLabels,
  shapeObstacleRects,
} from '../src/utils/diagramLabels'

let passed = 0
const failed: string[] = []
function check(name: string, ok: boolean, detail = '') {
  if (ok) passed++
  else failed.push(`${name}${detail ? `: ${detail}` : ''}`)
}

const relation = parseDiagramSpec({
  type: 'relation',
  nodes: [{ id: 'a', label: 'A' }, { id: 'b', label: 'B' }],
  edges: [{ from: 'a', to: 'b', label: '推出' }],
})
check('合法 relation', relation?.nodes?.length === 2)
check('schema 版本写入', relation?.schemaVersion === 1)
check('未来 schema 拒绝', parseDiagramSpec({
  schemaVersion: 2,
  type: 'relation',
  nodes: [{ id: 'a', label: 'A' }],
}) === null)
check('非法类型拒绝', parseDiagramSpec({ type: 'script' }) === null)
check('超限节点拒绝', parseDiagramSpec({
  type: 'relation',
  nodes: Array.from({ length: 41 }, (_, i) => ({ id: `n${i}`, label: `N${i}` })),
}) === null)
check('超限边拒绝', parseDiagramSpec({
  type: 'relation',
  nodes: [{ id: 'a', label: 'A' }],
  edges: Array.from({ length: 81 }, () => ({ from: 'a', to: 'a' })),
}) === null)
check('非法坐标拒绝', parseDiagramSpec({
  type: 'geometry2d',
  shapes: [{ kind: 'point', x: Number.NaN, y: 0 }],
}) === null)
check('无采样曲线不出空图', parseDiagramSpec({
  type: 'plot2d',
  shapes: [
    { kind: 'axis', from: [-1, 0], to: [1, 0] },
    { kind: 'curve', expr: 'x^2', domain: [-1, 1] },
  ],
}) === null)
check('占位标签被丢弃', parseDiagramSpec({
  type: 'geometry2d',
  shapes: [{ kind: 'point', x: 1, y: 2, label: 'DJJ' }],
})?.shapes[0]?.label === undefined)
const splitCurve = parseDiagramSpec({
  type: 'plot2d',
  shapes: [{
    kind: 'curve',
    points: [[-2, -0.5], [-1, -1], [1, 1], [2, 0.5]],
    segments: [[[-2, -0.5], [-1, -1]], [[1, 1], [2, 0.5]]],
  }],
})
const splitSegments = splitCurve?.shapes[0]?.segments as number[][][] | undefined
check('多段曲线保留分段', Array.isArray(splitSegments) && splitSegments.length === 2)
check('单点分段被丢弃', (() => {
  const parsed = parseDiagramSpec({
    type: 'plot2d',
    shapes: [{
      kind: 'curve',
      points: [[0, 0], [1, 1]],
      segments: [[[0, 0]], [[0, 0], [1, 1]]],
    }],
  })
  const segments = parsed?.shapes[0]?.segments as number[][][] | undefined
  return Array.isArray(segments) && segments.length === 1
})())

const blocks = splitMessageBlocks('第一段\n\n第二段', [{
  id: 'd1',
  anchorIndex: 6,
  spec: relation!,
}])
check('按锚点分段', blocks.length === 3 && blocks[1].kind === 'diagram')
check('锚点越界钳制', splitMessageBlocks('abc', [{
  id: 'd2',
  anchorIndex: 999,
  spec: relation!,
}]).length === 2)

const event = parseDiagramEvent({
  mg_event: 'diagram',
  requestId: 'r1',
  anchorId: 'd1',
  anchorIndex: 12,
  diagram: relation,
})
check('图解事件', event?.id === 'd1' && event?.anchorIndex === 12)
check('非法事件拒绝', parseDiagramEvent({ mg_event: 'diagram', diagram: { type: 'x' } }) === null)
const firstAppend = appendDiagram(undefined, event!)
const secondAppend = appendDiagram(firstAppend, event!)
check('图解去重', firstAppend.length === 1 && secondAppend.length === 1)
let capped = secondAppend
for (const id of ['d2', 'd3', 'd4', 'd5', 'd6', 'd7']) {
  capped = appendDiagram(capped, { ...event!, id })
}
check('单消息最多两张图', capped.length === 2)

// 两张图各 4500 点:第二张累计 9000 超过 8000 预算,必须拒绝。
const manyShapes = Array.from({ length: 45 }, (_, si) => ({
  kind: 'polygon',
  points: Array.from({ length: 100 }, (_, i) => [si, i]),
}))
const bigSpec = parseDiagramSpec({
  type: 'geometry2d',
  shapes: manyShapes,
})
let totalBudget = appendDiagram(undefined, { id: 'p1', anchorIndex: 0, spec: bigSpec! })
for (const id of ['p2', 'p3']) {
  totalBudget = appendDiagram(totalBudget, { id, anchorIndex: 1, spec: bigSpec! })
}
check('单消息总点数上限', totalBudget.length === 1)

const threeD = parseDiagramSpec({
  type: 'surface3d',
  shapes: [{
    kind: 'surface', expr: 'x^2+y^2', domain: [-1, 1], rows: 3, cols: 3,
    points: [[0, 0, 0], [0, 1, 1]],
  }],
  annotations: [{ x: 1, y: 1, z: 2, text: '最陡上升' }],
})
check('三维标注保留 z', threeD?.annotations[0]?.z === 2)
check('曲面网格保留行列', threeD?.shapes[0]?.rows === 3 && threeD?.shapes[0]?.cols === 3)

const treeSpec: DiagramSpec = {
  type: 'tree',
  nodes: [
    { id: 'root', label: '论文' },
    { id: 'a', label: '研究问题' },
    { id: 'b', label: '方法' },
  ],
  edges: [{ from: 'root', to: 'a' }, { from: 'root', to: 'b' }],
  shapes: [], annotations: [],
}
const tree = layoutTree(treeSpec)
check('树布局节点完整', tree.nodes.length === 3)
check('树布局父子顺序', tree.nodes[0].y < tree.nodes[1].y)
check('树布局尺寸有效', tree.width > 0 && tree.height > 0)
check('树布局边完整', tree.edges.length === 2)
const sharedTree: DiagramSpec = { type: 'tree', nodes: [], edges: [], shapes: [], annotations: [] }
for (let level = 0; level < 20; level++) {
  for (let column = 0; column < 2; column++) {
    const id = `${level}-${column}`
    sharedTree.nodes.push({ id, label: id })
    if (level > 0) for (let parent = 0; parent < 2; parent++) {
      sharedTree.edges.push({ from: `${level - 1}-${parent}`, to: id })
    }
  }
}
const sharedLayout = layoutTree(sharedTree)
check('共享子节点布局不重复', sharedLayout.nodes.length === 40
  && new Set(sharedLayout.nodes.map((node) => node.id)).size === 40)
const collapsedRoot = filterCollapsed(treeSpec, new Set(['root']))
check('折叠根节点只留根', collapsedRoot.nodes.length === 1
  && collapsedRoot.edges.length === 0)
const collapsedChild = filterCollapsed(treeSpec, new Set(['a']))
check('折叠子节点不影响兄弟', collapsedChild.nodes.length === 3
  && collapsedChild.edges.length === 2)

const relationSpec: DiagramSpec = {
  type: 'relation', nodes: [
    { id: 'x', label: '概念 X' }, { id: 'y', label: '概念 Y' },
  ], edges: [{ from: 'x', to: 'y' }], shapes: [], annotations: [],
}
const cyclicRelation: DiagramSpec = { ...relationSpec, edges: [
  { from: 'x', to: 'y' }, { from: 'y', to: 'x' },
] }
const collapsedCycle = filterCollapsed(cyclicRelation, new Set(['x']))
check('折叠环形关系保留所选节点', collapsedCycle.nodes.length === 1
  && collapsedCycle.nodes[0].id === 'x')
const relationLayout = layoutRelation(relationSpec)
check('关系图节点有限坐标', relationLayout.nodes.every((n) =>
  Number.isFinite(n.x) && Number.isFinite(n.y)))
check('关系图不重叠', relationLayout.nodes[0].x !== relationLayout.nodes[1].x
  || relationLayout.nodes[0].y !== relationLayout.nodes[1].y)

const conceptSpec: DiagramSpec = {
  type: 'tree',
  nodes: [
    { id: 'r1', label: '多元函数在一点的局部性质' },
    { id: 'r2', label: '反例:xy/(x²+y²) 偏导存在但不可微且不连续' },
    { id: 'a', label: '偏导数连续' },
    { id: 'b', label: '可微' },
    { id: 'c', label: '连续' },
    { id: 'd', label: '偏导数存在' },
  ],
  edges: [
    { from: 'r1', to: 'a' }, { from: 'r1', to: 'b' },
    { from: 'r2', to: 'c' }, { from: 'r2', to: 'd' },
    { from: 'a', to: 'b' }, { from: 'b', to: 'c' },
    { from: 'b', to: 'd' },
  ],
  shapes: [], annotations: [],
}
const conceptLayout = layoutTree(conceptSpec)
check('概念图节点不重叠', conceptLayout.nodes.every((node, index) => (
  conceptLayout.nodes.every((other, otherIndex) => index === otherIndex
    || overlapArea(
      { x: node.x, y: node.y, w: node.w, h: node.h },
      { x: other.x, y: other.y, w: other.w, h: other.h },
    ) === 0)
)))

const flowSpec: DiagramSpec = {
  type: 'flow', nodes: [
    { id: 's1', label: '第一步' }, { id: 's2', label: '第二步' },
  ], edges: [{ from: 's1', to: 's2' }], shapes: [], annotations: [],
}
const flow = layoutFlow(flowSpec)
check('流程图顺序', flow.nodes[0].x < flow.nodes[1].x
  || flow.nodes[0].y < flow.nodes[1].y)
check('流程图边完整', flow.edges.length === 1)

const branchSpec: DiagramSpec = {
  type: 'flow', nodes: [
    { id: 'a', label: '可微' },
    { id: 'b', label: '连续' },
    { id: 'c', label: '偏导数存在' },
  ], edges: [{ from: 'a', to: 'b' }, { from: 'a', to: 'c' }],
  shapes: [], annotations: [],
}
const branch = layoutFlow(branchSpec)
const nodeB = branch.nodes.find((n) => n.id === 'b')!
const nodeC = branch.nodes.find((n) => n.id === 'c')!
check('分支流程同层并排', nodeB.y === nodeC.y && nodeB.x !== nodeC.x)

const paper = buildPaperDiagram({
  question: '如何提高催化效率?',
  methods: ['方法 A', '方法 B'],
  conclusions: ['结论 A'],
  limitations: ['样本有限'],
  outline: [{ title: '第一章', children: [{ title: '1.1 背景', children: [] }] }],
}, '测试论文')
check('论文脑图根节点', paper.nodes[0]?.label === '测试论文')
check('论文脑图分支', paper.nodes.some((n) => n.label === '研究问题')
  && paper.nodes.some((n) => n.label === '方法'))
check('论文脑图节点上限', paper.nodes.length <= 40 && paper.edges.length > 0)

// 标注布局:同一锚点的多条说明必须分散到不同方位,且不能压住主体。
const clusteredFigure = { x: 100, y: 100, w: 220, h: 180 }
const clustered = placeLabels([
  {
    id: 'note-a', text: '梯度方向', anchorX: 210, anchorY: 190,
    figure: clusteredFigure, figureWeight: 2.5, priority: 3,
  },
  {
    id: 'note-b', text: '最陡上升方向', anchorX: 212, anchorY: 192,
    figure: clusteredFigure, figureWeight: 2.5, priority: 3,
  },
  {
    id: 'note-c', text: '等高线', anchorX: 208, anchorY: 188,
    figure: clusteredFigure, figureWeight: 2.5, priority: 3,
  },
], [], { x: -300, y: -300, w: 900, h: 900 })
check('标注互不重叠', clustered.every((label, index) => clustered.every(
  (other, otherIndex) => index === otherIndex || overlapArea(label, other) === 0,
)))
check('标注分散到不同方位', new Set(clustered.map((label) => label.side)).size >= 2)
check('标注避开主体包围盒', clustered.every(
  (label) => overlapArea(label, clusteredFigure) === 0,
))

const curveObstacles = shapeObstacleRects([{
  kind: 'curve', points: [[0, 0], [25, 35], [50, 45], [75, 30], [100, 0]],
}])
const curveNotes = placeLabels([{
  id: 'curve-note', text: '切点', anchorX: 50, anchorY: 45,
  figure: { x: 0, y: 0, w: 100, h: 45 }, figureWeight: 2.5,
}], curveObstacles, { x: -100, y: -100, w: 300, h: 260 })
check('标注避开曲线本身', curveNotes.every((label) => (
  curveObstacles.every((obstacle) => overlapArea(label, obstacle) === 0)
)))

// 节点图边标签:不能压节点,也不能互相叠。
const labeledFlowSpec: DiagramSpec = {
  type: 'flow', nodes: [
    { id: 'a', label: '可微' },
    { id: 'b', label: '偏导数连续' },
    { id: 'c', label: '方向导数存在' },
    { id: 'd', label: '连续' },
  ],
  edges: [
    { from: 'a', to: 'b', label: '推出' },
    { from: 'a', to: 'c', label: '推出' },
    { from: 'a', to: 'd', label: '推出' },
    { from: 'b', to: 'd', label: '蕴含' },
  ],
  shapes: [], annotations: [],
}
const labeledFlow = layoutFlow(labeledFlowSpec)
const nodeRects = labeledFlow.nodes.map((node) => ({
  x: node.x, y: node.y, w: node.w, h: node.h,
}))
const edgeRects = labeledFlow.edges
  .filter((edge) => edge.label && edge.labelX !== undefined && edge.labelY !== undefined)
  .map((edge) => {
    const measured = measureLabel({
      id: `${edge.from}-${edge.to}`, text: edge.label!,
      anchorX: 0, anchorY: 0, fontSize: 9, maxWidth: 110, maxLines: 2,
    })
    return {
      x: edge.labelX!, y: edge.labelY! - measured.fontSize,
      w: measured.w, h: measured.h,
    }
  })
check('边标签数量完整', edgeRects.length === labeledFlow.edges.length)
check('边标签不压节点', edgeRects.every((label) => (
  nodeRects.every((node) => overlapArea(label, node) === 0)
)))
check('边标签互不重叠', edgeRects.every((label, index) => edgeRects.every(
  (other, otherIndex) => index === otherIndex || overlapArea(label, other) === 0,
)))

// 3D 屏幕空间标注:围绕主体外围排布,互不重叠。
const screenFigure = { x: 160, y: 110, w: 220, h: 180 }
const screenPlaced = placeScreenLabels([
  {
    id: 's1', anchorX: 270, anchorY: 200, width: 72, height: 20,
    priority: 3, avoidRect: screenFigure, avoidWeight: 3,
  },
  {
    id: 's2', anchorX: 272, anchorY: 202, width: 60, height: 20,
    priority: 3, avoidRect: screenFigure, avoidWeight: 3,
  },
  {
    id: 's3', anchorX: 268, anchorY: 198, width: 48, height: 20,
    priority: 3, avoidRect: screenFigure, avoidWeight: 3,
  },
], { width: 720, height: 520 })
check('3D 标注互不重叠', screenPlaced.every((label, index) => screenPlaced.every(
  (other, otherIndex) => index === otherIndex || overlapArea(label, other) === 0,
)))
check('3D 标注避开主体', screenPlaced.every(
  (label) => overlapArea(label, screenFigure) === 0,
))

const wrapped = measureLabel({
  id: 'wrap', text: '这是一个需要换行显示的较长标注说明文字',
  anchorX: 0, anchorY: 0, fontSize: 10, maxWidth: 60, maxLines: 2,
})
check('标注按宽度换行', wrapped.lines.length <= 2
  && wrapped.lines.every((line) => measureTextWidth(line, 10) <= 60))

// 用户明确说“不要画图”时,前端不能在回答结束后自行补图。
const noDrawHistory = [{ role: 'user', content: '先不要画图，等我讲完' }]
check('本轮不画图时禁用自动补图', !needsDiagram('先不要画图，继续讲讲为什么切线斜率等于导数'))
check('历史里的不画图指令持续生效', !needsDiagram('继续讲这个定理', noDrawHistory))
check('恢复画图后允许补图', needsDiagram('现在画个三维图', noDrawHistory))
check('用三维图也算恢复画图', needsDiagram('用三维图讲讲梯度', noDrawHistory))
check('不画思维导图但改画三维图不算停止', !diagramSuppressed('不要画思维导图，画三维图'))
check('别画了也算停止', diagramSuppressed('别画了，用文字说'))

// GeoGebra 隐藏内核:只解析构造结果,最终仍转成我们的 DiagramSpec。
const square = compileExpression('x^2')
check('GeoGebra 表达式平方', square?.(3) === 9)
const trig = compileExpression('sin(pi/2)')
check('GeoGebra 表达式三角函数', trig !== null && Math.abs(trig(0) - 1) < 1e-9)
const implicit = compileExpression('2x+1')
check('GeoGebra 表达式隐式乘法', implicit?.(2) === 5)
check('GeoGebra 表达式拒绝命令注入', compileExpression('Execute("x")') === null)

const ggbXml = `<geogebra><construction>
<expression label="f" exp="f(x) = x^(2)" type="function"/>
<element type="function" label="f"><show object="true"/></element>
<expression label="A" exp="(1, 1)" type="point"/>
<element type="point" label="A"><coords x="1" y="1" z="1"/></element>
<expression label="B" exp="(2, 3)" type="point"/>
<element type="point" label="B"><coords x="2" y="3" z="1"/></element>
<expression label="C" exp="(3, 1)" type="point"/>
<element type="point" label="C"><coords x="3" y="1" z="1"/></element>
<command name="Tangent"><input a0="A" a1="f"/><output a0="t"/></command>
<element type="line" label="t"><coords x="-2" y="1" z="1"/></element>
<command name="Segment"><input a0="A" a1="B"/><output a0="s"/></command>
<element type="segment" label="s"><coords x="-2" y="1" z="1"/></element>
<command name="Circle"><input a0="(0, 0)" a1="2"/><output a0="c"/></command>
<element type="conic" label="c">
  <matrix A0="1" A1="1" A2="-4" A3="0" A4="0" A5="0"/>
</element>
<command name="Polygon">
  <input a0="A" a1="B" a2="C"/>
  <output a0="p" a1="c_1" a2="a" a3="b"/>
</command>
<element type="polygon" label="p"><show object="true"/></element>
<element type="segment" label="c_1"><coords x="-2" y="1" z="1"/></element>
<element type="segment" label="a"><coords x="2" y="1" z="-7"/></element>
<element type="segment" label="b"><coords x="0" y="-2" z="2"/></element>
</construction></geogebra>`
const ggbSpec = diagramFromGeoGebraXml(ggbXml)
check('GeoGebra XML 转为自绘图解', ggbSpec?.type === 'plot2d'
  && ggbSpec.shapes.some((shape) => shape.kind === 'curve')
  && ggbSpec.shapes.some((shape) => shape.kind === 'point')
  && ggbSpec.shapes.some((shape) => shape.kind === 'circle')
  && ggbSpec.shapes.some((shape) => shape.kind === 'polygon'))
check('GeoGebra 切线转成短切线', ggbSpec?.shapes.some(
  (shape) => shape.kind === 'segment' && shape.label === '切线',
) === true)
check('GeoGebra 多边形不重复画辅助边', ggbSpec?.shapes.filter(
  (shape) => shape.kind === 'segment' && !shape.label,
).length === 1)

const ggb3dXml = `<geogebra><construction>
<expression label="A" exp="(1, 0, 0)" type="point"/>
<element type="point3d" label="A"><coords x="1" y="0" z="0" w="1"/></element>
<expression label="B" exp="(0, 1, 0)" type="point"/>
<element type="point3d" label="B"><coords x="0" y="1" z="0" w="1"/></element>
<expression label="C" exp="(0, 0, 1)" type="point"/>
<element type="point3d" label="C"><coords x="0" y="0" z="1" w="1"/></element>
<command name="Segment"><input a0="A" a1="B"/><output a0="s"/></command>
<element type="segment3d" label="s"/>
<command name="Plane"><input a0="A" a1="B" a2="C"/><output a0="p"/></command>
<element type="plane3d" label="p"><coords x="1" y="1" z="1" w="-1"/></element>
<command name="Sphere"><input a0="(0, 0, 0)" a1="2"/><output a0="S"/></command>
<element type="quadric" label="S"/>
<command name="Polygon">
  <input a0="A" a1="B" a2="C"/>
  <output a0="q" a1="c" a2="a" a3="b"/>
</command>
<element type="polygon3d" label="q"/>
<element type="segment3d" label="c"/>
<element type="segment3d" label="a"/>
<element type="segment3d" label="b"/>
<command name="Surface">
  <input a0="u" a1="v" a2="u^(2) + v^(2)" a3="u" a4="-1" a5="1" a6="v" a7="-1" a8="1"/>
  <output a0="surf"/>
</command>
<element type="surfacecartesian3d" label="surf"/>
</construction></geogebra>`
const ggb3dSpec = diagramFromGeoGebra3DXml(ggb3dXml)
check('GeoGebra 3D XML 转为自绘三维图', ggb3dSpec?.type === 'geometry3d'
  && ggb3dSpec.shapes.some((shape) => shape.kind === 'point')
  && ggb3dSpec.shapes.some((shape) => shape.kind === 'segment')
  && ggb3dSpec.shapes.some((shape) => shape.kind === 'plane')
  && ggb3dSpec.shapes.some((shape) => shape.kind === 'sphere')
  && ggb3dSpec.shapes.some((shape) => shape.kind === 'polygon'))
check('GeoGebra 3D 曲面不硬转网格', !ggb3dSpec?.shapes.some(
  (shape) => shape.kind === 'surface',
))
check('GeoGebra 3D 多边形辅助边去重', ggb3dSpec?.shapes.filter(
  (shape) => shape.kind === 'segment',
).length === 1)


// 图在文字上方时,正文里的“如下图”必须改成“如上图”;反之亦然。
const afterFigure = splitMessageBlocks('前言\n\n如下图，曲线有两支。', [{
  id: 'd3', anchorIndex: 3, spec: relation!,
}])
const afterFigureText = afterFigure[2]
check('图在上方:下图改为上图',
  afterFigureText.kind === 'text' && afterFigureText.text.includes('如上图'),
  afterFigureText.kind === 'text' ? afterFigureText.text : '')

const beforeFigure = splitMessageBlocks('如上图所示，曲线有两支。\n\n后文', [{
  id: 'd4', anchorIndex: 12, spec: relation!,
}])
const beforeFigureText = beforeFigure[0]
check('图在下方:上图改为下图',
  beforeFigureText.kind === 'text' && beforeFigureText.text.includes('如下图'),
  beforeFigureText.kind === 'text' ? beforeFigureText.text : '')

// GeoGebra 命令 spec:白名单、上限、类型
const geo2d = parseDiagramSpec({
  type: 'geogebra2d',
  title: '切线',
  commands: ['f(x)=x^2', 'A=(1,1)', 't=Tangent(A,f)'],
})
check('GeoGebra 2D spec 可解析',
  geo2d?.type === 'geogebra2d' && geo2d?.commands?.length === 3)
check('GeoGebra 危险命令拒绝',
  parseDiagramSpec({ type: 'geogebra2d', commands: ['Execute("x")'] }) === null)
check('GeoGebra 命令数量上限',
  parseDiagramSpec({
    type: 'geogebra2d',
    commands: Array.from({ length: 31 }, () => 'A=(1,1)'),
  }) === null)
check('GeoGebra 3D 曲面命令可解析',
  parseDiagramSpec({
    type: 'geogebra3d',
    commands: ['s=Surface(u,v,u^2+v^2,u,-2,2,v,-2,2)'],
  })?.type === 'geogebra3d')

if (failed.length) {
  console.error('图解协议自测失败:')
  for (const line of failed) console.error(' -', line)
  process.exit(1)
}
console.log(`图解协议自测:${passed}/${passed} 通过`)

