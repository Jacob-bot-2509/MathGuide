# 缺失交叉主题习题来源审计（phase3a / Issue #6）

- 审计日期：2026-11-07（UTC+8）。只审计、不导入、不改业务代码。
- 任务：[Issue #6](https://github.com/Jacob-bot-2509/MathGuide/issues/6)。远程读取基线：`main`，tree SHA `45b0b835009b98f6dd8d30edcfd84404be945b20`；未 clone，未操作用户电脑，未创建分支、评论或 PR。
- 已先读：[阶段 0 来源审计](EXERCISE_SOURCE_AUDIT.md)、`backend/exercises/taxonomy.py`、`backend/exercises/gate.py`；沿用三件套、严格/实用口径、Go/No-Go 与原始 topic-id。**树中未找到独立的“习题库方案”文档**，不能声称已经核对该文档；提交前应补对附件/外部方案。
- 复现脚本：`scripts/audit/`；计数、样本 ID、哈希与人工复核：`scripts/audit/results/`。不提交原始 PDF、网页或题库全文。

## 0. 结论摘要

**整体 No-Go：不能据本轮证据宣布 28 个主题已补齐，不能开始批量导入。** 这是审计决策，不是“世界上没有这些题”。

1. 实测 MATH **test 全部 5,000 行**、NuminaMath **9,000 行固定分散窗口**；后者排除 `cn_contest` 300 行。大学交叉主题命中很少，数据集级 MIT/Apache-2.0 也不等于底层原题许可已清。
2. 28 项均有逐项候选与判定；有计数的都是本次实际页面/接口读取结果，**没有题量估计或按全书外推**。章节代理池、精确主题池和未知总量分开标记。
3. Kuttler/LibreTexts 的 CC BY 4.0 许可较适合后续工作，但人工复核暴露出**长矩阵答案被误当过程、答案串题和算术错误**。仅确认 `vector-space` 样本内 4 题；`orthogonal-transform` 1 题（证明题，须另过产品题型门槛）。这两个主题可有条件做小样本验证，不是 50 题配额的 Go。
4. Diffy Qs 选定 ODE 样本中确认 1 个完整线性相关性论证；其余长答案多数只有最终公式。作者允许选 CC BY-SA 4.0，但翻译/分发的 SA 策略尚未决定。
5. 不能把“免费”当许可：当前 OpenStax 在线版标 NC-SA 且另有 AI 使用授权要求；APEX 是 BY-NC；NTIC 是 BY-ND 且含 NC 图片；Trench 实分析的教师解答手册明确不随正文开放。详见许可表。

## 1. 统计口径与边界

### 1.1 与阶段 0 对齐

三件套 = **题干 + 可确定的答案 + 完整过程**，缺一不合格。

- `S`：题干清理后 ≥20 字符；公式短题可能被规则误杀，不据此断言原题不存在。
- `A`：独立有效 `answer`，或明确的 `Answer`/答案区块、`\boxed{...}`；不采用“最后一行就是答案”。Numina 的 `proof`、`notfound`、`None` 等占位不算独立答案。
- `P规则`：解答 ≥200 字符，或 ≥80 字符且至少两个关系/推导标记。教材的 Answer 区块也可能含推导，故同样检测；**不能因为没有叫 Solution 的标签就一概判无过程**。
- `T规则`：S、A、P规则同时满足；这是阶段 0 风格启发式，**不是完整解人工验收数，更不是正确率**。
- `人工确认下界`：只把读过且过程确实支持结论、没有未处理依赖/明显错误的样本计入。`—` 表示未完成该组逐题人工复核，不能解读为 0。下界小不代表全池只有这么多。
- 严格独立答案字段口径单列于 HF 结果；教材 Answer 区块只用实用口径，不把其文本伪装成现有数据库的独立最终答案字段。证明题即使有完整证明，也须单列产品题型许可，不能自动进入数值判分题。
- 中文采用阶段 0 的“中文字符 /（中文字符+英文词）≥20%”；HF 样本有实际计数。教材为英文，需中文翻译。图像统计与“引用图/要求作图”分开，0 个 HTML 图片不保证没有图形依赖。

### 1.2 池、样本与“实际可得量”

- 每个**来源-主题诊断组**最多抽 50 个顶层习题，seed `20261107`；不把子问拆成题，不把讲解中的 worked examples 混成课后题。
- 表 3 是每主题主诊断组（n≤50）；表 4 是备选来源诊断，不与表 3 相加为独立题总数。不同源、不同主题可能重复，尚未与现有 6,861 题去重。
- `精确/精选池`：固定页上人工选定题号或题面匹配。`章节池`：明确的相关章节全部习题，可能含相邻概念，只是**主题候选上界**，不是已确认的该 topic 总量。未核验的全书/全网题量记 **未知**。
- MATH 5,000 是 test split 的全扫，不是整个 12,500 题库全扫；Numina 是 offset `0,10000,...,890000` 各读 100 行的系统窗口，不是随机全库估计。两者关键词只查题干，不查解答，避免“解答提到某主题”误命中。
- 少于 50 的行报告的是**本轮已核验限定材料中的可获取候选量**；没有断言不能从其它章节继续找到题。50 是尽量达到的抽样目标，不是默认填充数。

### 1.3 排除、溯源与安全

明确排除考研真题、全国大学生数学竞赛、丘赛、阿里赛原题。脚本有中英文赛事/考试词黑名单，并额外整体排除 Numina `cn_contest`。**这只是候选过滤，不是原题来源认证**：其余 `olympiads`、论坛、`cn_k12`、合成题也不能自动认定未含禁用来源。无法逐题证明来源者全部留在 provenance hold，不进入 Go 数量。

Numina `default/train/120033` 的 solution 混入“翻译上述文本”指令且正文为 None；仅作为污染数据记录，未执行。它的 graph/topological subspace 也不是线性向量空间，因此剔除该语义命中。教材未见上述四类赛事原题标记，但开放教材中的第三方引文/图片仍需逐项保留归属。

## 2. 来源与许可核对（不能跨书继承 LibreTexts 许可）

所有链接均在本轮读取或从已读取页面发现；失败的候选另列，不把猜测路径当来源。

| 代号 | 实际来源/许可依据 | 本轮核验许可 | 中文/翻译 | 图形与取得方式 | 决策 |
|---|---|---|---|---|---|
| K | [Kuttler / LibreTexts](https://math.libretexts.org/Bookshelves/Linear_Algebra/A_First_Course_in_Linear_Algebra_(Kuttler))；[9.E 习题及页尾许可](https://math.libretexts.org/Bookshelves/Linear_Algebra/A_First_Course_in_Linear_Algebra_(Kuttler)/09%3A_Vector_Spaces/9.E%3A_Exercises) | **CC BY 4.0**，页内明确 Ken Kuttler / Lyryx；没有逐题 license 字段 | 英文；要翻译 | HTML 题干+部分 Answer；主样本无图 | 优先人工精选；不是全书自动 Go |
| D | [Notes on Diffy Qs](https://www.jirka.org/diffyqs/) 的 License 段 | **双许可 BY-NC-SA 4.0 或 BY-SA 4.0，可选后一许可**；不能误写为只有 NC | 英文；要翻译 | PreTeXt；有答案不等于有完整过程；全书有图 | SA 策略、答案过程验收前 No-Go 批量 |
| A | [Active Calculus 2nd ed. colophon](https://activecalculus.org/single/frontmatter-3.html)；[Multi colophon](https://activecalculus.org/multi/frontmatter-3.html) | **CC BY-SA 4.0**，允许商业适用的修改与再分发但须遵守 SA | 英文；要翻译 | HTML，选定习题未配到公开答案/过程；部分图 | 缺三件套；勿把教师资源假定公开 |
| X | [APEX Calculus 本版 colophon](https://opentext.uleth.ca/apex-calculus/colophon.html)；[答案附录](https://opentext.uleth.ca/apex-calculus/selected-answers.html) | **CC BY-NC 4.0**（Hartman，edition 5）；不是 BY，也不自动等于其它 APEX 版本 | 英文；要翻译 | HTML；题目和答案分离，以精确 backlink 配对；部分图 | 商业/闭源产品情境下 No-Go，非商业仍需完整过程 |
| R | [Lebl Basic Analysis](https://www.jirka.org/ra/) 的 License 与 solutions 段 | 双许可 **BY-NC-SA 4.0 / BY-SA 4.0** | 英文；要翻译 | HTML；作者明确**没有习题解答手册** | 正文练习可研究；当前三件套 No-Go |
| N | [NTIC 2024/6 colophon](https://math.gordon.edu/ntic/ntic/colophon.html) | 文本/多数图 **CC BY-ND 4.0**；部分图 NC，整书不可商业分发 | 英文；需要翻译，但 ND 不许可分发改编翻译 | HTML，章节习题无配对解答 | **No-Go 翻译题库**；不得假定“开放教材=可改编” |
| G | [Grinstead–Snell / Doyle 2006 PDF](https://math.dartmouth.edu/~prob/prob/prob.pdf) 首页；[公开源目录](https://math.dartmouth.edu/~prob/prob/) | **GNU Free Documentation License**；所取文件未核验到具体版本条文/解答手册同许可 | 英文；要翻译 | ch10/ch11 TeX；有图与跨题依赖；公开目录未配到解答手册 | GFDL 履约及手册权利未解决前 No-Go |
| H | [Herman PDE2 书页及许可](https://people.uncw.edu/hermanr/pde2/PDE2notes/index.htm)；[PDE1 书页](https://people.uncw.edu/hermanr/pde1/PDE1notes/index.htm) | **CC BY-NC-SA 3.0 US**（书页）；章节 PDF 无逐题许可 | 英文；要翻译 | PDF，可抽出题号；未取得配对习题完整解；图/作图题存在 | NC/SA + 三件套不足，No-Go |
| V | [Cline Variational Principles](https://phys.libretexts.org/Bookshelves/Classical_Mechanics/Variational_Principles_in_Classical_Mechanics_(Cline))；[5.E 页尾许可](https://phys.libretexts.org/Bookshelves/Classical_Mechanics/Variational_Principles_in_Classical_Mechanics_(Cline)/05%3A_Calculus_of_Variations/5.E%3A_Calculus_of_Variations_(Exercises)) | **CC BY-NC-SA 4.0**；封面图 BY 2.5 不覆盖书中文字 | 英文；要翻译 | 11 个编号练习；第8题有图；未配到答案 | No-Go；勿把讲解例题算练习解 |
| M | [EleutherAI/hendrycks_math 卡片](https://huggingface.co/datasets/EleutherAI/hendrycks_math) | 卡片 **MIT**；非逐题权利证明 | 样本英文；要翻译 | HF problem/solution；有可能含 Asymptote 图代码 | 大学主题覆盖弱；底层原题及现有题去重 hold |
| U | [NuminaMath-1.5 卡片](https://huggingface.co/datasets/project-numina/NuminaMath-1.5) | 卡片 **Apache-2.0**；原题来自试卷/论坛，不能替代底层许可 | 抽中相关题为英文；要翻译；cn_* 不是语种 | HF 多字段；合成解与污染字段需复核 | 禁用来源不能逐题排净，No-Go |
| O | [OpenStax Calculus 3 当前在线 preface/attribution](https://openstax.org/books/calculus-volume-3/pages/preface) | 当前页面明确 **BY-NC-SA 4.0**，并写明 LLM/生成式 AI 使用需事先书面许可 | 英文；要翻译 | 本轮只核对许可/前言，未继续批量取练习 | 不凭历史记忆当作 BY 4.0；未取得许可前 No-Go；Vol 2 未独立验版，不能继承结论 |
| T | [Trench ODE](https://digitalcommons.trinity.edu/mono/9/)；[Real Analysis](https://digitalcommons.trinity.edu/mono/7/) | 正文 **BY-NC-SA 3.0**；实分析页明确**教师解答手册不在 CC 内、保留全部权利、需教师身份** | 英文；要翻译 | 正文公开，不等于解答手册公开 | No-Go；未请求或获取受限手册 |
| J / B / W | [Hefferon 官网](https://hefferon.net/linearalgebra/)；[Beezer FCLA](https://linear.ups.edu/html/fcla.html)；[Wilf 下载页](https://www2.math.upenn.edu/~wilf/DownldGF.html) | **本轮未完成许可核验**，不填写凭记忆的 GFDL/CC 版本 | 英文候选；待确认 | Hefferon landing 声称每题完整解，但 PDF 406；Beezer TLS/500；Wilf 403 | 保留优先重试名单；**未知不是 0，也不是 Go** |

许可判断不是法律意见。SA 不等于 NC；本报告不把 SA 本身判为禁止商业使用，而是把未决定的译文/衍生题库授权方案作为放行阻塞。公开可浏览也不自动授予复制/翻译分发权。

## 3. 28 个主题主诊断矩阵

S/A/P/T 均为**实际样本内计数**；P/T 是规则候选，人工列才是已读确认下界。`章节`池不能当精确主题总量。表内所有材料均英文、非中文，**需要翻译**；N 另有 ND 翻译分发障碍。`图`为主样本观测，`引用/作图`不是已提取图片数。每行许可代号回表 2，定位与完整样本 ID 见脚本结果。

| topic-id | 主源与限定池（实测，不是全网总量） | n | S | A | P规则 | T规则 | 人工确认下界 | 图/翻译 | 判定（批量/小样本） |
|---|---|---:|---:|---:|---:|---:|---|---|---|
| `orthogonal-transform` | K：7.E 题面含 orthogonal matrix，10题 | 10 | 10 | 10 | 10 | 10 | 1 | 无；是 | No-Go批量；有条件Go：仅1题证明型验证 |
| `vector-space` | K：9.E 章节池106题，抽50 | 50 | 50 | 17 | 12 | 12 | 4 | 无；是 | No-Go批量；有条件Go：仅4题验证 |
| `inner-product` | D：A.5 章节池16题 | 16 | 16 | 7 | 0 | 0 | — | 未见；是 | No-Go：未配到过程 |
| `fourier-series` | D：4.2/4.3 章节池30题 | 30 | 29 | 10 | 5 | 5 | 0 | 未见；是 | No-Go：长公式≠过程；SA待决 |
| `fourier-transform` | H：Transforms 34题中精选8题 | 8 | 8 | 0 | 0 | 0 | 0 | 1题要求作图；是 | No-Go：无配对解；NC |
| `laplace-transform` | D：6.1/6.2 章节池37题 | 37 | 35 | 8 | 1 | 1 | 0 | 未见；是 | No-Go：仅结果；SA待决 |
| `taylor` | X：9.7/9.8 章节池69题，抽50 | 50 | 47 | 7 | 3 | 3 | — | 未见；是 | No-Go：NC；A备选28题无解 |
| `power-series` | X：9.6 章节池36题 | 36 | 34 | 0 | 0 | 0 | — | 未见；是 | No-Go：无精确配对解；NC |
| `cauchy-riemann` | H：Complex 第11/14/27题，3题 | 3 | 3 | 0 | 0 | 0 | 0 | 未见；是 | No-Go：无配对解；NC |
| `green-theorem` | A：Green theorem 章节池14题 | 14 | 14 | 0 | 0 | 0 | 0 | 1题有图；是 | No-Go：未配到答案与过程 |
| `divergence-theorem` | A：Divergence theorem 章节池18题 | 18 | 18 | 0 | 0 | 0 | 0 | 未见；是 | No-Go：未配到答案与过程 |
| `stokes-theorem` | A：Stokes theorem 章节池15题 | 15 | 15 | 0 | 0 | 0 | 0 | 1题有图；是 | No-Go：未配到答案与过程 |
| `line-surface-integral` | A：线/面积分两节候选池28题 | 28 | 28 | 0 | 0 | 0 | 0 | 未见；是 | No-Go：未配到答案与过程 |
| `jacobian` | A：Change of variables 章节池19题 | 19 | 19 | 0 | 0 | 0 | 0 | 未见；是 | No-Go：未配到答案与过程 |
| `implicit-function` | R：8.5 逆/隐函数定理章节池11题 | 11 | 11 | 0 | 0 | 0 | 0 | 未见；是 | No-Go：作者明确无手册 |
| `quadric-surface` | A：Common graphs 章节池24题 | 24 | 24 | 0 | 0 | 0 | 0 | 1题有图；是 | No-Go：未配到答案与过程 |
| `norm` | R：8.2 范数/矩阵/行列式章节池19题 | 19 | 19 | 0 | 0 | 0 | 0 | 未见；是 | No-Go：作者明确无手册 |
| `convolution` | D：6.3 章节池13题 | 13 | 13 | 4 | 0 | 0 | — | 未见；是 | No-Go：仅配到短答案 |
| `generating-function` | G：ch10 实测31个带标签练习 | 31 | 31 | 0 | 0 | 0 | 0 | 未见图引用；是 | No-Go：未取得公开配对解 |
| `markov-chain` | G：ch11 实测119个带标签练习，抽50 | 50 | 50 | 0 | 0 | 0 | 0 | 2题图引用；是 | No-Go：未取得公开配对解 |
| `matrix-exponential` | D：3.8 章节池17题 | 17 | 17 | 5 | 5 | 5 | 0 | 未见；是 | No-Go：答案是矩阵结果，非推导 |
| `ode-system` | D：3.1/3.3 章节池23题 | 23 | 23 | 10 | 8 | 8 | 1 | 未见；是 | No-Go批量：仅1题下界；SA待决 |
| `prime-number-theorem` | N：21.5 章节池11题 | 11 | 11 | 0 | 0 | 0 | 0 | 未见；是（ND阻塞） | No-Go：无解；ND |
| `riemann-zeta` | N：24.7/25.9 章节候选池23题 | 23 | 23 | 0 | 0 | 0 | 0 | 未见；是（ND阻塞） | No-Go：无解；ND |
| `analytic-number-theory` | N：21.5/24.7/25.9 候选池34题 | 34 | 34 | 0 | 0 | 0 | 0 | 未见；是（ND阻塞） | No-Go：无解；ND |
| `variational` | V：5.E 章节池11题 | 11 | 11 | 0 | 0 | 0 | 0 | 第8题有图；是 | No-Go：无解；NC |
| `green-function` | H：Greens 26题中精选12题 | 12 | 12 | 0 | 0 | 0 | 0 | 2题图引用；是 | No-Go：无配对解；NC |
| `parseval` | H：Fourier 21题中精选3/4/5，3题 | 3 | 3 | 0 | 0 | 0 | 0 | 1题要求作图；是 | No-Go：无配对解；NC |

**不能误读本表：**人工确认 4/50、1/10 是当前保守下界，不是总体可用率的无偏估计；不能乘以 106 或全书题量外推。主样本的 0 配对解也不等于全书绝无解。章节池尤其 `quadric-surface`、`norm`、`implicit-function`、`riemann-zeta`、`analytic-number-theory` 含邻近概念，须再做逐题标签验收。

### 3.1 取得题目的精确入口

| 诊断组 | 实际页面/文件（全部经过读取） |
|---|---|
| 教材-taylor | [入口1](https://opentext.uleth.ca/apex-calculus/sec_taylor_poly.html)；[入口2](https://opentext.uleth.ca/apex-calculus/sec_taylor_series.html) |
| 教材-power-series | [入口1](https://opentext.uleth.ca/apex-calculus/sec_power_series.html) |
| 教材-green-theorem | [入口1](https://opentext.uleth.ca/apex-calculus/sec_greensthm.html) |
| 教材-divergence-theorem | [入口1](https://opentext.uleth.ca/apex-calculus/sec_stokes_divergence.html) |
| 教材-stokes-theorem | [入口1](https://opentext.uleth.ca/apex-calculus/sec_stokes_divergence.html) |
| 教材-line-surface-integral | [入口1](https://opentext.uleth.ca/apex-calculus/sec_line_int_intro.html)；[入口2](https://opentext.uleth.ca/apex-calculus/sec_surface_integral.html) |
| 教材-quadric-surface | [入口1](https://opentext.uleth.ca/apex-calculus/sec_space_coord.html) |
| 教材-implicit-function | [入口1](https://opentext.uleth.ca/apex-calculus/sec_multi_chain.html) |
| 教材-vector-space | [入口1](https://www.jirka.org/diffyqs/html/subspaces_section.html) |
| 教材-inner-product | [入口1](https://www.jirka.org/diffyqs/html/innerproduct_section.html) |
| 教材-norm | [入口1](https://www.jirka.org/diffyqs/html/innerproduct_section.html) |
| 教材-fourier-series | [入口1](https://www.jirka.org/diffyqs/html/ts_section.html)；[入口2](https://www.jirka.org/diffyqs/html/moreonfourier_section.html) |
| 教材-laplace-transform | [入口1](https://www.jirka.org/diffyqs/html/laplace_section.html)；[入口2](https://www.jirka.org/diffyqs/html/transformsofders_section.html) |
| 教材-convolution | [入口1](https://www.jirka.org/diffyqs/html/convolution_section.html) |
| 教材-matrix-exponential | [入口1](https://www.jirka.org/diffyqs/html/sec_matexp.html) |
| 教材-ode-system | [入口1](https://www.jirka.org/diffyqs/html/sec_introtosys.html)；[入口2](https://www.jirka.org/diffyqs/html/linsystems_section.html) |
| lebl-implicit | [入口1](https://www.jirka.org/ra/html/sec_svinvfuncthm.html) |
| lebl-norm | [入口1](https://www.jirka.org/ra/html/sec_normsmatsdets.html) |
| active-taylor | [入口1](https://activecalculus.org/single/sec-8-2-taylor-poly.html)；[入口2](https://activecalculus.org/single/sec-8-4-taylor-series.html)；[入口3](https://activecalculus.org/single/sec-8-5-finding-using-taylor-series.html) |
| ntic-pnt | [入口1](https://math.gordon.edu/ntic/ntic/exercises-prime-pi.html) |
| ntic-zeta | [入口1](https://math.gordon.edu/ntic/ntic/exercises-infinite-sums.html)；[入口2](https://math.gordon.edu/ntic/ntic/exercises-riemann-hypothesis.html) |
| ntic-analytic | [入口1](https://math.gordon.edu/ntic/ntic/exercises-prime-pi.html)；[入口2](https://math.gordon.edu/ntic/ntic/exercises-infinite-sums.html)；[入口3](https://math.gordon.edu/ntic/ntic/exercises-riemann-hypothesis.html) |
| kuttler-vector | [入口1](https://math.libretexts.org/Bookshelves/Linear_Algebra/A_First_Course_in_Linear_Algebra_(Kuttler)/09%3A_Vector_Spaces/9.E%3A_Exercises) |
| kuttler-spectral | [入口1](https://math.libretexts.org/Bookshelves/Linear_Algebra/A_First_Course_in_Linear_Algebra_(Kuttler)/07%3A_Spectral_Theory/7.E%3A_Exercises) |
| active-jacobian | [入口1](https://activecalculus.org/multi/S-11-9-Change-of-Variable.html) |
| active-green | [入口1](https://activecalculus.org/multi/S_Vector_GreensTheorem.html) |
| active-divergence | [入口1](https://activecalculus.org/multi/S_Vector_DivThm.html) |
| active-stokes | [入口1](https://activecalculus.org/multi/S_Vector_StokesThm.html) |
| active-line-surface | [入口1](https://activecalculus.org/multi/S_Vector_ParamLineIntegrals.html)；[入口2](https://activecalculus.org/multi/S_Vector_ScalarSurfaceIntegral.html) |
| active-quadric | [入口1](https://activecalculus.org/multi/S-Precalc-CommonGraphs.html) |
| fourier-transform | [入口1](https://people.uncw.edu/hermanr/pde2/PDE2notes/Transforms.pdf) |
| green-function | [入口1](https://people.uncw.edu/hermanr/pde2/PDE2notes/Greens.pdf) |
| cauchy-riemann | [入口1](https://people.uncw.edu/hermanr/pde2/PDE2notes/Complex.pdf) |
| parseval | [入口1](https://people.uncw.edu/hermanr/pde1/PDE1notes/Fourier.pdf) |
| variational | [入口1](https://phys.libretexts.org/Bookshelves/Classical_Mechanics/Variational_Principles_in_Classical_Mechanics_(Cline)/05%3A_Calculus_of_Variations/5.E%3A_Calculus_of_Variations_(Exercises)) |
| generating-function | [入口1](https://math.dartmouth.edu/~prob/prob/ch10.tex) |
| markov-chain | [入口1](https://math.dartmouth.edu/~prob/prob/ch11.tex) |

### 3.2 人工复核：为什么必须区分规则与完整解

详见 [manual-review.json](../scripts/audit/results/manual-review.json)。

- **Kuttler 9.E：**抽 50 题，17 题有 Answer，12 题通过长度/关系规则；人工确认第 **21、56、60、62** 题有足够完整的解释。21/56 为规则漏掉的短而完整解。其余未放行，不用模型补写。
- 9.E 第 **61** 题（“证明任意两组基底等势”）的 Answer 却重复上一题 `Q(√2)` 的内容，是**串题**；第 **68** 题出现 `5−1=5` 并传播到最终系数，**不能作为正确参考解**。第105题题面把三分量向量写作 `R²`。第59题依赖前题，第92/101题有符号/转写问题，均待上下文/源文勘误，不计确认下界。
- **Kuttler 7.E：**仅取题面确实写 `orthogonal matrix` 的 10 题，不能把全部 82 个谱论练习计为正交变换题。10 题都通过长度规则，但56–63主要给最终特征向量/对角化数据；仅第 **66** 题的双向证明本轮放行。79题先保留其对前题78的上下文依赖。若产品只收数值判分、不收证明题，这一主题的 Go 应改为 No-Go。
- **Diffy Qs：**审阅 vector-space、Fourier、Laplace、matrix-exponential、ode-system 所有 P规则阳性项。长 LaTeX 矩阵、多个小问的答案列表会轻易超过200字符。矩阵指数5个阳性项均未展示完整求解过程；ODE `3.1.106` 甚至明确把解释留给读者。ODE `3.3.102` 给出非零线性组合为零的直接证据，可作为简短完整解，确认下界1。未逐题审完的短答案不据此宣布全池真实完整解数为0。
- 对这些问题只能**记录/暂缓**，不能在本审计中导入、改原解或自行生成补齐解。

## 4. 备选来源诊断（不与主样本简单相加）

### 4.1 APEX / Diffy Qs 可复现结构计数

下表是实际题目块/答案附录精确 backlink 配对；不是“全书可用题数”。`A` 为答案块数，`P/T` 仍是规则阳性数。APEX 对有答案附录的题进行配对，未忽略附录；不匹配的编号没有用位置近似硬配。

| 来源诊断组 | 章节池 | n | S | A | P规则 | T规则 | 样本含图题 |
|---|---:|---:|---:|---:|---:|---:|---:|
| taylor | 69 | 50 | 47 | 7 | 3 | 3 | 0 |
| power-series | 36 | 36 | 34 | 0 | 0 | 0 | 0 |
| green-theorem | 24 | 24 | 19 | 9 | 6 | 6 | 0 |
| divergence-theorem | 24 | 24 | 24 | 12 | 6 | 6 | 16 |
| stokes-theorem | 24 | 24 | 24 | 12 | 6 | 6 | 16 |
| line-surface-integral | 34 | 34 | 31 | 15 | 2 | 2 | 2 |
| quadric-surface | 32 | 32 | 23 | 12 | 1 | 0 | 9 |
| implicit-function | 30 | 30 | 27 | 4 | 3 | 3 | 0 |
| vector-space | 9 | 9 | 9 | 3 | 2 | 2 | 0 |
| inner-product | 16 | 16 | 16 | 7 | 0 | 0 | 0 |
| norm | 16 | 16 | 16 | 7 | 0 | 0 | 0 |
| fourier-series | 30 | 30 | 29 | 10 | 5 | 5 | 0 |
| laplace-transform | 37 | 37 | 35 | 8 | 1 | 1 | 0 |
| convolution | 13 | 13 | 13 | 4 | 0 | 0 | 0 |
| matrix-exponential | 17 | 17 | 17 | 5 | 5 | 5 | 0 |
| ode-system | 23 | 23 | 23 | 10 | 8 | 8 | 0 |

- APEX `green-theorem` 的24题来自含 flow/flux/二维 divergence 的混合章节；`divergence-theorem` 和 `stokes-theorem` 两行来自同一24题章节，**不可以计成48道独立题，也未语义确认每题同时属于两主题**。
- APEX `implicit-function` 诊断组只是链式法则/隐式求导，**不能冒充隐函数定理**；故主矩阵改用 Lebl 真正8.5定理章节。APEX `quadric-surface`、Diffy `norm` 同样只是候选章节池。
- Active Taylor 的3节共28个习题块，主样本少于50并非“该主题全网只有28题”；另有 APEX 69个候选、抽50，但 NC 不适合作为默认替代。Active Multi 的具体主样本见表3及结果文件。未使用需要教师验证的解答资料。

### 4.2 HF 实跑结果：不能用阶段 0 总体齐全率代替长尾覆盖

接口：[MATH size](https://datasets-server.huggingface.co/size?dataset=EleutherAI%2Fhendrycks_math)、[MATH splits](https://datasets-server.huggingface.co/splits?dataset=EleutherAI%2Fhendrycks_math)、[Numina splits](https://datasets-server.huggingface.co/splits?dataset=project-numina%2FNuminaMath-1.5)。逐页取得的行号与题干哈希保存在 [dataset-results.json](../scripts/audit/results/dataset-results.json)。

| 来源 | 实际读取 | 排除 | 有相关题的关键词组 | S/A/P/T（实用） | 独立答案字段/严格T | 中文/图代码标记 |
|---|---:|---:|---|---|---|---|
| MATH test 全7 config | 5,000 | 0 | vector-space：1 | 1/1/1/1 | 0/0 | 0/0 |
| MATH test | 同上，不重复累计 | 同上 | quadric-surface：1 | 1/1/1/1 | 0/0 | 0/0 |
| Numina 固定窗口 | 9,000 | 300（cn_contest） | vector-space：3个词面命中，人工语义保留2 | 3/2/3/2（剔除语义误命中后2/2/2/2） | 2/2；不含 proof 占位 | 0/0 |
| Numina 固定窗口 | 同上，不重复累计 | 同上 | power-series：2 | 2/0/2/0 | 0/0 | 0/0 |

其余主题在上述**字面词典+限定读取窗口**均为0命中，完整28项0值已写入结果 JSON。**不是全库0覆盖，也不是语义0覆盖**：Numina `default/train/740097` 本质上是生成函数系数题，却未写 generating function，因此被字面规则漏掉；它没有完整配对推导，补作语义候选仍不提高可用三件套数。此例说明不能把关键词0当作来源不存在。

- MATH 命中：`precalculus/test/239`（线性无关）、`intermediate_algebra/test/372`（抛物面极值/博弈）；不意味着它们是现有库之外的新题，需后续内容哈希去重与标签回查。
- Numina 相关有效向量题：`default/train/430057`（cn_k12，换基）、`default/train/260081`（aops_forum，超立方体与子空间）；`default/train/120033` 是误命中与指令污染，不采纳。
- Numina 来源窗口实际分布：olympiads 2000、amc_aime 100、aops_forum 600、metamath 200、cn_k12 2600、orca_math 1600、cn_contest 300、number_theory 100、synthetic_math 1500。不是按该比例推算全库。
- HF 三件套数只是形态审计，不等于数学正确、题目无禁用来源、底层版权已获许可。**本轮 HF 导入 Go 数量为0（provenance hold）**，不沿用阶段0“总体94%即可补大学长尾”的推断。

### 4.3 PDF/TeX 实测，非页数估算

- Grinstead–Snell/Doyle：直接读取公开 `ch10.tex`、`ch11.tex`，按顶层 `\i` / `\istar` 和 `exer 章.节.题` 标签计数。ch10 **31** 个带标签练习，全部读；ch11 **119** 个带标签练习，抽50；子问不拆题。没有把书中“奇数题解可获取”的前言说法当作本轮已拿到手册，更没有把受限完整手册视为公共源。
- Herman Transforms：末尾 Problems **34**个题块，人工精选 **6/7/8/9/10/30/31/34** 共8题属 Fourier transform/应用。
- Herman Greens：末尾 **26**个题块，精选 **1–5、9、10、13–16、24** 共12题；不是整个章节所有题都算 Green function。
- Herman Complex：末尾 **30**个题块；选 **11、14、27**，分别为 CR 等价条件、调和共轭、解析映射 Jacobian。后两题属应用，不冒充直接定义题。
- Herman Fourier：末尾 **21**个题块；Parseval **3、4、5** 共3题。均未配到公共完整习题解答。
- Cline 5.E：实际 **11**个顶层编号练习（其中含约束/广义坐标等邻近概念；不声称11题全是纯变分方程题），子列表不是独立题，第8题有图；答案/过程配对数0。

## 5. Go/No-Go 与后续动作（不执行导入）

### 5.1 放行标准

- **Go 小样本验证**：真实主题 + 开放许可可履约 + 完整答案过程经人工读过 + 无禁用来源证据 + 能保留来源与归属。允许量不足50，但必须如实报告，不能说覆盖已补齐。
- **Go 批量补缺**：还要逐题去重/来源排禁、题型门槛、完整过程与正确性验收、翻译与 SA/ND/NC 分发方案、图形资产与可渲染性都落实。
- **No-Go** 可以表示“尚未证明可用”而非永久不可用。当前只有 K 的两个主题可有条件做小验证；`orthogonal-transform` 若证明题不在产品范围，仍为 No-Go。**28项整体批量补齐 No-Go。**

### 5.2 建议顺序

1. 首先重取 Hefferon 官方正文/完整解与授权页、Beezer FCLA、Wilf 官方下载；本轮网络/许可核验失败的候选不能用记忆补数量。
2. 在 Kuttler 明确 BY 4.0 的章节做**源文校验、上下文补打包、逐题核解**，先验证向量空间/正交变换；不是自动修正文书中的错解，也不在本 Issue 修改题库。
3. 对已有 MATH/Numina 题做标签与内容哈希回查，区分“无题”与“未贴交叉标签”；必须保留本 Issue 禁用赛事原题的排除条件。
4. 如接受 SA，优先研究 Lebl/Active 的公开解答可能性或另找真正开放的完整解来源；作者明确没有解答的书，不假设可以拿到教师手册。
5. 数论长尾不要用 NTIC BY-ND 内容做可分发中文改编；寻找可改编、且解答也授权的替代源。OpenStax 不凭旧版本 BY 印象放行，更不能继续批量获取用于 AI 产品而忽略当前页面授权要求。
6. 本轮没有确认到同时满足题目、完整解、可分发许可的原生中文补缺源；这只是查证范围内未确认，不是宣称中文源不存在。不要退回考研/大学生数学竞赛/丘赛/阿里赛原题。

## 6. 复现命令与审计产物

以下命令仅在执行者自己的 Linux box 运行，使用公开只读 URL，无 token、无用户数据、无数据库写入。**不需要 clone 仓库**；把本次交付的 `scripts/audit/` 放在任意工作目录即可。`results/` 是轻量元数据，可随文档提交；原始缓存仍放 `/tmp`，不要提交。

```bash
python3 -m venv /tmp/mathguide-audit-venv
/tmp/mathguide-audit-venv/bin/pip install requests beautifulsoup4
# 需要系统已有 pdftotext（poppler-utils）；本轮 box 已有。
PY=/tmp/mathguide-audit-venv/bin/python3
OUT=/tmp/mathguide-topic-audit
mkdir -p "$OUT"

$PY scripts/audit/audit_topic_datasets.py \
  --seed 20261107 --cache "$OUT/hf-cache" --out "$OUT/dataset-results.json"
$PY scripts/audit/audit_topic_textbooks.py \
  --cache "$OUT/book-cache" --out "$OUT/textbook-results.json"
$PY scripts/audit/audit_topic_supplement.py \
  --cache "$OUT/supp-cache" --out "$OUT/supplement-results.json"
$PY scripts/audit/audit_probability_chapters.py \
  --cache "$OUT/prob-cache" --out "$OUT/probability-results.json"
$PY scripts/audit/audit_topic_pdf_sources.py \
  --cache "$OUT/pdf-cache" --out "$OUT/pdf-results.json"
```

- 结果快照：[HF](../scripts/audit/results/dataset-results.json)、[APEX/Diffy](../scripts/audit/results/textbook-results.json)、[Active/Kuttler/NTIC/Lebl](../scripts/audit/results/supplement-results.json)、[概率](../scripts/audit/results/probability-results.json)、[高级主题PDF/Cline](../scripts/audit/results/pdf-results.json)、[人工复核](../scripts/audit/results/manual-review.json)。样本 ID、URL、SHA-256、每题布尔标记可追查，不提交原题全文。
- `audit_topic_supplement.py` 的 `kuttler-*` 等是**诊断组名**，不是新增 cross_topic id；组内 `topic` 使用现有合法 id。
- PDF 切题脚本对前三章的题块数有断言（34/26/30），Cline 对1–11连续编号断言。上游排版改变应失败，不静默硬填数字。
- 数据集脚本报告失败页，不把失败当0题；本轮最终 rows 审计没有失败页。API 不保留历史版本的无限稳定性；重新运行如遇上游改版，须比较题干哈希与[输入快照清单](../scripts/audit/results/input-sha256.json)，不能承诺永远复现相同活站内容。
- 人工确认下界不能由自动命令“重新生成”；必须按照 manifest 的题号、链接和理由再读源文。结果中的候选 T 不是人工确认数。

## 7. 阻塞与限制（如实保留）

1. **计划文档缺失**：远程递归树中没有独立“习题库方案”，只核对了阶段0审计、词表与 gate；不能声称外部方案全部满足。
2. **发现工具不可用**：`parallel-cli` 在 box 未安装（command not found）。未用其它搜索提供商绕代；本轮通过候选书官网、公开书架、公开 HF 接口和页面内链接逐项取证。广域来源发现未完成；恢复该工具需 `/parallel-setup`，不是本报告已经搜索穷尽。
3. **连接失败**：Hefferon PDF/授权页面 406（landing 经 WebFetch 可读，但不能证明已取得完整解）；Beezer 官网 TLS EOF / WebFetch 500；Wilf 官网403；HF Numina `/search` 返回500。未把这些错误等同于资源不存在。数据集统计另用范围更小、公开且只读的 `/rows` 扫描，而非声称搜索成功。
4. **未达50的项目**：主矩阵除 Kuttler vector、APEX Taylor、Markov 外均少于50；本轮只给已取得的实际限定池和样本，不补写题、不估算缺额。备选章节未全部语义/正确性复核；**不能把这份报告作为“每主题50道完整可用题”的验收证据**。
5. **过程启发式存在严重假阳性**：长 TeX矩阵、答案列表和显式留给读者的推导会通过长度门槛；本报告以人工下界纠偏，不重写/美化阶段0结论。
6. **覆盖与新题数不同**：未与现有6861题库做内容去重，也未核验全部自动标签。HF关键词扫描有假阳性和假阴性；章节池也会过包含。报告没有全网总量或可新增题数估计。
7. **版权与翻译不等于数据集卡片许可**：无逐题 provenance/许可的混合来源、ND翻译、NC商业限制、SA分发，以及单独保留权利的手册都仍需处理。
8. **图形与数学正确性**：HTML图片计数和PDF图引用不覆盖全部绘图/跨题依赖；未做全样本渲染、翻译、难度评分或数学正确率评测。

## 8. Issue 末尾摘要（≤10行，供人工粘贴；未发布）

已完成28个缺失交叉主题的来源审计矩阵；仅审计，未导入、未改业务代码。
总体 No-Go：当前证据不足以批量补齐28主题，也未宣称每主题已有50道完整可用题。
实跑 MATH test 5,000行、NuminaMath 9,000行；排除 cn_contest 300行，不以窗口0命中推断全库0覆盖。
教材题量均为实测限定池，无题量估算；有章节过包含、跨题依赖及尚未完成的人工核解。
Kuttler BY 4.0样本仅确认向量空间4题、正交变换1题（证明型），可有条件小规模验证。
发现长矩阵答案冒充过程、Kuttler串题/算术错误；规则阳性不能直接作为完整解数量。
OpenStax当前在线版NC-SA、NTIC含ND、Trench解答手册不随正文开放；许可与翻译分发仍阻塞。
文档：docs/EXERCISE_TOPIC_SOURCE_AUDIT.md；复现脚本及元数据：scripts/audit/。
Hefferon/Beezer/Wilf取证受网络阻塞，独立“习题库方案”未在树中找到；PR须人工审阅，不自动合并。
