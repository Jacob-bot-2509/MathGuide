/**
 * 科研课题上下文透镜(共享状态):
 * 在科研侧栏、文献检索、数据表之间同步当前聚焦的 ResearchProject id，
 * 缺省为空串表示「全部课题」，完全向后兼容。
 */
import { ref } from 'vue'

const KEY = 'mg-active-project'

function loadInitial(): string {
  try {
    return localStorage.getItem(KEY) || ''
  } catch {
    return ''
  }
}

export const activeProjectId = ref<string>(loadInitial())

export function setActiveProjectId(projectId: string): void {
  const next = String(projectId || '').trim()
  activeProjectId.value = next
  try {
    if (next) localStorage.setItem(KEY, next)
    else localStorage.removeItem(KEY)
  } catch {
    /* 忽略隐私模式限制 */
  }
}
