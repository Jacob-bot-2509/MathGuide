# 部署清单(实验测评)

目标:公网 HTTPS + 关闭演示通道 + 保留测评注册入口 + CSP。

## 1. 后端配置

在 `backend/.env.local` 至少设置:

```ini
MG_DEMO_MODE=0
MG_INVITE_CODES=eval-2026-a,eval-2026-b
# 双域隔离:两个子域共享登录 Cookie(Cookie 只作用于父域)
MG_COOKIE_DOMAIN=.example.com
# 前端经各子域 /api 同域反代时不需要 CORS;只在直连 API 域名时配置
# MG_CORS_ORIGINS=https://learn.example.com,https://research.example.com
MG_AUTH_RATE_MAX=30
MG_AUTH_RATE_WINDOW=60
# 管理员白名单,否则 /api/stats 无人可访问,留存清理也不会保护管理员
MG_ADMIN_PHONES=你的手机号
# 可选:自动留存清理(0=关闭)
# MG_ACCOUNT_TTL_DAYS=180
# MG_USAGE_TTL_DAYS=90
# 反向代理时由 Caddy/Nginx 传 X-Forwarded-Proto,后端会按 HTTPS 发 HSTS
# MG_ENABLE_HSTS=1
```

- `MG_DEMO_MODE=0` 后固定验证码、微信/QQ 游客登录、开放注册全部关闭。
- 测评同学用 `MG_INVITE_CODES` 中的邀请码注册;邀请码共享,按批次轮换。
- 后端只监听 `127.0.0.1:8000`,不要直接暴露公网端口。
- 若多人共用实验室出口 IP,把 `MG_AUTH_RATE_MAX` 调大。

## 2. 前端构建

```bash
cd frontend
npm ci
npm run build
```

产物在 `frontend/dist`。`theme-init.js` 已从内联脚本拆成独立文件,
所以 CSP 不需要放开 `script-src 'unsafe-inline'`。

## 3. 反向代理

二选一:

- Caddy:`caddy run --config deploy/Caddyfile`
- Nginx:参考 `deploy/nginx.conf`

如果前端与 API 不同源,把 CSP 的 `connect-src` 加上 API 域名,
并把该域名加入 `MG_CORS_ORIGINS`。

两者都做了:

- HTTPS 终止 + HSTS
- `/api/*` 反代到 `127.0.0.1:8000`
- SPA `try_files ... /index.html`
- CSP(脚本只允许自身;样式因 KaTeX 保留 `unsafe-inline`)
- `X-Content-Type-Options` / `Referrer-Policy` / `X-Frame-Options` / `Permissions-Policy`

首次上线先确认 HTTPS 与 SSE 正常,再长期保留 HSTS。

## 4. 上线前检查

```bash
# 后端测试
cd backend && ../.venv/Scripts/python.exe -m pytest

# 前端测试与构建
cd frontend && npm test && npm run build

# 公网绑定必须被拒绝(MG_DEMO_MODE=1 时)
cd backend && ../.venv/Scripts/python.exe -m uvicorn main:app --host 0.0.0.0 --port 8010
# 预期:RuntimeError,不会启动
```

浏览器检查:

- `https://mg.example.com` 证书有效,HSTS 存在
- 注册必须填邀请码;`123456` 验证码登录返回 400
- 账号页可导出数据、可注销
- 浏览器控制台无 CSP violation
- SSE 回答能持续输出,不被代理缓冲

## 5. 进程与日志

- 参考 `deploy/mathguide.service` 用 systemd 托管后端;`data/` 是唯一可写目录。
- 参考 `deploy/logrotate.conf` 轮转 `/var/log/mathguide/*.log`(默认保留 14 天)。
- 如果使用 journald,改用 journald 的 `SystemMaxUse` / `MaxRetentionSec`。

## 6. 备份与模型厂商

- 备份 `backend/data/` 到加密仓库(restic/borg),并定期做恢复演练;
  备份访问权限与生产数据同级。
- 在阿里云百炼 / 智谱控制台确认账号的数据留存与训练开关;
  实验数据不应被厂商用于训练,必要时签署 DPA/数据处理协议。
- 磁盘加密、`data/` 目录权限、密钥管理由部署主机负责;仓库只保证代码侧最小化。

## 7. 数据

- `backend/data/` 只允许后端进程用户读写;备份加密并限制访问。
- `usage.jsonl` / `usage.json` 已不含手机号/昵称;账号注销会级联删除。
- 定期备份 `users.json` / `tokens.json`;`tokens.json` 只存 SHA-256 哈希。
- 设置留存期限后由启动清理执行:
  ```ini
  MG_ACCOUNT_TTL_DAYS=180   # 长期未登录账号;管理员白名单不会被删
  MG_USAGE_TTL_DAYS=90      # 过期用量记录(JSONL 与旧备份)
  ```
- 实验结束按告知的保留期限删除账号数据,或让参与者自行注销。
