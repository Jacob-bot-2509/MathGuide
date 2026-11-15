# 部署待办与已知风险（部署时让我读这份）

> **怎么调出**：下次你说"按 `docs/DEPLOY_PLAYBOOK.md` 帮我部署"，我就照这份执行；它是本仓库里部署事项的唯一真源。
> 最后更新：2026-11-15（§一/§四：`MG_DAILY_LLM_CALLS` 升级为公网必填、**新增第 4 条「反代信任链」**
> 与四条静默失效路径；§五之二：新增压测基线 `tools/locustfile.py`、「测天花板两段式」
> 与真实 IP 实测对照表）
> 2026-11-15 追加：§一.4 从「靠 uvicorn 参数」改成「`MG_TRUSTED_PROXIES` 在代码里判定」
> （`backend/client_ip.py`：通配/空白名单启动即拒绝、塌陷时 ERROR 限频、`proxy_check.py` 可验收）
> 配套：[deploy/README.md](../deploy/README.md)（操作手册）、[COVERAGE_PLAN.md](COVERAGE_PLAN.md)（质量口径）

## 一、部署前必须做完的四件事

1. **配置**：`cp backend/.env.local.example backend/.env.local`，逐项填。至少确认：
   - `MG_DEMO_MODE`：**公网部署必须设 0**（设 1 且绑定公网地址会直接拒绝启动，这是有意设计）
   - `MG_CORS_ORIGINS`：写具体前端来源，**不要 `*`**（演示模式下 `*` 会拒绝启动）
   - `MG_COOKIE_DOMAIN`：双域部署时设父域（如 `.example.com`），单域留空
   - `MG_INVITE_CODES`：非演示模式不开邀请码等于关闭注册
   - `MG_DAILY_LLM_CALLS`：**公网必填**（如 `200`）。默认 `0` = 不限，只在自托管/演示时合理；
     这是唯一的成本总闸——「每用户 6 次/分」是速率不是总额，服务器余量充足时永远不会先报警，
     不设它单账号理论上有 8640 次/天。超限返回 429 `daily quota reached`，计数落在 `usage` 表，
     重启不清零
2. **单 worker**：`uvicorn main:app --host ... --port 8000` **禁止加 `--workers N`**。
   按进程内存实现的是**限流（12 处滑动窗口）、会话缓存、检索缓存、PDF 并发闸门**：加 N 会让
   限流额度变 N 倍、缓存分裂，**闸门变成 N×`MG_PDF_CONCURRENCY` 个浏览器（4C8G 也扛不住）**。
   每日额度是例外——它实时 `COUNT(*)` 查 `usage` 表（`quota.py`），多 worker、重启都不会翻倍。
   **现在这条是硬校验**：`MG_DEMO_MODE=0`（公网模式）下检测到 `--workers N` 或
   `WEB_CONCURRENCY>1` 会**直接拒绝启动**（`RuntimeError: 检测到 N 个 worker…`）；
   演示模式仍只打 WARNING，方便本机反复起停。
3. **跑一次自检**：`cd backend && python tools/check_pdf.py`，必须 `RESULT: OK`（见第二节）。
   若自检提示「沙箱起不来」并让你设 `MG_EDGE_NO_SANDBOX=1`，那这一行**必须同时进生产环境**，
   否则自检通过、线上照样 500。
4. **配好真实 IP 白名单（按 IP 限流的地基）**：`.env.local` 里写
   `MG_TRUSTED_PROXIES=<反代地址>`（`deploy/mathguide.service` 已写 `127.0.0.1`；
   反代在 Docker/另一台机器时改成 `172.17.0.1/32`，前面再挂 CDN 时把回源网段一起写）。
   登录/注册/登出/账号导出/账号注销这 5 个入口的「10 次/分/IP」读的是
   `client_ip.client_key`（`auth._client_key` 委托给它），判定规则只有两条：
   ① 直连对端**不在**白名单 → `X-Forwarded-For` **一律忽略**（客户端伪造无效）；
   ② 在 → 从右往左取第一个不在白名单里的地址（nginx 追加的那个），跳过自己叠的每一层反代。
   所以 `deploy/nginx.conf` 里的
   `proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;` 不能少。
   - **启动即拒绝的三种写法**（是起不来，不是告警）：`MG_TRUSTED_PROXIES=*` /
     `0.0.0.0/0` / `::/0`（那不是配置，是把限流关掉）；白名单里混进非法 IP/CIDR；
     `MG_DEMO_MODE=0` 绑 `127.0.0.1` 但白名单为空（公网部署只能经反代进来，空着必然
     全员一个桶）。演示模式只打 WARNING，方便本机反复起停。
   - **运行时不再静默**：收到 `X-Forwarded-For` 但对端不在白名单时，后端打
     `[client-ip] … 不在 MG_TRUSTED_PROXIES 里` 的 ERROR（每 60 秒最多一条，附修法）。
   - **启动命令必须加 `--no-proxy-headers`**：uvicorn 0.52 的 `--proxy-headers`
     **默认开启**（白名单默认 `127.0.0.1`），只要对端命中它自己的白名单，它就会抢在应用
     之前把 `scope["client"]` 改写成「它算出来的地址」。不关掉的话后端看不到真实对端、
     无法校验链路：① 单层反代能凑巧正确；② 多挂一层 CDN 就变成「按 CDN 节点分桶」；
     ③ 本机/回环反代下客户端伪造的 XFF 会被它直接采信。后端检测到它仍开着时会把来源
     标记为 `uvicorn` 并打 WARN，`proxy_check.py` 也会提示迁移（`via=uvicorn`）。
     `--forwarded-allow-ips=*` 则直接拒绝启动。
   - **代码也管不到的两种拓扑错误**：反代没传 XFF；多挂了一层 CDN 却没把回源段加进
     白名单、也没配 `set_real_ip_from`（Cloudflare 用 `CF-Connecting-IP`）——后者等于
     「按 CDN 节点分桶」，比完全塌陷更隐蔽。这两种现在都会在 60 秒内以 ERROR 出现在
     日志里，验收项也会 FAIL，不必再等「第 11 个人登录失败」才发现。
   - **验收**：`python tools/proxy_check.py --base-url https://<域名>` 的
     「真实 IP 链路」项 PASS（需临时设 `MG_DIAG_CLIENT_IP=1`：两次**不同**的伪造 XFF
     必须得到同一个 `ref`）；人工复核仍是两个不同出口（手机热点 + 宽带）各登录 6 次
     互不挤占（见 §五之二 最后一行）。

## 二、PDF 导出链路（方案 A：服务器装浏览器）

**原理**：结构化文档 → HTML（内嵌 KaTeX，资源在 `backend/static/katex`，`file://` 引用，不依赖外网）
→ headless 浏览器 `--print-to-pdf` → 字节流返回。**没有浏览器时 PDF 分支返回 500 `pdf render failed`**；
Word / Markdown 导出不受影响（带竖线横线的数组公式会降级为纯文本）。

**安装**（Linux）：

```bash
apt install -y chromium fonts-noto-cjk
chromium --version                      # 期望 >= 120;>=132 时 --headless 等价于 --headless=new
cd backend && python tools/check_pdf.py --out /tmp/selfcheck.pdf   # 必须 RESULT: OK
```

**配置**：

```
MG_EDGE_PATH=/usr/bin/chromium     # 优先级最高;配了但文件不存在会直接返回 None(不兜底)
MG_PDF_TIMEOUT=300                 # 可选,默认 120s,下限 10s;低配 VPS 建议上调
# MG_EDGE_NO_SANDBOX=1             # 只在自检说「沙箱起不来」时才加;公网部署保持关闭(默认)
MG_PDF_CONCURRENCY=2               # 可选,同时允许几个浏览器(默认 2,夹到 1–8;1GB 设 1;4C8G 建议 3,先量 RSS)
MG_PDF_QUEUE=8                     # 可选,允许几个请求排队(默认 8,0 = 不排队直接 429)
MG_PDF_QUEUE_WAIT=15               # 可选,单个请求最多排队几秒(默认 15)
```

**并发闸门**：每次导出都会起一个 headless 浏览器（峰值 100–300MB）。闸门在
`doc.py::_html_to_pdf` 这个唯一出口上：同时 `MG_PDF_CONCURRENCY` 个，多出来的排队
`MG_PDF_QUEUE` 个，排队超过 `MG_PDF_QUEUE_WAIT` 秒或队列满 → **429 + `Retry-After: 20`**
（前端提示"稍后重试"），**不会起第 N+1 个浏览器**。所以上线后看到 429 不是故障，
是闸门在保命；频繁出现才说明该调大 `MG_PDF_CONCURRENCY` 或加机器。

**自检五项**（`tools/check_pdf.py`）：浏览器可发现+版本 → 系统中文字体 → 真打印出 PDF（含 `--headless` 回退，
并在 `MG_EDGE_NO_SANDBOX` 的两种取值下各印一次，回答「这台机器要不要放开沙箱」）
→ PDF 内嵌入 CJK 字体（`/Type0` 计数）→ PDF 文本层能读到「极限」。任一失败打印修复命令并 `RESULT: FAIL`。

**沙箱开关的判据**（别猜，看自检结论）：

| 自检结论 | 生产配置 |
| --- | --- |
| 「保留沙箱也能打印」/ 未提沙箱 | **不要**设 `MG_EDGE_NO_SANDBOX`（默认即关闭） |
| 「这台机器只有放开沙箱才能打印」 | 生产必须同样设 `MG_EDGE_NO_SANDBOX=1`，否则线上 500 |
| 两种设置都打不出来 | 不是沙箱问题：查浏览器版本 / `fonts-noto-cjk` / `MG_PDF_TIMEOUT` |

**三个坑（已在代码/文档处理）**

| 坑 | 规避 |
| --- | --- |
| 缺中文字体 → 中文变方块 | `apt install fonts-noto-cjk`；自检第 2、4、5 项 |
| `--headless` 参数新旧不一，写死会**静默不产出 PDF**（返回码 0、无报错、就是没文件） | 代码自动回退：先 `--headless=new`，无产出文件再试 `--headless` |
| 长文档超时 | `MG_PDF_TIMEOUT`（默认 120s） |

**部署后必须做一次眼验**（自检证明不了"公式印对了"）：导出含**数组公式（竖线横线）+ 中文**的文档，
肉眼确认：公式在不在 / 表格线在不在 / 中文有没有变方块。

**本机已验证**：Windows + Edge 157.0.4341.57，1.54s、57–59KB、`%PDF` 头、嵌入 5 个 CJK 字体、
pypdf 可提取「极限」。**Linux chromium 尚未实测**，靠自检兜住。

## 三、数据与备份（曾有一条错误文档，已修正）

- 真实数据在 **`backend/data/mathguide.db`**（SQLite，WAL 模式）。
- 备份要连 **`-wal` / `-shm`** 一起；`users.json` / `tokens.json` 是**旧格式，只作迁移源**，
  照旧文档备份它们等于没备份（此坑已在 `deploy/README.md` 修正）。
- 用户上传的论文/上传文件在 `backend/data/research/`（按 uid 分目录，落盘用内容哈希，无路径穿越）。

**用脚本，不要 `cp`**（`cp` 会丢掉还在 WAL 里的最后一段写入，甚至拷到写了一半的页）：

```bash
cd backend
python tools/db_backup.py                     # → data/backups/mg-YYYYmmdd-HHMMSS.db,默认留 7 份
python tools/db_backup.py --out /backup --keep 14
python tools/db_restore.py --from data/backups/mg-20261115-120000.db          # 演练:只报告,不写
python tools/db_restore.py --from data/backups/mg-20261115-120000.db --yes    # 真恢复
```

- 备份走 `sqlite3.Connection.backup()`（等价 `sqlite3 ... ".backup"`），自动包含 WAL 内容，
  服务在跑也能得到一致快照；产物必须过 `PRAGMA integrity_check` 才算成功。
- 恢复同样走 backup API（不覆盖文件、不手工删 `-wal`），并在写入前自动留一份
  `data/backups/mg-prerestore-*.db` **安全副本**，末尾直接打印"回退命令"。
- 演练命令（等价的裸命令）：`sqlite3 backend/data/mathguide.db ".backup '/backup/mg-$(date +%F).db'"`。

## 四、安全开关速查

| 开关 | 作用 | 公网建议 |
| --- | --- | --- |
| `MG_DEMO_MODE=0` | 关闭演示模式（解除本机绑定/来源限制） | **必须** |
| `MG_CORS_ORIGINS` | 允许的前端来源（逗号分隔） | 写具体域名 |
| `MG_COOKIE_DOMAIN` | 跨子域共享登录态 | 双域时设父域 |
| `MG_INVITE_CODES` | 注册邀请码 | 建议设置 |
| `MG_DAILY_LLM_CALLS` | 每日模型调用额度（超限 429） | **必填**（如 200）；唯一的成本总闸 |
| `MG_EDGE_PATH` | headless 浏览器路径 | PDF 需要时设置 |
| `MG_EDGE_NO_SANDBOX` | 沙箱受限时追加 `--no-sandbox` 兜底档 | **默认关闭**；仅当自检判定「沙箱起不来」才开，且必须与生产一致 |
| `MG_PDF_CONCURRENCY` | 同时允许几个浏览器（默认 2） | 1GB 设 1；**4C8G 建议 3**（先按 2 量出 RSS 再上调）；超出的请求 429 重试 |
| `MG_CHAT_RATE_MAX` | 每用户模型请求速率（默认 6 次/60 秒；0=关闭） | 保持默认；**0 只在压测测容量时用**，别留在生产 |
| `MG_TRUSTED_PROXIES` | 受信反代 IP/CIDR（决定真实客户端 IP） | **公网必填**（如 `127.0.0.1`）；配错=全员一个桶，通配/空着绑回环会拒绝启动 |
| `MG_DIAG_CLIENT_IP` | `/api/health` 返回客户端 IP 摘要（哈希） | 仅部署验收时临时 `1`，平时关闭 |
| `MG_PRINT_OPEN` | 允许局域网演示机触发本机打印 | **公网不要开**（需同时 `MG_DEMO_MODE=1` 才生效） |

写操作有来源校验（跨站 POST → 403），登录/注册豁免，无 `Origin` 的脚本客户端放行。

## 五、部署后验收（25 项，一条命令）

```bash
cd backend
python tools/smoke_deploy.py --base-url http://127.0.0.1:8000          # 演示模式
python tools/smoke_deploy.py --base-url https://math.example.com --invite <MG_INVITE_CODES 里的值>
```

输出是 PASS/FAIL 表，每条带"看到什么 + 下一步查什么"；结尾 `PASS 25 · FAIL 0` 即通过。
- `--skip-pdf`：目标机确实出不了 PDF 时用（同时要记进 §六 已知限制）；
- `--skip-mutating`：只读，不注册账号、不导出；
- 脚本会注册一个临时账号并在末尾注销；`--keep-account` 可保留以便查日志；
- **auth 接口默认 10 次/分/IP**，连着跑两遍第二遍会 429（脚本会提示"等 60 秒"）。

覆盖：健康检查 / 未登录 401 / 安全头 / 畸形 JSON / 注册下发凭据（Cookie+Bearer）/ 弱口令 /
重复手机号 / 跨站 POST 403 / 登出 + 双凭据失效 / 重新登录 / SSE 收尾 `[DONE]` / 论文库 + 存储 /
数据表 / 404 语义（路由·文档·表）/ Markdown·PDF·Word 导出 / 超量 413 / 打印守卫 403 /
统计需管理员 / 注销账号 + 注销后 401。

手敲版（只有这些都不方便时才用）：

```bash
curl -s http://127.0.0.1:8000/api/health          # {"ok":true,...}
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8000/api/auth/session   # 401(未登录)
cd backend && python tools/check_pdf.py           # RESULT: OK
```

更细的逐条预期见 `docs/OPTIMIZATION_PLAN.md` §0.1。

### 五之二、上机专项自检（LLM / 反代 / 负载 / 备份演练）

25 项验收验的是「接口按契约应答」；下面这几项验的是**只有目标机能回答**的问题，
各有独立脚本，FAIL 会直接打印"下一步查什么"：

| 专项（§2） | 命令（`backend/` 下） | 判据 |
| --- | --- | --- |
| LLM 连通 + 异平台容灾（2.5） | `python tools/check_llm.py --failover` | 已配置角色全 `[ OK ]`；`failover` 显示「A 失败 → B 接管」 |
| 反代/证书/Cookie/HSTS（2.7） | `python tools/proxy_check.py --base-url https://<域名> --phone <账号> --password <密码>` | FAIL 0；HTTPS 下 cookie 有 `Secure/HttpOnly/SameSite=lax` |
| 语音入口前置（2.8） | 同上（`Permissions-Policy` 一项） | `microphone=(self)` |
| 告警出口（2.13） | `python tools/proxy_check.py … --webhook <地址>` | 「告警 webhook 可投递 · HTTP 2xx」 |
| 长文档耗时（2.3） | `python tools/load_probe.py --long-doc 100` | 渲染 < `MG_PDF_TIMEOUT` 的 60%（≈60 页样张） |
| 并发导出内存（2.4） | `python tools/load_probe.py --export 2 --pid $(pgrep -f 'uvicorn main:app')` | RSS 峰值 < 可用内存 70% |
| 并发问答首字（2.12） | `python tools/load_probe.py --chat 10 --pid … --phone … --password …` | 无 FAIL；首字 p95 可接受 |
| 备份可恢复（2.10） | `python tools/db_backup.py --drill` | 「[OK] 演练: 已恢复一份副本 · 行数一致」 |
| 真实 IP 链路（§一.4） | 临时设 `MG_DIAG_CLIENT_IP=1` 重启后端,再跑 `python tools/proxy_check.py --base-url https://<域名>`；或 `for i in $(seq 1 11); do curl -s -o /dev/null -w "%{http_code} " -X POST https://<域名>/api/auth/login -H 'Content-Type: application/json' -H "X-Forwarded-For: 10.0.0.$i" --data-binary '{"method":"password","phone":"<账号>","password":"wrong"}'; done; echo` | 「真实 IP 链路」PASS（两次**不同**的伪造 XFF → 同一个 `ref`、`via=forwarded`），且 11 次伪造 XFF 后**必须出现 429**；`via=uvicorn` = 启动命令没加 `--no-proxy-headers`（单层可用、多挂 CDN 会分桶）；`via=peer-untrusted` = 白名单没命中（全员一个桶）；两次 `ref` 不同 = 白名单过宽或写了 `*` |

**429 要看内容分两种**（`load_probe.py` 已经分开计数）：

- `pdf export busy` + `Retry-After`：导出并发闸门，**容量信号**，说明当前并发已经压到上限；
- `rate limited`：**每用户 6 次/分**的接口限流（`chat`/`doc`/`docgen` 共用同一个滑动窗口）。
  它只说明压测太密，**不代表机器不行**；10 并发请准备 ≥2 个账号（`--phone/--password` 可重复）。

> webhook 与证书两项必须在**目标网络里**跑；本机跑出来的结论只代表本机。

**真实 IP 实测对照**（本机 uvicorn 0.52.4，11 次登录、同一台机器同一条链路，2026-11-15 实测）。
这四行是**旧机制**（`--forwarded-allow-ips`）的行为，也正是 v1.27.1 把判定收进
`backend/client_ip.py` 的原因：同一份代码只因为参数写法不同，就在
「正常 / 塌陷 / 绕过」之间静默切换，而日志里看不出来：

| `--forwarded-allow-ips` | 请求里的 `X-Forwarded-For` | 结果 | 说明 |
| --- | --- | --- | --- |
| `127.0.0.1` | 每次不同（= nginx 追加的真实 IP） | `401 ×11` | 正常：一人一个桶，互不挤占 |
| `172.17.0.1`（反代在 Docker） | 每次不同（同上，反代确实追加了） | `401 ×10` + `429` | **塌陷**：白名单对不上，全员退回 `127.0.0.1` |
| `127.0.0.1` | `10.0.0.$i, 203.0.113.9`（客户端伪造 + 真实地址追加） | `401 ×10` + `429` | 伪造无效：只认右起第一个不受信地址 |
| `*` | 每次不同（纯伪造） | `401 ×11` | **绕过**：`*` 时直接采信最左边，10 次/分形同虚设 |

新机制（`MG_TRUSTED_PROXIES`）走同一条「右起第一个非受信地址」的规则，另外三点写死在代码里：
对端不在白名单时 XFF **一律忽略**（第 1、3 行的正确行为成为唯一行为）；
`*`/`0.0.0.0/0` **直接拒绝启动**（第 4 行不可能再出现）；
白名单对不上时打 ERROR 且 `proxy_check.py` FAIL（第 2 行不再静默）。

**压测基线（要曲线，不要 PASS/FAIL）**：`load_probe.py` 回答「过没过判据」，`locustfile.py`
回答「随用户数怎么变」——产出 QPS / 分位延迟 / CSV·HTML 报告。两者口径一致（两类 429 分开计数），
换机器时各跑一遍。locust 是**可选依赖**：`pip install locust` 即可，**不进 `requirements-dev.txt`**
（它会拖进 gevent，各解释器版本的 wheel 覆盖不一致，没必要让 CI 承担）。

| 场景 | 命令（`backend/` 下） | 判据 |
| --- | --- | --- |
| 静态吞吐基线 | `python -m locust -f tools/locustfile.py --headless -u 50 -r 10 -t 30s --tags static --host http://127.0.0.1:8000` | 失败 0；rps / p95 连同机型记进部署记录 |
| 问答并发 | `--tags chat -u 6 -r 6 -t 60s`（先设 `MG_LOCUST_TOKENS`；测容量时后端设 `MG_CHAT_RATE_MAX=0`） | `rate_429 = 0` 才算测到机器 |
| 导出闸门 | `--tags export -u 12 -r 12 -t 60s` | `gate_429` 允许 >0（容量信号）；失败项应为 0 |

**一个虚拟用户必须对一个账号**：`-u` 超过凭据数就会复用账号，先撞「每用户 6 次/分」，
测出来的是限流而不是机器（脚本结束时会把 `rate_429 > 0` 判读成「本轮并发结论无效」）。
凭据优先 `MG_LOCUST_TOKENS`（逗号分隔 token：免登录、不撞认证接口 10 次/分/IP），否则
`MG_LOCUST_ACCOUNTS="手机号:密码,..."`（`test_start` 里统一登录一次）；`chat` / `export`
在完全没有凭据时**直接退出**，避免空转跑出「0 请求 · 0 失败」的假结果。

**测天花板的正确顺序（先把限流让开，再谈并发）**：`_rate_check` 在**贵的活之前**判定
（`chat_stream` 入口、导出入口都是），所以默认 6 次/分时同一账号并发 7 个请求，第 7 个拿到的
429 是 `rate limited`，**根本轮不到导出闸门**。不关它，量到的是限流口径，不是机器上限：

| 阶段 | 后端启动方式 | 看什么 | 这个阶段能下的结论 |
| --- | --- | --- | --- |
| ① 测容量 | `MG_CHAT_RATE_MAX=0`（关闭每用户限流） | rps / p95 / `gate_429` 占比 / RSS | 「这台机器能扛多少」 |
| ② 验保护 | 恢复默认（删掉该变量 = 6 次/60 秒） | 同一账号第 7 个请求必须 429 `rate limited` | 「限流确实咬得住」 |

两个阶段**不能混在一轮里看**：① 的失败项应为 0、`gate_429` 才是容量信号；② 只需要看到那个
`rate limited`。`MG_CHAT_RATE_WINDOW` 只在要改窗口长度时用（默认 60 秒）；坏值（拼错、负数）
一律回退 6，不会把保护悄悄关掉。

**本机对照数（Windows 笔记本 + 真实上游）—— 只作下单量级的参照，不是目标机结论**

| 场景 | 结果 |
| --- | --- |
| 静态 150 用户 / 12s | 1174 请求 · **105.9 rps** · p50 20ms · p95 640ms · 失败 0；服务进程 RSS 峰值 96MB |
| 导出 12 并发（默认 2+8） | 13 次全成功、**0 拒绝**；均值 11.4s、p95 17s |
| 导出 10 并发（`MG_PDF_QUEUE=2`） | 8 成功 + 3 次 `pdf export busy`（记成功、单列一行）——闸门确认在工作 |
| 问答 6 并发 / 3 账号 | 15 成功（p95 790ms）+ 14 次 `rate limited` ← 测法太密，不是机器 |

读法：105.9 rps 是**用户节奏上限**（脚本 `wait_time` 0.5–2s），不是服务端上限——rps 随用户数
近似线性增长（50 人 32.6 → 150 人 105.9），说明单进程还没触底。导出吞吐上限 ≈
`MG_PDF_CONCURRENCY / 单次耗时` ≈ 2 / 11.4s ≈ **10.5 次/分**：100 人同时点导出会有 90 个立刻
429，剩下的按 10.5 次/分排空（≈9 分钟）。这是设计意图（快速失败），不是缺陷；嫌慢只能调大
`MG_PDF_CONCURRENCY`（内存允许时）或加机器。内存那条**本机测不准**（Edge 采样混进了桌面浏览器），
必须在目标机用 `--export 2 --pid` 重测，再据此定 `MG_PDF_CONCURRENCY`。
### 五之三、集中登录 / 考试当天（唯一会让学生「有感受」的限流）

登录/注册/登出/导出/注销共用**按 IP 的 10 次/60 秒**（`MG_AUTH_RATE_MAX`），而聊天问答是
**按账号**的 6 次/60 秒（`MG_CHAT_RATE_MAX`）—— 两者不是一回事。于是有一个和反代配置无关、
只和**组织方式**有关的坑：

| 形态 | 结果 |
| --- | --- |
| 40 人机房共用一个出口 IP，开考时一起点「登录」 | 前 10 个进入，第 11 个起 429（**配置全对也一样**，因为是同一个公网 IP） |
| 同上，但打开了双闸 `MG_AUTH_DUAL_BUCKET=1` | ≈80 次/分 < 120 天花板，**40 人全部通过**；单账号仍锁在 10 次/分 |
| 同上，但进场时陆续登录（每人隔 ~10 秒） | 平均 6 次/分 < 10，不触发 |
| 已登录状态下开考（只提问） | 完全不碰 IP 桶，只受「6 次/分/账号」约束 |

**有开关的做法（机房推荐，2026-11 起）**：打开双闸 `MG_AUTH_DUAL_BUCKET=1`。它把上面那个
「每个 IP 10 次」拆成两个桶：

| 桶 | 环境变量 | 含义 | 默认 |
| --- | --- | --- | --- |
| IP 天花板 | `MG_AUTH_IP_RATE_MAX` | 一个出口 IP 后面整间机房一分钟最多过多少人 | 120 |
| 账号额度 | `MG_AUTH_RATE_MAX` | 同一手机号（登录/注册）或同一 uid（导出/注销）的额度 | 10 |

于是 40 人同时点登录（≈80 次/分）能全部通过，而**单账号爆破仍被锁在 10 次/分**——这比
「把 `MG_AUTH_RATE_MAX` 调到 30~40」安全得多（后者等于把每个人的保护也一起削弱）。默认关是
有意的：它放宽的是「一个 IP 一分钟能过多少人」，不该替所有人默认放宽。打开方式：

```bash
# backend/.env.local
MG_AUTH_DUAL_BUCKET=1
MG_AUTH_IP_RATE_MAX=120   # 按「人数 × 3 / 分钟」估:40 人 → 120;100 人 → 300
# 重启后端后确认日志出现这一行(没有这一行 = 没生效):
#   [auth] 认证限流双闸:IP 120 次/60s + 账号 10 次/60s
```

两个容易踩的点：①`MG_AUTH_IP_RATE_MAX` 写成比 `MG_AUTH_RATE_MAX` 还小属于写反了，启动时会
打 WARNING 并按账号额度纠正（否则双闸会退化成「一个更小的单桶」）；②改完**必须重启**才算数
（限流器在启动时构建），重启会把正在答题的人一起掉线，所以这一步要安排在开考前、不要考中。

**不用改代码的做法（仍然有效，可以和上面叠加）**：让学生**提前打开一次页面**。`/api/auth/session`
不走登录限流（见 `auth.py` 的 `session` 没有 `_auth_rate_check`），会直接恢复登录态；token 是
24 小时有效并在接近过期时自动轮换（`RENEW_AFTER_RATIO`）。也就是说：**考前 24 小时内每人打开
过一次，开考时就不需要登录**，IP 桶在数学上不会被撞到。

**真的撞上了 429 怎么办**：提示是「登录太频繁，请约 1 分钟后再试」，响应带 `Retry-After`。
**不要重启后端** —— 重启只会把已经在答题的人一起掉线，而且不改变限流判定；等这一分钟即可。
确需应急放行，把 `MG_AUTH_RATE_MAX` 临时调到 30~40 并在考后改回（调大就等于削弱暴力破解防护，
所以只作为一次性开关，别长期留着）。



## 六、已知限制（部署时别踩，也不必现在修）

| 项 | 现状 |
| --- | --- |
| Linux + chromium 实机验证 | 未做（只有 Windows Edge 157 实测） |
| 压测基线 | 只有 Windows 本机数（静态 105.9 rps、导出 ≈10.5 次/分），**4C8G 目标机未测**；Linux chromium 的渲染内存也没测（本机用 Edge，采样被桌面浏览器污染）。上机后按 §五之二 重跑才算数 |
| 自检结论 vs 生产配置 | 自检里临时开 `MG_EDGE_NO_SANDBOX=1` 才通过、生产忘了开 → 线上仍 500。判据见第二节表 |
| 老版本浏览器缺 `--no-pdf-header-footer` | PDF 可能带页眉（难看，不影响内容）；未做兼容 |
| 数组公式→Word 图片 | 走 `math_table_render`（同一条浏览器链路），Linux 上会降级为纯文本 |
| 导出 429 | 并发闸门生效时返回 429 + `Retry-After: 20`，属预期行为；频繁出现才需要调 `MG_PDF_CONCURRENCY` |
| 接口限流 6 次/分/用户 | `chat`/`doc`/`docgen` 共用同一个滑动窗口。验收/压测时十并发只用 1 个账号会先撞它（429 `rate limited`），不代表机器扛不住；`load_probe.py` 会分开计数并要求加账号 |
| 登录限流按 IP（10 次/60 秒） | 一个出口 IP 后面所有账号共享这个桶（学校机房/单位 NAT 就是这样）。与反代配置无关，纯组织问题：让学生进场时打开一次页面恢复登录态即可不碰它，或打开 `MG_AUTH_DUAL_BUCKET=1` 把「整间机房天花板」和「单账号额度」分开，见 §五之三 |
| macOS | 已加 `macos-latest` CI 线守路径/字体差异，但**没有**在真 Mac 上做过人工验收 |
| 3.14 的 analysis 依赖 | scipy/pandas/statsmodels 无 cp314 wheel → 该解释器下 `analysis_regression` 整模块 skip；CI 有非阻塞探测，出 wheel 会提示摘豁免 |
| 覆盖率 | 后端 **90.06%**（1537 passed）、前端 **97.7%**（51 文件 1021 条）；逐文件达标 146/146，口径见 `COVERAGE_PLAN.md` §2 |
| 单文件最大 | `ChatWorkspace.vue` 3056 行（已从 3944 降） |
| 题库搬上去却出不了题 | 6,776 题全部标在 `research` 层，而 `MG_EXERCISE_TIERS` 默认 `safe` → 计划接口 `available` 三项全 0、组卷回 422 `no_evidence`，**无报错无日志**。投放后按 `deploy/README.md` §0 核对（需 `MG_EXERCISE_TIERS=safe,research`） |

## 七、回滚

- 代码：`git checkout v1.27.0`（当前发布）或上一 tag `v1.26.1`；**无接口路径变更、无数据表结构变更**，
  回滚不需要动数据库。
- 数据：`cd backend && python tools/db_restore.py --from data/backups/mg-<时间戳>.db --yes`
  （脚本会先给当前库留 `mg-prerestore-*.db` 安全副本，并打印"万一要退回去"的命令）；
  不用脚本时的等价做法是停服务 → 覆盖 `mathguide.db` **连 `-wal` / `-shm`** → 启动。
- 环境：除 `MG_DAILY_LLM_CALLS`（公网必填）外，`MG_EDGE_PATH` / `MG_PDF_TIMEOUT` /
  `MG_PDF_CONCURRENCY` 都是可选，删掉即回默认行为。
