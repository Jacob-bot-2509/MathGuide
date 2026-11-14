/**
 * mathArrays:把 KaTeX 不认的 array 列规则改成 HTML 表格。
 *
 * 为什么值得测:KaTeX 对 `|`、`@{}`、`\multicolumn`、`\hline` 这些列语法支持不全,
 * 解析失败就会整块公式渲染成红字。这里退化成 <table> 兜底,
 * 但兜底本身必须“宁可不渲染也不能错渲染”—— 所以每条异常路径都要有出口(null)。
 */
import { describe, expect, it } from 'vitest'
import { renderMathArray } from '@/utils/mathArrays'

/** 包一层 array 环境,减少转义噪音。 */
const arr = (cols: string, body: string): string =>
  `\\begin{array}{${cols}}${body}\\end{array}`

const cellRenderer = (tex: string): string => `[${tex}]`

const render = (source: string): string | null =>
  renderMathArray(source, cellRenderer)

const rowCount = (html: string): number => html.match(/<tr/g)?.length ?? 0

const tdCount = (html: string): number => html.match(/<td/g)?.length ?? 0

describe('renderMathArray:入口与格式判定', () => {
  it('不是 array 环境时返回 null(交给 KaTeX 自己处理)', () => {
    expect(render('x^2')).toBeNull()
    expect(render('\\begin{matrix}a\\end{matrix}')).toBeNull()
    expect(render('')).toBeNull()
  })

  it('缺 \\end{array} 或列规则缺失时返回 null', () => {
    expect(render('\\begin{array}{cc} a & b')).toBeNull()
    expect(render('\\begin{array}a & b\\end{array}')).toBeNull()
  })

  it('列规则为空或含未知对齐符时返回 null', () => {
    expect(render(arr('', 'a'))).toBeNull()
    expect(render(arr('cp', 'a'))).toBeNull()
  })

  it('列数超过 30 时返回 null(表格宽到没法看)', () => {
    expect(render(arr('c'.repeat(31), 'a'))).toBeNull()
    expect(render(arr('c'.repeat(30), 'a'))).not.toBeNull()
  })

  it('body 里再嵌 array 时放弃(嵌套表没有安全退路)', () => {
    expect(render(arr('c', '\\begin{array}{c}x\\end{array}'))).toBeNull()
  })

  it('正常二维表渲染成 table,并把每个单元格交给 renderCell', () => {
    const html = render(arr('cc', 'a & b \\\\ c & d'))!
    expect(html.startsWith('<span class="mg-array"')).toBe(true)
    expect(html.endsWith('</table></span>')).toBe(true)
    expect(rowCount(html)).toBe(2)
    expect(tdCount(html)).toBe(4)
    expect(html).toContain('[a]')
    expect(html).toContain('[d]')
  })

  it('对齐符 l/c/r 映射到 text-align', () => {
    const html = render(arr('lcr', 'a & b & c'))!
    expect(html).toContain('text-align:left')
    expect(html).toContain('text-align:center')
    expect(html).toContain('text-align:right')
  })
})

describe('renderMathArray:列规则细节', () => {
  it('单竖线画 1px 实线,双竖线画 3px 双线', () => {
    expect(render(arr('|c', 'a'))).toContain('border-left:1px solid currentColor')
    expect(render(arr('||c', 'a'))).toContain('border-left:3px double currentColor')
    expect(render(arr('c|', 'a'))).toContain('border-right:1px solid currentColor')
  })

  it('三根竖线时按“双线”降级(没有 4px 方案)', () => {
    expect(render(arr('c|||', 'a'))).toContain('border-right:3px double currentColor')
  })

  it('没有竖线时边框为 none(不能凭空多出格子线)', () => {
    const html = render(arr('c', 'a'))!
    expect(html).toContain('border-left:none')
    expect(html).toContain('border-right:none')
  })

  it('@{} 系列控制列间距,padding 用 em 表示', () => {
    // 默认左右各 1 半格 = 0.5em
    expect(render(arr('c', 'a'))).toContain('padding:0 0.5em 0 0.5em')
    // @{} 把左边距压成 0
    expect(render(arr('@{}c', 'a'))).toContain('padding:0 0.5em 0 0em')
    // @{\;} = 0.2778em,取一半
    expect(render(arr('@{\\;}c', 'a'))).toContain('0.1389em')
    // @{\,} = 0.1667em,取一半
    expect(render(arr('c@{\\,}c', 'a & b'))).toContain('0.08335em')
  })

  it('@{} 里写不认识的间距时返回 null(不猜)', () => {
    expect(render(arr('@{xyz}c', 'a'))).toBeNull()
    expect(render(arr('@{c', 'a'))).toBeNull()
  })

  it('*n{cols} 展开成重复列', () => {
    expect(tdCount(render(arr('*3{c}', 'a & b & c'))!)).toBe(3)
  })

  it('*0 / *21 这类越界重复直接放弃(避免生成巨型表格)', () => {
    expect(render(arr('*0{c}', 'a'))).toBeNull()
    expect(render(arr('*21{c}', 'a'))).toBeNull()
    expect(render(arr('*{c', 'a'))).toBeNull()
  })

  it('嵌套 * 也会展开', () => {
    expect(tdCount(render(arr('*2{*2{c}}', 'a & b & c & d'))!)).toBe(4)
  })

  it('列规则里的空白不影响解析', () => {
    expect(render(arr('  c | c  ', 'a & b'))).toContain('border-right:1px solid')
  })
})

describe('renderMathArray:行与 \\hline / \\cline', () => {
  it('\\hline 生成整行横线(不占单元格文本)', () => {
    const html = render(arr('cc', 'a & b \\\\ \\hline c & d'))!
    expect(rowCount(html)).toBe(3)
    expect(html).toContain('border-top:1px solid currentColor')
  })

  it('\\cline{2-3} 只画指定列区间,其他列仍是 none', () => {
    const html = render(arr('ccc', 'a & b & c \\\\ \\cline{2-3} d & e & f'))!
    expect(html).toContain('border-top:1px solid currentColor')
    expect(html).toContain('border-top:none')
  })

  it('\\cline 区间越界或倒序时返回 null', () => {
    expect(render(arr('cc', '\\cline{0-1} a & b'))).toBeNull()
    expect(render(arr('cc', '\\cline{2-1} a & b'))).toBeNull()
    expect(render(arr('cc', '\\cline{1-3} a & b'))).toBeNull()
    expect(render(arr('cc', '\\cline{x} a & b'))).toBeNull()
  })

  it('末尾多余的 row separator 不生成空行', () => {
    expect(rowCount(render(arr('cc', 'a & b \\\\ c & d \\\\'))!)).toBe(2)
  })

  it('中间的空白行仍保留(和 LaTeX 语义一致)', () => {
    expect(rowCount(render(arr('cc', 'a & b \\\\  \\\\ c & d'))!)).toBe(3)
  })

  it('单元格不足时补齐空单元格,但不给 renderCell 送空串', () => {
    const calls: string[] = []
    const html = renderMathArray(arr('ccc', 'a'), (tex) => {
      calls.push(tex)
      return `[${tex}]`
    })!
    expect(tdCount(html)).toBe(3)
    expect(calls).toEqual(['a'])
  })

  it('前导空单元格照样占位', () => {
    const calls: string[] = []
    renderMathArray(arr('cc', ' & b'), (tex) => {
      calls.push(tex)
      return tex
    })
    expect(calls).toEqual(['b'])
  })

  it('单元格里含花括号与转义时不会被误切', () => {
    expect(render(arr('cc', '\\frac{1}{2} & b'))).toContain('[\\frac{1}{2}]')
  })

  it('花括号不闭合时返回 null(不能把结构猜错)', () => {
    expect(render(arr('cc', 'a & {b'))).toBeNull()
    expect(render(arr('cc', 'a} & b'))).toBeNull()
  })
})

describe('renderMathArray:\\multicolumn', () => {
  it('跨列单元格用 colspan 表达,并按格式串决定边框与对齐', () => {
    const html = render(arr('ccc', '\\multicolumn{2}{|c|}{标题} \\\\ a & b & c'))!
    expect(html).toContain('colspan="2"')
    expect(html).toContain('text-align:center')
    expect(html).toContain('border-left:1px solid currentColor')
    expect(html).toContain('border-right:1px solid currentColor')
    expect(html).toContain('[标题]')
  })

  it('跨列数非法(0 / 越界 / 非数字)时返回 null', () => {
    expect(render(arr('cc', '\\multicolumn{0}{c}{x} & b'))).toBeNull()
    expect(render(arr('cc', '\\multicolumn{3}{c}{x} & b'))).toBeNull()
    expect(render(arr('cc', '\\multicolumn{a}{c}{x} & b'))).toBeNull()
  })

  it('格式串非法、内容后有多余字符、缺内容组都返回 null', () => {
    expect(render(arr('cc', '\\multicolumn{1}{p}{x} & b'))).toBeNull()
    expect(render(arr('cc', '\\multicolumn{1}{c}{x} 尾巴 & b'))).toBeNull()
    expect(render(arr('cc', '\\multicolumn{1}{c}'))).toBeNull()
  })

  it('跨满整行时不再补空单元格', () => {
    expect(tdCount(render(arr('cc', '\\multicolumn{2}{c}{全部}'))!)).toBe(1)
  })

  it('双竖线格式给出双线边框', () => {
    const html = render(arr('cc', '\\multicolumn{2}{||c||}{全}'))!
    expect(html).toContain('border-left:3px double currentColor')
    expect(html).toContain('border-right:3px double currentColor')
  })

  it('跨列后剩余的列照常补空(混合行)', () => {
    expect(tdCount(render(arr('ccc', '\\multicolumn{2}{c}{甲} & b'))!)).toBe(2)
  })
})

