# MathGuide v1.26.0 — 会话续期、PDF 导出服务器化与覆盖率收口

发布日期：2026-11-14
发布类型：行为改进 + 工程质量版本（会话 / 安全 / 部署 / 覆盖率）
代码快照：`5cbb996`（源码包由该提交生成；标签 `v1.26.0` 指向包含发布说明与附件的发布提交）
基线版本：`v1.25.0`（发布提交 `66ead6e`）

本版本在 v1.25.0 基础上解决四类问题：**会话每天掉登录**、**成本与安全缺少护栏**、**PDF 导出只能在 Windows 本机用**、**单测覆盖不足与单文件体量过大**。
接口路径与数据库表结构都没有变化；用户可感知的行为变化只有三处（会话轮换、每日额度、来源校验），且都有环境变量可关闭或调参。

## 一、会话与认证

- 会话语义定案（滑动续期）：Cookie 保留 30 天，token 仍是 24 小时硬上限；`GET /api/auth/session` 在 token 剩余寿命低于 20% 时签发新 token（响应体带 `token`，Cookie 同步换新）。
- 轮换节流：同一账号 5 分钟内不重复轮换，避免客户端不写回 token 时把 token 表刷爆；轮换**不吊销**旧 token，多标签页不会互相踢下线。
- 旧 Bearer 回退：请求头里的 Bearer 失效时自动回退到 Cookie 凭据，修掉「另一个标签页换了 token 导致本页 401」。
- 登出同时吊销 Cookie 与 Bearer 两个凭据（此前只清其中一个）。
- 前端修复：会话恢复不再把本地 token 覆盖成 `undefined` —— 此前每次启动后所有请求都会悄悄退化成纯 Cookie 鉴权。

## 二、安全与成本护栏

- 每日模型调用额度：`MG_DAILY_LLM_CALLS`，按当天用量记录计数（多 worker / 重启 / 手工改库都不会算错），超限返回 429 并给出明确提示；覆盖聊天、直观解释、语音转写、文档生成与修订、习题规划、整页与公式识别共 8 个入口。
- 记账修正：空 prompt 的罐头欢迎语不再记一次用量（它根本不调用模型），既不污染成本报表也不占当天额度。
- 写操作来源校验：POST / PUT / PATCH / DELETE 按 `Origin`（无则 `Referer`）与请求 Host 同源比对，跨站 403；登录/注册豁免；无 Origin 的脚本客户端放行（不误伤自动化）。
- 打印收紧：`MG_PRINT_OPEN=1` 不再能绕过本机校验，必须同时处于演示模式才生效；部署到远端时 `/api/research/tables/{id}/print` 一律 403。
- 多 worker 启动告警：检测到 `WEB_CONCURRENCY>1` 时明确提示「限流与会话缓存按进程内存实现，多 worker 会让额度变成 N 倍且缓存分裂」，并把「必须单 worker」写进 `deploy/mathguide.service` 与部署清单。
- 依赖与供应链：`watchfiles` 移出运行依赖、`sympy` 锁版本、`ruff` 入 dev；`.env.local.example` 补齐 16 个原先未文档化的变量。

## 三、PDF 导出（Linux 服务器）

此前导出 PDF 实际只在 Windows 本机可用：浏览器候选路径只列了 Edge 的两个安装位置。服务器上没有 Edge 时，`_html_to_pdf` 会**完全静默地返回 None**（不抛异常），只有用户点「导出」才会发现。

- 浏览器查找改为三级：`MG_EDGE_PATH`（部署时显式指定）→ 系统已知路径（Windows Edge；Linux 的 `/usr/bin/chromium`、`chromium-browser`、`google-chrome`、`microsoft-edge`、`/snap/bin/chromium`）→ `PATH` 里的常见命令名。
- 显式配了 `MG_EDGE_PATH` 但文件不存在时**直接失败、不做兜底**：否则配错会悄悄换用别的浏览器，产出的 PDF 与预期不一致却查不出原因。
- headless 参数自动回退：先 `--headless=new`，失败再试 `--headless`（老版本浏览器不认新参数），装的是旧版也不会整条链路失效。
- PDF 超时可配：新增 `MG_PDF_TIMEOUT`，默认值从 60 秒提到 **120 秒**（低配 VPS 上 60 秒会误杀长文档），下限 10 秒。
- 新增部署自检 `backend/tools/check_pdf.py`：一条命令回答「这台机器能不能出 PDF」，按顺序查四项 —— 浏览器能否发现（含版本号）、系统有无中文字体、能否真的打印出 PDF（含参数回退）、PDF 里是否嵌入了 CJK 字体；任一项失败给可执行的修复建议，最后输出 ASCII 结论行 `RESULT: OK` / `RESULT: FAIL` 便于脚本判断，并把 stdout 切到 UTF-8（Windows 控制台默认 GBK，中文会显示成 `???`）。
- `deploy/README.md` 补 Linux 上线清单：`apt install -y chromium fonts-noto-cjk`（**不装中文字体，PDF 里中文变方块**，代码兜不住）、`chromium --version` 期望 ≥ 120、导出前的自检命令。
- 新增 `backend/tests/test_doc_export_edge.py`：覆盖浏览器缺失、headless 参数回退、超时、临时目录清理。
- 已知限制：**Linux + chromium 尚未实机验证**（本机只有 Windows Edge 157 实测通过）。首次部署请先跑 `python tools/check_pdf.py`，不要等用户点导出才发现。


## 四、覆盖率收口与测试卫生

本轮的目标是「逐文件达标」，不是把总数刷高。

- 后端：覆盖率 **78% → 90%**（`1504 passed`）；CI 门槛 `--cov-fail-under` 由 75 提到 **85**，只用于防倒退。
- 逐文件台账 **146/146 达标**（口径见 `docs/COVERAGE_PLAN.md` §2：该文件覆盖率 ≥ 所属类别的线，**且**主要公开函数至少被调用一次 —— 90% 行覆盖但某个导出函数从未被调用，仍算未达标）。
- 前端：vitest 覆盖率 **12.34% → 97.7%**（**51 文件 1021 条**）；CI 新增覆盖率门禁：全局 statements 90 / branches 85 / functions 90 / lines 95，并按类别分组硬卡（utils 80 / stores 70 / services 60）。全局值留余量避免无害重构就红，分组线卡单文件掉队。
- 不给 `.vue` 模板设覆盖率：模板断言需要截图对比，本项目没有该手段；组件逻辑已在 composable 层测过。
- 不为覆盖率改产品代码：难测若是设计耦合所致，记进 `docs/OPTIMIZATION_PLAN.md` 当结构债，而不是把逻辑搬进测试。
- 修掉「测试污染真实数据」：`backend/tests/conftest.py` 把科研落盘目录统一重定向到 `tmp_path`。此前跑一次测试会往真实 `backend/data/research` 写 10 个目录。
- 新增 `backend/tests/test_patch_targets.py`：静态守卫扫描 `setattr(chat, "X")` 与 `patch` 目标，符号搬迁后「测试仍然绿、但什么都没测到」会在 CI 立刻红 —— 这正是 M3 拆分踩过的坑。
- 覆盖率排查时发现并删除 `chat.py` 一段不可达的「数据表直答」前置分支（行为不变）。

## 五、结构治理

| 文件 | 改前 | 改后 | 拆出 |
| --- | --- | --- | --- |
| `backend/chat.py` | 1875 | 1509 | `chat_sse` / `chat_prompts` / `chat_routing`（`chat.*` 兼容导出，外部零改动） |
| `backend/research_corpus.py` | 2568 | 2202 | `research_formats`（字节 → 页 → 章节 → 切片，纯函数无状态） |
| `frontend/src/utils/i18n.ts` | 2027 | 127 | `utils/i18n/{account,chat,common,learn,research}.ts`（955 条词条无损） |
| `frontend/src/components/chat/ChatWorkspace.vue` | 3944 | 3056 | `useResearchSplit` / `useDiagramFocus` / `useChatStream` / `useChatAttachments` / `useSpeechInput` + `utils/splitPane` |

- 拆分前先补测试：ChatWorkspace 的三批拆分都以「先加断言再动手」为前提，拆完**没有改动任何一条既有测试**。
- 兼容性：`chat.py` 与 `research_corpus.py` 都保留原导出名，外部调用与测试无需修改；两处「搬运内部符号」的坑（`monkeypatch` 指向旧模块会静默失效、测试 patch 目标需同步）已写进 `docs/OPTIMIZATION_PLAN.md` 第 7 节，并由本版新增的静态守卫兜住。
- 尚未拆的部分与原因：`send()` 主链路与会话迁移（`deleteHistory` / `newConversation` / `jumpTo`）不成块，继续拆的收益低于回归风险；再往下应拆模板，需要截图对比类视觉回归手段，本项目暂不具备。

## 六、文档与仓库卫生

- 三处会误导人的文档错误修正：`deploy/README.md` 的备份步骤从已废弃的 `users.json`/`tokens.json` 改为 `mathguide.db`（含 `-wal`/`-shm`，照旧做等于没备份）；`backend/README.md` 的「认证走本地 JSON 存储」改为 SQLite；`auth.py` 的接口方法标注 `POST` → `GET`。
- 后端 README 补齐 31 条原先未文档化的接口（描述取自函数 docstring，未臆造）。
- 新增 `docs/DEPLOY_PLAYBOOK.md`（部署待办、上线清单、已知限制、回滚步骤）与 `docs/HANDOFF.md`（新会话交接：状态、下一步、硬规则、环境坑、常用命令），并挂进 README 导航。
- 新增 `docs/COVERAGE_PLAN.md`（按类别定线 + 逐文件台账 + 决策记录）与 `docs/COVERAGE_REMAINING.md`（剩余工作草稿，本版收口后**已关闭**）。
- 删除零引用的 `GeoGebraBlock.vue`。
- `docs/OPTIMIZATION_PLAN.md`：本轮完整方案、度量口径、决策记录（D1–D7）、M5 准入门槛与真实环境验证记录。
- `EVAL_REPORT.md` 加版本时效说明（0.667 是 v1.24.0 前的数字，v1.25.0 已是 0.708 / 0.792）；`RESEARCH_SOURCE_PLAN.md` 标注已被 V2 取代，不再按它排期。
- `.gitignore` 补覆盖率产物（`.coverage*` / `htmlcov/` / `coverage-*/`）与本地临时日志；`releases/` 停止新增（附件改挂 GitHub Release）。

## 七、验证

- 后端：`1504 passed, 1 skipped`，覆盖率 **90%**。该数字是本轮收口时 `pytest --cov` 的实跑结果；其后两条提交（conftest 隔离、patch 目标守卫）只新增测试，未重跑全量。
- 前端：`eslint` 0 违规；`vue-tsc --noEmit` 与 `vite build` 通过；20 套脚本自测 + vitest **51 文件 1021 条**全过，覆盖率 97.7%。
- 真实环境验证（本机起后端 + Vite dev，打真实 HTTP，25 项检查全部通过，明细见 `docs/OPTIMIZATION_PLAN.md`）：
  - 注册 / 登录 / 会话不轮换 / 连调节流 / 登出后 Cookie 与旧 Bearer 双双 401 / 重新登录；
  - 跨站 `Origin` 的 POST → 403；同源 → 200；无 `Origin` 的脚本客户端 → 200；
  - `/api/chat/stream` 以 `data: [DONE]` 收尾；
  - 伪装公网 Host 打打印接口 → 403「打印仅支持本机访问」；
  - 附件上传 200 + `docId`、同内容重复上传标 `duplicate`、正文过短 400；
  - 额度=1 且当天已有 1 条用量 → 真实提问 429，而罐头欢迎语连发 3 次仍 200；
  - `WEB_CONCURRENCY=4` 启动 → 单 worker 告警确实打印，uvicorn 确实起 4 进程；
  - 前端首页、vite 代理 `/api/health`、`ChatWorkspace.vue` 经 vite 编译（产物含新 composable 引用）。
- PDF 导出：Windows + Edge 157 实测出 PDF（含中文与数组公式）通过，`check_pdf.py` 四项全绿。
- 本环境无法验证、由单测兜底的四项：会话**轮换**分支（需 token 年龄 >19.2h）、语音输入全链路（需真麦克风 + Chrome）、LLM 真实回答（无 API key，额度改用「造当天用量行」触发）、触摸手势（无真触屏）。

## 八、升级与部署注意

- 前端版本号升至 `1.26.0`（`frontend/package.json`），「关于」页版本条目同步更新。
- **无接口路径变更、无数据库表结构变更**：`backend/data/mathguide.db` 直接沿用，不需要迁移脚本。
- **升级前请确认备份的是 `mathguide.db`（连同 `-wal` / `-shm`）**，不是旧的 `users.json` / `tokens.json` —— 旧备份步骤是错的，本版已修正 `deploy/README.md`。
- 新增可选环境变量：`MG_EDGE_PATH`（服务器上 chromium 路径）、`MG_PDF_TIMEOUT`（导出超时）、`MG_DAILY_LLM_CALLS`（每日模型调用额度，留空=不限）、`MG_COOKIE_DOMAIN`、`MG_LOG_LEVEL`、`MG_RESEARCH_MAX_UPLOAD_MB` / `_MAX_DOCS` / `_MAX_TOTAL_MB` 等，全部见 `backend/.env.local.example`。
- **Linux 服务器上线前必须先装浏览器与中文字体**：`apt install -y chromium fonts-noto-cjk`，然后 `cd backend && python tools/check_pdf.py` 看到 `RESULT: OK` 再对外开放导出。
- **必须单 worker 部署**：限流、每日额度与会话缓存都按进程内存实现；加 `--workers N` 会让额度变成 N 倍。启动时会告警，`deploy/mathguide.service` 已写明。
- 打印如在局域网演示机上使用，需同时满足 `MG_PRINT_OPEN=1` **且** `MG_DEMO_MODE=1`；公网部署一律 403。
- 会话行为变化：用户不再每天被登出；已登录用户升级后会拿到新 token，旧 token 仍可用至自身过期（不会被强制踢下线）。
- 发布附件：完整源码快照、相对 `v1.25.0` 的补丁、改动前代码包、`MANIFEST.sha256` 与校验脚本。

### 发布物存放（自 v1.26.0 生效）

从 v1.26.0 开始，源码包 / 补丁 / 改动前代码包**不再提交进仓库**，改为在 GitHub Release 页面作为附件上传（`releases/` 已加入 `.gitignore`，历史目录保留但不更新）。

原因：每版附件约 2 MB 且二进制不可压缩，17 个版本已让 `.git` 达到 257 MB，克隆与 CI checkout 越来越慢。仓库内只保留 `MANIFEST.sha256` 与发布说明，用于校验下载到的附件。

### 已知限制（本版不修）

- **PDF 导出没有并发闸门**：单次导出实测约 1 秒、峰值私有内存约 460 MB（Windows + Edge 157）；10 个导出同时发起时峰值 4.5 GB、进程数 217，需 4C8G。若确有批量导出场景，请在网关层限并发（建议 ≤ 3），并给 headless 浏览器配独立 `--user-data-dir`（实测可把每份内存降到约 240 MB、耗时也更短）。
- **手机端窄屏样式未处理**：`100vh` 在 iOS 上会被工具栏挤压、输入框贴底被挡；`ChatWorkspace.vue` 等视图没有窄屏媒体查询，两个侧栏同时展开会在 375px 宽度下溢出。与 3D 图解的移动端手势仲裁一起，等真实用户反馈与真机在手再动。
- **Linux + chromium 未实机验证**（见 §三）。

## 九、合并记录

- `66ead6e` v1.25.0 发布提交（基线）
- `ebb027b` chore: 工程债清理 M0/M1/M2/M7（会话语义、契约护栏、lint + logging、CI、仓库卫生）
- `9248780` feat(auth): 会话改为滑动续期（D1 方案 B）
- `ab8c42a` test+fix: RAG / 流式测试护栏、安全加固（M6）、`chat.py` 拆分（M3-1）
- `67b731b` feat: 每日额度护栏（M6-4）、覆盖率门槛（M4-3）、vitest 落地（M4-4）
- `3f30a47` refactor+chore: 拆出 `research_formats`（M3-3）+ 仓库卫生
- `a25acd9` refactor: i18n 词条按领域拆分（M3-4），校验迁到 vitest
- `399a9fb` refactor(chat): `ChatWorkspace` 抽出分栏与图解放大 composable（M3-2 第一批）
- `ab29fa9` test+refactor(chat): 组件测试能力落地，抽出 `useChatStream`（M3-2 第二批）
- `7dd6020` refactor(chat): 抽出 `useChatAttachments`（M3-2 第三批）
- `7239490` refactor(chat): 抽出 `useSpeechInput`，M3-2 三块拆完
- `5368ad3` docs: 记录真实环境验证结果（起服务打真实 HTTP）
- `1ca15e3` docs: M5 冻结，等数据审核合格后启动（D7）
- `359107a` release: v1.26.0 版本号与关于页条目
- `c51f206` docs: 覆盖率方案 —— 按类别定线、逐文件台账、分批执行
- `755f05f` test(coverage): B1 零覆盖与装配层 —— 5 个文件全部达标
- `521926f` test(coverage): B2 三个零网络模块达到 100%（rerank / synthesize / diagram_alerts）
- `bec921d` test(coverage): 近线补齐 5/8 —— math_table_render / judges / build / exercise_docgen / docgen 全部达标
- `1bce998` test(coverage): linear_algebra 83.9→85.5%（B 类最后一个近线文件）
- `9f3a41b` test(coverage): B5 起步 —— 4 个前端小 utils 达到 100%
- `6916e04` test(coverage): rag/route 60→100%，research_urls 75→93%（B3 起步）
- `1d6e28a` docs: 覆盖率剩余工作草稿（54 个文件，分 7 组）
- `3ae5e0d` feat(doc)+test: 导出 PDF 支持 Linux 服务器（A 方案），`doc.py` 72.6→80%
- `80f886d` feat(doc): headless 参数新旧自动回退 + PDF 超时可配；补 deploy 上线清单
- `64f1f8c` docs(deploy): 明确「装新版浏览器」，并解释 `--headless` 回退不是为用旧版
- `4b15747` feat(tools): 新增导出 PDF 的部署自检 `tools/check_pdf.py`；本机真机验证通过
- `a5484ab` feat(tools): 自检增加「PDF 里的中文内容」检查 + UTF-8 输出 + ASCII 结论行
- `3dd3401` docs: 新增部署待办与已知风险（DEPLOY_PLAYBOOK），并挂进 README
- `2a079fc` test(coverage): G1 起步 —— rag/__init__ 降级与索引重建分支（7 条）
- `6941d95` docs: 新增新会话交接单 HANDOFF（状态 / 下一步 / 硬规则 / 环境坑 / 命令）
- `c23bf13` test(coverage): rag/__init__ 74.3→89% 达标（G1 前半完成）；补跑全量 1182 passed
- `33c9ea0` test(coverage): rag/llm 57.3→92% 达标 —— G1 两个文件收口
- `da58d89` docs: COVERAGE_REMAINING 追加五大组执行工单（可机械照做）
- `bf26d41` docs: 刷新后端台账（实测 95/146）+ 新增五大组交接表
- `8dc6e1b` test(coverage): G2/G3/G5/G6/G7 全量收口 —— 146/146 文件达标
- `0a2331c` refactor(chat): 删除不可达的数据表直答前置分支
- `10b9df4` docs(deploy): 修正部署手册里的覆盖率现状（80%/14.6% → 90%/97.7%）
- `c30bd18` ci(frontend): 加覆盖率门禁（全局 + 按类别分组阈值）
- `45b397f` docs(readme): 覆盖率草稿标记已关闭（54 个文件 → 146/146 达标）
- `6188534` test(conftest): 科研落盘目录统一重定向 `tmp_path`，修测试污染真实 `data/`
- `856d182` test(chat): 加静态守卫，防止 `setattr(chat, X)` 在符号搬迁后静默失效
- `5cbb996` docs(about): v1.26.0 条目补「PDF 导出服务器化」与覆盖率终值（**代码快照**）
- 发布提交：v1.26.0 发布说明、`MANIFEST.sha256` 与 GitHub Release 附件（源码包 / 补丁 / 改动前代码）

历史发布说明：v1.25.0 及更早见 `docs/release-notes-v1.25.0.md` 与 `releases/`（历史目录）。


