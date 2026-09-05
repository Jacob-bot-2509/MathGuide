<script setup lang="ts">
/**
 * 隐私与安全:相册访问授权(头像)、语音识别授权、个性化学习数据开关,
 * 以及本地数据管理。
 */
import { useRouter } from 'vue-router'
import { settingsState, updateSettings } from '@/stores/settings'
import { clearAllSessions } from '@/stores/sessions'
import { clearTrash } from '@/stores/trash'
import { t } from '@/utils/i18n'
import { showToast } from '@/utils/toast'

const router = useRouter()

function toggle(key: 'albumAccess' | 'voiceAccess' | 'personalized') {
  updateSettings({ [key]: !settingsState[key] })
  showToast(settingsState[key] ? t('privacy.toastOn') : t('privacy.toastOff'))
}

function clearLocalData() {
  if (!window.confirm(t('privacy.clearConfirm'))) return
  // 走 store 清空:localStorage 与内存缓存一并清除,
  // 否则回到学习页时内存档案会被 persistSessions 原样写回
  clearAllSessions()
  clearTrash()
  showToast(t('privacy.toastCleared'))
}
</script>

<template>
  <div class="privacy">
    <header class="head">
      <button class="back" @click="router.back()">{{ t('common.back') }}</button>
      <span class="title">{{ t('privacy.title') }}</span>
    </header>

    <main class="body">
      <p class="section tech-label">{{ t('privacy.perms') }}</p>
      <div class="card">
        <div class="row">
          <div class="row-text">
            <span class="k">{{ t('privacy.album') }}</span>
            <span class="desc">{{ t('privacy.albumDesc') }}</span>
          </div>
          <button class="switch" :class="{ on: settingsState.albumAccess }" @click="toggle('albumAccess')">
            <span class="knob"></span>
          </button>
        </div>
        <div class="row">
          <div class="row-text">
            <span class="k">{{ t('privacy.voice') }}</span>
            <span class="desc">{{ t('privacy.voiceDesc') }}</span>
          </div>
          <button class="switch" :class="{ on: settingsState.voiceAccess }" @click="toggle('voiceAccess')">
            <span class="knob"></span>
          </button>
        </div>
        <div class="row">
          <div class="row-text">
            <span class="k">{{ t('privacy.personal') }}</span>
            <span class="desc">{{ t('privacy.personalDesc') }}</span>
          </div>
          <button class="switch" :class="{ on: settingsState.personalized }" @click="toggle('personalized')">
            <span class="knob"></span>
          </button>
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
    </main>
  </div>
</template>

<style scoped>
.privacy {
  min-height: 100vh;
}

.head {
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 16px 26px;
  border-bottom: 1px solid var(--line);
  background: var(--bg-panel);
}

.back {
  background: transparent;
  border: 1px solid var(--line);
  color: var(--text);
  padding: 7px 16px;
  cursor: pointer;
  border-radius: 4px;
  font-size: 13px;
  transition: all var(--dur-fast) var(--ease-out);
}

.back:hover {
  color: var(--cyan);
  border-color: var(--line-bright);
  box-shadow: var(--glow-cyan);
}

.title {
  color: var(--text-hi);
  font-size: 16px;
  letter-spacing: 0.1em;
}

.body {
  max-width: 560px;
  margin: 0 auto;
  padding: 26px 24px 60px;
}

.section {
  margin: 22px 0 10px;
  font-size: 11px;
}

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

.switch {
  width: 40px;
  height: 22px;
  border-radius: 999px;
  background: rgba(96, 165, 250, 0.15);
  border: 1px solid var(--line);
  position: relative;
  cursor: pointer;
  flex-shrink: 0;
  transition: all var(--dur-fast) var(--ease-out);
}

.switch .knob {
  position: absolute;
  top: 2px;
  left: 2px;
  width: 16px;
  height: 16px;
  border-radius: 50%;
  background: var(--text-dim);
  transition: all var(--dur-fast) var(--ease-out);
}

.switch.on {
  background: rgba(77, 214, 255, 0.25);
  border-color: var(--line-bright);
}

.switch.on .knob {
  left: 20px;
  background: var(--cyan);
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
</style>
