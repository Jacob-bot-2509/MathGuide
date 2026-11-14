# MathGuide v1.26.0 — 会话续期、成本护栏与结构治理

发布日期：2026-11-14
发布类型：行为改进 + 工程质量版本（会话 / 安全 / 结构）
代码快照：`1ca15e3`（源码包由该提交生成；标签 `v1.26.0` 指向包含发布说明与附件的发布提交）
基线版本：`v1.25.0`

本版本在 v1.25.0 基础上解决三类问题：**会话每天掉登录**、**成本与安全缺少护栏**、**单文件体量过大**。
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

## 三、工程质量

- 日志：新增 `backend/log.py`（分级 + `request_id` ContextVar + 纯 ASGI 中间件），服务代码 85 处 `print` 全部归零；`backend/tools/` 的 CLI 输出保留（其 stdout 就是接口）。
- Lint 基线：后端 ruff（`E4/E7/E9/F/I`）0 违规；前端 eslint 9 flat + prettier（`npm run lint` / `npm run format`）。
- 覆盖率门槛：后端 76.6%，CI `--cov-fail-under=75` 防倒退。
- 契约测试：路由 ↔ README 双向一致、auth 文档方法 ↔ 实际注册方式、KaTeX 前后端版本一致、i18n 中英词条一致（含未定义 key 检查）。
- CI：新增 ruff / eslint 步骤，后端矩阵 ubuntu 3.13 + ubuntu 3.14 + windows 3.13，前端 Node 固定 22，并发取消。
- 新增测试：RAG 检索 golden（固定语料 + 排序/门限/重建稳定性）、聊天流式 e2e（真 store 真检索，不 mock 业务路由）、每日额度、来源校验、打印守卫、会话轮换与过期。
- 前端测试能力：vitest 接入 `@vitejs/plugin-vue` + `@vue/test-utils` + happy-dom，按文件切 DOM 环境；新增组件级挂载测试（用假 SSE 响应，无需起后端）与图解放大手势测试。

## 四、结构治理

| 文件 | 改前 | 改后 | 拆出 |
| --- | --- | --- | --- |
| `backend/chat.py` | 1875 | 1509 | `chat_sse` / `chat_prompts` / `chat_routing`（`chat.*` 兼容导出，外部零改动） |
| `backend/research_corpus.py` | 2568 | 2202 | `research_formats`（字节 → 页 → 章节 → 切片，纯函数无状态） |
| `frontend/src/utils/i18n.ts` | 2027 | 127 | `utils/i18n/{account,chat,common,learn,research}.ts`（955 条词条无损） |
| `frontend/src/components/chat/ChatWorkspace.vue` | 3944 | 3056 | `useResearchSplit` / `useDiagramFocus` / `useChatStream` / `useChatAttachments` / `useSpeechInput` + `utils/splitPane` |

- 拆分前先补测试：ChatWorkspace 的三批拆分都以「先加断言再动手」为前提，拆完**没有改动任何一条既有测试**。
- 兼容性：`chat.py` 与 `research_corpus.py` 都保留原导出名，外部调用与测试无需修改；两处「搬运内部符号」的坑（`monkeypatch` 指向旧模块会静默失效、测试 patch 目标需同步）已写进 `docs/OPTIMIZATION_PLAN.md` 第 7 节。
- 尚未拆的部分与原因：`send()` 主链路与会话迁移（`deleteHistory` / `newConversation` / `jumpTo`）不成块，继续拆的收益低于回归风险；再往下应拆模板，需要截图对比类视觉回归手段，本项目暂不具备。

## 五、文档与仓库卫生

- 三处会误导人的文档错误修正：`deploy/README.md` 的备份步骤从已废弃的 `users.json`/`tokens.json` 改为 `mathguide.db`（含 `-wal`/`-shm`，照旧做等于没备份）；`backend/README.md` 的「认证走本地 JSON 存储」改为 SQLite；`auth.py` 的接口方法标注 `POST` → `GET`。
- 后端 README 补齐 31 条原先未文档化的接口（描述取自函数 docstring，未臆造）。
- 删除零引用的 `GeoGebraBlock.vue`。
- `docs/OPTIMIZATION_PLAN.md`：本轮完整方案、度量口径、决策记录（D1–D7）、M5 准入门槛与真实环境验证记录。
- `EVAL_REPORT.md` 加版本时效说明（0.667 是 v1.24.0 前的数字，v1.25.0 已是 0.708 / 0.792）；`RESEARCH_SOURCE_PLAN.md` 标注已被 V2 取代，不再按它排期。
- `.gitignore` 补覆盖率产物与本地临时日志；`releases/` 停止新增（附件改挂 GitHub Release）。

## 六、验证

- 后端：`995 passed, 1 skipped`（基线 944），覆盖率 76.6%。
- 前端：`eslint` 0 违规；`vue-tsc --noEmit` 与 `vite build` 通过；20 套脚本自测 + vitest **9 文件 80 条**断言全过。
- 真实环境验证（本机起后端 + Vite dev，打真实 HTTP，25 项检查全部通过）：
  - 注册 / 登录 / 会话不轮换 / 连调节流 / 登出后 Cookie 与旧 Bearer 双双 401 / 重新登录；
  - 跨站 Origin 的 POST → 403；同源 → 200；无 Origin 的脚本客户端 → 200；
  - `/api/chat/stream` 以 `data: [DONE]` 收尾；
  - 伪装公网 Host 打打印接口 → 403「打印仅支持本机访问」；
  - 附件上传 200 + `docId`、同内容重复上传标 `duplicate`、正文过短 400；
  - 额度=1 且当天已有 1 条用量 → 真实提问 429，而罐头欢迎语连发 3 次仍 200；
  - `WEB_CONCURRENCY=4` 启动 → 单 worker 告警确实打印，uvicorn 确实起 4 进程；
  - 前端首页、vite 代理 `/api/health`、`ChatWorkspace.vue` 经 vite 编译（产物含新 composable 引用）。
- 本环境无法验证、由单测兜底的四项：会话**轮换**分支（需 token 年龄 >19.2h）、语音输入全链路（需真麦克风 + Chrome）、LLM 真实回答（无 API key，额度改用「造当天用量行」触发）、触摸手势（无真触屏）。

## 七、升级与部署注意

- 前端版本号升至 `1.26.0`（`frontend/package.json`）。
- **无接口路径变更、无数据库表结构变更**：`backend/data/mathguide.db` 直接沿用，不需要迁移脚本。
- **升级前请确认备份的是 `mathguide.db`（连同 `-wal` / `-shm`）**，不是旧的 `users.json` / `tokens.json` —— 旧备份步骤是错的，本版已修正 `deploy/README.md`。
- 新增可选环境变量：`MG_DAILY_LLM_CALLS`（每日模型调用额度，留空=不限）、`MG_COOKIE_DOMAIN`（跨子域登录）、`MG_LOG_LEVEL`、`MG_RESEARCH_MAX_UPLOAD_MB` / `_MAX_DOCS` / `_MAX_TOTAL_MB` 等，全部见 `backend/.env.local.example`。
- **必须单 worker 部署**：限流、每日额度与会话缓存都按进程内存实现；加 `--workers N` 会让额度变成 N 倍。启动时会告警，`deploy/mathguide.service` 已写明。
- 打印如在局域网演示机上使用，需同时满足 `MG_PRINT_OPEN=1` **且** `MG_DEMO_MODE=1`；公网部署一律 403。
- 会话行为变化：用户不再每天被登出；已登录用户升级后会拿到新 token，旧 token 仍可用至自身过期（不会被强制踢下线）。
- 发布附件：完整源码快照、相对 `v1.25.0` 的补丁、改动前代码包、`MANIFEST.sha256` 与校验文件。

### 发布物存放（自 v1.26.0 生效）

从 v1.26.0 开始，源码包 / 补丁 / 改动前代码包**不再提交进仓库**，改为在 GitHub
Release 页面作为附件上传（`releases/` 已加入 `.gitignore`，历史目录保留但不更新）。

原因：每版附件约 2 MB 且二进制不可压缩，17 个版本已让 `.git` 达到 257 MB，
克隆与 CI checkout 越来越慢。仓库内只保留 `MANIFEST.sha256` 与发布说明，
用于校验下载到的附件。

## 八、合并记录

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
- 发布提交：v1.26.0 版本号、关于页版本条目与本发布说明

历史发布说明：v1.25.0 及更早见 `docs/release-notes-v1.25.0.md` 与 `releases/`（历史目录）。
