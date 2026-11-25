# MathGuide v1.32.0 — AI for Science 科研工作台、5 篇并发导入与科学发现闭环

发布日期：2026-11-26
发布类型：重大功能与设计体系升级（AI for Science 工作台 + 5 篇批量导入与横向对比 + 确定性复核与复现闭环）
代码快照：`ad6524c`
基线版本：`v1.31.0`

本版本将 MathGuide 从早期深黑科幻风格全面升级为面向高标准学习与科学研究的 **AI for Science 精密工作台**；在严格保持学习区与科研区数据隔离的前提下，围绕「纯对话模型做不到的确定性科学能力」构建了**多篇外部文献并发导入 → 结构化横向对比 → 研究缺口挖掘 → 独立双角色低温复核 → 定量回归回写 PDF 批注 → 课题级报告沉淀**的完整闭环，并同步完成桌面、平板与手机端响应式适配。

## 一、AI for Science 视觉底座与设计工程化

- **双科研主题令牌体系**：重构 `frontend/src/styles/tokens.css`，建立 **Observatory Slate（深色天文台 `#0b0e14`）** 与 **Archival Preprint（浅色暖纸预印本 `#f6f5f0`）** 双主题，10/10 WCAG 2.1 对比度全部达标（浅色强调色由 `3.68:1` 提升至 `7.16:1`），100% 保留旧变量别名向后兼容。
- **去除高干扰科幻视觉**：移除全站 CRT 扫描线、强晕影与强模糊过场，将 260 颗动态星空替换为零 GPU 消耗的精密坐标网格底纹；重构 `HomeView`（实时静默指标 + 双工作区卡片）、`IntroView`（2.2s SVG 描边徽标与经典数学公式）与 `LoginView`。
- **工程化设计工具链**：新增 3 个零依赖 Node 脚本（`ui-design-audit.mjs`、`migrate-science-tokens.mjs`、`build-science-ui-preview.mjs`）及离线交互预览页 `docs/design/ai-for-science-preview.html`，修复 11 处未定义 CSS 变量并收敛 62 处硬编码语义色。

## 二、三栏科研工作台、多子窗演示台与全局跳转

- **左侧可折叠仪器栏**：收敛学习与科研核心工具，去除冗余按钮与重复人设模式条（图谱统一由「学习分析」内进入，科研侧栏精简为课题透镜 + 核心科研工具），持久化折叠状态（`mg-rail-open`）。
- **右侧多子窗口科研演示台**：支持 **单窗 / 双窗分屏 / 三窗堆叠**（`single` / `split` / `stack`）与可拖拽水平分割条，承载「交互图表 / 文件与资料 / 文献检索与阅读」三个独立可折叠、可最大化子窗口（CSS Flex 排布确保阅读器切换布局时不卸载、不丢页码）。
- **演示台内嵌论文结构与思维导图**：在阅读器子窗口顶栏直接集成 `PaperInsights`，支持就地展开、缓存与强制刷新。
- **全局快速跳转面板（`Ctrl/⌘ + K`）**：新增 `CommandPalette.vue`（移动端配顶栏 `⌘K` 入口），按当前板块严格隔离上下文——学习辅助内只搜索学习会话与图谱，科研板块内才搜索科研会话、已入库论文（带真实标题）与研究数据表，杜绝跨区混入。
- **全端移动端适配**：≤960px 自动切单栏抽屉与横向滑动标签，≤600px 全宽安全区适配；52 个样式源文件全部通过 `responsive-audit-test.mjs` 护栏。

## 三、上限 5 篇多文献并发导入与横向对比闭环

- **外部文献批量并发导入（上限 5 篇）**：在 `ResearchSearchView`「全网文献」模式新增多选勾选与批量操作条，新增并发导入引擎 `frontend/src/utils/batchPaperImport.ts`（并发度 3，单次上限 5 篇）：
  - 已入库论文直接复用 `docId`；
  - 直链 PDF 走 `createTempPaper` → 正式入库；
  - 无直链时按 DOI/标题自动调用 `/api/research/fulltext` 解析合法开放获取 PDF 或落地页；
  - 单篇闭源失败仅标记原因，不阻断同批其余论文。
- **本地多文件并发上传**：支持文件选择器一次多选最多 5 篇本地论文并发上传并自动选中。
- **后端限流适配**：将 `backend/research_corpus.py` 上传限流由 `4 / 5min` 调整为 `12 / 5min`，保障单批 5 篇并发入库与失败重试不误触 429。
- **全科研区统一 5 篇待对比篮**：新增共享状态 `frontend/src/stores/compareQueue.ts`，同步打通外部批量导入、本地论文库、演示台阅读器与三栏独立精读台 `PaperWorkspace`，一键调用既有 `/api/research/literature/compare` 生成带页码溯源的多文献横向对比表。

## 四、AI for Science 确定性闭环与双区协同

- **对比表 → 挖掘研究缺口**：完整保留 `ResearchTablesView` 既有 `onChat()` 自动保存与回归透传，针对多文献对比表新增 **「挖掘研究缺口」** 按钮，自动携带表格上下文进入 `/research` 提炼尚未解决的 Research Gaps 与可验证假设。
- **科研区独立双角色低温复核**：在科研输入卡片顶栏提供 **「✓ 双角色复核」** 与 **「◈ 综述配图」** 两个 AI4S 系统工具开关；开启复核后，后端 `chat.py` 在论文精读（`_gen_paper_llm`）与五学术源综合（`_gen_research`）完成后，由独立第二角色以 `temperature=0` 运行 `_verify_answer` 核查推理与引用一致性（并纳入研究缓存键，严守 `analysis_worker` 安全沙箱，不执行任意代码）。
- **定量复现回写 PDF 批注**：在 `ResearchTablesView` 为带原文来源（`table.source.docId` + `page`）的数据表及 OLS/多项式回归结果新增 **「回写论文批注」**，一键将回归方程、`R²`、`p` 值或统计摘要写回原论文对应页。
- **课题上下文透镜与一键报告**：新增 `frontend/src/stores/researchProject.ts`，同步科研侧栏、文献检索与数据表的当前课题选择，并在科研侧栏提供一键 **「导出课题报告 (DOCX)」**。
- **带现场还原锚点的科研待办**：向后兼容扩展 `TodoTask.anchor`（严守 `:research` 独立分桶），科研回复与 `PaperWorkspace` 均支持一键 **「Pin 到待办」**，在待办面板点「↗ 还原现场」直达对应论文页、数据表或会话。
- **Study ⇄ Research 双向协同**：
  - 学以致研：`GraphView` 知识点详情卡新增 **「查前沿论文」**，携带中英文术语直入科研区检索；
  - 以研促学：科研对话与 `PaperWorkspace` 回复新增 **「夯实前置理论」**，在学习区开启独立教学拆解（不污染原科研上下文），并在学习区顶部展示 **「← 返回原科研会话」** 一键回跳；
  - 保留并修补既有设置：`personalized` 关闭时真实拦截学习分析提示，`researchSearchMode='page'` 不再静默丢弃宽屏模型高亮批注动作。

## 五、验证

- **后端**：`pytest tests/test_chat_helpers.py tests/test_chat_routing_branches.py tests/test_chat_stream_e2e.py tests/test_research_workspace.py -q` → **174 passed**；`ruff check` 全部通过。
- **前端**：`npm test` → **60 个测试文件 / 1086 个用例全部通过**（含新增批量导入、双角色复核与以研促学往返桥接单测；中英双语词条 `1030` 项完全对齐）；`npm run lint`、`vue-tsc --noEmit`、`npm run build` 通过；`check:build` **8 / 8** 通过。
- **设计 & 移动端护栏**：`ui-design-audit.mjs --strict` 通过（0 未定义变量，0 CRT/强闪残留，WCAG 10/10 达标）；`responsive-audit-test.mjs` 通过（52 个样式源文件全绿）。

## 六、升级与部署注意

- 前端版本号升至 `1.32.0`（「设置 → 关于 MG」同步）。
- 没有数据库结构变更，旧库与现有本地缓存直接向后兼容。
- 生产环境部署与密钥安全规范沿用 `v1.31.0`（公网 HTTPS、`MG_DEMO_MODE=0`）。
- 发布附件：完整源码快照 `MathGuide-v1.32.0-source.tar.gz`、相对 `v1.31.0` 的完整补丁 `v1.32.0.patch`、改动前代码包 `MathGuide-v1.32.0-before-code.tar.gz`、`MANIFEST.sha256`、`SHA256SUMS`、`README.md` 与 `verify_manifest.py`。

## 七、合并记录

- `ad6524c` feat: AI for Science 工作台升级、5篇并发导入与双区协同闭环
- 发布提交：`v1.32.0` 发布说明与完整源码 / 补丁 / 改动前代码 / 校验清单
