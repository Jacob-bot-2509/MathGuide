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
| 正确率 | 判为正确的可答题 / 已判可答题 |
| 答案级幻觉率 | 至少 1 条无依据断言的回答 / 有断言且可判的回答 |
| 断言级幻觉率 | 无依据断言数 / 总断言数 |
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
- `answerable: false`: 不可答题,`reference_answer` 留空;评审判“是否拒答”。
- `gold_chunk_ids`: 留空则不参与检索召回统计。

## 评审可信度

- 默认评审角色 `backup`(glm),与生成角色 `main`(qwen)异源;同源自评不可信。
- 评审输出 JSON,失败会记入 `health.judge_errors`,不会伪造判分。
- 评审只是模型判分。写论文/答辩前,必须人工盲标 50~100 条,算 Cohen's kappa;
  `kappa < 0.6` 时不要引用这些数字。
- 评审提示明确禁止用“数学常识”给断言背书:标准答案和检索资料没写的,一律算无依据。

## 当前限制

- 研究型问题默认跳过(需要外部检索源,评测不稳定);加 `--include-research` 才跑。
- 回答阶段串行执行(`rag.search` 捕获需要全进程 monkeypatch),检索阶段可并发。
- 数值题只比较最后一个数字;复杂公式建议用 `expr` + `\boxed{}`。
- 证明题仍靠 LLM 评审,没有符号证明器。
- 样本集很小,当前只用于框架冒烟,不能对外报准确率。
