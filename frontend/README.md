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

Vue 3 + Vite + TypeScript + vue-router + GSAP + KaTeX + MathJax(SVG 输出)

## 目录

```
src/
  api/          # 接口层(后端接入唯一入口)
  │ types.ts    #   前后端接口契约:消息/流式回调/认证结构
  │ http.ts     #   fetch 封装 + OpenAI 兼容 SSE 流解析
  services/     # 业务服务:页面唯一依赖,mock ↔ 真实接口的切换开关
  │ chatService.ts / authService.ts
  mock/         # 演示环境模拟实现(后端接入后废弃)
  │ assistant.ts #   双轨讲解 Mock 回复 + 逐字流式输出
  │ accounts.ts  #   Mock 账号库
  stores/       # 全局状态:user(登录态)/ settings(应用设置)
  utils/        # 纯工具:toast / tex2svg / classifier / commands / avatar
  components/
  ├─ common/    # Starfield、UserAvatar、ModulePlaceholder
  └─ chat/      # MathText、MathFormula、CategoryPanel
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
- `.env.local`(`VITE_USE_MOCK=false`)已把登录与聊天切换到真实接口;
  删除该文件并重启 dev server 即回到纯 Mock 演示模式;
- 登录令牌存于登录态(内存 + localStorage 刷新保持),令牌失效(401)时自动回登录页;
- `src/api/http.ts` 解析 OpenAI 兼容 SSE,**每帧 payload 为 JSON 字符串**(兼容纯文本),
  正文中的 `\n` 由后端转义,流式拼接无丢字;
- 聊天接口当前为后端无状态单轮回复(上下文栈仍由前端会话系统维护);
  替换 MockLLM 为真实模型只需改 `backend/mockllm.py`,前端无需改动。

## 功能说明

- **开场动画**:MG 故障闪现(RGB 分裂 + 乱码解码)→ 环绕公式逐笔描边书写。
  公式用 MathJax SVG 输出(字形是 path,可逐笔动画);
  聊天正文公式用 KaTeX(渲染快,适合流式输出)。
- **学习辅助**:一体化智能答疑对话。六个模块已合并:
  智能答疑是对话本身,其余五个模块(概念动画演示 / 例题精讲 /
  章节知识导航 / 错题归纳 / 公式查询手册)是指令栏指令,点击即执行
  (指令栏位于输入框下方)。
- **问题归纳系统 + 多会话(上下文栈)**:
  - 每个用户问题自动分类到高等数学大板块(数学分析 / 高等代数 /
    空间解析几何 / 拓扑学 / 微分方程 / 概率论与数理统计 / 复变函数),
    分类器见 `lib/classifier.ts`,后端接入后可替换为模型分类。
  - 同板块问题延续当前会话;检测到不同类型的问题时,检索同板块
    旧会话并切回(上下文栈),否则新开会话 —— 避免不同类型问题相互纠缠。
  - 会话持久化到 localStorage(记忆功能,刷新不丢失);
    问题归纳面板按板块显示问题数量,点击问题跳回当时所在的对话。
  - 如需重置历史:浏览器控制台执行 `localStorage.removeItem('mg-learn-sessions')`。
- **Mock 流式回复**:逐字输出模拟真实 SSE 流,后端接入后仅需替换
  `streamMockReply` 的实现,界面层无需改动。

## 开发阶段

① 开场动画 ② 页面框架与动效 ③ 学习辅助界面 ④ 科学研究界面
⑤ 账号体系:登录(手机号+密码 / 手机号+验证码 / 微信 / QQ,
微信与 QQ 为演示环境模拟授权,支持创建账户)、设置中心(账号管理 /
隐私与安全 / 语言 / 外观 / 关于 / 退出登录 / 回收站)、头像自选
(预设 + 相册上传,需相册授权)、聊天页语音输入(浏览器本地识别)与
模型语音回复开关(待开发)、浅色主题(全站含开机动画)。
⑥ 国际化(进行中):设置 → 语言 支持简体中文 / English,界面即时切换;
词典在 `utils/i18n.ts`,Mock 助手回复双语输出,中英文关键词均可命中。

用户与设置数据仅存于本机 localStorage,接入后端后由真实账号接口替换。
