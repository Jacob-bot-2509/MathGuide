# MathGuide 工程优化方案（P0–P5）

日期：2026-11-13
状态：**M0 / M1 / M2 / M7 已完成并验证**（见第 0 节）；M3–M6 待排期
基线：v1.25.0（代码快照 `8475f4a` / 发布提交 `66ead6e`）；后端 944 passed、前端 20 套自测
关联：[后端 README](../backend/README.md)、[部署清单](../deploy/README.md)、[评测报告](EVAL_REPORT.md)

## 0. 本轮落地情况（2026-11-13）

| 批次 | 状态 | 实际改动 |
| --- | --- | --- |
| M0 热修 | ✅ 完成 | 会话 Cookie 与 token 同寿命（24h）+ 过期 401 测试；乱码注释、`POST→GET` 文档、部署备份改 `mathguide.db`、后端 README 存储描述改 SQLite；删除零引用 `GeoGebraBlock.vue`；`.env.local.example` 补齐 16 个变量（另加 `MG_LOG_LEVEL`） |
| M1 契约护栏 | ✅ 完成 | `tests/test_api_contract.py`（5 条：路由↔README 双向、auth 文档↔注册方式、KaTeX 前后端版本）；`scripts/i18n-test.ts`（ZH/EN 键一致 + `t()` 引用存在）；README 补 31 条接口；`main.py` docstring 改为分组概览 |
| M2 基建 | ✅ 完成 | ruff（`backend/pyproject.toml`，59 处自动修 + 8 处手改，现存 0 违规）；eslint 9 flat + prettier + `globals`（`npm run lint` 0 违规）；`print` → logging（服务代码 85 处，`backend/log.py` 带 request_id 中间件）；`watchfiles` 移出运行依赖、`sympy` 锁版本、`ruff` 入 dev；CI 加 ruff / eslint / Windows / py3.14 矩阵，node 固定 22 |
| M7 仓库卫生 | ⚠️ 部分 | `releases/` 已加入 `.gitignore` + `NEWRELEASE.md` 说明（停止新增，历史保留）；KaTeX 物理去重**延后**，由 M1 的版本一致性测试守住 |
| M3–M6 | ⏳ 待做 | 见第 7–10 节 |

**验证结果**：后端 `956 passed, 1 skipped`（基线 944 + 新增 12：契约 5 条、会话过期 1 条、日志 6 条）；前端 `eslint` 0 违规、`vue-tsc` 通过、21 套自测全通过、`vite build` 通过；`ruff check backend` 全绿。


## 1. 这份方案解决什么

v1.25.0 的功能与测试水位已经不错（PBKDF2、token 只存哈希、body 上限、SSRF 只放行 OA 源、演示模式公网启动守卫、944 个后端测试）。本轮**不动产品口径、不动检索参数、不改数据库结构**，只收四类债：

1. **语义债**：会话有效期自相矛盾（Cookie 30 天 / token 24 小时且不续期），用户每天掉登录；
2. **文档债**：30 个接口没写进 README；`deploy/README.md` 的备份步骤还指向已废弃的 `users.json`/`tokens.json`（照做等于没备份）；
3. **基建债**：零 lint、零 logging（196 处 `print`）、CI 只有 Linux 单点、前端测试依赖未声明；
4. **体量债**：`ChatWorkspace.vue` 3944 行、`research_corpus.py` 2566 行、`chat.py` 1875 行 51 个函数；`releases/` 36.8 MB 版本快照进 git，`.git` 已 257 MB。

## 2. 度量口径（改前 → 改后目标）

| 指标 | 当前实测 | 目标 | 验证方式 |
| --- | --- | --- | --- |
| ruff / eslint 违规数 | 无工具，未测 | 0（新增代码零违规，存量按 `--diff` 增量） | CI |
| `print(` 数量（非测试） | 196 | 0（全部走 logging） | `Select-String` / rg |
| 接口文档覆盖率 | 49/78 = 63% | 100% + CI 守护 | M1-1 测试 |
| 会话行为 | 24h 必掉登录 | 与 Cookie 语义一致 | `test_auth.py` |
| 最大单文件行数 | 3944（ChatWorkspace） | ≤ 1200 | `wc -l` 排序 |
| RAG 检索回归护栏 | 无 | top-k 顺序 golden 测试 | `test_rag_regression.py` |
| 仓库体积（.git） | 257 MB | 停止增长（历史迁移见 D3） | `git count-objects -vH` |
| 后端测试数 | 944 | 956（本轮已达） | pytest |

## 3. 总览

| 编号 | 事项 | 优先级 | 影响面 | 估时 | 依赖 |
| --- | --- | --- | --- | --- | --- |
| M0-1 | 会话语义定案（Cookie vs token） | P0 | 用户每天掉登录 | 2h | D1 |
| M0-2 | `auth.py:448` 注释乱码 | P0 | 可读性 | 5m | — |
| M0-3 | `auth.py:15` 方法文档 POST→GET | P0 | 接口契约 | 5m | — |
| M0-4 | 部署备份步骤改 `mathguide.db` | P0 | **数据安全** | 30m | — |
| M0-5 | 后端 README 存储描述 JSON→SQLite | P0 | 文档矛盾 | 10m | — |
| M0-6 | 删除零引用 `GeoGebraBlock.vue` | P0 | 死代码 | 10m | — |
| M0-7 | 补 16 个未文档化环境变量 | P0 | 部署踩坑 | 40m | — |
| M1-1 | 路由 ↔ 文档一致性测试 | P1 | 防漂移 | 2h | M0-3 |
| M1-2 | i18n key 一致性测试 | P1 | 防文案漂移 | 1.5h | — |
| M1-3 | README 补 30 条接口 | P1 | 可维护 | 3h | M1-1 |
| M2-1 | 引入 ruff | P1 | 质量门禁 | 4h | — |
| M2-2 | 引入 eslint + prettier | P1 | 质量门禁 | 4h | — |
| M2-3 | `print` → logging | P1 | 可观测性 | 6h | — |
| M2-4 | 显式声明 esbuild | P1 | 测试可复现 | 15m | — |
| M2-5 | requirements 整理 | P1 | 可复现 | 30m | — |
| M2-6 | CI 加 Windows/3.14 矩阵 | P1 | 跨平台回归 | 3h | M2-1/2 |
| M3-1 | `chat.py` 按职责拆分 | P2 | 可维护 | 2d | — |
| M3-2 | `ChatWorkspace` 抽 composables | P2 | 可维护 | 3d | — |
| M3-3 | `research_corpus.py` 拆分 | P2 | 可维护 | 2d | — |
| M3-4 | `i18n.ts` 按域拆文件 | P2 | 可维护 | 0.5d | M1-2 |
| M4-1 | RAG 检索回归测试 | P3 | 防检索退化 | 1d | — |
| M4-2 | 聊天流式端到端测试 | P3 | 防链路断裂 | 1d | — |
| M4-3 | 覆盖率统计与门槛 | P3 | 质量可视化 | 0.5d | — |
| M4-4 | 前端迁 vitest（可选） | P3 | 测试体验 | 2d | D4 |
| M4-5 | KaTeX 前后端版本一致性测试 | P3 | 渲染一致性 | 0.5h | — |
| M5-1~5 | 研究源 / 图解 / 公式 / 评测口径 / 题库 | P4 | 学术指标 | 见研究计划 | — |
| M6-1 | 收紧 `MG_PRINT_OPEN` | P5 | 安全 | 1h | — |
| M6-2 | 写死"必须单 worker" | P5 | 稳定性 | 1h | — |
| M6-3 | CSRF / `__Host-` 评估 | P5 | 安全 | 4h | D5 |
| M6-4 | 每日模型调用上限 | P5 | 成本护栏 | 1d | — |
| M7-1 | `releases/` 移出 git | — | 仓库体积 | 4h | D3 |
| M7-2 | KaTeX 字体去重 | — | 体积 | 2h | — |

---

## 4. M0 · 热修（P0，约 0.5 人日，零行为变更除 M0-1）

这一批可以当天合入 `release/v1.26.0`，独立成一个 `fix:` 提交。

### M0-1 会话语义定案

**现状**：`store.py:27` `TOKEN_TTL_HOURS = 24`，`store.py:423` 超期即 `None`；`auth.py:48` 却写 `COOKIE_MAX_AGE = 30 * 24 * 3600`，注释还声称"与 token 的实际留存策略同量级"。`auth.py:361` 的 `session()` 只 `_set_session_cookie(response, token)`，用同一个 token，**没有轮换**。净效果：Cookie 留 30 天，token 24 小时失效，用户每天被登出一次。

**方案 A（推荐，最小改动）**：让 Cookie 与 token 同寿命。

```python
# backend/auth.py
COOKIE_MAX_AGE = store.TOKEN_TTL_HOURS * 3600  # 与 token TTL 同寿命,避免"Cookie 还在但已登出"
```

验收：`test_auth.py` 增加断言 `Max-Age=86400`，并断言把 `issued` 拨回 25 小时前 `/api/auth/session` 返回 401。

**方案 B（体验更好，需额外测试）**：滑动续期 —— 在 `session()` 里签发新 token 并吊销旧的，但必须处理两个坑：

1. 多标签页并发续期会让别的标签页拿着已被吊销的 token → 401，因此旧 token 要留 60 秒宽限期（`revoke` 改为"打标记 + 宽限后清理"）；
2. 每次启动都换 token 会写库，需要节流（剩余寿命 > 20% 时不续期）。

验收：`issued` 拨到 23 小时 → `session` 返回新 token；旧 token 在宽限期内仍可用、宽限期后 401；连点 5 次 `session` 只产生 1 个新 token。

> 决策点 **D1**：选 A 还是 B。A 一天内可完成；B 约 1 人日并要动 `store.py` 的 token 生命周期语义。

### M0-2 ~ M0-5 文档与注释修正

| 文件:行 | 现状 | 改为 |
| --- | --- | --- |
| `backend/auth.py:448` | 整条中文注释被替换成半角问号（全仓唯一一行） | 按上下文补回："用量与诊断一并删除，避免残留" |
| `backend/auth.py:15` | `- POST /api/auth/session` | `- GET  /api/auth/session`（`main.py:104` 无 `methods`，实际 GET） |
| `deploy/README.md:103` | "定期备份 `users.json` / `tokens.json`" | 备份 `backend/data/mathguide.db` 及 `-wal`/`-shm`（停服务后 copy 或 `sqlite3 .backup`）；旧 JSON 只作迁移源 |
| `backend/README.md:4` | "认证…走本地 JSON 存储" | "认证…走 SQLite（`data/mathguide.db`）"，与同文第 "存储与迁移(SQLite)" 节一致 |

M0-4 是本批**唯一有真实风险收益**的一条：现在照着部署文档做备份，用户数据（SQLite）根本不在备份范围内。

### M0-6 删除死代码

`frontend/src/components/diagram/GeoGebraBlock.vue`（128 行，`bafde09` 2026-11-03 引入）在全仓 `.ts/.vue/.html` 中零引用（含动态 `import()` 路径）。删除并跑 `vue-tsc --noEmit` + `npm run build` 确认无引用。

### M0-7 环境变量文档补齐

`backend/.env.local.example` 缺失但代码在用的 16 个变量（扫描 `getenv("MG_...")` 与示例文件差集得到）：

| 变量 | 用途 | 建议 | 出处 |
| --- | --- | --- | --- |
| `MG_COOKIE_DOMAIN` | 跨子域共享登录 | **必写**（双域部署必需） | `auth.py` |
| `MG_RESEARCH_MAX_UPLOAD_MB` | 单文件上传上限 | 写默认值 | `research_corpus.py` |
| `MG_RESEARCH_MAX_DOCS` | 账号文档数上限 | 写默认值 | `research_corpus.py` |
| `MG_RESEARCH_MAX_TOTAL_MB` | 账号总占用上限 | 写默认值 | `research_corpus.py` |
| `MG_VISION_API_KEY` / `_BASE_URL` / `_MODEL` | 公式/整页识别 | 写"可选" | `research_vision.py` |
| `MG_UNPAYWALL_EMAIL` | Unpaywall 礼貌池 | 写"可选" | `research_oa.py` |
| `MG_OPENALEX_API_KEY` | OpenAlex 配额 | 写"可选" | `research_lit.py`、`research_oa.py` |
| `MG_NCBI_API_KEY` | PubMed 配额 | 写"可选" | `research_lit.py` |
| `MG_ADS_API_KEY` | ADS 配额 | 写"可选" | `research_lit.py` |
| `MG_LITERATURE_MAILTO` | 文献源礼貌池邮箱 | 写"可选" | `research_lit.py` |
| `MG_ANALYSIS_PYTHON` | 回归 worker 解释器 | 写"可选"，指向 `backend/README.md` 的 worker 节 | `analysis_client.py` |
| `MG_TREE_WALK` | 章节树检索开关 | 写默认 0 + "无评测集前不要开" | `research_corpus.py` |
| `MG_PRINT_OPEN` | 允许远端触发本地打印 | **标注危险**，见 M6-1 | `research_tables.py` |
| `MG_HOST` | 无 CLI 时补绑定地址 | 写"一般不用" | `config.py` |

验收：再跑一次差集脚本无输出。

---

## 5. M1 · 契约护栏（P1，约 1 人日）

目标：把"文档/文案与代码不同步"这类问题从**人肉检查**变成**CI 红灯**。M1 之后再改接口或加文案，忘记同步就会失败。

### M1-1 路由 ↔ 文档一致性测试

新增 `backend/tests/test_api_contract.py`：

1. 断言 `main.routes` 中所有 `/api/*` 路径都出现在 `backend/README.md` 的接口表里（当前 78 个唯一路径，README 只有 49 个 → 先补文档，M1-3）；
2. 断言 `main.py` 顶部 docstring 的"接口一览"与真实路由数量一致（现在写 16 条，实际 78 条）；
3. 断言 `auth.py` 模块 docstring 里的方法/路径与 `main.py` 注册的 `methods` 匹配（能直接抓住 M0-3 这类错）。

实现要点：解析 `Route("...", ..., methods=[...])` 用正则即可（`main.py` 格式统一，88 处声明），不需要引入 `inspect` 反射。README 侧用同一套归一化（`{doc_id}`/`{table_id}` → `{}`）。附一条"豁免白名单"常量，允许 `/api/health` 之类不必写进表。

验收：`pytest backend/tests/test_api_contract.py` 通过；故意删 README 一行 → 测试失败。

### M1-2 i18n key 一致性测试

新增 `frontend/scripts/i18n-test.ts`（挂进 `run-tests.mjs`）：

1. `ZH` 与 `EN` 的 key 集合相等；
2. 源码里所有 `t('...')` 的字面量 key 都存在于字典中（当前扫出来是同步的，加护栏防漂移）；
3. 允许"已定义未使用"存在，但**新增未使用 key 时打印警告**（当前有 86 个死 key，可作为清理清单，不阻塞 CI）。

> 踩坑记录：写扫描脚本时要注意两种写法 —— 同一行两个 key（`i18n.ts:866`），以及英文值里含撇号导致改用双引号（`i18n.ts:1319`），否则会产生假告警。

### M1-3 README 补齐 30 条接口

按 `annotations` / `text` / `file` / `history`(+`trash`/`restore`) / `legacy-import` / `storage` / `cache/purge` / `print` / `regression` / `suggest-topic` / `validate-formula` / `match-formulas` / `papers/import` / `papers/temp`(+`temp-page`) / `diagrams/plan` / `diagrams/metrics` / `forms` 等分组补表：方法 / 路径 / 鉴权 / 限流 / 请求体要点 / 落盘副作用。

同时把 `main.py` 顶部 docstring 从"16 条精选"改成"分组概要 + 指向 backend/README.md 全表"，避免长期维护两份。

---

## 6. M2 · 工程基建（P1，约 2.5 人日）

### M2-1 后端 lint（ruff）

- 新增 `backend/pyproject.toml`：`target-version = "py313"`、`line-length = 110`（贴合现有长行）、规则集 `E,F,I,B,UP,SIM`；
- 首次落地策略：**不做全量格式化**，只 `ruff check --fix` 处理能自动修的（import 排序、未用导入），其余用 `per-file-ignores` 显式豁免并在注释里写明原因；
- CI 加 `ruff check backend`（`--diff` 在 PR 上只查改动行，降低噪音）。

### M2-2 前端 lint + format

- `eslint` 9 flat config + `eslint-plugin-vue` + `typescript-eslint`，规则先只开 `vue/multi-word-component-names`、`no-unused-vars`、`no-console`（当前 `console.log` 为 0，开 `no-console` 成本极低）；
- `prettier` 与现有风格对齐（单引号、无分号、`printWidth: 100` —— 现有代码就是这套），**只对新文件强制**，存量文件在后续 M3 触碰时顺带格式化，避免 3944 行文件一次性大 diff 淹没 review；
- `package.json` 加 `"lint": "eslint src"`、`"format": "prettier --write src"`。

### M2-3 print → logging

- 新增 `backend/log.py`：`get_logger(name)`，统一格式 `%(asctime)s %(levelname)s %(name)s %(message)s`，handler 仍写 stdout（保留 `main.py:30` 的 UTF-8 + `line_buffering` 修复，保证 Windows 控制台不因下标字符崩）；
- 196 处 `print(` 按语义分级：启动/清理 → `INFO`，降级/回退 → `WARNING`，吞异常 → `ERROR`（带上异常类型，不带 traceback 到用户响应）；
- **脱敏口径与现状一致**：不记录 prompt / 回答正文 / 手机号，只记 uid、长度、耗时、模型角色；
- 顺带补 `request_id`（从 SSE 流生成），把一次请求的多条日志串起来。

验收：`Select-String '^\\s*print\\('` 在非测试代码中为 0；启动日志、一次聊天、一次降级回退各能串起同一 `request_id`。

### M2-4 / M2-5 依赖整理

- `frontend/package.json` devDependencies 加 `"esbuild": "0.28.2"` —— `run-tests.mjs` 全程 `npx esbuild`，但它只是 vite 的传递依赖（`package-lock.json` 里存在、`package.json` 未声明），vite 换打包器或离线环境会直接炸；
- `backend/requirements.txt:4` `watchfiles` 注释自述"仅开发用"却放在运行依赖 → 移到 `requirements-dev.txt`（注意 `dev_reload.py` 只在本地用，生产 `uvicorn` 直跑不依赖它；改完要确认 CI 的 `pip install -r requirements.txt` 后 `compileall` 仍过）；
- `backend/requirements-dev.txt:3` `sympy>=1.12` 浮动 → 锁到当前可用版本，避免"昨天过今天挂"。

### M2-6 CI 矩阵

```yaml
strategy:
  matrix:
    os: [ubuntu-latest, windows-latest]
    python: ["3.13", "3.14"]
    exclude:
      - os: windows-latest
        python: "3.14"   # 先跑通 3.13,再放开
```

理由：项目是 Windows 优先（`dev.bat`、GBK/UTF-8 处理、`vite.config.ts` 里 `D:\code` junction 注释），但 CI 只有 Ubuntu；本机已是 Python 3.14.7，CI 却是 3.13。加 Windows 任务能直接抓 GBK 编码、路径分隔符、`kill tree` 这类只有 Windows 才炸的问题。

成本控制：Windows job 只跑 backend（前端在 Ubuntu 跑即可），并在 `pytest` 前加 `-x` 快速失败。

---

## 7. M3 · 结构治理（P2，约 7.5 人日，必须分步上）

原则：**只搬迁、不改逻辑**。每一步都用"全量测试通过 + 无行为 diff"作为完成条件，一步一个 commit，出问题可单步 revert。

### M3-1 `chat.py` 拆分（2 人日）

现状 1875 行 / 51 个函数，一个模块同时承担 SSE 协议、提示词、角色路由、检索改写、答案复核、图解校验、论文问答、导航、公式澄清、直觉解释。

| 新文件 | 迁入内容 | 说明 |
| --- | --- | --- |
| `chat_sse.py` | `_sse` / `_frames` / `_frame_text_len` / `_with_meta` / `_DONE` | 纯协议层，无业务依赖 |
| `chat_prompts.py` | `WELCOME_*` / `FALLBACK_*` / `ATTACH_*` / `_INTUITION_SYSTEM_*` / `_CLARIFY_*` | 只有常量，评审时最好 diff |
| `chat_routing.py` | `_pick_role` / `_chitchat_kind` / `_conversational_reply` / `_normalize_query` / `_retrieval_query` / `_validated_history` | 纯函数，最适合补单测 |
| `chat_verify.py` | `_verify_answer` / `_diagram_verified` / `_verify_clarify` | 双模型复核 |
| `chat_paper.py` | `_gen_paper_llm` / `_paper_actions_frame` | 论文问答 |
| `chat_nav.py` | `_nav_system` / `_nav_guide_system` / `_gen_nav_list` / `_gen_nav_guide` | 导航 |

`chat.py` 保留 `chat_stream` / `intuition` / `speech_to_math` 三个路由入口 + 用量记账，并 `from chat_sse import ...` 保持测试里的 `chat._sse` 等引用不破（现有 `test_chat_helpers.py` 直接调私有函数，**不要动这些名字**）。

验收：`pytest backend/tests` 944 passed 不变；`wc -l backend/chat.py` ≤ 700。

### M3-2 `ChatWorkspace.vue` 抽 composables（3 人日）

3944 行，其中 script 2221 行、183 个顶层声明。按职责抽 3 个 `composables/`：

1. `useChatStream.ts`：SSE 连接、帧解析、中断与 `[DONE]` 收尾、失败重试（`sse-stream-test.ts` 已有契约，抽完直接复用该测试）；
2. `useChatPersistence.ts`：会话/消息落本地、回收站、导入导出；
3. `useChatAttachments.ts`：附件/公式导入/剪贴板。

模板部分先不动。目标 ≤ 1200 行（script + template）。风险最高的第 1 项建议单独排一天，做完立刻 `npm test` + 手测"中断/恢复/切会话"三个场景。

### M3-3 `research_corpus.py` 拆分（2 人日）

2566 行 / 113 个函数，混了索引构建、切片、检索、文件落盘、配额、HTTP 接口。建议按 `corpus_store.py`（落盘/配额/迁移）、`corpus_index.py`（切片/向量/评分）、`research_docs_api.py`（HTTP 层）三段拆；`research_corpus` 保留导出面，避免 `main.py` 与 30+ 处调用点同时改。

注意：这是全文最热路径（36 处引用），**必须**先用 M4-1 的检索 golden 测试兜底再动手。

### M3-4 `i18n.ts` 按域拆文件（0.5 人日）

2027 行 / 955 个 key 一个文件。按 `i18n/{common,chat,research,tables,account,about}.ts` 拆，`i18n/index.ts` 合并导出并保留 `t()` 签名。纯机械拆分，M1-2 的测试保证不漏 key。

---

## 8. M4 · 测试补齐（P3，约 2.5 人日；可选 vitest 另计 2 人日）

### M4-1 RAG 检索回归测试（1 人日，优先级最高）

v1.25.0 的发布卖点就是"检索排序与召回"，但后端只有 `test_rag_diversity.py`(34 行) + `test_rag_init.py`(83 行) 覆盖，参数一调只能靠离线跑 `course-50`。补：

1. **固定小语料**：`tests/fixtures/rag/` 放 5~8 篇带标题/小节的 md，覆盖"章节标题命中""公式符号""同义改写"三类；
2. **embedding 打桩**：conftest 已坚持不联网，用确定性哈希向量（同一文本 → 同一向量）替代真实 embedding；
3. **golden 断言**：`W_SECTION`、bigram IDF、关键词权重 5.0、数学题向量门限 0.50 这些当前参数下，断言 top-3 顺序与分数区间；参数一改测试就红，逼着改的人同时更新 golden 并在 PR 说明理由。

### M4-2 聊天流式端到端测试（1 人日）

现在只有 `test_chat_helpers.py` 里两处 `TestClient` 片段。补三条主链路：

1. 未配置 LLM → 知识库直答降级（保证"演示永远能答"）；
2. 正常流 → 帧序列、`[DONE]` 收尾、用量记账各一次（`_meter` 逻辑有 11 处 `to_thread`，很容易改坏）；
3. 限流触发 → 429 且不写用量。

### M4-3 覆盖率门槛（0.5 人日）

`pytest --cov=. --cov-report=term-missing`，先记录基线（估计 70%±），CI 用 `--cov-fail-under=<基线-2>` 做**防倒退**而不是追高。前端覆盖率随 D4 一起定。

### M4-4 前端测试迁 vitest（2 人日，可选）

现状 20 个脚本靠 `npm test` 串行 `esbuild + node` 跑，无覆盖率、失败信息弱、依赖未声明。vitest 与 vite 同源，迁移成本低且能直接跑 `.vue` 组件测试（现在 `ChatWorkspace` 这类大组件完全没测试，正是因为缺组件测试能力）。是否做见 **D4**。

### M4-5 KaTeX 前后端版本一致性测试（0.5h，建议并入 M1）

聊天渲染用 npm `katex`，PDF/Word 导出用 `backend/static/katex/katex.min.js`。当前两边都是 **0.16.47**（`package-lock.json` 与 `katex.min.js` 里的 `version:` 字段），但没有任何机制保证：升级前端依赖时若忘了同步 `backend/static/katex/`，就会出现"聊天里能渲染、导出的 PDF 报 ParseError"或反之。加一条断言即可，成本几乎为零。

---

## 9. M5 · 产品与研究缺口（P4，不占工程排期）

这一批**不是重构任务**，而是项目文档里已自认的缺口，应按"先补数据、再调参"的顺序单独立项，和工程优化并行推进。

### M5-1 研究检索源（`RESEARCH_SOURCE_PLAN_V2.md:561-568`）

文档自列未完成：S2 免费 key 的生产配置、ChinaXiv / CAS IR Grid / ChemRxiv 的网络验证、CORE、授权索引（WoS/Scopus/MathSciNet/SciFinder/Reaxys）、校园图书馆与 CARSI。

更值得优先处理的是同文档的冒烟基线（`:555-559`）：

| 学科 | 结果 | authority_precision | peer | oa |
| --- | --- | --- | --- | --- |
| general | 30 | **10%** | 100% | 43% |
| math | 30 | **10%** | 100% | 10% |
| physics | 30 | **30%** | 100% | 27% |
| chemistry | 30 | 57% | 100% | 27% |
| biology | 30 | 80% | 100% | 57% |

math 只有 10%，而数学是主打学科；math 的 oa（可获取全文比例）也只有 10%。建议顺序：① 先扩样本到每学科 ≥ 100 查询，得到有置信区间的基线；② 再调权重；③ 最后才谈接入新源。否则"调参"是在 30 条样本上过拟合。

### M5-2 图解（`STATIC_DIAGRAM_PLAN.md:343-347`）

- 3D 首屏构图与复杂曲面采样需真实样本调优；
- 图解事件晚到时锚点随正文增长轻微移动（体验瑕疵，已有韧性机制兜底）；
- 3D 仍是"一图一 renderer"，大量消息时依赖 `forceContextLoss` 与控制上下文卸载 —— 这是**潜在的内存/稳定性风险**，建议在演示机（低配）上做一次 30 条长会话压测，再决定是否做 renderer 池化。

### M5-3 公式与表格（`DATA_FORMULA_PLAN.md:475-480`）

真实整页 / 手写 / 多表样本金标准、多公式依赖组与批量应用、**部署前并发压测与成本上限**、自动采用策略的误采用率。

其中"并发压测与成本上限"应**上提到工程侧**：测评期如果 20 人同时用，单进程 + 每张图多一次异源校验 + 复核调用，很容易撞平台 QPS 或把额度烧穿。建议在 M6 里补一条"成本与并发护栏"（见 M6-4）。

### M5-4 评测口径（`EVAL_REPORT.md:55-58`）

- 报告自述：幻觉率只有 glm-5.2 单次判断，**无人工盲标、无 kappa 一致性**，不能替代人工评审；
- 两套 50 题为项目组自编草稿，需教师/助教审核；
- **文档已过期**：报告（2026-10-28）仍写 hit@3 = 0.667 并称其为"最明确的短板"，而 v1.25.0 发布说明已是 hit@3 0.708 / hit@5 0.792。建议给报告加"版本对应"表头，或直接发布 v1.25.0 版报告（含 400 题锁定集的 dev/test 切分说明）。

### M5-5 题库（`EXERCISE_BANK_STATUS.md:8`）

人工复验未完成；复验完成后把通过项替换为 `verified` 数据即可，接口不变 —— 属纯数据工作，可与工程并行。

---

## 10. M6 · 安全加固（P5，约 1.5 人日）

先说结论：现有安全设计不弱（PBKDF2 200k + 旧 sha256 自动升级、token 只存 SHA-256、body 分块限流、上传按内容哈希落盘、SSRF 只放行 OA 源、演示模式公网绑定/`CORS=*` 拒绝启动、CSP/HSTS 齐全）。以下是三处可加固点和一条新增护栏。

### M6-1 收紧 `MG_PRINT_OPEN`

`research_tables._print_allowed()` 第一行就是 `if os.getenv("MG_PRINT_OPEN") == "1": return True`，**绕过后面的本机 host 校验**。一旦这个变量被设成 1 并部署到公网，任何客户端都能触发服务端 `os.startfile`/打印。

改法（按稳妥程度排序）：
1. **推荐**：`MG_PRINT_OPEN=1` 时仍要求 `MG_DEMO_MODE=1` **且** 请求 host 属本机；两者任一不满足 → 403；
2. 或在 `config.assert_safe_demo_mode()` 旁边增加启动检查：`MG_PRINT_OPEN=1` 且 `MG_DEMO_MODE=0` → 直接拒绝启动（与现有守卫风格一致，最省事）；
3. 示例文件里标注"危险：仅本机演示"（M0-7 一并做）。

验收：新增测试 —— host 头为 `evil.com` 时，即便 `MG_PRINT_OPEN=1` 也返回 403。

### M6-2 把"必须单进程"写成硬约束

限流器（`rate_limit.SlidingWindowLimiter`）、`session_cache`、`chat._RESEARCH_CACHE` 都是**进程内存**；而 `deploy/mathguide.service` 的 `ExecStart` 没有 `--workers`，`deploy/README.md` 也没写这条约束。哪天有人为了并发加 `--workers 4`，限流立刻变成 4 倍额度、会话缓存各自分裂。

改法：
1. `deploy/README.md` 增加一节"进程模型：必须单 worker，原因…"；
2. `ExecStart` 显式写 `--proxy-headers --forwarded-allow-ips=127.0.0.1`（别依赖 uvicorn 默认值；现在 nginx 已传 `X-Forwarded-For`，`_client_key()` 依赖它做按 IP 限流）；
3. 启动时若检测到 `--workers > 1`（读 `sys.argv`）或 `WEB_CONCURRENCY > 1`，打 `WARNING` 并说明限流会失效。

### M6-3 写操作来源校验

Cookie 用 `samesite=lax`，跨站 POST 已被浏览器挡住；但双域部署下 Cookie 作用域是父域（`MG_COOKIE_DOMAIN=.example.com`），**任一子域被 XSS 就等于全站沦陷**。建议：

- 低成本优先做：加一个校验 `Origin`/`Referer` 的中间件，只对 `POST/PUT/PATCH/DELETE` 生效，允许列表 = `cors_origins()` + 同源 host；不匹配 403。这对现有前端零改动（浏览器必带 `Origin`）。
- `__Host-` Cookie 前缀只在单域部署可用，与跨子域共享冲突 → 见 **D5**，不建议测评期动。

### M6-4 成本与并发护栏（新增，来自 M5-3）

- 配置化：`MG_DAILY_LLM_CALLS`（账号/全局）、`MG_DAILY_VISION_CALLS`，超限返回 429 并在 `/api/stats` 可见；
- 现有 `usage` 表已按 uid 记账，加"按天聚合查询"即可，不需要新表；
- 目的：测评期防止单账号刷爆额度，也防止一张图触发 3~4 次模型调用把成本放大。

---

## 11. M7 · 仓库卫生（不占排期，随时可做）

### M7-1 `releases/` 移出 git

`releases/` 现 36.8 MB / 106 文件（17 个版本 × ~2 MB 源码 tar.gz + patch），`.git` 打包 257 MB。每发一版 +2 MB，克隆与 CI checkout 会持续变慢。

三个选项（**D3**）：

| 方案 | 做法 | 优点 | 代价 |
| --- | --- | --- | --- |
| A（推荐） | 停止新增：`releases/` 加进 `.gitignore`，附件挂 GitHub Release assets；历史保留 | 零风险，立即止血 | 库里仍有 36.8 MB 历史 |
| B | `git filter-repo --path releases --invert-paths` 重写历史 | 仓库真正变小 | 破坏性：所有人必须重新 clone，tag 校验值会变 |
| C | `git lfs migrate import --include="releases/**"` | 历史保留且仓库变轻 | 依赖 LFS 配额；CI 需装 LFS |

建议：先做 A，把 `NEWRELEASE.md` 的发布流程改成"源码包作为 Release asset 上传"，等这届测评结束再评估 B。

### M7-2 KaTeX 字体去重

`backend/static/katex/` 有 20×`.ttf` + 20×`.woff` + 20×`.woff2`（共 60 个二进制），前端又通过 npm 装了同一份 KaTeX 0.16.47。后端那份是给 PDF/Word 渲染用的本地文件，不能简单删；但可以让前端构建时从同一目录 `copy` 一份，而不是两个来源各自升级。若怕动构建，至少让 M4-5 的版本一致性测试守住。

---

## 12. 决策点（需先拍板，否则会卡住对应里程碑）

| 编号 | 问题 | 选项 | 建议 | 影响 |
| --- | --- | --- | --- | --- |
| D1 | 会话有效期怎么统一 | A：Cookie 改为 24h；B：实现 token 滑动续期 | **A**（当天可完成，风险最低）；B 留到有用户反馈再评估 | M0-1 |
| D2 | `chat.py` 是否拆 | 拆 / 不拆 | **拆**，但必须在 M4-2 之后（先有条链路测试再搬） | M3-1 |
| D3 | `releases/` 怎么处理 | A 停止新增 / B 重写历史 / C LFS | **A 先止血**，B 放到测评结束 | M7-1 |
| D4 | 前端测试是否迁 vitest | 迁 / 不迁 | **迁**（否则大组件永远没测试入口） | M4-4、M3-2 |
| D5 | 是否上 `__Host-` Cookie | 上 / 不上 | **不上**（与跨子域共享冲突）；先做 Origin 校验 | M6-3 |

## 13. 排期建议（1 人全职口径）

| 阶段 | 内容 | 工期 | 交付物 |
| --- | --- | --- | --- |
| S0（第 1 天） | M0 全批 + D1 拍板 | 0.5 天 | `fix:` 提交，可直接合 `main` |
| S1（第 2–3 天） | M1 契约护栏 + M4-5 | 1.5 天 | 3 个新测试文件，CI 变绿且能挡漂移 |
| S2（第 4–6 天） | M2 基建（lint / logging / CI 矩阵） | 2.5 天 | `chore:` + `refactor(log)` 提交 |
| S3（第 7–9 天） | M4-1/4-2/4-3 测试补齐 | 3 天 | RAG golden + 流式 e2e |
| S4（第 10–16 天） | M3-1 → M3-3 → M3-4（结构治理） | 5 天 | 单文件行数达标 |
| S5（第 17–19 天） | M3-2 大组件拆分（风险最高，单独排） | 3 天 | `ChatWorkspace` ≤ 1200 行 |
| S6（并行） | M5 / M6 / M7 | — | 见各节 |

**v1.26.0 发版建议切分**：S0–S2 做 patch 版（`v1.25.1`，纯修）；S3–S5 做 minor（`v1.26.0`，含结构性重构，发布说明里写明"无接口变更、无数据迁移"）。

## 14. 明确不做（防止范围蔓延）

- **不改检索参数**（`W_SECTION`、IDF、权重 5.0、门限 0.50）：本轮只加护栏，调参属 M5-1，需要更大样本；
- **不改数据库表结构**：M0-M7 全部不需要迁移；
- **不重写前端框架/状态管理**：`stores/*` 保持不动，M3-2 只抽 composable；
- **不做全量格式化**：避免 3944 行文件一次性大 diff 淹没 review；
- **不动演示通道语义**（`MG_DEMO_MODE` 默认值、固定验证码 123456）：那是测评流程的一部分。

## 15. 验收清单（每个里程碑都要跑）

```bash
# 后端（在 backend/ 下，用仓库根 .venv）
cd backend && ..\.venv\Scripts\python.exe -m pytest -q

# 前端（在 frontend/ 下）
npm ci && npx vue-tsc --noEmit && npm test && npm run build

# 本计划新增
npx ruff check backend            # M2-1
npx eslint src                    # M2-2
git ls-files releases | wc -l     # M7-1 后应为固定值
```

结构类里程碑（M3）额外加人工冒烟：登录 → 提问（含图解）→ 中断 → 切会话 → 导出 PDF → 研究区上传论文 → 表格公式计算。这 7 步覆盖了本次动过的所有路径。

## 16. 附录 · 本方案的取证方式（可复现）

| 结论 | 取证命令 |
| --- | --- |
| 文件体量 | `Get-ChildItem -Recurse -Include *.py,*.vue,*.ts \| Measure-Object -Line` 排序 |
| `print` / logging | `Select-String -Pattern '^\s*print\('`；`'^import logging'` 计数为 0 |
| 路由文档覆盖率 | 正则抓 `Route\("(/api/...)"`（88 处 / 78 唯一）与 README 路径集合求差（49） |
| 环境变量缺口 | 抓 `getenv("MG_...")` 与 `.env.local.example` 的 `MG_*=` 求差（16 个） |
| 死代码 | 全量 `.ts/.vue/.html` 搜组件名，命中 ≤1（仅自身） |
| i18n 一致性 | 解析 `ZH`/`EN` 块内 `'key':` 求差；再扫 `t('...')` 字面量 |
| 仓库体积 | `git count-objects -vH`（pack 257.42 MiB） |
| 语法基线 | `python -m compileall -q backend`（0 错误，Python 3.14.7） |

> 说明：本次核对时工作区无 `.venv` 与 `node_modules`，因此 944 passed 等运行时数字引用的是 v1.25.0 发布说明，不是本轮实跑结果。
