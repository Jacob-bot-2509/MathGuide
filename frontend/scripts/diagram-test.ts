/** 图解协议:白名单、上限、消息锚点分段。 */
/* eslint-disable */
declare const process: { exit(code: number): void }

import {
  parseDiagramEvent,
  parseDiagramSpec,
  splitMessageBlocks,
  type DiagramBlock,
} from '../src/utils/diagramSpec'

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

if (failed.length) {
  console.error('图解协议自测失败:')
  for (const line of failed) console.error(' -', line)
  process.exit(1)
}
console.log(`图解协议自测:${passed}/${passed} 通过`)
