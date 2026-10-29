"""
科研语料检索离线评测。

两种用法:
1) 对已有用户库评测:
    python tools/eval_research.py --uid u-xxx --questions eval.jsonl
2) 对样本目录一键评测(临时库,不污染正式数据):
    python tools/eval_research.py --samples D:\\Works\\research-samples

输入 JSONL,每行:
    {"question": "...", "doc": "paper.pdf", "page": 4, "pages_ok": [3, 4],
     "lang": "en", "kind": "digital"}

指标:
- Hit@k       前 k 条命中里是否出现期望论文
- PageHit     命中片段的页码是否覆盖期望页(严格按 `page`)
- PageHitAny  覆盖 `page` 或 `pages_ok` 中任意一页
- MRR         第一条命中期望论文的倒数排名

样本模式下默认只测数字版(kind=digital),因为语料库当前不支持无文本层的扫描件;
默认关闭 LLM 章节摘要,避免评测时产生额外模型费用;embedding 按 .env.local 生效,
可用 --no-embed 强制纯 BM25 对照。
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import config  # noqa: E402

config.load_env()

import research_corpus as rc  # noqa: E402


def _load_questions(path: Path) -> list[dict]:
    rows: list[dict] = []
    for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            print(f"[eval] 第 {lineno} 行不是合法 JSON,跳过")
            continue
        if isinstance(item, dict) and item.get("question"):
            rows.append(item)
    return rows


def _filter(questions: list[dict], kind: str, lang: str) -> list[dict]:
    out = questions
    if kind != "all":
        out = [q for q in out if q.get("kind") == kind]
    if lang != "all":
        out = [q for q in out if q.get("lang") == lang]
    return out


def _prepare_samples(samples: Path, questions: list[dict], *,
                     no_embed: bool, with_summary: bool) -> tuple[Path, list[str]]:
    """临时语料库:只入库评测题涉及的数字版 PDF。返回 (临时目录, 入库文档名)。"""
    pdf_dir = samples / "pdfs"
    docs = sorted({str(q.get("doc")) for q in questions if q.get("doc")})
    if not docs:
        raise SystemExit("评测集没有 doc 字段")
    missing = [d for d in docs if not (pdf_dir / d).is_file()]
    if missing:
        raise SystemExit("样本 PDF 缺失:" + ", ".join(missing[:5]))

    temp = Path(tempfile.mkdtemp(prefix="mg-eval-research-"))
    rc.DATA_DIR = temp
    rc._indexes.clear()
    rc._index_paths.clear()
    if no_embed:
        rc.embed_mod.is_configured = lambda: False  # type: ignore[assignment]
    if not with_summary:
        # 评测只测检索:跳过上传时的章节摘要 LLM 调用
        rc.llm_mod.is_configured = lambda *a, **k: False  # type: ignore[assignment]

    for i, name in enumerate(docs, 1):
        data = (pdf_dir / name).read_bytes()
        try:
            info = rc._ingest("eval", name, data, "application/pdf")
        except ValueError as exc:
            raise SystemExit(f"入库失败 {name}: {exc}") from exc
        print(f"[eval] 入库 {i}/{len(docs)} {name} "
              f"pages={info.get('pages')} chunks={info.get('chunks')}")
    return temp, docs


def run(uid: str, questions: list[dict], top_k: int, use_tree: bool) -> dict:
    index = rc._get_index(uid)
    if not index.chunks:
        raise SystemExit("论文库为空:样本模式请用 --samples,或先在科研检索页导入论文")

    hit_at_k = 0
    page_hit = 0
    page_hit_any = 0
    reciprocal = 0.0
    details: list[dict] = []
    by_lang: dict[str, dict[str, float]] = {}
    mode = ""

    for item in questions:
        question = str(item["question"])
        want_doc = item.get("doc")
        want_page = item.get("page")
        pages_ok = item.get("pages_ok") or []
        result = index.search(question, top_k=top_k, use_tree=use_tree)
        mode = result.get("mode", mode)
        hits = result["hits"]

        rank = 0
        for i, hit in enumerate(hits, 1):
            if not want_doc or hit["docName"] == want_doc:
                rank = i
                break
        if rank:
            hit_at_k += 1
            reciprocal += 1.0 / rank

        strict = False
        loose = False
        if want_doc and want_page is not None:
            wanted = {int(want_page)}
            wanted_any = wanted | {int(p) for p in pages_ok if isinstance(p, int)}
            for hit in hits:
                if hit["docName"] != want_doc:
                    continue
                span = range(hit["pageStart"], hit["pageEnd"] + 1)
                if int(want_page) in span:
                    strict = True
                if any(p in span for p in wanted_any):
                    loose = True
                if strict:
                    break
        if strict:
            page_hit += 1
        if loose:
            page_hit_any += 1

        lang = str(item.get("lang") or "?")
        bucket = by_lang.setdefault(lang, {"n": 0, "hit": 0, "page": 0})
        bucket["n"] += 1
        bucket["hit"] += 1 if rank else 0
        bucket["page"] += 1 if strict else 0

        details.append({
            "question": question,
            "lang": lang,
            "kind": item.get("kind", ""),
            "want": f"{want_doc or '*'} p.{want_page if want_page is not None else '*'}",
            "rank": rank,
            "pageHit": strict,
            "pageHitAny": loose,
            "top": [
                {"doc": h["docName"], "page": f'{h["pageStart"]}-{h["pageEnd"]}',
                 "section": h["section"], "score": h["score"]}
                for h in hits[:3]
            ],
        })

    n = max(len(questions), 1)
    for bucket in by_lang.values():
        bucket["hitAtK"] = round(bucket["hit"] / max(bucket["n"], 1), 4)
        bucket["pageHit"] = round(bucket["page"] / max(bucket["n"], 1), 4)
    return {
        "questions": len(questions),
        "hitAtK": round(hit_at_k / n, 4),
        "pageHit": round(page_hit / n, 4),
        "pageHitAny": round(page_hit_any / n, 4),
        "mrr": round(reciprocal / n, 4),
        "topK": top_k,
        "tree": use_tree,
        "mode": mode,
        "byLang": by_lang,
        "details": details,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="科研语料检索离线评测")
    parser.add_argument("--uid", help="内部 uid(backend/data/users.json);--samples 模式下不需要")
    parser.add_argument("--questions", help="JSONL 评测集;样本模式默认 samples/eval/research_eval.jsonl")
    parser.add_argument("--samples", help="样本目录(含 pdfs/ 与 eval/research_eval.jsonl)")
    parser.add_argument("--kind", default="digital", choices=("digital", "scanned(OCR)", "all"),
                        help="评测题类型,默认 digital;扫描件需 OCR 入库后才可用")
    parser.add_argument("--lang", default="all", choices=("all", "en", "zh"))
    parser.add_argument("--top-k", type=int, default=8)
    parser.add_argument("--tree", action="store_true", help="启用章节树筛选/走树")
    parser.add_argument("--no-embed", action="store_true", help="强制纯 BM25(样本模式)")
    parser.add_argument("--with-summary", action="store_true",
                        help="样本模式允许上传时调用 LLM 生成章节摘要(默认关闭)")
    parser.add_argument("--keep", action="store_true", help="保留样本模式临时库,便于排查")
    parser.add_argument("--json", action="store_true", help="输出完整 JSON")
    args = parser.parse_args()

    temp: Path | None = None
    try:
        if args.samples:
            samples = Path(args.samples)
            questions_path = Path(args.questions) if args.questions else (
                samples / "eval" / "research_eval.jsonl")
            if not questions_path.is_file():
                raise SystemExit(f"评测集不存在: {questions_path}")
            questions = _filter(_load_questions(questions_path), args.kind, args.lang)
            if not questions:
                raise SystemExit(f"没有匹配的评测题(kind={args.kind}, lang={args.lang})")
            if args.kind == "scanned(OCR)":
                raise SystemExit("样本模式暂不支持扫描件:语料库还没有 OCR 入库通道;"
                                 "请用 --kind digital,或先把 OCR 文本接入入库")
            if args.kind == "all" and any(
                    str(q.get("kind", "")).startswith("scanned") for q in questions):
                print("[eval] 扫描件暂不可入库,自动只跑数字版")
                questions = [q for q in questions
                             if not str(q.get("kind", "")).startswith("scanned")]
            temp, _ = _prepare_samples(
                samples, questions,
                no_embed=args.no_embed, with_summary=args.with_summary)
            uid = "eval"
            source = f"samples:{samples}"
        else:
            if not args.uid or not args.questions:
                raise SystemExit("非样本模式需要同时提供 --uid 与 --questions")
            path = Path(args.questions)
            if not path.is_file():
                raise SystemExit(f"评测集不存在: {path}")
            questions = _filter(_load_questions(path), args.kind, args.lang)
            if not questions:
                raise SystemExit("过滤后评测集为空")
            uid = args.uid
            source = f"uid:{uid}"

        out = run(uid, questions, max(1, args.top_k), args.tree)
    finally:
        if temp is not None and not args.keep:
            shutil.rmtree(temp, ignore_errors=True)

    if args.json:
        print(json.dumps({"source": source, **out}, ensure_ascii=False, indent=2))
        return

    print(f"来源 {source} · 问题数 {out['questions']} · Hit@{args.top_k} "
          f"{out['hitAtK']:.2%} · PageHit {out['pageHit']:.2%} · "
          f"PageHitAny {out['pageHitAny']:.2%} · MRR {out['mrr']:.3f} · "
          f"mode {out['mode']} · tree {out['tree']}")
    for lang, b in sorted(out["byLang"].items()):
        print(f"  lang={lang} n={b['n']} Hit@{args.top_k}={b['hitAtK']:.2%} "
              f"PageHit={b['pageHit']:.2%}")
    for d in out["details"]:
        flag = "✓" if d["rank"] else "✗"
        page = "P" if d["pageHit"] else ("p" if d["pageHitAny"] else "-")
        print(f"{flag}{page} rank={d['rank']} 问:{d['question'][:40]} 期望:{d['want']} "
              f"首条:{d['top'][0]['doc'] if d['top'] else '—'}")


if __name__ == "__main__":
    main()
