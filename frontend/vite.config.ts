import { fileURLToPath, URL } from 'node:url'
import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
    // D:\code 是指向 D:\Works\code 的junction(仓库实际路径)。默认 Vite 会把入口
    // 解析成 realpath,再按 root 求相对路径,得到 "../../Works/code/frontend/index.html",
    // vite:build-html 直接报错("fileName must not be absolute or relative path")。
    // 保留符号链接路径后,从 D:\code 下执行 npm run build 与在真实路径下一致。
    preserveSymlinks: true,
  },
  server: {
    // 仅本机访问(未设置 host → 默认 localhost,不对外网卡监听)
    port: 5173,
    strictPort: true,
    proxy: {
      // 开发环境:后端接口统一走 vite 代理 → 同源(免 CORS)
      '/api': { target: 'http://127.0.0.1:8000', changeOrigin: true },
    },
  },
  build: {
    // mathjax-full 体积较大,单独分块是正常现象,提高告警阈值
    chunkSizeWarningLimit: 1800,
  },
})
