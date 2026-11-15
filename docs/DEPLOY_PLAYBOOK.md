# 部署待办与已知风险（部署时让我读这份）

> **怎么调出**：下次你说"按 `docs/DEPLOY_PLAYBOOK.md` 帮我部署"，我就照这份执行；它是本仓库里部署事项的唯一真源。
> 最后更新：2026-11-15 ｜ 对应版本：`v1.26.1`（tag，代码快照 `1176a11`）
> 配套：[deploy/README.md](../deploy/README.md)（操作手册）、[COVERAGE_PLAN.md](COVERAGE_PLAN.md)（质量口径）

## 一、部署前必须做完的三件事

1. **配置**：`cp backend/.env.local.example backend/.env.local`，逐项填。至少确认：
   - `MG_DEMO_MODE`：**公网部署必须设 0**（设 1 且绑定公网地址会直接拒绝启动，这是有意设计）
   - `MG_CORS_ORIGINS`：写具体前端来源，**不要 `*`**（演示模式下 `*` 会拒绝启动）
   - `MG_COOKIE_DOMAIN`：双域部署时设父域（如 `.example.com`），单域留空
   - `MG_INVITE_CODES`：非演示模式不开邀请码等于关闭注册
2. **单 worker**：`uvicorn main:app --host ... --port 8000` **禁止加 `--workers N`**。
   限流、每日额度、会话缓存都按进程内存实现；加 N 会让额度变 N 倍、缓存分裂。
   启动时会打 WARNING 提醒，但不会拦你。
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
```

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
- 备份命令示例：`sqlite3 backend/data/mathguide.db ".backup '/backup/mg-$(date +%F).db'"`。

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
| `MG_PRINT_OPEN` | 允许局域网演示机触发本机打印 | **公网不要开**（需同时 `MG_DEMO_MODE=1` 才生效） |

写操作有来源校验（跨站 POST → 403），登录/注册豁免，无 `Origin` 的脚本客户端放行。

## 五、部署后验收（25 项 HTTP 检查的精简版）

```bash
curl -s http://127.0.0.1:8000/api/health          # {"ok":true,...}
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8000/api/auth/session   # 401(未登录)
# 注册→登录→session→登出后应为 401;跨站 Origin 的 POST 应为 403
cd backend && python tools/check_pdf.py           # RESULT: OK
```

完整 25 项见 `docs/OPTIMIZATION_PLAN.md` §0.1（含每项预期结果）。

## 六、已知限制（部署时别踩，也不必现在修）

| 项 | 现状 |
| --- | --- |
| Linux + chromium 实机验证 | 未做（只有 Windows Edge 157 实测） |
| 自检结论 vs 生产配置 | 自检里临时开 `MG_EDGE_NO_SANDBOX=1` 才通过、生产忘了开 → 线上仍 500。判据见第二节表 |
| 老版本浏览器缺 `--no-pdf-header-footer` | PDF 可能带页眉（难看，不影响内容）；未做兼容 |
| 数组公式→Word 图片 | 走 `math_table_render`（同一条浏览器链路），Linux 上会降级为纯文本 |
| 覆盖率 | 后端 **89.89%**（1506 passed）、前端 **97.7%**（51 文件 1021 条）；逐文件达标 146/146，口径见 `COVERAGE_PLAN.md` §2 |
| 单文件最大 | `ChatWorkspace.vue` 3056 行（已从 3944 降） |

## 七、回滚

- 代码：`git checkout v1.26.1`（当前发布，代码快照 `1176a11`）或上一 tag `v1.26.0`；**无接口路径变更、无数据表结构变更**，
  回滚不需要动数据库。
- 数据：恢复 `mathguide.db` 快照（停服务 → 覆盖三个文件 → 启动）。
- 环境：`MG_EDGE_PATH` / `MG_PDF_TIMEOUT` / `MG_DAILY_LLM_CALLS` 都是可选，删掉即回默认行为。
