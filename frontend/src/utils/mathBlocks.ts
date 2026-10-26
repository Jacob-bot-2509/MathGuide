/**
 * 把流式正文切成「稳定块」,供 LearnView 用多个 MathText 分别渲染。
 *
 * 目的:流式输出时每个增量都会重渲染整条消息;把已完成的段落拆成独立块后,
 * 前面块的 text prop 不变,Vue 会跳过它们的解析/重渲染,只有最后一块在变。
 *
 * 切分规则(宁可不切,也不能切坏结构):
 * - 只在「不在 fenced code(```)内、不在块级公式($$...$$)内」的空行处切;
 * - 块尾保留空行,拼回去与原文逐字相同,pre-wrap 的段落间距不变;
 * - 未闭合的代码围栏/公式会留在最后一块,等闭合后再成为稳定块。
 */
export function splitStableBlocks(text: string): string[] {
  if (!text) return []

  const blocks: string[] = []
  let start = 0
  let inFence = false
  let inDisplay = false
  let i = 0

  while (i < text.length) {
    const newline = text.indexOf('\n', i)
    const end = newline === -1 ? text.length : newline
    const line = text.slice(i, end)
    const trimmed = line.trim()

    if (trimmed.includes('```')) {
      // 与 MathText 的代码块解析口径一致:同行出现两个 ``` 视为自闭合,不跨块
      const fences = (line.match(/```/g) || []).length
      if (fences % 2 === 1) inFence = !inFence
    } else if (!inFence) {
      const dollars = (line.match(/\$\$/g) || []).length
      if (dollars % 2 === 1) inDisplay = !inDisplay
      // MathText 也把 \[...\] 当块级公式;跨空行时必须保持完整
      const opens = (line.match(/\\\[/g) || []).length
      const closes = (line.match(/\\\]/g) || []).length
      if (opens !== closes) inDisplay = !inDisplay
      // \(...\) 在 MathText 里允许跨行(正则用 [\s\S]),同样不能切
      const parenOpens = (line.match(/\\\(/g) || []).length
      const parenCloses = (line.match(/\\\)/g) || []).length
      if (parenOpens !== parenCloses) inDisplay = !inDisplay
    }

    if (!inFence && !inDisplay && trimmed === '') {
      const cut = newline === -1 ? text.length : newline + 1
      const piece = text.slice(start, cut)
      if (piece.trim() === '' && blocks.length > 0) {
        // 连续空行并入上一块,避免产生只有空白的块
        blocks[blocks.length - 1] += piece
      } else {
        blocks.push(piece)
      }
      start = cut
    }

    i = newline === -1 ? text.length : newline + 1
  }

  if (start < text.length) blocks.push(text.slice(start))
  return blocks
}
