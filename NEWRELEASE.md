# MathGuide v1.31.0 — 全设备移动端底座、图谱滑动窗口与后端语音转写

发布日期：2026-11-22
发布类型：功能版本（移动端适配 + 知识图谱交互 + 语音输入兜底）
代码快照：`70b66ad`
基线版本：`v1.30.0`

本版本把前三台真机踩出来的特例收敛为全站移动端规则；手机知识图谱的推荐/详情改成图谱下方的横向滑动窗口；语音输入不再只依赖浏览器 Web Speech，新增后端 ASR 兜底，国产浏览器和 Android 语音服务不可达时仍可用。桌面端既有接口与布局保持兼容。

## 一、全设备移动端底座

- **视口与安全区**：`viewport-fit=cover` + `interactive-widget=resizes-content`；刘海/圆角/Home 指示条使用 `env(safe-area-inset-*)`；页面高度改用 `100dvh`，Safari 工具栏不再切底部输入条。
- **横竖屏与键盘**：Android 键盘弹出时收缩内容而不是盖住输入框；聊天输入条、设置页、科研检索/表格、图谱页、阅读器补底部安全区。
- **窄屏重排**：科研表格侧栏置顶；论文工作台改上下布局，结构/导图在手机上覆盖阅读器；阅读器放大改全屏；首页导航收缩；账号头像格自动减列；设置行允许换行。
- **输入与文本**：iOS 窄屏表单字号 16px，聚焦不自动放大；全局长英文名/URL 换行；触屏去掉双击缩放延迟。
- **弹层**：所有 `max-height` 补 `dvh` 兜底；弹窗宽度从 `100vw` 扣除左右安全区；小红书式贴边面板不再伸出屏幕。
- **护栏**：新增 `frontend/scripts/responsive-audit-test.mjs`，纳入 `npm test`，也可 `npm run check:responsive`；挡回退 `100vh` 无 `dvh`、`100vw`、无效 `ddvh`、缺 `viewport-fit=cover`。

## 二、手机知识图谱：推荐与详情合并

- 图谱区与面板区改为上下布局，「推荐下一步」不再浮在图谱上方。
- 推荐与知识点详情放进同一个横向滚动窗口：
  - 默认显示推荐页；
  - 点知识点自动滑到详情页；
  - 详情页右滑原生回到推荐页；
  - 关闭按钮先回推荐页再取消选中。
- 使用原生 `scroll-snap`，保留惯性滑动与边界回弹；桌面端仍是原浮层布局，只对 ≤760px 生效。
- 英文知识点名节点框自适应：120–220px、按完整名称换行、不省略；边端点随框宽调整。

## 三、双语图谱与学习分析

- 图谱接口补齐 `nameEn`、`chapterEn`、`summaryEn`、`keyPointsEn`、`chaptersEn`；图谱导出支持 `?lang=en`。
- 学习分析面板优先显示 `nameEn`；后端快照、章节名、系统提示与回退报告同步英文。
- 英文欢迎语不再复用会话里的中文；英文界面切换后聊天、学习分析、图谱保持全英文。
- 80 个英文知识点名与注释按学术英语审计：修正 8 个非标准术语，统一美式拼写，修复 `L'Hôpital`、`Newton–Leibniz`、`Cauchy–Schwarz` 编码。

## 四、语音：HTTPS 前提 + 后端 ASR

- **HTTPS 回归修复**：Vite 只有同时设置 `MG_HTTPS_CERT` / `MG_HTTPS_KEY` 才启用 HTTPS；只加 `--host 0.0.0.0` 会退回 HTTP。`useSpeechInput` 增加 `window.isSecureContext` 检查，HTTP 下明确提示，不再静默失败。
- **Web Speech 优先**：有 `SpeechRecognition` 且安全上下文正常时，仍走浏览器本地识别。
- **自动兜底**：没有 Web Speech 或报 `network` 时，切 `MediaRecorder` 录音 → 重采样 16kHz 单声道 WAV → base64 → `POST /api/speech/transcribe`。
- **后端 ASR**：
  - 默认智谱 `glm-asr-2512`（当前实测可达）；
  - `MG_ASR_PROVIDER=qwen` 时优先 Qwen Omni `qwen3.8-omni-flash` 音频输入，失败自动回退智谱；
  - 音频 ≤30 秒、≤25 MB；前端 29 秒自动停止，WAV 约 960KB，低于 2MB 请求体上限。
- **点击反馈**：点麦克风立刻点亮并提示「正在听」；`getUserMedia` 8 秒超时；超时后迟到的音频流立即关闭。
- 新增自检页 `frontend/public/mic-check.html`，显示安全上下文、`getUserMedia`、`MediaRecorder`、Web Speech、AudioContext 与 5 秒麦克风电平。

## 五、真机记录与部署文档

- 新增 `deploy/REAL-DEVICE-MATRIX.md`：三台设备矩阵、F-01~F-14 修补记录、验证基线、回归清单。
- 设备：
  - D1 REDMI Pad 2 Pro / Android 16 / 浏览器 20.6.1061104
  - D2 iPad Air 11-inch (M3) / A3266 / iPadOS 26.6.2 / Safari
  - D3 HONOR 500 Pro / MEP-AN00 / Android 16 / 百度 15.84.0.10
- 记录本地 HTTPS、mkcert 根证书安装与 HyperOS CA 菜单排查；生产环境不需要装 CA，公网证书自动受信任。

## 六、验证

- 后端：`pytest -q` → `1661 passed`；`ruff check .` 通过。
- 前端：`npm test` → 59 个测试文件 / 1079 个用例全部通过；`npm run lint`、`vue-tsc --noEmit`、`npm run build` 通过；`check:build` 8/8。
- 端到端 ASR：生成的 WAV 经 HTTPS `POST /api/speech/transcribe` 转写得到「艾克斯平方加一」，provider `zhipu`，model `glm-asr-2512`。
- 真机状态：D1 证书/访问已通，三台设备功能仍待 9 项清单复测；D1/D3 的 CA 安装与麦克风自检受设备浏览器限制，未完成最终确认。

## 七、升级与部署注意

- 前端版本号升至 `1.31.0`（「设置 → 关于 MG」同步）。
- 没有数据库结构变更，旧库直接可用。
- 生产必须使用公网 HTTPS；`MG_HTTPS_CERT/MG_HTTPS_KEY` 只用于本地调试。
- 生产必须关闭演示模式：`MG_DEMO_MODE=0`，使用邀请码/密码登录。
- 语音转写需配置智谱 Key（默认复用 `MG_ZHIPU_*`）；用 Qwen 时确保服务器能访问 DashScope，并设 `MG_ASR_PROVIDER=qwen`。
- 如果设备浏览器没有 `getUserMedia` / `MediaRecorder`，后端 ASR 也无法兜底，需要换 Chrome 或系统输入法语音键。
- 发布附件：源码快照、相对 `v1.30.0` 的完整补丁、改动前代码包、`MANIFEST.sha256` 与 `SHA256SUMS`。

## 八、合并记录

- `70b66ad` feat: 移动端适配底座、图谱滑动窗口与后端语音转写
- 发布提交：v1.31.0 发布说明与完整源码 / 补丁 / 改动前代码 / 校验清单
