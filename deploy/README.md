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
# 后端测试与静态检查
cd backend && ../.venv/Scripts/python.exe -m pytest
cd backend && ../.venv/Scripts/ruff.exe check .

# 前端测试、静态检查与构建
cd frontend && npm run lint && npm test && npm run build

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
- 登录态:断网/刷新不掉登录;`mg_session` Cookie 的 `Max-Age` 为 30 天,
  而服务端 token 上限 24h(活跃用户由 `/api/auth/session` 自动轮换)

## 5. 进程与日志

- 参考 `deploy/mathguide.service` 用 systemd 托管后端;`data/` 是唯一可写目录。
- **必须单 worker**:限流器(`rate_limit`)、会话缓存(`session_cache`)、聊天检索缓存
  都放在进程内存里。加 `--workers 4` 会让"每账号 6 次/分"变成 24 次/分、
  缓存互相看不见(同一用户切到别的 worker 就像换了台机器)。
  启动时若检测到多 worker,后端会打一条 WARNING 提醒。
- **必须传 `--proxy-headers --forwarded-allow-ips=127.0.0.1`**:反向代理已带
  `X-Forwarded-For`,不显式声明时能否取到真实客户端 IP 取决于 uvicorn 版本默认值,
  而按 IP 限流与日志都依赖它。
- 参考 `deploy/logrotate.conf` 轮转 `/var/log/mathguide/*.log`(默认保留 14 天)。
- 如果使用 journald,改用 journald 的 `SystemMaxUse` / `MaxRetentionSec`。
- 日志级别用 `MG_LOG_LEVEL`(默认 INFO);每条带 `request_id`,同一次回答的多条
  日志可用它串起来。日志里不含问题正文、回答正文与手机号。

## 6. 备份与模型厂商

- 备份 `backend/data/` 到加密仓库(restic/borg),并定期做恢复演练;
  备份访问权限与生产数据同级。
- 在阿里云百炼 / 智谱控制台确认账号的数据留存与训练开关;
  实验数据不应被厂商用于训练,必要时签署 DPA/数据处理协议。
- 磁盘加密、`data/` 目录权限、密钥管理由部署主机负责;仓库只保证代码侧最小化。

## 7. 数据

- `backend/data/` 只允许后端进程用户读写;备份加密并限制访问。
- `usage.jsonl` / `usage.json` 已不含手机号/昵称;账号注销会级联删除。
- 定期备份 `backend/data/mathguide.db`(连同 `-wal` / `-shm`):停服务后
  `sqlite3 mathguide.db ".backup '/backup/mathguide.db'"` 或整目录复制;
  `tokens` 表只存 token 的 SHA-256,库文件泄露不等于凭据泄露。
- `users.json` / `tokens.json` 只在首次建库时作为迁移源被导入一次,之后不再写入;
  可留作历史备份,但**不要再按它们做日常备份**。
- 设置留存期限后由启动清理执行:
  ```ini
  MG_ACCOUNT_TTL_DAYS=180   # 长期未登录账号;管理员白名单不会被删
  MG_USAGE_TTL_DAYS=90      # 过期用量记录(JSONL 与旧备份)
  ```
- 实验结束按告知的保留期限删除账号数据,或让参与者自行注销。

## 导出 PDF(可选功能)

PDF 导出实现为「HTML + KaTeX → headless 浏览器打印」,因此**依赖服务器上有浏览器**。
没有浏览器时,`/api/doc/generate`、`/api/doc/qa`、`/api/doc/exercise` 的 PDF 分支返回
**500 `pdf render failed`**;Word / Markdown 导出不受影响(其中带竖线横线的数组公式会降级为纯文本)。

### 启用步骤(Linux)

```bash
apt install -y chromium fonts-noto-cjk
chromium --headless=new --disable-gpu --print-to-pdf=/tmp/t.pdf https://example.com
file /tmp/t.pdf          # 期望: PDF document
```

在 `backend/.env.local` 指定(优先级最高,配错不会兜底到别的浏览器):

```
MG_EDGE_PATH=/usr/bin/chromium
```

**沙箱受限的机器**(LXC/Docker 容器、Ubuntu 23.10+ 默认 `kernel.apparmor_restrict_unprivileged_userns=1`)
会「有 chromium 但打印不出 PDF」,这时才需要放开沙箱:

```
# MG_EDGE_NO_SANDBOX=1
```

生产渲染的是模型生成内容,沙箱该留着,所以**默认关闭**,只做显式开关。
该不该开不要猜 —— 下面的自检会在两种设置下各印一次,直接给结论;
若结论是「必须开」,生产配置必须同为 1,否则线上导出仍是 500。

### 版本要求

**装新版,不要刻意装旧版。** 推荐 chromium ≥ 120(或 Chrome/Edge ≥ 109);≥ 132 时 `--headless` 已等价于 `--headless=new`。

```bash
chromium --version        # 期望 >= 120
```

那为什么代码里还留着 `--headless` 旧参数的回退?**不是为了让你装旧版**,而是兜住两件控制不了的事:

- 目标机器可能是托管环境/云镜像,`apt` 里只有发行版自带那一版,你没法挑;
- 这个失败**完全静默**:返回码 0、日志无报错、就是没有 PDF。等用户点导出才发现,比多试一次贵得多。

代价是一次重试(仅在 `--headless=new` 不产出文件时触发),收益是把"静默 500"变成"照样能用"。
在镜像里固定了浏览器版本时,这层回退可视为纯保险,无需额外维护。

### 四个容易踩的点

1. **中文字体缺失 → PDF 里中文变方块**。必须装 `fonts-noto-cjk`(或 `fonts-wqy-zenhei`)。
   代码兜不住:字体不在系统里,渲染出来就是豆腐块。
   → 验收时**肉眼看中文正文**,不要只看“有没有生成 PDF”。
2. **`--headless` 参数新旧不一**。老发行版只认 `--headless`,新版只认 `--headless=new`;
   写死一个会**静默不产出 PDF**(返回码 0、无报错、就是没有文件)。
   → 代码已自动回退:先试 `--headless=new`,没产出文件再试 `--headless`。
3. **长文档超时**。默认 120 秒(`MG_PDF_TIMEOUT` 可调,下限 10 秒)。低配 VPS 建议 300。
4. **沙箱起不来**。容器 / Ubuntu 23.10+ 上 chromium 可能起来了却打不出 PDF(非 root 无法初始化 sandbox)。
   → 自检会判定「要不要开 `MG_EDGE_NO_SANDBOX=1`」;**自检时开了、生产忘开 = 线上照样 500**,两处必须一致。

### 上线前先跑自检(一条命令)

```bash
cd backend && python tools/check_pdf.py --out /tmp/selfcheck.pdf
```

依次检查五项:浏览器能否发现(含版本号)、系统是否有中文字体、能否真的打印出 PDF
(含 `--headless` 参数回退,并在 `MG_EDGE_NO_SANDBOX` 两种取值下各印一次以判定要不要放开沙箱)、
PDF 里是否嵌入了 CJK 字体、PDF 文本层能否读到中文。任一项失败都会打印**具体修复建议**
并以退出码 1 结束 —— 比等到用户点「导出」才发现要早得多。

> 自检通过只能证明"机器能出 PDF",**证明不了"公式印对了"**。所以下面这次眼验仍然要做。

### 部署后必做的一次冒烟

导出一份「含数组公式(竖线横线)+ 中文」的文档,肉眼确认三件事:
**公式在不在 / 表格线在不在 / 中文有没有变方块**。
