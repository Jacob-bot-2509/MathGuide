/** 附件接收入口:相册/拍照/文件、拖拽、粘贴、剪贴板导入,以及附件消息的生成。
 *
 * 抽出的原因:这一块是「外部输入 → 会话消息」的边界,和对话渲染、面板开关无关,
 * 但里面塞了 PDF 文本层、文本截断、图片压缩、配额立即落盘等易错细节。
 *
 * 边界约定:
 * - 选择菜单的开合与三个 <input> 的 DOM 引用留在组件(template ref 只能在组件里),
 *   这里通过 deps.closeAttachMenu 回关菜单;
 * - 会话写入、流式回复、落盘都注入,本模块不反向依赖组件。
 */
import { ref } from 'vue'
import { compressImage } from '@/utils/avatar'
import { FALLBACK_CATEGORY } from '@/utils/classifier'
import { extractPdfText } from '@/utils/fileText'
import { t } from '@/utils/i18n'
import type { ChatAttachment, ChatMsg, ChatSession } from '@/stores/sessions'
import type { ChatMeta } from '@/services/chatService'

/** 一次拖拽最多接收的文件数(start 提到 3:移动端相册多选常见 2~3 张) */
const MAX_DROP_FILES = 3
/** 粘贴文本上限(移动端一次粘贴整页讲义的量级) */
const PASTE_TEXT_MAX = 3000
/** 随附件保存的正文类型;上限 3 万字(发挥长上下文能力,移动端粘贴仍 3 千) */
const FILE_TEXT_EXT = /\.(txt|md|markdown)$/i
const FILE_TEXT_MAX = 30000
/** 论文类扩展名:科研区里这类文件走「临时语料 → 询问是否入库」 */
const PAPER_EXT = /\.(pdf|docx|epub|html?|xml|rtf|tex)$/i

export interface ChatAttachmentDeps {
  /** 科研区才把论文送进语料库,学习区一律当普通附件 */
  isResearch: () => boolean
  /** 触屏设备:用「粘贴导入」替代拖拽 */
  isTouchDevice: boolean
  /** 关掉附件选择菜单(pasteImport 从菜单里点出来) */
  closeAttachMenu: () => void
  activeSession: () => ChatSession | null
  createSession: (cat?: ChatSession['cat']) => ChatSession
  nextMsgId: () => number
  cancelReply: (id: number) => void
  scheduleStream: (
    session: ChatSession,
    reply: ChatMsg,
    prompt: string,
    delay: number,
    meta?: ChatMeta,
  ) => void
  history: (session: ChatSession, beforeId?: number) => ChatMeta['history']
  scrollBottom: (smooth?: boolean) => void
  pinToBottom: () => void
  /** 立即写盘并返回是否成功(附件可能很大,必须拿到真实配额结果) */
  flush: () => boolean
  toast: (message: string) => void
  /** 论文进入临时语料(解析成功后询问是否入库) */
  stagePaper: (file: File) => Promise<void>
}

export function useChatAttachments(deps: ChatAttachmentDeps) {
  /** 拖拽悬停中:显示放置遮罩 */
  const dragging = ref(false)
  let dragHideTimer: ReturnType<typeof setTimeout> | null = null

  /** 文件入库:PDF(pdfjs 提取文本层)/ 文本类(.txt/.md)读取正文随附件保存,其余仅元信息 */
  async function attachFileItem(file: File) {
    if (file.name.toLowerCase().endsWith('.pdf') || file.type === 'application/pdf') {
      try {
        const text = await extractPdfText(file)
        if (!text) {
          // 扫描版 PDF(无文本层):按普通文件接收并提示
          attachMessage({ kind: 'file', name: file.name, size: file.size }, file.name)
          deps.toast(t('learn.toastPdfNoText'))
          return
        }
        attachMessage({ kind: 'file', name: file.name, size: file.size, text }, file.name)
        return
      } catch {
        /* 解析失败按普通文件处理 */
      }
    }
    if (FILE_TEXT_EXT.test(file.name)) {
      try {
        const raw = await file.text()
        const capped = raw.trim().slice(0, FILE_TEXT_MAX)
        attachMessage({ kind: 'file', name: file.name, size: file.size, text: capped }, file.name)
        return
      } catch {
        /* 读取失败按普通文件处理 */
      }
    }
    attachMessage({ kind: 'file', name: file.name, size: file.size }, file.name)
  }

  /** 图片统一入库:压缩为缩略 dataURL 后作为图片附件发送(相册/拍照/拖入/粘贴共用) */
  async function importImageFile(file: File) {
    try {
      const url = await compressImage(file, 800)
      attachMessage({ kind: 'image', name: file.name, url, size: file.size }, file.name)
    } catch {
      deps.toast(t('acc.toastAvatarFail'))
    }
  }

  function isPaperFile(file: File): boolean {
    return file.type === 'application/pdf'
      || file.type.includes('wordprocessingml')
      || file.type === 'application/epub+zip'
      || PAPER_EXT.test(file.name)
  }

  /** 附件消息:留在当前会话(未分类会话归入未归类),MG 给出附件接收回复 */
  function attachMessage(attachment: ChatAttachment, content: string) {
    let session = deps.activeSession()
    if (!session) session = deps.createSession(FALLBACK_CATEGORY)
    if (!session.cat) session.cat = FALLBACK_CATEGORY
    if (session.messages.some((m) => m.streaming)) {
      if (!session.messages[0]?.streaming) return
      deps.cancelReply(session.messages[0].id)
      session.messages.shift()
    }

    const userMsg: ChatMsg = { id: deps.nextMsgId(), role: 'user', content, attachment }
    session.messages.push(userMsg)
    deps.pinToBottom()
    deps.scrollBottom()
    // 图片以 dataURL 随会话持久化:存储超限时明确提示,避免静默丢失记录。
    // 附件可能很大,必须立即写并拿到真实配额结果,不能等 debounce。
    if (!deps.flush()) deps.toast(t('learn.toastStorage'))

    const reply: ChatMsg = {
      id: deps.nextMsgId(), role: 'assistant', content: '', streaming: true, thinking: true,
    }
    session.messages.push(reply)
    // 同上:流式期间通过响应式代理更新,界面才能实时刷新
    const live = session.messages[session.messages.length - 1]
    // 契约 [attach:image|file]文件名;粘贴导入的文本带正文(空行分隔),后端交 LLM 阅读理解
    const attachPrompt = `[attach:${attachment.kind}]${attachment.name}`
      + `${attachment.text ? `\n\n${attachment.text}` : ''}`
    deps.scheduleStream(session, live, attachPrompt, 450, {
      sessionId: session.id,
      categoryKey: session.cat?.key,
      history: deps.history(session),
    })
  }

  function fmtSize(bytes?: number): string {
    if (bytes === undefined) return ''
    if (bytes < 1024) return `${bytes} B`
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
    return `${(bytes / 1024 / 1024).toFixed(1)} MB`
  }

  /* ---------- 三条输入通道:选择文件 / 拖拽 / 粘贴 ---------- */

  async function onImage(e: Event) {
    const input = e.target as HTMLInputElement
    const file = input.files?.[0]
    input.value = ''
    if (file) await importImageFile(file)
  }

  function onFile(e: Event) {
    const input = e.target as HTMLInputElement
    const file = input.files?.[0]
    input.value = ''
    if (!file) return
    if (deps.isResearch() && isPaperFile(file)) void deps.stagePaper(file)
    else attachFileItem(file)
  }

  function onDragOver(e: DragEvent) {
    if (deps.isTouchDevice || !e.dataTransfer?.types.includes('Files')) return
    e.preventDefault()
    dragging.value = true
    if (dragHideTimer) {
      clearTimeout(dragHideTimer)
      dragHideTimer = null
    }
  }

  /** dragleave 在子元素间穿梭时会频繁触发:延迟收尾,避免遮罩闪烁 */
  function onDragLeave() {
    if (dragHideTimer) clearTimeout(dragHideTimer)
    dragHideTimer = setTimeout(() => (dragging.value = false), 120)
  }

  async function onDropFiles(e: DragEvent) {
    if (deps.isTouchDevice) return
    if (dragHideTimer) clearTimeout(dragHideTimer)
    dragging.value = false
    const files = Array.from(e.dataTransfer?.files ?? [])
    if (!files.length) return
    e.preventDefault()
    if (files.length > MAX_DROP_FILES) {
      deps.toast(t('learn.toastDropTooMany'))
      return
    }
    for (const f of files) {
      if (f.type.startsWith('image/')) await importImageFile(f)
      else if (deps.isResearch() && isPaperFile(f)) await deps.stagePaper(f)
      else await attachFileItem(f)
    }
  }

  /** 输入框粘贴到剪贴板文件(截图/复制图片)时:不进输入框,直接作为附件导入 */
  function onPaste(e: ClipboardEvent) {
    const items = e.clipboardData?.items
    if (!items) return
    for (const item of items) {
      if (item.kind !== 'file') continue
      const f = item.getAsFile()
      if (!f) continue
      e.preventDefault()
      if (f.type.startsWith('image/')) importImageFile(f)
      else if (deps.isResearch() && isPaperFile(f)) void deps.stagePaper(f)
      else attachFileItem(f)
      return
    }
  }

  /** 移动端「粘贴导入」按钮:优先读剪贴板图片,退而读文本
      (作为 .txt 附件导入,正文随提示词交给模型阅读理解) */
  async function pasteImport() {
    deps.closeAttachMenu()
    // 剪贴板图片(截图/复制的图片)
    try {
      if (navigator.clipboard?.read) {
        const items = await navigator.clipboard.read()
        for (const item of items) {
          const imgType = item.types.find((ty) => ty.startsWith('image/'))
          if (!imgType) continue
          const blob = await item.getType(imgType)
          const ext = imgType.split('/')[1] || 'png'
          await importImageFile(new File([blob], `粘贴图片.${ext}`, { type: imgType }))
          return
        }
      }
    } catch {
      /* 无图片或未授权,继续尝试文本 */
    }
    // 剪贴板文本(复制的文档/题目/论文片段)
    try {
      const text = (await navigator.clipboard.readText()).trim()
      if (!text) {
        deps.toast(t('learn.toastPasteEmpty'))
        return
      }
      const capped = text.slice(0, PASTE_TEXT_MAX)
      attachMessage(
        { kind: 'file', name: '粘贴文本.txt', size: new Blob([capped]).size, text: capped },
        '粘贴文本.txt',
      )
    } catch {
      deps.toast(t('learn.toastPasteEmpty'))
    }
  }

  return {
    dragging,
    attachFileItem,
    importImageFile,
    isPaperFile,
    attachMessage,
    fmtSize,
    onImage,
    onFile,
    onDragOver,
    onDragLeave,
    onDropFiles,
    onPaste,
    pasteImport,
  }
}
