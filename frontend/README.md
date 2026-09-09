# MathGuide 前端

大模型高等数学学习辅助与科学研究应用 —— 前端工程。
黑色科幻主题,MG 标志以"故障乱码"风格开场。

## 运行

```bash
npm install
npm run dev       # 开发服务器 http://localhost:5173
npm run build     # 类型检查 + 构建
npm run preview   # 预览构建产物
```

开场动画同一会话内只播放一次,URL 加 `?replay=1` 可强制重播;
动画结束需点击 CONTINUE 进入首页(不自动跳转)。

## 技术栈

Vue 3 + Vite + TypeScript + vue-router + GSAP + KaTeX + MathJax(SVG 输出) + pdfjs-dist(PDF 文本提取)

## 目录

```
src/
  api/          # 接口层(后端接入唯一入口)
  │ types.ts    #   前后端接口契约:消息/流式回调/认证结构
  │ http.ts     #   fetch 封装 + OpenAI 兼容 SSE 流解析
  services/     # 业务服务:页面唯一依赖(全部走真实后端)
  │ chatService.ts / authService.ts
  stores/       # 全局状态:user / settings / sessions(会话栈)
  │ notebook.ts #   问题记录(归纳本)
  utils/        # 纯工具:toast / tex2svg / classifier / commands / avatar
  │ speechTips.ts # 语音念法速查贴士数据(中英双语)
  components/
  ├─ common/    # Starfield、UserAvatar、ModulePlaceholder
  └─ chat/      # MathText、MathFormula、CategoryPanel、SpeechTips
  views/        # 页面;settings/ 下为设置中心与子页
  router/       # 路由(含登录守卫)
  styles/       # tokens.css 设计令牌 + base.css 全局样式
```

路径别名 `@` → `src/`。

## 后端对接(已完成的最小集成)

本地后端骨架位于 `../backend`(starlette + uvicorn + 本地 JSON 存储),契约见
`backend/README.md`。运行方式:

```bash
# 终端 1:后端(8000)
cd ../backend && D:/code/.venv/Scripts/python.exe -m uvicorn main:app --host 0.0.0.0 --port 8000
# 终端 2:前端(5173)
npm run dev
```

Windows 下也可直接双击仓库根目录的 `dev.bat` 一键拉起两个服务
(后端无 --reload,改动后端代码后需重启后端窗口;前端为热更新)。

- 开发期由 vite 代理把 `/api` 转发到 `http://127.0.0.1:8000`(见 `vite.config.ts`);
- 登录与聊天全部走真实后端(LLM 平台密钥在 `backend/.env.local` 配置,见 `backend/.env.local.example`);
- 登录令牌存于登录态(内存 + localStorage 刷新保持),令牌失效(401)时自动回登录页;
- `src/api/http.ts` 解析 OpenAI 兼容 SSE,**每帧 payload 为 JSON 字符串**(兼容纯文本),
  正文中的 `\n` 由后端转义,流式拼接无丢字;
- 聊天请求携带最近几轮历史(多轮上下文),会话上下文栈由前端会话系统维护。

## 功能说明

- **开场动画**:MG 故障闪现(RGB 分裂 + 乱码解码)→ 环绕公式逐笔描边书写。
  公式用 MathJax SVG 输出(字形是 path,可逐笔动画);
  聊天正文公式用 KaTeX(渲染快,适合流式输出)。
- **学习辅助**:一体化智能答疑对话。智能答疑是对话本身,其余四个模块
  (概念动画演示 / 章节知识导航 / 问题记录 / 公式查询手册)是指令栏指令,点击即执行
  (指令栏位于输入框下方)。
- **章节知识导航(交互化)**:上传/拖入/粘贴教材(txt/md/PDF)→ 点指令一键划分
  章节列表(胶囊按钮)→ 点章节出该章知识指引 → 末尾右对齐黄色「返回」框跳回列表;
  已讲解章节直接跳转不重复生成。
- **问题记录(归纳本)**:数学题解答完成后末尾弹出「是 / 否」按钮,点「是」把题目
  与解答(含参考思路)收纳成档(不分类);点「问题记录」指令展示归纳本,
  点击题目跳回原问答温故知新。一次性提问若干题 → 统一收纳在一个档。
- **文件导入三通道**:本地选择 / 桌面拖拽(电脑端)/ 剪贴板粘贴导入(移动端);
  文本与 PDF 自动提取正文交 LLM 阅读理解,扫描版 PDF 友好提示。
- **语音输入 + 念法速查**:点一下麦克风开始、再点一下完成(期间其他操作不打断);
  语音中麦克风旁弹出📓本子图标,点开查看数学符号标准念法(中英双语切换)。
- **问题归纳系统 + 多会话(上下文栈)**:
  - 每个用户问题自动分类到高等数学大板块(数学分析 / 高等代数 /
    空间解析几何 / 拓扑学 / 微分方程 / 概率论与数理统计 / 复变函数),
    分类器见 `utils/classifier.ts`(关键词预判,后端路由做最终裁决)。
  - 同板块问题延续当前会话;检测到不同类型的问题时,检索同板块
    旧会话并切回(上下文栈),否则新开会话 —— 避免不同类型问题相互纠缠。
  - 会话持久化到 localStorage(记忆功能,刷新不丢失);
    问题归纳面板按板块显示问题数量,点击问题跳回当时所在的对话。
  - 如需重置历史:浏览器控制台执行 `localStorage.removeItem('mg-learn-sessions')`。
- **LLM 流式回复**:后端转发模型增量(SSE),前端增量节流上屏;流式期间
  贴底自动跟随、上拉阅读不抢滚;生成中发送键变「停止生成」(保留已生成内容);
  研究型问题回答末尾附小字引用区(可点击跳转);数学题解答末尾附🔍复核结论与
  「是 / 否」收录按钮(交互契约 `cmd://…`,MathText 渲染,点击冒泡统一处理)。
- **多轮对话**:请求携带最近 16 轮历史,更早对话由后端滚动摘要压缩,长对话不丢上下文。

## 开发阶段

① 开场动画 ② 页面框架与动效 ③ 学习辅助界面 ④ 科学研究界面
⑤ 账号体系:登录(手机号+密码 / 手机号+验证码 / 微信 / QQ,
微信与 QQ 为演示环境模拟授权,支持创建账户)、设置中心(账号管理 /
隐私与安全 / 语言 / 外观 / 关于 / 退出登录 / 回收站)、头像自选
(预设 + 相册上传,需相册授权)、聊天页语音输入(浏览器本地识别)与
模型语音回复开关(待开发)、浅色主题(全站含开机动画)。
⑥ 国际化:设置 → 语言 支持简体中文 / English,界面即时切换;
词典在 `utils/i18n.ts`,中英文关键词均可命中。

账号数据存于后端(backend/data,JSON 存储);会话档案、问题记录归纳本与设置存于本机 localStorage
(keys:`mg-learn-sessions` / `mg-notebook`)。
