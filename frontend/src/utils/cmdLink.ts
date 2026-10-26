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
  const raw = url.slice(CHAPTER_PREFIX.length)
  let name: string
  try {
    name = decodeURIComponent(raw)
  } catch {
    name = raw
  }
  return name || null
}
