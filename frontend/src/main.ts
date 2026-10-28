import { createApp } from 'vue'
import App from './App.vue'
import router from './router'
import { bootstrapSession } from './services/authService'
import './styles/tokens.css'
import './styles/base.css'
import 'katex/dist/katex.min.css'

/** 先恢复共享登录态再挂载:双域部署下 Cookie 有效、但本子域
 *  localStorage 为空的用户不会被路由守卫误踢回登录页。
 *  后端不可达时最多等 3 秒,不让启动无限挂起。 */
async function start() {
  await Promise.race([
    bootstrapSession(),
    new Promise((resolve) => setTimeout(resolve, 3000)),
  ])
  createApp(App).use(router).mount('#app')
}

void start()
