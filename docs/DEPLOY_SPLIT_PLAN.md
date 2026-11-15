# 部署前能做完的 vs 上服务器才能做的

> **怎么调出**：下次说"按 `docs/DEPLOY_SPLIT_PLAN.md` 继续"。
> 配套：`docs/DEPLOY_PLAYBOOK.md`（部署唯一真源）、`deploy/README.md`（操作手册）。
> 最后更新：2026-11-15（§1 全部 13 项收口）｜ 对应版本：`v1.26.1` 之后的收口提交

## 0. 一条判据

| 问题 | 结论 |
| --- | --- |
| 这件事需要**真实运行环境**才能得出确定结论吗？（真浏览器 / 真外网 / 真数据 / 真时间流逝 / 真内核策略） | 只能在服务器上做 |
| 能在本机构造**确定性断言**吗？（单元测试、打桩、静态检查、本机构建、脚本演练） | 现在就该做完，不要拖进部署窗口 |

理由很实际：部署窗口只有一次机会，任何能在 CI 里亮红灯的东西都不该在那天才第一次亮。
反过来说，凡是自检/脚本能在本机证明的，都不该占用手忙脚乱的现场时间。

## 1. 现在就能做（不需要服务器）

| # | 任务 | 现状 | 为什么本机能做 | 完成判据 |
| --- | --- | --- | --- | --- |
| 1.1 | 运维文档与配置收口（`MG_EDGE_NO_SANDBOX` 进 `.env.local.example` / playbook / deploy README；数字与回滚指针校正） | **已做**（2026-11-15） | 纯文档 | 三处文档口径一致，`docs/DEPLOY_PLAYBOOK.md` §二有判据表 |
| 1.2 | `check_pdf.py` 双档沙箱探测 | **已做**（2026-11-15） | 打桩/真实 Edge 都能跑 | 自检输出直接给出"要不要开沙箱"，且提示自检与生产必须一致 |
| 1.3 | **PDF 导出并发闸门** | **已做**（2026-11-15） | 用打桩替换浏览器调用即可测并发与拒绝路径 | `doc.py` 的 `_html_to_pdf` 单点加闸：同时 2 个（`MG_PDF_CONCURRENCY`）、排队 8（`MG_PDF_QUEUE`）、最多等 15s（`MG_PDF_QUEUE_WAIT`），超出直接 **429 + `Retry-After: 20`**；`docgen` 同步翻 429；8 条用例含"被拒时根本没起浏览器" |
| 1.4 | **"进程内不得改 rlimit" 静态守卫** | **已做**（2026-11-15） | 纯 AST 扫描，秒级 | `backend/tools/lint_rlimits.py`：`analysis_client.py` 白名单，其余 `setrlimit`/`prlimit`（含 `from resource import ... as`）立即非零退出；进 CI；6 条用例含"守卫自己会报错" |
| 1.5 | 单 worker 强校验 | **已做**（2026-11-15） | 启动逻辑可单测 | `config.assert_single_worker()`：公网模式（`MG_DEMO_MODE=0`）下 `--workers N`/`WEB_CONCURRENCY>1` **拒绝启动**（RuntimeError）；演示模式仍只告警，本机反复起停不受影响。已用真实 `import main` 验证三种组合 |
| 1.6 | **25 项验收脚本化** `backend/tools/smoke_deploy.py` | **已做**（2026-11-15） | 本机 `127.0.0.1` 全跑一遍 | 25 项 PASS/FAIL 表 + 每项修复提示；`--base-url` 换服务器、`--invite` 走非演示、`--skip-pdf` / `--skip-mutating` / `--keep-account`；本机实测 **PASS 25 · FAIL 0**；临时账号自动注销 |
| 1.7 | 备份/恢复脚本 `tools/db_backup.py` / `db_restore.py` | **已做**（2026-11-15） | 本机真实 db 演练一次即可 | 走 `sqlite3.backup()`（等价 `.backup`，自动含 WAL），产物 `integrity_check` + 行数核对，`--keep` 轮转；恢复前自动留 `mg-prerestore-*.db` 安全副本并打印回退命令。本机真库已跑过备份→恢复；7 条用例含"数据还在 WAL 里也能备份" |
| 1.8 | macOS CI 线 | **已做**（2026-11-15） | 写 yml 即可，跑在 GitHub 上 | `ci.yml` 新增 `macos-latest` / py3.13 一行（门槛同 85），路径大小写、字体、`fork` 语义差异由这条线守 |
| 1.9 | 3.14 线 analysis 依赖 | **已做（豁免 + 监控）**（2026-11-15） | CI 层决定 | 维持 `skip_analysis`（scipy/pandas/statsmodels 无 cp314 wheel），但加了一步**非阻塞探测**：一旦上游出了 wheel，CI 日志会打 `::warning::` 提醒摘掉豁免；豁免理由写进 `COVERAGE_PLAN.md` §2 |
| 1.10 | 前端构建产物检查（KaTeX 随包、体积） | **已做**（2026-11-15） | 本机 `npm run build` + 断言 | `frontend/scripts/check-build.mjs`（`npm run check:build`，已进 CI）：断言 `.katex` 规则 + ≥8 个 KaTeX 字体真的在 dist、`robots.txt`/`theme-init.js` 随包、`backend/static/katex` 仍在、单块 gzip ≤800KB / 合计 ≤1.6MB / dist ≤10MB。实测 8/8 通过（最大块 619KB、合计 1297KB、6.31MB） |
| 1.11 | 数据投放脚本幂等性 | **已做**（2026-11-15） | 临时 JSONL 跑两遍比对 | `merge_bank.merge()` 抽成可测函数：重复执行 `added=0`、不产生重复行、`input` 文件缺失时自动新建；`fetch_knowledge.write_md` 已存在则跳过且不覆盖。5 条用例 |
| 1.12 | systemd / logrotate / nginx 模板 | **已做（此前已有，本轮补 `robots.txt`）** | 模板现在写，部署当天只改域名 | `deploy/` 下四份模板齐备且被 `deploy/README.md` 逐条引用；新增 `frontend/public/robots.txt`（并让 1.10 的构建检查确保它进 dist） |
| 1.13 | 安全头 / robots 默认值核查 | **已做**（2026-11-15） | 代码 + 单测 | 后端 `security_headers.py` 覆盖 nosniff / frame / referrer / permissions，HSTS 仅在 HTTPS 或 `MG_ENABLE_HSTS=1` 时发（4 条用例）；反向代理模板里 CSP + HSTS + `Permissions-Policy` 齐全；`robots.txt` 默认 `Disallow: /api/` 并挡掉 `/workspace`、`/research` |

**结论：§1 全部 13 项已收口**（1.1 / 1.2 见上文，1.3–1.13 见各行"现状"列）。
每项都留下了可重复跑的验证入口：`pytest` 用例、`tools/lint_rlimits.py`、`tools/smoke_deploy.py`、
`tools/db_backup.py`、`npm run check:build`。部署当天**不需要**在没有验证手段的情况下临场判断。

**优先级说明**：P1 = 部署前必须做完（否则上线当天会产生"说不清原因"的故障或无法复现）；
P2 = 可以带着未做完上线，但要写进已知限制。

## 2. 必须上服务器才能做

判断依据同上：这些任务的结论**取决于目标机器/目标网络/真实时间**，本机跑一百遍也不算数。

| # | 任务 | 为什么本地做不了 | 上机判据 | 失败时怎么办 |
| --- | --- | --- | --- | --- |
| 2.1 | chromium 五项自检 + 数组公式眼验 | 发行版 chromium 版本、字体包装法、apparmor 策略都与本机不同 | `python tools/check_pdf.py` → `RESULT: OK`；再肉眼确认一份含数组公式（竖线横线）+ 中文的 PDF | 按自检打印的修复命令逐项装包；仍不行则回退"PDF 分支返回 500，其它格式可用" |
| 2.2 | 沙箱受限判定（要不要 `MG_EDGE_NO_SANDBOX=1`） | 取决于内核 `kernel.apparmor_restrict_unprivileged_userns` 与运行用户身份 | 自检结论：三档（不放开就行 / 必须放开 / 都打不出） | 必须放开 → 写进生产 env 并记入风险台账；都打不出 → 查浏览器版本与字体 |
| 2.3 | 长文档超时基线 | 需要真实 60+ 页文档 + 目标机 CPU | 最大文档导出耗时 < `MG_PDF_TIMEOUT` 的 60%（默认 120s） | 上调 `MG_PDF_TIMEOUT`（低配 VPS 建议 300） |
| 2.4 | 并发导出的内存/CPU 上限 | 本机余量与目标机无关，测不出 OOM 阈值 | 2 个并发导出时内存峰值 < 机器可用内存的 70% | 定 1.3 的闸门 N（建议 2）与排队上限（建议 8） |
| 2.5 | LLM 平台真实连通/限流/额度 | 需要真实 key、真实出口 IP、真实配额 | 主力 + 备胎各成功一次；故意打满看 429 是否被正确透出 | 配 `MG_DAILY_LLM_CALLS`；检查备胎角色是否真的接管 |
| 2.6 | `research_lit.py` 真实外网链路 | 测试只有 fake client；真实站点有 403/429/证书/重定向/大文件 | 真实 DOI 能下载到 PDF/全文并落到 `backend/data/research/` | 记成已知限制；礼貌池邮箱 `MG_LITERATURE_MAILTO` 配好 |
| 2.7 | 反代与登录态（`MG_COOKIE_DOMAIN`、HSTS、`X-Forwarded-Proto`、CORS 真域名） | 需要真实域名、证书、反代头 | 双域/单域各登录一次；跨站 POST → 403；HTTPS 下 cookie 带 `Secure` | 单域先留空；HSTS 只在确认 HTTPS 正常后再开 |
| 2.8 | 语音输入 | 需要真麦克风 + 浏览器权限；**非 localhost 的 http 下 `getUserMedia` 直接不可用** | 真机点一次录音能出文字（因此必须 HTTPS） | 无 HTTPS 就先不开放入口 |
| 2.9 | 会话轮换 / 跨天 token / 时区 | 需要真实时间流逝或至少服务器真实时区 | 隔天回来仍是登录态；token 轮换不踢人 | 记成已知限制，先按 7 天 TTL 观察 |
| 2.10 | 备份/恢复真实演练 + 磁盘配额 | 真实 db 体积、WAL 行为、剩余磁盘 | 备份→改数据→恢复→数据回滚到备份点；`MG_RESEARCH_MAX_TOTAL_MB` 生效 | 备份脚本（1.7）必须先在本地演练过 |
| 2.11 | 25 项验收真实执行 | 需要真实依赖（邀请码、额度、跨站来源） | 脚本（1.6）全 PASS；跨站 POST 403、邀请码注册、429 各验一次 | 单项失败按 playbook §五 定位 |
| 2.12 | 单 worker 并发/首字延迟/内存基线 | 目标机核数、内存、网络决定 | 10 并发问答首字延迟可接受、内存无持续增长 | 加 N 之前先解决：额度与缓存都是进程内实现（见 playbook §一.2） |
| 2.13 | 告警 webhook + 日志落盘/切割 | 需要真实 webhook 与真实日志量 | `MG_DIAGRAM_ALERT_WEBHOOK` 能收到一条测试消息；logrotate 生效 | 未配则关闭；日志级别用 `MG_LOG_LEVEL` |
| 2.14 | systemd 守护/开机自启/崩溃重启 | 服务器特有能力 | `kill -9` 后自动拉起；重启机器后服务可用 | 用模板（1.12） |
| 2.15 | 教材/题库导入真实耗时 | 真实数据量，本机没有投放数据 | 导入耗时可接受、可中断可重入 | 依赖 1.11 的幂等性 |

## 3. 部署窗口内的顺序（约 60 分钟）

| 时间 | 动作 | 判据 | 对应本文件 |
| --- | --- | --- | --- |
| 0–10m | `apt install -y chromium fonts-noto-cjk`；`chromium --version` | ≥ 120 | 2.1 |
| 10–20m | 填 `backend/.env.local`（demo=0、CORS 真域名、邀请码、额度） | 与 playbook §一/§四 逐项对齐 | 2.7 |
| 20–30m | `python tools/check_pdf.py`；按结论决定 `MG_EDGE_NO_SANDBOX` | `RESULT: OK` + 沙箱结论落地到 env | 2.1 / 2.2 |
| 30–40m | `python tools/smoke_deploy.py --base-url http://127.0.0.1:8000 --invite <码>` | **25 项全 PASS**（SKIP 要能解释） | 2.11 |
| 40–50m | 真实链路：一次问答、一次导出、一次文献检索 | 三件事都成 | 2.5 / 2.6 / 2.3 |
| 50–60m | `python tools/db_backup.py` → `python tools/db_restore.py --from <备份>` → `--yes` 演练；记下回滚命令 | 备份过 `integrity_check`；恢复后行数一致；安全副本存在 | 2.10 |

> 窗口里**不写代码、不改仓库**。任何"顺手修一下"都会让线上与 tag 对不上，回滚时无从下手。

## 4. 服务器上允许改什么

| 允许 | 不允许 |
| --- | --- |
| `backend/.env.local`（开关与密钥） | 直接改 `*.py` / `*.vue` / `*.yml` |
| 系统包（chromium、fonts、sqlite3） | `git pull` 到未发布的提交 |
| systemd / nginx / logrotate 配置 | 手工 `sqlite3` 改表结构 |
| 日志级别、超时、额度这类环境变量 | 用 `--workers N` 绕过单 worker 约束 |

发现代码问题 → 回本地改 → 走 CI → 发 patch 版本（v1.26.2），**不在服务器上热改**。

## 5. 需要拍板的四件事（本轮已按括号内方案默认执行）

| 决策 | 选项 | 现状 |
| --- | --- | --- |
| PDF 沙箱 | A. 若自检要求就开 `MG_EDGE_NO_SANDBOX=1`；B. 给 PDF 单跑一个低权限用户/带 seccomp 的容器 | 代码侧已就绪：自检直接给结论、生产必须与自检一致；**开不开由 2.1/2.2 的实机结论定** |
| PDF 并发闸门 | N=2、排队 8（建议）；或 N=1 直接串行 | **已实现且可调**：`MG_PDF_CONCURRENCY` / `MG_PDF_QUEUE` / `MG_PDF_QUEUE_WAIT`；阈值仍按 2.4 的实测确认（1GB 机器建议 1） |
| macOS 门禁 | 加 / 不加 | **已加**（`macos-latest` py3.13，门槛同 85）。若长期飘红再评估是否转 `experimental` |
| 3.14 的 analysis 依赖 | 装（覆盖率盲区消失、CI 变慢）/ 记豁免 | **记豁免 + 监控**：`COVERAGE_PLAN.md` §2 写明原因，CI 里加了非阻塞探测，出 wheel 会自动提示摘豁免 |

## 6. 与其它文档的分工

- `docs/DEPLOY_PLAYBOOK.md`：**怎么做**（命令、开关、回滚）；
- 本文件：**什么时候做、在哪做**（本地 vs 服务器）；
- `docs/HANDOFF.md`：新会话从哪接手；
- `docs/COVERAGE_PLAN.md`：质量门槛，与部署无关但会拦住"为上线临时改代码"。


