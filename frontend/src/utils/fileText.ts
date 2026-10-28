/**
 * 文件正文提取:聊天附件与科研资料库共用。
 * PDF 懒加载 pdfjs(仅首次使用时拉取,主包体积不受影响)。
 */

/** PDF 文本层提取:页数上限 80、正文上限 max 字;超限截断而不是失败 */
export async function extractPdfText(file: File, max = 30000): Promise<string> {
  const pdfjs = await import('pdfjs-dist')
  const worker = await import('pdfjs-dist/build/pdf.worker.min.mjs?url')
  pdfjs.GlobalWorkerOptions.workerSrc = worker.default
  const doc = await pdfjs.getDocument({ data: await file.arrayBuffer() }).promise
  const parts: string[] = []
  const pages = Math.min(doc.numPages, 80) // 页数上限,防超大 PDF 拖垮页面
  for (let i = 1; i <= pages; i++) {
    const page = await doc.getPage(i)
    const content = await page.getTextContent()
    parts.push(content.items.map((it) => ('str' in it ? it.str : '')).join(' '))
  }
  const text = parts.join('\n').replace(/\s+/g, ' ').trim()
  return text.slice(0, max)
}

/** 纯文本类文件读取(截断到 max 字) */
export async function readTextFile(file: File, max = 30000): Promise<string> {
  const raw = await file.text()
  return raw.trim().slice(0, max)
}

/** 文本类扩展名(聊天附件与科研资料共用同一口径) */
export const TEXT_FILE_EXT = /\.(txt|md|markdown|tex|csv|json)$/i
