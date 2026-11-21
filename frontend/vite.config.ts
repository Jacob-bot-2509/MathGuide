import { readFileSync } from 'node:fs'
import { fileURLToPath, URL } from 'node:url'
import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// 本地 HTTPS(内网 iPad 调试):设置 MG_HTTPS_CERT / MG_HTTPS_KEY 指向 mkcert 证书;
// 不设置时保持 HTTP 本机开发。生产由 nginx 终止 TLS,不读这两个变量。
const httpsCert = process.env.MG_HTTPS_CERT
const httpsKey = process.env.MG_HTTPS_KEY
const https = httpsCert && httpsKey
  ? { cert: readFileSync(httpsCert), key: readFileSync(httpsKey) }
  : undefined

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
    // 仅本机访问(未设置 host → 默认 localhost,不对外网卡监听);
    // 开 HTTPS 时监听所有网卡,供 iPad 通过局域网访问。
    host: https ? '0.0.0.0' : undefined,
    https,
    port: 5173,
    strictPort: true,
    proxy: {
      // 开发环境:后端接口统一走 vite 代理 → 同源(免 CORS)。
      // 多工作树并行时用 MG_API_TARGET 指向另一端口的主仓库后端。
      '/api': {
        target: process.env.MG_API_TARGET || 'http://127.0.0.1:8000',
        // 保留浏览器原始 Host:后端 OriginGuard 用 Origin 的 netloc 与 Host 比对,
        // 改写 Host 会让局域网 IP 访问(如 iPad 连 http://192.168.x.x:5173)被判跨源 403。
        changeOrigin: false,
        // 本地 HTTPS 时告诉后端原始请求是 https:Cookie 的 Secure 与 HSTS 判定要用
        headers: https ? { 'X-Forwarded-Proto': 'https' } : undefined,
      },
    },
  },
  build: {
    // mathjax-full 体积较大,单独分块是正常现象,提高告警阈值
    chunkSizeWarningLimit: 1800,
  },
})
