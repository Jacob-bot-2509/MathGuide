import { createApp } from 'vue'
import App from './App.vue'
import router from './router'
import './styles/tokens.css'
import './styles/base.css'
import 'katex/dist/katex.min.css'

createApp(App).use(router).mount('#app')
