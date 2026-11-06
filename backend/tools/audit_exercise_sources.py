#!/usr/bin/env python3
"""Phase-0 audit of candidate exercise-library sources.

The audit samples public data only and never imports a full dataset.  It uses
the Hugging Face datasets-server "rows" API for tabular datasets and downloads a
bounded set of MIT OCW PDFs.  Raw payloads (JSON pages and PDFs) are cached
under ``--cache`` (default ``/tmp/exercise_source_audit``) and must not be
committed.

Sources
-------
* ``math``           -- EleutherAI/hendrycks_math (test split, 7 subjects)
* ``olympiadbench``  -- Hothan/OlympiadBench (official repack, math configs)
* ``numinamath``     -- project-numina/NuminaMath-1.5, ``cn_k12`` + ``cn_contest``
* ``mit_ocw``        -- MIT OCW 18.01SC / 18.02SC / 18.03SC exercise PDFs

The three-part gate ("三件套") is: a non-empty statement, an answer, and a full
worked solution (not just an answer key).  An answer counts when it is an
explicit field, a ``\\boxed{...}`` result, or an ``Answer:`` marker.  Both a
strict count (explicit field only) and a practical count (field or deterministic
extraction) are reported; a "last line" heuristic is kept only as a diagnostic
and never counts toward the gate.

Usage
-----
    python backend/tools/audit_exercise_sources.py --source all --n 200 \
        --seed 20261106 --cache /tmp/exercise_source_audit \
        --json-out /tmp/exercise_source_audit/results.json

    # one source at a time
    python backend/tools/audit_exercise_sources.py --source math --n 200

The script is read-only with respect to the repository.  It uses only the Python
standard library; MIT OCW parsing additionally needs ``pypdf``.
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import math
import random
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

HF_ROWS = "https://datasets-server.huggingface.co/rows"
HF_SIZE = "https://datasets-server.huggingface.co/size"
OCW = "https://ocw.mit.edu"
USER_AGENT = "MathGuide-Exercise-Source-Audit/0.1 (+phase-0 read-only audit)"

CJK_RE = re.compile(r"[\u3400-\u9fff]")
LATIN_WORD_RE = re.compile(r"[A-Za-z]{2,}")
BOXED_RE = re.compile(r"\\boxed\s*\{")
ANSWER_MARK_RE = re.compile(r"(?im)^\s*(?:answer|答案|答)\s*[:：]\s*(.+)$")
NUMBERED_PROBLEM_RE = re.compile(r"(?m)^\s*Problem\s+(\d+)\s*[:.]")
EXERCISE_LABEL_RE = re.compile(r"(?<![0-9A-Za-z])(\d[A-Z]-\d+)(?:\s*,\s*(\d+))?")

LICENSES = {
    "math": ("MIT", "https://huggingface.co/datasets/EleutherAI/hendrycks_math"),
    "olympiadbench": ("Apache-2.0", "https://huggingface.co/datasets/Hothan/OlympiadBench"),
    "numinamath": ("Apache-2.0", "https://huggingface.co/datasets/project-numina/NuminaMath-1.5"),
    "mit_ocw": ("CC BY-NC-SA 4.0", "https://ocw.mit.edu/terms/"),
}

MATH_CONFIGS = [
    "algebra",
    "counting_and_probability",
    "geometry",
    "intermediate_algebra",
    "number_theory",
    "prealgebra",
    "precalculus",
]

# Math-only OlympiadBench configs.  The dataset also ships physics configs,
# which are out of scope for this ticket.
OLYMPIADBENCH_CONFIGS = [
    "OE_TO_maths_en_COMP",
    "OE_TO_maths_zh_COMP",
    "OE_TO_maths_zh_CEE",
    "OE_MM_maths_en_COMP",
    "OE_MM_maths_zh_COMP",
    "OE_MM_maths_zh_CEE",
    "TP_TO_maths_en_COMP",
    "TP_TO_maths_zh_COMP",
    "TP_TO_maths_zh_CEE",
    "TP_MM_maths_en_COMP",
    "TP_MM_maths_zh_COMP",
    "TP_MM_maths_zh_CEE",
]

# Verified interior sampling windows (not exact subset boundaries): the Hub
# dataset is ordered by source, and every fetched page is checked against the
# expected ``source`` value.  ``cn_k12`` occupies roughly rows 281k-549k and
# ``cn_contest`` roughly rows 702k-735k; the windows below stay inside both.
NUMINAMATH_RANGES = {
    "cn_k12": (290_000, 540_000),
    "cn_contest": (706_000, 730_000),
}

MIT_COURSES = {
    "18.01": "18-01sc-single-variable-calculus-fall-2010",
    "18.02": "18-02sc-multivariable-calculus-fall-2010",
    "18.03": "18-03sc-differential-equations-fall-2011",
}


# ---------------------------------------------------------------------------
# Small utilities
# ---------------------------------------------------------------------------


def log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def sha1(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:16]


def clean_text(text: Any) -> str:
    if text is None:
        return ""
    if isinstance(text, list):
        text = "\n".join(str(t) for t in text if t)
    text = str(text)
    text = (
        text.replace("\ufb01", "fi")
        .replace("\ufb02", "fl")
        .replace("\ufb00", "ff")
        .replace("\ufb03", "ffi")
        .replace("\ufb04", "ffl")
        .replace("\u00ad", "")
    )
    text = html.unescape(text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def text_stats(text: str) -> dict[str, int]:
    cjk = len(CJK_RE.findall(text))
    words = len(LATIN_WORD_RE.findall(text))
    return {"chars": len(text), "cjk_chars": cjk, "latin_words": words}


def language_of(text: str) -> str:
    st = text_stats(text)
    if st["cjk_chars"] >= 5 and st["cjk_chars"] >= max(5, st["latin_words"] // 2):
        return "zh"
    if st["latin_words"] >= 3:
        return "en"
    return "unknown"


def extract_boxed(text: str) -> str:
    """Return the last top-level ``\\boxed{...}`` content, if any."""
    last = ""
    for match in BOXED_RE.finditer(text):
        i = match.end() - 1
        depth = 0
        for j in range(i, min(len(text), i + 2000)):
            ch = text[j]
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    candidate = text[i + 1 : j].strip()
                    if candidate:
                        last = candidate
                    break
    return last


def extract_answer_marker(text: str) -> str:
    matches = [m.group(1).strip() for m in ANSWER_MARK_RE.finditer(text)]
    if matches:
        return matches[-1][:300]
    return ""


def extract_final_line(text: str) -> str:
    """Conservative final-result heuristic for worked solutions without a field."""
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    for line in reversed(lines[-4:]):
        if len(line) > 180:
            continue
        if re.search(r"(?:=|≈|→|is)\s*[^=]{1,80}$", line) and re.search(r"[0-9A-Za-z]", line):
            return line[:300]
        if re.fullmatch(r"[\(\[]?[-+]?[\d./\\√πe^ ]+[\)\]]?", line):
            return line
    return ""


def is_full_solution(text: str) -> bool:
    """A worked solution must contain a derivation, not only an answer key.

    PDF/LaTeX sources often put a whole derivation on one line, so line and
    sentence counts alone are misleading.  Length plus relational/step markers
    are used instead.
    """
    text = text.strip()
    if len(text) < 80:
        return False
    if len(text) >= 200:
        return True
    markers = len(
        re.findall(
            r"(?:=|\\le|\\ge|\\Rightarrow|\\rightarrow|→|⇒|\\therefore|"
            r"所以|因此|于是|then|thus|hence)",
            text,
        )
    )
    if markers >= 2:
        return True
    return bool(re.search(r"(?im)^\s*(?:solution|解|证明|proof)\s*[:：]", text))


def chinese_share(text: str) -> float:
    st = text_stats(text)
    total = st["cjk_chars"] + st["latin_words"]
    return st["cjk_chars"] / total if total else 0.0


def largest_remainder(weights: dict[str, int], total: int) -> dict[str, int]:
    """Allocate ``total`` proportionally to positive weights (largest remainder)."""
    positive = {k: v for k, v in weights.items() if v > 0}
    if not positive:
        return {k: 0 for k in weights}
    weight_sum = sum(positive.values())
    raw = {k: total * v / weight_sum for k, v in positive.items()}
    floors = {k: min(int(math.floor(v)), positive[k]) for k, v in raw.items()}
    remaining = total - sum(floors.values())
    order = sorted(positive, key=lambda k: (raw[k] - floors[k], positive[k]), reverse=True)
    idx = 0
    while remaining > 0:
        for k in order:
            if remaining == 0:
                break
            if floors[k] < positive[k]:
                floors[k] += 1
                remaining -= 1
        idx += 1
        if idx > 1000:
            break
    return {k: floors.get(k, 0) for k in weights}


# ---------------------------------------------------------------------------
# HTTP + cache
# ---------------------------------------------------------------------------


class Fetcher:
    def __init__(self, cache: Path, delay: float = 0.4, retries: int = 6):
        self.cache = cache
        self.cache.mkdir(parents=True, exist_ok=True)
        self.delay = delay
        self.retries = retries
        self._last = 0.0

    def _throttle(self) -> None:
        wait = self.delay - (time.time() - self._last)
        if wait > 0:
            time.sleep(wait)
        self._last = time.time()

    def _get(self, url: str, timeout: int = 60) -> bytes:
        last_err: Exception | None = None
        for attempt in range(self.retries):
            self._throttle()
            try:
                req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    return resp.read()
            except urllib.error.HTTPError as exc:
                last_err = exc
                if exc.code in (429, 500, 502, 503, 504):
                    wait = min(60, 3 * (2**attempt))
                    log(f"HTTP {exc.code}; retrying in {wait}s: {url[:120]}")
                    time.sleep(wait)
                else:
                    raise
            except Exception as exc:  # noqa: BLE001 - transient network failures
                last_err = exc
                wait = min(30, 2 * (attempt + 1))
                log(f"network error ({exc}); retrying in {wait}s")
                time.sleep(wait)
        raise RuntimeError(f"failed to fetch {url}: {last_err}")

    def json(self, url: str, key: str | None = None) -> Any:
        key = key or sha1(url)
        path = self.cache / "json" / f"{key}.json"
        if path.exists():
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                path.unlink()
        data = json.loads(self._get(url).decode("utf-8"))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        return data

    def text(self, url: str, key: str | None = None) -> str:
        key = key or sha1(url)
        path = self.cache / "html" / f"{key}.html"
        if path.exists():
            return path.read_text(encoding="utf-8", errors="replace")
        raw = self._get(url).decode("utf-8", errors="replace")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(raw, encoding="utf-8")
        return raw

    def binary(self, url: str, key: str) -> bytes:
        path = self.cache / "pdf" / f"{key}.pdf"
        if path.exists():
            return path.read_bytes()
        raw = self._get(url, timeout=120)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
        return raw


# ---------------------------------------------------------------------------
# Records
# ---------------------------------------------------------------------------


@dataclass
class Item:
    source: str
    subset: str
    item_id: str
    problem: str
    answer: str
    solution: str
    language: str
    subject: str = ""
    question_type: str = ""
    difficulty: str = ""
    has_image: bool = False
    native_bilingual: bool = False
    explicit_answer: bool = False
    answer_recovered: bool = False
    answer_heuristic: bool = False
    parse_ok: bool = True
    parse_note: str = ""
    valid_problem: bool = True
    valid_solution: bool = True
    license_name: str = ""
    license_url: str = ""

    def title(self) -> str:
        return f"{self.source}/{self.subset}/{self.item_id}"


def finalize(item: Item) -> Item:
    """Fill derived answer/statement/solution flags and parse status."""
    item.problem = clean_text(item.problem)
    item.solution = clean_text(item.solution)
    item.answer = clean_text(item.answer)
    item.language = item.language or language_of(item.problem + "\n" + item.solution)

    explicit = bool(item.answer)
    boxed = extract_boxed(item.solution)
    marker = extract_answer_marker(item.solution)
    if not item.answer:
        item.answer = boxed or marker
    recovered = bool(item.answer)
    item.explicit_answer = explicit
    item.answer_recovered = recovered
    item.answer_heuristic = bool(extract_final_line(item.solution))

    problem_len = len(re.sub(r"\s+", " ", item.problem))
    if problem_len < 20:
        item.parse_ok = False
        item.parse_note = item.parse_note or "题干为空或过短"
    return item


# ---------------------------------------------------------------------------
# Hugging Face sources
# ---------------------------------------------------------------------------


def hf_size(fetcher: Fetcher, dataset: str) -> dict[str, dict[str, int]]:
    """Return ``{config: {split: num_rows}}`` from the datasets-server size API."""
    data = fetcher.json(f"{HF_SIZE}?dataset={dataset}", key=f"size_{sha1(dataset)}")
    out: dict[str, dict[str, int]] = defaultdict(dict)
    for cfg in data.get("size", {}).get("splits", []):
        name = cfg.get("config")
        split = cfg.get("split")
        if name and split:
            out[name][split] = int(cfg.get("num_rows", 0))
    return out


def hf_rows(
    fetcher: Fetcher, dataset: str, config: str, split: str, offset: int, length: int
) -> dict[str, Any]:
    url = (
        f"{HF_ROWS}?dataset={urllib.parse.quote(dataset, safe='')}"
        f"&config={urllib.parse.quote(config, safe='')}"
        f"&split={urllib.parse.quote(split, safe='')}"
        f"&offset={offset}&length={length}"
    )
    return fetcher.json(url, key=f"rows_{sha1(url)}")


def sample_hf_config(
    fetcher: Fetcher,
    dataset: str,
    config: str,
    split: str,
    quota: int,
    total: int,
    rng: random.Random,
) -> list[dict[str, Any]]:
    """Sample ``quota`` rows from one config using bounded 100-row pages."""
    if quota <= 0 or total <= 0:
        return []
    quota = min(quota, total)
    pages_needed = max(1, math.ceil(quota / 100))
    page_count = max(1, math.ceil(total / 100))
    offsets: list[int] = []
    for page in rng.sample(range(page_count), min(pages_needed, page_count)):
        off = min(page * 100, max(0, total - 100))
        if off not in offsets:
            offsets.append(off)
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()

    def add_rows(page: dict[str, Any]) -> None:
        for row in page.get("rows", []):
            payload = row["row"]
            fingerprint = sha1(
                str(payload.get("problem", "")) + "\x00" + str(payload.get("solution", ""))
            )
            if fingerprint not in seen:
                seen.add(fingerprint)
                rows.append(payload)

    for off in offsets:
        add_rows(hf_rows(fetcher, dataset, config, split, off, min(100, total - off)))
        if len(rows) >= quota * 2 and len(rows) >= quota:
            break
    if len(rows) < quota:
        # Fall back to the first page when random pages were too short.
        add_rows(hf_rows(fetcher, dataset, config, split, 0, min(100, total)))
    return rng.sample(rows, min(quota, len(rows)))


def load_math(fetcher: Fetcher, n: int, rng: random.Random) -> list[Item]:
    dataset = "EleutherAI/hendrycks_math"
    sizes = hf_size(fetcher, dataset)
    totals = {cfg: sizes.get(cfg, {}).get("test", 0) for cfg in MATH_CONFIGS}
    quotas = largest_remainder(totals, n)
    items: list[Item] = []
    for cfg in MATH_CONFIGS:
        total = totals.get(cfg, 0)
        quota = quotas.get(cfg, 0)
        log(f"[math] {cfg}: total={total}, quota={quota}")
        for idx, row in enumerate(sample_hf_config(fetcher, dataset, cfg, "test", quota, total, rng)):
            solution = row.get("solution", "")
            items.append(
                finalize(
                    Item(
                        source="math",
                        subset=cfg,
                        item_id=f"{cfg}-{idx}-{sha1(str(row.get('problem', '')))}",
                        problem=row.get("problem", ""),
                        answer="",
                        solution=solution,
                        language="en",
                        subject=row.get("type", ""),
                        question_type="free-response",
                        difficulty=row.get("level", ""),
                        native_bilingual=False,
                        license_name=LICENSES["math"][0],
                        license_url=LICENSES["math"][1],
                    )
                )
            )
    return items


def load_olympiadbench(fetcher: Fetcher, n: int, rng: random.Random) -> list[Item]:
    dataset = "Hothan/OlympiadBench"
    sizes = hf_size(fetcher, dataset)
    totals = {cfg: sizes.get(cfg, {}).get("train", 0) for cfg in OLYMPIADBENCH_CONFIGS}
    quotas = largest_remainder(totals, n)
    items: list[Item] = []
    for cfg in OLYMPIADBENCH_CONFIGS:
        total = totals.get(cfg, 0)
        quota = quotas.get(cfg, 0)
        log(f"[olympiadbench] {cfg}: total={total}, quota={quota}")
        for idx, row in enumerate(sample_hf_config(fetcher, dataset, cfg, "train", quota, total, rng)):
            solution = clean_text(row.get("solution", []))
            answer = clean_text(row.get("final_answer", []))
            images = [row.get(f"image_{i}") for i in range(1, 10)]
            has_image = any(img not in (None, "", []) for img in images) or "<img" in row.get(
                "question", ""
            )
            language = "zh" if str(row.get("language", "")).lower().startswith("chin") else "en"
            if not row.get("language"):
                language = language_of(row.get("question", ""))
            items.append(
                finalize(
                    Item(
                        source="olympiadbench",
                        subset=cfg,
                        item_id=f"{cfg}-{row.get('id', idx)}",
                        problem=row.get("question", ""),
                        answer=answer,
                        solution=solution,
                        language=language,
                        subject=row.get("subfield", ""),
                        question_type=row.get("question_type", ""),
                        difficulty=row.get("difficulty", ""),
                        has_image=has_image,
                        native_bilingual=False,
                        license_name=LICENSES["olympiadbench"][0],
                        license_url=LICENSES["olympiadbench"][1],
                    )
                )
            )
    return items


def load_numinamath(fetcher: Fetcher, n: int, rng: random.Random) -> list[Item]:
    dataset = "project-numina/NuminaMath-1.5"
    split = "train"
    items: list[Item] = []
    for source_name, (start, end) in NUMINAMATH_RANGES.items():
        total = end - start
        quota = min(n, total)
        log(f"[numinamath] {source_name}: range={start}-{end}, quota={quota}")
        rows: list[dict[str, Any]] = []
        pages_needed = max(1, math.ceil(quota / 100))
        offsets = rng.sample(range(start, end - 100, 100), min(pages_needed, (end - start) // 100))
        for off in offsets:
            page = hf_rows(fetcher, dataset, "default", split, off, 100)
            got = page.get("rows", [])
            bad = [r for r in got if r["row"].get("source") != source_name]
            if bad:
                raise RuntimeError(
                    f"NuminaMath range drift for {source_name} at offset {off}: "
                    f"expected {source_name}, found {bad[0]['row'].get('source')}"
                )
            rows.extend(r["row"] for r in got)
        if len(rows) < quota:
            raise RuntimeError(f"NuminaMath {source_name}: only {len(rows)} rows sampled")
        for idx, row in enumerate(rng.sample(rows, quota)):
            items.append(
                finalize(
                    Item(
                        source="numinamath",
                        subset=source_name,
                        item_id=f"{source_name}-{idx}-{sha1(str(row.get('problem', '')))}",
                        problem=row.get("problem", ""),
                        answer=row.get("answer", ""),
                        solution=row.get("solution", ""),
                        language=language_of(row.get("problem", "")),
                        subject=row.get("problem_type", ""),
                        question_type=row.get("question_type", ""),
                        difficulty="competition" if source_name == "cn_contest" else "K12",
                        valid_problem=str(row.get("problem_is_valid", "yes")).lower() != "no",
                        valid_solution=str(row.get("solution_is_valid", "yes")).lower() != "no",
                        native_bilingual=False,
                        license_name=LICENSES["numinamath"][0],
                        license_url=LICENSES["numinamath"][1],
                    )
                )
            )
    return items


# ---------------------------------------------------------------------------
# MIT OCW
# ---------------------------------------------------------------------------


def ocw_resource_pdf(fetcher: Fetcher, slug_url: str) -> str | None:
    page = fetcher.text(slug_url)
    matches = re.findall(r'href="([^"]+\.pdf)"', page)
    if not matches:
        return None
    href = html.unescape(matches[0])
    return href if href.startswith("http") else OCW + href


def ocw_slugs(fetcher: Fetcher, course: str) -> list[str]:
    xml = fetcher.text(f"{OCW}/courses/{course}/sitemap.xml")
    return re.findall(r"<loc>([^<]+)</loc>", xml)


def ocw_pair_urls(fetcher: Fetcher, course: str, slugs: list[str]) -> dict[str, tuple[str, str | None]]:
    """Map a resource slug (e.g. ``mit18_01sc_pset1prb``) to (problem, solution) PDFs."""
    by_slug = {s.rstrip("/").rsplit("/", 1)[-1]: s for s in slugs}
    pairs: dict[str, tuple[str, str | None]] = {}
    for slug, url in sorted(by_slug.items()):
        match = re.match(r"^(mit18_01sc_pset\d+)(?:prb)?$", slug)
        if match:
            base = match.group(1)
            sol_slug = f"{base}sol"
            if slug.endswith("prb") and sol_slug in by_slug:
                prob_pdf = ocw_resource_pdf(fetcher, url)
                sol_pdf = ocw_resource_pdf(fetcher, by_slug[sol_slug])
                if prob_pdf:
                    pairs[slug] = (prob_pdf, sol_pdf)
        match = re.match(r"^(mit18_02sc_supprob\d+)$", slug)
        if match:
            sol_slug = slug.replace("supprob", "supprobsol")
            if sol_slug in by_slug:
                prob_pdf = ocw_resource_pdf(fetcher, url)
                sol_pdf = ocw_resource_pdf(fetcher, by_slug[sol_slug])
                if prob_pdf:
                    pairs[slug] = (prob_pdf, sol_pdf)
    return pairs


def ocw_qs_pairs(fetcher: Fetcher, course: str, slugs: list[str], per_pset: int = 3) -> list[tuple[str, str, str]]:
    """Return (label, question_pdf, solution_pdf) for 18.03 session Q/S pairs."""
    by_slug = {s.rstrip("/").rsplit("/", 1)[-1]: s for s in slugs}
    grouped: dict[str, list[str]] = defaultdict(list)
    for slug in sorted(by_slug):
        if not re.match(r"^mit18_03scf11_ps\d+.*q$", slug):
            continue
        sol_slug = slug[:-1] + "s"
        if sol_slug not in by_slug:
            continue
        pset = re.match(r"(mit18_03scf11_ps\d+)", slug).group(1)
        grouped[pset].append(slug)
    out: list[tuple[str, str, str]] = []
    for pset in sorted(grouped, key=lambda s: int(re.search(r"ps(\d+)", s).group(1))):
        grouped[pset].sort(key=lambda s: (1 if "_ii_" in s else 0, s))
        for slug in grouped[pset][:per_pset]:
            q_pdf = ocw_resource_pdf(fetcher, by_slug[slug])
            s_pdf = ocw_resource_pdf(fetcher, by_slug[slug[:-1] + "s"])
            if q_pdf and s_pdf:
                out.append((slug, q_pdf, s_pdf))
    return out


def pdf_text(fetcher: Fetcher, pdf_url: str, key: str) -> str:
    try:
        from pypdf import PdfReader
    except ImportError as exc:  # pragma: no cover
        raise SystemExit(
            "MIT OCW auditing needs pypdf. Install it with "
            "`pip install pypdf` (or skip with --source math,olympiadbench,numinamath)."
        ) from exc
    text_path = fetcher.cache / "text" / f"{key}.txt"
    if text_path.exists():
        return text_path.read_text(encoding="utf-8")
    raw = fetcher.binary(pdf_url, key=key)
    import io

    reader = PdfReader(io.BytesIO(raw))
    pages = []
    for page in reader.pages:
        try:
            pages.append(page.extract_text() or "")
        except Exception:  # noqa: BLE001 - malformed page
            pages.append("")
    text = "\n".join(pages)
    text_path.parent.mkdir(parents=True, exist_ok=True)
    text_path.write_text(text, encoding="utf-8")
    return text


MIT_HEADER_RE = re.compile(
    r"(?im)^\s*(?:"
    r"E\.\s*(?:Solutions to\s*)?18\.0[123]\s*(?:Exercises|EXERCISES)?"
    r"|S\.\s*18\.0[123]\s*Solutions to Exercises"
    r"|18\.0[123]\s*EXERCISES"
    r"|Part\s+I+\s+Problems(?:\s+and\s+Solutions)?"
    r"|OCW\s+18\.03SC"
    r"|MIT OpenCourseWare"
    r"|For information about citing these materials.*"
    r"|http://ocw\.mit\.edu(?:/terms/?)?"
    r"|18\.0[123]SC\s+.*"
    r")\s*$"
)


def clean_pdf_text(text: str) -> str:
    lines = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if MIT_HEADER_RE.match(stripped):
            continue
        if re.fullmatch(r"\d{1,3}", stripped):
            continue
        lines.append(line.rstrip())
    return "\n".join(lines)


def split_exercises(problem_text: str, solution_text: str, subset: str, course: str) -> list[Item]:
    """Split 18.01/18.02 exercise PDFs on labels such as ``1A-1``."""
    prob_matches = list(EXERCISE_LABEL_RE.finditer(problem_text))
    if not prob_matches:
        return []
    labels: list[str] = []
    prob_blocks: dict[str, str] = {}
    for i, match in enumerate(prob_matches):
        label = match.group(1)
        if label in prob_blocks:
            continue
        end = prob_matches[i + 1].start() if i + 1 < len(prob_matches) else len(problem_text)
        block = problem_text[match.end() : end].strip()
        if len(block) >= 10:
            labels.append(label)
            prob_blocks[label] = block
    if not labels:
        return []

    # PDF extraction sometimes glues the previous answer (e.g. ".../5") to the
    # next label, so solution labels are matched without the left boundary.
    sol_matches = list(re.finditer(r"(\d[A-Z]-\d+)(?:\s*,\s*(\d+))?", solution_text))
    sol_blocks: list[tuple[set[str], str]] = []
    for i, match in enumerate(sol_matches):
        end = sol_matches[i + 1].start() if i + 1 < len(sol_matches) else len(solution_text)
        block = solution_text[match.end() : end].strip()
        keys = {match.group(1)}
        if match.group(2):
            prefix = match.group(1).rsplit("-", 1)[0]
            keys.add(f"{prefix}-{match.group(2)}")
        sol_blocks.append((keys, block))
    sol_map: dict[str, str] = {}
    for keys, block in sol_blocks:
        for key in keys:
            sol_map.setdefault(key, block)

    items: list[Item] = []
    for label in labels:
        solution = sol_map.get(label, "")
        items.append(
            finalize(
                Item(
                    source="mit_ocw",
                    subset=f"{course}:{subset}",
                    item_id=label,
                    problem=prob_blocks[label],
                    answer="",
                    solution=solution,
                    language="en",
                    subject=label.rsplit("-", 1)[0],
                    question_type="exercise",
                    difficulty="",
                    native_bilingual=False,
                    license_name=LICENSES["mit_ocw"][0],
                    license_url=LICENSES["mit_ocw"][1],
                    parse_ok=True,
                    parse_note="" if solution else "题解未配对",
                )
            )
        )
    return items


def split_1803_problems(question_text: str, solution_text: str, subset: str) -> list[Item]:
    def sections(text: str) -> dict[int, str]:
        matches = list(NUMBERED_PROBLEM_RE.finditer(text))
        out: dict[int, str] = {}
        for i, match in enumerate(matches):
            end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
            num = int(match.group(1))
            block = text[match.end() : end].strip()
            if num not in out and len(block) >= 10:
                out[num] = block
        return out

    questions = sections(question_text)
    solutions = sections(solution_text)
    items: list[Item] = []
    for num, question in sorted(questions.items()):
        solution = solutions.get(num, "")
        items.append(
            finalize(
                Item(
                    source="mit_ocw",
                    subset=f"18.03:{subset}",
                    item_id=f"P{num}",
                    problem=question,
                    answer="",
                    solution=solution,
                    language="en",
                    subject="differential-equations",
                    question_type="exercise",
                    difficulty="",
                    native_bilingual=False,
                    license_name=LICENSES["mit_ocw"][0],
                    license_url=LICENSES["mit_ocw"][1],
                    parse_ok=True,
                    parse_note="" if solution else "题解未配对",
                )
            )
        )
    return items


def load_mit_ocw(fetcher: Fetcher, n: int, rng: random.Random) -> list[Item]:
    per_course = [n // 3 + (1 if i < n % 3 else 0) for i in range(3)]
    courses = list(MIT_COURSES)
    pools: dict[str, list[Item]] = {}
    for course, quota in zip(courses, per_course):
        slug = MIT_COURSES[course]
        slugs = ocw_slugs(fetcher, slug)
        log(f"[mit_ocw] {course}: {len(slugs)} sitemap URLs, target {quota}")
        pool: list[Item] = []
        if course in {"18.01", "18.02"}:
            pairs = ocw_pair_urls(fetcher, slug, slugs)
            for name, (prob_url, sol_url) in sorted(pairs.items()):
                prob_text = clean_pdf_text(pdf_text(fetcher, prob_url, f"{course}_{name}_prb"))
                sol_text = clean_pdf_text(pdf_text(fetcher, sol_url, f"{course}_{name}_sol")) if sol_url else ""
                pool.extend(split_exercises(prob_text, sol_text, name, course))
                log(f"[mit_ocw] {course}/{name}: pool={len(pool)}")
        else:
            pairs = ocw_qs_pairs(fetcher, slug, slugs, per_pset=3)
            for name, q_url, s_url in pairs:
                q_text = clean_pdf_text(pdf_text(fetcher, q_url, f"{course}_{name}_q"))
                s_text = clean_pdf_text(pdf_text(fetcher, s_url, f"{course}_{name}_s"))
                pool.extend(split_1803_problems(q_text, s_text, name))
                log(f"[mit_ocw] {course}/{name}: pool={len(pool)}")
        pools[course] = pool
        log(f"[mit_ocw] {course}: parsed pool={len(pool)}")
    items: list[Item] = []
    for course, quota in zip(courses, per_course):
        pool = pools[course]
        if len(pool) < quota:
            log(f"[mit_ocw] WARNING {course}: only {len(pool)} parsed problems for quota {quota}")
        items.extend(rng.sample(pool, min(quota, len(pool))))
    return items


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------


def is_zh(item: Item) -> bool:
    return chinese_share(item.problem + "\n" + item.solution) >= 0.2


def item_missing_reason(item: Item) -> str:
    if not item.parse_ok:
        return item.parse_note or "解析失败"
    if not item.valid_problem or not item.valid_solution:
        return "数据质量标记为无效"
    if len(item.problem.strip()) < 20:
        return "题干缺失/过短"
    if not item.solution or len(item.solution.strip()) < 40:
        return "过程缺失（含题解未配对）"
    if not item.explicit_answer and not item.answer_recovered:
        return "答案无法抽取"
    if not is_full_solution(item.solution):
        return "过程过短/疑似仅答案（启发式）"
    return ""


def summarize(items: list[Item], source: str) -> dict[str, Any]:
    subset_items: dict[str, list[Item]] = defaultdict(list)
    for item in items:
        subset_items[item.subset].append(item)

    def block(rows: list[Item]) -> dict[str, Any]:
        n = len(rows)
        if not n:
            return {"n": 0}
        parse_ok = sum(r.parse_ok and len(r.problem.strip()) >= 20 for r in rows)
        explicit = sum(r.explicit_answer for r in rows)
        recovered = sum(r.answer_recovered for r in rows)
        solutions = sum(bool(r.solution.strip()) and len(r.solution.strip()) >= 40 for r in rows)
        full = sum(is_full_solution(r.solution) for r in rows)
        triple_strict = sum(
            r.parse_ok
            and len(r.problem.strip()) >= 20
            and r.explicit_answer
            and is_full_solution(r.solution)
            for r in rows
        )
        triple_practical = sum(
            r.parse_ok
            and len(r.problem.strip()) >= 20
            and r.answer_recovered
            and is_full_solution(r.solution)
            for r in rows
        )
        reasons = Counter(item_missing_reason(r) for r in rows)
        reasons.pop("", None)
        zh = sum(is_zh(r) for r in rows)
        bilingual = sum(r.native_bilingual for r in rows)
        per_item_license = 0  # none of the audited sources has a per-item license field
        with_image = sum(r.has_image for r in rows)
        embedded_only = sum(r.answer_recovered and not r.explicit_answer for r in rows)
        solution_end_result = sum(r.answer_heuristic for r in rows)
        invalid_flags = sum(not (r.valid_problem and r.valid_solution) for r in rows)
        st = [text_stats(r.problem + "\n" + r.solution) for r in rows]
        en_words = sum(s["latin_words"] for s in st)
        zh_chars = sum(s["cjk_chars"] for s in st)
        # Translation volume: translate English sources to Chinese, Chinese to English.
        translate_en_tokens = sum(
            s["latin_words"] * 1.33 for s, r in zip(st, rows) if not is_zh(r)
        )
        translate_zh_tokens = sum(s["cjk_chars"] * 1.0 for s, r in zip(st, rows) if is_zh(r))
        translate_tokens = int(round(translate_en_tokens + translate_zh_tokens))
        return {
            "n": n,
            "parse_ok_rate": parse_ok / n,
            "explicit_answer_rate": explicit / n,
            "recoverable_answer_rate": recovered / n,
            "answer_embedded_only_rate": embedded_only / n,
            "solution_end_result_rate": solution_end_result / n,
            "invalid_flag_rate": invalid_flags / n,
            "solution_rate": solutions / n,
            "full_solution_rate": full / n,
            "triple_strict_rate": triple_strict / n,
            "triple_practical_rate": triple_practical / n,
            "missing_reasons": dict(reasons.most_common()),
            "native_bilingual_rate": bilingual / n,
            "zh_rate": zh / n,
            "per_item_license_rate": per_item_license / n,
            "image_rate": with_image / n,
            "en_words": en_words,
            "zh_chars": zh_chars,
            "translate_en_tokens": int(round(translate_en_tokens)),
            "translate_zh_tokens": int(round(translate_zh_tokens)),
            "translate_tokens": translate_tokens,
            "translation_cost_usd_economy": translate_tokens / 1e6 * 0.87,
            "translation_cost_usd_quality": translate_tokens / 1e6 * 14.5,
            "avg_problem_chars": sum(len(r.problem) for r in rows) / n,
            "avg_solution_chars": sum(len(r.solution) for r in rows) / n,
            "subjects": dict(Counter(r.subject for r in rows if r.subject).most_common(10)),
            "question_types": dict(Counter(r.question_type for r in rows if r.question_type).most_common(10)),
            "difficulties": dict(Counter(r.difficulty for r in rows if r.difficulty).most_common(10)),
            "languages": dict(Counter(r.language for r in rows).most_common()),
        }

    overall = block(items)
    overall["source"] = source
    overall["license"] = LICENSES.get(source, ("", ""))[0]
    overall["license_url"] = LICENSES.get(source, ("", ""))[1]
    overall["subsets"] = {name: block(rows) for name, rows in sorted(subset_items.items())}
    return overall


# ---------------------------------------------------------------------------
# Markdown output
# ---------------------------------------------------------------------------


def pct(value: float) -> str:
    return f"{100 * value:.1f}%"


def render_markdown(results: dict[str, Any], args: argparse.Namespace) -> str:
    lines: list[str] = []
    lines.append("# 习题库来源审计（阶段 0）\n")
    lines.append(
        f"> 自动生成：seed={args.seed}，每个来源抽样 n={args.n}；"
        f"原始数据缓存在 `{args.cache}`，未提交。\n"
    )
    lines.append("## 总览\n")
    lines.append(
        "| 来源 | 样本 | 可解析率 | 答案字段 | 答案可抽取 | 三件套(严格) | 三件套(实用) | 原生双语 | 中文占比 | 许可字段 |"
    )
    lines.append("|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    labels = {
        "math": "MATH",
        "olympiadbench": "OlympiadBench",
        "numinamath_cn_k12": "NuminaMath cn_k12",
        "numinamath_cn_contest": "NuminaMath cn_contest",
        "mit_ocw": "MIT OCW",
    }
    for key, label in labels.items():
        data = results["sources"].get(key)
        if not data:
            continue
        lines.append(
            f"| {label} | {data['n']} | {pct(data['parse_ok_rate'])} | "
            f"{pct(data['explicit_answer_rate'])} | {pct(data['recoverable_answer_rate'])} | "
            f"{pct(data['triple_strict_rate'])} | {pct(data['triple_practical_rate'])} | "
            f"{pct(data['native_bilingual_rate'])} | {pct(data['zh_rate'])} | "
            f"{pct(data['per_item_license_rate'])} |"
        )
    lines.append("")
    lines.append("## 缺失原因\n")
    for key, label in labels.items():
        data = results["sources"].get(key)
        if not data:
            continue
        reasons = data.get("missing_reasons", {})
        text = "；".join(f"{k}: {v}" for k, v in reasons.items()) or "无"
        lines.append(f"- **{label}**（样本 {data['n']}）：{text}")
    lines.append("")
    lines.append("## 分布\n")
    for key, label in labels.items():
        data = results["sources"].get(key)
        if not data:
            continue
        lines.append(f"### {label}\n")
        lines.append(f"- 板块/主题：`{data.get('subjects', {})}`")
        lines.append(f"- 题型：`{data.get('question_types', {})}`")
        lines.append(f"- 难度：`{data.get('difficulties', {})}`")
        lines.append(f"- 语言：`{data.get('languages', {})}`")
        lines.append("")
    lines.append("## 翻译预估\n")
    lines.append("| 来源 | 英文词数/样本 | 中文字数/样本 | 英→中 tokens/样本 | 中→英 tokens/样本 |")
    lines.append("|---|---:|---:|---:|---:|")
    for key, label in labels.items():
        data = results["sources"].get(key)
        if not data:
            continue
        lines.append(
            f"| {label} | {data.get('en_words', 0)} | {data.get('zh_chars', 0)} | "
            f"{data.get('translate_en_tokens', 0)} | {data.get('translate_zh_tokens', 0)} |"
        )
    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source",
        default="all",
        help="comma-separated: all, math, olympiadbench, numinamath, mit_ocw",
    )
    parser.add_argument("--n", type=int, default=200, help="sample size per source (default 200)")
    parser.add_argument("--seed", type=int, default=20261106)
    parser.add_argument("--cache", default="/tmp/exercise_source_audit")
    parser.add_argument("--json-out", default=None)
    parser.add_argument("--markdown-out", default=None)
    parser.add_argument(
        "--items-out",
        default=None,
        help="optional JSONL of normalized sampled items (derived data only)",
    )
    parser.add_argument("--delay", type=float, default=0.4, help="HTTP delay between requests")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    cache = Path(args.cache)
    fetcher = Fetcher(cache, delay=args.delay)
    rng = random.Random(args.seed)

    requested = args.source.split(",")
    if "all" in requested:
        requested = ["math", "olympiadbench", "numinamath", "mit_ocw"]
    if args.n <= 0:
        raise SystemExit("--n must be positive")
    known = {"math", "olympiadbench", "numinamath", "mit_ocw"}
    unknown = [name for name in requested if name not in known]
    if unknown:
        raise SystemExit(f"unknown --source value(s): {', '.join(unknown)}")

    items: dict[str, list[Item]] = {}
    if "math" in requested:
        items["math"] = load_math(fetcher, args.n, rng)
    if "olympiadbench" in requested:
        items["olympiadbench"] = load_olympiadbench(fetcher, args.n, rng)
    if "numinamath" in requested:
        nm = load_numinamath(fetcher, args.n, rng)
        items["numinamath_cn_k12"] = [i for i in nm if i.subset == "cn_k12"]
        items["numinamath_cn_contest"] = [i for i in nm if i.subset == "cn_contest"]
    if "mit_ocw" in requested:
        items["mit_ocw"] = load_mit_ocw(fetcher, args.n, rng)

    results: dict[str, Any] = {"meta": vars(args), "sources": {}}
    for source, rows in items.items():
        results["sources"][source] = summarize(rows, source)

    if args.items_out:
        items_path = Path(args.items_out)
        items_path.parent.mkdir(parents=True, exist_ok=True)
        with items_path.open("w", encoding="utf-8") as handle:
            for source_rows in items.values():
                for item in source_rows:
                    handle.write(json.dumps(item.__dict__, ensure_ascii=False) + "\n")
        log(f"[audit] wrote {items_path}")

    results_path = Path(args.json_out) if args.json_out else cache / "results.json"
    results_path.parent.mkdir(parents=True, exist_ok=True)
    results_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    log(f"[audit] wrote {results_path}")

    markdown = render_markdown(results, args)
    markdown_path = Path(args.markdown_out) if args.markdown_out else cache / "summary.md"
    markdown_path.write_text(markdown, encoding="utf-8")
    log(f"[audit] wrote {markdown_path}")
    print(markdown)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
