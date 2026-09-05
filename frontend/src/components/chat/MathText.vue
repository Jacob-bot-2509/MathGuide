<script lang="ts">
/**
 * 轻量富文本渲染:行内公式 $...$、块级公式 $$...$$、代码块 ```、加粗 **...**。
 * 流式输出中未闭合的公式会原样显示,闭合后自动渲染为 KaTeX。
 * 使用渲染函数输出,避免模板插值 VNode 数组带来的问题。
 */
import { defineComponent, h, type VNode } from 'vue'
import katex from 'katex'

interface Seg {
  type: 'text' | 'bold' | 'math' | 'mathd' | 'code'
  value: string
}

// 已闭合公式的渲染缓存:流式期间每帧只有最后一段在变化,
// 缓存使每次提交只渲染新公式,避免随正文增长的全量 KaTeX 重渲染
const katexCache = new Map<string, string>()
const KATEX_CACHE_MAX = 500

function renderKatex(latex: string, display: boolean): string {
  const key = `${display ? 'd' : 'i'}|${latex}`
  const hit = katexCache.get(key)
  if (hit !== undefined) return hit
  let html = ''
  try {
    html = katex.renderToString(latex, { displayMode: display, throwOnError: false })
  } catch {
    /* 渲染失败返回空,保持正文可读 */
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

function parse(src: string): Seg[] {
  const segs: Seg[] = []
  for (const part of src.split(/(```[\s\S]*?(?:```|$))/g)) {
    if (part.startsWith('```')) {
      segs.push({ type: 'code', value: part.replace(/^```[a-z]*\s*|\s*```$/g, '') })
    } else {
      segs.push(...parseInline(part))
    }
  }
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

.seg-mathd {
  display: block;
  margin: 10px 0;
  overflow-x: auto;
}
</style>
