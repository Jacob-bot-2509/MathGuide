# 部署待办与已知风险（部署时让我读这份）

> **怎么调出**：下次你说"按 `docs/DEPLOY_PLAYBOOK.md` 帮我部署"，我就照这份执行；它是本仓库里部署事项的唯一真源。
> 最后更新：2026-11-15（§1 收口：并发闸门 / 单 worker 硬校验 / 25 项验收脚本 / 备份恢复脚本）
> 配套：[deploy/README.md](../deploy/README.md)（操作手册）、[COVERAGE_PLAN.md](COVERAGE_PLAN.md)（质量口径）

## 一、部署前必须做完的三件事

1. **配置**：`cp backend/.env.local.example backend/.env.local`，逐项填。至少确认：
   - `MG_DEMO_MODE`：**公网部署必须设 0**（设 1 且绑定公网地址会直接拒绝启动，这是有意设计）
   - `MG_CORS_ORIGINS`：写具体前端来源，**不要 `*`**（演示模式下 `*` 会拒绝启动）
   - `MG_COOKIE_DOMAIN`：双域部署时设父域（如 `.example.com`），单域留空
   - `MG_INVITE_CODES`：非演示模式不开邀请码等于关闭注册
2. **单 worker**：`uvicorn main:app --host ... --port 8000` **禁止加 `--workers N`**。
   限流、每日额度、会话缓存都按进程内存实现；加 N 会让额度变 N 倍、缓存分裂。
   **现在这条是硬校验**：`MG_DEMO_MODE=0`（公网模式）下检测到 `--workers N` 或
   `WEB_CONCURRENCY>1` 会**直接拒绝启动**（`RuntimeError: 检测到 N 个 worker…`）；
   演示模式仍只打 WARNING，方便本机反复起停。
3. **跑一次自检**：`cd backend && python tools/check_pdf.py`，必须 `RESULT: OK`（见第二节）。
   若自检提示「沙箱起不来」并让你设 `MG_EDGE_NO_SANDBOX=1`，那这一行**必须同时进生产环境**，
   否则自检通过、线上照样 500。

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
MG_PDF_CONCURRENCY=2               # 可选,同时允许几个浏览器(默认 2,夹到 1–8;1GB 机器设 1)
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
| `MG_DAILY_LLM_CALLS` | 每日模型调用额度（超限 429） | 设置,防成本失控 |
| `MG_EDGE_PATH` | headless 浏览器路径 | PDF 需要时设置 |
| `MG_EDGE_NO_SANDBOX` | 沙箱受限时追加 `--no-sandbox` 兜底档 | **默认关闭**；仅当自检判定「沙箱起不来」才开，且必须与生产一致 |
| `MG_PDF_CONCURRENCY` | 同时允许几个浏览器（默认 2） | 1GB 机器设 1；超出的请求 429 重试 |
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

## 六、已知限制（部署时别踩，也不必现在修）

| 项 | 现状 |
| --- | --- |
| Linux + chromium 实机验证 | 未做（只有 Windows Edge 157 实测） |
| 自检结论 vs 生产配置 | 自检里临时开 `MG_EDGE_NO_SANDBOX=1` 才通过、生产忘了开 → 线上仍 500。判据见第二节表 |
| 老版本浏览器缺 `--no-pdf-header-footer` | PDF 可能带页眉（难看，不影响内容）；未做兼容 |
| 数组公式→Word 图片 | 走 `math_table_render`（同一条浏览器链路），Linux 上会降级为纯文本 |
| 导出 429 | 并发闸门生效时返回 429 + `Retry-After: 20`，属预期行为；频繁出现才需要调 `MG_PDF_CONCURRENCY` |
| macOS | 已加 `macos-latest` CI 线守路径/字体差异，但**没有**在真 Mac 上做过人工验收 |
| 3.14 的 analysis 依赖 | scipy/pandas/statsmodels 无 cp314 wheel → 该解释器下 `analysis_regression` 整模块 skip；CI 有非阻塞探测，出 wheel 会提示摘豁免 |
| 覆盖率 | 后端 **90.06%**（1537 passed）、前端 **97.7%**（51 文件 1021 条）；逐文件达标 146/146，口径见 `COVERAGE_PLAN.md` §2 |
| 单文件最大 | `ChatWorkspace.vue` 3056 行（已从 3944 降） |

## 七、回滚

- 代码：`git checkout v1.26.1`（当前发布，代码快照 `1176a11`）或上一 tag `v1.26.0`；**无接口路径变更、无数据表结构变更**，
  回滚不需要动数据库。
- 数据：`cd backend && python tools/db_restore.py --from data/backups/mg-<时间戳>.db --yes`
  （脚本会先给当前库留 `mg-prerestore-*.db` 安全副本，并打印"万一要退回去"的命令）；
  不用脚本时的等价做法是停服务 → 覆盖 `mathguide.db` **连 `-wal` / `-shm`** → 启动。
- 环境：`MG_EDGE_PATH` / `MG_PDF_TIMEOUT` / `MG_DAILY_LLM_CALLS` / `MG_PDF_CONCURRENCY` 都是可选，删掉即回默认行为。
