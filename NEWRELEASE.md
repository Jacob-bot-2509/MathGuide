# MathGuide v1.9.0 — 安全加固与可靠性发布

发布日期：2026-10-26
发布类型：安全加固 / 可靠性修复（无新增大功能）
代码快照：`b6d55fca648e2ba3a49bd27b72fc13396b7fd68d`
基线版本：`v1.8.0`（`12d7144e9b7efc9286333874ca6754689e6c8ab5`）
标签：`v1.9.0`（指向上述代码快照）

本版本对认证、会话隔离、PDF 导出、检索降级、流式回答和前端本地数据做了一轮系统性加固，
并补齐后端单元/集成测试、前端自测入口与 CI。所有行为变更、配置项、验证记录和完整源码
附件都在本文档中列明，可直接按代码提交与 SHA-256 复核。

> 说明：`v1.8.0` 之后本地已有 5 个文档/设置提交（`docs/MATHGUIDE_ANIMATION_SPEC.md`、
> 各学科视觉隐喻文档、`.vscode/settings.json` 恢复）。本次代码快照包含这 5 个提交，
> 之后再叠加本版本的安全加固提交。完整差异见 `v1.9.0.patch`。

## 一、安全修复

- **跨用户会话缓存隔离**：教材正文与滚动摘要缓存的键从客户端 `sessionId` 改为
  `(uid, sessionId)`；拿不到 uid 时不缓存，避免不同用户撞号后把对方教材/摘要拼进
  自己的模型上下文。登出时清理该用户缓存。（`backend/session_cache.py`）
- **PDF 导出注入修复**：LLM 输出中的引用 `id` 强制转整数并转义，URL 只允许
  `http(s)`；生成页加入 CSP + 每次随机 nonce，禁止注入脚本、`file:` 图片与外连。
  （`backend/doc.py`）
- **密码哈希升级**：新账号使用 PBKDF2-HMAC-SHA256（20 万轮）；旧版单轮 SHA-256
  在登录成功后自动升级；比较改用 `secrets.compare_digest`。（`backend/store.py`）
- **演示模式开关**：`MG_DEMO_MODE=0` 时关闭固定验证码、微信/QQ 访客登录和
  `/register`；默认 `1` 仅适合本机演示。（`backend/auth.py`）
- **认证与接口限流**：登录/注册/登出按客户端 IP 60 秒 10 次；聊天/语音/导出按用户
  60 秒 6 次；限流表有界并自动清理不活跃 key。（`backend/rate_limit.py`）
- **请求体上限**：所有 JSON 接口 2 MiB，超限 413；非法 JSON/非对象 400；超长
  `Content-Length` 与孤立代理项（`\ud800`）不会再变成 500。（`backend/http_utils.py`）
- **管理员接口**：`/api/stats` 仅允许 `MG_ADMIN_PHONES` / `MG_ADMIN_UIDS` 白名单；
  未配置时默认 403，避免任何登录用户读取全站手机号。（`backend/main.py`）
- **CORS 收紧**：默认只放行 `http://localhost:5173` 与 `http://127.0.0.1:5173`；
  其他来源用 `MG_CORS_ORIGINS` 显式配置。
- **游客账号上限**：`MG_GUEST_MAX`（默认 500，0=禁止）；满额时先清理无有效 token
  的最旧游客，仍满才拒绝新建。（`backend/store.py`、`backend/auth.py`）
- **本机数据按账号隔离**：登录返回不可逆 `accountKey`；同账号重登（含 401 后）保留
  本机会话/归纳本/回收站/语音缓存，换账号自动清空。（`frontend/src/stores/localData.ts`）
- **arXiv 改走 HTTPS**，外部响应 2 MiB 上限；4xx 中只重试 408/425/429。
  （`backend/rag/research/sources.py`、`backend/tools/fetch_knowledge.py`）

## 二、可靠性与正确性

- **embedding 冷启动降级**：`rag.init()` 同时兜住 `Embedder` 构造与 `KnowledgeIndex`
  装载；冷缓存/服务超时不再导致后端起不来，必要时以空索引启动。
- **向量缓存键含模型名**：换 embedding 模型不再静默复用旧向量；校验返回条数、
  空向量、维度不一致、NaN/字符串等坏缓存。
- **知识库坏文件隔离**：单个 md/txt 编码/占用/frontmatter 异常只跳过该文件。
- **LLM 半截输出不回放**：只有一字未出才切 backup；已输出内容后失败只追加
  “回答中断”提示，避免出现“半截 A + 完整 B”；语音转写半截失败主动断流，
  前端回退原文，不把半截结果写进缓存。
- **用量统计改 JSONL**：`data/usage.jsonl` 追加写入，内存保留最近 2000 条；
  旧 `data/usage.json` 自动读取并在下次记账时迁移；PDF 不再把文件字节数算作字数。
- **外部源请求可取消**：总预算结束时关闭在途/迟到的 urllib 响应，线程不再空转到
  自身超时。
- **PDF 自带 KaTeX**：`backend/static/katex/`（含 MIT LICENSE），只部署 backend
  也能渲染公式；导出临时目录改用系统临时目录。
- **`sync_knowledge` 标记后移**：召回评测通过后才推进 `.last_sync`，有问题的批次
  不会被永久跳过。

## 三、前端体验与本地数据

- **退出登录清理本机学习数据**：会话、归纳本、回收站、语音缓存统一清理；确认文案
  已更新。
- **sessions 持久化 debounce**：120ms 合并写；附件发送、离开学习页、
  `beforeunload`/`pagehide` 立即 flush；清空会话会取消待写，避免旧档案被写回。
- **MathText 分块增量渲染**：只在非代码围栏、非 `$$`/`\[`/`\(` 公式块内的空行切块；
  已完成块 props 不变，流式期间只重渲染最后一块。
- **回收站过期清理写回** localStorage，不再“复活”。
- **畸形 `cmd://chapter/%` 链接**安全回退，不再抛 `URIError`。
- **语音转写失败撤回半截输入**；`postSSE` 错误路径只触发一次 `onFail`。

## 四、工程与测试

- 新增后端测试套件 `backend/tests/`（17 个文件：16 个测试模块 + `conftest.py`）与
  `pytest.ini`、`requirements-dev.txt`。
- 新增前端统一测试入口：`npm test`
  （语音编译器、SSE 收尾契约、MathText 渲染/链接安全、回收站/本地数据/会话持久化）。
- 新增 `.github/workflows/ci.yml`：后端 compile + pytest；前端 vue-tsc + test + build。
- 依赖锁定：`starlette==1.6.0`、`uvicorn==0.52.4`、`httpx==0.28.1`、
  `watchfiles==1.2.0`、`pytest==8.4.2`。
- `dev.bat` 使用 `%~sdp0` 短路径，不再写死 `D:\code`。

## 五、验证记录

以下结果在代码快照 `b6d55fc` 上执行：

```text
后端:
  python -m compileall -q .                 通过
  python -m pytest -q                       133 passed
  eval_route.py                             50/50 通过
  eval_recall.py                            60/60 通过（关键词模式）
  import main                               8 条路由正常

前端:
  vue-tsc --noEmit                          通过
  npm test                                  语音 80/80
                                            SSE 17/17
                                            MathText 24/24
                                            存储/本地数据 15/15
  npm run build                             通过（仅 tex2svg 分块 >1800kB 的既有告警）

其他:
  Edge headless 实际渲染 PDF                合法 PDF，包含 KaTeX 字体
  旧 usage.json 兼容读取                    275 calls / 10 users
  git diff --check                          无空白错误
```

## 六、行为变更与配置

| 项目 | 变更 | 默认/迁移 |
| --- | --- | --- |
| `/api/stats` | 仅管理员 | 需配 `MG_ADMIN_PHONES` 或 `MG_ADMIN_UIDS`;不配则 403 |
| 演示登录 | 可关闭 | `MG_DEMO_MODE=1` 默认演示;`0` 关闭固定码/访客/开放注册 |
| 游客账号 | 有上限 | `MG_GUEST_MAX=500`;`0` 禁止;满额清理无 token 的最旧游客 |
| CORS | 默认本机 | `MG_CORS_ORIGINS` 按需扩展 |
| 密码 | PBKDF2 20 万轮 | 旧 SHA-256 登录后自动升级;登录耗时约增加 50–100ms |
| 用量文件 | `usage.json` → `usage.jsonl` | 旧文件自动读取/迁移并保留备份 |
| 本地学习数据 | 退出/换账号清理 | 同账号重登保留;旧版本无归属标记时首次认领不删除 |
| embedding | 缓存键含模型 | 换模型/新机器首次启动会重算一次向量 |
| PDF | 后端自带 KaTeX | 新增 `backend/static/katex/`（1.5MB，含 LICENSE） |

## 七、完整代码与溯源附件

本版本把**完整源码快照**与**完整变更补丁**一并入库，位于 `releases/v1.9.0/`，
也会作为 GitHub Release 资产上传：

| 附件 | 内容 | SHA-256 |
| --- | --- | --- |
| `MathGuide-v1.9.0-source.tar.gz` | **完整源码快照**（210 个文件，1,195,185 字节），由 `git archive` 从代码提交 `b6d55fc` 生成；解压即完整可运行源码 | `3c6c38c75aa6f62ac08209f8220580b9e4ec64e575255c437cb4234c0d1f1053` |
| `v1.9.0.patch` | 相对 `v1.8.0` 的完整二进制安全补丁（1,694,794 字节） | `5e57bb081bdf4a6648b66185cdddcbeebda31a7cd090e6d219892d056b53c2c2` |
| `MANIFEST.sha256` | 源码快照 210 个文件的逐文件 SHA-256（按归档内真实字节生成） | `ad9eaebf2241a1659b31427eef6dd9d40ca26772589e3fdc33bd3fa4bcbd68b9` |
| `SHA256SUMS` | 上述附件 + 校验脚本的 SHA-256 | `0201e3ec1c49a73f925b328472e26e299924f6ce941ed5bc5a38352d5a407fdd` |
| `verify_manifest.py` | 跨平台逐文件校验脚本 | `5e05564aa48880428c447a837bb4a121c63cd63a28897e4c9cd8dbc98480c2c7` |

复核步骤：

```bash
cd releases/v1.9.0
sha256sum -c SHA256SUMS
tar -xzf MathGuide-v1.9.0-source.tar.gz
python verify_manifest.py MathGuide-v1.9.0   # checked=210 failures=0
```

源码包不包含 `.git`、`backend/.env.local`、`backend/data/`、`.venv/`、`node_modules/`
和运行时缓存；这些均被 `.gitignore` 排除。KaTeX 资源的 MIT LICENSE 随包保留。
`releases/**` 在 `.gitattributes` 中标记为 `-text`，clone 后附件字节与校验和不变；
`MANIFEST.sha256` 按源码包内真实字节生成，请以解压后的源码目录为准（Windows 源码
工作树可能因 `core.autocrlf` 为 CRLF，不能直接与清单比对）。

## 八、已知限制

- 历史 `data/usage.json` 中的 `totalChars` 仍为旧口径（按 SSE 帧长度累计），无法
  从旧数据反推真实字数；新记录已按正文准确统计。
- 游客 token 过期后重新登录会生成新的 guest 身份，因此本机数据会按“换账号”清理；
  手机号账号使用稳定 `accountKey`，不受影响。
- `/api/stats` 使用环境变量白名单，不是数据库角色；真实部署建议改为 `role` 字段。
- 单进程 JSON/JSONL 存储与限流：多 worker 部署前需换数据库/Redis。
- `urllib` 取消是“关闭在途响应”的尽力而为；连接阶段（DNS/TCP）仍受自身超时约束。
- MathText 分块对跨空行的极少数 Markdown 结构（如跨段加粗）可能与整段解析略有差异；
  代码围栏与 `$$`/`\[`/`\(` 已明确保护。

## 九、升级步骤

1. 拉取 `v1.9.0`，按 `backend/requirements.txt` / `frontend/package-lock.json` 安装依赖。
2. 在 `backend/.env.local` 按需配置：
   `MG_ADMIN_PHONES`、`MG_GUEST_MAX`、`MG_CORS_ORIGINS`；生产环境设 `MG_DEMO_MODE=0`。
3. 重启后端；首次启动会自动读取旧 `usage.json`，下一次记账时迁移为 `usage.jsonl`。
4. 运行 `python -m pytest` 与 `npm test`（或使用 CI）确认环境。
5. 需要核对发布包时，按第七节命令执行 SHA-256 与逐文件校验。
