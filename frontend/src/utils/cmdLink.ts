/**
 * `cmd://chapter/<章节名>` 链接解析。
 *
 * 章节名来自模型输出,百分号编码可能是畸形的(如 `%E0%A4%A`)。
 * `decodeURIComponent` 遇到非法转义会抛 URIError;这里退回原始文本,
 * 保证点击章节胶囊不会让整个事件处理器崩掉。
 */
const CHAPTER_PREFIX = 'cmd://chapter/'

export function chapterNameFromCmd(url: string): string | null {
  if (!url.startsWith(CHAPTER_PREFIX)) return null
  const raw = url.slice(CHAPTER_PREFIX.length).replace(/\?page=\d+$/, '')
  let name: string
  try {
    name = decodeURIComponent(raw)
  } catch {
    name = raw
  }
  return name || null
}

/** 页码只用于匹配本地书签，不信任模型自行给出的页码。 */
export function chapterPageFromCmd(url: string): number | null {
  if (!url.startsWith(CHAPTER_PREFIX)) return null
  const match = /\?page=(\d+)$/.exec(url)
  if (!match) return null
  const page = Number(match[1])
  return Number.isSafeInteger(page) ? page : null
}
