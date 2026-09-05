<script setup lang="ts">
/**
 * 登录界面:登录方式即实名认证方式。
 * - 手机号 + 密码 / 手机号 + 验证码(演示验证码 123456)
 * - 微信 / QQ:与用户设备上的账号做交接(演示环境模拟授权流程,
 *   真实接入需微信开放平台 / QQ 互联 SDK)
 */
import { onBeforeUnmount, ref } from 'vue'
import { useRouter } from 'vue-router'
import Starfield from '@/components/common/Starfield.vue'
import { DEMO_CODE, loginWithCode, loginWithPassword, loginWithThirdParty, registerWithPassword } from '@/services/authService'
import { userState } from '@/stores/user'
import { t } from '@/utils/i18n'
import { showToast } from '@/utils/toast'

const router = useRouter()

const mode = ref<'pass' | 'code' | 'register'>('pass')
const phone = ref('')
const password = ref('')
const confirm = ref('')
const code = ref('')
const countdown = ref(0)
const authing = ref<'' | 'wechat' | 'qq'>('')

let cdTimer: ReturnType<typeof setInterval> | null = null

function validPhone(): boolean {
  return /^1[3-9]\d{9}$/.test(phone.value)
}

function sendCode() {
  if (!validPhone()) {
    showToast(t('login.toastPhone'))
    return
  }
  showToast(t('login.toastCodeSent'), 3200)
  countdown.value = 60
  cdTimer = setInterval(() => {
    countdown.value--
    if (countdown.value <= 0 && cdTimer) {
      clearInterval(cdTimer)
      cdTimer = null
    }
  }, 1000)
}

async function doPhoneLogin() {
  if (!validPhone()) {
    showToast(t('login.toastPhone'))
    return
  }
  try {
    if (mode.value === 'pass') {
      if (password.value.length < 6) {
        showToast(t('login.toastPw'))
        return
      }
      const result = await loginWithPassword(phone.value, password.value)
      if (result === 'notfound') {
        showToast(t('login.toastNotFound'), 3200)
        mode.value = 'register'
        return
      }
      if (result === 'wrong') {
        showToast(t('login.toastWrong'))
        return
      }
      entered()
      return
    }
    // 验证码登录:未注册手机号自动创建账户
    if (code.value !== DEMO_CODE) {
      showToast(t('login.toastCodeErr'))
      return
    }
    await loginWithCode(phone.value, code.value)
    entered()
  } catch {
    showToast(t('login.toastNet'))
  }
}

/** 创建账户 */
async function doRegister() {
  if (!validPhone()) {
    showToast(t('login.toastPhone'))
    return
  }
  if (code.value !== DEMO_CODE) {
    showToast(t('login.toastCodeErr'))
    return
  }
  if (password.value.length < 6) {
    showToast(t('login.toastPw'))
    return
  }
  if (confirm.value !== password.value) {
    showToast(t('login.toastMismatch'))
    return
  }
  try {
    if (!(await registerWithPassword(phone.value, password.value))) {
      showToast(t('login.toastExists'))
      mode.value = 'pass'
      confirm.value = ''
      return
    }
    showToast(t('login.toastCreated'))
    entered()
  } catch {
    showToast(t('login.toastNet'))
  }
}

/** 微信 / QQ:模拟与设备上账号的授权交接 */
function thirdAuth(kind: 'wechat' | 'qq') {
  if (authing.value) return
  authing.value = kind
  setTimeout(async () => {
    try {
      await loginWithThirdParty(kind)
      entered()
    } catch {
      showToast(t('login.toastNet'))
    } finally {
      authing.value = ''
    }
  }, 1400)
}

/** 登录成功后的统一收尾 */
function entered() {
  showToast(`${t('login.welcome')}${userState.info?.nickname ?? ''}`)
  router.push('/home')
}

onBeforeUnmount(() => {
  if (cdTimer) clearInterval(cdTimer)
})
</script>

<template>
  <div class="login">
    <Starfield class="bg" />

    <main class="panel">
      <div class="brand">
        <span class="brand-mark">MG</span>
        <span class="brand-name">MATHGUIDE</span>
      </div>
      <p class="slogan">{{ t('login.slogan') }}</p>

      <!-- 手机号登录 -->
      <div class="tabs">
        <button class="tab" :class="{ on: mode === 'pass' }" @click="mode = 'pass'">{{ t('login.tabPass') }}</button>
        <button class="tab" :class="{ on: mode === 'code' }" @click="mode = 'code'">{{ t('login.tabCode') }}</button>
        <button class="tab" :class="{ on: mode === 'register' }" @click="mode = 'register'">{{ t('login.tabRegister') }}</button>
      </div>

      <div class="field">
        <span class="prefix">+86</span>
        <input v-model="phone" class="input" type="tel" maxlength="11" :placeholder="t('login.phone')" />
      </div>

      <template v-if="mode === 'pass'">
        <div class="field">
          <input v-model="password" class="input" type="password" :placeholder="t('login.password')" />
        </div>
      </template>

      <template v-else-if="mode === 'code'">
        <div class="field field-code">
          <input v-model="code" class="input" type="text" maxlength="6" :placeholder="t('login.code')" />
          <button class="code-btn" :disabled="countdown > 0" @click="sendCode">
            {{ countdown > 0 ? `${countdown}${t('login.resend')}` : t('login.getCode') }}
          </button>
        </div>
      </template>

      <template v-else>
        <div class="field field-code">
          <input v-model="code" class="input" type="text" maxlength="6" :placeholder="t('login.code')" />
          <button class="code-btn" :disabled="countdown > 0" @click="sendCode">
            {{ countdown > 0 ? `${countdown}${t('login.resend')}` : t('login.getCode') }}
          </button>
        </div>
        <div class="field">
          <input v-model="password" class="input" type="password" :placeholder="t('login.setPassword')" />
        </div>
        <div class="field">
          <input v-model="confirm" class="input" type="password" :placeholder="t('login.confirm')" />
        </div>
      </template>

      <button class="login-btn" @click="mode === 'register' ? doRegister() : doPhoneLogin()">
        {{ mode === 'pass' ? t('login.submitLogin') : mode === 'code' ? t('login.submitAuto') : t('login.submitRegister') }}
      </button>

      <!-- 第三方登录 -->
      <div class="divider"><span>{{ t('login.third') }}</span></div>
      <div class="third">
        <button class="third-btn wechat" @click="thirdAuth('wechat')">
          <span class="icon">微</span>{{ t('login.wechat') }}
        </button>
        <button class="third-btn qq" @click="thirdAuth('qq')">
          <span class="icon">Q</span>{{ t('login.qq') }}
        </button>
      </div>

      <p class="agreement">{{ t('login.agreement') }}</p>
    </main>

    <!-- 第三方授权交接模拟层 -->
    <div v-if="authing" class="auth-overlay">
      <div class="auth-card">
        <p class="auth-title">{{ authing === 'wechat' ? t('login.authTitleWx') : t('login.authTitleQq') }}</p>
        <p class="auth-desc">{{ t('login.authDesc') }}</p>
        <div class="spinner"></div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.login {
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24px;
  position: relative;
}

.bg {
  position: fixed;
  inset: 0;
  z-index: -1;
  opacity: 0.85;
}

.panel {
  width: min(400px, 100%);
  background: var(--bg-panel);
  border: 1px solid var(--line);
  border-radius: 16px;
  padding: 36px 32px 28px;
  backdrop-filter: blur(10px);
  box-shadow: 0 0 60px rgba(77, 214, 255, 0.06);
}

.brand {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 10px;
}

.brand-mark {
  font-family: var(--font-tech);
  font-weight: 700;
  color: var(--cyan);
  border: 1px solid var(--line-bright);
  padding: 3px 8px;
  border-radius: 4px;
  box-shadow: var(--glow-cyan);
  font-size: 14px;
}

.brand-name {
  font-family: var(--font-tech);
  letter-spacing: 0.2em;
  color: var(--text-hi);
  font-size: 18px;
}

.slogan {
  text-align: center;
  color: var(--text-dim);
  font-size: 12px;
  margin: 14px 0 22px;
}

.tabs {
  display: flex;
  border-bottom: 1px solid var(--line);
  margin-bottom: 20px;
}

.tab {
  flex: 1;
  background: transparent;
  border: none;
  color: var(--text-dim);
  padding: 10px 0;
  cursor: pointer;
  font-size: 14px;
  position: relative;
  transition: color var(--dur-fast);
}

.tab::after {
  content: "";
  position: absolute;
  left: 30%;
  right: 30%;
  bottom: -1px;
  height: 2px;
  background: var(--cyan);
  transform: scaleX(0);
  transition: transform var(--dur-med) var(--ease-out);
}

.tab.on {
  color: var(--cyan);
}

.tab.on::after {
  transform: scaleX(1);
}

.field {
  display: flex;
  align-items: center;
  gap: 10px;
  background: var(--bg-card);
  border: 1px solid var(--line);
  border-radius: 10px;
  padding: 0 14px;
  margin-bottom: 14px;
  transition: border-color var(--dur-fast);
}

.field:focus-within {
  border-color: var(--line-bright);
}

.prefix {
  color: var(--text-dim);
  font-size: 13px;
  border-right: 1px solid var(--line);
  padding-right: 10px;
}

.input {
  flex: 1;
  background: transparent;
  border: none;
  outline: none;
  color: var(--text);
  font-size: 14px;
  padding: 12px 0;
}

.input::placeholder {
  color: var(--text-dim);
}

.field-code .input {
  min-width: 0;
}

.code-btn {
  background: transparent;
  border: none;
  color: var(--cyan);
  cursor: pointer;
  font-size: 13px;
  white-space: nowrap;
  padding: 6px 0;
}

.code-btn:disabled {
  color: var(--text-dim);
  cursor: not-allowed;
}

.login-btn {
  width: 100%;
  background: rgba(77, 214, 255, 0.12);
  border: 1px solid var(--line-bright);
  color: var(--cyan);
  padding: 12px;
  border-radius: 10px;
  cursor: pointer;
  font-size: 15px;
  letter-spacing: 0.2em;
  transition: all var(--dur-fast) var(--ease-out);
}

.login-btn:hover {
  background: rgba(77, 214, 255, 0.2);
  box-shadow: var(--glow-cyan);
}

.divider {
  display: flex;
  align-items: center;
  gap: 12px;
  margin: 22px 0 14px;
  color: var(--text-dim);
  font-size: 11px;
}

.divider::before,
.divider::after {
  content: "";
  flex: 1;
  height: 1px;
  background: var(--line);
}

.third {
  display: flex;
  gap: 14px;
}

.third-btn {
  flex: 1;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  background: transparent;
  border: 1px solid var(--line);
  color: var(--text);
  padding: 10px;
  border-radius: 10px;
  cursor: pointer;
  font-size: 13px;
  transition: all var(--dur-fast) var(--ease-out);
}

.third-btn .icon {
  display: grid;
  place-items: center;
  width: 20px;
  height: 20px;
  border-radius: 50%;
  font-size: 11px;
  font-weight: 700;
}

.third-btn.wechat:hover {
  border-color: #4dffb8;
  color: #4dffb8;
  box-shadow: 0 0 10px rgba(77, 255, 184, 0.25);
}

.third-btn.wechat .icon {
  background: #4dffb8;
  color: #06281c;
}

.third-btn.qq:hover {
  border-color: var(--blue);
  color: var(--blue);
  box-shadow: 0 0 10px rgba(47, 123, 255, 0.25);
}

.third-btn.qq .icon {
  background: var(--blue);
  color: #fff;
}

.agreement {
  text-align: center;
  color: var(--text-dim);
  font-size: 11px;
  margin: 18px 0 0;
}

/* ---------- 授权交接模拟层 ---------- */
.auth-overlay {
  position: fixed;
  inset: 0;
  z-index: 50;
  background: rgba(3, 5, 9, 0.75);
  display: flex;
  align-items: center;
  justify-content: center;
  backdrop-filter: blur(4px);
}

.auth-card {
  background: var(--bg-panel);
  border: 1px solid var(--line-bright);
  border-radius: 14px;
  padding: 30px 34px;
  text-align: center;
  box-shadow: var(--glow-cyan);
}

.auth-title {
  color: var(--text-hi);
  font-size: 15px;
  margin: 0 0 8px;
}

.auth-desc {
  color: var(--text-dim);
  font-size: 12px;
  margin: 0 0 18px;
}

.spinner {
  width: 26px;
  height: 26px;
  margin: 0 auto;
  border: 2px solid var(--line);
  border-top-color: var(--cyan);
  border-radius: 50%;
  animation: mg-spin 0.8s linear infinite;
}
</style>
