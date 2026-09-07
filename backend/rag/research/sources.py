"""
深度搜索源适配器(执行表 P1):每个源独立实现、独立超时与重试,
单源失败(网络不通 / 限流 / 超时)只记入 errors,不影响其他源。

网络实现说明:统一用 urllib + 线程池(asyncio.to_thread)。原因:
urllib 自动读取 Windows 系统代理,而 httpx 只认环境变量——arXiv 等
外网源在本机必须经系统代理才能到达(与 tools/fetch_knowledge.py 同路径)。

- arXiv:标题 + 摘要 + 作者 + 年份,带一次重试;
- Semantic Scholar:带引用数(权威性因子);代理出口常被限流(429)→ 静默跳过;
- StackExchange(math 站):评分/回答数为质量信号,可达性最稳;
- 知识库:由编排层直接调用 rag.search,不走本文件。
"""
import asyncio
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

from .types import SearchHit

UA = {"User-Agent": "MathGuide-DeepSearch/1.0"}


def _http_get(url: str, timeout: float) -> str:
    """同步 GET(线程中运行);经系统代理访问外网"""
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace")


async def search_arxiv(query: str, max_results: int = 8) -> list[SearchHit]:
    url = "http://export.arxiv.org/api/query?" + urllib.parse.urlencode({
        "search_query": f'all:"{query}"',
        "start": 0,
        "max_results": max_results,
        "sortBy": "relevance",
        "sortOrder": "descending",
    })
    ns = "{http://www.w3.org/2005/Atom}"
    for _ in range(2):  # 代理链路偏慢,重试一次
        try:
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
        except Exception:
            await asyncio.sleep(1.5)
    return []


async def search_semantic_scholar(query: str, limit: int = 8) -> list[SearchHit]:
    import json
    url = ("https://api.semanticscholar.org/graph/v1/paper/search?" + urllib.parse.urlencode({
        "query": query,
        "fields": "title,abstract,year,authors,url,citationCount",
        "limit": limit,
    }))
    try:
        data = json.loads(await asyncio.to_thread(_http_get, url, 10))
    except Exception:
        return []  # 429 限流或不可达:静默跳过
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
    try:
        data = json.loads(await asyncio.to_thread(_http_get, url, 10))
    except Exception:
        return []
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
