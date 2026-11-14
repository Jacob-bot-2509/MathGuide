/**
 * mathIsolation:把完整公式从 Markdown 里“抽出来”,把没写完的尾巴挂起。
 *
 * 为什么值得测:流式输出时每一块新文本都会被重新解析,
 * 这里一旦把普通美元金额当成公式、或者把没闭合的 `$` 当成公式吞掉后文,
 * 用户看到的就是整段文字凭空消失。反过来,漏掉公式会让 KaTeX 拿到半截 TeX 变红字。
 */
import { describe, expect, it } from 'vitest'
import {
  isolateMath,
  normalizeMathDelimiters,
  prepareMath,
  restoreMathSource,
  splitIsolatedMath,
} from '@/utils/mathIsolation'

describe('prepareMath:清理 Markdown 反斜杠转义', () => {
  it('单独出现的 \\( 与 \\) 退化成普通括号(译者误加的定界符)', () => {
    expect(prepareMath('\\(')).toBe('(')
    expect(prepareMath('\\)')).toBe(')')
  })

  it('被转义的环境名去掉多余的反斜杠', () => {
    expect(prepareMath('\\begin{aligned\\*}a\\end{aligned\\*}'))
      .toBe('\\begin{aligned*}a\\end{aligned*}')
  })

  it('转义过的表格分隔符只在“环境被转义”时才还原', () => {
    // 触发条件:整段带 \begin{}\* 的转义环境(说明这段被 Markdown 转义过)
    const out = prepareMath('\\begin{aligned\\*}a\\\\,b\\\\\\&c\\end{aligned\\*}')
    expect(out).toContain('a\\,b')
    expect(out).toContain('\\\\&c')
    // 普通公式里的 \\, 保持原样(它就是 LaTeX 的窄空格)
    expect(prepareMath('a\\\\,b')).toBe('a\\\\,b')
  })

  it('\\text{} 里的下划线被转义,公式里的裸下划线保留', () => {
    expect(prepareMath('\\text{a_b}')).toBe('\\text{a\\_b}')
    expect(prepareMath('x_1')).toBe('x_1')
  })

  it('重复的几何符号(译者抄了两遍)只留一份', () => {
    expect(prepareMath('\\triangle \\( \\triangle ABC \\)').trim())
      .toBe('\\triangle ABC')
    expect(prepareMath('\\angle \\( \\angle AOB \\)').trim()).toBe('\\angle AOB')
  })

  it('外面又套了一层定界符时剥掉外层', () => {
    expect(prepareMath('\\(x+1\\)')).toBe('x+1')
    expect(prepareMath('\\[x+1\\]')).toBe('x+1')
    expect(prepareMath('\\\\(x+1\\\\)')).toBe('x+1')
  })

  it('\\root n \\of 还原成 \\sqrt[n]', () => {
    expect(prepareMath('\\root 3 \\of x')).toBe('\\sqrt[3]x')
  })

  it('\\renewcommand 的 arraystretch 换成 \\def(KaTeX 只认后者)', () => {
    expect(prepareMath('\\renewcommand{\\arraystretch}{1.5}'))
      .toBe('\\def\\arraystretch{1.5}')
  })

  it('\\amp 还原成表格分隔符 &', () => {
    expect(prepareMath('a \\amp b')).toBe('a & b')
  })

  it('整段被 \\[...\\] 包住时剥掉外层定界符', () => {
    expect(prepareMath('\\[0,1\\]')).toBe('0,1')
  })

  it('公式中间的 \\[..\\] 换成普通方括号(区间/闭包写法)', () => {
    expect(prepareMath('a \\in \\[0,1\\] 里')).toBe('a \\in [0,1] 里')
  })

  it('^{\\*} 与 \\√ 统一成 KaTeX 认识的写法', () => {
    expect(prepareMath('x^{\\*}')).toBe('x^{*}')
    expect(prepareMath('\\√2')).toBe('\\surd2')
  })

  it('x_y_ 这种单字母夹下划线去掉下划线(Markdown 斜体残留)', () => {
    expect(prepareMath('_a_')).toBe('a')
    expect(prepareMath('x_a_')).toBe('x_a_')
  })
})

describe('isolateMath:完整公式抽取', () => {
  it('没有公式时原文照抄', () => {
    const result = isolateMath('普通一段文字,没有公式。')
    expect(result.formulas).toEqual([])
    expect(result.text).toBe('普通一段文字,没有公式。')
  })

  it('行内 $...$ 被替换成 token 并保留 latex', () => {
    const result = isolateMath('已知 $x^2$ 求导')
    expect(result.formulas).toHaveLength(1)
    expect(result.formulas[0]).toMatchObject({
      latex: 'x^2', display: false, pending: false, source: '$x^2$',
    })
    expect(result.text).toBe(`已知 ${result.formulas[0].token} 求导`)
  })

  it('块级 $$...$$ 标记成 display', () => {
    const result = isolateMath('$$\\int_0^1 x\\,dx$$')
    expect(result.formulas[0].display).toBe(true)
    expect(result.formulas[0].latex).toBe('\\int_0^1 x\\,dx')
  })

  it('\\(...\\) 行内、\\[...\\] 块级都认', () => {
    expect(isolateMath('\\(a+b\\)').formulas[0]).toMatchObject({
      latex: 'a+b', display: false,
    })
    expect(isolateMath('\\[a+b\\]').formulas[0]).toMatchObject({
      latex: 'a+b', display: true,
    })
  })

  it('公式里的反斜杠转义不会提前截断(\\$) ', () => {
    const result = isolateMath('价格 \\$5 与 $a$')
    expect(result.formulas).toHaveLength(1)
    expect(result.text.startsWith('价格 \\$5 与 ')).toBe(true)
  })

  it('多个公式按出现顺序编号', () => {
    const result = isolateMath('$a$ 和 $b$')
    expect(result.formulas).toHaveLength(2)
    expect(result.formulas[1].token.endsWith('1END')).toBe(true)
    expect(result.text).toContain(' 和 ')
  })

  it('正文里出现 token 前缀时自动加长前缀,避免撞车', () => {
    const result = isolateMath('MGFORMULATOKEN 出现在正文里,然后 $a$')
    expect(result.formulas[0].token.startsWith('MGFORMULATOKENX')).toBe(true)
    expect(result.text).toContain('MGFORMULATOKEN 出现在正文里')
  })
})

describe('isolateMath:不该当成公式的情况', () => {
  it('美元金额不吞正文("价格 $5 元")', () => {
    const result = isolateMath('价格 $5 元')
    expect(result.formulas).toEqual([])
    expect(result.text).toBe('价格 $5 元')
  })

  it('纯中文的 $...$ 不当作公式(更像是标点误用)', () => {
    expect(isolateMath('$你好$').formulas).toEqual([])
  })

  it('含 and/or 的自然语言句子不当作公式', () => {
    expect(isolateMath('$a and b$').formulas).toEqual([])
  })

  it('过长(>300)或含空行的内容不当作公式', () => {
    expect(isolateMath(`$${'x'.repeat(301)}$`).formulas).toEqual([])
    expect(isolateMath('$a\n\nb$').formulas).toEqual([])
  })

  it('数字后面跟货币单位时不当公式', () => {
    expect(isolateMath('$12.5$ 元').formulas).toEqual([])
    // “售价”这类词出现在公式前面时,也按钱处理
    expect(isolateMath('售价 $99$').formulas).toEqual([])
  })

  it('行内公式里出现 $$ 时不误判为块级闭合', () => {
    const result = isolateMath('$a$$b$')
    expect(result.formulas).toHaveLength(1)
    expect(result.formulas[0].display).toBe(false)
    expect(result.formulas[0].latex).toBe('a$$b')
  })

  it('运算符后紧跟的相邻行内公式按行内处理(不是块级)', () => {
    const result = isolateMath('$x+$$y$ 成立')
    expect(result.formulas[0].display).toBe(false)
    expect(result.formulas[0].latex).toBe('x+{}y')
  })
})

describe('isolateMath:代码块与未完成公式', () => {
  it('行内代码里的 $ 不参与公式识别', () => {
    const result = isolateMath('把 `$x$` 写进代码')
    expect(result.formulas).toEqual([])
    expect(result.text).toBe('把 `$x$` 写进代码')
  })

  it('三反引号围栏整块保留(内部的 $ 全部当文本)', () => {
    const source = '```\n$a$\n```'
    expect(isolateMath(source)).toEqual({ text: source, formulas: [] })
  })

  it('只有开头一个反引号时,代码段止于换行', () => {
    const result = isolateMath('`$a$\n后续 $b$')
    expect(result.text.startsWith('`$a$')).toBe(true)
    expect(result.formulas).toHaveLength(1)
  })

  it('没闭合的代码围栏一直吃到结尾(不会漏出半截公式)', () => {
    const result = isolateMath('```\n$a$')
    expect(result.formulas).toEqual([])
    expect(result.text).toBe('```\n$a$')
  })

  it('流式来了一半的公式:挂起并标记 pending,不吐给 Markdown', () => {
    const result = isolateMath('先看 $x^')
    expect(result.formulas).toHaveLength(1)
    expect(result.formulas[0]).toMatchObject({ latex: '', pending: true, source: '$x^' })
    expect(result.text).toBe(`先看 ${result.formulas[0].token}`)
  })

  it('独占一行的 $ 后面跟着不像数学的内容时按普通字符处理', () => {
    const result = isolateMath('价格 $ 的一半')
    expect(result.formulas).toEqual([])
  })

  it('未闭合的 \\( 也挂起,并保持 display=false', () => {
    const result = isolateMath('算式 \\(a+')
    expect(result.formulas[0]).toMatchObject({ pending: true, display: false })
  })

  it('未闭合的 \\[ 挂起为块级', () => {
    const result = isolateMath('\\[a+')
    expect(result.formulas[0]).toMatchObject({ pending: true, display: true })
  })
})

describe('isolateMath:AMS 环境', () => {
  it('\\begin{align}...\\end{align} 整体当块级公式', () => {
    const result = isolateMath('\\begin{align}a&=b\\end{align}')
    expect(result.formulas).toHaveLength(1)
    expect(result.formulas[0].display).toBe(true)
    expect(result.formulas[0].pending).toBe(false)
    expect(result.formulas[0].latex).toBe('\\begin{align}a&=b\\end{align}')
  })

  it('带星号的 align 也能配对,包括被转义的 \\end{align\\*}', () => {
    const plain = isolateMath('\\begin{align*}a&=b\\end{align*}')
    expect(plain.formulas[0].display).toBe(true)
    const escaped = isolateMath('\\begin{align*}a&=b\\end{align\\*}')
    expect(escaped.formulas).toHaveLength(1)
  })

  it('matrix/cases/array 等环境同样被保护', () => {
    for (const env of ['matrix', 'pmatrix', 'cases', 'array', 'aligned', 'gather']) {
      const result = isolateMath(`\\begin{${env}}a\\end{${env}}`)
      expect(result.formulas, env).toHaveLength(1)
    }
  })

  it('环境没闭合时整段挂起(等下一块流式文本)', () => {
    const result = isolateMath('前文 \\begin{align} a&=b')
    expect(result.formulas[0]).toMatchObject({ pending: true, display: true })
    expect(result.text).toBe(`前文 ${result.formulas[0].token}`)
  })

  it('已经是行内的 $$...$$ 里带 align 时升级成块级', () => {
    const result = isolateMath('$$\\begin{aligned}a\\end{aligned}$$')
    expect(result.formulas[0].display).toBe(true)
  })

  it('不认识的 \\begin{foo} 不当公式', () => {
    expect(isolateMath('\\begin{foo}a\\end{foo}').formulas).toEqual([])
  })

  it('\\begin 前面有转义反斜杠时不当环境起点', () => {
    expect(isolateMath('\\\\begin{align}a\\end{align}').formulas).toEqual([])
  })
})

describe('restoreMathSource / splitIsolatedMath / normalizeMathDelimiters', () => {
  it('restoreMathSource 把 token 还原成原始文本(公式与待定都还原)', () => {
    const isolated = isolateMath('$a$ 与 $b^')
    expect(restoreMathSource(isolated.text, isolated.formulas)).toBe('$a$ 与 $b^')
  })

  it('没有公式时 splitIsolatedMath 直接返回单段文本', () => {
    expect(splitIsolatedMath('纯文本', [])).toEqual(['纯文本'])
  })

  it('splitIsolatedMath 把文本与公式交替切开', () => {
    const isolated = isolateMath('前 $a$ 中 $b$ 后')
    const parts = splitIsolatedMath(isolated.text, isolated.formulas)
    expect(parts).toHaveLength(5)
    expect(parts[0]).toBe('前 ')
    expect(typeof parts[1]).toBe('object')
    expect(parts[4]).toBe(' 后')
  })

  it('splitIsolatedMath 里 token 出现在开头/结尾也能正确切', () => {
    const isolated = isolateMath('$a$ 结尾')
    const parts = splitIsolatedMath(isolated.text, isolated.formulas)
    expect(typeof parts[0]).toBe('object')
    expect(parts[1]).toBe(' 结尾')
  })

  it('normalizeMathDelimiters 把 \\(..\\) 统一成 $..$', () => {
    expect(normalizeMathDelimiters('求 \\(x+1\\) 的值')).toBe('求 $x+1$ 的值')
  })

  it('normalizeMathDelimiters 保持块级为 $$..$$', () => {
    expect(normalizeMathDelimiters('\\[x+1\\]')).toBe('$$x+1$$')
  })

  it('normalizeMathDelimiters 不动待定公式(等流式补全)', () => {
    expect(normalizeMathDelimiters('算 $x^')).toBe('算 $x^')
  })

  it('normalizeMathDelimiters 不动代码块里的内容', () => {
    expect(normalizeMathDelimiters('`\\(x\\)`')).toBe('`\\(x\\)`')
  })
})

