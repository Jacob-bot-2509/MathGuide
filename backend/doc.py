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
import html as html_mod
import json
import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from chat import _rate_check, _record, require_auth
import rag.llm as llm

# Edge 浏览器(Windows 自带,仅调用不改系统文件)
_EDGE_CANDIDATES = (
    Path("C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe"),
    Path("C:/Program Files/Microsoft/Edge/Application/msedge.exe"),
)

# KaTeX 静态资源(与前端 node_modules 同一份,渲染行为与聊天页一致)
_KATEX_DIR = Path(__file__).resolve().parent.parent / "frontend" / "node_modules" / "katex" / "dist"

CONTENT_MAX = 32000  # 与聊天输入上限一致


def _find_edge() -> str | None:
    for p in _EDGE_CANDIDATES:
        if p.is_file():
            return str(p)
    return shutil.which("msedge")


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


def _normalize_doc(obj: dict, content: str, lang: str) -> dict:
    """把 LLM 输出规整为渲染所需的最小合法结构(缺什么补什么)"""
    title = str(obj.get("title") or "").strip()[:120] or (
        "Research Summary" if lang == "en" else "研究综述")
    abstract = str(obj.get("abstract") or "").strip()
    keywords = [str(k).strip()[:40] for k in (obj.get("keywords") or [])
                if str(k).strip()][:8]
    sections = []
    for s in obj.get("sections") or []:
        heading = str(s.get("heading") or "").strip()[:100]
        paras = [str(p).strip()[:8000] for p in (s.get("paragraphs") or [])
                 if str(p).strip()]
        if paras:
            sections.append({"heading": heading or title, "paragraphs": paras})
    if not sections:
        sections = [{"heading": title, "paragraphs": [content]}]
    refs = []
    for r in obj.get("references") or []:
        ref = {
            "id": r.get("id") or (len(refs) + 1),
            "title": str(r.get("title") or "").strip()[:300],
            "source": str(r.get("source") or "").strip()[:40],
            "url": str(r.get("url") or "").strip()[:500],
        }
        if ref["title"]:
            refs.append(ref)
    return {
        "title": title, "abstract": abstract, "keywords": keywords,
        "sections": sections, "references": refs,
    }


# 公式分隔:块级 $$..$$ 优先,行内 \(..\) 与 $..$(后位非数字,防金额误判)与 MathText 同口径
_MATH_RE = re.compile(
    r"(\$\$[\s\S]+?\$\$|\\\([\s\S]+?\\\)|\$(?=[^0-9])([^$\n]+?)\$)")


def _render_math(html_safe: str) -> str:
    """把已转义的文本中的公式包上渲染标记(KaTeX 页内脚本处理)"""
    def repl(m: re.Match) -> str:
        body = m.group(1)
        if body.startswith("$$"):
            return f'<span class="mg-mathd">{body[2:-2]}</span>'
        if body.startswith("\\("):
            return f'<span class="mg-math">{body[2:-2]}</span>'
        return f'<span class="mg-math">{body[1:-1]}</span>'
    return _MATH_RE.sub(repl, html_safe)


def _render_html(doc: dict, lang: str, katex_dir: Path) -> str:
    zh = lang != "en"
    css = (katex_dir / "katex.min.css").as_uri()
    js = (katex_dir / "katex.min.js").as_uri()

    def esc(s: str) -> str:
        return html_mod.escape(s)

    secs = []
    for s in doc["sections"]:
        paras = "\n".join(
            f"<p>{_render_math(esc(p))}</p>" for p in s["paragraphs"])
        secs.append(f'<section><h2>{esc(s["heading"])}</h2>{paras}</section>')

    refs = ""
    if doc["references"]:
        items = "\n".join(
            f'<li>[{r["id"]}] {esc(r["title"])} — {esc(r["source"])}'
            + (f' <a href="{esc(r["url"])}">{esc(r["url"])}</a>' if r["url"] else "")
            for r in doc["references"])
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
    font_stack = ("Georgia, 'Times New Roman', serif" if not zh
                  else "'Microsoft YaHei', 'PingFang SC', 'Noto Sans CJK SC', sans-serif")

    return f"""<!DOCTYPE html>
<html lang="{lang_attr}">
<head>
<meta charset="utf-8">
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
    <div class="brand">MATHGUIDE · {"SURVEY" if not zh else "研究综述"}</div>
    <h1>{esc(doc["title"])}</h1>
    <div class="date">{"Generated by MathGuide" if not zh else "由 MathGuide 生成"} · {date_str}</div>
    {meta_block}
  </div>
  {''.join(secs)}
  {refs}
  <script src="{js}"></script>
  <script>
    document.querySelectorAll('.mg-math').forEach(function (el) {{
      try {{ katex.render(el.textContent, el, {{ throwOnError: true }}); }}
      catch (e) {{ /* 渲染失败保留源码,与聊天页同口径 */ }}
    }});
    document.querySelectorAll('.mg-mathd').forEach(function (el) {{
      try {{ katex.render(el.textContent, el, {{ displayMode: true, throwOnError: true }}); }}
      catch (e) {{ }}
    }});
  </script>
</body>
</html>"""


def _html_to_pdf(html_path: Path, pdf_path: Path) -> bytes | None:
    """Edge headless 打印 HTML 为 PDF;失败返回 None(由调用方决定兜底)"""
    edge = _find_edge()
    if edge is None:
        print("[doc] 未找到 Edge 浏览器")
        return None
    cmd = [
        edge, "--headless=new", "--disable-gpu", "--no-pdf-header-footer",
        f"--print-to-pdf={pdf_path}", "--virtual-time-budget=8000",
        html_path.as_uri(),
    ]
    try:
        subprocess.run(cmd, capture_output=True, timeout=60, check=False)
    except subprocess.TimeoutExpired:
        print("[doc] Edge 转 PDF 超时")
        return None
    if not pdf_path.is_file():
        print("[doc] Edge 未产出 PDF")
        return None
    data = pdf_path.read_bytes()
    if not data.startswith(b"%PDF"):
        print("[doc] 产物不是合法 PDF")
        return None
    return data


async def export_pdf(request: Request) -> Response | JSONResponse:
    """POST /api/doc/export {content, lang}:研究综述 → 结构化重组 → PDF 下载"""
    rec = require_auth(request)
    body = await request.json()
    content = str(body.get("content", "")).strip()[:CONTENT_MAX]
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
                fallback=True, max_tokens=6000):
            full.append(delta)
        raw = "".join(full)
        parsed = _extract_json(raw)
        if parsed is None:
            print(f"[doc] LLM 输出非 JSON(前 80 字): {raw[:80]!r},降级排版")
            doc = _fallback_doc(content, lang)
        else:
            doc = _normalize_doc(parsed, content, lang)
    except Exception as exc:  # noqa: BLE001 模型侧错误不阻断下载
        print(f"[doc] LLM 重组失败,降级排版: {exc}")
        doc = _fallback_doc(content, lang)

    # HTML → PDF(Edge 转码也放线程池,不冻事件循环)
    with tempfile.TemporaryDirectory(prefix="mg-doc-", dir=Path(__file__).parent) as tmp:
        html_path = Path(tmp) / "doc.html"
        pdf_path = Path(tmp) / "out.pdf"
        html_path.write_text(_render_html(doc, lang, _KATEX_DIR), encoding="utf-8")
        pdf = await asyncio.to_thread(_html_to_pdf, html_path, pdf_path)
        if pdf is None:
            return JSONResponse({"detail": "pdf render failed"}, status_code=500)

    _record(rec, cmd="导出文档", prompt_len=len(content),
            reply_len=len(pdf), role="deep", research=True)
    filename = f"mg-survey-{lang}-{time.strftime('%Y%m%d')}.pdf"
    return Response(
        pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
