/** 图解协议:白名单、上限、消息锚点分段。 */
/* eslint-disable */
declare const process: { exit(code: number): void }

import {
  parseDiagramEvent,
  parseDiagramSpec,
  splitMessageBlocks,
  type DiagramBlock,
  type DiagramSpec,
} from '../src/utils/diagramSpec'
import { layoutFlow, layoutRelation, layoutTree } from '../src/utils/diagramLayout'

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

const relationSpec: DiagramSpec = {
  type: 'relation', nodes: [
    { id: 'x', label: '概念 X' }, { id: 'y', label: '概念 Y' },
  ], edges: [{ from: 'x', to: 'y' }], shapes: [], annotations: [],
}
const relationLayout = layoutRelation(relationSpec)
check('关系图节点有限坐标', relationLayout.nodes.every((n) =>
  Number.isFinite(n.x) && Number.isFinite(n.y)))
check('关系图不重叠', relationLayout.nodes[0].x !== relationLayout.nodes[1].x
  || relationLayout.nodes[0].y !== relationLayout.nodes[1].y)

const flowSpec: DiagramSpec = {
  type: 'flow', nodes: [
    { id: 's1', label: '第一步' }, { id: 's2', label: '第二步' },
  ], edges: [{ from: 's1', to: 's2' }], shapes: [], annotations: [],
}
const flow = layoutFlow(flowSpec)
check('流程图顺序', flow.nodes[0].x < flow.nodes[1].x
  || flow.nodes[0].y < flow.nodes[1].y)
check('流程图边完整', flow.edges.length === 1)

if (failed.length) {
  console.error('图解协议自测失败:')
  for (const line of failed) console.error(' -', line)
  process.exit(1)
}
console.log(`图解协议自测:${passed}/${passed} 通过`)
