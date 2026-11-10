# 评测框架(正确率 / 幻觉率 / 检索)

先只做“检索感知 + 回答判分”,不含关系图和符号验证。

## 快速开始

在 `backend/` 下:

```bash
# 1. 只测检索(不调 LLM,几乎零成本)
python tools/eval_qa.py --data evaluation/data/sample.jsonl --stage retrieval

# 2. 完整评测(生产链路回答 + 异源评审)
python tools/eval_qa.py --data evaluation/data/sample.jsonl --stage all --limit 10

# 3. 只生成不评审(省钱,人工看回答)
python tools/eval_qa.py --data evaluation/data/sample.jsonl --stage answer --no-judge
```

输出到 `backend/reports/eval_<时间>/`(已 gitignore):

- `records.jsonl`: 每条样本的检索片段、回答、客观判分、LLM 判分、延迟、错误。
- `summary.json`: 聚合指标、配置、数据集指纹。
- `report.md`: 人读报告,含分组表和失败样本。

## 指标口径

| 指标 | 定义 |
|---|---|
| 正确率 | 判为正确的可答题 / 已判可答题（优先严格客观判分：数值题只认 `\boxed{}` 或最后一个数字） |
| 宽松正确率 | 旧 numeric 规则（回答任意位置出现标准数字即算对），仅用于对照 |
| 答案级幻觉率 | 存在明确编造或矛盾断言的回答 / 可判定的回答 |
| 断言级幻觉率 | 明确编造或矛盾断言数 / 可判定断言数 |
| 不可答编造率 | 不可答题中未拒答的比例 |
| hit@k | top-k 命中任一金标片段的问题比例 |
| recall@k | top-k 命中的金标片段数 / 金标总数 |
| MRR@k | 首个金标片段排名的倒数 |

准确率与幻觉率分开报。算错但没编事实,算错误;编造定理、条件、引用,才算幻觉。

## 数据格式

JSONL,每行一条:

```json
{
  "id": "kb-taylor-01",
  "question": "什么是泰勒展开？",
  "reference_answer": "……",
  "reference_solution": "完整推导（可选，证明题判分用）",
  "answer_type": "concept",
  "domain": "泰勒展开",
  "difficulty": 2,
  "answerable": true,
  "gold_chunk_ids": ["03-taylor#1"],
  "tags": ["concept"]
}
```

- `answer_type`: `concept|numeric|expr|choice|proof|unanswerable`。
- `numeric`/`expr`/`choice`: 先走机器判分(`sympy`、数值容差、选项匹配);解析失败才交给 LLM 评审。
- `reference_solution`: 完整解答。有它时评委以完整推导为准,且**不让检索片段参与判分**(内部正确率集不把无关片段当依据)。
- `answerable: false`: 不可答题,`reference_answer` 留空;评审判”是否拒答”。
- `gold_chunk_ids`: 留空则不参与检索召回统计。

内部 400 道正确率集由 `review_packets/book_extract/build_eval_dataset.py` 生成:
`eval_correctness_400_eval.jsonl`(全量)、`eval_correctness_dev_120.jsonl`(开发集)、
`eval_correctness_test_280.jsonl`(锁定集)。评测统一传 `temperature=0`。

## 评审可信度

- 默认请求评审角色 `backup`;其不可用时可能回退到 `deep` 或 `main`。报告列出实际角色;角色不同不保证模型或提供商异源,必须核对配置。
- 评审输出 JSON,失败会记入 `health.judge_errors`,不会伪造判分。
- 评审只是模型判分。写论文/答辩前,必须人工盲标 50~100 条,算 Cohen's kappa;
  `kappa < 0.6` 时不要引用这些数字。
- 评审可依据标准解答、题目条件或可验证的数学推导判定断言;证据不足时标记 `null`,单独统计,不自动视为正确或编造。旧版 `supported=false` 包含“未找到依据”,重新汇总时按无法判定处理;新旧口径不可直接比较。

## 当前限制

- 研究型问题默认跳过(需要外部检索源,评测不稳定);加 `--include-research` 才跑。
- 回答阶段串行执行(`rag.search` 捕获需要全进程 monkeypatch),检索阶段可并发。
- 数值题支持简单分数;其他复杂表达式可能无法自动判分并需评审。没有 `\boxed{}` 时仍可能依赖最后一个数字,无法保证准确。
- 证明题仍靠 LLM 评审,没有符号证明器。
- 样本集很小,当前只用于框架冒烟,不能对外报准确率。
