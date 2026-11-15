/**
 * 构建产物检查:`npm run build` 之后跑,守住"部署包到底带没带齐东西"。
 *
 * 为什么需要它:前端构建是"静默降级"的重灾区 ——
 *   - KaTeX 的 CSS/字体没打进 dist → 页面公式变源码,但构建仍然成功;
 *   - public/ 下的 robots.txt / theme-init.js 没被复制 → 首屏闪白、搜索收录不该收录的页面;
 *   - 某个 chunk 悄悄涨到 2MB → 首屏在 4G 上白屏 10 秒,CI 里没人会看 vite 的警告。
 * 这三类问题在本地都能确定性判定,所以放在这里挡,而不是等上线后靠用户反馈。
 *
 * 用法(在 frontend/ 下):
 *   npm run build && node scripts/check-build.mjs
 *   node scripts/check-build.mjs --dist dist        # 指定产物目录
 *
 * 退出码:0 = 通过;1 = 有硬性失败。
 */
import { existsSync, readdirSync, readFileSync, statSync } from 'node:fs'
import { gzipSync } from 'node:zlib'
import { dirname, join, relative } from 'node:path'
import { fileURLToPath } from 'node:url'

const HERE = dirname(fileURLToPath(import.meta.url))

const BUDGETS = {
  /** 单个 JS 分块 gzip 上限(当前最大是 mathjax tex2svg ≈ 634KB) */
  chunkGzipKb: 800,
  /** 全部 JS gzip 合计上限 */
  totalJsGzipKb: 1600,
  /** dist 总体积上限(KaTeX 字体占大头,当前 ≈ 6.3MB) */
  totalMb: 10,
}

/** 后端离线导出 PDF 依赖的仓库内资产,不归前端构建管,但必须存在。 */
const BACKEND_KATEX = ['../../backend/static/katex/katex.min.js', '../../backend/static/katex/katex.min.css']
  .map((path) => join(HERE, path))

const argv = process.argv.slice(2)
const distArg = argv.indexOf('--dist')
const DIST = distArg >= 0 && argv[distArg + 1] ? argv[distArg + 1] : 'dist'

const results = []
function check(name, fn) {
  try {
    const detail = fn()
    results.push({ ok: true, name, detail })
  } catch (error) {
    results.push({ ok: false, name, detail: error.message })
  }
}

function assert(condition, message) {
  if (!condition) throw new Error(message)
}

function readText(path) {
  return readFileSync(path, 'utf8')
}

function walk(dir) {
  return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const full = join(dir, entry.name)
    return entry.isDirectory() ? walk(full) : [full]
  })
}

function kb(bytes) {
  return Math.round((bytes / 1024) * 10) / 10
}

const files = existsSync(DIST) ? walk(DIST) : []
const assets = files.filter((file) => file.includes(`${join(DIST, 'assets')}`))

check('产物目录存在', () => {
  assert(files.length > 0, `${DIST}/ 不存在或为空,先跑 npm run build`)
  return `${files.length} 个文件`
})

check('入口 HTML 指向打包资源', () => {
  const html = readText(join(DIST, 'index.html'))
  assert(/<div id="app">/.test(html), 'index.html 里没有 #app 挂载点')
  assert(/<script[^>]+src="\/assets\/[^"]+\.js"/.test(html), 'index.html 没有引用 /assets/*.js')
  return 'index.html ok'
})

check('public/ 资源随包', () => {
  const robots = join(DIST, 'robots.txt')
  assert(existsSync(robots), 'dist/robots.txt 缺失(public/robots.txt 没被复制?)')
  assert(/Disallow:\s*\/api\//.test(readText(robots)), 'robots.txt 没有 Disallow: /api/')
  assert(existsSync(join(DIST, 'theme-init.js')), 'dist/theme-init.js 缺失(首屏主题会闪)')
  return 'robots.txt + theme-init.js'
})

check('KaTeX 随包(CSS 类 + 字体)', () => {
  const cssFiles = assets.filter((file) => file.endsWith('.css'))
  assert(cssFiles.length > 0, 'dist/assets 下没有 CSS')
  const hasKatexCss = cssFiles.some((file) => /\.katex/.test(readText(file)))
  assert(hasKatexCss, '打包后的 CSS 里没有 .katex 规则(公式会退化成源码)')
  const fonts = assets.filter((file) => /KaTeX_.+\.woff2$/.test(file))
  assert(fonts.length >= 8, `KaTeX 字体只有 ${fonts.length} 个(少于 8 个,字体被外部化了?)`)
  return `.katex 规则 + ${fonts.length} 个字体`
})

check('后端离线导出用的 KaTeX 资产在仓库里', () => {
  const missing = BACKEND_KATEX.filter((path) => !existsSync(path))
  assert(!missing.length, `缺:${missing.join(', ')}(PDF 导出会退化成源码公式)`)
  return BACKEND_KATEX.length + ' 个文件'
})

const jsAssets = assets.filter((file) => file.endsWith('.js'))
const jsGzip = jsAssets.reduce((sum, file) => sum + gzipSync(readFileSync(file)).length, 0)

check(`单个 JS 分块 gzip ≤ ${BUDGETS.chunkGzipKb}KB`, () => {
  const oversize = jsAssets
    .map((file) => ({ file: relative(DIST, file), size: kb(gzipSync(readFileSync(file)).length) }))
    .filter((item) => item.size > BUDGETS.chunkGzipKb)
  assert(!oversize.length, oversize.map((i) => `${i.file} ${i.size}KB`).join(' / '))
  const biggest = jsAssets
    .map((file) => ({ file: relative(DIST, file), size: kb(gzipSync(readFileSync(file)).length) }))
    .sort((a, b) => b.size - a.size)[0]
  return `最大 ${biggest.file} ${biggest.size}KB`
})

check(`JS gzip 合计 ≤ ${BUDGETS.totalJsGzipKb}KB`, () => {
  const total = kb(jsGzip)
  assert(total <= BUDGETS.totalJsGzipKb, `实际 ${total}KB(超预算 ${total - BUDGETS.totalJsGzipKb}KB)`)
  return `${jsAssets.length} 个 JS · ${total}KB`
})

check(`dist 总体积 ≤ ${BUDGETS.totalMb}MB`, () => {
  const total = files.reduce((sum, file) => sum + statSync(file).size, 0)
  const mb = Math.round((total / 1024 / 1024) * 100) / 100
  assert(mb <= BUDGETS.totalMb, `实际 ${mb}MB`)
  return `${mb}MB`
})

let failed = 0
console.log(`构建产物检查 · ${DIST}/`)
for (const item of results) {
  if (item.ok) {
    console.log(`[OK]   ${item.name} · ${item.detail}`)
  } else {
    failed += 1
    console.log(`[FAIL] ${item.name} · ${item.detail}`)
  }
}
console.log(`合计:${results.length - failed} 通过 · ${failed} 失败`)
process.exit(failed ? 1 : 0)
