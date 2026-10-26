<script setup lang="ts">
/**
 * 隐私与安全:相册访问授权(头像)、语音识别授权、个性化学习数据开关,
 * 以及本地数据管理。
 */
import { settingsState, updateSettings } from '@/stores/settings'
import { clearLearningData } from '@/stores/localData'
import { clearAllTodoData } from '@/stores/todo'
import SettingsShell from '@/components/common/SettingsShell.vue'
import MgSwitch from '@/components/common/MgSwitch.vue'
import { t } from '@/utils/i18n'
import { showToast } from '@/utils/toast'


/** 开关变更:目标值由 MgSwitch 给出(原先函数内自行取反,值在两处各算一次) */
function toggle(key: 'albumAccess' | 'voiceAccess' | 'personalized', on: boolean) {
  updateSettings({ [key]: on })
  showToast(on ? t('privacy.toastOn') : t('privacy.toastOff'))
}

function clearLocalData() {
  if (!window.confirm(t('privacy.clearConfirm'))) return
  // 走统一入口:localStorage 与内存缓存一并清除,
  // 否则回到学习页时内存档案会被 persistSessions 原样写回
  clearLearningData()
  clearAllTodoData()
  showToast(t('privacy.toastCleared'))
}
</script>

<template>
  <SettingsShell :title="t('privacy.title')">
    <p class="section tech-label">{{ t('privacy.perms') }}</p>
    <div class="card">
      <div class="row">
        <div class="row-text">
          <span class="k">{{ t('privacy.album') }}</span>
          <span class="desc">{{ t('privacy.albumDesc') }}</span>
        </div>
        <MgSwitch
          :model-value="settingsState.albumAccess"
          @update:model-value="(v) => toggle('albumAccess', v)"
        />
      </div>
      <div class="row">
        <div class="row-text">
          <span class="k">{{ t('privacy.voice') }}</span>
          <span class="desc">{{ t('privacy.voiceDesc') }}</span>
        </div>
        <MgSwitch
          :model-value="settingsState.voiceAccess"
          @update:model-value="(v) => toggle('voiceAccess', v)"
        />
      </div>
      <div class="row">
        <div class="row-text">
          <span class="k">{{ t('privacy.personal') }}</span>
          <span class="desc">{{ t('privacy.personalDesc') }}</span>
        </div>
        <MgSwitch
          :model-value="settingsState.personalized"
          @update:model-value="(v) => toggle('personalized', v)"
        />
      </div>
    </div>

    <p class="section tech-label">{{ t('privacy.data') }}</p>
    <div class="card">
      <div class="row">
        <div class="row-text">
          <span class="k">{{ t('privacy.clear') }}</span>
          <span class="desc">{{ t('privacy.clearDesc') }}</span>
        </div>
        <button class="danger-btn" @click="clearLocalData">{{ t('privacy.clearBtn') }}</button>
      </div>
    </div>

    <p class="foot-note">{{ t('privacy.foot') }}</p>
    <RouterLink class="policy-link" :to="{ path: '/settings/terms', query: { tab: 'privacy' } }">
      {{ t('privacy.policyLink') }} <span aria-hidden="true">↗</span>
    </RouterLink>
  </SettingsShell>
</template>

<style scoped>
.card {
  background: var(--bg-card);
  border: 1px solid var(--line);
  border-radius: 10px;
}

.row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 14px 18px;
  border-bottom: 1px solid var(--line);
}

.row:last-child {
  border-bottom: none;
}

.row-text {
  display: flex;
  flex-direction: column;
  gap: 3px;
}

.k {
  color: var(--text-hi);
  font-size: 14px;
}

.desc {
  color: var(--text-dim);
  font-size: 11.5px;
  line-height: 1.5;
}

.danger-btn {
  background: color-mix(in srgb, var(--danger) 6%, transparent);
  border: 1px solid color-mix(in srgb, var(--danger) 45%, transparent);
  color: var(--danger);
  padding: 7px 16px;
  border-radius: 8px;
  cursor: pointer;
  font-size: 13px;
  flex-shrink: 0;
  transition: all var(--dur-fast) var(--ease-out);
}

.danger-btn:hover {
  background: color-mix(in srgb, var(--danger) 14%, transparent);
  box-shadow: 0 0 10px color-mix(in srgb, var(--danger) 30%, transparent);
}

.foot-note {
  color: var(--text-dim);
  font-size: 11.5px;
  line-height: 1.7;
  margin-top: 30px;
  padding: 0 6px;
}

.policy-link {
  display: inline-block;
  margin: 8px 6px 0;
  color: var(--cyan);
  font-size: 12px;
  text-decoration: none;
}

.policy-link:hover {
  text-shadow: 0 0 10px rgba(77, 214, 255, 0.5);
}
</style>
