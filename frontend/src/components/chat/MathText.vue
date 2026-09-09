<script lang="ts">
/**
 * 轻量富文本渲染:行内公式 $...$、块级公式 $$...$$、代码块 ```、加粗 **...**。
 * 流式输出中未闭合的公式会原样显示,闭合后自动渲染为 KaTeX。
 * 使用渲染函数输出,避免模板插值 VNode 数组带来的问题。
 */
import { defineComponent, h, type VNode } from 'vue'
import katex from 'katex'

interface Seg {
  type: 'text' | 'bold' | 'math' | 'mathd' | 'code' | 'link' | 'hr' | 'quote'
  value: string
  href?: string
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
    html = katex.renderToString(latex, { displayMode: display, throwOnError: false })
  } catch {
    // 渲染异常(如 KaTeX 宏展开超限)时不静默丢内容:原样展示 LaTeX 源码,
    // 保证任何符号都不会"凭空消失"
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

function parseInline(src: string): Seg[] {
  const segs: Seg[] = []
  // 行内 $...$:内容不以数字/空白开头,避免把 "$5 and $6" 这类金额误判为公式
  const re = /\$\$([\s\S]+?)\$\$|\$(?=[^0-9\s])([^$\n]+?)\$/g
  let last = 0
  let m: RegExpExecArray | null
  while ((m = re.exec(src))) {
    segs.push(...parseBold(src.slice(last, m.index)))
    if (m[1] !== undefined) segs.push({ type: 'mathd', value: m[1] })
    else segs.push({ type: 'math', value: m[2] })
    last = m.index + m[0].length
  }
  segs.push(...parseBold(src.slice(last)))
  return segs
}

// 行内 markdown 链接:[文字](url);解析失败按纯文本保留
const LINK_RE = /\[([^\]\n]+)\]\((https?:\/\/[^)\s]+)\)/g

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

/** 行级解析:连续 > 开头的行为引用块(引用区小字样式),其余走常规解析 */
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
  for (const line of src.split('\n')) {
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
        return h('a', { key: i, class: 'seg-link', href: s.href, target: '_blank', rel: 'noopener' }, s.value)
      case 'hr':
        return h('hr', { key: i, class: 'seg-hr' })
      case 'quote':
        return h('div', { key: i, class: 'seg-quote' }, parseInlineLinks(s.value).map((x, j) =>
          x.type === 'link'
            ? h('a', { key: j, class: 'seg-link', href: x.href, target: '_blank', rel: 'noopener' }, x.value)
            : h('span', { key: j }, x.value)))
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

/* 分隔线(正文与引用区之间) */
.seg-hr {
  border: none;
  border-top: 1px solid var(--line);
  margin: 12px 0;
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
