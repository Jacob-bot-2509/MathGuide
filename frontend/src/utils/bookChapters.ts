/**
 * 教材章节:书签补页码范围、按标题定位、切片、本地目录链接。
 *
 * 模型给的页码不可信(书上印的页码 ≠ PDF 页索引),所以目录页码只认 PDF 书签
 * 或本地逐页搜索;切片只在本章页范围内做,避免把下一章带进提示词。
 */

export interface BookChapterLite {
  title: string
  depth: number
  startPage: number
}

export interface BookChapter extends BookChapterLite {
  endPage: number
}

/** 标题归一化:去掉空白、标点与符号,保留中英文、数字与希腊字母 */
export function normalizeTitle(title: string): string {
  return title.toLowerCase().replace(/[^\p{L}\p{N}]/gu, '')
}

/** 书签补结束页:父章到下一个同级或更高级标题前结束 */
export function withRanges(outline: BookChapterLite[], pageCount: number): BookChapter[] {
  const items = outline
    .filter((item) => Number.isInteger(item.startPage) && item.startPage >= 0)
    .slice()
    .sort((a, b) => a.startPage - b.startPage || a.depth - b.depth)
  return items.map((item, index) => {
    const next = items
      .slice(index + 1)
      .find((other) => other.startPage > item.startPage && other.depth <= item.depth)
    const endPage = next ? next.startPage - 1 : pageCount - 1
    return { ...item, endPage: Math.max(item.startPage, Math.min(endPage, pageCount - 1)) }
  })
}

// 行首章标题:章号后必须有分隔符或行尾,避免把「第二章正文续」当成新章
const HEADING = /^\s*(?:第\s*[一二三四五六七八九十百千0-9]+\s*[章节](?:[\s:：·、.．-]|$)|Chapter\s+\d+(?:\s|:|$))/im

/** 找章节:书签精确 → 书签包含 → 逐页搜索标题 */
export function locateChapter(
  pages: string[],
  chapters: BookChapter[],
  title: string,
  page: number | null = null,
): BookChapter | null {
  const target = normalizeTitle(title)
  if (!target) return null
  if (page !== null) {
    return chapters.find((item) => item.startPage === page && item.title === title) ?? null
  }
  const exact = chapters.filter((item) => normalizeTitle(item.title) === target)
  if (exact.length) return exact.length === 1 ? exact[0] : null
  const loose = chapters.filter((item) => {
    const norm = normalizeTitle(item.title)
    return norm && (norm.includes(target) || target.includes(norm))
  })
  if (loose.length) return loose.length === 1 ? loose[0] : null

  const matches = pages.flatMap((page, index) => normalizeTitle(page).includes(target) ? [index] : [])
  // 标题也可能出现在目录或页眉; 多处命中时不能把第一处当成正文。
  if (matches.length !== 1) return null
  const startPage = matches[0]
  const next = chapters.find((item) => item.startPage > startPage)
  let nextStart = next?.startPage ?? -1
  if (nextStart < 0) {
    for (let i = startPage + 1; i < pages.length; i += 1) {
      if (HEADING.test(pages[i])) {
        nextStart = i
        break
      }
    }
  }
  // 无法确认章末且剩余超过 30 页时，不能把截取的前 30 页当成完整章节。
  if (nextStart < 0 && pages.length - startPage > 30) return null
  const endPage = nextStart > startPage ? nextStart - 1 : pages.length - 1
  return { title, depth: 0, startPage, endPage }
}

/** 章节原文切片:按页拼,超上限截断而不是失败 */
export function sliceChapter(
  pages: string[],
  chapter: BookChapter,
  maxChars = 200_000,
): { text: string; truncated: boolean } {
  const start = Math.max(0, Math.min(chapter.startPage, pages.length - 1))
  const end = Math.max(start, Math.min(chapter.endPage, pages.length - 1))
  const text = pages.slice(start, end + 1).join('\n')
  if (text.length <= maxChars) return { text, truncated: false }
  const before = text.charCodeAt(maxChars - 1)
  const after = text.charCodeAt(maxChars)
  const splitsCharacter = before >= 0xd800 && before <= 0xdbff && after >= 0xdc00 && after <= 0xdfff
  return { text: text.slice(0, splitsCharacter ? maxChars - 1 : maxChars), truncated: true }
}

/** 本地目录:每章一行可点击链接;标题里的方括号转义,避免提前闭合链接 */
export function buildChapterMarkdown(chapters: BookChapter[]): string {
  return chapters
    .map((chapter) => {
      const label = chapter.title.replace(/[[\]]/g, '\\$&')
      const duplicate = chapters.some((other) => other !== chapter && other.title === chapter.title)
      const href = `cmd://chapter/${encodeURIComponent(chapter.title)}${duplicate ? `?page=${chapter.startPage}` : ''}`
      return `${'  '.repeat(Math.max(0, chapter.depth))}[${label}](${href})`
    })
    .join('\n')
}

/** 缓存键:同名章节靠页码范围区分 */
export function chapterKey(chapter: BookChapter): string {
  return `${normalizeTitle(chapter.title)}@${chapter.startPage}-${chapter.endPage}`
}
