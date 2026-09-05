# MathGuide 后端

大模型高等数学学习辅助与科学研究应用 —— 最小后端骨架(演示环境)。

当前为**无真实模型**的最小实现:认证(注册 / 登录 / 登出)走本地 JSON 存储,
聊天回复由 MockLLM(`mockllm.py`)本地知识库生成,经 SSE 逐字流式下发,
用于打通「前端 ↔ SSE ↔ 认证」全链路;接入真实 LLM 时只需替换 `mockllm.build_reply`。

## 启动

```bash
cd backend
D:/code/.venv/Scripts/python.exe -m uvicorn main:app --host 0.0.0.0 --port 8000
# 前端开发模式(5173)已配置 vite 代理 /api → 8000,直连 8000 亦可调试
```

依赖:starlette、uvicorn(见 `requirements.txt`,已装于 `D:/code/.venv`)。

## 目录

```
backend/
  main.py      # 应用入口 + 路由表 + CORS(开发期放行)
  store.py     # JSON 文件持久化(users.json / tokens.json),启动时装载
  auth.py      # 注册 / 登录 / 登出 + require_auth(401)
  chat.py      # POST /api/chat/stream(SSE 流式下发)
  mockllm.py   # 本地模拟回复引擎(替换点:接入真实 LLM 只改这里)
  data/        # 运行时生成:用户与令牌数据(勿入库)
```

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
// 方式一:密码(mock 语义:手机号未注册 → 404 notfound;密码错 → 401 wrong)
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
  `sessionId` / `categoryKey` 随契约接收,当前骨架为**无状态单轮回复**(上下文栈由前端维护)。
- 空 `prompt` 视为新会话,下发欢迎语。
- 响应为 OpenAI 兼容 SSE,**每帧 payload 是 JSON 字符串**(正文含换行、LaTeX 反斜杠时仍为单行,不会拆碎 data 行):

```
data: "好的,先定位知识,"
data: "再给一道经典例题。\n\n"
...
data: [DONE]
```

前端按帧 `JSON.parse`(失败回退纯文本)后拼接即为完整正文。
认证失败:401 `{"detail":"unauthorized"}`。

## 接入真实 LLM

1. 写 `llm.py`:调用外部模型流式接口(OpenAI 兼容 chat completions 即可),
   产出与 `mockllm.build_reply` 同签名同调用的函数(同步生成完整文本,或改造 `chat.py` 透传上游流);
2. `chat.py` 换成对 `llm.build_reply`(或流)的调用 —— 其余代码、前端均无需改动。

## 演示账号

验证码登录演示码固定 `123456`。注册产生的数据落盘于 `data/`(users.json 存加盐口令摘要,
tokens.json 存令牌);清空这两个文件即可重置演示环境。
