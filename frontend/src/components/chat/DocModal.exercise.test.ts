// @vitest-environment happy-dom
/**
 * 习题集面板:预览的那一批必须就是「生成」拿到的同一批。
 *
 * 预览只记录 batchIds;只有「换一批」才把当前批并入 excludeIds。
 * 若预览时就把 batchIds 写进 excludeIds,点「生成」会排除刚预览的那批,
 * 用户看到的预览与最终文档永远不是同一批题。
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, shallowMount } from '@vue/test-utils'

const planMock = vi.fn()
const generateMock = vi.fn()

vi.mock('@/services/docgenService', () => ({
  planExercises: (...args: unknown[]) => planMock(...args),
  generateExercises: (...args: unknown[]) => generateMock(...args),
  confirmExerciseExport: vi.fn(),
  deleteExerciseHistory: vi.fn(),
  exportQaDocument: vi.fn(),
  fetchDocQuestions: vi.fn(),
  fetchExerciseHistory: vi.fn(async () => []),
  fetchExerciseHistoryDocument: vi.fn(),
  generateDocument: vi.fn(),
  renderDocument: vi.fn(),
  requestOutline: vi.fn(),
  reviseDocument: vi.fn(),
}))

vi.mock('@/services/docService', () => ({ downloadBlob: vi.fn() }))
vi.mock('@/utils/toast', () => ({ showToast: vi.fn() }))

import DocModal from '@/components/chat/DocModal.vue'
import { nextShuffleSeed } from '@/utils/exerciseBatch'
import { t } from '@/utils/i18n'

const BATCH = ['ex-1', 'ex-2', 'ex-3']

function plan(batchIds: string[], seed: number) {
  return {
    available: { zh: 30, en: 30, both: 30 },
    selected: batchIds.length,
    missing: 0,
    gaps: [],
    seed,
    preview: batchIds.map((id, index) => ({
      id, topic: 'analysis', type: 'compute', question: `第 ${index + 1} 题`,
    })),
    batchIds,
    reusedCount: 0,
  }
}

function buttonByText(wrapper: ReturnType<typeof shallowMount>, text: string) {
  const found = wrapper.findAll('button').find((item) => item.text() === text)
  if (!found) throw new Error(`找不到按钮:${text}`)
  return found
}

async function openExercisePanel() {
  const wrapper = shallowMount(DocModal, {
    props: { messages: [], entries: [] },
    global: { stubs: { teleport: true } },
  })
  await wrapper.findAll('.choice')[2].trigger('click')  // 独立要求
  await wrapper.findAll('.kind-switch .fmt')[1].trigger('click')  // 习题集
  return wrapper
}

beforeEach(() => {
  planMock.mockReset()
  generateMock.mockReset()
  generateMock.mockResolvedValue({
    document: { title: '习题集', abstract: '', keywords: [], sections: [], references: [] },
    selected: BATCH.length,
    missing: 0,
    gaps: [],
    draftId: 'draft-1',
  })
})

describe('习题集预览与换批', () => {
  it('预览不会把本批写进排除列表,生成仍是同一批', async () => {
    planMock.mockResolvedValue(plan(BATCH, 20261106))
    const wrapper = await openExercisePanel()

    await buttonByText(wrapper, t('doc.exercisePreview')).trigger('click')
    await flushPromises()
    expect(planMock.mock.calls[0][0]).toMatchObject({ excludeIds: [], seed: 20261106 })
    expect(wrapper.find('.exercise-preview').exists()).toBe(true)

    await buttonByText(wrapper, t('doc.generate')).trigger('click')
    await flushPromises()
    expect(generateMock).toHaveBeenCalledTimes(1)
    const body = generateMock.mock.calls[0][0] as { excludeIds: string[]; seed: number }
    expect(body.excludeIds).toEqual([])
    expect(body.seed).toBe(20261106)
    wrapper.unmount()
  })

  it('换一批把上一批并入排除列表并推进 seed', async () => {
    planMock.mockResolvedValueOnce(plan(BATCH, 20261106))
    const wrapper = await openExercisePanel()
    await buttonByText(wrapper, t('doc.exercisePreview')).trigger('click')
    await flushPromises()

    planMock.mockResolvedValueOnce(plan(['ex-9'], nextShuffleSeed(20261106)))
    await buttonByText(wrapper, t('doc.exerciseShuffle')).trigger('click')
    await flushPromises()

    const second = planMock.mock.calls[1][0] as { excludeIds: string[]; seed: number }
    expect(second.excludeIds).toEqual(BATCH)
    expect(second.seed).toBe(nextShuffleSeed(20261106))

    // 生成用的是换批后的请求:同一个 seed + 同一份排除列表
    await buttonByText(wrapper, t('doc.generate')).trigger('click')
    await flushPromises()
    const body = generateMock.mock.calls[0][0] as { excludeIds: string[]; seed: number }
    expect(body.excludeIds).toEqual(BATCH)
    expect(body.seed).toBe(second.seed)
    wrapper.unmount()
  })
})
