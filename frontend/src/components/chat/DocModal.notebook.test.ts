// @vitest-environment happy-dom
/**
 * 「在问题归纳中选择」必须能看到问题归纳面板里的历史问答,
 * 不能只认显式收进「问题记录」的词条。
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, shallowMount } from '@vue/test-utils'

const exportMock = vi.fn()
const downloadBlobMock = vi.fn()

vi.mock('@/services/docgenService', () => ({
  planExercises: vi.fn(),
  generateExercises: vi.fn(),
  confirmExerciseExport: vi.fn(),
  deleteExerciseHistory: vi.fn(),
  exportQaDocument: (...args: unknown[]) => exportMock(...args),
  fetchDocQuestions: vi.fn(),
  fetchExerciseHistory: vi.fn(async () => []),
  fetchExerciseHistoryDocument: vi.fn(),
  generateDocument: vi.fn(),
  renderDocument: vi.fn(),
  requestOutline: vi.fn(),
  reviseDocument: vi.fn(),
}))
vi.mock('@/services/docService', () => ({
  downloadBlob: (...args: unknown[]) => downloadBlobMock(...args),
}))
vi.mock('@/utils/toast', () => ({ showToast: vi.fn() }))

import DocModal from '@/components/chat/DocModal.vue'
import { t } from '@/utils/i18n'

function buttonByText(wrapper: ReturnType<typeof shallowMount>, text: string) {
  const found = wrapper.findAll('button').find((item) => item.text() === text)
  if (!found) throw new Error(`找不到按钮:${text}`)
  return found
}

async function openNotebookStep(historyQa: Array<{ key: string; question: string; answer: string }>) {
  const wrapper = shallowMount(DocModal, {
    props: { messages: [], entries: [], historyQa },
    global: { stubs: { teleport: true } },
  })
  await wrapper.findAll('.choice')[1].trigger('click')
  return wrapper
}

beforeEach(() => {
  exportMock.mockReset()
  exportMock.mockResolvedValue({ blob: new Blob(['x']), filename: 'x.pdf' })
  downloadBlobMock.mockReset()
})

describe('生成文档:在问题归纳中选择', () => {
  it('列出问题归纳中的历史问答,并可选中导出', async () => {
    const wrapper = await openNotebookStep([
      { key: 'h:1:11', question: '历史问题:求极限', answer: '历史回答' },
    ])
    const boxes = wrapper.findAll('input[type="checkbox"]')
    expect(boxes).toHaveLength(1)

    await boxes[0].trigger('change')
    await flushPromises()
    await buttonByText(wrapper, t('doc.generate')).trigger('click')
    await flushPromises()

    expect(exportMock).toHaveBeenCalledTimes(1)
    expect(exportMock.mock.calls[0][0]).toEqual([
      { question: '历史问题:求极限', answer: '历史回答' },
    ])
    wrapper.unmount()
  })

  it('与问题记录重复的问答只显示一次', async () => {
    const wrapper = shallowMount(DocModal, {
      props: {
        messages: [],
        entries: [{
          id: 1, question: '重复问题', answer: '重复回答',
          sessionId: 1, msgId: 1, createdAt: 1,
        }],
        historyQa: [{ key: 'h:1:1', question: '重复问题', answer: '重复回答' }],
      },
      global: { stubs: { teleport: true } },
    })
    await wrapper.findAll('.choice')[1].trigger('click')
    expect(wrapper.findAll('input[type="checkbox"]')).toHaveLength(1)
    wrapper.unmount()
  })
})
