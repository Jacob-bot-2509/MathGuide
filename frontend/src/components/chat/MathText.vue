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

function parseInline(src: string): Seg[] {
  const segs: Seg[] = []
  // 三种公式写法:$$..$$ 块级、\(..\) 行内(LLM 与知识库常用)、$..$ 行内。
  // 行内 $ 只要求后一位不是数字 —— "$5 and $6" 金额仍被挡,
  // 而 "$ x > 0 $" 这类带空格的数学公式(LLM 实测会输出)能正常渲染。
  // 未闭合的公式不会匹配,留在纯文本里,闭合后自动渲染(流式友好)
  const re = /\$\$([\s\S]+?)\$\$|\\\(([\s\S]+?)\\\)|\$(?=[^0-9])([^$\n]+?)\$/g
  let last = 0
  let m: RegExpExecArray | null
  while ((m = re.exec(src))) {
    segs.push(...parseBold(src.slice(last, m.index)))
    if (m[1] !== undefined) segs.push({ type: 'mathd', value: m[1] })
    else if (m[2] !== undefined) segs.push({ type: 'math', value: m[2] })
    else segs.push({ type: 'math', value: m[3] })
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
