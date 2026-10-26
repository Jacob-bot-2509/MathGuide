/**
 * MathText 数学公式渲染自测(经 vite SSR 装置真实渲染组件):
 *   npx esbuild scripts/math-text-test.ts --bundle --format=cjs --platform=node \
 *     --external:vite --external:vue --external:vue/server-renderer --outfile=.math-text-test.cjs && node .math-text-test.cjs
 *
 * 盯的是公式渲染的三个历史缺陷:
 *   ① \\(...\\) 分隔符(LLM 与知识库大量使用)不被识别,原样显示反斜杠括号;
 *   ② KaTeX 坏公式渲染成红色 katex-error 文本,而非优雅的源码兜底;
 *   ③ "$ x > 0 $" 带空格的公式被金额保护误挡。
 */
/* eslint-disable */
declare const process: { exit(code: number): void }

import { createServer } from 'vite'
import { renderToString } from 'vue/server-renderer'

let passed = 0
const failed: string[] = []

function check(name: string, got: boolean, detail = '') {
  if (got) {
    passed++
  } else {
    failed.push(`✗ ${name}${detail ? `\n    ${detail}` : ''}`)
  }
}

async function main() {
  const server = await createServer({
    server: { middlewareMode: true },
    appType: 'custom',
    logLevel: 'error',
    // 测试只按需 ssrLoadModule 组件,不需要预扫描 index.html 的依赖;
    // 关闭自动发现可以避免 server.close() 与依赖扫描竞争产生红色报错
    optimizeDeps: { noDiscovery: true },
  })
  try {
    const mod = await server.ssrLoadModule('/src/components/chat/MathText.vue')
    const MathText = (mod as { default: unknown }).default

    // 用 h() 构造 VNode 走 vue/server-renderer 渲染(MathText 是无状态函数组件,
    // 不碰浏览器 API,SSR 输出与浏览器端同构)
    const { h } = await import('vue')
    async function renderComp(text: string): Promise<string> {
      const vnode = h(MathText as never, { text })
      return renderToString(vnode)
    }

    // ① \(...\) 行内公式 → KaTeX 渲染
    let html = await renderComp('导数定义:\\(f\'(x)=\\lim_{h\\to 0}\\frac{f(x+h)-f(x)}{h}\\)')
    check('括号式行内公式被渲染', html.includes('katex'), `输出: ${html.slice(0, 120)}`)
    check('括号式不残留反斜杠括号', !html.includes('\\('), '')

    // ② $...$ 行内公式
    html = await renderComp('导数是 $f(x)$ 的斜率')
    check('$ 行内公式被渲染', html.includes('katex'), '')

    // ③ $$..$$ 块级公式(display 模式)
    html = await renderComp('$$\n\\int_0^1 x^2 dx\n$$')
    check('块级公式被渲染(display)', html.includes('katex-display'), '')

    // ④ "$ x > 0 $" 带空格(LLM 实测输出过)
    html = await renderComp('当 $ x > 0 $ 时成立')
    check('带空格行内公式被渲染', html.includes('katex'), '')

    // ⑤ 金额不误判:"$5 and $6"
    html = await renderComp('价格是 $5 and $6 元')
    check('金额不被误判为公式', !html.includes('katex'), '')

    // ⑥ 坏公式(未闭合花括号)→ 源码兜底,不是红色错误
    html = await renderComp('坏公式 $\\frac{1}{2$ 结尾')
    check('坏公式走源码兜底', html.includes('seg-math-raw'), '')
    check('坏公式不出现红色错误', !html.includes('katex-error') && !html.includes('#cc0000'), '')

    // ⑦ 未闭合公式流式中原样保留
    html = await renderComp('还没写完 $f(x')
    check('未闭合公式原样保留', html.includes('$f(x') && !html.includes('katex'), '')

    // ⑧ Unicode 数学符号纯文本直通(不经 KaTeX,无损失)
    html = await renderComp('x² + ∫₀¹ dx ≤ π → ∞')
    check('Unicode 符号原样保留', html.includes('x²') && html.includes('∫₀¹') && html.includes('→'), '')

    // ⑨ 多公式混排(LLM 典型输出形态)
    html = await renderComp('设 \\(f\\) 在点 \\(x_0\\) 附近光滑,则 $$f(x)=\\sum_{k=0}^{n}\\frac{f^{(k)}(x_0)}{k!}(x-x_0)^k$$ 成立')
    check('混排:三种写法都渲染', (html.match(/class="katex/g) || []).length >= 3, `katex 数量: ${(html.match(/class="katex/g) || []).length}`)

    // ⑩ 非法链接 scheme:只允许 http(s)/cmd://,javascript: 必须退化为纯文本
    html = await renderComp('[点我](javascript:alert(1))')
    check('javascript: 链接不渲染为 <a>', !html.includes('<a ') && html.includes('javascript:alert(1)'), `输出: ${html.slice(0, 160)}`)

    // ⑪ 用户/模型输出中的 HTML 标签按文本转义(不能变成真实标签)
    html = await renderComp('<img src=x onerror=alert(1)>')
    check('HTML 标签被转义', !html.includes('<img') && html.includes('&lt;img'), `输出: ${html.slice(0, 160)}`)

    // ⑫ KaTeX 默认 trust=false,\\href{javascript:...} 不得生成可点击链接
    html = await renderComp('$\\href{javascript:alert(1)}{x}$')
    check('KaTeX href 不生成 javascript 链接', !html.includes('href="javascript:'), `输出: ${html.slice(0, 160)}`)

    // ⑬ cmd://chapter 的畸形百分号编码安全回退(不能抛 URIError)
    const cmdMod = await server.ssrLoadModule('/src/utils/cmdLink.ts')
    const { chapterNameFromCmd } = cmdMod as { chapterNameFromCmd: (url: string) => string | null }
    check('畸形 cmd 链接回退原文', chapterNameFromCmd('cmd://chapter/%E0%A4%A') === '%E0%A4%A', '')
    check('正常 cmd 链接正确解码', chapterNameFromCmd('cmd://chapter/%E7%AC%AC1%E7%AB%A0') === '第1章', '')
    check('非章节 cmd 链接返回 null', chapterNameFromCmd('cmd://back') === null, '')

    // ⑭ 稳定块切分:不切代码围栏/块级公式,拼回原文不丢字
    const blocksMod = await server.ssrLoadModule('/src/utils/mathBlocks.ts')
    const { splitStableBlocks } = blocksMod as { splitStableBlocks: (text: string) => string[] }
    const stable = 'a\n\n```\nx\n\ny\n```\n\n$$\nu\n\nv\n$$\n\nb'
    const parts = splitStableBlocks(stable)
    check('分块:原文可无损拼回', parts.join('') === stable, `块数 ${parts.length}`)
    check('分块:代码围栏不被切断', parts.some((p) => p.includes('```\nx\n\ny\n```')), '')
    check('分块:块级公式不被切断', parts.some((p) => p.includes('$$\nu\n\nv\n$$')), '')
    check('分块:空文本返回空数组', splitStableBlocks('').length === 0, '')

    const bracket = 'a\n\n\\[\nx\n\ny\n\\]\n\nb'
    check('分块:\\[...\\] 不被切断',
      splitStableBlocks(bracket).some((p) => p.includes('\\[\nx\n\ny\n\\]')), '')

    const inline = 'a\n\n\\(\nx\n\ny\n\\)\n\nb'
    check('分块:\\\\(...\\\\) 不被切断',
      splitStableBlocks(inline).some((p) => p.includes('\\(\nx\n\ny\n\\)')), '')

    const mixed = '前面 $x$\n\n$$\na\n\nb\n$$\n\n尾 $y$'
    const whole = await renderComp(mixed)
    const pieceHtml = await Promise.all(splitStableBlocks(mixed).map((p) => renderComp(p)))
    const katexCount = (s: string) => (s.match(/class="katex/g) || []).length
    check('分块:公式数量与整段一致',
      katexCount(pieceHtml.join('')) === katexCount(whole),
      `${katexCount(pieceHtml.join(''))} vs ${katexCount(whole)}`)

    console.log(`\nMathText 公式渲染自测:${passed}/${passed + failed.length} 通过`)
    for (const f of failed) console.log(f)
    if (failed.length) process.exit(1)
  } finally {
    await server.close()
  }
}

void main()
