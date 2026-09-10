<script setup lang="ts">
/**
 * 回收站:被删除的问答记录保留 30 天。
 * 期限内可恢复(重新分配到原板块)或彻底删除;超期自动清除。
 */
import { TRASH_RETENTION_DAYS, daysLeft, removeFromTrash, restoreTrashItem, trashState } from '@/stores/trash'
import SettingsShell from '@/components/common/SettingsShell.vue'
import { catName, t } from '@/utils/i18n'
import { showToast } from '@/utils/toast'


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
    <p class="note">{{ t('trash.note', { n: TRASH_RETENTION_DAYS }) }}</p>

    <div v-if="trashState.items.length === 0" class="empty">{{ t('trash.empty') }}</div>

    <ul v-else class="list">
      <li v-for="item in trashState.items" :key="item.id" class="item">
        <span class="dot" :style="{ background: item.cat?.color ?? '#64748b', opacity: item.cat ? 1 : 0.3 }"></span>
        <div class="text">
          <span class="q">{{ item.question || t('trash.emptyQuestion') }}</span>
          <span class="meta">
            {{ item.cat ? catName(item.cat.key) : catName('other') }} ·
            {{ t('trash.deletedOn', { d: fmtDate(item.deletedAt), n: daysLeft(item.deletedAt) }) }}
          </span>
        </div>
        <button class="act restore" @click="restore(item.id)">{{ t('trash.restore') }}</button>
        <button class="act purge" @click="purge(item.id)">{{ t('trash.purge') }}</button>
      </li>
    </ul>
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
