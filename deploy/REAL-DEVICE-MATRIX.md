# 真机适配与修补记录

最后一次更新:2026-11-22
范围:MathGuide 在手机、平板上的布局、图解、双语界面与知识图谱真机验证。
状态口径:
- **已修**:代码已改,且在对应设备上复测通过。
- **待复测**:代码已改,记录里没有该设备的最终确认。
- **待补**:缺少机型、系统或浏览器版本,不能作为正式兼容性矩阵。

## 0. 当前本机调试入口(2026-11-22)

- HTTPS:`https://172.30.43.234:5173`(校园网)
- 备用:`https://192.168.137.55:5173`(电脑 WLAN/热点网段,证书已含该 IP)
- CA 下载:`http://172.30.43.234:8080/mkcert-rootCA.crt`(临时本地服务,装完可停)

之前设备语音不工作,是因为 Vite 被以 `--host 0.0.0.0` 启动但没有带 `MG_HTTPS_CERT/MG_HTTPS_KEY`;Vite 配置只有同时设置这两个变量才启用 HTTPS,所以退回了 HTTP。HTTP 非安全上下文下麦克风/语音识别可能显示已授权但拿不到音频。现已用 `.certs/172.30.43.234+4.pem` 重启 HTTPS,并重新签发包含 `192.168.137.55` 的证书。

设备信任根证书后才能稳定使用麦克风:

- iPad:下载 CA → 设置 → 已下载描述文件 → 安装 → 通用 → 关于本机 → 证书信任设置 → 对该根证书开启完全信任。
- Android(Redmi/HONOR):下载 CA → 设置 → 安全与隐私 → 更多安全设置 → 加密与凭据 → 安装证书 → CA 证书 → 仍然安装 → 选择 `mkcert-rootCA.crt`。HyperOS 部分版本路径是「密码与安全 → 系统安全 → 加密与凭据」;找不到就在设置顶部搜索「凭据」或「证书」。
- 安装页显示“最近/安全访问”没有文件时:先用系统「文件管理」确认 `mkcert-rootCA.crt` 在 `内部存储/Download`,不是浏览器私有目录;再在安装页点「浏览/≡」→「内部存储」→ `Download`。仍不显示时把扩展名改成 `.pem` 或 `.cer` 再试。部分 ROM 要求先设锁屏 PIN。

## 1. 设备矩阵

分工:**编号、访问方式、测试日期、状态由我维护;设备名(精确)、型号、系统版本、浏览器版本由你补。**

| 编号 | 设备 | 型号 | 系统 | 浏览器 | 访问方式 | 测试日期 | 状态 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| D1 | REDMI Pad 2 Pro | REDMI Pad 2 Pro | Android 16 | 浏览器 20.6.1061104 | 校园网(与电脑同一网络) | 2026-11-22 | 证书/访问已通,待功能复测 |
| D2 | Jacapo-25 iPad Air | iPad Air 11-inch (M3) / A3266 | iPadOS 26.6.2 | Safari(随 iPadOS 26.6.2) | 局域网 HTTPS | 2026-11-21 起 | 待复测 |
| D3 | HONOR 500 Pro | MEP-AN00 | Android 16 | 百度 15.84.0.10 | 校园网(与电脑同一网络) | 2026-11-21 起 | 待复测 |

矩阵字段已补齐。D1 浏览器名称就是“浏览器”，版本 `20.6.1061104`;D1/D3 均通过校园网与电脑连接同一网络访问。

## 2. 修补记录

### F-01 手机/平板整页布局

- 设备:D1、D2、D3
- 症状:桌面布局直接压到窄屏;聊天、首页、设置、科研检索/表格页留白与可点区域不合适;底部指令区占位。
- 处理:按 900px 断点重排;聊天页底部指令区改为可收起的 command pocket;页面使用可见视口高度,提高全屏利用率。
- 代码:`frontend/src/components/chat/ChatWorkspace.vue`、`frontend/src/components/common/SettingsShell.vue`、`frontend/src/views/*`
- 提交:`e736dff`
- 验证:REDMI 平板、iPad、HONOR 手机目视检查;提交说明记录前端 58 个测试文件 / 1071 用例通过。
- 状态:已修。

### F-02 面板贴边被裁

- 设备:D2、D3
- 症状:指令按钮靠屏幕边缘时,以按钮中心展开的面板伸出视口,内容被裁掉。
- 处理:`anchorTo(selector, panelWidth)` 按按钮位置计算面板左边界,并夹在视口内;不同宽度面板传各自宽度。
- 代码:`frontend/src/components/chat/ChatWorkspace.vue`(`anchorTo`,约 346 行)
- 提交:`e736dff`("指令弹窗边界内收")
- 状态:已修。

### F-03 Safari 工具栏遮挡底部输入条

- 设备:D2(iPad,Safari)
- 症状:`100vh` 包含浏览器工具栏区域,底部输入条被切掉。
- 处理:聊天页与设置页改用 `100dvh`;保留安全区内边距。
- 代码:`frontend/src/components/chat/ChatWorkspace.vue`(约 2080 行)、`frontend/src/components/common/SettingsShell.vue`
- 提交:`e736dff`
- 状态:已修。

### F-04 竖屏 iPad 指令行溢出

- 设备:D2(竖屏 768–834px)
- 症状:默认字号指令行放不下,"生成文档"等按钮被挤到第二行或出界。
- 处理:新增 `@media (max-width: 900px)` 断点,缩小按钮内边距并允许合理换行;无 hover 设备用 `@media (hover: none)` 保留可发现性。
- 代码:`frontend/src/components/chat/ChatWorkspace.vue`(约 2379、3309 行)
- 提交:`e736dff`
- 状态:已修。

### F-05 主题切换后底部区域仍是旧色

- 设备:D2(iPad)
- 症状:切换明暗主题后,滚出 `body` 的区域仍显示 `theme-init.js` 写的旧背景色。
- 处理:`applySettings()` 同步 `document.documentElement.style.background` 与 `colorScheme`。
- 代码:`frontend/src/stores/settings.ts`
- 提交:`e736dff`
- 状态:已修。

### F-06 iPad 图解失败与图解几何

- 设备:D2
- 症状:iPad 上检查图解功能时失败;部分投影未完整渲染;带标签对象被隐藏。
- 处理:图解链路按设备收紧;法向量按曲面方程/平面/球面/圆柱计算;自动补投影区域;洋红投影与半透明圆盘区分;所有带标签且可渲染对象不再隐藏;退化向量丢弃。
- 代码:`frontend/src/components/diagram/Diagram3D.vue`、`backend/research_diagrams.py`、`backend/tests/test_research_diagrams.py`
- 提交:`e736dff`
- 验证:后端图解测试通过;iPad 复测出图。
- 状态:已修。

### F-07 图谱手势与标签适配

- 设备:D2、D3
- 症状:手机上无法自然缩放/平移;标签在窄屏被裁。
- 处理:双指缩放/拖拽手势;标签几何与视口适配;补 `graphGesture`、`graphLabels` 测试。
- 代码:`frontend/src/utils/graphGesture.ts`、`frontend/src/utils/graphLabels.ts`、`frontend/src/views/GraphView.vue`
- 提交:`e736dff`
- 状态:已修。

### F-08 红米平板切 English 后仍有中文

- 设备:D1
- 症状:设置改 English 后,开场欢迎语、学习分析中的知识点名/章节名/介绍仍为中文;部分后端返回字段只有中文。
- 处理:
  1. 欢迎语按当前语言重新渲染,不再复用会话里存下的中文;`greet()` 写入 `welcome` 标记,`isWelcomeMessage()` 识别旧欢迎语。
  2. 学习分析面板优先显示 `nameEn`。
  3. 后端图谱与学习分析返回 `nameEn`、`chapterEn`、`summaryEn`、`keyPointsEn`、`chaptersEn`。
  4. `backend/knowledge_graph/localization.py` 作为英文名/注释/章节名唯一来源。
  5. 图谱导出支持 `?lang=en`。
- 代码:`frontend/src/components/chat/ChatWorkspace.vue`(`isWelcomeMessage` 约 577 行、`welcomeText` 约 583 行)、`frontend/src/components/chat/AnalysisPanel.vue`(`pointName` 约 91 行)、`backend/graph_api.py`、`backend/learning_analysis.py`、`backend/knowledge_graph/localization.py`
- 提交:**工作区未提交**
- 验证:后端图谱/学习分析测试 22 passed;前端 i18n 精确键数测试 3 passed;`ruff` 通过。
- 状态:待 D1 复测。

### F-09 英文知识点名在节点框内爆格/截断

- 设备:D1
- 症状:英文知识点名比中文长,固定宽度节点框显示不全或省略。
- 处理:用 `canvas.measureText` 量文本,节点宽 120–220px 自适应;按词/字符完整换行,不省略;节点高随行数增长;边端点按实际框宽计算;`resetView()` 改为 `fitTo` 全部节点,避免自适应后裁切。
- 代码:`frontend/src/views/GraphView.vue`(`NODE_MIN_W` 约 98 行、`nodeSizes` 约 143 行、`resetView` 约 223 行)
- 提交:**工作区未提交**
- 验证:英文名 120–220px、中文名 120–128px;标签无省略号。
- 状态:待 D1 复测。

### F-10 英文术语不统一/编码损坏

- 设备:D1(英文界面)
- 症状:部分知识点英文名为直译;`L'H?pital`、`Newton?Leibniz`、`Cauchy?Schwarz` 出现替换字符。
- 处理:按学术英语修正 8 个名称(如 `Rules of Differentiation`、`Infinitesimals and Infinitely Large Quantities`、`Applications to Maxima and Minima`);统一美式拼写;修复特殊字符;把 `zero-point theorem` 并入 `intermediate value theorem`;改用 `tangent half-angle substitution (also called the Weierstrass substitution)`、`proper rational function`、`complex conjugate roots`。
- 代码:`backend/knowledge_graph/data/point_names.en.json`、`backend/knowledge_graph/data/point_notes.en.json`
- 提交:**工作区未提交**
- 验证:80 个名称、80 组注释无 CJK;公式与变量保留。
- 状态:待 D1 复测。

### F-11 全设备移动端底座(不再只修三台已知设备)

- 设备:所有手机、平板、桌面浏览器
- 目标:把 F-01~F-10 的设备特例收敛为全站规则;未知机型不再依赖"刚好没踩到"。
- 处理:
  1. `viewport` 加 `viewport-fit=cover` 与 `interactive-widget=resizes-content`,刘海/圆角安全区生效,Android 键盘弹出时收缩内容而不是盖住输入框。
  2. 全局 `100dvh`、左右安全区、`overflow-wrap: break-word`;仅 iOS 窄屏把表单字号提到 16px,避免聚焦自动放大。
  3. 所有弹层 `max-height` 补 `dvh` 兜底;`100vh` 必须跟 `100dvh`,否则护栏测试失败。
  4. 页面头部统一加顶部安全区;聊天输入条、设置页、科研检索/表格页、图谱页、阅读器加底部/左右安全区。
  5. 窄屏重排:科研表格侧栏置顶、论文工作台改上下布局、阅读器放大改全屏、首页导航收缩、账号头像格自动减列、设置行允许换行。
  6. 新增 `scripts/responsive-audit-test.mjs`,纳入 `npm test`,并提供 `npm run check:responsive`:挡回退 `100vh` 无 `dvh`、`100vw`、无效 `ddvh`、缺 `viewport-fit=cover`。
- 代码:`frontend/index.html`、`frontend/src/styles/base.css`、`ChatWorkspace.vue`、`SettingsShell.vue`、`SettingsView.vue`、`SettingsAccountView.vue`、`SettingsPrivacyView.vue`、`HomeView.vue`、`LoginView.vue`、`GraphView.vue`、`ResearchSearchView.vue`、`ResearchTablesView.vue`、`PaperWorkspace.vue`、`DocumentViewer.vue`、各弹层组件、`frontend/scripts/responsive-audit-test.mjs`、`frontend/scripts/run-tests.mjs`
- 提交:**工作区未提交**
- 验证:护栏 51 个样式源文件通过;`npm run lint`、`vue-tsc --noEmit` 通过;58 个测试文件 / 1071 用例通过;`npm run build` 与 `check:build` 8 项通过。
- 状态:代码完成,待 320/360/390/768/834/1024 宽度真机复测。

### F-12 手机端知识图谱:推荐/详情改为图谱下方滑动窗口

- 设备:D1、D3(手机/平板窄屏)
- 症状:"推荐下一步"浮在图谱上方、与整体不对齐;点知识点后详情窗盖住整张图谱。
- 处理:
  1. 图谱区与面板区改成上下布局;推荐和详情都放在图谱下方,不再覆盖画布。
  2. 两块面板放进同一个横向滚动容器,`scroll-snap` 固定两页:默认推荐页,点知识点后滑到详情页。
  3. 详情页右滑原生回到推荐页;关闭按钮先回到推荐页再取消选中。
  4. 桌面端保持原浮层布局(`display: contents` + 绝对定位);只有 ≤760px 启用滑动窗口。
- 代码:`frontend/src/views/GraphView.vue`
- 提交:**工作区未提交**
- 验证:`vue-tsc`、ESLint、生产构建通过;待 D1/D3 真机手势复测。
- 状态:代码完成,待复测。

### F-13 移动端麦克风有权限但无声

- 设备:D1、D2、D3
- 症状:三台设备都允许麦克风,但语音输入没有识别结果;同时发现登录页回到了 HTTP。
- 原因:Vite 以 `--host 0.0.0.0` 启动时没有带 `MG_HTTPS_CERT/MG_HTTPS_KEY`,配置因此启用 HTTP。Web Speech API 在非安全上下文下可能拿到授权却拿不到音频;Android 浏览器还依赖系统/Google 语音服务,国内网络可能不可达。
- 处理:
  1. 用 `.certs/172.30.43.234+4.pem` 重启 HTTPS,并重签证书覆盖 `172.30.43.234` 与 `192.168.137.55`。
  2. `useSpeechInput` 增加 `window.isSecureContext` 检查:HTTP 下直接提示需要 HTTPS,不再静默失败。
  3. `sr.start()` 同步抛错时补提示,不再只把图标复位。
  4. 语音服务 `network` 错误的提示改为说明 HTTPS/Android 系统语音服务限制。
- 代码:`frontend/src/composables/useSpeechInput.ts`、`frontend/src/utils/i18n/learn.ts`、`frontend/src/composables/useSpeechInput.test.ts`
- 提交:**工作区未提交**
- 验证:语音/词条测试 14 passed;全量 58 文件 / 1072 用例通过;HTTPS 页面与 `/api/health` 均 200。
- 状态:HTTPS 已恢复,待三台设备装根证书后复测;若 Android 仍报 `network`,属于浏览器语音服务不可达,不是麦克风权限问题。

### F-14 后端 ASR 兜底(国产浏览器/无 Web Speech)

- 设备:D1、D2、D3
- 症状:平板自带浏览器没有 `SpeechRecognition`,只提示“用 Chrome/Edge”;Android Chrome 的 Web Speech 还可能因 Google 服务不可达报 `network`。
- 处理:
  1. 新增 `POST /api/speech/transcribe`:接收 base64 WAV/MP3,后端调用 ASR。
  2. 默认智谱 `glm-asr-2512`(当前 `open.bigmodel.cn` 可达),可用 `MG_ASR_PROVIDER=qwen` 切到 Qwen Omni(`qwen3.8-omni-flash` 音频输入),另一家自动兜底。
  3. 前端在无 Web Speech 或 `network` 错误时,用 `MediaRecorder` 录音 → 重采样 16kHz 单声道 WAV → base64 → 后端;仍走原有数学符号转写。
  4. 录音上限 29 秒;WAV 约 960KB,低于后端 2MB body 上限。
- 代码:`backend/speech_asr.py`、`backend/main.py`、`backend/tests/test_speech_asr.py`、`frontend/src/utils/wav.ts`、`frontend/src/services/chatService.ts`、`frontend/src/composables/useSpeechInput.ts`
- 提交:**工作区未提交**
- 验证:后端全量 1661 passed;前端 59 文件 / 1075 用例通过;HTTPS 端到端用生成 WAV 转写得到 `艾克斯平方加一`,提供方 `zhipu`/`glm-asr-2512`。
- 状态:代码完成,待 D1/D3 真机复测。Qwen 路径已接线,但当前 DashScope 网络不可达,默认走智谱。

## 3. 当前验证基线

| 项 | 结果 | 时间 |
| --- | --- | --- |
| 后端 `pytest tests/test_graph_api.py tests/test_learning_analysis.py -q` | 22 passed | 2026-11-22 |
| 后端 `pytest -q` | 1661 passed | 2026-11-22 |
| 后端 `ruff check .` | All checks passed | 2026-11-22 |
| 前端 `vitest run src/utils/i18n.test.ts` | 3 passed | 2026-11-22 |
| 前端 `npm test` | 59 个测试文件 / 1075 用例 passed;含移动端护栏 | 2026-11-22 |
| 前端 `npm run lint` / `vue-tsc --noEmit` | 通过 | 2026-11-22 |
| 前端 `npm run build` / `check:build` | 构建通过;产物检查 8/8 | 2026-11-22 |
| HTTPS 本机入口 | `https://172.30.43.234:5173/login` 200;`/api/health` 200 | 2026-11-22 |
| 后端 ASR 端到端 | WAV → `艾克斯平方加一`;provider `zhipu` / `glm-asr-2512` | 2026-11-22 |
| D1 REDMI Pad 2 Pro 复测 | 无本轮复测记录 | 待补 |
| D2 iPad Air 复测 | 无本轮复测记录 | 待补 |
| D3 HONOR 500 Pro 复测 | 无本轮复测记录 | 待补 |

## 4. 三台设备回归清单

每台都按同一顺序跑,避免只测改过的地方:

1. 设置切 English,刷新,再进聊天:开场欢迎语、输入框占位、按钮全英文。
2. 发一个中文问题,再发一个英文问题:英文回答不夹中文;图解标题与复核行跟随语言。
3. 打开学习分析:知识点名、章节名、介绍全英文;点知识点能进图谱。
4. 打开知识图谱:英文长名完整显示、不省略;双指缩放/平移;重置视图不裁切节点。
5. 触发一次图解:2D/3D 都能出图;投影完整;标签不遮挡;旋转时标签稳定。
6. 底部输入条不被 Safari/浏览器工具栏遮挡;横竖屏切换后仍可用。
7. 靠屏幕边缘打开问题记录/学习分析/公式手册/待办面板:面板完整在视口内。
8. 切明暗主题:页面底部与滚动越界区域颜色同步。
9. 导出图谱 HTML(`?lang=en`):节点名为英文,无中文标题残留。

## 5. 这算什么测试

- 三台真机跑功能:真机兼容性测试(device compatibility testing)。
- 上线前按清单逐项确认:预发布冒烟测试(pre-release smoke test)。
- 让小范围真实用户实际使用并收集问题:试点/灰度发布(pilot/canary)。
- 三者都不是"部署"本身;三台设备也不能替代多机型兼容性矩阵。
