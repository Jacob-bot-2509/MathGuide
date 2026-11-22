/**
 * 移动端适配护栏:把「不能回退」的视口规则变成可执行的检查。
 *
 * 这不是布局引擎,不能证明每台设备都好看;它只挡住几类一旦回退就会
 * 在手机上直接出硬问题的写法:
 *   - viewport 没有 viewport-fit=cover,safe-area 全部失效;
 *   - 声明了 100vh 却没有 100dvh 兜底,底部输入条会被 Safari 工具栏切掉;
 *   - 弹层 max-height 只用 vh,横竖屏切换后底部按钮不可达;
 *   - 用 100vw 做宽度,出现横向滚动条/被安全区裁切;
 *   - 误写成 50ddvh 这类无效值。
 *
 * 用法:node scripts/responsive-audit-test.mjs
 */
import { readdirSync, readFileSync } from 'node:fs'
import { dirname, join, relative } from 'node:path'
import { fileURLToPath } from 'node:url'

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..')
const failures = []
let checkedFiles = 0

function fail(file, line, message) {
  failures.push(`${relative(ROOT, file)}:${line}  ${message}`)
}

function read(path) {
  return readFileSync(join(ROOT, path), 'utf8')
}

/* 1. viewport:允许缩放,但必须让安全区生效 */
const html = read('index.html')
if (!/viewport-fit=cover/.test(html)) {
  failures.push('index.html  viewport 缺少 viewport-fit=cover')
}
if (/user-scalable=no|maximum-scale=1(?!\d)/.test(html)) {
  failures.push('index.html  viewport 禁止了页面缩放')
}

/* 2. 全局底座:动态视口与左右安全区 */
const base = read('src/styles/base.css')
for (const token of ['100dvh', 'safe-area-inset-left', 'safe-area-inset-right', 'overflow-wrap']) {
  if (!base.includes(token)) failures.push(`src/styles/base.css  缺少 ${token}`)
}

function walk(dir) {
  return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const full = join(dir, entry.name)
    return entry.isDirectory() ? walk(full) : [full]
  })
}

const files = walk(join(ROOT, 'src')).filter((file) => /\.(vue|css)$/.test(file))
for (const file of files) {
  checkedFiles++
  const lines = readFileSync(file, 'utf8').split(/\r?\n/)
  for (let index = 0; index < lines.length; index++) {
    const line = lines[index]
    if (line.includes('ddvh')) fail(file, index + 1, '出现无效单位 ddvh')

    // 去掉 dvh 后再找 vh,避免把 100dvh 当成 100vh
    const withoutDvh = line.replace(/dvh/g, '')
    const context = lines.slice(index + 1, index + 3).join('\n')

    if (/^\s*(?:height|min-height):\s*100vh;/.test(withoutDvh)) {
      if (!context.includes('100dvh')) {
        fail(file, index + 1, '100vh 后两行内缺少 100dvh 兜底')
      }
    }

    if (/^\s*max-height:\s*[^;]*vh/.test(withoutDvh)) {
      if (!context.includes('dvh')) {
        fail(file, index + 1, 'max-height 使用 vh 但缺少 dvh 兜底')
      }
    }

    if (/width:\s*100vw/.test(line)) {
      fail(file, index + 1, '不要用 100vw 做宽度,改用 100%/安全区')
    }
  }
}

if (failures.length) {
  console.error(`✗ 移动端适配护栏失败(${failures.length} 项)`)
  for (const item of failures) console.error(`  - ${item}`)
  process.exit(1)
}
console.log(`✓ 移动端适配护栏通过(${checkedFiles} 个样式源文件)`)
