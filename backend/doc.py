"""文档导出:LLM 结构化重组 → HTML(内嵌 KaTeX)→ Edge headless 转 PDF → 一次性下载。

数据流:前端把研究综述全文(含引用区)传来 → deep 模型按 schema 重组为结构化
JSON(中/英按 lang)→ 灌进 HTML 模板(公式以 \\(...\\) / $$..$$ 标记,由页内
KaTeX 渲染)→ 系统自带 msedge headless 打印成 PDF → 响应字节流,不落盘存档。

选型备注(见 doc-export 规划):不接真 LaTeX(LLM 输出不可控,TeX 严格编译,
管线脆弱);headless 用 Windows 自带 Edge,零安装;KaTeX 资源直接复用
frontend/node_modules 里的同一份,渲染行为与聊天页完全一致。
"""
from __future__ import annotations

import asyncio
import contextlib
import functools
import html as html_mod
import json
import os
import re
import secrets
import shutil
import subprocess
import tempfile
import threading
import time
from pathlib import Path

from starlette.requests import Request
from starlette.responses import JSONResponse, Response

import math_render
import rag.llm as llm
from chat import _rate_check, _record, require_auth
from http_utils import read_json_object
from log import get_logger

log = get_logger(__name__)

# 浏览器:本机 Windows 自带 Edge;Linux 服务器装 chromium。
# 查找优先级:MG_EDGE_PATH(部署时显式指定)→ 系统已知路径 → PATH 里的常见命令名。
_EDGE_CANDIDATES = (
    Path("C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe"),
    Path("C:/Program Files/Microsoft/Edge/Application/msedge.exe"),
    # Linux 服务器常见位置(apt / snap / rpm 各不同)
    Path("/usr/bin/chromium"),
    Path("/usr/bin/chromium-browser"),
    Path("/usr/bin/google-chrome"),
    Path("/usr/bin/microsoft-edge"),
    Path("/snap/bin/chromium"),
)
_EDGE_COMMANDS = (
    "msedge",
    "chromium",
    "chromium-browser",
    "google-chrome",
    "microsoft-edge",
)


def _find_edge() -> str | None:
    """返回可用的 headless 浏览器可执行文件;找不到返回 None。

    `MG_EDGE_PATH` 是部署开关:服务器上指定一次(例如容器内 `/usr/bin/chromium`)即可,
    不必依赖命令名是否在 PATH 里。**显式配置了但文件不存在时直接返回 None**,
    不做兜底 —— 否则配错了会悄悄用别的浏览器,产出的 PDF 和预期不一致却查不出原因。
    """
    configured = (os.getenv("MG_EDGE_PATH") or "").strip()
    if configured:
        path = Path(configured)
        return str(path) if path.is_file() else None
    for candidate in _EDGE_CANDIDATES:
        if candidate.is_file():
            return str(candidate)
    for name in _EDGE_COMMANDS:
        found = shutil.which(name)
        if found:
            return found
    return None

# KaTeX 静态资源:优先后端自带副本(便于只部署 backend),否则复用前端 node_modules。
# 两处目录结构都是 katex.min.css / katex.min.js。
_KATEX_CANDIDATES = (
    Path(__file__).resolve().parent / "static" / "katex",
    Path(__file__).resolve().parent.parent / "frontend" / "node_modules" / "katex" / "dist",
)


def _katex_dir() -> Path:
    for candidate in _KATEX_CANDIDATES:
        if (candidate / "katex.min.js").is_file():
            return candidate
    return _KATEX_CANDIDATES[-1]


CONTENT_MAX = 32000  # 与聊天输入上限一致


def _system_prompt(lang: str) -> str:
    schema = ('{"title": str, "abstract": str, "keywords": [str], '
              '"sections": [{"heading": str, "paragraphs": [str]}], '
              '"references": [{"id": int, "title": str, "source": str, "url": str}]}')
    if lang == "en":
        return (
            "You are an academic survey writer. Reorganize the provided research "
            "summary into a strictly valid JSON object — no markdown fences, no "
            f"commentary, JSON only. Schema: {schema}. Write in English. "
            "Keep every fact, number and reference from the input; never fabricate. "
            "Inline formulas in \\(...\\), display formulas in $$...$$. "
            "3 to 6 sections; abstract under 120 words; keywords 3 to 6."
        )
    return (
        "你是学术综述撰写助手。把用户提供的检索综述整理成严格合法的 JSON 对象"
        "——不要 markdown 代码块、不要任何解释,只输出 JSON。"
        f"schema:{schema}。用中文撰写。"
        "保持原文的事实、数据与引用对应关系,绝不虚构;引用编号与来源保持不变。"
        "段落中的行内公式用 \\(...\\) 包裹,块级公式用 $$...$$。"
        "sections 3~6 个,abstract 150 字以内,keywords 3~6 个。"
    )


def _extract_json(text: str) -> dict | None:
    """从 LLM 输出里抠出 JSON(容忍前后杂音与代码块围栏)"""
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        return None
    for candidate in (text[start:end + 1], text):
        try:
            obj = json.loads(candidate)
        except (json.JSONDecodeError, TypeError):
            continue
        if isinstance(obj, dict) and "sections" in obj:
            return obj
    return None


def _fallback_doc(content: str, lang: str) -> dict:
    """LLM 重组失败时的降级排版:原文按空行分段,保证用户永远拿得到文件"""
    title = "Research Summary" if lang == "en" else "研究综述"
    paras = [p.strip() for p in re.split(r"\n\s*\n", content) if p.strip()]
    return {
        "title": title,
        "abstract": "",
        "keywords": [],
        "sections": [{"heading": title, "paragraphs": paras or [content]}],
        "references": [],
    }


def _safe_url(value: object) -> str:
    """只允许 http(s) 外链:LLM 输出不可信,file:/javascript: 等一律丢弃。"""
    url = str(value or "").strip()[:500]
    return url if re.match(r"^https?://", url, re.IGNORECASE) else ""


def _as_list(value: object) -> list:
    return value if isinstance(value, list) else []


def _normalize_doc(obj: dict, content: str, lang: str) -> dict:
    """把 LLM 输出规整为渲染所需的最小合法结构(缺什么补什么)。
    这里同时是安全边界:id 必须是整数(渲染时还会转义),URL 只留 http(s)。"""
    title = str(obj.get("title") or "").strip()[:120] or (
        "Research Summary" if lang == "en" else "研究综述")
    abstract = str(obj.get("abstract") or "").strip()

    raw_keywords = obj.get("keywords")
    if isinstance(raw_keywords, str):
        raw_keywords = [raw_keywords]
    elif not isinstance(raw_keywords, list):
        raw_keywords = []
    keywords = [str(k).strip()[:40] for k in raw_keywords if str(k).strip()][:8]

    sections = []
    for s in _as_list(obj.get("sections")):
        if not isinstance(s, dict):
            continue
        heading = str(s.get("heading") or "").strip()[:100]
        paras = [str(p).strip() for p in _as_list(s.get("paragraphs"))
                 if str(p).strip()]
        if paras:
            sections.append({"heading": heading or title, "paragraphs": paras})
    if not sections:
        sections = [{"heading": title, "paragraphs": [content]}]

    refs = []
    for r in _as_list(obj.get("references")):
        if not isinstance(r, dict):
            continue
        try:
            ref_id = int(r.get("id"))
        except (TypeError, ValueError):
            ref_id = 0
        if ref_id <= 0:
            ref_id = len(refs) + 1
        ref = {
            "id": ref_id,
            "title": str(r.get("title") or "").strip()[:300],
            "source": str(r.get("source") or "").strip()[:40],
            "url": _safe_url(r.get("url")),
        }
        if ref["title"]:
            refs.append(ref)
    return {
        "title": title, "abstract": abstract, "keywords": keywords,
        "sections": sections, "references": refs,
    }


# 公式分隔:块级 $$..$$ 优先,行内 \(..\) 与 $..$(后位非数字,防金额误判)与 MathText 同口径
def _render_math(html_safe: str) -> str:
    result = []
    for is_math, display, value in math_render.segments(html_safe):
        if is_math:
            value = html_mod.escape(math_render.prepare(html_mod.unescape(value)))
            result.append(f'<span class="{"mg-mathd" if display else "mg-math"}">{value}</span>')
        else:
            result.append(value)
    return "".join(result)


def _render_html(doc: dict, lang: str, katex_dir: Path, brand: str | None = None) -> str:
    zh = lang != "en"
    css = (katex_dir / "katex.min.css").as_uri()
    js = (katex_dir / "katex.min.js").as_uri()
    array_js = (katex_dir.parent / "math_arrays.js").as_uri()
    nonce = secrets.token_hex(16)  # 只放行本页内联脚本;注入的 <script> 没有 nonce
    render_macros = {**math_render.MACROS, r"\knowl": r"\def\mgIgnore##1{}\mgIgnore{#1}#2"}

    def esc(s: str) -> str:
        return html_mod.escape(s)

    secs = []
    for s in doc["sections"]:
        paras = "\n".join(
            f"<p>{_render_math(esc(p))}</p>" for p in s["paragraphs"])
        secs.append(f'<section><h2>{_render_math(esc(s["heading"]))}</h2>{paras}</section>')

    refs = ""
    if doc["references"]:
        def ref_line(r: dict) -> str:
            url = _safe_url(r.get("url"))  # 纵深防御:绕过 _normalize_doc 也过滤 scheme
            item = (f'<li>[{esc(str(r.get("id", "")))}] '
                    f'{esc(str(r.get("title", "")))} — {esc(str(r.get("source", "")))}')
            if url:
                item += f' <a href="{esc(url)}" rel="noreferrer">{esc(url)}</a>'
            return item + "</li>"

        items = "\n".join(ref_line(r) for r in doc["references"])
        refs = f'<section class="refs"><h2>{"References" if not zh else "参考文献"}</h2><ol>{items}</ol></section>'

    meta_block = ""
    if doc["abstract"]:
        meta_block += (f'<div class="abstract"><strong>'
                       f'{"Abstract" if not zh else "摘要"}:</strong> '
                       f'{_render_math(esc(doc["abstract"]))}</div>')
    if doc["keywords"]:
        meta_block += (f'<div class="keywords"><strong>'
                       f'{"Keywords" if not zh else "关键词"}:</strong> '
                       f'{esc("、".join(doc["keywords"]) if zh else ", ".join(doc["keywords"]))}</div>')

    date_str = time.strftime("%Y-%m-%d")
    lang_attr = "en" if not zh else "zh-CN"
    brand_text = brand or ("SURVEY" if not zh else "研究综述")
    font_stack = ("Georgia, 'Times New Roman', serif" if not zh
                  else "'Microsoft YaHei', 'PingFang SC', 'Noto Sans CJK SC', sans-serif")

    return f"""<!DOCTYPE html>
<html lang="{lang_attr}">
<head>
<meta charset="utf-8">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src data:; style-src 'unsafe-inline' file:; script-src 'nonce-{nonce}' file:; font-src file: data:; base-uri 'none'; form-action 'none'">
<title>{esc(doc["title"])}</title>
<link rel="stylesheet" href="{css}">
<style>
  :root {{ --ink: #1a1f2b; --dim: #556; --line: #d8dce6; }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0; padding: 40px 44px;
    font-family: {font_stack};
    color: var(--ink); font-size: 13px; line-height: 1.75;
  }}
  .cover {{ text-align: left; border-bottom: 2px solid var(--ink); padding-bottom: 18px; margin-bottom: 26px; }}
  .cover h1 {{ font-size: 24px; line-height: 1.35; margin: 0 0 10px; }}
  .cover .brand {{ font-size: 10px; letter-spacing: 0.25em; color: var(--dim); text-transform: uppercase; }}
  .cover .date {{ font-size: 11px; color: var(--dim); margin-top: 6px; }}
  .abstract, .keywords {{ font-size: 12px; color: var(--dim); margin-top: 8px; }}
  section {{ margin: 0 0 22px; page-break-inside: auto; }}
  h2 {{ font-size: 16px; margin: 0 0 10px; padding-left: 10px; border-left: 3px solid #2563eb; }}
  p {{ margin: 0 0 10px; text-align: justify; }}
  .refs {{ font-size: 11.5px; color: var(--dim); }}
  .refs ol {{ padding-left: 22px; }}
  .refs li {{ margin-bottom: 5px; }}
  .refs a {{ color: #2563eb; word-break: break-all; }}
  .mg-mathd {{ display: block; margin: 12px 0; overflow-x: auto; text-align: center; }}
  .katex {{ font-size: 1.08em; }}
  @page {{ size: A4; margin: 18mm 16mm; }}
</style>
</head>
<body>
  <div class="cover">
    <div class="brand">MATHGUIDE · {esc(brand_text)}</div>
    <h1>{_render_math(esc(doc["title"]))}</h1>
    <div class="date">{"Generated by MathGuide" if not zh else "由 MathGuide 生成"} · {date_str}</div>
    {meta_block}
  </div>
  {''.join(secs)}
  {refs}
  <script nonce="{nonce}" src="{js}"></script>
  <script nonce="{nonce}" src="{array_js}"></script>
  <script nonce="{nonce}">
    const mathMacros = {json.dumps(render_macros, ensure_ascii=True)};
    function renderFormula(el, display) {{
      const source = el.textContent;
      try {{ katex.render(source, el, {{ displayMode: display, throwOnError: true, macros: Object.assign({{}}, mathMacros) }}); }}
      catch (e) {{
        try {{
          const table = MGMathArrays.renderMathArray(source, cell => katex.renderToString(cell,
            {{throwOnError: true, macros: Object.assign({{}}, mathMacros)}}));
          if (table) {{ el.innerHTML = table; return; }}
        }} catch (ignored) {{}}
        el.textContent = source;
      }}
    }}
    document.querySelectorAll('.mg-math').forEach(el => renderFormula(el, false));
    document.querySelectorAll('.mg-mathd').forEach(el => renderFormula(el, true));
  </script>
</body>
</html>"""


PDF_TIMEOUT_DEFAULT = 120.0  # 秒;低配 VPS 上 60s 会误杀长文档,可用 MG_PDF_TIMEOUT 覆盖


def _pdf_timeout() -> float:
    raw = (os.getenv("MG_PDF_TIMEOUT") or "").strip()
    if not raw:
        return PDF_TIMEOUT_DEFAULT
    try:
        return max(10.0, float(raw))
    except ValueError:
        return PDF_TIMEOUT_DEFAULT


def _edge_compat_flags() -> tuple[str, ...]:
    """容器/CI 上 Chromium"有二进制但打印不出 PDF"的补救参数。

    Ubuntu 23.10+ 默认 `kernel.apparmor_restrict_unprivileged_userns=1`,非 root 起不来
    sandbox,浏览器直接退出(命令返回非 0、没有产物)。生产渲染的是模型生成内容,
    沙箱该留着,所以**不默认关**,只留显式开关。
    """
    raw = (os.getenv("MG_EDGE_NO_SANDBOX") or "").strip().lower()
    if raw in ("1", "true", "yes", "on"):
        return ("--no-sandbox", "--disable-dev-shm-usage")
    return ()


def _stderr_tail(proc: object, limit: int = 300) -> str:
    """取浏览器 stderr 尾部:不产出 PDF 时,真正的原因只在这里。"""
    raw = getattr(proc, "stderr", None) or b""
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8", "replace")
    return " ".join(str(raw).split())[-limit:]


# --- 导出并发闸门 -----------------------------------------------------------
# 每次导出都会起一个 headless 浏览器进程(实测单个常驻/峰值 100–300MB)。N 个用户
# 同时点导出 = N 个浏览器,低配 VPS 会被直接打穿 —— 表现不是"导出变慢",而是 OOM
# 把整个 uvicorn 带走,所有人都用不了。所以给"同时启动的浏览器数"设硬上限:
# 超出的请求进有限队列,队列也满就**立刻**回 429(带 Retry-After),绝不无限排队
# (排队不花内存,但用户的连接会挂住,到最后还是超时,不如早点说清楚)。
#
# 为什么闸门放在 `_html_to_pdf` 里面:它是所有导出路径(综述导出、问答/组卷导出、
# Word 数组公式转图)唯一的浏览器出口。放在路由上,新加一条导出接口就会漏。
PDF_CONCURRENCY_DEFAULT = 2
PDF_QUEUE_DEFAULT = 8
PDF_QUEUE_WAIT_DEFAULT = 15.0


class PdfBusy(RuntimeError):
    """导出并发已满:调用方应回 429(带 Retry-After),不要继续起浏览器。

    刻意**不**返回 None:None 在调用链里等于"渲染失败"(各调用方会降级/报 500),
    而这里既不是渲染失败、也不该降级 —— 用户等一会儿重试就能成。
    """

    retry_after = 20  # 秒;给前端/运维一个明确的"多久后再试"


def _env_number(name: str, default: float, low: float, high: float) -> float:
    """读数值型环境变量并夹到 [low, high];写错(拼错/负数)按默认值处理。"""
    raw = (os.getenv(name) or "").strip()
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError:
        log.warning(f"[doc] {name}={raw!r} 不是数字,按默认 {default} 处理")
        return default
    return min(max(value, low), high)


def pdf_concurrency_limit() -> int:
    """同时允许启动的浏览器数(MG_PDF_CONCURRENCY,默认 2,夹到 1–8)。"""
    return int(_env_number("MG_PDF_CONCURRENCY", PDF_CONCURRENCY_DEFAULT, 1, 8))


def pdf_queue_limit() -> int:
    """允许排队等浏览器的请求数(MG_PDF_QUEUE,默认 8,夹到 0–32;0 = 不排队)。"""
    return int(_env_number("MG_PDF_QUEUE", PDF_QUEUE_DEFAULT, 0, 32))


def pdf_queue_wait() -> float:
    """单个请求最多排队等多少秒(MG_PDF_QUEUE_WAIT,默认 15,夹到 0–120)。"""
    return _env_number("MG_PDF_QUEUE_WAIT", PDF_QUEUE_WAIT_DEFAULT, 0.0, 120.0)


class _PdfGate:
    """计数型信号量 + 有限队列(标准库没有"队列满了直接拒绝"的原语)。

    `active` 是正在跑的浏览器数,`waiting` 是正在排队等槽位的请求数。
    判定顺序:有空槽 → 进;没空槽但还能排队 → 等(带截止时间);队列满或等超时 → PdfBusy。
    """

    def __init__(self) -> None:
        self._cond = threading.Condition()
        self._active = 0
        self._waiting = 0

    def snapshot(self) -> tuple[int, int]:
        with self._cond:
            return self._active, self._waiting

    def acquire(self) -> None:
        limit = pdf_concurrency_limit()
        queue = pdf_queue_limit()
        with self._cond:
            if self._active < limit:
                self._active += 1
                return
            if self._waiting >= queue:
                raise PdfBusy(
                    f"导出并发已满(同时 {self._active} 个,上限 {limit};"
                    f"排队 {self._waiting} 个,上限 {queue})"
                )
            self._waiting += 1
            try:
                deadline = time.monotonic() + pdf_queue_wait()
                while self._active >= limit:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise PdfBusy(
                            f"导出排队超过 {pdf_queue_wait():.0f}s 仍未轮到"
                            f"(同时 {self._active} 个,上限 {limit})"
                        )
                    self._cond.wait(remaining)
            finally:
                self._waiting -= 1
            self._active += 1

    def release(self) -> None:
        with self._cond:
            self._active = max(0, self._active - 1)
            self._cond.notify()


_gate = _PdfGate()


@contextlib.contextmanager
def pdf_slot():
    """占用一个浏览器槽位;满了抛 PdfBusy。调用方负责把它翻成 429。"""
    _gate.acquire()
    try:
        yield
    finally:
        _gate.release()


def _pdf_gate_reset() -> None:
    """测试用:把闸门计数清零(正常运行时没人会调它)。"""
    with _gate._cond:  # noqa: SLF001 测试专用,必须拿到同一把锁
        _gate._active = 0
        _gate._waiting = 0


def _html_to_pdf(html_path: Path, pdf_path: Path, *, gated: bool = True) -> bytes | None:
    """浏览器 headless 打印 HTML 为 PDF;失败返回 None(由调用方决定兜底)。

    并发已满时抛 `PdfBusy`(不是返回 None):这两种失败的用户动作完全不同 ——
    满了应该"过 20 秒重试"并拿到 429,渲染坏了才该降级/报错。

    `gated=False` 只给能力探测用(启动期一次性判断"这台机器能不能出 PDF"),
    它不该跟真实用户抢槽位,也不该因为"正好有人在导出"就被误判成"不能出 PDF"。
    """
    if not gated:
        return _html_to_pdf_ungated(html_path, pdf_path)
    with pdf_slot():
        return _html_to_pdf_ungated(html_path, pdf_path)


def _html_to_pdf_ungated(html_path: Path, pdf_path: Path) -> bytes | None:
    """真正的浏览器调用(不做并发控制,别直接调;走 `_html_to_pdf`)。

    `--headless` 参数按"新 → 旧"回退:新版 chromium/Edge 只认 `--headless=new`,
    部分发行版仍是老的 `--headless`。写死其中一个,会在另一半机型上**静默不产出 PDF**
    (命令返回 0、没有报错、就是没文件),所以这里逐个尝试。

    沙箱受限的环境(容器 / Ubuntu 23.10+ 的 CI 镜像)连 headless 都起不来,只有
    `MG_EDGE_NO_SANDBOX=1` 时才追加 `--no-sandbox` 那一档。
    """
    edge = _find_edge()
    if edge is None:
        log.info("[doc] 未找到可用的 headless 浏览器(MG_EDGE_PATH / chromium / msedge)")
        return None
    timeout = _pdf_timeout()
    compat = _edge_compat_flags()
    attempts = [("--headless=new",), ("--headless",)]
    if compat:
        attempts += [("--headless=new", *compat), ("--headless", *compat)]
    stderr_tail = ""
    for flags in attempts:
        pdf_path.unlink(missing_ok=True)
        cmd = [
            edge, *flags, "--disable-gpu", "--no-pdf-header-footer",
            f"--print-to-pdf={pdf_path}", "--virtual-time-budget=8000",
            html_path.as_uri(),
        ]
        try:
            proc = subprocess.run(cmd, capture_output=True, timeout=timeout, check=False)
        except subprocess.TimeoutExpired:
            # 超时说明这一档参数被接受了(只是慢),换参数没有意义
            log.warning(f"[doc] 浏览器转 PDF 超时({timeout:.0f}s,参数 {' '.join(flags)})")
            return None
        stderr_tail = _stderr_tail(proc) or stderr_tail
        if not pdf_path.is_file():
            continue  # 该参数不被支持 → 换下一档
        data = pdf_path.read_bytes()
        if not data.startswith(b"%PDF"):
            log.info(f"[doc] 产物不是合法 PDF(参数 {' '.join(flags)})")
            continue
        if flags != attempts[0]:
            log.info(f"[doc] 浏览器需要兼容参数才能产出 PDF: {' '.join(flags)}")
        return data
    tried = " / ".join(" ".join(flags) for flags in attempts)
    log.info(f"[doc] 浏览器未产出 PDF(已尝试 {tried});"
             f"最后一次 stderr 尾部: {stderr_tail or '空'}")
    return None


@functools.lru_cache(maxsize=1)
def pdf_render_available() -> bool:
    """这台机器能不能**真的**产出 PDF(有浏览器二进制 ≠ 能打印)。

    用例用它决定 skip:CI 镜像里 chromium 往往在,但沙箱/内核限制让它打印不出来 ——
    那是环境缺能力,不是渲染回归。探测只做一次,结果进日志。
    """
    if _find_edge() is None:
        return False
    with tempfile.TemporaryDirectory(prefix="mg-doc-probe-") as tmp:
        base = Path(tmp).resolve()
        html_path = base / "probe.html"
        pdf_path = base / "probe.pdf"
        html_path.write_text("<!doctype html><html><body>probe</body></html>",
                             encoding="utf-8")
        # 探测不占并发槽位:它只跑一次,且不该因为"此刻正好有人在导出"而被判成不能出 PDF
        return _html_to_pdf(html_path, pdf_path, gated=False) is not None


def render_pdf_bytes(document: dict, lang: str = "zh", brand: str | None = None) -> bytes | None:
    """把已结构化的文档渲染为 PDF(不再调用 LLM)。供文档生成/问答导出复用。"""
    if lang not in ("zh", "en"):
        lang = "zh"
    normalized = _normalize_doc(document, "", lang)
    katex_dir = _katex_dir()
    with tempfile.TemporaryDirectory(prefix="mg-doc-") as tmp:
        html_path = Path(tmp) / "doc.html"
        pdf_path = Path(tmp) / "out.pdf"
        html_path.write_text(_render_html(normalized, lang, katex_dir, brand), encoding="utf-8")
        return _html_to_pdf(html_path, pdf_path)


async def export_pdf(request: Request) -> Response | JSONResponse:
    """POST /api/doc/export {content, lang}:研究综述 → 结构化重组 → PDF 下载"""
    rec = require_auth(request)
    body = await read_json_object(request)
    raw_content = body.get("content", "")
    content = raw_content.strip()[:CONTENT_MAX] if isinstance(raw_content, str) else ""
    lang = str(body.get("lang", "zh")).strip()[:8]
    if lang not in ("zh", "en"):
        lang = "zh"
    if not content:
        return JSONResponse({"detail": "empty content"}, status_code=400)

    _rate_check(str(rec.get("uid") or rec.get("phone") or ""))

    # LLM 结构化重组(deep 强模型;失败降级为原文分段,绝不阻断下载)
    doc: dict
    try:
        full: list[str] = []
        async for delta in llm.stream_chat(
                _system_prompt(lang), content, role=llm.pick("deep"),
                fallback=True, max_tokens=6000, thinking=False):
            full.append(delta)
        raw = "".join(full)
        parsed = _extract_json(raw)
        if parsed is None:
            log.warning(f"[doc] LLM 输出非 JSON({len(raw)} 字),降级排版")
            doc = _fallback_doc(content, lang)
        else:
            doc = _normalize_doc(parsed, content, lang)
    except Exception as exc:  # noqa: BLE001 模型侧错误不阻断下载
        log.warning(f"[doc] LLM 重组失败,降级排版: {exc}")
        doc = _fallback_doc(content, lang)

    katex_dir = _katex_dir()
    if not (katex_dir / "katex.min.js").is_file():
        log.info("[doc] 未找到 KaTeX 资源,PDF 中的公式将以源码展示")

    # HTML → PDF(Edge 转码也放线程池,不冻事件循环)
    with tempfile.TemporaryDirectory(prefix="mg-doc-") as tmp:
        html_path = Path(tmp) / "doc.html"
        pdf_path = Path(tmp) / "out.pdf"
        html_path.write_text(_render_html(doc, lang, katex_dir), encoding="utf-8")
        try:
            pdf = await asyncio.to_thread(_html_to_pdf, html_path, pdf_path)
        except PdfBusy as exc:
            # 并发满了不是"渲染失败":不该降级、不该记成一次成功导出。
            # 429 而不是 503 —— 这是本服务的资源上限,重试同一个请求即可。
            log.info(f"[doc] 导出被并发闸门拒绝: {exc}")
            return JSONResponse(
                {"detail": "pdf export busy, retry later"}, status_code=429,
                headers={"Retry-After": str(PdfBusy.retry_after)})
        if pdf is None:
            return JSONResponse({"detail": "pdf render failed"}, status_code=500)

    # 用量:PDF 字节数不是「回复字数」,不混进 totalChars;调用次数仍记账
    try:
        await asyncio.to_thread(
            _record, rec, cmd="导出文档", prompt_len=len(content),
            reply_len=0, role="deep", research=True)
    except Exception as exc:  # noqa: BLE001 记账失败不影响下载
        log.warning(f"[doc] 导出记账失败: {exc}")
    filename = f"mg-survey-{lang}-{time.strftime('%Y%m%d')}.pdf"
    return Response(
        pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
