"""
深度搜索源适配器(执行表 P1):每个源独立实现、独立超时与指数退避重试,
单源失败(网络不通 / 限流 / 超时)只记入 errors,不影响其他源。

网络实现说明:统一用 urllib + 线程池(asyncio.to_thread)。原因:
urllib 自动读取 Windows 系统代理,而 httpx 只认环境变量——arXiv 等
外网源在本机必须经系统代理才能到达(与 tools/fetch_knowledge.py 同路径)。

- arXiv:标题 + 摘要 + 作者 + 年份;
- Semantic Scholar:带引用数(权威性因子);设 MG_S2_API_KEY 环境变量
  (semanticscholar.org 免费申请)后走专属配额,否则走公共池(常被限流);
- OpenAlex:开放学术图谱,免 key;设 MG_CONTACT_MAIL 后进礼貌池;
  部分网络下代理出口被限流(429)会自动跳过;
- StackExchange(math 站):评分/回答数为质量信号,可达性最稳;
- zbMATH Open:数学专业文献库(免 key,CC-BY-SA),带数学家同行评论(Review)
  与 MSC 分类——唯一数学专属源,命中即高度对口;
- 知识库:由编排层直接调用 rag.search,不走本文件。
"""
import asyncio
import os
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

from .types import SearchHit

UA = {"User-Agent": "MathGuide-DeepSearch/1.0"}

# 惰性读取:config.load_env() 在 main 启动时才跑,晚于本模块导入
# (此前写成模块级 os.getenv,导致 .env.local 里配的这两个值永远读不到)
def _s2_key() -> str:
    return os.getenv("MG_S2_API_KEY", "")


def _contact_mail() -> str:
    return os.getenv("MG_CONTACT_MAIL", "")


RETRIES = 2          # 外部源重试次数
BACKOFF_BASE = 1.5   # 指数退避基数(秒):1.5, 3, ...


def _http_get(url: str, timeout: float, headers: dict | None = None) -> str:
    """同步 GET(线程中运行);经系统代理访问外网"""
    req = urllib.request.Request(url, headers={**UA, **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace")


async def _retry(fn, *args, retries: int = RETRIES):
    """指数退避重试:最后一次仍失败则抛出"""
    last: Exception | None = None
    for i in range(retries + 1):
        try:
            return await fn(*args)
        except Exception as exc:  # noqa: BLE001
            last = exc
            if i < retries:
                await asyncio.sleep(BACKOFF_BASE * (2 ** i))
    raise last  # type: ignore[misc]


async def search_arxiv(query: str, max_results: int = 8) -> list[SearchHit]:
    """query 为 arXiv 检索语法(由编排层按源特性构造,见 _query_for):
    必须用 all:"词" OR all:"词" 展开——写成整串引号短语会变成精确匹配,多词必 0 命中"""
    url = "http://export.arxiv.org/api/query?" + urllib.parse.urlencode({
        "search_query": query,
        "start": 0,
        "max_results": max_results,
        "sortBy": "relevance",
        "sortOrder": "descending",
    })
    ns = "{http://www.w3.org/2005/Atom}"

    async def _fetch():
        text = await asyncio.to_thread(_http_get, url, 15)
        root = ET.fromstring(text)
        hits: list[SearchHit] = []
        for e in root.findall(f"{ns}entry"):
            title = (e.findtext(f"{ns}title", "") or "").strip().replace("\n", " ")
            summary = (e.findtext(f"{ns}summary", "") or "").strip().replace("\n", " ")
            authors = ", ".join(a.text.strip() for a in e.findall(f"{ns}author/{ns}name") if a.text)[:200]
            year = (e.findtext(f"{ns}published", "") or "")[:4]
            link = (e.findtext(f"{ns}id", "") or "").strip()
            if title:
                hits.append(SearchHit("arXiv", title, summary[:500], authors,
                                      int(year) if year.isdigit() else 0, link))
        return hits

    # 失败不再吞掉:异常上抛给编排层,由它记入 outcome.errors 并如实告知用户
    # (此前静默 return [],错误上报机制形同虚设,用户只看到"该源 0 条")
    return await _retry(_fetch)


async def search_semantic_scholar(query: str, limit: int = 8) -> list[SearchHit]:
    import json
    url = ("https://api.semanticscholar.org/graph/v1/paper/search?" + urllib.parse.urlencode({
        "query": query,
        "fields": "title,abstract,year,authors,url,citationCount",
        "limit": limit,
    }))
    key = _s2_key()
    headers = {"x-api-key": key} if key else None

    async def _fetch():
        return json.loads(await asyncio.to_thread(_http_get, url, 10, headers))

    data = await _retry(_fetch)  # 429 限流或不可达:由编排层记入 errors 后跳过
    hits: list[SearchHit] = []
    for p in data.get("data", []):
        title = (p.get("title") or "").strip()
        if not title:
            continue
        authors = ", ".join(a.get("name", "") for a in p.get("authors", [])[:3])
        hits.append(SearchHit("Semantic Scholar", title,
                              (p.get("abstract") or "")[:500], authors,
                              int(p.get("year") or 0), p.get("url") or "",
                              int(p.get("citationCount") or 0)))
    return hits


def _rebuild_abstract(inv_index: dict | None) -> str:
    """OpenAlex 摘要以倒排索引存储,重建为原文"""
    if not inv_index:
        return ""
    pos: dict[int, str] = {}
    for word, positions in inv_index.items():
        for p in positions:
            pos[p] = word
    return " ".join(pos[i] for i in sorted(pos))


async def search_openalex(query: str, limit: int = 8) -> list[SearchHit]:
    """OpenAlex:开放学术图谱,免 key;部分网络出口被限流时静默跳过"""
    import json
    params = {
        "search": query,
        "per-page": limit,
        "sort": "relevance_score:desc",
    }
    mail = _contact_mail()
    if mail:
        params["mailto"] = mail
    url = "https://api.openalex.org/works?" + urllib.parse.urlencode(params)

    async def _fetch():
        return json.loads(await asyncio.to_thread(_http_get, url, 10))

    data = await _retry(_fetch)
    hits: list[SearchHit] = []
    for w in data.get("results", []):
        title = (w.get("display_name") or "").strip()
        if not title:
            continue
        authors = ", ".join(a.get("author", {}).get("display_name", "")
                            for a in w.get("authorships", [])[:3] if a.get("author"))
        url = w.get("doi") or ""
        if url and not url.startswith("http"):
            url = f"https://doi.org/{url}"
        hits.append(SearchHit("OpenAlex", title,
                              _rebuild_abstract(w.get("abstract_inverted_index"))[:500], authors,
                              int(w.get("publication_year") or 0), url,
                              int(w.get("cited_by_count") or 0)))
    return hits


async def search_zbmath(query: str, limit: int = 8) -> list[SearchHit]:
    """zbMATH Open:数学专业文献库(免 key,2021 年起开放,CC-BY-SA)。
    特色是数学家撰写的同行评论(Review)与 MSC 分类,优先作摘要展示"""
    import json
    url = "https://api.zbmath.org/v1/document/_structured_search?" + urllib.parse.urlencode({
        "Anywhere": query,          # 字段名即 API 契约(带空格:Title/Author name/MSC 等)
        "results_per_page": limit,
        "page": 0,
    })

    async def _fetch():
        return json.loads(await asyncio.to_thread(_http_get, url, 12))

    data = await _retry(_fetch)
    hits: list[SearchHit] = []
    for doc in data.get("result") or []:
        title = ((doc.get("title") or {}).get("title") or "").strip()
        # 版权受限记录的占位条目(API 会返回「contents unavailable…」),丢弃
        if not title or "zbMATH Open Web Interface contents unavailable" in title:
            continue
        authors = ", ".join(a.get("name", "") for a in
                            (doc.get("contributors") or {}).get("authors", [])[:3])
        contribs = doc.get("editorial_contributions") or []
        # 同行评论最专业;无评论时退到作者摘要,再退到出处
        best = next((c for c in contribs if c.get("contribution_type") == "review"), None) \
            or next(iter(contribs), None)
        snippet = (best.get("text") if best else "") or \
            (doc.get("source") or {}).get("source", "") or ""
        msc = (doc.get("msc") or [{}])[0]
        if msc.get("text"):
            snippet = f"{snippet}〔MSC {msc.get('code','')}:{msc['text']}〕"
        year = str(doc.get("year") or "")
        hits.append(SearchHit("zbMATH", title, snippet[:500], authors,
                              int(year) if year.isdigit() else 0,
                              doc.get("zbmath_url") or ""))
    return hits


async def search_stackexchange(query: str, limit: int = 8) -> list[SearchHit]:
    import json
    from datetime import datetime
    url = ("https://api.stackexchange.com/2.3/search/advanced?" + urllib.parse.urlencode({
        "order": "desc",
        "sort": "relevance",
        "q": query,
        "site": "math",
        "pagesize": limit,
    }))

    async def _fetch():
        return json.loads(await asyncio.to_thread(_http_get, url, 10))

    data = await _retry(_fetch)
    hits: list[SearchHit] = []
    for item in data.get("items", []):
        title = (item.get("title") or "").strip()
        if not title:
            continue
        year = datetime.fromtimestamp(item.get("creation_date") or 0).year
        snippet = (f"评分 {item.get('score', 0)} · 回答 {item.get('answer_count', 0)}"
                   f" · 已解决 {item.get('is_answered', False)}")
        hits.append(SearchHit("StackExchange", title, snippet, "",
                              year, item.get("link") or ""))
    return hits
