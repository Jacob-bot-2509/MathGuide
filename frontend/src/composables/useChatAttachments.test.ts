/**
 * useChatAttachments 单测(node 环境):附件入库的三条输入通道与配额/分流分支。
 *
 * 这些分支平时要真传 PDF、真拖 4 个文件、真在科研区拖论文才碰得到,
 * 这里用假 deps + 假 File 精确驱动。
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'

const mocks = vi.hoisted(() => ({
  compressImage: vi.fn(async () => 'data:image/png;base64,AAA'),
  extractPdfText: vi.fn(async () => ''),
}))

vi.mock('@/utils/avatar', () => ({ compressImage: mocks.compressImage }))
vi.mock('@/utils/fileText', () => ({ extractPdfText: mocks.extractPdfText }))

import { useChatAttachments, type ChatAttachmentDeps } from '@/composables/useChatAttachments'
import { FALLBACK_CATEGORY } from '@/utils/classifier'
import { t } from '@/utils/i18n'
import type { ChatMsg, ChatSession } from '@/stores/sessions'

function makeHarness(overrides: Partial<ChatAttachmentDeps> = {}) {
  const session: ChatSession = { id: 1, messages: [] }
  const state = {
    session,
    toasts: [] as string[],
    flushOk: true,
    flushCalls: 0,
    cancelled: [] as number[],
    scheduled: [] as Array<{ prompt: string; delay: number }>,
    staged: [] as string[],
    closedMenu: 0,
    nextId: 100,
  }

  const deps: ChatAttachmentDeps = {
    isResearch: () => false,
    isTouchDevice: false,
    closeAttachMenu: () => { state.closedMenu += 1 },
    activeSession: () => session,
    createSession: () => session,
    nextMsgId: () => state.nextId++,
    cancelReply: (id) => state.cancelled.push(id),
    scheduleStream: (_s, _r, prompt, delay) => { state.scheduled.push({ prompt, delay }) },
    history: () => [],
    scrollBottom: () => {},
    pinToBottom: () => {},
    flush: () => { state.flushCalls += 1; return state.flushOk },
    toast: (message) => state.toasts.push(message),
    stagePaper: async (file) => { state.staged.push(file.name) },
    ...overrides,
  }

  return { state, deps, api: useChatAttachments(deps) }
}

function fileOf(name: string, type: string, content = 'body'): File {
  return new File([content], name, { type })
}

beforeEach(() => {
  mocks.compressImage.mockClear()
  mocks.extractPdfText.mockReset()
  mocks.extractPdfText.mockResolvedValue('')
})

describe('useChatAttachments 附件消息', () => {
  it('附件入库:追加「用户附件 + 助手占位」两条并立刻落盘', () => {
    const { state, api } = makeHarness()

    api.attachMessage({ kind: 'file', name: 'a.txt', size: 4, text: 'x' }, 'a.txt')

    expect(state.session.messages).toHaveLength(2)
    expect(state.session.messages[0].role).toBe('user')
    expect(state.session.messages[0].attachment?.name).toBe('a.txt')
    expect(state.session.messages[1].streaming).toBe(true)
    expect(state.flushCalls).toBe(1)
    // 带正文的附件把正文拼进提示词,后端据此阅读理解
    expect(state.scheduled[0].prompt).toContain('[attach:file]a.txt')
    expect(state.scheduled[0].prompt).toContain('x')
    expect(state.scheduled[0].delay).toBe(450)
  })

  it('未分类会话归入未归类(面板上能按板块找到)', () => {
    const { state, api } = makeHarness()
    api.attachMessage({ kind: 'file', name: 'a.txt', size: 4 }, 'a.txt')
    expect(state.session.cat).toBe(FALLBACK_CATEGORY)
  })

  it('配额写满时明确提示,不静默丢记录', () => {
    const { state, api } = makeHarness()
    state.flushOk = false

    api.attachMessage({ kind: 'file', name: 'a.txt', size: 4 }, 'a.txt')

    expect(state.toasts).toContain(t('learn.toastStorage'))
  })

  it('欢迎语还在流式时:先取消并顶掉它,避免附件排在欢迎语后面', () => {
    const { state, api } = makeHarness()
    const welcome: ChatMsg = { id: 1, role: 'assistant', content: '', streaming: true }
    state.session.messages.push(welcome)

    api.attachMessage({ kind: 'file', name: 'a.txt', size: 4 }, 'a.txt')

    expect(state.cancelled).toEqual([1])
    expect(state.session.messages.some((m) => m.id === 1)).toBe(false)
  })
})

describe('useChatAttachments 三条输入通道', () => {
  it('图片:压缩后按 image 附件入库(相册/拍照/拖入/粘贴共用)', async () => {
    const { state, api } = makeHarness()

    await api.importImageFile(fileOf('shot.png', 'image/png'))

    expect(mocks.compressImage).toHaveBeenCalled()
    const attach = state.session.messages[0].attachment
    expect(attach?.kind).toBe('image')
    expect(attach?.url).toBe('data:image/png;base64,AAA')
  })

  it('文本文件:正文截断到 3 万字随附件保存', async () => {
    const { state, api } = makeHarness()
    const long = 'x'.repeat(31000)

    await api.attachFileItem(fileOf('note.md', 'text/markdown', long))

    const attach = state.session.messages[0].attachment
    expect(attach?.text?.length).toBe(30000)
  })

  it('扫描版 PDF(无文本层):按普通文件接收并提示', async () => {
    const { state, api } = makeHarness()
    mocks.extractPdfText.mockResolvedValue('')

    await api.attachFileItem(fileOf('scan.pdf', 'application/pdf'))

    expect(state.session.messages[0].attachment?.text).toBeUndefined()
    expect(state.toasts).toContain(t('learn.toastPdfNoText'))
  })

  it('有文本层的 PDF:正文进附件', async () => {
    const { state, api } = makeHarness()
    mocks.extractPdfText.mockResolvedValue('PDF 正文')

    await api.attachFileItem(fileOf('paper.pdf', 'application/pdf'))

    expect(state.session.messages[0].attachment?.text).toBe('PDF 正文')
  })

  it('科研区的论文文件走临时语料,不进对话附件', async () => {
    const { state, api } = makeHarness({ isResearch: () => true })

    api.onFile({ target: { files: [fileOf('p.pdf', 'application/pdf')], value: '' } } as unknown as Event)
    await Promise.resolve()

    expect(state.staged).toEqual(['p.pdf'])
    expect(state.session.messages).toHaveLength(0)
  })

  it('学习区的同一个 PDF 走普通附件', async () => {
    const { state, api } = makeHarness()
    mocks.extractPdfText.mockResolvedValue('正文')

    api.onFile({ target: { files: [fileOf('p.pdf', 'application/pdf')], value: '' } } as unknown as Event)
    await Promise.resolve()
    await Promise.resolve()

    expect(state.staged).toEqual([])
    expect(state.session.messages.length).toBeGreaterThan(0)
  })

  it('拖入超过 3 个文件:提示且一个都不入库', async () => {
    const { state, api } = makeHarness()
    const files = ['a.txt', 'b.txt', 'c.txt', 'd.txt'].map((n) => fileOf(n, 'text/plain'))

    await api.onDropFiles({
      dataTransfer: { files },
      preventDefault: () => {},
    } as unknown as DragEvent)

    expect(state.toasts).toContain(t('learn.toastDropTooMany'))
    expect(state.session.messages).toHaveLength(0)
  })

  it('触屏设备忽略拖拽(用粘贴导入替代)', async () => {
    const { state, api } = makeHarness({ isTouchDevice: true })

    await api.onDropFiles({
      dataTransfer: { files: [fileOf('a.txt', 'text/plain')] },
      preventDefault: () => {},
    } as unknown as DragEvent)

    expect(state.session.messages).toHaveLength(0)
  })

  it('在输入框粘贴图片:拦下默认行为并直接作为附件', async () => {
    const { state, api } = makeHarness()
    let prevented = false

    api.onPaste({
      clipboardData: { items: [{ kind: 'file', getAsFile: () => fileOf('p.png', 'image/png') }] },
      preventDefault: () => { prevented = true },
    } as unknown as ClipboardEvent)
    await Promise.resolve()

    expect(prevented).toBe(true)
    expect(state.session.messages[0].attachment?.kind).toBe('image')
  })

  it('fmtSize 按量级切换单位', () => {
    const { api } = makeHarness()
    expect(api.fmtSize(undefined)).toBe('')
    expect(api.fmtSize(512)).toBe('512 B')
    expect(api.fmtSize(2048)).toBe('2.0 KB')
    expect(api.fmtSize(3 * 1024 * 1024)).toBe('3.0 MB')
  })
})
