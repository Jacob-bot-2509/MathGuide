<script setup lang="ts">
/**
 * 回收站:被删除的问答记录保留 30 天。
 * 期限内可恢复(重新分配到原板块)或彻底删除;超期自动清除。
 */
import { ref } from 'vue'
import { TRASH_RETENTION_DAYS, daysLeft, removeFromTrash, restoreTrashItem, trashState } from '@/stores/trash'
import { listPaperTrash, restorePaperHistory, type HistoryItem } from '@/services/literatureService'
import SettingsShell from '@/components/common/SettingsShell.vue'
import { catName, t } from '@/utils/i18n'
import { showToast } from '@/utils/toast'

type TrashTab = 'questions' | 'papers'

const activeTab = ref<TrashTab>('questions')
const paperTrash = ref<HistoryItem[]>([])
const paperLoading = ref(false)
const paperLoaded = ref(false)

/** 两个窗口独立:首次切到科研历史才拉服务端回收站 */
function setTab(tab: TrashTab): void {
  activeTab.value = tab
  if (tab === 'papers' && !paperLoaded.value) void loadPaperTrash()
}

async function loadPaperTrash(): Promise<void> {
  paperLoading.value = true
  try {
    paperTrash.value = await listPaperTrash()
  } catch {
    paperTrash.value = []
  } finally {
    paperLoading.value = false
    paperLoaded.value = true
  }
}

async function restorePaper(item: HistoryItem): Promise<void> {
  try {
    await restorePaperHistory(item.id)
    await loadPaperTrash()
    showToast(t('trash.toastRestored'))
  } catch {
    showToast(t('history.fail'))
  }
}


function fmtDate(t: number): string {
  return new Date(t).toLocaleDateString('zh-CN')
}

function restore(id: number) {
  if (restoreTrashItem(id)) showToast(t('trash.toastRestored'))
}

function purge(id: number) {
  if (!window.confirm(t('trash.purgeConfirm'))) return
  removeFromTrash(id)
  showToast(t('trash.toastPurged'))
}
</script>

<template>
  <SettingsShell :width="620" :title="t('trash.title')">
    <div class="tabs" role="tablist">
      <button
        class="tab"
        :class="{ on: activeTab === 'questions' }"
        role="tab"
        :aria-selected="activeTab === 'questions'"
        @click="setTab('questions')"
      >{{ t('trash.tabQuestions') }}</button>
      <button
        class="tab"
        :class="{ on: activeTab === 'papers' }"
        role="tab"
        :aria-selected="activeTab === 'papers'"
        @click="setTab('papers')"
      >{{ t('trash.tabPapers') }}</button>
    </div>

    <div v-if="activeTab === 'questions'" class="pane">
      <p class="note">{{ t('trash.note', { n: TRASH_RETENTION_DAYS }) }}</p>

      <div v-if="trashState.items.length === 0" class="empty">{{ t('trash.empty') }}</div>

      <ul v-else class="list">
        <li v-for="item in trashState.items" :key="item.id" class="item">
          <span class="dot" :style="{ background: item.cat?.color ?? '#64748b', opacity: item.cat ? 1 : 0.3 }"></span>
          <div class="text">
            <span class="q">{{ item.question || t('trash.emptyQuestion') }}</span>
            <span class="meta">
              <span class="ws">{{ t(item.workspace === 'research' ? 'trash.wsResearch' : 'trash.wsLearn') }}</span> ·
              {{ item.cat ? catName(item.cat.key) : catName('other') }} ·
              {{ t('trash.deletedOn', { d: fmtDate(item.deletedAt), n: daysLeft(item.deletedAt) }) }}
            </span>
          </div>
          <button class="act restore" @click="restore(item.id)">{{ t('trash.restore') }}</button>
          <button class="act purge" @click="purge(item.id)">{{ t('trash.purge') }}</button>
        </li>
      </ul>
    </div>

    <div v-else class="pane">
      <p class="note">{{ t('trash.paperNote', { n: TRASH_RETENTION_DAYS }) }}</p>
      <div v-if="paperLoading" class="empty">{{ t('viewer.loading') }}</div>
      <div v-else-if="paperTrash.length === 0" class="empty">{{ t('trash.paperEmpty') }}</div>
      <ul v-else class="list">
        <li v-for="item in paperTrash" :key="item.id" class="item">
          <div class="text">
            <span class="q">{{ item.title }}</span>
            <span class="meta">
              {{ t('history.notes', { n: item.annotations }) }} ·
              {{ t('history.daysLeft', { n: item.daysLeft ?? 0 }) }}
            </span>
          </div>
          <button class="act restore" @click="restorePaper(item)">{{ t('trash.restore') }}</button>
        </li>
      </ul>
    </div>
  </SettingsShell>
</template>

<style scoped>
.note {
  color: var(--text-dim);
  font-size: 12px;
  line-height: 1.7;
  margin: 0 0 16px;
  padding: 10px 14px;
  background: var(--bg-card);
  border: 1px solid var(--line);
  border-radius: 8px;
}

.tabs {
  display: flex;
  gap: 6px;
  margin-bottom: 16px;
  padding: 4px;
  background: var(--bg-card);
  border: 1px solid var(--line);
  border-radius: 10px;
}

.tab {
  flex: 1;
  padding: 9px 14px;
  background: transparent;
  border: none;
  border-radius: 7px;
  color: var(--text-dim);
  font-size: 13px;
  cursor: pointer;
  transition: all var(--dur-fast) var(--ease-out);
}

.tab:hover {
  color: var(--text);
}

.tab.on {
  color: var(--cyan);
  background: rgba(77, 214, 255, 0.1);
  box-shadow: inset 0 0 0 1px rgba(77, 214, 255, 0.22);
}

.empty {
  color: var(--text-dim);
  font-size: 13px;
  text-align: center;
  padding: 48px 0;
}

.list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.item {
  display: flex;
  align-items: center;
  gap: 12px;
  background: var(--bg-card);
  border: 1px solid var(--line);
  border-radius: 10px;
  padding: 12px 16px;
  transition: border-color var(--dur-fast);
}

.item:hover {
  border-color: var(--line-bright);
}

.dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  flex-shrink: 0;
}

.text {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.q {
  color: var(--text);
  font-size: 13.5px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.meta {
  color: var(--text-dim);
  font-size: 11.5px;
}

/* 来源工作区标签:恢复去向一眼可辨 */
.ws {
  color: var(--cyan);
}

.act {
  flex-shrink: 0;
  background: transparent;
  border: 1px solid var(--line);
  border-radius: 6px;
  padding: 6px 14px;
  cursor: pointer;
  font-size: 12.5px;
  transition: all var(--dur-fast) var(--ease-out);
}

.act.restore {
  color: var(--cyan);
}

.act.restore:hover {
  border-color: var(--line-bright);
  background: rgba(77, 214, 255, 0.1);
  box-shadow: var(--glow-cyan);
}

.act.purge {
  color: var(--danger);
}

.act.purge:hover {
  border-color: color-mix(in srgb, var(--danger) 50%, transparent);
  background: color-mix(in srgb, var(--danger) 10%, transparent);
}

@media (max-width: 560px) {
  .item {
    flex-wrap: wrap;
  }
}
</style>
