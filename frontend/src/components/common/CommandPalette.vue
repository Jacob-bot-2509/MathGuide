<script setup lang="ts">
/**
 * 全局工作台快速跳转面板 (Ctrl/⌘ + K 或顶栏触发):
 * 聚合双区会话、已入库论文、研究数据表与工作台/模式动作，
 * 让多线并行学习与科研切换保持零负担。
 */
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { t } from '@/utils/i18n'
import { getToken } from '@/stores/user'
import { sessionStore, type Workspace } from '@/stores/sessions'
import { settingsState, updateSettings } from '@/stores/settings'
import { crossWorkspaceHref } from '@/utils/workspace'
import { listResearchDocs, type ResearchDoc } from '@/services/researchService'
import { listResearchTables, type TableSummary } from '@/services/researchTableService'

interface PaletteItem {
  id: string
  group: 'actions' | 'sessions' | 'papers' | 'tables'
  title: string
  meta?: string
  badge?: string
  run: () => void
}

const router = useRouter()
const route = useRoute()

const open = ref(false)
const query = ref('')
const activeIdx = ref(0)
const inputEl = ref<HTMLInputElement | null>(null)
const docs = ref<ResearchDoc[]>([])
const tables = ref<TableSummary[]>([])
let loadedOnce = false

const currentScope = computed<'learn' | 'research' | 'other'>(() => {
  const p = route.path
  if (p.startsWith('/research')) return 'research'
  if (p.startsWith('/learn') || p.startsWith('/graph')) return 'learn'
  return 'other'
})

function canOpenPalette(): boolean {
  if (!getToken()) return false
  const p = route.path
  return p !== '/' && p !== '/intro' && p !== '/login'
}

async function fetchRemoteContext(): Promise<void> {
  // 严格遵守学习区与科研区数据隔离:仅在科研工作区内拉取已入库论文与研究数据表
  if (currentScope.value !== 'research' || loadedOnce) return
  loadedOnce = true
  const [docRes, tableRes] = await Promise.allSettled([
    listResearchDocs(),
    listResearchTables(),
  ])
  if (docRes.status === 'fulfilled') docs.value = docRes.value || []
  if (tableRes.status === 'fulfilled') tables.value = tableRes.value || []
}

function openPalette(): void {
  if (!canOpenPalette()) return
  open.value = true
  query.value = ''
  activeIdx.value = 0
  void fetchRemoteContext()
  void nextTick(() => inputEl.value?.focus())
}

function closePalette(): void {
  open.value = false
}

function jumpToWorkspace(
  workspace: Workspace,
  sessionId?: number,
  docId?: string,
  docTitle?: string,
): void {
  const targetPath = workspace === 'research' ? '/research' : '/learn'
  const payload = (sessionId || docId)
    ? { workspace, sessionId: sessionId || 0, docId, docTitle }
    : null
  if (payload) {
    try {
      sessionStorage.setItem('mg-jump-session', JSON.stringify(payload))
    } catch {
      /* 忽略隐私模式限制 */
    }
  }
  closePalette()
  if (route.path === targetPath) {
    if (payload) {
      window.dispatchEvent(new CustomEvent('mg:jump-session', { detail: payload }))
    }
    return
  }
  const href = crossWorkspaceHref(workspace, targetPath)
  if (href !== targetPath) {
    window.location.assign(href)
    return
  }
  void router.push(targetPath)
}

function sessionPreview(workspace: Workspace): PaletteItem[] {
  const store = sessionStore(workspace)
  const out: PaletteItem[] = []
  const tag = workspace === 'research' ? t('palette.researchTag') : t('palette.learnTag')
  for (const s of [...store.state.sessions].reverse()) {
    const firstUser = s.messages.find((m) => m.role === 'user' && m.content.trim())
    const title = (firstUser?.content || s.origin?.label || '').replace(/\s+/g, ' ').trim()
    if (!title) continue
    out.push({
      id: `sess-${workspace}-${s.id}`,
      group: 'sessions',
      title: title.slice(0, 64),
      meta: `${s.messages.length} msgs`,
      badge: tag,
      run: () => jumpToWorkspace(workspace, s.id),
    })
    if (out.length >= 6) break
  }
  return out
}

const allItems = computed<PaletteItem[]>(() => {
  const scope = currentScope.value
  const items: PaletteItem[] = [
    {
      id: 'act-learn',
      group: 'actions',
      title: t('learn.title'),
      meta: '/learn',
      badge: t('palette.learnTag'),
      run: () => jumpToWorkspace('learn'),
    },
    {
      id: 'act-research',
      group: 'actions',
      title: t('research.title'),
      meta: '/research',
      badge: t('palette.researchTag'),
      run: () => jumpToWorkspace('research'),
    },
  ]

  if (scope !== 'research') {
    items.push({
      id: 'act-graph',
      group: 'actions',
      title: t('graph.title'),
      meta: '/graph',
      run: () => { closePalette(); void router.push('/graph') },
    })
  }

  if (scope !== 'learn') {
    items.push({
      id: 'act-tables',
      group: 'actions',
      title: t('tables.entry'),
      meta: '/research/tables',
      run: () => { closePalette(); void router.push('/research/tables') },
    })
  }

  items.push({
    id: 'act-theme',
    group: 'actions',
    title: settingsState.theme === 'dark' ? 'Switch to Light Paper Theme' : 'Switch to Observatory Dark Theme',
    meta: settingsState.theme === 'dark' ? '浅色预印本' : '深色天文台',
    run: () => {
      updateSettings({ theme: settingsState.theme === 'dark' ? 'light' : 'dark' })
      closePalette()
    },
  })

  if (scope === 'learn') {
    items.push(...sessionPreview('learn'))
    return items
  }

  if (scope === 'research') {
    items.push(...sessionPreview('research'))
    for (const d of docs.value.slice(0, 12)) {
      items.push({
        id: `doc-${d.id}`,
        group: 'papers',
        title: d.title || d.name,
        meta: `${d.pages}p${d.year ? ` · ${d.year}` : ''}`,
        badge: 'PDF',
        run: () => jumpToWorkspace('research', 0, d.id, d.title || d.name),
      })
    }

    for (const tb of tables.value.slice(0, 10)) {
      items.push({
        id: `tbl-${tb.id}`,
        group: 'tables',
        title: tb.title,
        meta: `${tb.rows}×${tb.columns}`,
        badge: 'TBL',
        run: () => { closePalette(); void router.push({ path: '/research/tables', query: { tableId: tb.id } }) },
      })
    }
  }

  return items
})

const filteredItems = computed<PaletteItem[]>(() => {
  const q = query.value.trim().toLowerCase()
  if (!q) return allItems.value.slice(0, 16)
  return allItems.value
    .filter((item) =>
      item.title.toLowerCase().includes(q)
      || (item.meta || '').toLowerCase().includes(q)
      || (item.badge || '').toLowerCase().includes(q),
    )
    .slice(0, 20)
})

const grouped = computed(() => {
  const order: Array<{ key: PaletteItem['group']; label: string }> = [
    { key: 'sessions', label: t('palette.groupSessions') },
    { key: 'papers', label: t('palette.groupPapers') },
    { key: 'tables', label: t('palette.groupTables') },
    { key: 'actions', label: t('palette.groupActions') },
  ]
  let offset = 0
  return order
    .map((g) => {
      const list = filteredItems.value.filter((i) => i.group === g.key)
      const indexed = list.map((item) => ({ item, idx: offset++ }))
      return { ...g, items: indexed }
    })
    .filter((g) => g.items.length > 0)
})

const flatVisible = computed(() => grouped.value.flatMap((g) => g.items.map((x) => x.item)))

watch(query, () => { activeIdx.value = 0 })

function onGlobalKeydown(e: KeyboardEvent): void {
  if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') {
    if (!canOpenPalette()) return
    e.preventDefault()
    if (open.value) closePalette()
    else openPalette()
    return
  }
  if (!open.value) return
  if (e.key === 'Escape') {
    e.preventDefault()
    closePalette()
  } else if (e.key === 'ArrowDown') {
    e.preventDefault()
    const total = flatVisible.value.length
    if (total) activeIdx.value = (activeIdx.value + 1) % total
  } else if (e.key === 'ArrowUp') {
    e.preventDefault()
    const total = flatVisible.value.length
    if (total) activeIdx.value = (activeIdx.value - 1 + total) % total
  } else if (e.key === 'Enter') {
    const target = flatVisible.value[activeIdx.value]
    if (target) {
      e.preventDefault()
      target.run()
    }
  }
}

function onOpenEvent(): void {
  openPalette()
}

onMounted(() => {
  window.addEventListener('keydown', onGlobalKeydown)
  window.addEventListener('mg:open-palette', onOpenEvent)
})

onBeforeUnmount(() => {
  window.removeEventListener('keydown', onGlobalKeydown)
  window.removeEventListener('mg:open-palette', onOpenEvent)
})
</script>

<template>
  <Teleport to="body">
    <Transition name="pal-fade">
      <div v-if="open" class="pal-backdrop" @click.self="closePalette">
        <div class="pal-dialog" role="dialog" aria-modal="true" :aria-label="t('palette.openHint')">
          <div class="pal-head">
            <span class="pal-ico" aria-hidden="true">⌘</span>
            <input
              ref="inputEl"
              v-model="query"
              type="text"
              class="pal-input"
              :placeholder="t('palette.placeholder')"
              autocomplete="off"
              spellcheck="false"
            />
            <button type="button" class="pal-esc" @click="closePalette">ESC</button>
          </div>
          <div class="pal-body">
            <div v-if="!grouped.length" class="pal-empty">{{ t('palette.empty') }}</div>
            <section v-for="g in grouped" :key="g.key" class="pal-group">
              <div class="pal-group-label">{{ g.label }}</div>
              <button
                v-for="entry in g.items"
                :key="entry.item.id"
                type="button"
                class="pal-item"
                :class="{ active: activeIdx === entry.idx }"
                @mouseenter="activeIdx = entry.idx"
                @click="entry.item.run()"
              >
                <span v-if="entry.item.badge" class="pal-badge">{{ entry.item.badge }}</span>
                <span class="pal-title">{{ entry.item.title }}</span>
                <span v-if="entry.item.meta" class="pal-meta">{{ entry.item.meta }}</span>
              </button>
            </section>
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<style scoped>
.pal-backdrop {
  position: fixed;
  inset: 0;
  z-index: 950;
  background: color-mix(in srgb, var(--bg-void) 64%, transparent);
  backdrop-filter: blur(6px);
  display: flex;
  align-items: flex-start;
  justify-content: center;
  padding: max(10vh, 48px) 16px calc(16px + env(safe-area-inset-bottom));
}

.pal-dialog {
  width: 100%;
  max-width: 580px;
  max-height: 72vh;
  max-height: 72dvh;
  background: var(--bg-panel);
  border: 1px solid var(--line-bright);
  border-radius: 14px;
  box-shadow: var(--shadow-lg);
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.pal-head {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 12px 14px;
  border-bottom: 1px solid var(--line);
}

.pal-ico {
  font-family: var(--font-mono);
  font-size: 13px;
  color: var(--cyan);
}

.pal-input {
  flex: 1;
  min-width: 0;
  border: none;
  outline: none;
  background: transparent;
  color: var(--text-hi);
  font-size: 14px;
  font-family: inherit;
}
.pal-input::placeholder { color: var(--text-dim); }

.pal-esc {
  flex: none;
  font-family: var(--font-mono);
  font-size: 10.5px;
  padding: 3px 7px;
  border-radius: 6px;
  border: 1px solid var(--line);
  background: var(--bg-card);
  color: var(--text-dim);
  cursor: pointer;
}

.pal-body {
  flex: 1;
  overflow-y: auto;
  padding: 8px;
}

.pal-empty {
  padding: 28px 12px;
  text-align: center;
  color: var(--text-dim);
  font-size: 13px;
}

.pal-group {
  margin-bottom: 10px;
}
.pal-group:last-child { margin-bottom: 0; }

.pal-group-label {
  font-size: 11px;
  font-family: var(--font-mono);
  color: var(--text-dim);
  padding: 4px 10px 6px;
  letter-spacing: 0.04em;
}

.pal-item {
  width: 100%;
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 10px;
  border: 1px solid transparent;
  border-radius: 8px;
  background: transparent;
  color: var(--text);
  font-size: 13px;
  text-align: left;
  cursor: pointer;
}
.pal-item.active,
.pal-item:hover {
  background: color-mix(in srgb, var(--cyan) 12%, var(--bg-card));
  border-color: color-mix(in srgb, var(--cyan) 32%, var(--line));
  color: var(--text-hi);
}

.pal-badge {
  flex: none;
  font-size: 10.5px;
  font-family: var(--font-mono);
  padding: 1px 6px;
  border-radius: 999px;
  background: var(--bg-card);
  border: 1px solid var(--line);
  color: var(--cyan);
}

.pal-title {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.pal-meta {
  flex: none;
  font-size: 11px;
  font-family: var(--font-mono);
  color: var(--text-dim);
}

.pal-fade-enter-active,
.pal-fade-leave-active {
  transition: opacity var(--dur-fast) var(--ease-out);
}
.pal-fade-enter-from,
.pal-fade-leave-to { opacity: 0; }

@media (max-width: 600px) {
  .pal-backdrop {
    padding: calc(12px + env(safe-area-inset-top)) 10px calc(12px + env(safe-area-inset-bottom));
  }
  .pal-dialog {
    max-height: 82vh;
    max-height: 82dvh;
  }
}
</style>
