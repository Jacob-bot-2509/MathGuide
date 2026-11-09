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

    // ②b 伴随/转置符号不能被转义吃掉
    html = await renderComp('验证 $U^\\dagger U=I$ 成立')
    check('\\dagger 在行内公式中渲染',
      html.includes('katex') && html.includes('†') && !html.includes('seg-math-raw'),
      `输出: ${html.slice(0, 600)}`)
    html = await renderComp('验证 \\(U^\\dagger U=I\\) 成立')
    check('\\dagger 在括号式公式中渲染',
      html.includes('katex') && html.includes('†') && !html.includes('seg-math-raw'),
      `输出: ${html.slice(0, 600)}`)

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
    // ⑭ Markdown 表格:数学里的 | 不能被当作列分隔
    html = await renderComp(
      '| x | 切线斜率 $|\\cos x|$ | 直观感受 |\n'
      + '|---|---|---|\n'
      + '| $0$ | $1$ | 最陡的上坡 |\n'
      + '| $\\pi/3$ | $1/2$ | 缓缓上坡 |')
    check('表格被渲染为 <table>', html.includes('<table') && html.includes('<th'))
    check('表格三列不被数学竖线拆开',
      (html.match(/<th\b/g) || []).length === 3, `th 数量: ${(html.match(/<th\b/g) || []).length}`)
    check('表格单元格公式被渲染', html.includes('katex'))

    html = await renderComp('x | y\n--- | ---\n1 | 2')
    check('无外框表格也能识别', html.includes('<table') && html.includes('<td'))

    // 模型常用 |:-:| 这种单横线对齐行,不能因为不足三条横线就整张表失效
    html = await renderComp(
      '| 维数 $\\dim(S)$ | 几何形态 | 特征 |\n'
      + '|:-:|:-:|:-:|\n'
      + '| $0$ | 一个点 | 仅原点 $\\{0\\}$ |\n'
      + '| $1$ | 一条直线 | 过原点的直线 |')
    check('单横线对齐表格可识别', html.includes('<table')
      && (html.match(/<th\b/g) || []).length === 3,
    `th 数量: ${(html.match(/<th\b/g) || []).length}`)

    html = await renderComp('| a | b |\n|---|---|\n| \\(|x|\\) | 2 |')
    check('圆括号公式里的竖线不拆列',
      (html.match(/<td/g) || []).length === 2,
      `td 数量: ${(html.match(/<td/g) || []).length}`)

    html = await renderComp('| a | b |\n|---|---|\n| $$x^2$$ | 2 |')
    check('表格内块级公式按行内排版',
      html.includes('<table') && !html.includes('katex-display'))

    // 模型偶尔把块级公式折成多行;表格行必须按公式闭合位置拼回
    html = await renderComp(
      '| 维数 $$\n\\dim(S)\n$$ | 几何形态 | 特征 |\n'
      + '|:-:|:-:|:-:|\n'
      + '| $$0$$ | 一个点 | 仅原点 \\(\\{0\\}\\) |\n'
      + '| $$1$$ | 一条直线 | 过原点的直线 |')
    check('跨行公式表格可识别', html.includes('<table')
      && (html.match(/<th\b/g) || []).length === 3,
    `th 数量: ${(html.match(/<th\b/g) || []).length}`)

    html = await renderComp('| a | b |\n|---|---|\n| x \\| y | 2 |')
    check('转义竖线不拆列且还原',
      (html.match(/<td/g) || []).length === 2 && html.includes('x | y'))

    // ⑮ 代码/转义里的 | 不拆列
    html = await renderComp('| a | b |\n|---|---|\n| `x|y` | 2 |')
    check('代码内竖线不拆列', (html.match(/<td/g) || []).length === 2)

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

    // ⑪ 数字开头、跨行的行内公式必须渲染(模型实测输出)
    html = await renderComp('当 $0$ 时')
    check('数字开头公式渲染', html.includes('katex'), `输出: ${html.slice(0, 120)}`)

    html = await renderComp('当 x\nx 从右侧逼近 $0$ 时')
    check('句子里的数字公式渲染', html.includes('katex'), `输出: ${html.slice(0, 120)}`)

    html = await renderComp('近于 $0，随着 x 增大趋向 +\\infty$ 的单支')
    check('带数字与跨行的公式渲染', html.includes('katex'), `输出: ${html.slice(0, 120)}`)

    // ⑫ 金额保护不能误伤公式,也不能放过真正的价格
    html = await renderComp('价格是 $5 元')
    check('货币单位仍挡金额', !html.includes('katex'), '')

    html = await renderComp('$5 and $6')
    check('并列金额仍不渲染', !html.includes('katex'), '')

    html = await renderComp('价格 $5，展开式的关系数全是漂亮的')
    check('落单 $ 不把中文正文当公式', !html.includes('katex'), `输出: ${html.slice(0, 120)}`)

    html = await renderComp('$a' + 'x'.repeat(400) + '$b')
    check('落单 $ 不吞长文', !html.includes('katex'), '')


    // Isolation happens before table and Markdown parsing.
    html = await renderComp(String.raw`| a | b |
|---|---|
| \\(|x_1| < \boxed{2}\\) | 2 |`)
    check('双重转义和公式竖线在表格中渲染',
      (html.match(/<td/g) || []).length === 2 && html.includes('katex') && !html.includes('seg-math-raw'))

    html = await renderComp(String.raw`**值 \(\boxed{x_1 < 2}\)**`)
    check('公式在粗体解析前受保护', html.includes('katex') && !html.includes('seg-math-raw'))

    html = await renderComp(String.raw`先写 $$\begin{aligned}a&=b\\c&=`)
    check('未闭合块级公式原样显示', html.includes('$$') && !html.includes('katex'))
    html = await renderComp(String.raw`先写 $$\begin{aligned}a&=b\\c&=d\end{aligned}$$`)
    check('流式公式闭合后渲染', html.includes('katex-display') && !html.includes('seg-math-raw'))

    html = await renderComp('代码 `$x_1$` 和公式 $y_2$')
    check('行内代码里的公式不进入 KaTeX',
      (html.match(/class="katex"/g) || []).length === 1 && html.includes('$x_1$'))

    const isolationMod = await server.ssrLoadModule('/src/utils/mathIsolation.ts')
    const isolation = isolationMod as {
      isolateMath: (text: string) => { text: string, formulas: { source: string }[] }
      restoreMathSource: (text: string, formulas: { source: string }[]) => string
      normalizeMathDelimiters: (text: string) => string
    }
    const original = String.raw`MGFORMULATOKEN0END \(x_1 < 2\) \\[y^2\\]`
    const protectedMath = isolation.isolateMath(original)
    check('占位符不会与用户内容冲突且可还原',
      isolation.restoreMathSource(protectedMath.text, protectedMath.formulas) === original)
    check('括号定界符归一化',
      isolation.normalizeMathDelimiters(String.raw`\(x\) \\[y\\]`) === '$x$ $$y$$')

    html = await renderComp(String.raw`积分 \begin{align*}\dblInt_{\cS_t}\vF\cdot\hn\,\dee{x}&=15\pi\\&=15\pi\end{align*}`)
    check('题库独立公式环境及自定义宏渲染', html.includes('katex-display') && !html.includes('seg-math-raw'))
    html = await renderComp(String.raw`积分 \begin{align\*}\dblInt\_{\cS_t}\\,\dee{x}\\\ &=15\pi\end{align\*}`)
    check('Markdown 转义的题库公式环境渲染', html.includes('katex-display') && !html.includes('seg-math-raw'))
    html = await renderComp(String.raw`未结束 \begin{align*}x&=y`)
    check('流式未闭合环境保留原文', html.includes('\\begin{align*}') && !html.includes('katex'))

    html = await renderComp(String.raw`\begin{align*}x &= \knowl{./ref/path}{\text{4.1.3}}\end{align*}`)
    check('题库引用宏保留显示文字', html.includes('katex-display') && html.includes('4.1.3') && !html.includes('seg-math-raw'))

    const currentIsolation = isolationMod as { prepareMath: (text: string) => string }
    const pairs = [
      [String.raw`\\dfrac{x}{\\sqrt{y}}`, String.raw`\dfrac{x}{\sqrt{y}}`],
      [String.raw`\root 3 \of {x \root 3 \of {x}}`, String.raw`\sqrt[3]{x \sqrt[3]{x}}`],
      [String.raw`15(_x_+40)=900`, String.raw`15(x+40)=900`],
      [String.raw`(1)\[x+1\]`, String.raw`(1)[x+1]`],
      [String.raw`n\in N^{\*}`, String.raw`n\in N^{*}`],
      [String.raw`\begin{cases}x=1\\\\y=2\\end{cases}`, String.raw`\begin{cases}x=1\\y=2\end{cases}`],
    ]
    for (const [raw, expected] of pairs) {
      check('来源语法归一化: ' + raw.slice(0, 28), currentIsolation.prepareMath(raw) === expected)
    }
    const keep = String.raw`\begin{aligned}x_1&=1\\y_2&=2\end{aligned}+\text{file\_1}+\mathrm{A_B}+\operatorname{foo_bar}`
    check('原本正确的换行与下标不变', currentIsolation.prepareMath(keep) === keep)
    html = await renderComp(String.raw`$\begin{align*}x&=y\\a&=b\end{align*}$`)
    check('行内定界符内的块级环境渲染', html.includes('katex-display') && !html.includes('seg-math-raw'))

    html = await renderComp(String.raw`$①\times 3-$$②\times 2$`)
    check('相邻行内公式不被误认为块级定界符', html.includes('katex') && !html.includes('seg-math-raw') && !html.includes('katex-display'))
    html = await renderComp('`$x-$$y$`')
    check('代码中的相邻公式定界符保持原样', !html.includes('katex') && html.includes('$x-$$y$'))

    html = await renderComp(String.raw`$\frac{\cancelto{2}{10}}{\cancelto{3}{12}}$`)
    check('消去标记保留箭头和约分结果', html.includes('katex') && !html.includes('seg-math-raw') && html.includes('10') && html.includes('12') && html.includes('↗'))

    html = await renderComp(String.raw`引用 \( \PageIndex{21} \)`)
    check('题库页码引用宏显示编号', html.includes('katex') && html.includes('21') && !html.includes('seg-math-raw'))

    check('文字下划线安全保留', currentIsolation.prepareMath(String.raw`S_{\text {_NUA }}`) === String.raw`S_{\text {\_NUA }}`)
    check('转义根号保留原符号', currentIsolation.prepareMath('\\' + String.fromCharCode(0x221a)) === String.raw`\surd`)

    check('独立转义括号显示为括号', currentIsolation.prepareMath(String.raw`\(`) === '(' && currentIsolation.prepareMath(String.raw`\)`) === ')')
    html = await renderComp(String.raw`选择 $\($ $\)$ A`)
    check('选择题括号可渲染', html.includes('katex') && !html.includes('seg-math-raw'))

    check('重复的几何符号和嵌套定界符去除', currentIsolation.prepareMath(String.raw`\triangle\(\triangle ABC\\)`) === String.raw`\triangle ABC`)
    check('不同的几何符号不擅自合并', currentIsolation.prepareMath(String.raw`\triangle\(\angle ABC\)`) === String.raw`\triangle\(\angle ABC\)`)
    html = await renderComp(String.raw`$\triangle\(\triangle ABC\\)$`)
    check('重复几何符号的题目可渲染', html.includes('katex') && !html.includes('seg-math-raw'))

    check('嵌套括号定界符去除', currentIsolation.prepareMath(String.raw`\[x^2\]`) === 'x^2')

    html = await renderComp(String.raw`$\begin{aligned}x&=y\end{aligned}$`)
    check('aligned 环境保留行内排版', html.includes('katex') && !html.includes('katex-display') && !html.includes('seg-math-raw'))
    console.log(`\nMathText 公式渲染自测:${passed}/${passed + failed.length} 通过`)
    for (const f of failed) console.log(f)
    if (failed.length) process.exit(1)
  } finally {
    await server.close()
  }
}

void main()
