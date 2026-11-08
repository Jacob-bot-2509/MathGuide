# 技术选型说明（申请书方案 vs 实际实现）

本文用于结题材料与答辩：说明申请书中的技术方案在实现期做了哪些调整、为什么调整、
调整后如何验证。原则是“目标不变，约束变化，收益可验证”。

## 总览

| 申请书 | 实际实现 | 状态 | 说明 |
|---|---|---|---|
| Flask | Starlette + Uvicorn | 替换 | 流式长连接与异步 I/O 需要 ASGI |
| SQLite | SQLite（`data/mathguide.db`） | 已落实 | 用户、令牌、用量、诊断同库，事务 + 索引 + WAL |
| Streamlit | Vue 3 + Vite 主站；可选 Streamlit 只读看板 | 替换 + 补充 | 主站需要流式、画布交互、PDF 阅读器 |
| NetworkX + Pyvis | NetworkX 后端布局 + Pyvis HTML 导出 + 前端 SVG 渲染 | 已落实 | 布局与导出用 NetworkX/Pyvis，交互仍由自绘 SVG 承担 |
| DeepSeek API | 多平台角色路由，DeepSeek 已支持 | 已落实 | 配置 `MG_DEEPSEEK_API_KEY` 即可启用 |

## 1. Flask → Starlette + Uvicorn

**原因**：问答主链路是 SSE 流式输出，检索、模型调用、embedding 都是慢 I/O。
Flask（WSGI）同步模型下每个长连接占一个线程；Starlette（ASGI）原生 `await`，
同步检索用线程池隔离，不阻塞事件循环。

**收益**：并发会话互不拖慢；首字延迟与流式收尾可控；无需为了异步再引 gevent。

**代价与替代**：中间件（CORS、安全头、限流、请求体上限）需自行实现。项目已实现
并有测试覆盖；SSE 收尾契约有 17 项前端断言。

**结论**：不采用 Flask。若评审要求，可解释为“原型方案 → 流式约束 → ASGI”。

## 2. SQLite

**实现**：
- 库文件 `backend/data/mathguide.db`，WAL 模式，`busy_timeout=10s`。
- 表：`users`（手机号唯一索引）、`tokens`（SHA-256 键，uid 索引）、
  `usage`（uid/ts 索引）、`diagnoses`（uid + 知识点索引）。
- 账号删除、令牌吊销、游客清理在单事务内完成。
- 旧 `users.json` / `tokens.json` / `usage.json(l)` / `diagnoses.jsonl`
  首次建库导入一次，旧文件保留备份；导入与完成标记在同一事务内。
- 迁移遇到损坏文件或读取失败会停止并保留原文件，修复后重启重试（不带着半份数据启动）。
- 实测：真实旧数据迁移 51 用户 / 596 条用量 / 2 条诊断成功。

**收益**：事务、索引、并发保护；账号导出/注销不再全量重写 JSON。

**代价**：多一层 SQL 与迁移逻辑；备份/恢复需连同 `-wal`/`-shm`。

## 3. Streamlit → Vue 3 + Vite（+ 可选看板）

**原因**：Streamlit 每次交互重跑脚本，无法支撑逐字流式、图谱缩放拖拽、
PDF 阅读器、表格编辑、论文窗口动作等交互。

**收益**：19 套前端自测覆盖 SSE、公式渲染、图谱布局、论文动作协议等；
构建产物可按 CSP 部署。

**补充**：保留一个只读 Streamlit 看板（`tools/dashboard.py`），用于运维查看
账号、令牌、用量与薄弱点；主站不依赖 Streamlit。

## 4. NetworkX + Pyvis

**实现**：
- `backend/graph_layout.py`：NetworkX 构图，最长路径分层 + 重心法排序，
  输出固定像素坐标；不使用随机布局，同一份图输出完全一致。
- `/api/graph` 返回 `x/y/level`；前端优先使用后端坐标，缺失时退回本地布局。
- `/api/graph/export`：Pyvis 生成独立 HTML（vis 资源内联、按掌握度着色），
  可从图谱页导出分享。
- 前端仍用 SVG 渲染，保留掌握度着色、章节聚焦、搜索、详情与推荐联动。

**收益**：布局算法可单测、可复现；导出文件可离线打开；交互不被 iframe 限制。

## 5. DeepSeek

**实现**：`rag/llm.py` 的 `_providers()` 增加 `deepseek`，默认
`https://api.deepseek.com/v1`；只配 `MG_DEEPSEEK_API_KEY` 即可把任一角色
指向 `deepseek:<model>`。`tools/check_keys.py` 按角色校验 aliyun / zhipu / deepseek。

**收益**：第三家供应商，异平台容灾与异源复核更稳。

**说明**：当前账号阿里云 qwen 文本模型未开通（403），主链路使用智谱 GLM，
备胎使用阿里云 omni；DeepSeek 需自备 key。

## 验证方式

```bash
cd backend
../.venv/Scripts/python.exe -m pytest        # 后端 829 通过 / 1 跳过
cd ../frontend && npm test && npm run build  # 前端全部套件与构建
```

检索与问答指标见 `docs/EVAL_REPORT.md`；技术栈变化的答辩口径见本文各节“原因/收益/代价”。
