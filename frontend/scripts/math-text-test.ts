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

    console.log(`\nMathText 公式渲染自测:${passed}/${passed + failed.length} 通过`)
    for (const f of failed) console.log(f)
    if (failed.length) process.exit(1)
  } finally {
    await server.close()
  }
}

void main()
