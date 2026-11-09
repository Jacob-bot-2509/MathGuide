/**
 * Isolate complete math and the unfinished streaming suffix before Markdown.
 * Call again with the complete buffered source whenever a new chunk arrives.
 */
export interface IsolatedFormula {
  token: string
  source: string
  latex: string
  display: boolean
  pending: boolean
}

export interface IsolatedMath {
  text: string
  formulas: IsolatedFormula[]
}

function escaped(text: string, index: number): boolean {
  let count = 0
  while (index > 0 && text[--index] === '\\') count++
  return count % 2 === 1
}

function isDollarMath(latex: string, before: string, after: string): boolean {
  const value = latex.trim()
  if (!value || /\n\s*\n/.test(value) || (value.length > 300 && /^[A-Za-z]/.test(after))) return false
  if (/[\u3400-\u9fff\uf900-\ufaff]/.test(value)
      && !/\\[a-zA-Z]+|[=^_<>+\-*/]/.test(value)) return false
  if (!/[\\^_=<>+\-*/()[\]{}0-9a-zA-Z]/.test(value)) return false
  if (/\b(?:and|or)\b/i.test(value)) return false
  if (/^\d[\d,.]*$/.test(value)) {
    const next = after.trimStart().charAt(0)
    if ((next && '元块美圆¥￥'.includes(next))
        || /(价格|售价|花费|便宜|贵|折|￥|¥)\s*$/.test(before)) return false
  }
  return true
}

/** Undo Markdown escaping only when the environment name proves it was escaped. */
export function prepareMath(tex: string): string {
  if (tex.trim() === String.raw`\(` || tex.trim() === String.raw`\)`) return tex.trim().slice(1)
  if (/\\(?:begin|end)\{[A-Za-z]+\\\*\}/.test(tex)) {
    tex = tex.replace(/(\\(?:begin|end)\{[A-Za-z]+)\\\*(\})/g, '$1*$2')
    tex = tex.split(/(\\(?:text|mathrm|operatorname|mathtt|mbox)\s*\{(?:[^{}]|\{[^{}]*\})*\})/g).map((part, index) =>
      index % 2 ? part : part.replace(/\\_(?=[{0-9])/g, '_')
        .replace(/\\\\,/g, '\\,').replace(/\\\\\\(?=\s*&)/g, '\\\\'),
    ).join('')
  }
  // Translations can repeat a geometry symbol around an already delimited formula.
  const duplicate = tex.match(/^\s*(\\(?:triangle|angle))\s*\\{1,2}\(\s*(\1\b[\s\S]*?)\\{1,2}\)\s*$/)
  if (duplicate) tex = duplicate[2]
  const nested = tex.trim().match(/^(?:\\{1,2}\(([\s\S]+?)\\{1,2}\)|\\{1,2}\[([\s\S]+?)\\{1,2}\])$/)
  if (nested) tex = nested[1] ?? nested[2]
  tex = tex.split(/(\\(?:text|mathrm|operatorname|mathtt|mbox)\s*\{(?:[^{}]|\{[^{}]*\})*\})/g)
    .map((part, index) => {
      if (index % 2) return /^\\(?:text|mbox)\s*\{/.test(part) ? part.replace(/(?<!\\)_/g, '\\_') : part
      const escapedEnv = /(?<!\\)\\\\(?:begin|end)\{/.test(part)
      part = part.replace(/(?<!\\)\\\\(?=(?:begin|end|frac|dfrac|tfrac|sqrt|leqslant|geqslant|leq|geq|left|right|boxed|cdot|times|sin|cos|tan)\b)/g, '\\')
      if (escapedEnv) part = part.replace(/(?<!\\)\\{4}(?!\\)/g, '\\\\')
      if (part.includes('\\\\{') && part.includes('\\\\}')) {
        part = part.replaceAll('\\\\{', '\\{').replaceAll('\\\\}', '\\}')
      }
      return part.replace(/\\root\s*(\d+)\s*\\of\s*/g, '\\sqrt[$1]')
        .replace(/\\renewcommand\s*\{\\arraystretch\}\s*\{([^{}]+)\}/g, '\\def\\arraystretch{$1}')
        .replace(/(?<![A-Za-z\\])_([A-Za-z])_(?![A-Za-z0-9])/g, '$1')
        .replace(/\\\[([^\[\]]*?)\\\]/g, '[$1]')
        .replaceAll('^{\\*}', '^{*}').replaceAll('\\\u221a', '\\surd')
    }).join('')
  return tex.replace(/\\amp\b/g, '&')
}

/** Tokens are unique to the input and contain no Markdown syntax. */
export function isolateMath(source: string): IsolatedMath {
  let prefix = 'MGFORMULATOKEN'
  while (source.includes(prefix)) prefix += 'X'
  const formulas: IsolatedFormula[] = []
  let output = ''
  let i = 0

  const protect = (original: string, latex: string, display: boolean, pending: boolean) => {
    const token = prefix + formulas.length + 'END'
    formulas.push({ token, source: original, latex, display, pending })
    output += token
  }

  while (i < source.length) {
    // Preserve literal code spans and fences.
    if (source[i] === '`' && !escaped(source, i)) {
      let end = i
      while (source[end] === '`') end++
      const ticks = source.slice(i, end)
      const close = source.indexOf(ticks, end)
      const newline = source.indexOf('\n', end)
      const until = close < 0
        ? (ticks.length >= 3 || newline < 0 ? source.length : newline)
        : close + ticks.length
      output += source.slice(i, until)
      i = until
      continue
    }

    // Standalone AMS environments are common in the exercise bank.
    if (source[i] === '\\' && !escaped(source, i)) {
      const env = source.slice(i).match(/^\\begin\{((?:equation|align|alignat|gather|multline|flalign)(?:\\?\*)?|aligned|alignedat|gathered|split|array|cases|[pbBvV]?matrix|displaymath)\}/)
      if (env) {
        const name = env[1].replace('\\*', '*')
        const ends = ['\\end{' + name + '}']
        if (name.endsWith('*')) ends.push('\\end{' + name.slice(0, -1) + '\\*}')
        const matches = ends.map(marker => ({ marker, pos: source.indexOf(marker, i + env[0].length) }))
          .filter(match => match.pos >= 0).sort((a, b) => a.pos - b.pos)
        if (!matches.length) {
          protect(source.slice(i), '', true, true)
          break
        }
        const end = matches[0].pos + matches[0].marker.length
        const original = source.slice(i, end)
        protect(original, prepareMath(original), true, false)
        i = end
        continue
      }
    }

    // Adjacent inline formulas after an operator are often mistaken for display math.
    if (source[i] === '$' && !escaped(source, i)) {
      const adjacent = source.slice(i).match(/^\$(?!\$)([^$\n]+[+\-])\$\$(?!\$)([^$\n]+)(?<!\\)\$(?!\$)/)
      if (adjacent) {
        protect(adjacent[0], adjacent[1] + '{}' + adjacent[2], false, false)
        i += adjacent[0].length
        continue
      }
    }

    let openLength = 0
    let closer = ''
    let display = false
    if (source[i] === '$' && !escaped(source, i)) {
      display = source[i + 1] === '$'
      openLength = display ? 2 : 1
      closer = display ? '$$' : '$'
    } else if (source[i] === '\\' && !escaped(source, i)) {
      let end = i
      while (source[end] === '\\') end++
      const count = end - i
      if (count <= 2 && (source[end] === '(' || source[end] === '[')) {
        display = source[end] === '['
        closer = display ? ']' : ')'
        openLength = count + 1
      }
    }
    if (!openLength) {
      output += source[i++]
      continue
    }

    let end = i + openLength
    let closeLength = 0
    while (end < source.length) {
      if (closer[0] === '$') {
        if (source.startsWith(closer, end) && !escaped(source, end)
            && (closer === '$$' || (source[end - 1] !== '$' && source[end + 1] !== '$'))) {
          closeLength = closer.length
          break
        }
      } else if (source[end] === '\\' && !escaped(source, end)) {
        let slashEnd = end
        while (source[slashEnd] === '\\') slashEnd++
        if (slashEnd - end <= 2 && source[slashEnd] === closer) {
          closeLength = slashEnd - end + 1
          break
        }
        end = slashEnd
        continue
      }
      end++
    }

    if (!closeLength) {
      // Pending input is displayed as literal text until its closer arrives.
      protect(source.slice(i), '', display, true)
      break
    }
    const latex = source.slice(i + openLength, end)
    if (closer === '$' && !isDollarMath(latex, source.slice(Math.max(0, i - 8), i), source.slice(end + 1, end + 9))) {
      output += source.slice(i, i + openLength)
      i += openLength
      continue
    }
    const next = end + closeLength
    display ||= /^\s*\\begin\{(?:align|alignat|gather|equation|multline|flalign)\*?\}/.test(prepareMath(latex))
    protect(source.slice(i, next), latex, display, false)
    i = next
  }
  return { text: output, formulas }
}

/** Restore exact source after block splitting. */
export function restoreMathSource(text: string, formulas: IsolatedFormula[]): string {
  for (const formula of formulas) text = text.replaceAll(formula.token, () => formula.source)
  return text
}

/** Normalize only recognized delimiters, leaving code and incomplete math intact. */
export function normalizeMathDelimiters(source: string): string {
  const isolated = isolateMath(source)
  let text = isolated.text
  for (const formula of isolated.formulas) {
    const value = formula.pending ? formula.source : formula.display ? '$$' + formula.latex + '$$' : '$' + formula.latex + '$'
    text = text.replaceAll(formula.token, () => value)
  }
  return text
}

/** Resolve tokens as data; the caller renders math through Vue/KaTeX. */
export function splitIsolatedMath(text: string, formulas: IsolatedFormula[]): Array<string | IsolatedFormula> {
  if (!formulas.length) return [text]
  const lookup = new Map(formulas.map(formula => [formula.token, formula]))
  const pattern = new RegExp(formulas[0].token.replace(/\d+END$/, '') + '\\d+END', 'g')
  const result: Array<string | IsolatedFormula> = []
  let last = 0
  for (const match of text.matchAll(pattern)) {
    if (match.index > last) result.push(text.slice(last, match.index))
    result.push(lookup.get(match[0])!)
    last = match.index + match[0].length
  }
  if (last < text.length) result.push(text.slice(last))
  return result
}
