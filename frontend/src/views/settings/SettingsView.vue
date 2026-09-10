<script setup lang="ts">
/**
 * 设置中心:账号 / 应用 / 关于 三大板块 + 退出登录(红色)。
 */
import { useRouter } from 'vue-router'
import UserAvatar from '@/components/common/UserAvatar.vue'
import MgSelect from '@/components/common/MgSelect.vue'
import { settingsState, updateSettings } from '@/stores/settings'
import { userState } from '@/stores/user'
import { trashState } from '@/stores/trash'
import { logout } from '@/services/authService'
import SettingsShell from '@/components/common/SettingsShell.vue'
import { t } from '@/utils/i18n'
import { showToast } from '@/utils/toast'

const router = useRouter()

function pickTheme(theme: 'dark' | 'light') {
  updateSettings({ theme })
  showToast(theme === 'light' ? t('settings.toastLight') : t('settings.toastDark'))
}

function onLanguageChange() {
  updateSettings({ language: settingsState.language })
}

function doLogout() {
  if (window.confirm(t('settings.logoutConfirm'))) {
    logout()
    showToast(t('settings.toastLoggedOut'))
    router.push('/login')
  }
}
</script>

<template>
  <SettingsShell :title="t('settings.title')">
    <template #extra>
      <span class="tech-label sub">MG SYSTEM · SETTINGS</span>
    </template>

    <!-- 账号 -->
    <p class="section tech-label">{{ t('settings.sectionAccount') }}</p>
    <button class="row" @click="router.push('/settings/account')">
      <span class="row-label">{{ t('settings.account') }}</span>
      <span class="row-value">
        <UserAvatar :avatar="userState.info?.avatar" :size="26" />
        <span class="nick">{{ userState.info?.nickname }}</span>
        <span class="chev">›</span>
      </span>
    </button>
    <button class="row" @click="router.push('/settings/privacy')">
      <span class="row-label">{{ t('settings.privacy') }}</span>
      <span class="row-value"><span class="chev">›</span></span>
    </button>
    <button class="row" @click="router.push('/settings/trash')">
      <span class="row-label">{{ t('settings.trash') }}</span>
      <span class="row-value">
        <span class="trash-count">{{ t('settings.items', { n: trashState.items.length }) }}</span>
        <span class="chev">›</span>
      </span>
    </button>

    <!-- 应用 -->
    <p class="section tech-label">{{ t('settings.sectionApp') }}</p>
    <div class="row">
      <span class="row-label">{{ t('settings.language') }}</span>
      <MgSelect
        v-model="settingsState.language"
        :options="[
          { value: 'zh', label: '简体中文' },
          { value: 'en', label: 'English' },
        ]"
        @change="onLanguageChange"
      />
    </div>
    <div class="row">
      <span class="row-label">{{ t('settings.appearance') }}</span>
      <span class="seg">
        <button class="seg-btn" :class="{ on: settingsState.theme === 'dark' }" @click="pickTheme('dark')">{{ t('settings.dark') }}</button>
        <button class="seg-btn" :class="{ on: settingsState.theme === 'light' }" @click="pickTheme('light')">{{ t('settings.light') }}</button>
      </span>
    </div>

    <!-- 关于 -->
    <p class="section tech-label">{{ t('settings.sectionAbout') }}</p>
    <button class="row" @click="router.push('/settings/about')">
      <span class="row-label">{{ t('settings.feedback') }}</span>
      <span class="row-value"><span class="chev">›</span></span>
    </button>
    <button class="row" @click="router.push('/settings/about')">
      <span class="row-label">{{ t('settings.about') }}</span>
      <span class="row-value"><span class="chev">›</span></span>
    </button>

    <!-- 退出登录(红色) -->
    <button class="logout" @click="doLogout">{{ t('settings.logout') }}</button>
  </SettingsShell>
</template>

<style scoped>
.sub {
  margin-left: auto;
  font-size: 10px;
}

.row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  width: 100%;
  background: var(--bg-card);
  border: 1px solid var(--line);
  border-bottom: none;
  color: var(--text);
  padding: 14px 18px;
  cursor: pointer;
  font-size: 14px;
  text-align: left;
  transition: background var(--dur-fast);
}

.row:first-of-type {
  border-radius: 10px 10px 0 0;
}

.row:last-of-type {
  border-radius: 0 0 10px 10px;
  border-bottom: 1px solid var(--line);
}

.row:hover {
  background: rgba(96, 165, 250, 0.07);
}

.row-label {
  color: var(--text-hi);
}

.row-value {
  display: inline-flex;
  align-items: center;
  gap: 10px;
  color: var(--text-dim);
}

.nick {
  font-size: 13px;
}

.trash-count {
  font-family: var(--font-tech);
  font-size: 11px;
  color: var(--text-dim);
}

.chev {
  color: var(--text-dim);
  font-size: 16px;
}

.select {
  background: var(--bg-void);
  border: 1px solid var(--line);
  color: var(--text);
  padding: 6px 10px;
  border-radius: 6px;
  font-size: 13px;
  outline: none;
  cursor: pointer;
}

/* 语言下拉由 MgSelect 组件渲染,主题边框随深浅色自动适配 */

.seg {
  display: inline-flex;
  gap: 8px;
}

.seg-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  background: transparent;
  border: 1px solid var(--line);
  color: var(--text-dim);
  padding: 6px 14px;
  border-radius: 6px;
  cursor: pointer;
  font-size: 13px;
  transition: all var(--dur-fast) var(--ease-out);
}

.seg-btn:hover {
  color: var(--cyan);
  border-color: var(--line-bright);
}

.seg-btn.on {
  color: var(--cyan);
  border-color: var(--line-bright);
  background: color-mix(in srgb, var(--cyan) 8%, transparent);
}

.logout {
  display: block;
  width: 100%;
  margin-top: 36px;
  background: color-mix(in srgb, var(--danger) 6%, transparent);
  border: 1px solid color-mix(in srgb, var(--danger) 45%, transparent);
  color: var(--danger);
  padding: 13px;
  border-radius: 10px;
  cursor: pointer;
  font-size: 14px;
  letter-spacing: 0.15em;
  transition: all var(--dur-fast) var(--ease-out);
}

.logout:hover {
  background: color-mix(in srgb, var(--danger) 14%, transparent);
  box-shadow: 0 0 14px color-mix(in srgb, var(--danger) 30%, transparent);
}
</style>
