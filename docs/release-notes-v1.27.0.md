# MathGuide v1.27.0 — 部署验收脚本化、PDF 并发闸门与单进程约束

发布日期：2026-11-15
发布类型：功能版本（新增部署执行器；两处服务端行为变更：PDF 导出并发闸门、公网模式拒绝多 worker）
代码快照：`7137ff0`（源码包由该提交生成；标签 `v1.27.0` 指向包含发布说明与附件的发布提交）
基线版本：`v1.26.1`（发布提交 `a6576dc`）

v1.26.1 发出去之后，main 上又合了 17 个提交。主线只有一句话：**上线当天不要再靠临场判断**。

- 以前 §2 里 7 项"上服务器才能确认"的事，只能照着文档手敲 curl，然后凭经验看输出 —— 现在每条都是脚本，跑完给 PASS / FAIL / SKIP。
- 以前 PDF 导出不设闸门，人多的时候是"起第 N 个浏览器，直到机器不行" —— 现在超出并发直接回 429 并带 `Retry-After`。
- 以前多 worker 只打一行告警，限流额度跟着翻倍还没人注意 —— 现在公网模式直接拒绝启动。
- CI 加了 macOS 线，并新增静态守卫：进程内不得修改自身资源限制（v1.26.1 那条 Linux 无声挂起正是这类问题）。

接口路径、数据表结构、前端路由均无变化；新增两个环境变量 `MG_PDF_CONCURRENCY`（默认 2）、以及 `MG_DEMO_MODE` 之外没有任何必填项。

## 一、部署验收：7 项"只能上机确认"变成 5 个脚本

| 脚本 | 覆盖 `DEPLOY_SPLIT_PLAN` §2 | 判据 |
| --- | --- | --- |
| `backend/tools/smoke_deploy.py` | 2.1 / 2.2 / 2.6 / 2.9 / 2.11 等 25 项 | 健康检查、会话匿名、安全头、畸形 JSON、注册/登录、Cookie 与 Bearer、弱口令、重复手机号、跨站 POST、登出与登出后凭证、重新登录、SSE、检索接口、404 语义、Markdown/PDF/DOCX 三种导出、超长内容 400、打印守卫、`/api/stats` 需管理员、删号与删号后 Cookie |
| `backend/tools/check_llm.py` | 2.5 | 四类角色各真打一句（报模型/主机/首字/字数）；`--failover` 临时把主用 key 换成无效值，走**真实** `stream_chat(fallback=True)`，最后应答的模型与主机必须与第一次不同 —— **同平台重试不算接管** |
| `backend/tools/load_probe.py` | 2.3 / 2.4 / 2.12 | `--long-doc N` 渲染页数与耗时对比 `MG_PDF_TIMEOUT` 的 60%；`--export N` 并发导出并采样服务进程 RSS **峰值**；`--chat N` 取首字延迟 p50/p95；`--phone/--password` 可重复，按请求轮询 token |
| `backend/tools/proxy_check.py` | 2.7 / 2.8 / 2.13 | 证书链与剩余天数（验证模式，不用 `-k`）、HSTS 与 `max-age`、`X-Forwarded-Proto` 是否被采纳、会话 Cookie 的 `Secure/HttpOnly/SameSite/Domain`、`Permissions-Policy microphone=(self)`、前端 CSP、`--webhook` 真投一条与线上同形的告警载荷 |
| `backend/tools/db_backup.py` / `db_restore.py` | 2.10 | 备份后 `--drill` 用 `db_restore` 把快照**真的恢复**到临时库，比对 `integrity_check` 与逐表行数，完成后删临时库；恢复前自动给当前库留 `mg-prerestore-*.db` 安全副本 |

设计上刻意不做的事：

- **不注册账号**。`smoke_deploy` 会用 `--phone` 给的一次性号码注册（测的就是注册链路），但那号码由你指定；`check_llm` / `load_probe` / `proxy_check` 只用已有账号或 `--token`，不往线上库塞数据。
- **读不到就说 SKIP，不给假 PASS**。例如 `load_probe` 拿不到服务进程 pid 时，内存结论是 `SKIP` 而不是"内存 0MB，很健康"。
- **连不上只报一条**。`proxy_check` 先探 `/api/health`，不通就一条 FAIL 收场，不会刷一屏"安全头缺失"误导人。

## 二、两类 429 必须分开看（本版最值钱的发现）

`load_probe` 在压测时踩到：同样是 429，含义完全相反。

| 429 内容 | 来源 | 含义 | 脚本结论 |
| --- | --- | --- | --- |
| `pdf export busy, retry later` + `Retry-After` | PDF 并发闸门 | **容量信号**：说明闸门正常工作，排队即可 | 不计失败，只记录 |
| `rate limited` | 每账号 6 次/分的滑动窗口限流 | **测量无效**：这次压得比限流还密，测到的是限流器不是机器 | 判 FAIL，并提示"加账号重跑" |

关键细节：`doc` / `docgen` 与 `chat` **共用同一个每账号 6 次/分窗口**，所以 2.12 的十并发只用一个账号时，测的其实是限流器。脚本因此支持多账号轮询，文档也同步写清"十并发需 ≥2 个账号"。


## 三、PDF 导出：并发闸门，满了回 429 而不是起第 N 个浏览器

以前 `MG_PDF_TIMEOUT` 只管"单个导出最多等多久"，不管**同时有几个**。人多的时候就是不断地起 chromium，直到内存/句柄见底，然后所有人一起超时。

- 新增 `MG_PDF_CONCURRENCY`（默认 2，夹到 1–8）：同时允许启动的浏览器数。
- 超出后进**有限**队列；队列也满则**立刻**回 `429` + `Retry-After`，body 为 `{"detail": "pdf export busy, retry later"}` —— 不无限排队，因为排队只会把用户的等待时间换成"最后仍然失败"。
- 这个 429 是**容量信号**，不是错误：部署验收脚本据此区分"闸门在正常工作"与"被限流打歪了测量"（见 §二）。
- `check_pdf.py` 自检也同步改了：它会直接判断这台机器**要不要**放开沙箱，而不是让人读日志猜（`RESULT: OK` / 需要 `MG_EDGE_NO_SANDBOX=1` 时明确说出来）。

## 四、公网模式：多 worker 直接拒绝启动

限流额度、会话缓存（登出/吊销）、聊天检索缓存都是**进程内存**实现。多 worker 下"每账号 6 次/分"实际是 6×N 次，登出只在其中一个进程生效，缓存各存一份互不可见 —— 这类问题上线后极难查，因为"有时候有效、有时候无效"。

- 新增 `config.detect_workers()`（解析 `--workers` / `--workers=N` / `WEB_CONCURRENCY`）与 `assert_single_worker()`。
- **公网模式**：检测到 >1 个 worker 直接抛错退出，并在错误信息里给出替代方案（加机器、前置队列，不要加 worker）。
- **演示模式**（`MG_DEMO_MODE=1`）：只打 warning，方便本机反复起停。

## 五、CI：加 macOS 线，并守住"不得在进程内改 rlimit"

- 矩阵新增 `macos-latest`：上一版踩过的坑（`RLIMIT_AS` 打到测试进程自己身上）在 Linux 与 macOS 上表现不同，多一条线多一层交叉验证。
- 新增静态守卫 `backend/tools/lint_rlimits.py`：**进程内不得调用 `setrlimit`**（只允许在 `preexec_fn` 的 fork 子进程里），直接扫源码给出结论；已接入 CI。
- Python 3.14 线会探测 analysis 三件套是否可安装，不可安装就不装并跳过相关模块（该线不设覆盖率门槛，口径不可比）。
- 前端加入产物检查（`npm run check:build`），构建产物异常不再等到部署才发现。
- 顺带补了两条**幂等性契约**测试：题库合并与教材入库重复执行不得产生重复行 —— 这两处在部署时会被重跑。

## 六、升级注意

- **无接口路径、数据库表结构、前端路由变更**。前端版本号 `1.27.0`，「关于」页新增 v1.27.0 条目。
- 新增 `MG_PDF_CONCURRENCY`（默认 `2`，允许 1–8）：公网小机器建议保持默认；给到 4 以上前先确认内存（每个浏览器约 200–400MB）。
- **多 worker 部署会启动失败**（公网模式）。若历史上用过 `--workers N` / `WEB_CONCURRENCY`，升级时要去掉；并发不够请加机器或前置队列。
- 其余环境变量与 v1.26.1 一致（`MG_DEMO_MODE` / `MG_EDGE_PATH` / `MG_EDGE_NO_SANDBOX` / `MG_PDF_TIMEOUT` / `MG_DAILY_LLM_CALLS` / `MG_PRINT_OPEN` 等）。
- 部署流程仍按 `docs/DEPLOY_SPLIT_PLAN.md`：部署前用 §1 的 13 项自检，上机后按 §2 的"项 → 命令"表逐条跑，数字与 SKIP 项抄进部署记录。

## 七、发布物

附件在 GitHub Release 页（`v1.27.0`），仓库内只保留发布说明与 `releases/v1.27.0/MANIFEST.sha256`：

| 文件 | 说明 |
| --- | --- |
| `MathGuide-v1.27.0-source.tar.gz` | **完整源码快照**，`git archive` 自 `7137ff0` 生成（633 个文件，2,597,105 字节） |
| `v1.27.0.patch` | 相对 `v1.26.1`（`a6576dc`）的二进制补丁（228,091 字节） |
| `MathGuide-v1.27.0-before-code.tar.gz` | 基线里被改动文件的原版（18 个文件，138,729 字节） |
| `MANIFEST.sha256` | 源码快照内逐文件 SHA-256（633 条） |
| `SHA256SUMS` | 本版三份产物的 SHA-256 |
| `README.md` | 附件说明与校验步骤 |
| `verify_manifest.py` | 跨平台清单校验脚本 |

`SHA256SUMS` 内容：

```
4088d265f57c9789a049ce9a02c35cf9e5b9753c543d112cd5e93ed158b02b5b  MathGuide-v1.27.0-source.tar.gz
c4f133981eb24f0a7b09e7ce29a9a97c1bc2a20b865174989cd7c54a0c7e03cd  MathGuide-v1.27.0-before-code.tar.gz
0b25370aa2f25f72e22a4796049c69189f407e092f21f36e01d2eeea8782d878  v1.27.0.patch
```

## 八、合并记录

- `a6576dc` v1.26.1 发布提交（基线）
- `a451235` docs: 版本指针更新到 v1.26.1
- `76634fc` fix(tools): check_pdf 自检直接判定要不要放开沙箱
- `fe5f4f5` docs: v1.26.1 文档收口 + 新增「部署前 / 上机后」拆分方案
- `8247072` docs: 修正 DEPLOY_SPLIT_PLAN 里的行内代码反引号
- `303aeeb` feat(doc): PDF 导出并发闸门，满了回 429 而不是起第 N 个浏览器
- `18117d9` feat(config): 公网模式下多 worker 直接拒绝启动
- `5432ad1` feat(tools): 新增「进程内不得改 rlimit」静态守卫
- `53ee0c8` feat(tools): 25 项部署验收脚本化（smoke_deploy.py）
- `7ab0e35` feat(tools): 数据库备份/恢复脚本（.backup 语义，自带安全副本）
- `c842b84` test(tools): 补题合并与教材入库的幂等性契约
- `c892a5e` ci: macOS 线 + rlimit 守卫 + 3.14 analysis 探测 + 前端产物检查
- `bc56126` docs: DEPLOY_SPLIT_PLAN §1 十三项全部收口
- `da39e88` docs: HANDOFF 记下 §1 收口与 CI 矩阵现状
- `88c176c` feat(tools): §2 上机项的执行器（check_llm / load_probe / proxy_check）
- `af7b7a2` feat(tools): db_backup --drill + 部署文档同步（窗口全程有命令）
- `fcc5e8f` fix(tools): 连接层异常也要落成一条结论，别在主线程抛栈
- `5b92b98` docs: 基线同步 1577 passed（工具用例 40 条，load_probe 14）
- `7137ff0` release: v1.27.0 版本号与关于页条目（**代码快照**，源码包由该提交生成）
- 发布提交：v1.27.0 发布说明、`releases/v1.27.0/MANIFEST.sha256` 与 GitHub Release 附件

历史发布说明：v1.26.1 见 `docs/release-notes-v1.26.1.md`，更早见 `releases/`（历史目录）。

## 九、验证记录

CI（run 43711604627，覆盖 `7137ff0` 的全部改动）：

| 线 | 结果 |
| --- | --- |
| backend py3.13 ubuntu | **1577 passed**，覆盖率 90.06%（门槛 85%），72.9s |
| backend py3.13 windows | **1577 passed**，覆盖率 90.06%，95.6s |
| backend py3.13 macos | **1572 passed / 5 skipped**，44.9s（5 条依赖真实浏览器渲染，macOS runner 无可用 chromium） |
| backend py3.14 ubuntu | **1552 passed / 2 skipped**，60.0s（无 analysis 依赖，1 个模块整体跳过） |
| frontend node 22 | **51 文件 / 1021 条**通过，覆盖率门禁通过，11.9s |

五条线全部通过（`frontend` 另跑 `check:build`，`backend` 三条 3.13 线另跑 `lint_rlimits` 静态守卫）。

附件自检（本机构建后立即执行）：

- `SHA256SUMS`：三份产物哈希与 `releases/v1.27.0/SHA256SUMS` 逐条一致；
- 用 Python `tarfile` 解包源码包后 `verify_manifest.py` → `checked=633 failures=0`；
- 源码包内不含 `releases/` 与 `NEWRELEASE.md`（`.gitattributes` 的 `export-ignore` 生效）。


## 十、已知限制（本版不修）

- `load_probe` 的内存读数依赖能拿到服务进程 pid（Linux `/proc`、macOS `ps`）；拿不到时给 `SKIP`，不给假数字。
- 十并发（2.12）仍需 ≥2 个账号：`doc` / `docgen` 与 `chat` 共用每账号 6 次/分的窗口，这是产品既有约束，本版只是把测量方法与它对齐。
- `proxy_check` 的 TLS 与前端检查必须在**真的 HTTPS + 真域名**上才有意义；HTTP 直连时它们正确 SKIP，不是"通过"。
- macOS 线只跑 3.13；3.14 仍只有 ubuntu 一条（无 analysis 依赖）。
- Linux + chromium 的 PDF 渲染依旧以 `check_pdf.py` 的实机结论为准，本版不保证任何发行版都能出 PDF。

