# MathGuide 后端

大模型高等数学学习辅助与科学研究应用 —— 后端(RAG 检索增强生成骨架)。

认证(注册 / 登录 / 登出)走本地 JSON 存储;聊天采用 RAG 链路:
**知识库(markdown + LaTeX)→ 切片索引 → 检索 → LLM 流式生成**。
未配置 LLM 时自动降级为「知识库直答」模式(直接返回检索到的知识片段),
全链路(前端 ↔ SSE ↔ 认证)始终可演示。

## 启动

```bash
cd backend
# 演示模式只允许本机:--host 0.0.0.0 会被拒绝启动;公网部署必须 MG_DEMO_MODE=0
../.venv/Scripts/python.exe -m uvicorn main:app --host 127.0.0.1 --port 8000
# 前端开发模式(5173)已配置 vite 代理 /api → 8000,直连 8000 亦可调试
```

依赖:starlette、uvicorn、httpx(见 `requirements.txt`,已装于仓库根的 `.venv`)。
Windows 下也可用仓库根目录 `dev.bat` 一键启动前后端(脚本按自身所在目录解析路径,不再依赖 `D:\code`)。

开发测试依赖:

```bash
../.venv/Scripts/python.exe -m pip install -r requirements-dev.txt
../.venv/Scripts/python.exe -m pytest
```

## 目录

```
backend/
  main.py      # 应用入口 + 路由表 + CORS(默认只放行本机前端)+ UTF-8 输出修复
  store.py     # JSON 持久化 + PBKDF2 密码哈希(旧格式登录时自动升级),token 24h 过期,账号删除级联 token
  auth.py      # 注册 / 登录 / 登出 / 数据导出 / 注销 + require_auth(401) / require_admin(403) + 认证限流
  session_cache.py # 教材/摘要缓存,键 = (uid, sessionId),防止跨用户撞号
  http_utils.py    # JSON 请求体解析:2 MiB 上限(413)与 400 语义
  rate_limit.py    # 滑动窗口限流(聊天/认证共用,自动清理不活跃 key)
  chat.py      # POST /api/chat/stream:SSE 流式下发 + RAG 编排
               # (安全外壳:输入上限/限流/用量记账 → 路由 → LLM/直答)
  usage.py     # 用量统计(电表):按 uid 记账、旧记录 PII 迁移、按账号导出/删除
  rag/
    documents.py  # 知识文档加载与切片(markdown + frontmatter)
    index.py      # 检索索引:关键词 + bigram + 向量混合打分(闲聊噪声门限)
    embed.py      # Embedding 客户端(懒加载配置,批量 ≤10,失败自动降级)
    llm.py        # LLM 客户端(双平台四角色,按需路由 + 跨平台容灾)
    route.py      # 问题路由:研究型提问分流(简单应答 vs 深度搜索)
    research/     # 深度搜索:arXiv / zbMATH / Semantic Scholar / OpenAlex / StackExchange
                  # + LLM 查询改写 + 按源构造检索串 + 去重打分 + LLM 精排 + 双层缓存
                  # + 搜索范围(scope:前端勾选平台,未勾选的不发请求)
    __init__.py   # init / search / build_system(进程内单例)
  knowledge/   # 知识库文档(*.md,公式用 LaTeX),新增文档无需改代码
  static/katex/ # PDF 导出用的 KaTeX 资源(后端自带,不依赖前端 node_modules)
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
  (analysis / algebra / numberTheory / geometry / ode / probability / complex / topology / other);
  该字段是**文档归属标记**,检索不按它过滤(召回由关键词/向量决定);
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
schtasks /Create /TN "MathGuide-KB-Sync" /SC DAILY /ST 09:30 /TR "\"C:\path\to\MathGuide\.venv\Scripts\python.exe\" \"C:\path\to\MathGuide\backend\tools\sync_knowledge.py\" --limit 20"
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
- **闲聊噪声门限**:无关键词证据、纯靠语义相似度的命中需 ≥0.60,否则"你会什么""这道题怎么解"
  这类问句会以 0.4~0.57 的相似度误命中数学文档,把闲聊答成知识直答;
  门限按当前 embedding 模型实测分布标定(**换模型必须重标**,见 `rag/index.py` 注释);
- **降级保护**:embedding 初始化 / 索引重建 / 单次查询任一环节失败,
  自动退回关键词模式,检索链路永不因向量服务故障崩溃;
- **知识库容错**:单个 md/txt 文件解析失败(编码/占用/frontmatter 畸形)只跳过该文件;
  全部不可读时以空索引启动(检索走通用知识),不阻断后端;
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
MG_ROLE_DEEP=aliyun:qwen3.8-max     # 深答:证明 / 竞赛 / 研究综合
MG_ROLE_LONG=aliyun:qwen-long       # 长文:教材 / 长文档(3 万字级)
```

**角色按需路由**(未配置的角色自动回退 main,链路永不断):
- 证明 / 竞赛类提问 → deep;教材 / 粘贴长文档 → long;研究型综合 → deep;其余 → main;
- 研究型问题:LLM 查询改写(失败回退规则版)→ 跨论文库搜索 → LLM 精排 →
  **综合解答 + 编号引用**,引用区由后端用真实元数据拼装(幻觉防线);
  搜索与综合**双层缓存**,重复问题秒回;外部源请求带总预算,超时会关闭在途响应,
  不让线程空转到各自超时;
- **双角色验证**:数学题解答完成后由另一角色复核,结论追加在答案末尾(🔍 复核);
- **多轮对话**:携带最近 16 轮历史,更早对话每 8 轮滚动压缩成摘要附在 system 中;
- 解答末尾由后端拼装「是 / 否」收录按钮(契约 `cmd://nb/yes|no`),
  前端据此把题目与解答收纳进问题记录(归纳本);
- 任意环节失败自动降级:综合失败 → 来源列表,精排失败 → 规则排序,全部失败 → 知识库直答。

## 接口契约

统一前缀 `/api`;除健康检查、注册、登录外均需请求头 `Authorization: Bearer <token>`。

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/health` | 健康检查 `{ok, service}`(公开) |
| POST | `/api/auth/register` | 手机号 + 密码注册(`demo=1` 或带 `invite` 邀请码)→ `200 {token, user}` / `403 {error:"invite"}` / `409 {error:"exists"}` |
| POST | `/api/auth/login` | 四种方式,见下 → 一律 `200 {token, user}` |
| POST | `/api/auth/logout` | 吊销当前 token 并清理该用户会话缓存 → `200 {ok:true}` |
| POST | `/api/account/export` | 导出账号与用量元数据 → `200 {exportedAt, account, usage}` |
| POST | `/api/account/delete` | 注销账号(密码或 `confirm` 二次确认),级联删 token/用量 → `200 {ok:true}` |
| POST | `/api/chat/stream` | 聊天流式回复(SSE) |
| POST | `/api/speech/math` | 语音识别文本 → 数学符号转写(SSE) |
| POST | `/api/doc/export` | 研究综述 → 结构化 → PDF 下载 |
| GET | `/api/stats` | 用量统计(**仅管理员**):总调用数 / 回复字数 / 按 uid / 按模型角色 |

登录请求体:

```jsonc
// 方式一:密码(手机号未注册 → 404 notfound;密码错 → 401 wrong)
{ "method": "password", "phone": "13800138000", "password": "..." }
// 方式二:验证码(演示码 123456;手机号未注册自动建户)
{ "method": "code", "phone": "...", "code": "123456" }
// 方式三/四:微信 / QQ(访客式 guest 用户,昵称头像由前端模拟授权后携带)
{ "method": "wechat", "nickname": "...", "avatar": "preset:sum" }
```

`user` DTO:`{ nickname, avatar, authMethod: "phone-pass"|"phone-code"|"wechat"|"qq", phone?, accountKey }`

`accountKey` 是内部 uid 的不可逆哈希,前端只用它判断本机学习数据属于哪个账号:
换账号登录时清理上一位用户的本地会话/归纳本,同一账号重新登录则保留。

### 安全与部署模式

- **演示模式**:`MG_DEMO_MODE` 默认 `1`,允许固定验证码 `123456`、微信/QQ 访客登录
  与开放注册。固定验证码对**已注册手机号**同样有效,开放注册也无法验证手机号归属,
  只适合本机演示;真实部署必须设 `MG_DEMO_MODE=0`(关闭固定验证码、访客登录与
  `/register`),账号由真实短信/第三方流程或管理端创建,并配合 HTTPS。
  游客账号受 `MG_GUEST_MAX`(默认 500,0=禁止)约束,超出时先清理无有效 token 的最旧游客。
- **演示模式守卫**:`MG_DEMO_MODE=1` 时只允许绑定 `127.0.0.1` / `localhost` / `::1`,
  CORS 也只能是本机来源;`--host 0.0.0.0`、公网 CORS 或 `*` 会直接拒绝启动。
  公网部署必须显式 `MG_DEMO_MODE=0`(反向代理场景无法仅靠绑定地址识别)。
- **CORS**:默认只放行 `http://localhost:5173` 与 `http://127.0.0.1:5173`;
  其他来源用 `MG_CORS_ORIGINS` 显式列出,不要长期使用 `*`。
- **管理员**:`/api/stats` 需要手机号或 uid 命中 `MG_ADMIN_PHONES` / `MG_ADMIN_UIDS`
  白名单;未配置则默认无人可访问(403)。
- **请求体上限**:所有 JSON 接口 2 MiB,超限 413;昵称/头像/密码等字段另有长度上限。
- **认证限流**:登录/注册按客户端 IP 60 秒 10 次;聊天/语音/导出按用户 60 秒 6 次。
  反向代理部署时需让 uvicorn 正确获取客户端 IP(`--proxy-headers` 且仅信任自家代理),
  否则所有请求会被当成同一个 IP。
- **密码**:新账号用 PBKDF2-HMAC-SHA256(20 万轮);旧版单轮 SHA-256 记录在登录成功后
  自动升级,并全程用 `secrets.compare_digest` 比较。
- **token 落盘**:`tokens.json` 只存 token 的 SHA-256(`sha256:` 前缀),不存明文;
  旧明文键在启动时自动迁移,已签发 token 不需要重新登录。
- **测评注册**:`MG_DEMO_MODE=0` 后开放注册关闭;配置 `MG_INVITE_CODES` 后,
  持邀请码的手机号仍可注册。固定验证码与游客登录保持关闭。
- **认证限流**:`MG_AUTH_RATE_MAX` / `MG_AUTH_RATE_WINDOW` 可调;多人共用出口 IP 时调大。
- **留存清理**:`MG_ACCOUNT_TTL_DAYS` 删除长期未登录账号(管理员白名单保留),
  `MG_USAGE_TTL_DAYS` 清理过期用量;默认 `0` 关闭,启动时执行。
- **安全响应头**:API 统一加 `X-Content-Type-Options` / `Referrer-Policy` /
  `X-Frame-Options` / `Permissions-Policy`;HTTPS 或 `MG_ENABLE_HSTS=1` 时加 HSTS。
- **前端 CSP 与反代**:见仓库 `deploy/Caddyfile` / `deploy/nginx.conf`;前端主题脚本已拆成
  `theme-init.js`,CSP 不需要放开 `script-src 'unsafe-inline'`。
- **会话缓存**:教材/滚动摘要按 `(uid, sessionId)` 隔离;`sessionId` 由客户端提供,
  绝不能当作全局唯一键使用。
- **账号数据**:`POST /api/account/export` 导出账号与用量元数据(不含口令/令牌);
  `POST /api/account/delete` 需要当前密码(验证码/第三方账号需输入 `DELETE`/`注销`),
  删除账号、全部 token 与该账号用量记录。前端同时清理本机学习数据。

### 聊天流(SSE)

```jsonc
// POST /api/chat/stream  body:
{ "prompt": "什么是导数", "cmd": "章节知识导航", "sessionId": 1,
  "categoryKey": "analysis", "sources": ["arXiv", "zbMATH"],
  "history": [{"role": "user", "content": "…"}] }
```

- `cmd` 与前端指令栏对应(概念动画演示 / 章节知识导航 / 问题记录 / 公式查询手册 / 搜索范围);
  `history` 为最近几轮对话(≤16 条 × 400 字,后端校验),多轮上下文由后端组装;
- `categoryKey` 为前端板块预判,**后端不消费**:四路裁决(研究/知识/框架/会话)由
  `rag/route.py` 依问句判定,板块只用于前端会话归并与归纳面板,字段作契约预留;
- `sources` 为研究型提问的检索范围(平台名,取值见 `rag/research` 源注册表);
  缺省 / 空 / 非法值一律视为全平台,白名单外的名字直接忽略;
- 空 `prompt` 视为新会话,下发欢迎语;
- **章节导航契约**:`cmd=章节知识导航` 携带教材正文(≤3 万字)→ 返回可点击章节列表
  `[章节](cmd://chapter/…)`,教材按 `(用户, sessionId)` 缓存;`cmd=章节知识指引` 只发章节名,
  返回指引并附 `[返回](cmd://back)`(缓存失效时按通用知识作答);
- **附件契约**:`[attach:image|file]文件名`,文本文件可带正文(空行分隔)交 LLM 阅读理解;
- **续写契约**:`resume: true` + `partial: 已生成正文`,配合 `prompt` 原问题使用;
  走后端专用续写分支,不重新检索/复核,只输出断点后的内容(最多取正文末尾 24000 字);
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

**收尾标记是契约的一部分**:正常完成的流(含各正常降级分支)都以 `data: [DONE]` 结束,
由 `chat.py` 的 `_sse` 统一补发,生成器不必也不能自己 yield(重复的会被丢弃)。
前端据此判断回答是否完整 —— 没等到 `[DONE]` 就断开(后端重启、网络中断)时,
已收到的正文只是半截,界面会标「回答已中断」,不会当成完整回答存进历史。
语音转写是例外:若已输出半截再失败,会主动中断流(不补原文、不补 `[DONE]`),
让前端回退原文,避免半截转写写进本地缓存。
改后端时若绕过 `_sse` 直接返回 `StreamingResponse`,这条判定就失效了。

## 用量统计(测试期成本可见)

每次聊天流结束后自动记账到 `data/usage.jsonl`(**只记 uid**,不记手机号/昵称;
字段:时间、指令、字符数、模型角色;内存保留最近 2000 条,磁盘追加写入、超过 2200 行时
压实一次;兼容旧 `data/usage.json` 数组并在下次写入时迁移,旧文件保留作备份但会先清洗 phone/user)。
服务启动时 `usage.migrate_identity()` 会把 JSONL 与 `usage.json` 备份里的 `phone`/`user` 都换成 uid 并删除 PII。
PDF 导出只记调用次数,不把文件字节数混进「回复字数」:

```bash
../.venv/Scripts/python.exe tools/usage.py   # 终端报表:总调用/回复字数/按账号/按模型角色
# 或接口查询(需管理员 token):GET /api/stats → {calls, totalChars, users, roles}
```

## 测试

```bash
../.venv/Scripts/python.exe -m pytest        # 后端单元/集成测试(不读 .env、不联网)
cd ../frontend && npm test                   # 前端自测(编译器/SSE/MathText 安全用例)
```

后端测试覆盖:store 密码/token 哈希与生命周期、账号删除、auth 注册/登录/邀请码/
演示模式/管理员/限流/游客上限/数据导出/注销、演示模式部署守卫、安全响应头、
请求体 413/400、会话缓存跨用户隔离、embedding 冷启动降级、LLM 半截输出不回放、
文档切片、排序/精排、arXiv HTTPS/响应上限/请求取消、usage JSONL 迁移/PII 清洗/压实、
留存 TTL 清理、PDF 消毒。

## 演示账号

验证码登录演示码固定 `123456`(仅 `MG_DEMO_MODE=1` 且本机绑定时可用)。注册产生的数据
落盘于 `data/`(users.json 存加盐口令摘要,tokens.json 存令牌);清空这两个文件即可重置演示环境。
`tools/preflight.py` 在演示账号不存在时会自动注册,新 clone 也能直接自检。

## 质检工具(tools/)

以下命令在 `backend/` 目录执行;请使用项目 venv(先激活 `.venv`,或把 `python`
换成 `..\.venv\Scripts\python.exe`):

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
