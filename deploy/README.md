# 部署清单(实验测评)

目标:公网 HTTPS + 关闭演示通道 + 保留测评注册入口 + CSP。

## 0. 搬运清单:源码包里没有的东西

Release 的源码包是 `git archive` 产物,`.gitignore` 里的内容一律不在包内
(`backend/data/`、`.env.local`、`frontend/dist`、`node_modules`、`releases/`)。
所以「解压完能跑」不等于「解压完功能齐全」:下面这些要**另外搬**,而且**缺了都不报错**。

| 物 | 目标路径 | 体积 | 缺了会怎样 | 怎么搬 |
| --- | --- | --- | --- | --- |
| 习题题库 6,776 题 | `backend/data/exercises/bilingual/all.jsonl` | 20.3 MiB | 有两层静默:①文件不存在时 `exercise_docgen._store()` 退回 `data/exercises/staging/`(同样不在包里)→ 空库;②**即使文件在**,6,776 题也全是 `research` 层,而 `MG_EXERCISE_TIERS` 默认 `safe` → 仍然是 0 题。表现是组卷接口回 **422 `no_evidence`**(不是 500,日志也没有告警),25 项验收不覆盖这条 | `scp` / `rsync -a` 拷文件,**并在 `.env.local` 设 `MG_EXERCISE_TIERS=safe,research`**(见 §1),两条缺一不可 |
| 环境变量与密钥 | `backend/.env.local` | — | 演示通道照旧、邀请码与额度缺失;LLM 无 key 时问答**静默退化**为「知识库直答」——不报错,但答不了知识库以外的问题 | 按 §1 在服务器上**新建**;别整份拷本机的(那份多半是 demo 配置) |
| 前端产物 | `frontend/dist/` | 约 6 MB | 反代没有文件可发,首页 404 | 在服务器上 `npm ci && npm run build`(§2);不要把另一台机器编出来的包拷来混用 |
| 账号库(仅迁移旧环境) | `backend/data/mathguide.db` | 视账号量 | 全新部署**不需要**:首次启动自动建库 | 用 `python tools/db_backup.py` 出一致性快照再搬;**不要 `cp`**,WAL 里的最后一段会丢 |
| 文献与上传件(仅迁移) | `backend/data/research/` | 视上传量 | 检索历史与用户上传的 PDF 全部丢失 | `rsync -a` |
| embedding 缓存(可选) | `backend/knowledge/.embeddings.json` | 视知识量 | 不搬也能用:首次装载自动重建,但要**重新计费** | 只在启用 `MG_EMBED_*` 时有意义;知识库改过则不必搬,反正会重算 |

### 解包:Windows 上别用自带 `tar`

`backend/knowledge/` 里有一个含希腊字母的文件名(`Bound-sets-for-a-class-of-φ-Laplacian-op.md`,U+03C6)。
Windows 自带的 bsdtar 会按本地代码页改写文件名 —— 实测:

```text
$ tar -xzf MathGuide-v1.27.0-source.tar.gz -C tmp
$ python verify_manifest.py tmp/MathGuide-v1.27.0
MISSING  backend/knowledge/Bound-sets-for-a-class-of-??-Laplacian-op.md
checked=632 failures=1
```

内容没问题,只是名字被改写。同一份包改用 Python 的 `tarfile`(或 Linux 的 GNU tar,按 UTF-8 处理):

```bash
python -c "import tarfile,sys; tarfile.open(sys.argv[1]).extractall('.')" MathGuide-v<版本>-source.tar.gz
python verify_manifest.py MathGuide-v<版本>      # 期望: checked=<MANIFEST 条数> failures=0
```

Python 3.14 会给 `DeprecationWarning`(要求显式 `filter=`),加 `filter='data'` 即可,校验结果不变。

### 搬完核对(30 秒)

```bash
cd backend
python -c "print(sum(1 for l in open('data/exercises/bilingual/all.jsonl',encoding='utf-8') if l.strip()))"
# 期望: 6776
ls knowledge/*.md | wc -l
# 期望: 24

# 分层是否生效:计划接口的 available 就是「当前配置下能出多少题」
curl -s -X POST http://127.0.0.1:8000/api/doc/exercise/plan \
     -H "Authorization: Bearer <token>" -H 'Content-Type: application/json' \
     -d '{"count":10}'
# 期望 "available":{"zh":6776,"en":6776,"both":6776};三项都是 0 就是文件没放对、或 MG_EXERCISE_TIERS 没设成 safe,research
```

题库是**热加载**的:`_store()` 按 `(mtime, size)` 判断要不要重读,所以拷进去**不用重启进程**
(改 `MG_EXERCISE_TIERS` 要重启 —— 那是启动时读的环境变量)。

请在「第一个人点习题」之前把这三条跑掉 —— 空库是静默的,等到用户报「没有题目」才查就晚了。

### 两个容易漏的写权限

- systemd 模板里 `ProtectSystem=strict` + `ReadWritePaths=.../backend/data`,**默认只有 `data/` 可写**。
- 启用 `MG_EMBED_*`(向量检索)时,Embedder 要把缓存写到 `backend/knowledge/.embeddings.json`:
  那个目录默认只读,写入失败只打一条 WARN(`缓存写不进去不影响本次检索,但要让人知道`),
  后果是**每次重启都重新向量化、重复计费**。要用 embedding 就在 unit 里加一行
  `ReadWritePaths=/srv/mathguide/backend/knowledge`,要么明确不启用。

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
# 机房/单位 NAT 共用一个出口 IP 时打开双闸:MG_AUTH_RATE_MAX 变成单账号额度,
# MG_AUTH_IP_RATE_MAX 是整间机房每分钟过多少人(按 人数 × 3 估)。
# 比把 MG_AUTH_RATE_MAX 调大更安全(单账号爆破仍被锁住),见 docs/DEPLOY_PLAYBOOK.md §五之三
# MG_AUTH_DUAL_BUCKET=1
# MG_AUTH_IP_RATE_MAX=120
# 管理员白名单,否则 /api/stats 无人可访问,留存清理也不会保护管理员
MG_ADMIN_PHONES=你的手机号
# 可选:自动留存清理(0=关闭)
# MG_ACCOUNT_TTL_DAYS=180
# MG_USAGE_TTL_DAYS=90
# 组卷题库分层:现题库 6,776 题全在 research 层,默认只加载 safe → 不设这项就一题也出不了(§0)
MG_EXERCISE_TIERS=safe,research
# 反向代理时由 Caddy/Nginx 传 X-Forwarded-Proto,后端会按 HTTPS 发 HSTS
# MG_ENABLE_HSTS=1
```

- `MG_DEMO_MODE=0` 后固定验证码、微信/QQ 游客登录、开放注册全部关闭。
- 测评同学用 `MG_INVITE_CODES` 中的邀请码注册;邀请码共享,按批次轮换。
- 后端只监听 `127.0.0.1:8000`,不要直接暴露公网端口。
- 若多人共用实验室出口 IP,优先打开双闸 `MG_AUTH_DUAL_BUCKET=1`(单账号仍是
  `MG_AUTH_RATE_MAX` 次/窗口,整间机房的上限由 `MG_AUTH_IP_RATE_MAX` 决定);
  把 `MG_AUTH_RATE_MAX` 直接调大等于同时削弱单账号的爆破防护,只作一次性应急。

## 2. 前端构建

```bash
cd frontend
npm ci
npm run build
```

产物在 `frontend/dist`。`theme-init.js` 已从内联脚本拆成独立文件,
所以 CSP 不需要放开 `script-src 'unsafe-inline'`。

### 2.1 本地 HTTPS(iPad / 手机调试,可选)

生产用服务器证书;本地调试用 mkcert,代码不变,只是证书来源不同。

```bash
# 1. 电脑装 mkcert 并信任本地 CA
winget install FiloSottile.mkcert      # Windows;macOS 用 brew install mkcert
mkcert -install

# 2. 给局域网 IP 与 localhost 签证书(把 IP 换成电脑当前地址;有 Tailscale 可一并加)
cd .certs
mkcert 172.30.43.234 100.83.78.113 localhost 127.0.0.1 ::1
# 得到 172.30.43.234+4.pem / 172.30.43.234+4-key.pem 这类文件

# 3. 带证书启动前端(host 会自动监听 0.0.0.0)
cd frontend
MG_HTTPS_CERT="D:/Works/code/.certs/172.30.43.234+4.pem" \
MG_HTTPS_KEY="D:/Works/code/.certs/172.30.43.234+4-key.pem" \
npx vite --port 5173
```

iPad 访问 `https://<电脑局域网 IP>:5173`,并安装一次根证书:

1. 把 `mkcert -CAROOT` 下的 `rootCA.pem` 改名 `.crt`,通过 AirDrop/邮件/局域网发到 iPad;
2. 设置 → 已下载描述文件 → 安装;
3. 设置 → 通用 → 关于本机 → 证书信任设置 → 打开该根证书的完全信任。

注意:

- 只在本机开发用;`.certs/` 已加入 `.gitignore`,私钥绝不能入库或上传服务器。
- 局域网 IP 变化后证书失效,需要重新签;建议给电脑固定 DHCP 或改用主机名。
- 从 HTTP 切到 HTTPS 会换 origin,浏览器里的会话与教材缓存不会跟随;要重新登录/上传。
- 生产不读 `MG_HTTPS_CERT/MG_HTTPS_KEY`,由 nginx/Caddy 终止 TLS。

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

### 3.1 证书:Let's Encrypt

```bash
# Debian/Ubuntu
sudo apt install certbot python3-certbot-nginx
# 两个子域写进同一张证书(或改用通配符证书)
sudo certbot --nginx -d learn.example.com -d research.example.com
# 自动续期演练(证书到期前 30 天会由 systemd timer 续期)
sudo certbot renew --dry-run
```

然后把 `deploy/nginx.conf` 里的占位路径改成实际路径(通常是
`/etc/letsencrypt/live/<主域名>/fullchain.pem` 与 `privkey.pem`),
并确认:

- `server_name` 是真实域名,80 端口的 301 覆盖所有子域;
- `client_max_body_size 100m`(论文上传上限;教材单章 20 万字约 600 KB,也在内);
- `/api/` 的 `proxy_set_header X-Forwarded-Proto $scheme;` 不能删,
  Cookie 的 `Secure` 与 HSTS 都靠它;
- 双域部署在 `backend/.env.local` 设 `MG_COOKIE_DOMAIN=.example.com`,
  `MG_ENABLE_HSTS=1`;
- 先在浏览器确认证书链完整,再打开 HSTS;
- Caddy 用户不需要 certbot,Caddyfile 会自动申请和续期。

迁移后第一次访问会换 origin:用户需要重新登录;会话与教材缓存在本机,
不会自动带过去。`/api/account/export` 可导出服务端数据。

## 4. 上线前检查

```bash
# 后端测试与静态检查
cd backend && ../.venv/Scripts/python.exe -m pytest
cd backend && ../.venv/Scripts/ruff.exe check .
# 进程内 rlimit 守卫(秒级;主进程里 setrlimit 会让 uvicorn 整体挂起且无日志)
cd backend && python tools/lint_rlimits.py

# 前端测试、静态检查、构建与产物检查
cd frontend && npm run lint && npm test && npm run build && npm run check:build

# 公网绑定必须被拒绝(MG_DEMO_MODE=1 时)
cd backend && ../.venv/Scripts/python.exe -m uvicorn main:app --host 0.0.0.0 --port 8010
# 预期:RuntimeError,不会启动
```

**服务起来之后**跑一次 25 项验收(部署当天只改 `--base-url`,不靠手敲 curl):

```bash
cd backend
python tools/smoke_deploy.py --base-url http://127.0.0.1:8000 --invite <码>
# 期望结尾:PASS 25 · FAIL 0
```

**只有目标机能回答的四件事**,各有脚本(FAIL 项会直接打印"下一步查什么"):

```bash
cd backend
python tools/proxy_check.py --base-url https://mg.example.com --phone <账号> --password <密码> \
    --webhook <MG_DIAGRAM_ALERT_WEBHOOK>      # 证书/HTTPS/cookie 属性/HSTS/麦克风策略/webhook
python tools/check_llm.py --failover          # 四个角色各打一句;再打坏主用看备胎是否接管
python tools/load_probe.py --long-doc 100     # ≈60 页样张的真实渲染耗时(2.3)
python tools/load_probe.py --export 2 --pid $(pgrep -f 'uvicorn main:app')   # 并发导出 + RSS 峰值
python tools/db_backup.py --drill             # 备份后立刻恢复一份副本,证明这份备份能恢复
pip install locust                            # 可选:要吞吐曲线/QPS 时(不进 requirements)
python -m locust -f tools/locustfile.py --headless -u 50 -r 10 -t 30s \
    --tags static --host http://127.0.0.1:8000  # 静态基线;chat/export 场景与读法见 DEPLOY_PLAYBOOK §五之二
```

两点容易误判:
- **429 有两种**:导出闸门的 `pdf export busy`(容量信号,带 `Retry-After`)与
  **每用户 6 次/分**的接口限流 `rate limited`(说明压测太密,不是机器不行)。
  `load_probe.py` 会把后者单独计数并判失败 —— 加账号(`--phone/--password` 可重复)再跑。
- 这四项**必须在这台机器上跑**:证书链、出口 IP、内核沙箱、内存余量都换不了地方测。

浏览器检查:

- `https://mg.example.com` 证书有效,HSTS 存在
- 注册必须填邀请码;`123456` 验证码登录返回 400
- 账号页可导出数据、可注销
- 浏览器控制台无 CSP violation
- SSE 回答能持续输出,不被代理缓冲
- 登录态:断网/刷新不掉登录;`mg_session` Cookie 的 `Max-Age` 为 30 天,
  而服务端 token 上限 24h(活跃用户由 `/api/auth/session` 自动轮换)

## 5. 进程与日志

- 参考 `deploy/mathguide.service` 用 systemd 托管后端;默认只有 `data/` 可写
  (启用 `MG_EMBED_*` 时 `knowledge/` 也要,否则向量缓存写不进去、每次重启重算,见 §0)。
- **必须单 worker**:限流器(`rate_limit`)、会话缓存(`session_cache`)、聊天检索缓存
  都放在进程内存里。加 `--workers 4` 会让"每账号 6 次/分"变成 24 次/分、
  缓存互相看不见(同一用户切到别的 worker 就像换了台机器)。
  **现在是硬校验**:`MG_DEMO_MODE=0` 时检测到 `--workers N` / `WEB_CONCURRENCY>1`
  直接拒绝启动;演示模式仍只打 WARNING(方便本机反复起停)。
- **真实 IP 由 `MG_TRUSTED_PROXIES` 决定**(写进 `.env.local` 或 unit 的 `Environment=`)。
  后端自己从 `X-Forwarded-For` 取客户端地址(`client_ip.py`,唯一决策点):
  直连对端不在白名单 → XFF **一律忽略**(客户端伪造无效);在 → 从右往左取第一个
  不在白名单里的地址(nginx 追加的那个)。
  - 反代不在 `127.0.0.1`(Docker/另一台机器)时填反代的实际地址,如 `172.17.0.1/32`;
    前面再挂 CDN 时把回源网段一起加上。填错不会报错,而是**全员塌成一个 IP**
    (全站共享 10 次/分登录限流)—— 所以后端在两种情况下**直接拒绝启动**:
    白名单写成 `*`/`0.0.0.0/0`,或 `MG_DEMO_MODE=0` 绑 `127.0.0.1` 但白名单为空。
    运行时若收到 XFF 而白名单没命中,还会打一条 60 秒限频的 ERROR。
  - **启动命令必须加 `--no-proxy-headers`**(uvicorn 的 `--proxy-headers` 默认就开着):
    否则它会在应用之前改写 `scope["client"]`,后端看不到真实对端、也无法校验链路
    (单层反代碰巧对,多挂 CDN 会按节点分桶)。检测到仍开着时后端只打 WARN 并在
    `/api/health` 标记 `via=uvicorn`;`--forwarded-allow-ips=*` 直接拒绝启动。
  - 验收:`MG_DIAG_CLIENT_IP=1` 临时打开后跑 `python tools/proxy_check.py`,
    看「真实 IP 链路」一项(两次不同伪造 XFF 必须得到同一个 `ref`)。
  详见 `docs/DEPLOY_PLAYBOOK.md` §一 第 4 条。
- 参考 `deploy/logrotate.conf` 轮转 `/var/log/mathguide/*.log`(默认保留 14 天)。
- 如果使用 journald,改用 journald 的 `SystemMaxUse` / `MaxRetentionSec`。
- 日志级别用 `MG_LOG_LEVEL`(默认 INFO);每条带 `request_id`,同一次回答的多条
  日志可用它串起来。日志里不含问题正文、回答正文与手机号。

## 6. 备份与模型厂商

- 用 `python tools/db_backup.py` 做**数据库**一致性备份(`.backup` 语义,自动含 WAL;
  产物过 `integrity_check`;默认留最近 7 份),用 `python tools/db_restore.py --from <快照>`
  先演练、再加 `--yes` 真恢复(恢复前自动留 `mg-prerestore-*.db` 安全副本)。
- 再把 `backend/data/`(含 `research/` 上传件)整体同步到加密仓库(restic/borg),定期做恢复演练;
  备份访问权限与生产数据同级。
- 在阿里云百炼 / 智谱控制台确认账号的数据留存与训练开关;
  实验数据不应被厂商用于训练,必要时签署 DPA/数据处理协议。
- 磁盘加密、`data/` 目录权限、密钥管理由部署主机负责;仓库只保证代码侧最小化。

## 7. 数据

- `backend/data/` 只允许后端进程用户读写;备份加密并限制访问。
- `usage.jsonl` / `usage.json` 已不含手机号/昵称;账号注销会级联删除。
- 定期备份 `backend/data/mathguide.db`(连同 `-wal` / `-shm`):优先用
  `python tools/db_backup.py`(一致性快照,`cp` 会丢 WAL 里的最后一段写入);
  裸命令是 `sqlite3 mathguide.db ".backup '/backup/mathguide.db'"`;
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
