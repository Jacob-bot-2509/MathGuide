/**
 * 研究型提问的搜索范围(数据源平台勾选)。
 *
 * 语义:全选(默认)= 全平台检索;取消某平台则本轮深度搜索向它一个请求都不发,
 * 省时也省对方配额。选择持久化到 localStorage,下次进入仍是上次的范围。
 * 后端 rag/research 的白名单与这里的 key 同口径(SearchHit.source)。
 */
import { ref, watch } from 'vue'

/** 与后端 rag.research.ALL_SOURCES 一一对应(顺序即面板展示顺序) */
export const SOURCE_OPTIONS: { key: string; label: string; labelEn: string; hint: string; hintEn: string }[] = [
  { key: '知识库', label: '本地知识库', labelEn: 'Knowledge Base', hint: '课程对齐的教材讲义,最贴合考试', hintEn: 'Course-aligned notes, best for coursework' },
  { key: 'arXiv', label: 'arXiv', labelEn: 'arXiv', hint: '预印本论文,前沿且更新快', hintEn: 'Preprints — fast-moving frontier' },
  { key: 'zbMATH', label: 'zbMATH Open', labelEn: 'zbMATH Open', hint: '数学专业文献库,含数学家同行评论', hintEn: 'Math-specific database with expert reviews' },
  { key: 'Semantic Scholar', label: 'Semantic Scholar', labelEn: 'Semantic Scholar', hint: '带引用数的学术搜索引擎', hintEn: 'Academic search with citation counts' },
  { key: 'OpenAlex', label: 'OpenAlex', labelEn: 'OpenAlex', hint: '开放学术图谱,覆盖面广', hintEn: 'Open scholarly graph, broad coverage' },
  { key: 'StackExchange', label: 'StackExchange', labelEn: 'StackExchange', hint: '数学问答社区,题解与讨论', hintEn: 'Math Q&A community — solutions and discussion' },
]

export const ALL_SOURCE_KEYS = SOURCE_OPTIONS.map((s) => s.key)

const STORAGE_KEY = 'mg-research-scope'

function load(): string[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return [...ALL_SOURCE_KEYS]
    const arr = JSON.parse(raw)
    if (!Array.isArray(arr)) return [...ALL_SOURCE_KEYS]
    const valid = arr.filter((k: unknown) => typeof k === 'string' && ALL_SOURCE_KEYS.includes(k))
    // 空选择等于全平台(后端同口径):落盘时就规范成全集,避免面板显示"一个都没勾"
    return valid.length ? valid : [...ALL_SOURCE_KEYS]
  } catch {
    return [...ALL_SOURCE_KEYS]
  }
}

/** 当前勾选的平台(默认全平台) */
export const selectedSources = ref<string[]>(load())

/** 是否处于全平台(全选)状态 */
export function isAllSelected(): boolean {
  return selectedSources.value.length === ALL_SOURCE_KEYS.length
}

/** 提交给后端的范围:全平台时不传(走默认全量),缩小范围才带上 */
export function scopeForRequest(): string[] | undefined {
  return isAllSelected() ? undefined : [...selectedSources.value]
}

watch(
  selectedSources,
  (v) => {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(v))
    } catch {
      /* 隐私模式下 localStorage 不可写:范围仅在本次会话有效,不影响使用 */
    }
  },
  { deep: true },
)

export function toggleSource(key: string): void {
  const cur = selectedSources.value
  if (cur.includes(key)) {
    // 至少保留一个平台(全不选无意义,后端也会退回全平台)
    if (cur.length > 1) selectedSources.value = cur.filter((k) => k !== key)
  } else {
    selectedSources.value = ALL_SOURCE_KEYS.filter((k) => cur.includes(k) || k === key)
  }
}

export function selectAllSources(): void {
  selectedSources.value = [...ALL_SOURCE_KEYS]
}

/** 仅选一个平台(面板里点平台名右侧的「只搜这里」) */
export function onlySource(key: string): void {
  selectedSources.value = [key]
}
