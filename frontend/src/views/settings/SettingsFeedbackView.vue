<script setup lang="ts">
/**
 * 功能与改进:反馈表单。
 * 演示环境没有反馈后端,提交时在 GitHub 打开一条预填的 issue;
 * 不在本机假装"已上传",也不收集任何额外个人信息。
 */
import { ref } from 'vue'
import SettingsShell from '@/components/common/SettingsShell.vue'
import { APP_ISSUES_URL, APP_REPO_URL, APP_VERSION } from '@/utils/aboutContent'
import { t } from '@/utils/i18n'
import { showToast } from '@/utils/toast'

const feedback = ref('')
const MAX = 1000

function submitFeedback() {
  const value = feedback.value.trim()
  if (!value) {
    showToast(t('feedback.toastEmpty'))
    return
  }
  const firstLine = value.split('\n')[0].slice(0, 60)
  const body = `${value}\n\n---\nMathGuide ${APP_VERSION} · ${new Date().toISOString().slice(0, 10)}`
  const url =
    `${APP_REPO_URL}/issues/new?labels=feedback` +
    `&title=${encodeURIComponent(`[Feedback] ${firstLine}`)}` +
    `&body=${encodeURIComponent(body)}`
  // 不用 "noopener" 窗口特性:带该特性时部分浏览器即使成功打开也返回 null,
  // 会被误判成"被拦截";先打开再断开 opener 同样安全。
  const opened = window.open(url, '_blank')
  if (!opened) {
    showToast(t('feedback.toastBlocked'))
    return
  }
  opened.opener = null
  feedback.value = ''
  showToast(t('feedback.toastOpened'))
}
</script>

<template>
  <SettingsShell :title="t('feedback.title')">
    <p class="lead">{{ t('feedback.lead') }}</p>

    <div class="card">
      <textarea
        v-model="feedback"
        class="feedback"
        rows="6"
        :maxlength="MAX"
        :placeholder="t('feedback.ph')"
      ></textarea>
      <div class="actions">
        <span class="count">{{ feedback.length }} / {{ MAX }}</span>
        <button class="submit" @click="submitFeedback">{{ t('feedback.submit') }}</button>
      </div>
    </div>

    <p class="note">{{ t('feedback.note') }}</p>
    <p class="note note--warn">{{ t('feedback.privacyNote') }}</p>
    <a class="issue-link" :href="APP_ISSUES_URL" target="_blank" rel="noopener noreferrer">
      {{ t('feedback.issues') }} <span aria-hidden="true">↗</span>
    </a>
  </SettingsShell>
</template>

<style scoped>
.lead {
  margin: 0 0 12px;
  color: var(--text);
  font-size: 13px;
  line-height: 1.75;
}

.card {
  background: var(--bg-card);
  border: 1px solid var(--line);
  border-radius: 10px;
  padding: 14px 16px;
}

.feedback {
  width: 100%;
  box-sizing: border-box;
  resize: vertical;
  min-height: 120px;
  background: var(--bg-void);
  border: 1px solid var(--line);
  border-radius: 8px;
  color: var(--text);
  padding: 10px 13px;
  font-size: 13.5px;
  font-family: var(--font-ui);
  line-height: 1.7;
  outline: none;
  transition: border-color var(--dur-fast);
}

.feedback:focus {
  border-color: var(--line-bright);
}

.feedback::placeholder {
  color: var(--text-dim);
}

.actions {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-top: 11px;
}

.count {
  font-family: var(--font-tech);
  color: var(--text-dim);
  font-size: 10.5px;
}

.submit {
  margin-left: auto;
  background: rgba(77, 214, 255, 0.1);
  border: 1px solid var(--line-bright);
  color: var(--cyan);
  padding: 8px 20px;
  border-radius: 8px;
  cursor: pointer;
  font-size: 13px;
  transition: all var(--dur-fast) var(--ease-out);
}

.submit:hover {
  background: rgba(77, 214, 255, 0.18);
  box-shadow: var(--glow-cyan);
}

.note {
  margin: 14px 0 0;
  color: var(--text-dim);
  font-size: 11.5px;
  line-height: 1.7;
}

.note--warn {
  margin-top: 5px;
  color: color-mix(in srgb, var(--danger) 78%, var(--text));
}

.issue-link {
  display: inline-block;
  margin-top: 10px;
  color: var(--cyan);
  font-size: 12px;
  text-decoration: none;
}

.issue-link:hover {
  text-shadow: 0 0 10px rgba(77, 214, 255, 0.5);
}
</style>
