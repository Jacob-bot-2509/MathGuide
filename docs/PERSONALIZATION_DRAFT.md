# 个性化学习联动优化草案

> 状态:**草案,未实施**。本轮只做「不改功能」的代码体检与优化(见文末附录),
> 个性化模块之间的搭配与衔接涉及产品口径,先出草稿供你拍板。
> 结论先行:链路是通的,但**入口分散、信号单向、缺回写** —— 共 9 处断点,
> 其中 4 处(B1/B3/B4/B5)直接打断「讲 → 评 → 推 → 做」的闭环。

## 0. 一句话结论

现在的个性化是「四套各自正确的算法 + 三个互不相通的入口」:
诊断只在图谱页和面板里发生,推荐只服务于图谱页,学习分析只能看不能操作,
讲解会话讲完不会留下任何掌握度痕迹。功能都在,但用户走完一遍要自己记住
「刚才讲到哪个点、该去哪儿打分、打完分再去哪儿看待办」。

## 1. 现状盘点

### 1.1 后端能力(均已实现且有测试)

| 模块 | 能力 | 关键口径 |
|---|---|---|
| `backend/diagnosis.py` | 写入/读取诊断,薄弱点报告;`answer` 走模型评分,`selfRating` 走自评 | 1–5 分,`WEAK_THRESHOLD=3`,只存 uid |
| `backend/ebbinghaus.py` | 遗忘曲线 `R(t,s)=exp(-t/tau(s))`,`tau=30+15*(s-1)` 天 | `R<0.6` 进入待复核,只影响复习优先级 |
| `backend/recommendation.py` | 前置门控 + 双策略推荐 | 前置全 ≥3 才进候选;`difficulty` / `coreness` |
| `backend/graph_api.py` | 图谱节点/边/坐标/`status`/`retention` | `mastered≥3`、`weak<3`、`new` 未诊断 |
| `backend/learning_analysis.py` | 掌握度快照:覆盖、四象限 buckets、章节、瓶颈、待复核、下一步 | `MIN_SAMPLE=8` 判定数据质量 |
| `backend/profile.py` | 学习画像聚合 | **前端目前没有任何地方调用** |
| `backend/chat.py` | 「知识点讲解」按 pointId 注入该点笔记;「学习分析」把快照交给模型解读 | 只读快照,不允许模型补数 |

### 1.2 前端入口(三个,彼此不联动)

| 入口 | 位置 | 能做什么 | 不能做什么 |
|---|---|---|---|
| 图谱页 | `views/GraphView.vue` | 自评 1–5、切换推荐策略、点推荐项、跳讲解 | 看不到"为什么推荐"、不能加待办 |
| 分析面板 | `components/chat/AnalysisPanel.vue` | 自评 1–5、跳图谱定位、让模型分析 | 自评后图谱角标不刷新(需重新进页面) |
| 讲解会话 | `ChatWorkspace.vue` + `chat.py` | 带 pointId 讲解、追问 | **讲完没有任何自评入口** |

### 1.3 数据流(现状)

```
用户自评 ──► POST /api/diagnosis ──► diagnoses(SQLite)
                                        │
                             latest(uid) 每点取最后一次
                                        │
        ┌───────────────┬───────────────┼────────────────┐
        ▼               ▼               ▼                ▼
   图谱 status    推荐候选+复习lane   学习分析快照     画像(/api/profile,未接前端)
        │               │               │
        ▼               ▼               ▼
   GraphView 着色   推荐面板 5 条    面板/模型解读 + cmd://point 链接
```

**单向**:所有信号都从"自评"出发;讲解、待办、归纳本、完成任务都不产生信号。

## 2. 已发现的 9 个联动断点

按「改动成本 / 用户感知收益」排序。每条给出:现象(代码位置)→ 影响 → 建议 → 改动面 → 风险。

### B1. 讲解完没有诊断入口(最该先补)

- **现象**:`chat.py:_gen_point_lesson()` 结尾只问「接下来想先听哪一部分?」;
  前端 `ChatWorkspace.vue:2151` 用 `send(prompt, '知识点讲解', { pointId })` 发起。
  整条讲解链路不产生任何诊断记录。
- **影响**:用户刚听完一个知识点,掌握度可能已经从 2 变成 4,但系统不知道;
  推荐仍会把它当"陌生点"或维持旧分数。图谱页要给分得自己切页面找节点。
- **建议**:讲解回复末尾由**后端**追加一行确定性按钮(不依赖模型输出格式,
  与现有 `learning_analysis.footer_links()` 同一手法):
  `[太简单了](cmd://rate/<pointId>/5) · [基本会用](cmd://rate/<pointId>/4) · ...`
  前端在 `onChatClick` 的 cmd 分发里加一条 `cmd://rate/`,直接 `submitSelfRating`
  (复用 `graphService.submitSelfRating`),成功后把该行替换为「已记录 4 分」。
- **改动面**:`chat.py` 末尾追加一段(约 12 行)、`ChatWorkspace.vue` 分发 +1 分支、
  `MathText.vue` 无需改(已有 cmd:// 链接渲染)、i18n 文案 6 条。
- **风险**:低。不影响任何现有回答正文,按钮只在「知识点讲解」指令下出现。

### B2. `session.pointId` 会一直粘在会话上

- **现象**:`ChatWorkspace.vue:1224` `if (extra?.pointId) session.pointId = extra.pointId`,
  `:1286` `pointId: extra?.pointId ?? session.pointId` —— 赋值后**永不清除**。
  后端 `chat.py:1925-1932` 会把这个点的笔记作为「相关度 9.0」的片段插到检索结果最前面。
- **影响**:用户在「泰勒展开」的讲解会话里接着问「那极限怎么算」,模型仍会拿到
  泰勒展开的摘要与要点作为最高优先级资料,容易把回答往旧知识点上带。
- **建议**(三选一,建议 A+C):
  - A. 会话内第 3 轮之后自动清除 pointId(讲解 + 最多两轮追问);
  - B. 分类器判定板块变化时清除(B2 的会话切换逻辑就在这几行旁边);
  - C. 用户提问里出现了**另一个**知识点名(用 `knowledge_points.csv` 的 name 做匹配,
    后端已有图,可在 `_route_chat` 里判断并忽略旧 pointId)。
- **改动面**:前端 2 处赋值/清除 + 可能的 `ChatSession` 字段说明;后端 C 方案约 8 行。
- **风险**:中。清除过早会让"接着问这个点"失去上下文,需要一轮实测。

### B3. 自评之后各页面不互通

- **现象**:`GraphView.rate()` 会在自评后重拉 `/api/graph` 与推荐;
  `AnalysisPanel.rate()` 只重拉自己的快照;两边互不知道对方改了数据。
- **影响**:在面板里给自己打了 5 分,切到图谱页仍是旧的红色"薄弱";
  用户会怀疑数据没保存。
- **建议**:自评成功后派发一个轻量事件 `window.dispatchEvent(new Event('mg:diagnosis'))`,
  两个页面各自监听并失效自己的缓存(图谱重拉 `/api/graph`,面板重拉 `/api/profile/analysis`),
  不做全局状态库改造。
- **改动面**:3 个文件各 3–5 行。
- **风险**:低。

### B4. 推荐与待办 / 归纳本没有接口

- **现象**:推荐项(模板里 `v-for="item in recommendation.items"` 那一段,点击只做 `selectById`);
  `stores/todo.ts:saveTask()` 已经能建任务,两者无关联。
- **影响**:推荐说"该复习 X 了",用户关掉页面就忘了。
- **建议**:推荐项右侧加一个小图标(不改现有点击行为):
  「加入待办」→ `saveTask({ content: '复习:<点名>', date: 今天, time: 当前+30min, repeat: 'once' })`,
  并 toast 提示已加入。若该点有 `reviewDue`,默认时间改为今天 20:00。
- **改动面**:`GraphView.vue` 模板 +1 按钮、`stores/todo.ts` 无需改(已有 API)。
- **风险**:低(纯新增按钮)。

### B5. 待办完成不产生学习信号

- **现象**:`stores/todo.ts:markDone()` 只写 `done[key]`,与诊断完全无关。
- **影响**:用户"按推荐复习了 20 分钟",系统仍然认为这个点没有被复习过,
  下次推荐继续推荐同一批。
- **建议**:任务可选绑定 `pointId`(从推荐加入待办时自动带上);
  点「已完成」后弹一个**可跳过**的 1–5 自评条(复用 B1 的按钮组)。
  跳过则不写任何记录 —— 保持"没有信号就等于没诊断"的现有口径。
- **改动面**:`TodoTask` 增可选字段 `pointId`(向后兼容,`validTask` 不必强制)、
  面板弹条 1 个组件。
- **风险**:中(涉及本地数据结构,需要 `validData` 的宽松校验兜底,现有实现已是 filter 宽松)。

### B6. 归纳本与知识点脱钩

- **现象**:`stores/notebook.ts:NotebookEntry` 只有 `question/answer/sessionId/msgId`,
  没有板块 key,更没有 pointId。
- **影响**:归纳本只能"温故",不能回答"我在泰勒展开上错过几次"。
- **建议**:`addEntry()` 增加可选 `categoryKey` / `pointId`(调用点
  `ChatWorkspace.vue:1482` 手上都有 `session.cat?.key` 与 `session.pointId`)。
  读取端在归纳本条目上显示一个小小的板块色点,不新增页面。
- **改动面**:notebook store +2 字段、调用点 +2 参数、面板 +1 行展示。
- **风险**:低(旧数据没有这两个字段,按可选处理)。

### B7. 掌握度口径有两份实现

- **现象**:`graph_api._status()` 与 `learning_analysis` 的 buckets 各自从
  `score>=MASTERED_SCORE` / `retention<REVIEW_RETENTION` 推导状态。
- **影响**:目前两边阈值都引用同一常量,**暂时一致**;但任何一次调参都可能只改一处,
  出现"图谱说是已掌握、分析说已遗忘"的矛盾。
- **建议**:把「分数 + 保持率 → 状态」收敛成一个函数(建议放 `ebbinghaus.py` 或
  新建 `mastery.py`),两个模块都调用它。**纯重构,输出逐字节不变**。
- **改动面**:新增 1 个函数,2 处调用替换。
- **风险**:低,可用现有测试逐项比对。

### B8. 未诊断的点没有"复习"概念

- **现象**:`ebbinghaus.review_due()` 在 `score is None` 时直接返回 `(False, None, None)`。
  讲解过、待办做过但没有自评的点,永远不进待复核。
- **影响**:这类"学过但没记录"的点只能靠推荐里按难度排序往上顶。
- **建议(需你拍板)**:两条路——
  - 保守:不引入隐式信号,只把「讲解过」当成 UI 提示(图谱上给个小书签),不影响算法;
  - 激进:讲解会话结束时写一条 `source="implicit"` 的诊断(比如固定 2 分),
    让遗忘曲线有起点。**这会改变数据口径与推荐结果**,不建议默认开启。
- **改动面**:保守方案仅前端标记;激进方案要动 `diagnosis.SOURCES` 与迁移口径。
- **风险**:保守=低;激进=高(历史数据与新数据不可比)。

### B9. 数据不足时的引导不闭环

- **现象**:`AnalysisPanel` 在 `dataQuality === 'none' | 'sparse'` 时只显示一句提示;
  而快照里其实已经算好了 `suggestedDiagnosis`(最多 5 个"该评的点")。
- **影响**:新用户看到"样本不足"却不知道该评哪几个,转化断了。
- **建议**:提示下方直接渲染 `suggestedDiagnosis` 的前 3 个,每个带 1–5 按钮
  (面板里已经有 `ana-rate` 样式与 `rate()` 逻辑,只是数据源没接上)。
- **改动面**:`AnalysisPanel.vue` 模板 +3 行(数据已存在)。
- **风险**:极低。

## 3. 建议的目标闭环

```
讲解 ──► B1 末尾自评 ──► 诊断入库(diagnoses)
                              │
                              ▼
                   latest + 艾宾浩斯保持率
                     │                    │
                     ▼                    ▼
              推荐(含待复核)        图谱着色 / 学习分析
                     │                    │
                     ▼                    │
              B4 加入待办                │
                     │                    │
                     ▼                    │
              B5 完成后再自评 ────────────┤
                                          ▼
                                  B3 自评事件广播(各页同步刷新)

B9:数据不足时,分析面板直接用 suggestedDiagnosis 给出"该评哪几个"
```

原则:**每一步都复用已有接口,只加"下一步"的入口,不新增算法**。
四条边(B1/B3/B4/B5)做完,用户在一个屏幕内就能走完
「讲 → 评 → 推 → 做 → 再评」,不需要自己记路线。

## 4. 分阶段落地

| 阶段 | 内容 | 是否改数据口径 | 预估 |
|---|---|---|---|
| P0 | B1 讲解末尾自评、B3 跨页刷新、B9 不足引导 | 否 | 0.5–1 天 |
| P1 | B4 推荐加待办、B6 归纳本打标、B7 口径收敛 | 否 | 1–1.5 天 |
| P2 | B2 pointId 生命周期、B5 待办绑定与完成自评 | 否(新增可选字段) | 1–2 天 |
| P3 | B8 隐式信号 / 新推荐策略(按章节、按考试倒排) | **是** | 需先定口径 |

每个阶段都能独立发版:即使只做 P0,用户也能感知到"讲完就能打分"的闭环。

## 5. 需要你确认的 5 个决策点

1. **B1 按钮放哪**:回答正文末尾(由后端追加,确定性),还是气泡下方固定工具条(前端渲染)?
   前者与 `footer_links` 一致,后者更好点、但要多一套布局。
2. **B2 清除时机**:3 轮后清除 / 板块变化清除 / 检测到新知识点名清除?
3. **B5 完成待办是否强制自评**:可跳过(推荐)还是必须选一个分数?
4. **B8 是否引入隐式信号**:不引入(保守) / 引入但只在分析里显示不参与推荐 / 引入并参与推荐?
5. **B7 口径收敛要不要现在做**:现在做会让 `graph_api` 与 `learning_analysis` 共用一个函数
   (纯重构,零输出变化),但会碰两个核心模块,需要额外的回归比对。

## 6. 另有两处"非联动"的发现(顺带记录)

- `GET /api/profile`(学习画像)后端完整实现且有测试,但**前端从未调用**。
  要么在设置页接一个"学习画像"卡片,要么在文档里明确它是给看板/运维用的。
- `POST /api/diagnosis` 的**模型评分分支**(传 `answer` 由模型打 1–5 分)前端没有入口,
  目前只走 `selfRating`。如果暂时不用,建议在 README 里注明"预留";
  如果想用,B1 之后最自然的接法是"讲解后让用户复述一句,由模型评分"。

---

## 附录 A:本轮已完成的代码优化(全部不改功能)

原则:**改的是"怎么算",不是"算什么"**。所有输出、接口契约、界面文案、判定阈值一律不变。

### A.1 后端

| 文件 | 改动 | 原问题 | 收益 |
|---|---|---|---|
| `db.py` | `init()` 按库路径缓存建表结果,`reset_for_tests()` 失效 | 每次取连接都执行整份 SCHEMA(7 条 CREATE)+ 一次提交 | 每个鉴权请求少开 1 个连接、少 7 条 DDL |
| `store.py` | `init()` 命中 `_ready_key` 后不再 `SELECT meta` | 鉴权热路径每次多开一个连接查 meta | 每请求 3 个连接 → 1 个 |
| `usage.py` | 同上 | 每次记录用量多查一次 meta | 同上 |
| `diagnosis.py` | 同上;新增 `latest_from(entries)`;`weak_report(..., latest_map=)` | 读诊断时会取写锁 + 查 meta;`weak_report` 与 `latest` 各自全表扫描 | 诊断读路径由「写事务」降为纯读 |
| `profile.py` | 复用同一次 `for_user()` 结果 | 一次画像请求扫 3 遍 `diagnoses` | 3 次扫描 → 1 次 |
| `diagnosis.py` | `_llm_score` 用累加计数替代每帧 `sum(len(...))` | 流式评分时 O(n²) | O(n) |
| `knowledge_graph/__init__.py` | `topological_order()` 按实例缓存,返回副本 | 推荐/分析每次请求重跑 Kahn | O(V+E) → O(V) 拷贝 |
| `graph_layout.py` | `layout_points()` 按图实例 `lru_cache(8)`,返回浅拷贝 | 每次 `/api/graph` 重建 NetworkX 图 + 4 轮重心法 | 布局只在首请求计算 |
| `graph_api.py` | 章节判重改用 set | `chapter not in chapters` 是列表扫描(O(n²)) | O(n²) → O(n) |
| `rag/index.py` | 分词结果每次检索只算一次;多样性判定复用主循环的关键词结果 | 每个 chunk 都重跑一次 `findall`,且 `_diversify` 二次计算关键词分 | 100 片段时省约 200 次正则/子串扫描 |

### A.2 前端

| 文件 | 改动 | 原问题 | 收益 |
|---|---|---|---|
| `views/GraphView.vue` | 边/节点几何、暗化、截断文案全部提进 `computed`(`edgeGeoms`/`nodeGeoms`) | 拖拽/缩放改的是 viewBox,模板里 `pos()/isDim()/label()` 每次 pointermove 全量重算 | 平移缩放只更新一个属性,不再触发 N+E 次函数调用 |
| `views/GraphView.vue` | 首屏与自评后 `/api/graph` 与 `/api/recommendation` 并发 | 两次往返串行 | 首屏少等一个 RTT |
| `components/chat/MathText.vue` | 解析结果(`isolateMath` + `parse`)按原文缓存(16 条 LRU) | 父组件因滚动/面板等无关状态重渲染时,整段正文重新解析 | 长回答重渲染只重建 VNode,不重跑正则;流式每帧仍是新文本,解析次数不变 |
| `components/common/Starfield.vue` | 网格预渲染到离屏画布并按主题失效;resize 合并到一帧;`visibilitychange` 停帧 | 每帧重画约 30 条线;手机地址栏收缩会连续触发几十次 resize 并重建星点;后台标签页持续空转 | 每帧绘制调用减半;resize 不再抖;后台不耗电 |

### A.3 验证

```bash
# 后端
.venv\Scripts\python.exe -m pytest -q          # 927 passed, 1 skipped
# 前端
cd frontend && npx vue-tsc --noEmit            # 0 error
cd frontend && npm test                        # 19 个套件全部通过
cd frontend && npx vite build                  # built in 6.42s(仅 chunk 体积告警)
# 其中与本次改动直接相关:
#   MathText 公式渲染 78/78 · SSE 收尾 17/17 · 图谱布局 14/14
```

另外跑了一次链路冒烟(临时库,不落仓库数据):80 个知识点的布局缓存前后一致、
拓扑序缓存返回独立副本、诊断写入 → 推荐 → 快照 → 画像 → 薄弱点全部返回正常。

### A.4 刻意**没有**改的(需要产品决策或会改行为)

- `graphService.exportGraphHtml()` 直接 `fetch('/api/graph/export')`,没走 `BASE_URL` 前缀。
  配了 `VITE_API_BASE_URL` 的部署会 404。**这是 bug 不是优化**,修它属于改行为,留给你决定。
- `notebook.persist()` 只落盘最近 200 条,但内存里保留全部;两侧口径不一致。
  统一会让用户"少看见"条目,属于行为变化,未动。
- `rate_limit._sweep_if_needed()` 超容淘汰是 `min()` 逐个找,最坏 O(n·k)。
  只在极端造 key 时触发,收益低、改错风险高,未动。
- 两处"掌握度状态"推导(B7)未合并:合并要碰两个核心模块,建议随 P1 一起做。



