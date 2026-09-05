<script setup lang="ts">
/**
 * 账号管理:头像(预设 + 相册上传,需相册授权)、昵称、手机号、
 * 实名认证状态与实名信息补全。
 */
import { computed, ref } from 'vue'
import { useRouter } from 'vue-router'
import UserAvatar from '@/components/common/UserAvatar.vue'
import { updateUser, userState } from '@/stores/user'
import { settingsState } from '@/stores/settings'
import { AVATAR_PRESETS, fileToAvatar } from '@/utils/avatar'
import { authName, realnameText, t } from '@/utils/i18n'
import { showToast } from '@/utils/toast'

const router = useRouter()

const nickname = ref(userState.info?.nickname ?? '')
const pickingAvatar = ref(false)
const fileEl = ref<HTMLInputElement | null>(null)
const realName = ref('')
const realId = ref('')

const user = computed(() => userState.info)

function maskPhone(p?: string): string {
  return p ? `${p.slice(0, 3)}****${p.slice(-4)}` : t('acc.unbound')
}

function saveNickname() {
  const v = nickname.value.trim()
  if (!v) {
    showToast(t('acc.toastNickEmpty'))
    return
  }
  updateUser({ nickname: v })
  showToast(t('acc.toastNickSaved'))
}

function pickPreset(key: string) {
  updateUser({ avatar: key })
  pickingAvatar.value = false
  showToast(t('acc.toastAvatar'))
}

function pickFromAlbum() {
  if (!settingsState.albumAccess) {
    showToast(t('acc.toastAlbumDenied'))
    return
  }
  fileEl.value?.click()
}

async function onFile(e: Event) {
  const input = e.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''
  if (!file) return
  try {
    const dataUrl = await fileToAvatar(file)
    updateUser({ avatar: dataUrl })
    pickingAvatar.value = false
    showToast(t('acc.toastAvatar'))
  } catch {
    showToast(t('acc.toastAvatarFail'))
  }
}

function saveRealName() {
  const name = realName.value.trim()
  const id = realId.value.trim()
  if (!name) {
    showToast(t('acc.toastNameEmpty'))
    return
  }
  if (!/^\d{17}[\dXx]$/.test(id)) {
    showToast(t('acc.toastIdErr'))
    return
  }
  updateUser({ realName: { name, idMasked: `${id.slice(0, 3)}***********${id.slice(-4)}` } })
  showToast(t('acc.toastRealSaved'))
}
</script>

<template>
  <div class="acc">
    <header class="head">
      <button class="back" @click="router.back()">{{ t('common.back') }}</button>
      <span class="title">{{ t('acc.title') }}</span>
    </header>

    <main class="body">
      <!-- 头像 -->
      <div class="avatar-block">
        <UserAvatar :avatar="user?.avatar" :size="76" />
        <button class="ghost-btn" @click="pickingAvatar = !pickingAvatar">
          {{ pickingAvatar ? t('acc.collapse') : t('acc.changeAvatar') }}
        </button>
        <button class="ghost-btn" @click="pickFromAlbum">{{ t('acc.fromAlbum') }}</button>
        <input ref="fileEl" type="file" accept="image/*" hidden @change="onFile" />
      </div>

      <div v-if="pickingAvatar" class="preset-grid">
        <button
          v-for="p in AVATAR_PRESETS"
          :key="p.key"
          class="preset-item"
          :title="p.glyph"
          @click="pickPreset(p.key)"
        >
          <UserAvatar :avatar="p.key" :size="44" />
        </button>
      </div>

      <!-- 昵称 -->
      <p class="section tech-label">{{ t('acc.nickname') }}</p>
      <div class="field-row">
        <input v-model="nickname" class="input" :placeholder="t('acc.nickPh')" maxlength="16" />
        <button class="save-btn" @click="saveNickname">{{ t('acc.save') }}</button>
      </div>

      <!-- 账号信息 -->
      <p class="section tech-label">{{ t('acc.info') }}</p>
      <div class="info-card">
        <div class="info-row">
          <span class="k">{{ t('acc.phone') }}</span>
          <span class="v">{{ maskPhone(user?.phone) }}</span>
        </div>
        <div class="info-row">
          <span class="k">{{ t('acc.method') }}</span>
          <span class="v">{{ user ? authName(user.authMethod) : '-' }}</span>
        </div>
      </div>

      <!-- 实名认证 -->
      <p class="section tech-label">{{ t('acc.realname') }}</p>
      <div class="info-card">
        <div v-if="user" class="info-row">
          <span class="k">{{ t('acc.status') }}</span>
          <span class="v ok">{{ realnameText(user.authMethod) }}</span>
        </div>
        <template v-if="user?.realName">
          <div class="info-row">
            <span class="k">{{ t('acc.name') }}</span>
            <span class="v">{{ user.realName.name.slice(0, 1) }}**</span>
          </div>
          <div class="info-row">
            <span class="k">{{ t('acc.id') }}</span>
            <span class="v">{{ user.realName.idMasked }}</span>
          </div>
        </template>
        <template v-else>
          <div class="real-form">
            <input v-model="realName" class="input" :placeholder="t('acc.namePh')" maxlength="12" />
            <input v-model="realId" class="input" :placeholder="t('acc.idPh')" maxlength="18" />
            <button class="save-btn" @click="saveRealName">{{ t('acc.submit') }}</button>
          </div>
          <p class="note">{{ t('acc.note') }}</p>
        </template>
      </div>
    </main>
  </div>
</template>

<style scoped>
.acc {
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

.avatar-block {
  display: flex;
  align-items: center;
  gap: 14px;
}

.ghost-btn {
  background: transparent;
  border: 1px solid var(--line);
  color: var(--text);
  padding: 8px 16px;
  border-radius: 8px;
  cursor: pointer;
  font-size: 13px;
  transition: all var(--dur-fast) var(--ease-out);
}

.ghost-btn:hover {
  color: var(--cyan);
  border-color: var(--line-bright);
  box-shadow: var(--glow-cyan);
}

.preset-grid {
  display: grid;
  grid-template-columns: repeat(8, 44px);
  gap: 10px;
  margin-top: 16px;
}

.preset-item {
  background: transparent;
  border: 1px solid var(--line);
  border-radius: 50%;
  padding: 0;
  cursor: pointer;
  transition: all var(--dur-fast) var(--ease-out);
}

.preset-item:hover {
  border-color: var(--line-bright);
  box-shadow: var(--glow-cyan);
  transform: translateY(-2px);
}

.section {
  margin: 26px 0 10px;
  font-size: 11px;
}

.field-row {
  display: flex;
  gap: 10px;
}

.input {
  flex: 1;
  background: var(--bg-card);
  border: 1px solid var(--line);
  border-radius: 8px;
  color: var(--text);
  padding: 10px 14px;
  font-size: 14px;
  outline: none;
  transition: border-color var(--dur-fast);
}

.input:focus {
  border-color: var(--line-bright);
}

.input::placeholder {
  color: var(--text-dim);
}

.save-btn {
  background: rgba(77, 214, 255, 0.1);
  border: 1px solid var(--line-bright);
  color: var(--cyan);
  padding: 10px 20px;
  border-radius: 8px;
  cursor: pointer;
  font-size: 13px;
  transition: all var(--dur-fast) var(--ease-out);
}

.save-btn:hover {
  background: rgba(77, 214, 255, 0.18);
  box-shadow: var(--glow-cyan);
}

.info-card {
  background: var(--bg-card);
  border: 1px solid var(--line);
  border-radius: 10px;
  padding: 6px 18px;
}

.info-row {
  display: flex;
  justify-content: space-between;
  padding: 11px 0;
  border-bottom: 1px solid var(--line);
  font-size: 13.5px;
}

.info-row:last-child {
  border-bottom: none;
}

.k {
  color: var(--text-dim);
}

.v {
  color: var(--text);
}

.v.ok {
  color: var(--cyan);
}

.real-form {
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 14px 0;
}

.real-form .input {
  flex: none;
}

.real-form .save-btn {
  align-self: flex-start;
}

.note {
  color: var(--text-dim);
  font-size: 11.5px;
  line-height: 1.6;
  margin: 10px 0 12px;
}
</style>
