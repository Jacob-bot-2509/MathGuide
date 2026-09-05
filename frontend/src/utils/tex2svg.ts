/**
 * LaTeX → SVG 转换器(MathJax SVG 输出)
 *
 * 用于开场动画等需要"逐笔描边书写 / 发光"效果的场景:
 * SVG 输出把每个字形画成 path,可以单独做描边动画;
 * 聊天正文里的公式仍使用 KaTeX(渲染更快,适合流式输出)。
 */
import { mathjax } from 'mathjax-full/js/mathjax.js'
import { TeX } from 'mathjax-full/js/input/tex.js'
import { SVG } from 'mathjax-full/js/output/svg.js'
import { AllPackages } from 'mathjax-full/js/input/tex/AllPackages.js'
import { liteAdaptor } from 'mathjax-full/js/adaptors/liteAdaptor.js'
import { RegisterHTMLHandler } from 'mathjax-full/js/handlers/html.js'

let doc: ReturnType<typeof mathjax.document> | null = null

function ensureDoc() {
  if (doc) return doc
  const adaptor = liteAdaptor()
  RegisterHTMLHandler(adaptor)
  const tex = new TeX({ packages: AllPackages })
  // fontCache 'none':所有字形内联为 path,便于逐笔动画
  const svg = new SVG({ fontCache: 'none' })
  doc = mathjax.document('', { InputJax: tex, OutputJax: svg })
  return doc
}

/** 将 LaTeX 转为 SVG 字符串(display 模式)。转换失败时返回空串。 */
export function texToSvg(latex: string, display = true): string {
  try {
    const d = ensureDoc()
    const node = d.convert(latex, { display })
    return d.adaptor.innerHTML(node)
  } catch (err) {
    console.error('[MathGuide] LaTeX 转换失败:', latex, err)
    return ''
  }
}
