/**
 * 图解放大手势(vitest):浮层的缩放吸附、全屏后锁定、下滑关闭。
 *
 * 组件拆分前这些行为只有人工冒烟验证,`ChatWorkspace` 一改就没人守。
 * 这里直接驱动 composable 的 pointer 事件,断言「状态怎么变」而不是 CSS。
 *
 * 环境说明:vitest 跑在 node 下,所以 window/document 用 stub;
 * 事件对象只填处理函数真正读到的字段(clientX/clientY/pointerId)。
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ref } from 'vue'
import type { DiagramBlock } from '@/utils/diagramSpec'

type Pointer = {
  pointerId: number
  pointerType: string
  clientX: number
  clientY: number
  currentTarget: { setPointerCapture?: (id: number) => void }
  preventDefault: () => void
}

function pointer(pointerId: number, clientX: number, clientY: number): Pointer {
  return {
    pointerId,
    pointerType: 'touch',
    clientX,
    clientY,
    currentTarget: { setPointerCapture: () => {} },
    preventDefault: () => {},
  }
}

const BLOCK = { id: 'diagram-1' } as DiagramBlock

async function setup() {
  const { useDiagramFocus } = await import('@/composables/useDiagramFocus')
  const searchOpen = ref(false)
  const focus = useDiagramFocus({
    bodyRef: ref(null),
    listEl: ref(null),
    closeEl: ref(null),
    searchOpen,
  })
  return { focus, searchOpen }
}

beforeEach(() => {
  vi.resetModules()
  vi.unstubAllGlobals()
  // 组件内的 onMounted/onBeforeUnmount 在纯函数调用下会告警,与断言无关
  vi.spyOn(console, 'warn').mockImplementation(() => {})
  vi.stubGlobal('window', {
    innerWidth: 400,
    innerHeight: 800,
    // matches: true → 走窄屏浮层分支
    matchMedia: () => ({ matches: true, addEventListener() {}, removeEventListener() {} }),
    addEventListener() {},
    removeEventListener() {},
  })
  vi.stubGlobal('document', { activeElement: null })
})

describe('useDiagramFocus 手势', () => {
  it('双指拉开放大 → 越过阈值吸附全屏', async () => {
    const { focus } = await setup()
    focus.openDiagramFocus(BLOCK, 1)
    // 窄屏打开时是初始浮层,不是全屏
    expect(focus.focusPanel.value.fullscreen).toBe(false)

    focus.onFocusPointerDown(pointer(1, 100, 300) as unknown as PointerEvent)
    focus.onFocusPointerDown(pointer(2, 200, 300) as unknown as PointerEvent)
    // 手指间距 100 → 300,放大 3 倍
    focus.onFocusPointerMove(pointer(2, 400, 300) as unknown as PointerEvent)

    expect(focus.focusPanel.value.fullscreen).toBe(true)
  })

  it('单指左右拖动只改水平位置,并夹在不出屏范围内', async () => {
    const { focus } = await setup()
    focus.openDiagramFocus(BLOCK, 1)
    focus.onFocusPointerDown(pointer(1, 200, 300) as unknown as PointerEvent)
    // 右移 30px;400px 视口下 90vw 浮层每侧最多偏 (100-90)*400/200 = 20px
    focus.onFocusPointerMove(pointer(1, 230, 300) as unknown as PointerEvent)

    expect(focus.focusPanel.value.x).toBe(20)
    expect(focus.focusPanel.value.fullscreen).toBe(false)

    // 抬起后再左拖 10px:从当前位置回到 10,不再顶住边界
    focus.onFocusPointerUp(pointer(1, 230, 300) as unknown as PointerEvent)
    focus.onFocusPointerDown(pointer(2, 200, 300) as unknown as PointerEvent)
    focus.onFocusPointerMove(pointer(2, 190, 300) as unknown as PointerEvent)
    expect(focus.focusPanel.value.x).toBe(10)
  })

  it('全屏后单指拖动不再移动', async () => {
    const { focus } = await setup()
    focus.openDiagramFocus(BLOCK, 1)
    focus.onFocusPointerDown(pointer(1, 100, 300) as unknown as PointerEvent)
    focus.onFocusPointerDown(pointer(2, 200, 300) as unknown as PointerEvent)
    focus.onFocusPointerMove(pointer(2, 400, 300) as unknown as PointerEvent)
    expect(focus.focusPanel.value.fullscreen).toBe(true)

    focus.onFocusPointerUp(pointer(1, 100, 300) as unknown as PointerEvent)
    focus.onFocusPointerUp(pointer(2, 400, 300) as unknown as PointerEvent)

    const before = { ...focus.focusPanel.value }
    focus.onFocusPointerDown(pointer(3, 100, 400) as unknown as PointerEvent)
    focus.onFocusPointerMove(pointer(3, 260, 400) as unknown as PointerEvent)

    expect(focus.focusPanel.value).toEqual(before)
  })

  it('全屏态下滑超过 60px 才关闭,不足则保持', async () => {
    const { focus } = await setup()
    focus.openDiagramFocus(BLOCK, 1)
    // 先放大到全屏
    focus.onFocusPointerDown(pointer(1, 100, 300) as unknown as PointerEvent)
    focus.onFocusPointerDown(pointer(2, 200, 300) as unknown as PointerEvent)
    focus.onFocusPointerMove(pointer(2, 400, 300) as unknown as PointerEvent)
    focus.onFocusPointerUp(pointer(1, 100, 300) as unknown as PointerEvent)
    focus.onFocusPointerUp(pointer(2, 400, 300) as unknown as PointerEvent)

    // 下滑 40px:不够
    focus.onFocusPointerDown(pointer(3, 100, 400) as unknown as PointerEvent)
    focus.onFocusPointerUp(pointer(3, 100, 440) as unknown as PointerEvent)
    expect(focus.focusDiagram.value).not.toBeNull()

    // 下滑 100px:关闭
    focus.onFocusPointerDown(pointer(4, 100, 400) as unknown as PointerEvent)
    focus.onFocusPointerUp(pointer(4, 100, 500) as unknown as PointerEvent)
    expect(focus.focusDiagram.value).toBeNull()
  })

  it('同一张图连点两次才打开放大,只点一次不打开', async () => {
    const { focus } = await setup()
    const tap = (id: number) => {
      const event = pointer(id, 100, 300) as unknown as PointerEvent
      focus.onDiagramPointerDown(event)
      focus.onDiagramPointerUp(event, BLOCK, 1)
    }

    tap(1)
    expect(focus.focusDiagram.value).toBeNull()
    tap(2)
    expect(focus.focusDiagram.value?.id).toBe('diagram-1')
    expect(focus.isFocused(BLOCK)).toBe(true)
  })

  it('双指操作不算双击(避免缩放时误触放大)', async () => {
    const { focus } = await setup()
    focus.onDiagramPointerDown(pointer(1, 100, 300) as unknown as PointerEvent)
    focus.onDiagramPointerDown(pointer(2, 120, 300) as unknown as PointerEvent)
    focus.onDiagramPointerUp(pointer(1, 100, 300) as unknown as PointerEvent, BLOCK, 1)
    focus.onDiagramPointerUp(pointer(2, 120, 300) as unknown as PointerEvent, BLOCK, 1)

    expect(focus.focusDiagram.value).toBeNull()
  })
})
