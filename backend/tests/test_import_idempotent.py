"""数据投放脚本的幂等性:教材入库与补题合并重复执行不能产生重复行。

部署当天"脚本跑两遍"几乎是必然(断了重跑、换人重跑、Makefile 重入)。
这些脚本一旦不幂等,题库就会出现重复题、知识库里出现同名多份,
而且**没有任何报错** —— 只能靠人事后发现。所以把幂等当成契约来测。
"""
from __future__ import annotations

import json

from exercises.schema import parse_exercise
from tools import fetch_knowledge as fk
from tools import merge_bank


def _exercise(exercise_id: str, tier: str = "safe") -> dict:
    content = {
        lang: {"question": f"q-{exercise_id}", "answer": "2",
               "solution": f"Exercise {exercise_id} evaluates to 2."}
        for lang in ("zh", "en")
    }
    return parse_exercise({
        "id": exercise_id,
        "source": {"name": "Test", "tier": tier, "license": "MIT",
                   "url": "https://example.com/source", "attribution": "Test Source"},
        "original_language": "zh",
        "content": content,
        "type": "choice",
        "difficulty": 2,
        "difficulty_source": "rule",
        "primary_topic": "analysis",
        "topics": ["analysis"],
        "cross_topics": [],
        "tag_source": "rule",
    }).to_dict()


def _write_jsonl(path, items) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(item, ensure_ascii=False) + "\n" for item in items),
                    encoding="utf-8")


def _ids(path) -> list[str]:
    return [json.loads(line)["id"] for line in path.read_text(encoding="utf-8").splitlines() if line]


def test_merge_bank_is_idempotent(tmp_path):
    bank = tmp_path / "bank.jsonl"
    supplement = tmp_path / "supplement.jsonl"
    inputs = tmp_path / "input.jsonl"
    _write_jsonl(bank, [_exercise("e1")])
    _write_jsonl(supplement, [_exercise("e1"), _exercise("e2")])

    first = merge_bank.merge(bank, supplement, inputs)
    assert first["added"] == 1          # e1 已在库里,e2 才是新增
    assert first["input_added"] == 2    # 翻译输入是空文件 → 两条都进
    assert _ids(bank) == ["e1", "e2"]

    second = merge_bank.merge(bank, supplement, inputs)
    assert second["added"] == 0
    assert second["input_added"] == 0
    assert _ids(bank) == ["e1", "e2"]   # 没有重复行
    assert _ids(inputs) == ["e1", "e2"]


def test_merge_bank_dedupes_repeated_ids_inside_supplement(tmp_path):
    bank = tmp_path / "bank.jsonl"
    supplement = tmp_path / "supplement.jsonl"
    inputs = tmp_path / "input.jsonl"
    _write_jsonl(bank, [])
    _write_jsonl(supplement, [_exercise("dup"), _exercise("dup"), _exercise("other")])

    stats = merge_bank.merge(bank, supplement, inputs)
    assert stats["bank"] == 2
    assert _ids(bank) == ["dup", "other"]


def test_merge_bank_creates_missing_input_file(tmp_path):
    """首次投放时 input-all.jsonl 还不存在:不能因此崩掉,应该新建。"""
    bank = tmp_path / "bank.jsonl"
    supplement = tmp_path / "supplement.jsonl"
    inputs = tmp_path / "nested" / "input.jsonl"
    _write_jsonl(bank, [])
    _write_jsonl(supplement, [_exercise("e1")])

    merge_bank.merge(bank, supplement, inputs)
    assert inputs.is_file()
    assert _ids(inputs) == ["e1"]


def test_merge_bank_main_accepts_argv(tmp_path):
    bank = tmp_path / "bank.jsonl"
    supplement = tmp_path / "supplement.jsonl"
    inputs = tmp_path / "input.jsonl"
    _write_jsonl(bank, [])
    _write_jsonl(supplement, [_exercise("e1")])
    _write_jsonl(inputs, [])

    assert merge_bank.main(["--bank", str(bank), "--supplement", str(supplement),
                            "--input", str(inputs)]) == 0
    assert _ids(bank) == ["e1"]


def test_write_md_skips_existing_file(tmp_path):
    """教材入库:同名 md 已存在就跳过,内容不被覆盖(重跑不会翻倍也不会丢人工修订)。"""
    out = tmp_path / "knowledge"
    assert fk.write_md(out, "泰勒展开", "Taylor expansion", ["泰勒", "taylor"], "analysis", "正文一")
    path = out / "泰勒展开.md"
    assert path.is_file()
    original = path.read_text(encoding="utf-8")

    assert fk.write_md(out, "泰勒展开", "Taylor expansion", ["泰勒"], "analysis", "正文二") is False
    assert path.read_text(encoding="utf-8") == original
    assert len(list(out.glob("*.md"))) == 1
