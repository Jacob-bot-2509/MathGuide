# 习题库来源审计报告（阶段 0）

- 审计日期：2026-11-07（Asia/Shanghai）
- 抽样种子：`20261106`
- 每个来源抽样：`200` 题（NuminaMath 的 `cn_k12` 与 `cn_contest` 各 200 题）
- 审计脚本：[backend/tools/audit_exercise_sources.py](../backend/tools/audit_exercise_sources.py)
- 范围：MIT OCW 18.01/18.02/18.03、OlympiadBench、MATH、NuminaMath `cn_k12`/`cn_contest`
- 约束：只抽样、不导入题库、不改业务代码；原始 PDF/API 响应只落在 `/tmp` 缓存，不提交

## 0. 结论摘要

| 来源 | 三件套齐全率（实用口径） | 中文题占比 | 首批建议 | Go/No-Go |
|---|---:|---:|---:|---|
| MATH | 94.0% | 0% | 2,000 | **Go** |
| OlympiadBench（仅 open-ended） | 89.6%（全样本 65.5%） | 77% | 1,000 | **Go（有条件）** |
| NuminaMath `cn_k12` | 97.5% | 0% | 3,000 | **Go** |
| NuminaMath `cn_contest` | 94.5% | 0% | 1,500 | **Go** |
| MIT OCW 18.01/18.02/18.03 | 0.5% | 0% | 0 | **No-Go** |

首批合计约 **7,500 题**，按实用口径约 **7,119 题**可用；按高质量模型估算的机翻成本约 **$18**（不含人工抽检）。

三个需要产品/法务先注意的结论：

1. **没有任何来源提供逐题许可字段**。许可只能按数据集级处理；`OlympiadBench` 与 `NuminaMath` 的原始题目来自竞赛/试卷/论坛，数据集卡片标注的 Apache-2.0 不能自动覆盖底层题目的版权，导入前需法务复核。
2. **没有逐题平行的中英双语数据**。`OlympiadBench` 同时提供 en/zh 两个题集（en 1,389 题、zh 4,753 题），但抽样 200 题中没有发现同一题目的中英对齐对；其余来源都是单语。双语库必须依赖翻译。
3. **NuminaMath 的 `cn_*` 是“来源地”标签，不是中文文本**。`cn_k12` 与 `cn_contest` 抽样中中文占比均为 0%（分别只有 1 和 40 个中文字符）；题目与解答实际为英文，需翻译成中文后才能用于中文习题库。

## 1. 方法

### 1.1 抽样

- **MATH**：使用 `EleutherAI/hendrycks_math` 的 test split（共 5,000 题），按 7 个学科分层、按各科题量比例分配 200 个配额。test split 与 train split 不重复。
- **OlympiadBench**：使用 `Hothan/OlympiadBench`（官方数据的 HF 重打包）的 12 个数学 config，覆盖 en/zh、text-only/多模态、open-ended/theorem-proof；按各 config 题量比例分配 200 个配额。物理 config 不在本 Issue 范围，未抽样。
- **NuminaMath**：使用 `project-numina/NuminaMath-1.5` 的 `train` split。该数据集按 `source` 连续分块；脚本在已核验的内部窗口（`cn_k12` 约 290k–540k，`cn_contest` 约 706k–730k）内随机取 100 行页，并逐页校验 `source` 字段，不匹配即报错。窗口是内部采样窗口，不是精确子集边界。
- **MIT OCW**：按课程 sitemap 定位 18.01SC 的 5 套 exercise、18.02SC 的 6 套 supplementary exercises、18.03SC 的 30 组 session Q/S PDF；解析 PDF 文本后按题号/题标配对。18.01/18.02/18.03 各抽 67/67/66 题，共 200 题。
- **口径说明**：本报告把 MIT OCW 18.01/18.02/18.03 视为一个来源组，共抽 200 题（不是每门课程各 200 题）。若要求每门课程各 200 题，18.03 当前可解析 pool 只有 98 题，需要扩大 Q/S 抽样并重新解析。
- 所有来源都用固定 seed 的 `random.Random`，结果可复现；抽样是“按分布抽题”，不是全量下载。

### 1.2 三件套判定

三件套 = 题干 + 答案 + 完整过程，缺一即不合格。为区分“答案字段缺失”和“答案不可用”，报告同时给两个口径：

- **严格口径**：答案必须是独立字段（`answer` 或 `final_answer` 非空）。
- **实用口径**：答案可以是独立字段，也可以从解答中确定性抽取——`\boxed{...}`，或 `Answer:`/`答案：` 标记。**不含**“取最后一行”这类启发式。

判定细节：

- **题干**：清理后长度 ≥ 20 字符。
- **完整过程**：解答长度 ≥ 80 字符，且含至少 2 个推导/关系标记（`=`、`\le`、`\Rightarrow`、`→`、`\therefore`、`所以`、`因此`、`thus` 等）；≥ 200 字符直接视为有完整过程。PDF 常把整段推导排成一行，因此不以换行数作为硬条件。
- **可解析**：HF 行能取到题干；MIT PDF 文本能抽出题干。题干过短/为空不计入可解析。
- **无答案**：严格/实用口径下都抽不到答案。
- **过程过短/疑似仅答案**：有答案但解答不满足上述完整过程条件；短题的一行推导也可能被此规则误判，见“限制”。

### 1.3 指标定义

- **可解析率**：题干能正常抽出的样本占比。
- **答案字段率**：有独立答案字段的占比。
- **答案可抽取率**：独立字段或 `\boxed`/`Answer:` 可确定性抽取的占比。
- **三件套齐全率**：题干、答案、完整过程同时满足的占比；分严格/实用两个口径。
- **原生双语覆盖率**：同一题同时有中英两个原生版本的占比。用抽样 ID/内容对齐检查；0% 表示没有可直接配对的双语条目。
- **中文题占比**：题面+解答中中文字符占（中文字符+英文词）的比例 ≥ 20% 的条目占比。
- **许可字段完整率**：条目级许可字段非空的占比。四个来源都没有该字段，因此统一为 0%；数据集级许可另行给出。
- **翻译 token**：英文按 1 词 ≈ 1.33 token；中文按 1 字 ≈ 1 token；翻译输出按输入的 1.2 倍 token 估算。

### 1.4 数据访问与许可核对

| 来源 | 数据集级许可 | 许可依据 | 逐题许可字段 |
|---|---|---|---|
| MATH | MIT | `EleutherAI/hendrycks_math` HF 卡片 | 无（0%） |
| OlympiadBench | Apache-2.0 | `Hothan/OlympiadBench` HF 卡片 | 无（0%） |
| NuminaMath | Apache-2.0 | `project-numina/NuminaMath-1.5` HF 卡片 | 无（0%） |
| MIT OCW | CC BY-NC-SA 4.0 | MIT OCW Privacy and Terms of Use | 无（0%） |

说明：`OlympiadBench` 的 HF 卡片是重打包者标注；原始题目来自各国竞赛/中国高考题，`NuminaMath` 的题目来自公开 PDF/论坛。两者都需要法务确认“数据集许可是否覆盖底层题目”。MIT OCW 的 **NonCommercial + ShareAlike** 对商业产品或闭源题库有直接限制。

## 2. 总体指标

样本量均为 200。百分比为样本内比例。

| 来源 | 可解析率 | 答案字段率 | 答案可抽取率 | 完整过程率 | 三件套（严格） | 三件套（实用） | 中文题占比 | 原生双语 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| MATH | 100.0% | 0.0% | 100.0% | 94.0% | 0.0% | **94.0%** | 0.0% | 0.0% |
| OlympiadBench | 100.0% | 73.0% | 73.0% | 91.5% | 65.5% | **65.5%** | 77.0% | 0.0% |
| NuminaMath `cn_k12` | 100.0% | 98.5% | 98.5% | 99.0% | 97.5% | **97.5%** | 0.0% | 0.0% |
| NuminaMath `cn_contest` | 100.0% | 97.5% | 97.5% | 96.0% | 94.5% | **94.5%** | 0.0% | 0.0% |
| MIT OCW | 95.0% | 0.0% | 0.5% | 81.0% | 0.0% | **0.5%** | 0.0% | 0.0% |

解读：

- **MATH**：没有 `answer` 字段，但 100% 的解答含 `\boxed{}`，因此实用口径 94%；严格口径 0% 不代表答案缺失。未通过的 12 题是短解/一行推导（见限制）。
- **OlympiadBench**：open-ended 题的三件套率是 **89.6%**（129/144）；theorem proof 只有 **3.6%**（2/56），因为证明题没有 `final_answer`。全样本 65.5% 被证明题拉低。全样本中 47.5% 的题目带图片。
- **NuminaMath**：答案字段率最高（97.5%–98.5%），三件套率也最高；但文本语言是英文。
- **MIT OCW**：95% 的题能抽出题干/题解，但基本没有独立答案字段，只有 1 题命中 `Answer:`/`\boxed`；因此三件套实用口径仅 0.5%。

## 3. 缺失原因

按“主要失败原因”统计，一题只计一次；实际可能有多个原因。

| 来源 | 无答案 | 无过程/题解未配对 | 题干为空/过短 | 过程过短/疑似仅答案 | 质量标记无效 |
|---|---:|---:|---:|---:|---:|
| MATH | 0 | 0 | 0 | 12 | 0 |
| OlympiadBench | 54 | 2 | 0 | 13 | 0 |
| NuminaMath `cn_k12` | 3 | 0 | 0 | 2 | 0 |
| NuminaMath `cn_contest` | 5 | 0 | 0 | 6 | 0 |
| MIT OCW | 167 | 22 | 10 | 0（另有 15 题解答 <80 字符，其中 3 题 <40 字符已计入“无过程”） | 0 |

补充：

- **OlympiadBench 的 54 个“无答案”几乎全部是 theorem proof**。这不是抽样错误，而是数据形态：证明题没有可判分的最终答案字段。若将证明题按“题干+完整证明”单独设门槛，则这 56 题的证明完整率是 96.4%（54/56）；但按本 Issue 的三件套定义，它们不合格。
- **MIT 的 22 个“无过程”** 包含 19 题题解为空 + 3 题题解不足 40 字符；空题解又分为原课程未提供解答的 starred/进阶题，以及 PDF 题标配对失败。抽查到的例子包括 `2A-9`、`1I-5`、`2B-5` 等。**10 个“题干过短”** 多为 PDF 公式碎片（如 `. sin2 xdx`），是抽取噪声，不是原题缺失。
- **MIT 的 167 个“无答案”** 是结构性的：题解里通常有最终结果，但没有 `Answer:` 标记；用“最后一行含结果”的启发式时 84.5% 能命中，但该启发式未纳入三件套（避免把证明题/作图题的中间表达式误当答案）。

## 4. 双语与中文占比

| 来源 | 文本语言 | 中文题占比 | 逐题中英平行 | 集合级语种覆盖 |
|---|---|---:|---:|---|
| MATH | 英文 | 0.0% | 0% | 仅英文 |
| OlympiadBench | 中文为主 | 77.0% | 0%（抽样 45 en + 155 zh，ID 交集 0） | en + zh 两个题集 |
| NuminaMath `cn_k12` | 英文 | 0.0% | 0% | 仅英文 |
| NuminaMath `cn_contest` | 英文 | 0.0% | 0% | 仅英文 |
| MIT OCW | 英文 | 0.0% | 0% | 仅英文 |

- `OlympiadBench` 的 en/zh 是两个独立题集（en 1,389 题、zh 4,753 题，合计 6,142 道数学题），不是同一批题的双语版本。抽样中 en 与 zh 的题目 ID 没有交集，因此“逐题原生双语覆盖率”为 0%。
- `NuminaMath` 的 `source` 字段是采集来源（中国 K12、中国竞赛），不是文本语言。抽样里 `cn_k12` 只有 1 个中文字符、`cn_contest` 只有 40 个，题面和解答都是英文。这一点与“中文题占比”预期相反，需要在选题/翻译计划里明确。
- 结论：**当前没有任何来源能直接提供“同题中英双语”**。双语库必须以“英文原题 + 机器翻译 + 人工校对”为主路径；`OlympiadBench zh` 可以作为中文原生内容的补充，但它没有英文对照。

## 5. 板块/题型/难度分布

样本内计数。完整枚举见脚本输出的 `results.json`，这里列 Top 5。

| 来源 | 主要板块（Top 5） | 题型 | 难度 |
|---|---|---|---|
| MATH | Algebra 47、Intermediate Algebra 36、Prealgebra 35、Number Theory 22、Precalculus 22 | free-response 200 | Level 4 61、Level 5 50、Level 2 40、Level 3 34、Level 1 15 |
| OlympiadBench | Probability & Statistics 55、Solid Geometry 33、Conic Sections 30、Algebra 23、Geometry 19 | Open-ended 144、Theorem proof 56 | 中国高考 130、竞赛 70；带图 47.5% |
| NuminaMath `cn_k12` | Algebra 113、Geometry 42、Combinatorics 14、Inequalities 11、Calculus 9 | word problem 103、MCQ 95、proof 2 | K12（单一标签） |
| NuminaMath `cn_contest` | Algebra 75、Geometry 62、Number Theory 29、Combinatorics 20、Inequalities 12 | word problem 114、MCQ 43、proof 43 | competition（单一标签） |
| MIT OCW | 18.03 微分方程 66；18.01 的 1A/5A/3C…；18.02 的 2C/2F/4E… | exercise 200 | 无难度标签 |

补充：

- MATH 的难度分布明显偏难：Level 4/5 合计 111/200（55.5%），Level 1/2 合计 55/200（27.5%）。
- OlympiadBench 的图片依赖是最需要处理的工程问题：47.5% 样本带图；多模态 config 的 `image_*` 字段不能直接变成可渲染题干。
- NuminaMath `cn_contest` 的证明题占比 43/200（21.5%），明显高于 `cn_k12` 的 2/200（1%）；`cn_contest` 的答案字段率略低（97.5%）也与此有关。

## 6. 许可字段完整率

| 来源 | 数据集级许可 | 逐题许可字段完整率 | 备注 |
|---|---|---:|---|
| MATH | MIT | 0.0% | HF 卡片标注；题目为竞赛数学 |
| OlympiadBench | Apache-2.0 | 0.0% | HF 重打包卡片；原始赛事/高考题版权需复核 |
| NuminaMath | Apache-2.0 | 0.0% | 采集自公开 PDF/论坛；逐题来源不可追溯 |
| MIT OCW | CC BY-NC-SA 4.0 | 0.0% | **禁止商业使用；衍生作品需相同方式共享** |

**这是本审计最重要的合规结论**：四个来源都没有逐题 license/provenance 字段，无法在导入时按题过滤许可。可行的做法是：按数据集级许可决策 + 对每个来源保留原始 ID/URL + 人工抽检；如果产品是商业/闭源，MIT OCW 直接排除。

## 7. 翻译量与成本

### 7.1 模型与单价

- 经济型（GPT-4o-mini 级）：输入 $0.15/M tokens、输出 $0.60/M tokens；输出按输入 1.2 倍 → **$0.87/M 源 tokens**。
- 高质量（GPT-4o 级）：输入 $2.50/M tokens、输出 $10.00/M tokens；同样输出 1.2 倍 → **$14.50/M 源 tokens**。
- 英文 1 词 ≈ 1.33 token；中文 1 字 ≈ 1 token。
- 成本只含机器翻译 API，不含人工抽检、术语表、返工和排版。

### 7.2 样本量与全量外推

| 来源 | 样本英文词 | 样本中文字 | token/题 | 全量题数 | 全量 tokens | 经济型 | 高质量 |
|---|---:|---:|---:|---:|---:|---:|---:|
| MATH | 16,714 | 0 | 111.2 | 12,500 | 1.39M | $1.21 | $20.15 |
| OlympiadBench | 21,163 | 21,065 | 204.6 | 6,142 | 1.26M | $1.09 | $18.22 |
| NuminaMath `cn_k12` | 29,505 | 1 | 196.2 | 268,819 | 52.74M | $45.89 | $764.80 |
| NuminaMath `cn_contest` | 21,609 | 40 | 143.7 | 29,944 | 4.30M | $3.74 | $62.39 |
| MIT OCW | 18,769 | 0 | 124.8 | 无可靠全量 | — | — | — |
| **合计（不含 MIT）** | — | — | — | — | **59.69M** | **$51.93** | **$865.56** |

全量题数来源：MATH 12,500（train+test）、OlympiadBench 数学 6,142、NuminaMath 卡片 268,819 + 29,944；MIT OCW 没有可比的“全量题数”，只给样本均值。

### 7.3 首批翻译成本

| 来源 | 首批题量 | 预计可用（实用口径） | 高质量机翻成本 |
|---|---:|---:|---:|
| MATH | 2,000 | 1,880 | $3.22 |
| OlympiadBench（仅 open-ended） | 1,000 | 896 | $2.97 |
| NuminaMath `cn_k12` | 3,000 | 2,925 | $8.54 |
| NuminaMath `cn_contest` | 1,500 | 1,418 | $3.13 |
| MIT OCW | 0 | 0 | $0 |
| **合计** | **7,500** | **7,119** | **$17.86** |

结论：**机翻本身不是瓶颈**（首批不到 $20，全量已知来源不到 $900）；真正的成本在人工抽检、术语统一、题目/答案可渲染化和图片处理。

## 8. 分来源结论与建议

### 8.1 MATH — Go，首批 2,000

- 三件套实用口径 94%，答案可抽取 100%（`\boxed`）。
- 许可清晰（MIT），schema 稳定，题目/解答都是纯文本，无图片。
- 主要风险：6% 的解答是短解/一行推导（启发式误判或确实过短）；英文，需要翻译。
- 建议：从 test split 的 5,000 题里先取 2,000（按学科比例），预计 1,880 可用；作为“英文竞赛题 + 中文翻译”的第一批。

### 8.2 OlympiadBench — Go（有条件），首批 1,000

- open-ended 三件套 89.6%；全样本答案字段 73%（证明题拉低）；中文原生占比 77%，是唯一有中文原生内容的主要来源。
- 必须过滤：theorem proof（三件套 3.6%，无 `final_answer`）、带图题（47.5% 样本带图，需确认图片能否渲染）。
- 许可：HF 卡片 Apache-2.0，但原始赛事/高考题版权需法务复核；不能仅凭卡片就认定可商用。
- 建议：首批只取 text-only + open-ended + 有 `final_answer` 的题，1,000 题预计 896 可用；证明题暂不进入首批，除非产品接受“无答案字段”的证明题并单独设门槛。

### 8.3 NuminaMath `cn_k12` — Go，首批 3,000

- 三件套 97.5%，答案字段 98.5%，完整过程 99%，样本中无质量标记为无效的题。
- 题量最大（268,819），适合做规模化的 K12 基础题库。
- 关键纠正：文本是英文，中文占比 0%；“cn_k12”只是采集来源。若目标是中文题库，需要翻译，不能把它当原生中文源。
- 建议：首批 3,000 题，按 Algebra/Geometry/Combinatorics 等比例抽取；保留 `source`/`problem_id` 以便追溯；翻译后做术语校对。

### 8.4 NuminaMath `cn_contest` — Go，首批 1,500

- 三件套 94.5%，答案字段 97.5%，完整过程 96%；竞赛题占比高，适合提高难度上限。
- 题目仍是英文；43/200 是证明题，证明题的答案字段率略低。
- 建议：首批 1,500 题，优先 word problem/MCQ；证明题单独标注并人工抽检。

### 8.5 MIT OCW 18.01/18.02/18.03 — No-Go，首批 0

- **许可**：CC BY-NC-SA 4.0，禁止商业使用，衍生作品需相同方式共享。对商业/闭源题库不可接受；即使非商业，ShareAlike 也会影响题库和翻译文本的授权方式。
- **三件套**：实用口径 0.5%。题解里通常有最终结果，但没有独立答案字段；PDF 抽取后 22 题题解缺失/过短、10 题题干过短，18.03 的题解/题目配对还依赖人工检查。
- **结论**：不建议进入首批；如仅用于内部非商业研究，可保留为“人工精选题”来源，但需要逐题人工补答案并遵守 NC/SA。
- 如果未来产品明确是非商业且能接受 ShareAlike，可重新评估，但仍需先解决答案抽取与 PDF 切题问题。

## 9. 限制与风险

1. **自动判定是启发式**：三件套、完整过程、中文占比都由规则判定，不是人工逐题验收。抽样 200 题的 95% 置信区间在比例接近 90%–95% 时约 ±3–4 个百分点；接近 50% 时更宽。
2. **“完整过程”规则偏严**：MATH 的 12 题、OlympiadBench 的 13 题被判为“过程过短”，其中包含短题的一行推导（如 `1+3+5+7+9=25`）和简短但完整的解答。人工抽检后 MATH 的实际可用率可能高于 94%。
3. **OlympiadBench 是重打包版本**：`Hothan/OlympiadBench` 的 solution 字段可能不含原题解答中的图片；theorem proof 没有 `final_answer`；HF 卡片许可不等于底层题目许可。
4. **NuminaMath 的抽样窗口**：`cn_k12`/`cn_contest` 使用内部窗口而非精确子集边界；脚本逐页校验 `source`，如果上游重新排序，脚本会直接报错而不是静默采错。窗口内抽样假设“块内顺序与题目质量无关”，若上游按难度排序，样本可能有偏。
5. **MIT OCW 的 PDF 解析**：pypdf 对数学符号的抽取有损（如 `�`、上下标错位）；22 题题解缺失/过短、10 题题干过短。审计把这些问题计入失败，而不是假设人工能修复。
6. **许可与合规**：本报告只核对数据集卡片和 OCW 条款，不构成法律意见；`OlympiadBench`/`NuminaMath` 的底层题目版权、MIT 的 NC/SA 是否适用于产品，需要法务确认。
7. **未做人工质量评分**：本审计不判断题目难度是否适合产品、解答是否正确、翻译是否通顺；这些需要下一阶段的人工抽检和评测。
8. **样本量**：每个来源 200 题足以做 Go/No-Go 和量级估算，但不足以估计长尾子板块的可用率；细分板块的结论应视为方向性。

## 10. 复现命令

本报告的数字由下面两条命令生成（两条命令使用同一个 seed，但各自从干净 RNG 起步；表内数字与这两条命令一致）：

```bash
# 可选：MIT OCW 需要 pypdf；HF 来源不需要
pip install pypdf

# 1) Hugging Face 三个来源
python backend/tools/audit_exercise_sources.py \
  --source math,olympiadbench,numinamath \
  --n 200 \
  --seed 20261106 \
  --cache /tmp/exercise_source_audit \
  --json-out /tmp/exercise_source_audit/hf.json \
  --items-out /tmp/exercise_source_audit/hf_items.jsonl

# 2) MIT OCW（单独进程，避免与 HF 共用 RNG 状态）
python backend/tools/audit_exercise_sources.py \
  --source mit_ocw \
  --n 200 \
  --seed 20261106 \
  --cache /tmp/exercise_source_audit_mit \
  --json-out /tmp/exercise_source_audit_mit/mit.json \
  --items-out /tmp/exercise_source_audit_mit/mit_items.jsonl
```

- 也可以直接用 `--source all` 一次跑完；但共享 RNG 会让“先跑哪些来源”影响抽样结果，数字会与上表有少量抽样波动。需要严格复现上表时，请用上面两条命令。
- 脚本只使用公开接口：Hugging Face datasets-server 的 `size`/`rows` API、MIT OCW 的 sitemap/资源页/PDF。
- 原始 JSON 页与 PDF 落在 `--cache`（默认 `/tmp/exercise_source_audit`），不写入仓库；`/tmp` 可随时删除。
- 脚本没有 API Key、token、用户数据；重复运行会命中缓存，不会重复下载。

## 11. 附录：样本明细

### 11.1 MATH（test split）

| 学科 | 全量 | 样本 |
|---|---:|---:|
| Algebra | 1,187 | 47 |
| Counting & Probability | 474 | 19 |
| Geometry | 479 | 19 |
| Intermediate Algebra | 903 | 36 |
| Number Theory | 540 | 22 |
| Prealgebra | 871 | 35 |
| Precalculus | 546 | 22 |
| **合计** | **5,000** | **200** |

### 11.2 OlympiadBench（数学，12 个 config）

| config | 题量 | 样本 | 说明 |
|---|---:|---:|---|
| OE_TO_maths_en_COMP | 674 | 22 | open-ended、text-only、英文竞赛 |
| OE_TO_maths_zh_COMP | 408 | 13 | open-ended、text-only、中文竞赛 |
| OE_TO_maths_zh_CEE | 1,240 | 40 | open-ended、text-only、中国高考 |
| OE_MM_maths_en_COMP | 150 | 5 | open-ended、多模态、英文竞赛 |
| OE_MM_maths_zh_COMP | 56 | 2 | open-ended、多模态、中文竞赛 |
| OE_MM_maths_zh_CEE | 1,910 | 62 | open-ended、多模态、中国高考 |
| TP_TO_maths_en_COMP | 503 | 16 | theorem proof、text-only、英文 |
| TP_TO_maths_zh_COMP | 199 | 7 | theorem proof、text-only、中文 |
| TP_TO_maths_zh_CEE | 207 | 7 | theorem proof、text-only、高考 |
| TP_MM_maths_en_COMP | 62 | 2 | theorem proof、多模态、英文 |
| TP_MM_maths_zh_COMP | 81 | 3 | theorem proof、多模态、中文 |
| TP_MM_maths_zh_CEE | 652 | 21 | theorem proof、多模态、高考 |
| **合计** | **6,142** | **200** | 其中 open-ended 4,438、proof 1,704 |

### 11.3 NuminaMath

| 子集 | 全量 | 抽样窗口（行号） | 样本 |
|---|---:|---|---:|
| cn_k12 | 268,819 | 290,000–540,000 | 200 |
| cn_contest | 29,944 | 706,000–730,000 | 200 |

窗口内每页都校验 `source` 字段；本次审计中未出现不匹配。

### 11.4 MIT OCW

| 课程 | 材料 | 样本 |
|---|---|---:|
| 18.01SC | 5 套 exercise PDF + 对应 solution PDF | 67 |
| 18.02SC | 6 套 supplementary exercise PDF + 对应 solution PDF | 67 |
| 18.03SC | 30 组 session Q/S PDF（10 个 pset，每 pset 3 组） | 66 |
| **合计** | | **200** |
