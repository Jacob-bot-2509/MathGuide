/** 科研检索的右侧分栏:开合、比例、拖拽、本地记忆。
 *
 * 只负责「分栏」这一件事。检索面板里搜什么、结果怎么转交给对话、
 * 论文上下文怎么进出,仍由 ChatWorkspace 负责;这里不引用组件内部状态,
 * 比例换算全部委托给 utils/splitPane(有单测)。
 */
import { ref, type Ref } from 'vue'
import {
  SPLIT_DEFAULT,
  SPLIT_MIN_WIDTH,
  clampSplitRatio,
  parseStoredRatio,
} from '@/utils/splitPane'

const SPLIT_KEY = 'mg-research-split'

export interface ResearchSplitOptions {
  /** 分栏容器:拖拽时按它的宽度把指针位置换算成比例。 */
  bodyRef: Ref<HTMLElement | null>
}

export function useResearchSplit(options: ResearchSplitOptions) {
  const searchOpen = ref(false)
  const splitResizing = ref(false)
  const splitRatio = ref(loadSplitRatio())

  /** 宽度缺省时取容器实测宽度;量不到就只做 0..1 兜底。 */
  function clampSplit(
    value: number,
    width = options.bodyRef.value?.clientWidth ?? 0,
  ): number {
    return clampSplitRatio(value, width)
  }

  function loadSplitRatio(): number {
    try {
      return clampSplit(parseStoredRatio(localStorage.getItem(SPLIT_KEY), SPLIT_DEFAULT))
    } catch {
      return SPLIT_DEFAULT
    }
  }

  function saveSplitRatio(): void {
    try {
      localStorage.setItem(SPLIT_KEY, String(splitRatio.value))
    } catch {
      /* 隐私模式/配额写满:记不住不影响分栏本身 */
    }
  }

  function startSplitDrag(e: PointerEvent): void {
    const body = options.bodyRef.value
    if (!body) return
    e.preventDefault()
    splitResizing.value = true
    const rect = body.getBoundingClientRect()
    const move = (ev: PointerEvent) => {
      splitRatio.value = clampSplit((rect.right - ev.clientX) / rect.width, rect.width)
    }
    const up = () => {
      splitResizing.value = false
      window.removeEventListener('pointermove', move)
      window.removeEventListener('pointerup', up)
      saveSplitRatio()
    }
    window.addEventListener('pointermove', move)
    window.addEventListener('pointerup', up)
  }

  function nudgeSplit(delta: number): void {
    splitRatio.value = clampSplit(splitRatio.value + delta)
    saveSplitRatio()
  }

  function resetSplit(): void {
    splitRatio.value = clampSplit(SPLIT_DEFAULT)
    saveSplitRatio()
  }

  /** 窗口变窄时收起分栏,避免聊天区被压到不可用。 */
  function closeSplitIfNarrow(): void {
    if (searchOpen.value && window.innerWidth < SPLIT_MIN_WIDTH) searchOpen.value = false
  }

  return {
    searchOpen,
    splitResizing,
    splitRatio,
    clampSplit,
    startSplitDrag,
    nudgeSplit,
    resetSplit,
    closeSplitIfNarrow,
  }
}
