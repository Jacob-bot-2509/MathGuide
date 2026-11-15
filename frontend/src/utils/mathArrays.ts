/** Preserve TeX array layout when KaTeX does not support its column syntax. */
type Boundary = { rule: number; space: number }
type Cell = { value: string; span: number; align: string; left: number; right: number }
type Row = { cells: Cell[] } | { rule: [number, number] }

function group(source: string, start: number): { value: string; end: number } | null {
  while (/\s/.test(source[start] || '')) start++
  if (source[start] !== '{') return null
  let level = 1
  for (let i = start + 1; i < source.length; i++) {
    if (source[i] === '\\' && /[{}\\]/.test(source[i + 1] || '')) { i++; continue }
    if (source[i] === '{') level++
    if (source[i] === '}' && --level === 0) return { value: source.slice(start + 1, i), end: i + 1 }
  }
  return null
}

function expandColumns(source: string, depth = 0): string | null {
  if (depth > 4) return null
  let out = ''
  for (let i = 0; i < source.length; i++) {
    if (source[i] !== '*') { out += source[i]; continue }
    const count = source.slice(i + 1).match(/^\s*(\d+)/)
    if (!count || Number(count[1]) < 1 || Number(count[1]) > 20) return null
    const part = group(source, i + 1 + count[0].length)
    if (!part) return null
    const expanded = expandColumns(part.value, depth + 1)
    if (expanded === null) return null
    out += expanded.repeat(Number(count[1]))
    i = part.end - 1
  }
  return out
}

function columns(source: string): { aligns: string[]; boundaries: Boundary[] } | null {
  const spec = expandColumns(source)
  if (spec === null) return null
  const aligns: string[] = []
  const boundaries: Boundary[] = [{ rule: 0, space: 1 }]
  const spacing: Record<string, number> = { '': 0, '~': 0.3333, '\\,': 0.1667, '\\;': 0.2778, '\\quad': 1 }
  for (let i = 0; i < spec.length; i++) {
    const ch = spec[i]
    if (/\s/.test(ch)) continue
    if (ch === '|') { boundaries[aligns.length].rule++; continue }
    if (ch === '@') {
      const part = group(spec, i + 1)
      if (!part || !(part.value.trim() in spacing)) return null
      boundaries[aligns.length].space = spacing[part.value.trim()]
      i = part.end - 1
      continue
    }
    if (!'lcr'.includes(ch)) return null
    aligns.push(ch)
    if (aligns.length > 30) return null
    boundaries.push({ rule: 0, space: 1 })
  }
  return aligns.length ? { aligns, boundaries } : null
}

function splitTop(source: string, delimiter: '&' | '\\\\'): string[] | null {
  const parts: string[] = []
  let start = 0, depth = 0
  for (let i = 0; i < source.length; i++) {
    const ch = source[i]
    if (ch === '\\') {
      if (source.startsWith(delimiter, i) && depth === 0) {
        parts.push(source.slice(start, i)); i += delimiter.length - 1; start = i + 1; continue
      }
      if (/[{}\\&]/.test(source[i + 1] || '')) i++
      continue
    }
    if (ch === '{') depth++
    if (ch === '}' && --depth < 0) return null
    if (ch === delimiter && depth === 0) { parts.push(source.slice(start, i)); start = i + 1 }
  }
  if (depth !== 0) return null
  parts.push(source.slice(start))
  return parts
}

function rows(source: string, aligns: string[], boundaries: Boundary[]): Row[] | null {
  const rawRows = splitTop(source, '\\\\')
  if (!rawRows) return null
  const result: Row[] = []
  for (const [rowIndex, rawRow] of rawRows.entries()) {
    let row = rawRow.trim()
    while (row.startsWith('\\hline') || row.startsWith('\\cline')) {
      if (/^\\hline\b/.test(row)) { result.push({ rule: [1, aligns.length] }); row = row.replace(/^\\hline\b\s*/, ''); continue }
      const match = row.match(/^\\cline\s*\{\s*(\d+)\s*-\s*(\d+)\s*\}\s*/)
      if (!match) return null
      const first = Number(match[1]), last = Number(match[2])
      if (first < 1 || last < first || last > aligns.length) return null
      result.push({ rule: [first, last] }); row = row.slice(match[0].length)
    }
    if (!row && rowIndex === rawRows.length - 1) continue
    const rawCells = splitTop(row, '&')
    if (!rawCells) return null
    let index = 0
    const cells: Cell[] = []
    for (const raw of rawCells) {
      let value = raw.trim(), span = 1, align = aligns[index], left = boundaries[index]?.rule || 0, right = 0
      if (/^\\multicolumn\b/.test(value)) {
        let pos = value.indexOf('\\multicolumn') + '\\multicolumn'.length
        const n = group(value, pos); if (!n || !/^\d+$/.test(n.value.trim())) return null
        span = Number(n.value.trim()); pos = n.end
        const format = group(value, pos); if (!format || !/^\|*[lcr]\|*$/.test(format.value.trim())) return null
        pos = format.end
        const cell = group(value, pos); if (!cell || value.slice(cell.end).trim()) return null
        const fmt = format.value.trim()
        align = fmt.match(/[lcr]/)![0]
        left = fmt.startsWith('|') ? (fmt.startsWith('||') ? 2 : 1) : 0
        right = fmt.endsWith('|') ? (fmt.endsWith('||') ? 2 : 1) : 0
        value = cell.value
      } else {
        right = boundaries[index + 1]?.rule || 0
      }
      if (span < 1 || index + span > aligns.length || !align) return null
      cells.push({ value, span, align, left, right })
      index += span
    }
    while (index < aligns.length) {
      cells.push({ value: '', span: 1, align: aligns[index], left: boundaries[index].rule, right: boundaries[index + 1].rule })
      index++
    }
    result.push({ cells })
  }
  return result
}

/** Render a complete array using safe, separately rendered KaTeX cells. */
export function renderMathArray(source: string, renderCell: (tex: string) => string): string | null {
  const tex = source.trim(), begin = '\\begin{array}', end = '\\end{array}'
  if (!tex.startsWith(begin) || !tex.endsWith(end)) return null
  const spec = group(tex, begin.length)
  if (!spec || spec.end > tex.length - end.length) return null
  const layout = columns(spec.value)
  if (!layout) return null
  const body = tex.slice(spec.end, -end.length)
  if (/\\(?:begin|end)\s*\{/.test(body)) return null
  const parsed = rows(body, layout.aligns, layout.boundaries)
  if (!parsed) return null
  const border = (n: number) => n > 1 ? '3px double currentColor' : n ? '1px solid currentColor' : 'none'
  const align = (a: string) => ({ l: 'left', c: 'center', r: 'right' }[a] || 'center')
  let html = '<span class="mg-array" style="display:inline-block;max-width:100%;overflow-x:auto;vertical-align:middle"><table style="border-collapse:collapse;border-spacing:0;display:inline-table;vertical-align:middle">'
  for (const row of parsed) {
    if ('rule' in row) {
      html += '<tr aria-hidden="true">'
      for (let i = 0; i < layout.aligns.length; i++) {
        const line = i + 1 >= row.rule[0] && i + 1 <= row.rule[1] ? '1px solid currentColor' : 'none'
        html += `<td style="padding:0;height:0;line-height:0;border-top:${line}"></td>`
      }
      html += '</tr>'
      continue
    }
    let index = 0
    html += '<tr>'
    for (const cell of row.cells) {
      const leftSpace = layout.boundaries[index].space / 2
      const rightSpace = layout.boundaries[index + cell.span].space / 2
      const rendered = cell.value ? renderCell(cell.value) : ''
      html += `<td colspan="${cell.span}" style="padding:0 ${rightSpace}em 0 ${leftSpace}em;text-align:${align(cell.align)};border-left:${border(cell.left)};border-right:${border(cell.right)}">${rendered}</td>`
      index += cell.span
    }
    html += '</tr>'
  }
  return html + '</table></span>'
}
