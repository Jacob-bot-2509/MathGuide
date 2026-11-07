# 习题题库状态（临时使用）

- 更新：2026-11-08
- 数据：`backend/data/exercises/bilingual/all.jsonl`（gitignored，需单独投放）
- 定位：供实验/内测临时使用的题库；**人工复验未完成**，不可用于正式评分或对外承诺正确率。

## 1. 规模

| 项 | 数量 |
|---|---:|
| 题目总数 | 7,059 |
| 双语（中+英） | 6,979（98.87%） |
| 仅中文 | 36 |
| 仅英文 | 44 |

补充题 198 道（Kuttler 53、CLP 111、CLP-2 34），原库 6,861 道。

## 2. 来源与许可

| 来源 | 数量 | 许可 | 层级 |
|---|---:|---|---|
| NuminaMath | 4,101 | Apache-2.0 | research |
| MATH | 1,937 | MIT | research |
| OlympiadBench | 823 | Apache-2.0 | research |
| CLP-4 Vector Calculus | 111 | CC BY-NC-SA 4.0 | research |
| Kuttler Linear Algebra | 53 | CC BY 4.0 | research |
| CLP-2 Integral Calculus | 34 | CC BY-NC-SA 4.0 | research |

- 全部为 `research` 层；默认 `safe` 层为空。
- 运行前必须设 `MG_EXERCISE_TIERS=safe,research`，否则文档生成无题可选。
- 许可为来源级声明；原始数据集不一定提供逐题授权。

## 3. 板块覆盖

| 板块 | 数量 |
|---|---:|
| 高等代数 algebra | 3,399 |
| 空间解析几何 geometry | 1,351 |
| 数学分析 analysis | 1,206 |
| 概率论与数理统计 probability | 581 |
| 数论 numberTheory | 522 |
| 微分方程 ode | **0** |
| 复变函数 complex | **0** |
| 拓扑 topology | **0** |

空板块不是漏标：现有三个数据集与补充来源都没有对应三件套题目。

## 4. 交叉主题覆盖：14 / 34

| 主题 | 数量 | 主题 | 数量 |
|---|---:|---|---:|
| vector-calculus | 68 | divergence-theorem | 49 |
| stokes-theorem | 36 | quadratic-form | 29 |
| line-surface-integral | 29 | green-theorem | 23 |
| taylor | 24 | residue | 18 |
| power-series | 12 | vector-space | 7 |
| orthogonal-transform | 5 | eigen | 4 |
| least-squares | 2 | euler-formula | 1 |

其余 20 项为 0：inner-product、fourier-series、fourier-transform、laplace-transform、cauchy-riemann、jacobian、implicit-function、quadric-surface、norm、convolution、generating-function、markov-chain、matrix-exponential、ode-system、prime-number-theorem、riemann-zeta、analytic-number-theory、variational、green-function、parseval。

来源审计结论见 PR #7（分支 `audit/issue6-topic-source-audit`）：多数缺口缺配对解答或许可阻塞，未批量导入。

## 5. 质量状态

- 全部题目通过三件套质量门：题干、答案、过程；`quality.manual_review = pending`。
- 补充题说明：
  - Kuttler 只导入题型可确定的证明题（答案记为 `Proof`）与是非题（`Yes`/`No`）。
  - 需要从答案块抽取数值结果的题暂未导入，留待人工核验后补。
  - CLP 为已有导入器的解析结果，未逐题人工复算。
- 翻译为机器翻译：`translation.status = machine`、`reviewed = false`。
- Diffy Qs、APEX 等来源只有答案或没有过程，未导入。

## 6. 使用与复现

```bash
cd backend
export MG_EXERCISE_TIERS=safe,research
python -m uvicorn main:app --host 127.0.0.1 --port 8000
```

文档生成接口：`POST /api/doc/exercise/plan`、`POST /api/doc/exercise`。

重新生成补充题：

```bash
cd backend
python tools/import_kuttler.py
python tools/merge_supplement.py \
  data/exercises/supplement/kuttler.jsonl \
  data/exercises/staging/clp.jsonl \
  data/exercises/staging/clp2.jsonl
python tools/translate_exercises.py \
  --input data/exercises/supplement/all.jsonl \
  --output data/exercises/supplement/all.bilingual.jsonl \
  --target auto --limit 100000 --concurrency 2 --role main --resume
python tools/merge_bank.py
```

## 7. 后续

1. 人工复验补充题，重点核对 Kuttler 是否题与答案块对应、CLP 数值答案。
2. 为 ode / complex / topology 寻找可分发且带完整过程的新来源。
3. 处理 80 道未译题（等价换算、漏译、占位符）后再决定是否补译。
