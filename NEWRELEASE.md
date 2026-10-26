# MathGuide v1.10.0 — 待办、续写、隐私加固与测评支持

发布日期：2026-10-27
发布类型：功能 + 隐私/安全加固 + 测评支持
代码快照：`13296dc169d840e2cce2964324939a124bb53fac`
基线版本：`v1.9.0`（`b6d55fca648e2ba3a49bd27b72fc13396b7fd68d`）
标签：`v1.10.0`（指向上述代码快照）

本版本增加待办清单与停止后续写，重做「关于 MG」与服务协议/隐私政策，
补齐账号数据导出与自助注销；同时把演示模式守卫、token 哈希、用量 PII 清洗、
邀请码注册、安全响应头、CSP 部署模板和留存清理落到代码与部署清单。
另包含 LLM 思考模式控制与正确率/幻觉率评测框架。

## 一、新功能

### 1. 待办清单

- 指令栏「待办清单」打开面板，支持一次性 / 每天 / 每周任务（周一至周日多选）。
- 日期精确到年月日，时间到时分；保存先入草稿，点「设置好了」转日程。
- 当天最早任务到点弹一次高亮提醒面板（无关闭按钮，只能点「好的，我开始做」）；
  页面隐藏时发浏览器系统通知。
- 未到点显示「在表」，到点「进行中」，点击「进行中」变「已完成」；
  跨天未完成变「已过期」，弹「我已知晓」面板。
- 状态色：进行中红色、已完成绿色、已过期灰色。
- 支持暂停/恢复、退回草稿、删除；数据按 `accountKey` 分桶，同账号退出重登保留。
- 实现：`frontend/src/utils/todoTime.ts`、`frontend/src/stores/todo.ts`、
  `frontend/src/components/chat/TodoPanel.vue`、`TodoReminder.vue`。

### 2. 停止生成后「回复」

- 点「停止生成」且有已生成正文时，消息右下角出现「回复」按钮。
- 点击后把原问题 + 已生成正文作为 `resume: true` + `partial` 发给后端。
- 后端专用续写分支：不重新检索/复核，只输出断点后的内容（最多取正文末尾 24000 字）；
  增量追加到同一条消息，不新建气泡。
- `stopped` 随会话持久化，刷新后仍可续写；续写过的消息不再进入后续历史。
- 实现：`backend/chat.py` 的 `_gen_continue` / `resume` 分支，
  `frontend/src/services/chatService.ts`、`stores/sessions.ts`、`views/LearnView.vue`。

### 3. 设置改版

- 拆分三个入口：
  - `/settings/feedback`：功能与改进，提交时在 GitHub 打开预填 issue；
  - `/settings/about`：关于 MG，展示当前/稳定版本、版本记录、用途、协议入口、开源许可；
  - `/settings/terms`：服务协议 / 隐私政策双标签页，未登录也可读取。
- 登录页《用户协议》《隐私政策》可点击；隐私与安全页增加政策入口。
- 修正不实表述：
  - 登录页不再写“登录方式即实名认证方式”；
  - 隐私页不再写“所有数据只在浏览器”，明确 `backend/data/` 与模型/检索平台流向；
  - 语音识别说明为“浏览器提供，音频不经过 MG 服务器；部分浏览器会发给其自有语音服务”；
  - CSP 限定为“导出文档 CSP”，不再暗示主应用已有 CSP。
- 实现：`SettingsAboutView.vue`、`SettingsFeedbackView.vue`、`SettingsTermsView.vue`、
  `utils/aboutContent.ts`、`router/index.ts`、`utils/i18n.ts`。

### 4. 账号数据导出与注销

- `POST /api/account/export`：导出账号信息与用量元数据（不含口令摘要、token、内部 uid）。
- `POST /api/account/delete`：
  - 手机号密码账号需再输当前密码；
  - 验证码/微信/QQ 账号需输入 `DELETE` 或 `注销`；
  - 级联删除账号、全部 token、usage JSONL 与旧 `usage.json` 备份。
- 前端导出会把后端数据与浏览器会话、归纳、设置、回收站、搜索范围、语音缓存、
  当前账号待办合并为 JSON；`mg-user` 会去掉 token。
- 注销成功后清理本机学习数据与待办并回登录页。
- 实现：`backend/auth.py`、`frontend/src/services/accountService.ts`、
  `SettingsAccountView.vue`。

## 二、隐私与安全

- **演示模式守卫**：`MG_DEMO_MODE=1` 时只允许绑定 `127.0.0.1` / `localhost` / `::1`；
  CORS 只能本机来源；`--host 0.0.0.0`、公网 CORS 或 `*` 直接拒绝启动。
- **token 哈希落盘**：`tokens.json` 只存 `sha256:<digest>`，不存明文 bearer token；
  旧明文键启动时自动迁移，已签发 token 不需要重新登录。
- **用量最小化**：`usage.jsonl` 新记录只写 uid，不写手机号/昵称；
  启动时把旧 JSONL 与 `usage.json` 备份里的 `phone`/`user` 换成 uid 并删除 PII。
- **留存清理**：`MG_ACCOUNT_TTL_DAYS` 删除长期未登录账号（管理员白名单保留），
  `MG_USAGE_TTL_DAYS` 清理过期用量；默认 `0` 关闭。
- **安全响应头**：`X-Content-Type-Options`、`Referrer-Policy`、`X-Frame-Options`、
  `Permissions-Policy`；HTTPS 或 `X-Forwarded-Proto: https` 时发 HSTS。
- **CSP 部署模板**：`deploy/Caddyfile` / `deploy/nginx.conf` 提供 HTTPS、HSTS、CSP、
  SSE 不缓冲与 SPA fallback；主题预加载拆到 `frontend/public/theme-init.js`，
  CSP 不需要放开 `script-src 'unsafe-inline'`。
- **登录响应不缓存**：登录/注册/导出/注销响应加 `Cache-Control: no-store`。
- **日志脱敏**：复核日志与 PDF 重排失败日志不再输出模型内容片段，只记长度/数量。
- **限流可配置**：`MG_AUTH_RATE_MAX` / `MG_AUTH_RATE_WINDOW`；多人共用出口 IP 时可调大。
- **邀请码注册**：`MG_DEMO_MODE=0` 后固定验证码/游客登录/开放注册关闭；
  配置 `MG_INVITE_CODES` 后持邀请码可注册，邀请码比较用 `secrets.compare_digest`。
- **登录页适配**：读取 `/api/health` 的 `demo`/`invite`；测评环境自动隐藏验证码与
  微信/QQ 入口，无邀请码时隐藏创建账户。

## 三、LLM 与评测

- **思考模式控制**：`rag/llm.py` 增加 `thinking` 参数；`main`/`backup` 默认关闭
  `enable_thinking`，`deep`/`long` 保留。首字看门狗把 `reasoning_content` 视为有效
  首帧，避免思考型模型被误切备胎；综合、导航、复核、PDF 重排等机械任务显式关闭思考。
- **默认深答模型**更新为 `aliyun:qwen3.8-max`。
- **评测框架**：新增 `backend/evaluation/` 与 `backend/tools/eval_qa.py`。
  - 指标：正确率、答案级/断言级幻觉率、不可答编造率、hit@k、recall@k、MRR@k。
  - 支持检索阶段、回答阶段、异源 LLM 评审；输出 `records.jsonl`、`summary.json`、
    `report.md` 到已忽略的 `backend/reports/`。
  - 新增 `sympy>=1.12` 开发依赖；新增 `test_eval_extract.py`、`test_eval_metrics.py`。

## 四、验证

```text
backend pytest                         171 passed
frontend npm test
  语音数学编译器                       80/80
  SSE 收尾契约                         17/17
  MathText 渲染与链接安全              24/24
  回收站/本地数据/会话持久化           15/15
  待办清单时间/状态                    24/24
  关于 MG 内容完整性                   127/127
  账号导出本机数据                     7/7
npm run build                          通过（仅 tex2svg 分块 >1800kB 的既有告警）
```

手工验证：

- CSP 下加载构建产物：开场 MathJax、登录、聊天 SSE 正常，控制台无 CSP violation。
- 测评模式（`MG_DEMO_MODE=0` + `MG_INVITE_CODES`）：登录页隐藏验证码/第三方入口，
  邀请码注册可用。
- token 哈希迁移后旧 token 仍可访问 `/api/account/export`；`tokens.json` 22 条全部为
  `sha256:` 键。
- `usage.jsonl` 302 条、`usage.json` 275 条，PII 字段均为 0。
- `MG_DEMO_MODE=1` + `--host 0.0.0.0` 启动退出码 1。
- API 基础安全头存在；带 `X-Forwarded-Proto: https` 时 HSTS 存在。
- `git diff --check` 无空白错误。

## 五、行为变更与配置

| 项目 | 变更 | 默认/迁移 |
| --- | --- | --- |
| 演示模式 | 公网绑定/公网 CORS 拒绝启动 | `MG_DEMO_MODE=1` 仅本机；公网必须 `0` |
| 测评注册 | 关闭演示后只放行邀请码 | `MG_INVITE_CODES` 逗号分隔；不配则注册关闭 |
| token 存储 | 明文键 → SHA-256 键 | 启动自动迁移，旧 token 继续有效 |
| 用量身份 | `phone`/`user` → `uid` | 启动清洗 JSONL 与旧备份 |
| 认证限流 | 可配置 | `MG_AUTH_RATE_MAX=10` / `MG_AUTH_RATE_WINDOW=60` |
| 留存清理 | 默认关闭 | `MG_ACCOUNT_TTL_DAYS` / `MG_USAGE_TTL_DAYS` |
| HSTS | 仅 HTTPS 或显式开启 | `MG_ENABLE_HSTS=1` 可强制 |
| 登录页 | 读取后端模式 | `/api/health` 返回 `demo` / `invite` |
| 注册表单 | 加入邀请码；移除未使用的验证码字段 | 演示环境邀请码可留空 |
| 默认深答模型 | `qwen3-235b-a22b` → `qwen3.8-max` | 可用 `MG_ROLE_DEEP` 覆盖 |

## 六、完整代码与溯源附件

本版本把**完整源码快照**与**完整变更补丁**一并入库，位于 `releases/v1.10.0/`，
也会作为 GitHub Release 资产上传：

| 附件 | 内容 | SHA-256 |
| --- | --- | --- |
| `MathGuide-v1.10.0-source.tar.gz` | **完整源码快照**（246 个文件，1,264,352 字节），由 `git archive` 从代码提交 `13296dc` 生成；解压即完整可运行源码 | `9864dde09ee1969dc149cb29858552e7e303c4e84a2cbed03d00281631593f26` |
| `v1.10.0.patch` | 相对 `v1.9.0` 的完整二进制补丁（358,672 字节，排除 `releases/` 附件） | `3f7071db044225a1c9961e0e6878477a1206aa7b54cf3dbee2558112b63f2325` |
| `MANIFEST.sha256` | 源码快照 246 个文件的逐文件 SHA-256（按归档内真实字节生成） | `03dea0c563585355322091ce022c7d5462f0b63f89512545f1d8b38b2f3d5e81` |
| `SHA256SUMS` | 上述附件 + 校验脚本的 SHA-256 | `12e0fdcfe9537ea2c494568497675ca40cc2dfca11d324f234d09033e01a5bdb` |
| `verify_manifest.py` | 跨平台逐文件校验脚本 | `5e05564aa48880428c447a837bb4a121c63cd63a28897e4c9cd8dbc98480c2c7` |

复核步骤：

```bash
cd releases/v1.10.0
sha256sum -c SHA256SUMS
tar -xzf MathGuide-v1.10.0-source.tar.gz
python verify_manifest.py MathGuide-v1.10.0   # checked=246 failures=0
```

源码包不包含 `.git`、`backend/.env.local`、`backend/data/`、`.venv/`、`node_modules/`
和运行时缓存；这些均被 `.gitignore` 排除。`releases/**` 在 `.gitattributes` 中标记为
`-text` 和 `export-ignore`，因此源码包/补丁不会重复携带旧发布附件，clone 后附件字节与
校验和不变。`MANIFEST.sha256` 按源码包内真实字节生成，请以解压后的源码目录为准。

## 七、已知限制

- 实际 HTTPS 证书与域名需部署时填写；仓库提供 Caddy/Nginx 模板，不包含证书。
- 自动留存清理只在启动时执行；如需按小时级清理，需要额外 cron/定时任务。
- 磁盘加密、备份访问控制、模型厂商零留存/不训练设置属于部署环境事项，代码侧只提供
  最小化与文档清单。
- 单进程 JSON/JSONL 存储与限流：多 worker 部署前需换数据库/Redis。
- 评测框架当前样本集很小，只用于框架冒烟；对外报准确率前需人工盲标并计算 kappa。
- 待办提醒依赖页面打开或浏览器通知权限；浏览器完全关闭时不会唤醒 Service Worker。

## 八、升级步骤

1. 拉取 `v1.10.0`，按 `backend/requirements.txt` / `frontend/package-lock.json` 安装依赖。
2. 在 `backend/.env.local` 按需配置：
   `MG_DEMO_MODE`、`MG_INVITE_CODES`、`MG_CORS_ORIGINS`、`MG_ADMIN_PHONES`、
   `MG_AUTH_RATE_MAX`、`MG_AUTH_RATE_WINDOW`、`MG_ACCOUNT_TTL_DAYS`、`MG_USAGE_TTL_DAYS`。
3. 重启后端：会自动迁移 token 哈希、清洗 usage PII，并按配置执行留存清理。
4. 前端 `npm run build`；按 `deploy/README.md` 配置 HTTPS/CSP 反向代理。
5. 运行 `python -m pytest` 与 `npm test` 确认环境。
6. 需要核对发布包时，按第六节命令执行 SHA-256 与逐文件校验。
