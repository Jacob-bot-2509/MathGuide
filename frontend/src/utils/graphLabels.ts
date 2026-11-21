export function chapterLabel(chapter: string, language: string, chaptersEn: Record<string, string> = {}): string {
  return language === 'en' ? chaptersEn[chapter] || chapter : chapter
}

export function displayName(node: { name: string; nameEn?: string }, language: string): string {
  return language === 'en' ? node.nameEn || node.name : node.name
}

export function matchesGraphNode(node: { name: string; nameEn?: string; id: string; chapter: string }, term: string, chaptersEn: Record<string, string> = {}): boolean {
  const query = term.trim().toLowerCase()
  return [node.name, node.nameEn ?? '', node.id, node.chapter, chapterLabel(node.chapter, 'en', chaptersEn)]
    .some(value => value.toLowerCase().includes(query))
}

export function graphViewBounds(points: { x: number; y: number }[], aspect: number) {
  const minX = Math.min(...points.map(point => point.x)) - 98
  const maxX = Math.max(...points.map(point => point.x)) + 98
  const minY = Math.min(...points.map(point => point.y)) - 38
  const maxY = Math.max(...points.map(point => point.y)) + 38
  let w = Math.max(760, maxX - minX)
  let h = Math.max(480, maxY - minY)
  if (w / h > aspect) h = w / aspect
  else w = h * aspect
  return { x: (minX + maxX - w) / 2, y: (minY + maxY - h) / 2, w, h }
}

export function initialGraphView(points: { x: number; y: number }[], aspect: number, viewportWidth: number, narrow: boolean, full = false) {
  const bounds = graphViewBounds(points, aspect)
  if (!narrow || full || !viewportWidth) return bounds
  // 最小可读缩放:12.5px 字号渲染后不低于 8px,即 view.w 不超过视口宽 ×1.5625
  const maxWidth = viewportWidth * 1.5625
  const w = Math.min(bounds.w, maxWidth)
  const h = w / aspect
  // 以内容范围中心取景,再夹回内容边界内,避免露出大片空白
  const cx = bounds.x + bounds.w / 2
  const cy = bounds.y + bounds.h / 2
  return {
    x: Math.min(Math.max(cx - w / 2, bounds.x), bounds.x + bounds.w - w),
    y: Math.min(Math.max(cy - h / 2, bounds.y), bounds.y + bounds.h - h),
    w,
    h,
  }
}

export function wrapGraphLabel(text: string, measure: (text: string) => number, width = 138): string[] {
  const chars = Array.from(text)
  const lines: string[] = []
  for (let row = 0; row < 2 && chars.length; row++) {
    let line = ''
    while (chars.length && measure(line + chars[0]) <= width) line += chars.shift()
    if (!line && chars.length) line = chars.shift()!
    if (row === 0 && chars.length) {
      const space = line.lastIndexOf(' ')
      if (space > 0) {
        chars.unshift(...Array.from(line.slice(space + 1)))
        line = line.slice(0, space)
      }
      while (chars[0] === ' ') chars.shift()
    }
    if (row === 1 && chars.length) {
      while (line && measure(line.trimEnd() + '…') > width) line = line.slice(0, -1)
      line = line.trimEnd() + '…'
    }
    lines.push(line)
  }
  return lines
}
