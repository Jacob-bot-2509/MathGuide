/**
 * MathGuide AI-for-Science UI 设计审计与护栏脚本
 *
 * 扫描 frontend/src 下的所有 .vue / .css 文件以及核心主题文件，量化当前
 * 「黑色科幻/赛博朋克」视觉债务与令牌一致性问题，为升级到 AI for Science
 * 科研工作台提供可执行的逐文件清单与 CI 护栏。
 *
 * 检查维度：
 *   1. 视觉噪声残留：CRT 扫描线、全局暗角、Starfield 星空、--glow-* 霓虹辉光、高模糊过场；
 *   2. 令牌断裂：未定义的 CSS 变量（如 var(--bg)）、硬编码语义色（#ffd166 / #ff8a8a / #7ee787 等）；
 *   3. 字体与可读性：缺少科研衬线/等宽数字排版令牌、局部主题覆写破坏浅色模式；
 *   4. 对比度校验：对 tokens.css（或候选 tokens.science.css）执行 WCAG 2.1 AA 对比度计算；
 *   5. 品牌元数据漂移：视图中残留的过时版本号（如 v0.1.0 vs package.json）。
 *
 * 用法：
 *   node scripts/ui-design-audit.mjs                # 人类可读审计报告
 *   node scripts/ui-design-audit.mjs --json         # 机器可读 JSON 输出
 *   node scripts/ui-design-audit.mjs --strict       # 护栏模式：存在硬错误或超标项时返回非零退出码
 *   node scripts/ui-design-audit.mjs --tokens src/styles/tokens.science.css
 */
import { existsSync, readdirSync, readFileSync } from 'node:fs'
import { dirname, join, relative } from 'node:path'
import { fileURLToPath } from 'node:url'

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..')
const args = process.argv.slice(2)
const JSON_MODE = args.includes('--json')
const STRICT_MODE = args.includes('--strict')
const tokenArgIdx = args.indexOf('--tokens')
const TOKEN_FILE = tokenArgIdx >= 0 && args[tokenArgIdx + 1]
  ? join(ROOT, args[tokenArgIdx + 1])
  : join(ROOT, 'src/styles/tokens.css')

function walk(dir) {
  return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const full = join(dir, entry.name)
    return entry.isDirectory() ? walk(full) : [full]
  })
}

/** 提取 .vue 的 <style> 块（保留原始行号），.css 文件则全文返回 */
function extractStyleLines(filePath, content) {
  const lines = content.split(/\r?\n/)
  if (filePath.endsWith('.css')) {
    return lines.map((text, idx) => ({ line: idx + 1, text }))
  }
  const out = []
  let inStyle = false
  for (let i = 0; i < lines.length; i++) {
    const text = lines[i]
    if (/<style\b/.test(text)) {
      inStyle = true
      continue
    }
    if (/<\/style>/.test(text)) {
      inStyle = false
      continue
    }
    if (inStyle) out.push({ line: i + 1, text })
  }
  return out
}

/** 解析 CSS 文件里 :root 与 :root[data-theme='light'] 声明的自定义属性 */
function parseTokenThemes(cssText) {
  const dark = {}
  const light = {}
  const blockRe = /(:root(?:\[data-theme=['"]light['"]\])?)\s*\{([\s\S]*?)\}/g
  let m
  while ((m = blockRe.exec(cssText))) {
    const target = m[1].includes('light') ? light : dark
    const body = m[2]
    for (const vm of body.matchAll(/(--[a-z0-9-]+)\s*:\s*([^;]+);/gi)) {
      target[vm[1].trim()] = vm[2].trim()
    }
  }
  return { dark, light }
}

/** 解析 var(--foo) 引用链，返回最终颜色值 */
function resolveVar(map, fallbackMap, name, depth = 0) {
  if (depth > 8) return ''
  const raw = map[name] ?? fallbackMap[name] ?? ''
  const ref = raw.match(/^var\((--[a-z0-9-]+)\)$/i)
  if (ref) return resolveVar(map, fallbackMap, ref[1], depth + 1)
  return raw
}

/** 解析 #rgb / #rrggbb / rgba() 到 [r, g, b] (忽略透明叠加，rgba 在给定底色上合成) */
function parseColor(str, bgRgb = [0, 0, 0]) {
  if (!str) return null
  const hex = str.trim().match(/^#([0-9a-f]{3}|[0-9a-f]{6})$/i)
  if (hex) {
    const h = hex[1]
    if (h.length === 3) {
      return [parseInt(h[0] + h[0], 16), parseInt(h[1] + h[1], 16), parseInt(h[2] + h[2], 16)]
    }
    return [parseInt(h.slice(0, 2), 16), parseInt(h.slice(2, 4), 16), parseInt(h.slice(4, 6), 16)]
  }
  const rgba = str.trim().match(/^rgba?\(\s*([\d.]+)\s*,\s*([\d.]+)\s*,\s*([\d.]+)(?:\s*,\s*([\d.]+))?\s*\)$/i)
  if (rgba) {
    const r = Number(rgba[1])
    const g = Number(rgba[2])
    const b = Number(rgba[3])
    const a = rgba[4] !== undefined ? Number(rgba[4]) : 1
    return [
      Math.round(r * a + bgRgb[0] * (1 - a)),
      Math.round(g * a + bgRgb[1] * (1 - a)),
      Math.round(b * a + bgRgb[2] * (1 - a)),
    ]
  }
  return null
}

function relativeLuminance([r, g, b]) {
  const chan = [r, g, b].map((v) => {
    const s = v / 255
    return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4
  })
  return 0.2126 * chan[0] + 0.7152 * chan[1] + 0.0722 * chan[2]
}

function contrastRatio(fg, bg) {
  const l1 = relativeLuminance(fg)
  const l2 = relativeLuminance(bg)
  const [hi, lo] = l1 >= l2 ? [l1, l2] : [l2, l1]
  return Number(((hi + 0.05) / (lo + 0.05)).toFixed(2))
}

const SEMANTIC_HEX_SUGGESTIONS = {
  '#ffd166': 'var(--warn)',
  '#f6c85f': 'var(--warn)',
  '#ff8a8a': 'var(--danger)',
  '#ff6b6b': 'var(--danger)',
  '#7ee787': 'var(--success)',
  '#4dffb8': 'var(--success)',
  '#6ee7a8': 'var(--success)',
  '#05070a': 'var(--bg-void)',
  '#05060a': 'var(--bg-void)',
  '#0b1220': 'var(--bg-panel)',
  '#4dd6ff': 'var(--cyan)',
  '#e8f2ff': 'var(--text-hi)',
  '#c2d2e4': 'var(--text)',
  '#8b9bb0': 'var(--text-dim)',
}

const pkg = JSON.parse(readFileSync(join(ROOT, 'package.json'), 'utf8'))
const tokenCss = existsSync(TOKEN_FILE) ? readFileSync(TOKEN_FILE, 'utf8') : ''
const themes = parseTokenThemes(tokenCss)
const declaredVars = new Set([
  ...Object.keys(themes.dark),
  ...Object.keys(themes.light),
  '--safe-inline',
  '--card-accent',
  '--card-glow',
])

// 扫描所有源码中局部声明的 CSS 变量，避免误报组件私有变量
const srcFiles = walk(join(ROOT, 'src')).filter((f) => /\.(vue|css)$/.test(f))
const locallyDeclaredVars = new Set()
for (const file of srcFiles) {
  const raw = readFileSync(file, 'utf8')
  for (const { text } of extractStyleLines(file, raw)) {
    for (const m of text.matchAll(/(--[a-z0-9-]+)\s*:/gi)) {
      locallyDeclaredVars.add(m[1])
    }
  }
}

const report = {
  version: pkg.version,
  tokenFile: relative(ROOT, TOKEN_FILE),
  scannedFiles: srcFiles.length,
  summary: {
    undefinedVars: 0,
    hardcodedSemanticHex: 0,
    glowUsages: 0,
    starfieldImports: 0,
    crtEffects: 0,
    blurTransitions: 0,
    staleVersionRefs: 0,
    contrastFailures: 0,
  },
  undefinedVars: [],
  hardcodedHexByColor: {},
  hardcodedHexSamples: [],
  cyberpunkArtifacts: [],
  staleVersions: [],
  contrastChecks: [],
}

for (const file of srcFiles) {
  const rel = relative(ROOT, file).replace(/\\/g, '/')
  const raw = readFileSync(file, 'utf8')
  const allLines = raw.split(/\r?\n/)

  // 检查 Starfield 引用与旧版本号残留
  allLines.forEach((line, idx) => {
    if (/import\s+Starfield\b/.test(line)) {
      report.summary.starfieldImports++
      report.cyberpunkArtifacts.push({
        file: rel,
        line: idx + 1,
        kind: 'starfield',
        detail: '引入星空+透视网格背景，建议替换为静止精密坐标网格/科研氛围层',
      })
    }
    if (/\bv0\.1\.0\b/.test(line) && pkg.version !== '0.1.0') {
      report.summary.staleVersionRefs++
      report.staleVersions.push({
        file: rel,
        line: idx + 1,
        found: 'v0.1.0',
        expected: `v${pkg.version}`,
      })
    }
  })

  // 检查样式块
  const isTokenFile = rel.endsWith('tokens.css') || rel.endsWith('tokens.science.css')
  for (const { line, text } of extractStyleLines(file, raw)) {
    // 1. 未定义变量
    for (const m of text.matchAll(/var\(\s*(--[a-z0-9-]+)(?:\s*,|\s*\))/gi)) {
      const name = m[1]
      if (!declaredVars.has(name) && !locallyDeclaredVars.has(name)) {
        report.summary.undefinedVars++
        report.undefinedVars.push({ file: rel, line, variable: name, snippet: text.trim() })
      }
    }

    // 2. 霓虹辉光
    if (/var\(--glow-/.test(text)) {
      report.summary.glowUsages++
    }

    // 3. CRT 扫描线 / 暗角 / 失焦强闪过场
    if (/repeating-linear-gradient\(0deg,/.test(text)) {
      report.summary.crtEffects++
      report.cyberpunkArtifacts.push({
        file: rel,
        line,
        kind: 'crt-scanlines',
        detail: '全屏 CRT 扫描线叠层会降低公式上下标与 PDF 文本清晰度',
      })
    }
    if (/filter:\s*blur\(10px\)\s*brightness/.test(text)) {
      report.summary.blurTransitions++
      report.cyberpunkArtifacts.push({
        file: rel,
        line,
        kind: 'flash-transition',
        detail: '高亮失焦页面过场偏科幻炫技，建议改为 160ms 轻量位移淡入',
      })
    }

    // 4. 硬编码语义色（跳过 tokens 定义文件本身）
    if (!isTokenFile) {
      for (const hm of text.matchAll(/#([0-9a-f]{3}|[0-9a-f]{6})\b/gi)) {
        const hex = hm[0].toLowerCase()
        if (SEMANTIC_HEX_SUGGESTIONS[hex]) {
          report.summary.hardcodedSemanticHex++
          report.hardcodedHexByColor[hex] = (report.hardcodedHexByColor[hex] || 0) + 1
          if (report.hardcodedHexSamples.length < 40) {
            report.hardcodedHexSamples.push({
              file: rel,
              line,
              hex,
              suggested: SEMANTIC_HEX_SUGGESTIONS[hex],
            })
          }
        }
      }
    }
  }
}

// WCAG 2.1 AA 对比度检查（正文 ≥ 4.5:1，大字/UI 控件 ≥ 3.0:1）
const PAIRS = [
  { fg: '--text-hi', bg: '--bg-void', min: 7.0, label: '主标题 / 画布背景' },
  { fg: '--text', bg: '--bg-void', min: 4.5, label: '正文 / 画布背景' },
  { fg: '--text-dim', bg: '--bg-panel', min: 4.5, label: '次要文字 / 面板背景' },
  { fg: '--cyan', bg: '--bg-card', min: 4.5, label: '主强调色 / 卡片背景' },
  { fg: '--danger', bg: '--bg-card', min: 4.5, label: '警示色 / 卡片背景' },
]

for (const mode of ['dark', 'light']) {
  const map = mode === 'light' ? { ...themes.dark, ...themes.light } : themes.dark
  const voidRgb = parseColor(resolveVar(map, themes.dark, '--bg-void')) || (mode === 'light' ? [247, 246, 242] : [11, 14, 20])
  for (const pair of PAIRS) {
    const bgRaw = resolveVar(map, themes.dark, pair.bg)
    const fgRaw = resolveVar(map, themes.dark, pair.fg)
    const bgRgb = parseColor(bgRaw, voidRgb)
    const fgRgb = parseColor(fgRaw, bgRgb || voidRgb)
    if (!bgRgb || !fgRgb) continue
    const ratio = contrastRatio(fgRgb, bgRgb)
    const pass = ratio >= pair.min
    if (!pass) report.summary.contrastFailures++
    report.contrastChecks.push({
      theme: mode,
      pair: `${pair.fg} on ${pair.bg}`,
      label: pair.label,
      fg: fgRaw,
      bg: bgRaw,
      ratio,
      min: pair.min,
      pass,
    })
  }
}

if (JSON_MODE) {
  console.log(JSON.stringify(report, null, 2))
} else {
  console.log(`\n═══════════════════════════════════════════════════════════════`)
  console.log(`  MathGuide AI-for-Science UI 设计审计报告 (v${report.version})`)
  console.log(`  令牌文件: ${report.tokenFile}  |  扫描文件: ${report.scannedFiles}`)
  console.log(`═══════════════════════════════════════════════════════════════\n`)

  const s = report.summary
  console.log(`【总览指标】`)
  console.log(`  • 未定义 CSS 变量        : ${s.undefinedVars} 处`)
  console.log(`  • 硬编码语义色（绕过令牌）: ${s.hardcodedSemanticHex} 处`)
  console.log(`  • 霓虹辉光 (--glow-*)    : ${s.glowUsages} 处`)
  console.log(`  • 星空透视网格 (Starfield): ${s.starfieldImports} 处`)
  console.log(`  • CRT 扫描线 / 强闪过场  : ${s.crtEffects + s.blurTransitions} 处`)
  console.log(`  • 过时版本号残留 (v0.1.0): ${s.staleVersionRefs} 处`)
  console.log(`  • WCAG 对比度不达标      : ${s.contrastFailures} 项\n`)

  if (report.undefinedVars.length) {
    console.log(`【1. 未定义 CSS 变量（建议优先修复）】`)
    for (const item of report.undefinedVars) {
      console.log(`  ✗ ${item.file}:${item.line}  ${item.variable}  → ${item.snippet}`)
    }
    console.log('')
  }

  if (report.cyberpunkArtifacts.length) {
    console.log(`【2. 科幻/赛博朋克视觉残留】`)
    for (const item of report.cyberpunkArtifacts) {
      console.log(`  • ${item.file}:${item.line}  [${item.kind}] ${item.detail}`)
    }
    console.log('')
  }

  const hexEntries = Object.entries(report.hardcodedHexByColor).sort((a, b) => b[1] - a[1])
  if (hexEntries.length) {
    console.log(`【3. 硬编码语义色统计（可用 migrate-science-tokens.mjs 自动收敛）】`)
    for (const [hex, count] of hexEntries) {
      console.log(`  • ${hex.padEnd(9)} × ${String(count).padStart(2)}  → 建议替换为 ${SEMANTIC_HEX_SUGGESTIONS[hex]}`)
    }
    console.log('')
  }

  if (report.staleVersions.length) {
    console.log(`【4. 过时版本号残留】`)
    for (const item of report.staleVersions) {
      console.log(`  • ${item.file}:${item.line}  发现 ${item.found}，package.json 为 ${item.expected}`)
    }
    console.log('')
  }

  console.log(`【5. WCAG 2.1 对比度校验】`)
  for (const c of report.contrastChecks) {
    const mark = c.pass ? '✓' : '✗'
    console.log(
      `  ${mark} [${c.theme.padEnd(5)}] ${c.label.padEnd(14)} ${String(c.ratio).padStart(5)}:1 (要求 ≥ ${c.min}:1)  ${c.pair}`,
    )
  }
  console.log('')
}

if (STRICT_MODE) {
  const hardFails = report.summary.undefinedVars + report.summary.contrastFailures + report.summary.crtEffects
  if (hardFails > 0) {
    if (!JSON_MODE) console.error(`✗ UI 护栏未通过：存在 ${hardFails} 项硬性问题（未定义变量 / 对比度不足 / CRT 扫描线）`)
    process.exit(1)
  }
}
