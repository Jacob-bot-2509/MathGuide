<script lang="ts">
/**
 * 轻量富文本渲染:行内公式 $...$ / \(..\)、块级公式 $$...$$ / \[..\]、代码块 ```、加粗 **...**。
 * 流式输出中未闭合的公式会原样显示,闭合后自动渲染为 KaTeX。
 * 使用渲染函数输出,避免模板插值 VNode 数组带来的问题。
 */
import { defineComponent, h, type VNode } from 'vue'
import katex from 'katex'

interface Seg {
  type: 'text' | 'bold' | 'math' | 'mathd' | 'code' | 'link' | 'hr' | 'quote' | 'table'
  value: string
  href?: string
  header?: string[]
  rows?: string[][]
  aligns?: Array<'left' | 'center' | 'right'>
}

// 已闭合公式的渲染缓存:流式期间每帧只有最后一段在变化,
// 缓存使每次提交只渲染新公式,避免随正文增长的全量 KaTeX 重渲染
const katexCache = new Map<string, string>()
const KATEX_CACHE_MAX = 500

function escapeHtml(s: string): string {
  return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
}

function renderKatex(latex: string, display: boolean): string {
  const key = `${display ? 'd' : 'i'}|${latex}`
  const hit = katexCache.get(key)
  if (hit !== undefined) return hit
  let html = ''
  try {
    // throwOnError: true —— 语法有误(未闭合花括号、非法宏等)时抛异常走下方 catch,
    // 原样展示 LaTeX 源码;若用 false,KaTeX 会把错误渲染成红色 katex-error 文本,
    // 用户看到的是刺眼的报错而不是内容
    html = katex.renderToString(latex, { displayMode: display, throwOnError: true })
  } catch {
    // 渲染异常时不静默丢内容:原样展示 LaTeX 源码,保证任何符号都不会"凭空消失"
    html = `<code class="seg-math-raw">${escapeHtml(latex)}</code>`
  }
  if (katexCache.size >= KATEX_CACHE_MAX) katexCache.clear()
  katexCache.set(key, html)
  return html
}

function parseBold(src: string): Seg[] {
  const segs: Seg[] = []
  for (const part of src.split(/(\*\*[^*]+\*\*)/g)) {
    if (!part) continue
    if (part.startsWith('**') && part.endsWith('**') && part.length > 4) {
      segs.push({ type: 'bold', value: part.slice(2, -2) })
    } else {
      segs.push({ type: 'text', value: part })
    }
  }
  return segs
}

function looksLikeInlineMath(inner: string): boolean {
  const s = inner.trim()
  if (!s || s.length > 300) return false
  // 含中文时:必须是「公式里夹了说明文字」而不是「落单的 $ 吞了整段正文」。
  // 判据是出现 LaTeX 命令或数学运算符;纯汉字句子一律不渲染(否则 KaTeX
  // 会把整段中文当数学排版,既慢又乱)。
  if (/[㐀-鿿豈-﫿]/.test(s)) {
    return s.length <= 160 && /\\[a-zA-Z]+|[=^_<>+\-*/]/.test(s)
  }
  return /[\\^_=<>+\-*/()[\]{}0-9a-zA-Z]/.test(s)
}

function isMoneyMath(inner: string, before: string, after: string): boolean {
  // 金额保护:只挡真正的价格写法,不能因为 "$0$" 以数字开头就拒绝渲染。
  const s = inner.trim()
  if (!s) return false
  // "$5 and $6" 这种两个金额并列
  if (/\b(?:and|or)\b/i.test(s)) return true
  if (!/^\d[\d,.]*$/.test(s)) return false
  const next = after.trimStart().charAt(0)
  if ('元块美圆¥￥'.includes(next)) return true
  return /(价格|售价|花费|便宜|贵|折|￥|¥)\s*$/.test(before)
}

function parseInline(src: string): Seg[] {
  const segs: Seg[] = []
  // 四种公式写法:$$..$$ 与 \[..\] 块级、\(..\) 与 $..$ 行内(LLM 与知识库常用)。
  // 行内 $ 允许数字开头("$0$" 很常见),金额由 isMoneyMath 结合上下文排除。
  // 允许单个换行(模型常把一句公式折行),但禁止空行、限制 300 字,
  // 避免一个落单的 $ 把后面大段正文吞进公式。
  // 未闭合的公式不会匹配,留在纯文本里,闭合后自动渲染(流式友好)。
  const re = /\$\$([\s\S]+?)\$\$|\\\[([\s\S]+?)\\\]|\\\(([\s\S]+?)\\\)|\$(?!\$)((?:\n(?!\s*\n)|[^$\n]){1,300}?)\$/g
  let last = 0
  let m: RegExpExecArray | null
  while ((m = re.exec(src))) {
    if (m[4] !== undefined
        && (!looksLikeInlineMath(m[4])
          || isMoneyMath(m[4], src.slice(Math.max(0, m.index - 8), m.index),
            src.slice(m.index + m[0].length, m.index + m[0].length + 8)))) {
      continue
    }
    segs.push(...parseBold(src.slice(last, m.index)))
    if (m[1] !== undefined) segs.push({ type: 'mathd', value: m[1] })
    else if (m[2] !== undefined) segs.push({ type: 'mathd', value: m[2] })
    else if (m[3] !== undefined) segs.push({ type: 'math', value: m[3] })
    else segs.push({ type: 'math', value: m[4] })
    last = m.index + m[0].length
  }
  segs.push(...parseBold(src.slice(last)))
  // 纯文本段再拆行内链接(章节胶囊 / 返回按钮等可点击载体)
  const out: Seg[] = []
  for (const s of segs) {
    if (s.type !== 'text') {
      out.push(s)
      continue
    }
    out.push(...parseInlineLinks(s.value))
  }
  return out
}

// 行内 markdown 链接:[文字](url);解析失败按纯文本保留。
// 支持 cmd:// 内部契约链接(章节跳转 / 「返回」按钮),http(s) 为常规外链;
// cmd 链接允许空格(章节名带空格时仍可点击),http 链接保持常规约束
const LINK_RE = /\[([^\]\n]+)\]\((https?:\/\/[^)\s]+|cmd:\/\/[^)]+)\)/g

function parseInlineLinks(src: string): Seg[] {
  const segs: Seg[] = []
  let last = 0
  let m: RegExpExecArray | null
  while ((m = LINK_RE.exec(src))) {
    if (m.index > last) segs.push({ type: 'text', value: src.slice(last, m.index) })
    segs.push({ type: 'link', value: m[1], href: m[2] })
    last = m.index + m[0].length
  }
  if (last < src.length) segs.push({ type: 'text', value: src.slice(last) })
  return segs
}

function parse(src: string): Seg[] {
  const segs: Seg[] = []
  for (const part of src.split(/(```[\s\S]*?(?:```|$))/g)) {
    if (part.startsWith('```')) {
      segs.push({ type: 'code', value: part.replace(/^```[a-z]*\s*|\s*```$/g, '') })
      continue
    }
    // 单独成行的 --- → 分隔线(带捕获,奇数位置即分隔符)
    const blocks = part.split(/((?:^|\n)---(?:\n|$))/)
    for (let i = 0; i < blocks.length; i++) {
      if (i % 2 === 1) {
        segs.push({ type: 'hr', value: '' })
        continue
      }
      segs.push(...parseBlock(blocks[i]))
    }
  }
  return segs
}

/** 表格行拆分:数学公式/代码里的 | 不能当列分隔。 */
function splitTableRow(line: string): string[] {
  const cells: string[] = []
  let current = ''
  let math: '' | '$' | '$$' | '\\(' | '\\[' = ''
  let code = false
  for (let i = 0; i < line.length; i += 1) {
    const ch = line[i]
    const next = line[i + 1]
    if (code) {
      current += ch
      if (ch === '`') code = false
      continue
    }
    if (math) {
      if (math === '$' && ch === '$') {
        math = ''
        current += ch
        continue
      }
      if (math === '$$' && ch === '$' && next === '$') {
        math = ''
        current += '$$'
        i += 1
        continue
      }
      if ((math === '\\(' || math === '\\[') && ch === '\\') {
        const close = math === '\\(' ? ')' : ']'
        if (next === close) {
          math = ''
          current += `\\${next}`
          i += 1
          continue
        }
      }
      current += ch
      continue
    }
    if (ch === '`') {
      code = true
      current += ch
      continue
    }
    if (ch === '\\' && (next === '(' || next === '[')) {
      math = next === '(' ? '\\(' : '\\['
      current += `\\${next}`
      i += 1
      continue
    }
    if (ch === '\\') {
      // 转义字符整体保留,尤其 \| 不能拆列。
      current += ch
      if (next !== undefined) {
        current += next
        i += 1
      }
      continue
    }
    if (ch === '$') {
      math = next === '$' ? '$$' : '$'
      current += math
      if (math === '$$') i += 1
      continue
    }
    if (ch === '|') {
      cells.push(current.trim())
      current = ''
      continue
    }
    current += ch
  }
  cells.push(current.trim())
  if (cells.length && cells[0] === '') cells.shift()
  if (cells.length && cells[cells.length - 1] === '') cells.pop()
  return cells
}

function isTableSeparator(line: string): boolean {
  const cells = splitTableRow(line)
  // 常见模型会写 |:-:|:-:| 这种单横线对齐行;GFM 也接受 1 个以上横线。
  return cells.length > 0 && cells.every((cell) => /^:?-{1,}:?$/.test(cell))
}

function tableAligns(line: string): Array<'left' | 'center' | 'right'> {
  return splitTableRow(line).map((cell) => {
    if (cell.startsWith(':') && cell.endsWith(':')) return 'center'
    if (cell.endsWith(':')) return 'right'
    return 'left'
  })
}

/** 行级解析:表格优先,其次连续 > 引用块,其余走常规解析 */
function parseBlock(src: string): Seg[] {
  const segs: Seg[] = []
  let normal = ''
  let quote = ''
  const flushNormal = () => {
    if (normal.trim()) segs.push(...parseInline(normal))
    normal = ''
  }
  const flushQuote = () => {
    if (quote.trim()) segs.push({ type: 'quote', value: quote.trim() })
    quote = ''
  }
  const lines = src.split('\n')
  for (let i = 0; i < lines.length; i += 1) {
    const line = lines[i]
    if (line.includes('|') && i + 1 < lines.length
      && isTableSeparator(lines[i + 1])) {
      flushNormal()
      flushQuote()
      const header = splitTableRow(line)
      const aligns = tableAligns(lines[i + 1])
      const rows: string[][] = []
      let j = i + 2
      while (j < lines.length && lines[j].trim() && lines[j].includes('|')) {
        rows.push(splitTableRow(lines[j]))
        j += 1
      }
      segs.push({ type: 'table', value: '', header, rows, aligns })
      i = j - 1
      continue
    }
    if (line.startsWith('>')) {
      flushNormal()
      quote += `${line.slice(1).trim()}\n`
    } else {
      flushQuote()
      normal += `${line}\n`
    }
  }
  flushNormal()
  flushQuote()
  return segs
}

/** 链接节点:http(s) 外链 → <a> 新窗口打开;cmd:// 内部契约 → 可点击按钮
    (data-mg-cmd 携带契约地址,点击事件冒泡到对话列表统一处理) */
function renderLink(key: number | string, value: string, href: string | undefined): VNode {
  if (href?.startsWith('cmd://')) {
    if (href === 'cmd://back') {
      // 「返回」按钮:另起一行、右对齐的醒目黄框
      return h('div', { key, class: 'back-row' },
        h('button', { key, class: 'back-btn', type: 'button', 'data-mg-cmd': href }, value))
    }
    return h('button', { key, class: 'seg-cmd', type: 'button', 'data-mg-cmd': href }, value)
  }
  return h('a', { key, class: 'seg-link', href, target: '_blank', rel: 'noopener' }, value)
}

function inlineNodes(
  value: string,
  keyPrefix: string,
  inlineDisplayMath = false,
): VNode[] {
  return parseInline(value).map((seg, index) => {
    const key = `${keyPrefix}-${index}`
    if (seg.type === 'math') {
      return h('span', { key, class: 'seg-math', innerHTML: renderKatex(seg.value, false) })
    }
    if (seg.type === 'mathd') {
      // 表格单元格里的 $$...$$ 按行内排版,否则 display 公式会把一格撑成多行。
      return h('span', {
        key, class: inlineDisplayMath ? 'seg-math' : 'seg-mathd',
        innerHTML: renderKatex(seg.value, !inlineDisplayMath),
      })
    }
    if (seg.type === 'bold') return h('strong', { key }, seg.value)
    if (seg.type === 'link') return renderLink(key, seg.value, seg.href)
    return h('span', { key }, seg.value)
  })
}

function buildNodes(text: string): VNode[] {
  return parse(text).map((s, i) => {
    switch (s.type) {
      case 'text':
        return h('span', { key: i }, s.value)
      case 'bold':
        return h('strong', { key: i }, s.value)
      case 'code':
        return h('pre', { key: i, class: 'seg-code' }, h('code', null, s.value))
      case 'math':
        return h('span', { key: i, class: 'seg-math', innerHTML: renderKatex(s.value, false) })
      case 'mathd':
        return h('span', { key: i, class: 'seg-mathd', innerHTML: renderKatex(s.value, true) })
      case 'link':
        return renderLink(i, s.value, s.href)
      case 'hr':
        return h('hr', { key: i, class: 'seg-hr' })
      case 'quote':
        return h('div', { key: i, class: 'seg-quote' }, parseInlineLinks(s.value).map((x, j) =>
          x.type === 'link'
            ? renderLink(j, x.value, x.href)
            : h('span', { key: j }, x.value)))
      case 'table': {
        const header = s.header || []
        const rows = s.rows || []
        const aligns = s.aligns || []
        const align = (index: number): 'left' | 'center' | 'right' =>
          aligns[index] || 'left'
        return h('div', { key: i, class: 'seg-table-wrap' }, [
          h('table', { class: 'seg-table' }, [
            h('thead', null, [
              h('tr', null, header.map((cell, j) => h(
                'th', { key: j, style: { textAlign: align(j) } },
                inlineNodes(cell, `${i}-h-${j}`, true),
              ))),
            ]),
            h('tbody', null, rows.map((row, r) => h(
              'tr', { key: r },
              header.map((_cell, j) => h(
                'td', { key: j, style: { textAlign: align(j) } },
                inlineNodes(row[j] || '', `${i}-${r}-${j}`, true),
              )),
            ))),
          ]),
        ])
      }
    }
  })
}

export default defineComponent({
  name: 'MathText',
  props: {
    text: { type: String, required: true },
  },
  setup(props) {
    return () => h('div', { class: 'math-text' }, buildNodes(props.text))
  },
})
</script>

<style scoped>
.math-text {
  white-space: pre-wrap;
  word-break: break-word;
}

.seg-code {
  display: block;
  background: rgba(5, 8, 14, 0.7);
  border: 1px solid var(--line);
  border-radius: 8px;
  padding: 10px 14px;
  margin: 8px 0;
  overflow-x: auto;
  font-family: var(--font-tech);
  font-size: 13px;
}

.seg-math {
  padding: 0 2px;
}

/* 渲染失败时的 LaTeX 源码兜底展示 */
.seg-math-raw {
  color: var(--text-dim);
  font-family: var(--font-tech);
  font-size: 12px;
}

/* 可点击链接(引用跳转) */
.seg-link {
  color: var(--cyan);
  text-decoration: underline;
  word-break: break-all;
}

.seg-link:hover {
  color: var(--text-hi);
}

/* 可点击章节胶囊(章节导航列表) */
.seg-cmd {
  display: inline-block;
  margin: 2px 4px 2px 0;
  padding: 3px 12px;
  border: 1px solid var(--line-bright);
  border-radius: 999px;
  background: color-mix(in srgb, var(--cyan) 8%, transparent);
  color: var(--cyan);
  font-size: 13px;
  cursor: pointer;
  transition: all var(--dur-fast) var(--ease-out);
}

.seg-cmd:hover {
  background: color-mix(in srgb, var(--cyan) 18%, transparent);
  box-shadow: var(--glow-cyan);
}

/* 「返回」按钮行:章节指引末尾右对齐的醒目黄框 */
.back-row {
  display: flex;
  justify-content: flex-end;
  margin-top: 10px;
}

.back-btn {
  padding: 4px 16px;
  border: 1px solid #ffd166;
  border-radius: 6px;
  background: rgba(255, 209, 102, 0.12);
  color: #ffd166;
  font-size: 12px;
  cursor: pointer;
  letter-spacing: 0.1em;
  transition: all var(--dur-fast) var(--ease-out);
}

.back-btn:hover {
  background: rgba(255, 209, 102, 0.25);
  box-shadow: 0 0 10px rgba(255, 209, 102, 0.4);
}

/* 分隔线(正文与引用区之间) */
.seg-hr {
  border: none;
  border-top: 1px solid var(--line);
  margin: 12px 0;
}

.seg-table-wrap {
  margin: 10px 0;
  overflow-x: auto;
  border: 1px solid var(--line);
  border-radius: 8px;
}

.seg-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 12px;
  line-height: 1.6;
}

.seg-table th,
.seg-table td {
  padding: 6px 10px;
  border-bottom: 1px solid var(--line);
  vertical-align: top;
}

.seg-table th {
  color: var(--cyan);
  font-weight: 600;
  white-space: nowrap;
  background: color-mix(in srgb, var(--cyan) 6%, transparent);
}

.seg-table tbody tr:last-child td {
  border-bottom: none;
}

.seg-table .seg-math {
  white-space: nowrap;
}

/* 引用区:小字、醒目、可跳转(回答末尾的来源列表) */
.seg-quote {
  font-size: 12px;
  line-height: 1.6;
  color: var(--text-dim);
  border-left: 2px solid color-mix(in srgb, var(--cyan) 55%, transparent);
  padding-left: 10px;
  margin: 4px 0;
  word-break: break-word;
}

.seg-mathd {
  display: block;
  margin: 10px 0;
  overflow-x: auto;
}
</style>
