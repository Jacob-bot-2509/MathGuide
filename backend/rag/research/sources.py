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
import contextvars
import os
import threading
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

from .types import SearchHit

UA = {"User-Agent": "MathGuide-DeepSearch/1.0"}
# 外部源响应上限:正常 arXiv/OpenAlex 单页远小于此;防止异常/恶意响应占满内存
MAX_RESPONSE_BYTES = 2 * 1024 * 1024

# 在途响应登记:asyncio 取消线程里的 urllib 请求时,从事件循环线程
# close() 对应响应,让阻塞中的 read() 尽快抛错退出(线程池不被拖到超时)。
_cancel_token: contextvars.ContextVar[object | None] = contextvars.ContextVar(
    "mg_http_cancel_token", default=None)
_cancel_flags: dict[object, threading.Event] = {}
_inflight: dict[object, object] = {}
_inflight_lock = threading.Lock()

# 惰性读取:config.load_env() 在 main 启动时才跑,晚于本模块导入
# (此前写成模块级 os.getenv,导致 .env.local 里配的这两个值永远读不到)
def _s2_key() -> str:
    return os.getenv("MG_S2_API_KEY", "")


def _contact_mail() -> str:
    return os.getenv("MG_CONTACT_MAIL", "")


RETRIES = 2          # 外部源重试次数
BACKOFF_BASE = 1.5   # 指数退避基数(秒):1.5, 3, ...


def _http_get(url: str, timeout: float, headers: dict | None = None) -> str:
    """同步 GET(线程中运行);经系统代理访问外网,响应有大小上限。

    token 由 `_http_get_async` 通过 contextvar 注入:打开响应后登记到
    _inflight,并检查取消标志,保证外层取消时 read() 能被 close() 打断。
    """
    token = _cancel_token.get()
    cancel = _cancel_flags.get(token) if token is not None else None
    if cancel is not None and cancel.is_set():
        raise RuntimeError("request cancelled")

    req = urllib.request.Request(url, headers={**UA, **(headers or {})})
    resp = urllib.request.urlopen(req, timeout=timeout)
    try:
        if token is not None:
            with _inflight_lock:
                _inflight[token] = resp
        if cancel is not None and cancel.is_set():
            raise RuntimeError("request cancelled")
        with resp:
            raw = resp.read(MAX_RESPONSE_BYTES + 1)
        if len(raw) > MAX_RESPONSE_BYTES:
            raise ValueError(f"响应超过 {MAX_RESPONSE_BYTES} 字节上限")
        return raw.decode("utf-8", errors="replace")
    finally:
        if token is not None:
            with _inflight_lock:
                _inflight.pop(token, None)
        # 取消发生在 urlopen 返回之前时,外层已经错过这次响应(登记表里没有它),
        # 这里必须自己关掉,否则连接要等 GC 才回收。重复 close 是安全的。
        try:
            resp.close()
        except Exception:  # noqa: BLE001 已经关过/半关闭的连接可能再抛
            pass


async def _http_get_async(url: str, timeout: float, headers: dict | None = None) -> str:
    """在线程池执行 `_http_get`;协程被取消时关闭在途响应,避免线程空转到超时。"""
    token = object()
    cancel = threading.Event()
    with _inflight_lock:
        _cancel_flags[token] = cancel
    ctx_token = _cancel_token.set(token)
    try:
        return await asyncio.to_thread(_http_get, url, timeout, headers)
    finally:
        _cancel_token.reset(ctx_token)
        cancel.set()
        with _inflight_lock:
            _cancel_flags.pop(token, None)
            resp = _inflight.pop(token, None)
        if resp is not None:
            try:
                resp.close()  # 从事件循环线程关闭,唤醒线程里的阻塞 read()
            except Exception:  # noqa: BLE001 已断开的连接可能再抛,忽略
                pass


def _is_retryable(exc: Exception) -> bool:
    """4xx 里只有 408/425/429 值得重试;其余立刻放弃,别把配额浪费在必然失败的请求上。"""
    if isinstance(exc, urllib.error.HTTPError):
        return exc.code in (408, 425, 429) or exc.code >= 500
    return True


async def _retry(fn, *args, retries: int = RETRIES):
    """指数退避重试:最后一次仍失败或错误不可重试时抛出"""
    last: Exception | None = None
    for i in range(retries + 1):
        try:
            return await fn(*args)
        except Exception as exc:  # noqa: BLE001
            last = exc
            if not _is_retryable(exc):
                raise
            if i < retries:
                await asyncio.sleep(BACKOFF_BASE * (2 ** i))
    raise last  # type: ignore[misc]


async def search_arxiv(query: str, max_results: int = 8) -> list[SearchHit]:
    """query 为 arXiv 检索语法(由编排层按源特性构造,见 _query_for):
    必须用 all:"词" OR all:"词" 展开——写成整串引号短语会变成精确匹配,多词必 0 命中"""
    url = "https://export.arxiv.org/api/query?" + urllib.parse.urlencode({
        "search_query": query,
        "start": 0,
        "max_results": max_results,
        "sortBy": "relevance",
        "sortOrder": "descending",
    })
    ns = "{http://www.w3.org/2005/Atom}"

    async def _fetch():
        text = await _http_get_async(url, 15)
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
        return json.loads(await _http_get_async(url, 10, headers))

    data = await _retry(_fetch)  # 429 限流或不可达:由编排层记入 errors 后跳过
    hits: list[SearchHit] = []
    for p in data.get("data", []):
        title = (p.get("title") or "").strip()
        if not title:
            continue
        authors = ", ".join(a.get("name", "") for a in (p.get("authors") or [])[:3]
                            if isinstance(a, dict))
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
        return json.loads(await _http_get_async(url, 10))

    data = await _retry(_fetch)
    hits: list[SearchHit] = []
    for w in data.get("results", []):
        title = (w.get("display_name") or "").strip()
        if not title:
            continue
        authors = ", ".join(a.get("author", {}).get("display_name", "")
                            for a in (w.get("authorships") or [])[:3]
                            if isinstance(a, dict) and a.get("author"))
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
        return json.loads(await _http_get_async(url, 12))

    data = await _retry(_fetch)
    hits: list[SearchHit] = []
    for doc in data.get("result") or []:
        title = ((doc.get("title") or {}).get("title") or "").strip()
        # 版权受限记录的占位条目(API 会返回「contents unavailable…」),丢弃
        if not title or "zbMATH Open Web Interface contents unavailable" in title:
            continue
        contributors = doc.get("contributors")
        authors_raw = contributors.get("authors") if isinstance(contributors, dict) else []
        authors = ", ".join(a.get("name", "") for a in (authors_raw or [])[:3]
                            if isinstance(a, dict))
        contribs = [c for c in (doc.get("editorial_contributions") or [])
                    if isinstance(c, dict)]
        # 同行评论最专业;无评论时退到作者摘要,再退到出处
        best = next((c for c in contribs if c.get("contribution_type") == "review"), None) \
            or next(iter(contribs), None)
        source = doc.get("source")
        source_text = source.get("source", "") if isinstance(source, dict) else ""
        snippet = (best.get("text") if best else "") or source_text or ""
        msc_raw = doc.get("msc")
        msc = msc_raw[0] if isinstance(msc_raw, list) and msc_raw and isinstance(msc_raw[0], dict) else {}
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
        return json.loads(await _http_get_async(url, 10))

    data = await _retry(_fetch)
    hits: list[SearchHit] = []
    for item in data.get("items", []):
        title = (item.get("title") or "").strip()
        if not title:
            continue
        try:
            created = int(item.get("creation_date") or 0)
        except (TypeError, ValueError):
            created = 0
        year = datetime.fromtimestamp(created).year
        snippet = (f"评分 {item.get('score', 0)} · 回答 {item.get('answer_count', 0)}"
                   f" · 已解决 {item.get('is_answered', False)}")
        hits.append(SearchHit("StackExchange", title, snippet, "",
                              year, item.get("link") or ""))
    return hits
