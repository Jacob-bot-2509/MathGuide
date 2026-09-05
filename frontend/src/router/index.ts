import { createRouter, createWebHistory } from 'vue-router'
import IntroView from '@/views/IntroView.vue'
import { isLoggedIn } from '@/stores/user'
import { t } from '@/utils/i18n'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', name: 'intro', component: IntroView, meta: { title: 'MathGuide' } },
    {
      path: '/login',
      name: 'login',
      component: () => import('@/views/LoginView.vue'),
      meta: { title: '登录 · MathGuide' },
    },
    {
      path: '/home',
      name: 'home',
      component: () => import('@/views/HomeView.vue'),
      meta: { title: 'MathGuide · 首页', requiresAuth: true },
    },
    {
      path: '/learn',
      name: 'learn',
      component: () => import('@/views/LearnView.vue'),
      meta: { title: 'MathGuide · 学习辅助', requiresAuth: true },
    },
    {
      path: '/research',
      name: 'research',
      component: () => import('@/views/ResearchView.vue'),
      meta: { title: 'MathGuide · 科学研究', requiresAuth: true },
    },
    {
      path: '/settings',
      name: 'settings',
      component: () => import('@/views/settings/SettingsView.vue'),
      meta: { title: 'MathGuide · 设置', requiresAuth: true },
    },
    {
      path: '/settings/account',
      name: 'settings-account',
      component: () => import('@/views/settings/SettingsAccountView.vue'),
      meta: { title: 'MathGuide · 账号管理', requiresAuth: true },
    },
    {
      path: '/settings/privacy',
      name: 'settings-privacy',
      component: () => import('@/views/settings/SettingsPrivacyView.vue'),
      meta: { title: 'MathGuide · 隐私与安全', requiresAuth: true },
    },
    {
      path: '/settings/about',
      name: 'settings-about',
      component: () => import('@/views/settings/SettingsAboutView.vue'),
      meta: { title: 'MathGuide · 关于', requiresAuth: true },
    },
    {
      path: '/settings/trash',
      name: 'settings-trash',
      component: () => import('@/views/settings/SettingsTrashView.vue'),
      meta: { title: 'MathGuide · 回收站', requiresAuth: true },
    },
  ],
})

// 登录守卫:需要登录的页面未登录 → 登录页;已登录访问登录页 → 首页
router.beforeEach((to) => {
  const authed = isLoggedIn()
  if (to.meta.requiresAuth && !authed) return { path: '/login' }
  if (to.path === '/login' && authed) return { path: '/home' }
})

router.afterEach((to) => {
  const name = to.name ? String(to.name) : ''
  document.title = t(`title.${name}`) ?? (to.meta.title as string) ?? 'MathGuide'
})

export default router
