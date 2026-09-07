"""
知识库采集脚本:从公开工程级数据源拉取高等数学资料,自动转为 knowledge/*.md。

用法(在 backend 目录下):
    python tools/fetch_knowledge.py --source arxiv --limit 10
    python tools/fetch_knowledge.py --source wiki --limit 20
    python tools/fetch_knowledge.py --source all --limit 10 --out knowledge

数据源:
- arxiv:arXiv API(math.* 高等数学分类,取标题+摘要,公式多为 LaTeX 原文),
  国内网络经系统代理可用,已验证;
- wiki:Wikipedia API(高等数学核心主题条目,英文站,纯文本摘要),
  需要能访问维基百科的网络(部分校园网不可达,失败会逐条跳过,不影响其他源)。

幂等:输出文件已存在则跳过;失败重跑即可续传。
"""
import argparse
import re
import sys
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

USER_AGENT = "MathGuide-KB-Fetcher/1.0 (competition demo)"

# 英文停用词:不进 keywords(与 rag/index.py STOPWORDS 同口径)
_STOPWORDS = frozenset(
    "a an the for of and on in to is are was were be been with some this that these those "
    "from by or at it its as not no we you they he she i me my our their your can will would".split()
)

# arXiv 高等数学相关分类
ARXIV_CATS = [
    "math.CA", "math.AP", "math.AT", "math.CV", "math.DG", "math.FA",
    "math.GN", "math.HO", "math.NA", "math.OA", "math.PR", "math.ST",
]
# 维基百科高等数学核心主题(英文站:国内网络经系统代理可达;主题, 板块 key)
WIKI_TOPICS = [
    ("Mathematical analysis", "analysis"), ("Calculus", "analysis"), ("Limit (mathematics)", "analysis"),
    ("Derivative", "analysis"), ("Integral", "analysis"), ("Series (mathematics)", "analysis"),
    ("Taylor series", "analysis"), ("Fourier transform", "analysis"),
    ("Differential equation", "ode"), ("Ordinary differential equation", "ode"),
    ("Partial differential equation", "ode"),
    ("Linear algebra", "algebra"), ("Matrix (mathematics)", "algebra"), ("Determinant", "algebra"),
    ("Eigenvalues and eigenvectors", "algebra"), ("Linear map", "algebra"), ("Quadratic form", "algebra"),
    ("Analytic geometry", "geometry"),
    ("Probability theory", "probability"), ("Mathematical statistics", "probability"),
    ("Normal distribution", "probability"), ("Law of large numbers", "probability"),
    ("Central limit theorem", "probability"),
    ("Complex analysis", "complex"), ("Analytic function", "complex"), ("Residue theorem", "complex"),
    ("Topology", "topology"), ("Compact space", "topology"), ("Connected space", "topology"),
    ("Homeomorphism", "topology"), ("Mean value theorem", "analysis"),
]


def http_get(url: str, timeout: int = 30) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace")


def slugify(text: str, maxlen: int = 40) -> str:
    s = re.sub(r"[^\w一-鿿]+", "-", text).strip("-")
    return s[:maxlen] or "doc"


def write_md(out_dir: Path, title: str, title_en: str, keywords: list[str],
             category: str, body: str) -> bool:
    """写入 knowledge/*.md;已存在则跳过(幂等)"""
    path = out_dir / f"{slugify(title)}.md"
    if path.exists():
        return False
    out_dir.mkdir(parents=True, exist_ok=True)
    kws = sorted({k.lower() for k in keywords if k and len(k) >= 2 and k.lower() not in _STOPWORDS})
    lines = [
        "---",
        f"title: {title}",
        f"title_en: {title_en}",
        f"keywords: {kws!r}".replace("'", '"'),
        f"category: {category}",
        "---",
        "",
        body.strip(),
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")
    print(f"  + {path.name}")
    return True


# ---------- arXiv ----------

def _arxiv_category(cat: str) -> str:
    mapping = {"math.CA": "analysis", "math.AP": "ode", "math.AT": "topology", "math.CV": "complex",
               "math.DG": "geometry", "math.FA": "analysis", "math.GN": "topology", "math.HO": "analysis",
               "math.NA": "analysis", "math.OA": "algebra", "math.PR": "probability", "math.ST": "probability"}
    return mapping.get(cat, "analysis")


def fetch_arxiv(out_dir: Path, limit: int) -> int:
    """拉取 arXiv 高等数学分类最新论文的标题+摘要"""
    added = 0
    for cat in ARXIV_CATS:
        if added >= limit:
            break
        query = urllib.parse.quote(f"cat:{cat}")
        url = f"http://export.arxiv.org/api/query?search_query={query}&start=0&max_results={min(8, limit)}&sortBy=relevance"
        print(f"[arxiv] {cat} ...")
        try:
            root = ET.fromstring(http_get(url))
        except Exception as exc:  # noqa: BLE001 网络/解析错误均可重试
            print(f"  ! {cat} failed: {exc}")
            continue
        ns = {"a": "http://www.w3.org/2005/Atom"}
        for entry in root.findall("a:entry", ns):
            if added >= limit:
                break
            title = (entry.findtext("a:title", "", ns) or "").strip().replace("\n", " ")
            summary = (entry.findtext("a:summary", "", ns) or "").strip().replace("\n", " ")
            if not title or len(summary) < 60:
                continue
            kws = re.findall(r"[A-Za-z][A-Za-z-]{2,}", title)[:8]
            if write_md(out_dir, title, title, kws + [cat], _arxiv_category(cat), summary):
                added += 1
        time.sleep(3)  # arXiv 要求 ≥3s 间隔
    return added


# ---------- Wikipedia ----------

def fetch_wiki(out_dir: Path, limit: int) -> int:
    """拉取维基百科高等数学主题条目的纯文本摘要(英文站,走系统代理)"""
    added = 0
    for topic, cat in WIKI_TOPICS:
        if added >= limit:
            break
        print(f"[wiki] {topic} ...")
        try:
            url = ("https://en.wikipedia.org/w/api.php?action=query&format=json&prop=extracts"
                   f"&exintro=1&explaintext=1&redirects=1&titles={urllib.parse.quote(topic)}")
            data = urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": USER_AGENT}),
                                          timeout=20).read().decode("utf-8")
            pages = __import__("json").loads(data)["query"]["pages"]
            text = next(iter(pages.values())).get("extract", "")
        except Exception as exc:  # noqa: BLE001 单条失败不影响整体
            print(f"  ! {topic} failed: {exc}")
            continue
        if len(text) < 40:
            print(f"  ! {topic}: empty extract")
            continue
        clean = re.sub(r"\n{2,}", "\n\n", text).strip()
        kws = re.findall(r"[A-Za-z][A-Za-z-]{2,}", topic.replace("(mathematics)", ""))[:6]
        if write_md(out_dir, topic, topic, kws + [topic.lower()], cat, clean):
            added += 1
        time.sleep(1)
    return added


def main() -> None:
    ap = argparse.ArgumentParser(description="采集公开高等数学资料 → knowledge/*.md")
    ap.add_argument("--source", choices=["arxiv", "wiki", "all"], default="all")
    ap.add_argument("--limit", type=int, default=10, help="最多新增文档数")
    ap.add_argument("--out", default=str(Path(__file__).resolve().parent.parent / "knowledge"))
    args = ap.parse_args()

    out_dir = Path(args.out)
    total = 0
    if args.source in ("arxiv", "all"):
        total += fetch_arxiv(out_dir, args.limit - total)
    if args.source in ("wiki", "all"):
        total += fetch_wiki(out_dir, args.limit - total)
    print(f"\n新增 {total} 篇文档 → {out_dir}")
    print("重启后端或直接提问即自动热重载;建议随后跑 eval_recall.py 验证命中率。")


if __name__ == "__main__":
    main()
