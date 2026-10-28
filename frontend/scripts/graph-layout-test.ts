/**
 * 知识图谱分层布局自测(纯函数,esbuild 打包后 node 执行)。
 *
 * 覆盖:链式层级、菱形收敛、多根节点、未知前置、成环兜底与画布尺寸。
 */
/* eslint-disable */
declare const process: { exit(code: number): void }

import { LEVEL_GAP, MARGIN, NODE_GAP, layoutGraph } from '../src/utils/graphLayout'

let passed = 0
const failed: string[] = []
function check(name: string, ok: boolean, detail = '') {
  if (ok) passed++
  else failed.push(`${name}${detail ? `: ${detail}` : ''}`)
}

const chain = layoutGraph([
  { id: 'a' },
  { id: 'b', prerequisites: ['a'] },
  { id: 'c', prerequisites: ['b'] },
])
check('链式层级 a/b/c', chain.positions.a.level === 0
  && chain.positions.b.level === 1
  && chain.positions.c.level === 2)
check('三列同高', chain.positions.a.y === MARGIN
  && chain.positions.b.y === MARGIN
  && chain.positions.c.y === MARGIN)
check('链式宽度', chain.width === MARGIN * 2 + 2 * LEVEL_GAP,
  `${chain.width}`)
check('链式高度只剩单个节点高', chain.height === MARGIN * 2)

const diamond = layoutGraph([
  { id: 'a' },
  { id: 'b', prerequisites: ['a'] },
  { id: 'c', prerequisites: ['a'] },
  { id: 'd', prerequisites: ['b', 'c'] },
])
check('菱形层级', diamond.positions.a.level === 0
  && diamond.positions.b.level === 1
  && diamond.positions.c.level === 1
  && diamond.positions.d.level === 2)
check('同层纵向错开', diamond.positions.b.y !== diamond.positions.c.y)
check('同层纵距', Math.abs(diamond.positions.b.y - diamond.positions.c.y) === NODE_GAP)

const roots = layoutGraph([{ id: 'x' }, { id: 'y' }])
check('多根同层', roots.positions.x.level === 0 && roots.positions.y.level === 0)
check('多根纵向排列', roots.positions.x.y !== roots.positions.y.y)

const unknown = layoutGraph([
  { id: 'a' },
  { id: 'b', prerequisites: ['ghost'] },
])
check('未知前置按根处理', unknown.positions.b.level === 0)

const cycle = layoutGraph([
  { id: 'a', prerequisites: ['b'] },
  { id: 'b', prerequisites: ['a'] },
])
check('成环不死循环且全部有位置',
  Boolean(cycle.positions.a) && Boolean(cycle.positions.b))

console.log(`\n图谱布局自测:${passed}/${passed + failed.length} 通过`)
for (const item of failed) console.log(`✗ ${item}`)
if (failed.length) process.exit(1)
