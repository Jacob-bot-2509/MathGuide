/**
 * 相关论文按钮:结果区只在「全网文献」模式渲染。
 * 守护两点接线:点击后必须切模式;滚动前必须等 DOM 更新。
 */
import { readFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const here = dirname(fileURLToPath(import.meta.url))
const source = readFileSync(
  resolve(here, '../src/views/ResearchSearchView.vue'),
  'utf8',
)

let passed = 0
const failed = []
function check(name, ok, detail = '') {
  if (ok) passed++
  else failed.push(`${name}${detail ? `: ${detail}` : ''}`)
}

const start = source.indexOf('async function findRelated')
const end = source.indexOf('\n}', start)
check('找到 findRelated', start >= 0 && end > start)
const handler = start >= 0 && end > start ? source.slice(start, end) : ''

check(
  '相关检索切到全网文献',
  handler.includes("setSearchMode('web')"),
  handler.slice(0, 80),
)
check(
  '滚动前等待渲染',
  handler.includes('await nextTick()')
    && handler.indexOf('await nextTick()') < handler.indexOf("querySelector('.lit')"),
)

if (failed.length) {
  console.error(`✗ ${failed.length} 项失败`)
  for (const item of failed) console.error(`  - ${item}`)
  process.exit(1)
}
console.log(`✓ 相关论文接线 ${passed} 项通过`)
