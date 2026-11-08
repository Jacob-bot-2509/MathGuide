# 习题题库状态（临时使用）

- 更新：2026-11-08
- 数据：`backend/data/exercises/bilingual/all.jsonl`（gitignored，需单独投放）
- 来源级单语文件：`backend/data/exercises/staging/{kuttler,clp,clp2}.jsonl` 与对应 `.manifest.json`
- 补题合并结果：`backend/data/exercises/supplement/all.jsonl`
- 定位：供实验/内测临时使用的题库；**人工复验未完成**，不可用于正式评分或对外承诺正确率。

## 1. 规模

| 项 | 数量 |
|---|---:|
| 题目总数 | 6,776 |
| 双语（中+英） | 6,776（100%） |
| 仅中文 | 0 |
| 仅英文 | 0 |

补充题 198 道（Kuttler 53、CLP 111、CLP-2 34），原库 6,861 道；按 2026-11-08 审计清单修复时剔除 46 道。

## 2. 来源与许可

| 来源 | 数量 | 许可 | 层级 |
|---|---:|---|---|
| NuminaMath | 4,014 | Apache-2.0 | research |
| MATH | 1,925 | MIT | research |
| OlympiadBench | 639 | Apache-2.0 | research |
| CLP-4 Vector Calculus | 111 | CC BY-NC-SA 4.0 | research |
| Kuttler Linear Algebra | 53 | CC BY 4.0 | research |
| CLP-2 Integral Calculus | 34 | CC BY-NC-SA 4.0 | research |

- 全部为 `research` 层；默认 `safe` 层为空。
- 运行前必须设 `MG_EXERCISE_TIERS=safe,research`，否则文档生成无题可选。
- 许可为来源级声明；原始数据集不一定提供逐题授权。

## 3. 板块覆盖

| 板块 | 数量 |
|---|---:|
| 高等代数 algebra | 3,353 |
| 空间解析几何 geometry | 1,266 |
| 数学分析 analysis | 1,132 |
| 概率论与数理统计 probability | 514 |
| 数论 numberTheory | 511 |
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
| taylor | 24 | residue | 17 |
| power-series | 12 | vector-space | 7 |
| orthogonal-transform | 5 | eigen | 4 |
| least-squares | 1 | euler-formula | 1 |

其余 20 项为 0：inner-product、fourier-series、fourier-transform、laplace-transform、cauchy-riemann、jacobian、implicit-function、quadric-surface、norm、convolution、generating-function、markov-chain、matrix-exponential、ode-system、prime-number-theorem、riemann-zeta、analytic-number-theory、variational、green-function、parseval。

来源审计结论见 PR #7（分支 `audit/issue6-topic-source-audit`）：多数缺口缺配对解答或许可阻塞，未批量导入。

## 5. 质量状态

- 全部题目通过三件套质量门：题干、答案、过程；`quality.manual_review = pending`。
- 2026-11-08 审计修复：
  - 56 道中文答案被误译（`A`→“一个”、`B`→“乙”等）已回填为源答案；翻译管线不再翻译选项字母、单变量和纯公式答案。
  - 63 道提示词泄漏：能清洗的已清洗，源文无法清除的 36 道整题剔除。
  - 45 道中英字段放反/伪译文：重新判定语种、丢弃伪译文或重译。
  - 17 道公式回填损坏：丢弃坏译文并重译。
  - 4 道 Kuttler 旧版 PageIndex：用新 staging 覆盖；其中 `r4:22` 是正常交叉引用，属审计误报。
  - 30 道 OlympiadBench HTML 标签已清洗。
  - 修复共剔除 46 道（源提示词残留 36、源公式损坏 4、质量门 6），staging 中对应条目已同步移除。
- 修复后按“保留正确翻译、删除乱码/未译/不合格”继续清理：
  - 212 道单语题无法抢救，整题删除；
  - 公式占位符嵌套 bug 修复后，76 道坏译文重译成功 72 道，失败 4 道删除；
  - 中文同时位于 `$...$` 内外导致的混合语言译文 61 道，重译成功 43 道，失败 18 道删除；
  - 最后 3 道仍夹英文的题删除。
- 最终 6,776 道全部双语，无残留 `[[M]]`、无乱码、无提示词泄漏；相对审计前共减少 283 道（7,059 → 6,776）。
- 三条人工复验的 CLP 题已按 `translation.status = reviewed`、`reviewed = true` 入库。
- 补充题说明：
  - Kuttler 只导入题型可确定的证明题（答案记为 `Proof`）与是非题（`Yes`/`No`）。
  - 需要从答案块抽取数值结果的题暂未导入，留待人工核验后补。
  - CLP 为已有导入器的解析结果，未逐题人工复算。
- 除三条人工复验题外，其余译文为机器翻译：`translation.status = machine`、`reviewed = false`。
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
  data/exercises/staging/kuttler.jsonl \
  data/exercises/staging/clp.jsonl \
  data/exercises/staging/clp2.jsonl
python tools/translate_exercises.py \
  --input data/exercises/supplement/all.jsonl \
  --output data/exercises/supplement/all.bilingual.jsonl \
  --target auto --limit 100000 --concurrency 2 --role main --resume
python tools/merge_bank.py
```

审计修复（需要审计清单 `ID_LIST.md` / `issues.csv`）：

```bash
cd backend
python tools/remediate_bank.py --ids <ID_LIST.md> --issues <issues.csv>
python tools/clean_translations.py
python tools/merge_remediated.py
```

单语抢救与坏题清理：

```bash
cd backend
python tools/rescue_translations.py \
  --input data/exercises/bilingual/rescue.queue.jsonl \
  --output data/exercises/bilingual/rescue.bilingual.jsonl
python tools/purge_untranslated.py --rescued data/exercises/bilingual/rescue.bilingual.jsonl --hold
```

## 7. 后续

1. 人工复验补充题，重点核对 Kuttler 是否题与答案块对应、CLP 数值答案。
2. 为 ode / complex / topology 寻找可分发且带完整过程的新来源。
3. 已删除的 283 道题（乱码、未译、数字/占位符校验失败）如需回补，应先修翻译或解析，再重新导入；不要直接放行校验失败译文。
