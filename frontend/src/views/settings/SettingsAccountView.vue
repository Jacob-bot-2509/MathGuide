<script setup lang="ts">
/**
 * 账号管理:头像(预设 + 相册上传,需相册授权)、昵称、手机号、
 * 实名认证状态与实名信息补全。
 */
import { computed, ref } from 'vue'
import { useRouter } from 'vue-router'
import UserAvatar from '@/components/common/UserAvatar.vue'
import { updateUser, userState } from '@/stores/user'
import { clearAllTodoData } from '@/stores/todo'
import { settingsState } from '@/stores/settings'
import { deleteAccount, exportAccountData } from '@/services/accountService'
import { logout } from '@/services/authService'
import { AVATAR_PRESETS, fileToAvatar } from '@/utils/avatar'
import SettingsShell from '@/components/common/SettingsShell.vue'
import { authName, realnameText, t } from '@/utils/i18n'
import { showToast } from '@/utils/toast'


const router = useRouter()
const nickname = ref(userState.info?.nickname ?? '')
const pickingAvatar = ref(false)
const fileEl = ref<HTMLInputElement | null>(null)
const realName = ref('')
const realId = ref('')
const dataBusy = ref(false)
const deleting = ref(false)
const deletePassword = ref('')
const deleteWord = ref('')

const user = computed(() => userState.info)
const en = computed(() => settingsState.language === 'en')
const needsPassword = computed(() => user.value?.authMethod === 'phone-pass')
const expectedWord = computed(() => (en.value ? 'DELETE' : '注销'))
const canDelete = computed(() => (
  needsPassword.value ? deletePassword.value.length > 0 : deleteWord.value.trim() === expectedWord.value
))

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

async function exportData() {
  if (dataBusy.value) return
  dataBusy.value = true
  try {
    const mode = await exportAccountData()
    showToast(mode === 'full' ? t('acc.exportDone') : t('acc.exportLocalOnly'))
  } catch {
    showToast(t('acc.exportFail'))
  } finally {
    dataBusy.value = false
  }
}

function openDelete() {
  deleting.value = true
  deletePassword.value = ''
  deleteWord.value = ''
}

function cancelDelete() {
  deleting.value = false
  deletePassword.value = ''
  deleteWord.value = ''
}

async function confirmDelete() {
  if (!canDelete.value) {
    showToast(t('acc.deleteNeedConfirm'))
    return
  }
  dataBusy.value = true
  try {
    const result = await deleteAccount(
      needsPassword.value
        ? { password: deletePassword.value }
        : { confirm: deleteWord.value.trim() },
    )
    if (result === 'wrong') {
      showToast(t('acc.deleteWrong'))
      return
    }
    // 后端已删除账号与全部 token;本机学习数据也要一起清掉
    logout()
    clearAllTodoData()
    deleting.value = false
    router.push('/login')
    showToast(t('acc.deleteDone'))
  } catch {
    showToast(t('acc.deleteFail'))
  } finally {
    dataBusy.value = false
  }
}
</script>

<template>
  <SettingsShell :title="t('acc.title')">
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

    <!-- 数据与账号 -->
    <p class="section tech-label">{{ t('acc.data') }}</p>
    <div class="info-card">
      <div class="action-row">
        <div class="action-text">
          <span class="k">{{ t('acc.export') }}</span>
          <span class="desc">{{ t('acc.exportDesc') }}</span>
        </div>
        <button class="ghost-btn" :disabled="dataBusy" @click="exportData">
          {{ dataBusy ? t('acc.processing') : t('acc.exportBtn') }}
        </button>
      </div>
      <div class="action-row">
        <div class="action-text">
          <span class="k">{{ t('acc.delete') }}</span>
          <span class="desc">{{ t('acc.deleteDesc') }}</span>
        </div>
        <button class="danger-btn" :disabled="dataBusy" @click="openDelete">{{ t('acc.deleteBtn') }}</button>
      </div>
    </div>

    <div v-if="deleting" class="delete-panel">
      <p class="delete-warn">
        {{ needsPassword ? t('acc.deleteWarnPass') : t('acc.deleteWarnWord', { word: expectedWord }) }}
      </p>
      <input
        v-if="needsPassword"
        v-model="deletePassword"
        class="input"
        type="password"
        autocomplete="current-password"
        :placeholder="t('acc.deletePasswordPh')"
        @keyup.enter="confirmDelete"
      />
      <input
        v-else
        v-model="deleteWord"
        class="input"
        type="text"
        autocomplete="off"
        :placeholder="t('acc.deleteWordPh', { word: expectedWord })"
        @keyup.enter="confirmDelete"
      />
      <div class="delete-actions">
        <button class="danger-btn" :disabled="dataBusy || !canDelete" @click="confirmDelete">
          {{ dataBusy ? t('acc.processing') : t('acc.deleteConfirmBtn') }}
        </button>
        <button class="ghost-btn" :disabled="dataBusy" @click="cancelDelete">{{ t('acc.cancel') }}</button>
      </div>
    </div>
  </SettingsShell>
</template>

<style scoped>
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

.action-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 13px 0;
  border-bottom: 1px solid var(--line);
}

.action-row:last-child {
  border-bottom: none;
}

.action-text {
  display: flex;
  flex-direction: column;
  gap: 3px;
  min-width: 0;
}

.action-text .desc {
  color: var(--text-dim);
  font-size: 11.5px;
  line-height: 1.55;
}

.action-row .ghost-btn,
.action-row .danger-btn {
  flex-shrink: 0;
  white-space: nowrap;
}

.danger-btn {
  background: color-mix(in srgb, var(--danger) 6%, transparent);
  border: 1px solid color-mix(in srgb, var(--danger) 45%, transparent);
  color: var(--danger);
  padding: 8px 16px;
  border-radius: 8px;
  cursor: pointer;
  font-size: 13px;
  flex-shrink: 0;
  transition: all var(--dur-fast) var(--ease-out);
}

.danger-btn:hover:not(:disabled) {
  background: color-mix(in srgb, var(--danger) 14%, transparent);
  box-shadow: 0 0 10px color-mix(in srgb, var(--danger) 30%, transparent);
}

.ghost-btn:disabled,
.danger-btn:disabled,
.save-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.delete-panel {
  margin-top: 12px;
  padding: 14px 16px;
  border: 1px solid color-mix(in srgb, var(--danger) 38%, transparent);
  border-radius: 10px;
  background: color-mix(in srgb, var(--danger) 5%, var(--bg-card));
}

.delete-warn {
  margin: 0 0 10px;
  color: var(--text);
  font-size: 12.5px;
  line-height: 1.65;
}

.delete-panel .input {
  width: 100%;
  box-sizing: border-box;
  flex: none;
  background: var(--bg-void);
}

.delete-actions {
  display: flex;
  gap: 9px;
  margin-top: 11px;
}

.note {
  color: var(--text-dim);
  font-size: 11.5px;
  line-height: 1.6;
  margin: 10px 0 12px;
}
</style>
