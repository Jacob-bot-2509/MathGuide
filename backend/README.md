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
  main.py      # 应用入口 + 路由表 + CORS(开发期放行)
  store.py     # JSON 文件持久化(users.json / tokens.json),启动时装载
  auth.py      # 注册 / 登录 / 登出 + require_auth(401)
  chat.py      # POST /api/chat/stream:SSE 流式下发 + RAG 编排(检索 → LLM / 直答)
  rag/
    documents.py  # 知识文档加载与切片(markdown + frontmatter)
    index.py      # 检索索引(关键词 + 标题 + bigram 重合度打分,零依赖)
    llm.py        # LLM 客户端(OpenAI 兼容流式,环境变量配置)
    __init__.py   # init / search / build_system(进程内单例)
  knowledge/   # 知识库文档(*.md,公式用 LaTeX),新增文档无需改代码
  data/        # 运行时生成:用户与令牌数据(勿入库)
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

## 检索升级(可选):embedding 向量混合

知识量大或需要"换一种说法也能命中"的语义检索时,配置环境变量启用向量混合打分:

```bash
set MG_EMBED_BASE_URL=https://api.deepseek.com/v1
set MG_EMBED_API_KEY=sk-xxxx        # 缺省沿用 MG_LLM_API_KEY
set MG_EMBED_MODEL=text-embedding-3-small
```

- 启用后片段在装载时批量向量化,结果缓存于 `knowledge/.embeddings.json`
  (chunk id 为键,文档改动自动重算),重启不重复计费;
- 检索按「关键词命中 + 向量相似度」混合排序,未配置时行为与纯关键词模式一致;
- 缓存文件请勿入库(已在 .gitignore 排除规则 `*.json` 覆盖范围外时手动排除)。

## 接入真实 LLM

环境变量(无需改代码):

```bash
set MG_LLM_BASE_URL=https://api.deepseek.com/v1   # 任意 OpenAI 兼容服务
set MG_LLM_API_KEY=sk-xxxx
set MG_LLM_MODEL=deepseek-chat                     # 默认 gpt-4o-mini
```

配置后聊天自动切换:检索知识片段 → 组装 system prompt(含资料 + 指令 + 格式约束)
→ 模型流式输出;调用失败自动降级为知识库直答。检索能力升级(如向量 embedding)
只需改 `rag/index.py` 的 `search`,接口不变。

## 接口契约

统一前缀 `/api`;除注册 / 登录外均需请求头 `Authorization: Bearer <token>`。

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/health` | 健康检查 `{ok, service}` |
| POST | `/api/auth/register` | 手机号 + 密码注册 → `200 {token, user}` / `409 {error:"exists"}` |
| POST | `/api/auth/login` | 四种方式,见下 → 一律 `200 {token, user}` |
| POST | `/api/auth/logout` | 吊销当前 token → `200 {ok:true}` |
| POST | `/api/chat/stream` | 聊天流式回复(SSE) |

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
{ "prompt": "什么是导数", "cmd": "例题精讲", "sessionId": 1, "categoryKey": "analysis" }
```

- `cmd` 与前端指令栏对应(概念动画演示 / 例题精讲 / 章节知识导航 / 错题归纳 / 公式查询手册);
  `sessionId` / `categoryKey` 随契约接收,当前为**无状态单轮回复**(上下文栈由前端维护);
- 空 `prompt` 视为新会话,下发欢迎语;难度由后端按问题措辞自动判定(中英文);
- 响应为 OpenAI 兼容 SSE,**每帧 payload 是 JSON 字符串**(正文含换行、LaTeX 反斜杠时仍为单行,不会拆碎 data 行):

```
data: "好的,先定位知识,"
data: "再给一道经典例题。\n\n"
...
data: [DONE]
```

前端按帧 `JSON.parse`(失败回退纯文本)后拼接即为完整正文。
认证失败:401 `{"detail":"unauthorized"}`。

## 演示账号

验证码登录演示码固定 `123456`。注册产生的数据落盘于 `data/`(users.json 存加盐口令摘要,
tokens.json 存令牌);清空这两个文件即可重置演示环境。

## 质检工具(tools/)

```bash
python tools/eval_recall.py    # 知识库召回率评测:54 道多语问法批量测,报告落盘 eval_report.txt
python tools/preflight.py      # 演示前自检:前后端健康 + 登录 + 抽查题端到端,全绿才可演示
python tools/fetch_knowledge.py --source arxiv --limit 20   # 从 arXiv 拉论文摘要入库
```

- **eval_recall**:新增文档后必须重跑,未命中项按报告补 keywords,目标封闭集 100% 命中;
- **preflight**:演示/答辩前 30 秒跑一次,任何环节(服务、账号、知识库、检索)故障立即报红并给出修复提示,
  保证用户实测不翻车;
- **fetch_knowledge**:arXiv 已验证可用(经系统代理),维基源需网络可达维基百科。
