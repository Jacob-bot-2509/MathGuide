import { createRouter, createWebHistory } from 'vue-router'
import IntroView from '@/views/IntroView.vue'
import { isLoggedIn } from '@/stores/user'
import { t } from '@/utils/i18n'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', name: 'intro', component: IntroView },
    {
      path: '/login',
      name: 'login',
      component: () => import('@/views/LoginView.vue'),
    },
    {
      path: '/home',
      name: 'home',
      component: () => import('@/views/HomeView.vue'),
      meta: { requiresAuth: true },
    },
    {
      path: '/learn',
      name: 'learn',
      component: () => import('@/views/LearnView.vue'),
      meta: { requiresAuth: true },
    },
    {
      path: '/research',
      name: 'research',
      component: () => import('@/views/ResearchView.vue'),
      meta: { requiresAuth: true },
    },
    {
      path: '/settings',
      name: 'settings',
      component: () => import('@/views/settings/SettingsView.vue'),
      meta: { requiresAuth: true },
    },
    {
      path: '/settings/account',
      name: 'settings-account',
      component: () => import('@/views/settings/SettingsAccountView.vue'),
      meta: { requiresAuth: true },
    },
    {
      path: '/settings/privacy',
      name: 'settings-privacy',
      component: () => import('@/views/settings/SettingsPrivacyView.vue'),
      meta: { requiresAuth: true },
    },
    {
      path: '/settings/about',
      name: 'settings-about',
      component: () => import('@/views/settings/SettingsAboutView.vue'),
      meta: { requiresAuth: true },
    },
    {
      path: '/settings/trash',
      name: 'settings-trash',
      component: () => import('@/views/settings/SettingsTrashView.vue'),
      meta: { requiresAuth: true },
    },
  ],
})

// 登录守卫:需要登录的页面未登录 → 登录页;已登录访问登录页 → 首页
router.beforeEach((to) => {
  const authed = isLoggedIn()
  if (to.meta.requiresAuth && !authed) return { path: '/login' }
  if (to.path === '/login' && authed) return { path: '/home' }
})

// 标题文案的唯一真源是 i18n 的 title.*;此前路由表里还各挂了一份中文 meta.title,
// 且 `t(...) ?? fallback` 是死代码 —— t() 查不到时返回 key 本身,永远不为 null
router.afterEach((to) => {
  document.title = to.name ? t(`title.${String(to.name)}`) : 'MathGuide'
})

export default router
