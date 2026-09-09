# MathGuide 后端

大模型高等数学学习辅助与科学研究应用 —— 后端(RAG 检索增强生成骨架)。

认证(注册 / 登录 / 登出)走本地 JSON 存储;聊天采用 RAG 链路:
**知识库(markdown + LaTeX)→ 切片索引 → 检索 → LLM 流式生成**。
未配置 LLM 时自动降级为「知识库直答」模式(直接返回检索到的知识片段),
全链路(前端 ↔ SSE ↔ 认证)始终可演示。

## 启动

```bash
cd backend
D:/code/.venv/Scripts/python.exe -m uvicorn main:app --host 0.0.0.0 --port 8000
# 前端开发模式(5173)已配置 vite 代理 /api → 8000,直连 8000 亦可调试
```

依赖:starlette、uvicorn、httpx(见 `requirements.txt`,已装于 `D:/code/.venv`)。
Windows 下也可用仓库根目录 `dev.bat` 一键启动前后端。

## 目录

```
backend/
  main.py      # 应用入口 + 路由表 + CORS(开发期放行)+ UTF-8 输出修复
  store.py     # JSON 文件持久化(users.json / tokens.json),token 24h 过期
  auth.py      # 注册 / 登录 / 登出 + require_auth(401)
  chat.py      # POST /api/chat/stream:SSE 流式下发 + RAG 编排
               # (安全外壳:输入上限/限流/用量记账 → 路由 → LLM/直答)
  usage.py     # 用量统计(电表):调用记录落盘 usage.json,支撑 /api/stats 与报表
  rag/
    documents.py  # 知识文档加载与切片(markdown + frontmatter)
    index.py      # 检索索引:关键词 + bigram + 向量混合打分(闲聊噪声门限)
    embed.py      # Embedding 客户端(懒加载配置,批量 ≤10,失败自动降级)
    llm.py        # LLM 客户端(双平台四角色,按需路由 + 跨平台容灾)
    route.py      # 问题路由:研究型提问分流(简单应答 vs 深度搜索)
    research/     # 深度搜索:arXiv / Semantic Scholar / OpenAlex / StackExchange
                  # + LLM 查询改写 + 去重打分 + LLM 精排 + 双层缓存
    __init__.py   # init / search / build_system(进程内单例)
  knowledge/   # 知识库文档(*.md,公式用 LaTeX),新增文档无需改代码
  data/        # 运行时生成:用户 / 令牌 / 用量数据(勿入库)
  tools/       # 质检与运维:评测 / 自检 / key 校验 / 知识同步 / 用量报表
```

## 知识库文档格式

往 `knowledge/` 增加 `.md` / `.txt` 文件即自动进入知识库,**无需重启后端**
(下次提问时自动重建索引),无需改代码:

```markdown
---
title: 函数极限
title_en: Limits
keywords: ["极限", "lim", "趋近", "收敛", "converge", "limit"]
category: analysis
---

## 专业表述
设 $f(x)$ 在 $x_0$ 的某去心邻域内有定义,若 ...

## 形象理解
极限衡量的是「逼近的最终去向」……

## 关键结论
$\lim_{x\to 0}\frac{\sin x}{x}=1$ 是一切等价无穷小替换的根基。
```

- `keywords`:中英触发词(JSON 数组,统一小写),参与检索打分;
- `category`:与前端 `utils/classifier.ts` 板块 key 一致
  (analysis / algebra / geometry / ode / probability / complex / topology / other);
- 正文按 `##` 标题切片,单节过长自动按段落再切(公式块不切断);
  公式统一 LaTeX(行内 `$...$`、块级 `$$...$$`),前端 KaTeX 直接渲染。

纯文本资料(讲义 / 笔记)可直接存为 `.txt`:文件名作标题、按空行分段入库,
无需 frontmatter(此时 category 为 other,建议重要资料仍用 md 格式标好板块与关键词)。
PDF / Word 等二进制格式:先转成 md/txt(或后续在 `rag/documents.py` 挂载解析器),格式同上。

### 每日自动同步(增量更新)

`tools/sync_knowledge.py` 只拉「上次同步以来」的 arXiv 论文(按 submittedDate 增量),
且仅收录标题/摘要命中课程主题词的论文(自动入库质检门),拉完自动跑召回率评测,
不过线不发布。同步标记存于 `tools/.last_sync`(不入库)。

Windows 定时任务示例(每天 09:30 自动同步):

```bat
schtasks /Create /TN "MathGuide-KB-Sync" /SC DAILY /ST 09:30 /TR "\"D:\code\.venv\Scripts\python.exe\" \"D:\code\backend\tools\sync_knowledge.py\" --limit 20"
```

## 检索升级(可选):embedding 向量混合

配置环境变量启用向量混合打分(与 LLM 同平台的 key 即可,本项目已启用):

```bash
set MG_EMBED_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
set MG_EMBED_API_KEY=sk-xxx
set MG_EMBED_MODEL=text-embedding-v3
```

深度搜索可选环境变量(不设也可用,设了更稳):

```bash
set MG_S2_API_KEY=xxx      # Semantic Scholar 免费 API key(semanticscholar.org 申请),
                           # 走专属配额,告别公共池 429 限流
set MG_CONTACT_MAIL=xxx@xx.com  # OpenAlex 礼貌池标识(官方建议,提升配额)
```

- 启用后片段在装载时批量向量化(单批 ≤10,阿里云实测上限),结果缓存于
  `knowledge/.embeddings.json`(chunk id 为键,文档改动自动重算),重启不重复计费;
- 检索按「关键词命中 + 向量相似度」混合排序,未配置时行为与纯关键词模式一致;
- **闲聊噪声门限**:纯向量命中(无任何关键词/bigram 证据)需相似度 ≥0.55,
  否则"你好呀"这类话术会以低相似度误命中数学文档;
- **降级保护**:embedding 初始化 / 索引重建 / 单次查询任一环节失败,
  自动退回关键词模式,检索链路永不因向量服务故障崩溃;
- 缓存文件请勿入库(.gitignore 已排除 `knowledge/.embeddings.json`)。

## 接入真实 LLM

复制 `backend/.env.local.example` → `backend/.env.local`(已被 gitignore,key 永不入库),
填入真实 Key 后重启后端即可,无需改代码:

```ini
MG_ALIYUN_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
MG_ALIYUN_API_KEY=sk-xxx            # 阿里云百炼(Qwen 系列)
MG_ZHIPU_BASE_URL=https://open.bigmodel.cn/api/paas/v4
MG_ZHIPU_API_KEY=xxx                # 智谱开放平台(GLM 系列)
MG_ROLE_MAIN=aliyun:qwen3.8-flash   # 主力:日常问答 / 改写 / 复核 / 摘要
MG_ROLE_BACKUP=zhipu:glm-5.2        # 备胎:主力失败自动切换(异平台容灾)
MG_ROLE_DEEP=aliyun:qwen3-235b-a22b # 深答:证明 / 竞赛 / 研究综合
MG_ROLE_LONG=aliyun:qwen-long       # 长文:教材 / 长文档(3 万字级)
```

**角色按需路由**(未配置的角色自动回退 main,链路永不断):
- 证明 / 竞赛类提问 → deep;教材 / 粘贴长文档 → long;研究型综合 → deep;其余 → main;
- 研究型问题:LLM 查询改写(失败回退规则版)→ 跨论文库搜索 → LLM 精排 →
  **综合解答 + 编号引用**,引用区由后端用真实元数据拼装(幻觉防线);
  搜索与综合**双层缓存**,重复问题秒回;
- **双角色验证**:数学题解答完成后由另一角色复核,结论追加在答案末尾(🔍 复核);
- **多轮对话**:携带最近 16 轮历史,更早对话每 8 轮滚动压缩成摘要附在 system 中;
- 解答末尾由后端拼装「是 / 否」收录按钮(契约 `cmd://nb/yes|no`),
  前端据此把题目与解答收纳进问题记录(归纳本);
- 任意环节失败自动降级:综合失败 → 来源列表,精排失败 → 规则排序,全部失败 → 知识库直答。

## 接口契约

统一前缀 `/api`;除注册 / 登录外均需请求头 `Authorization: Bearer <token>`。

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/health` | 健康检查 `{ok, service}` |
| POST | `/api/auth/register` | 手机号 + 密码注册 → `200 {token, user}` / `409 {error:"exists"}` |
| POST | `/api/auth/login` | 四种方式,见下 → 一律 `200 {token, user}` |
| POST | `/api/auth/logout` | 吊销当前 token → `200 {ok:true}` |
| POST | `/api/chat/stream` | 聊天流式回复(SSE) |
| GET | `/api/stats` | 用量统计(需 token):总调用数 / 回复字数 / 按用户 / 按模型角色 |

登录请求体:

```jsonc
// 方式一:密码(手机号未注册 → 404 notfound;密码错 → 401 wrong)
{ "method": "password", "phone": "13800138000", "password": "..." }
// 方式二:验证码(演示码 123456;手机号未注册自动建户)
{ "method": "code", "phone": "...", "code": "123456" }
// 方式三/四:微信 / QQ(访客式 guest 用户,昵称头像由前端模拟授权后携带)
{ "method": "wechat", "nickname": "...", "avatar": "preset:sum" }
```

`user` DTO:`{ nickname, avatar, authMethod: "phone-pass"|"phone-code"|"wechat"|"qq", phone? }`

### 聊天流(SSE)

```jsonc
// POST /api/chat/stream  body:
{ "prompt": "什么是导数", "cmd": "章节知识导航", "sessionId": 1,
  "categoryKey": "analysis", "history": [{"role": "user", "content": "…"}] }
```

- `cmd` 与前端指令栏对应(概念动画演示 / 章节知识导航 / 问题记录 / 公式查询手册);
  `history` 为最近几轮对话(≤16 条 × 400 字,后端校验),多轮上下文由后端组装;
- 空 `prompt` 视为新会话,下发欢迎语;
- **章节导航契约**:`cmd=章节知识导航` 携带教材正文(≤3 万字)→ 返回可点击章节列表
  `[章节](cmd://chapter/…)`,教材按 `sessionId` 缓存;`cmd=章节知识指引` 只发章节名,
  返回指引并附 `[返回](cmd://back)`(缓存失效时按通用知识作答);
- **附件契约**:`[attach:image|file]文件名`,文本文件可带正文(空行分隔)交 LLM 阅读理解;
- **安全底座**:prompt 服务端截断 3.2 万字;每用户 60 秒内最多 6 问(超出 429);
  token 24 小时过期;每次调用自动记账(用量统计见下);
- 响应为 OpenAI 兼容 SSE,**每帧 payload 是 JSON 字符串**(正文含换行、LaTeX 反斜杠时仍为单行,不会拆碎 data 行):

```
data: "好的,先定位知识,"
data: "再给一道经典例题。\n\n"
...
data: [DONE]
```

前端按帧 `JSON.parse`(失败回退纯文本)后拼接即为完整正文。
认证失败:401 `{"detail":"unauthorized"}`;限流:429 `{"detail":"rate limited"}`。

## 用量统计(测试期成本可见)

每次聊天流结束后自动记账到 `data/usage.json`(谁、什么指令、回复字数、模型角色;
上限 2000 条,超量丢最旧):

```bash
python tools/usage.py   # 终端报表:总调用/回复字数/按用户/按模型角色
# 或接口查询(需登录 token):GET /api/stats → {calls, totalChars, users, roles}
```

## 演示账号

验证码登录演示码固定 `123456`。注册产生的数据落盘于 `data/`(users.json 存加盐口令摘要,
tokens.json 存令牌);清空这两个文件即可重置演示环境。

## 质检工具(tools/)

```bash
python tools/check_keys.py      # LLM Key 快速校验(不打印 key 内容,两把都 ✓ 才可跑真机)
python tools/sync_knowledge.py  # 知识库每日同步一条龙:增量拉取(课程词过滤)→ 召回评测 → 报告
python tools/eval_recall.py    # 知识库召回率评测:55 道多语问法批量测,报告落盘 eval_report.txt
python tools/eval_route.py     # 路由分流评测:50 用例四路(研究/知识/框架/会话)
python tools/eval_search.py    # 深度搜索评测:10 道研究型问题(网络依赖,单源失败不影响整体)
python tools/preflight.py      # 演示前自检:前后端健康 + 登录 + 抽查题端到端,全绿才可演示
python tools/fetch_knowledge.py --source arxiv --limit 20   # 从 arXiv 拉论文摘要入库
python tools/usage.py          # 用量报表:总调用 / 回复字数 / 按用户 / 按模型角色
```

- **eval_recall**:新增文档后必须重跑,未命中项按报告补 keywords,目标封闭集 100% 命中;
- **preflight**:演示/答辩前 30 秒跑一次,任何环节(服务、账号、知识库、检索)故障立即报红并给出修复提示,
  保证用户实测不翻车;
- **fetch_knowledge**:arXiv 已验证可用(经系统代理),维基源需网络可达维基百科。
