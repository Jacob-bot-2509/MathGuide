"""Render ruled mathematical arrays for Word without losing their borders."""
from __future__ import annotations

import html
import json
import struct
import tempfile
from pathlib import Path

import doc
import math_render


def render_table_image(tex: str) -> tuple[bytes, float]:
    """Return a lossless BMP and its width in inches, or fail without altering the formula."""
    import pypdfium2

    katex_dir = doc._katex_dir()
    css = (katex_dir / "katex.min.css").as_uri()
    script = (katex_dir / "katex.min.js").as_uri()
    macros = {**math_render.MACROS, r"\knowl": r"\def\mgIgnore##1{}\mgIgnore{#1}#2"}
    content = html.escape(math_render.prepare(tex))
    page_html = f"""<!doctype html><meta charset="utf-8">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; script-src 'unsafe-inline' file:; style-src 'unsafe-inline' file:; font-src file:">
<link rel="stylesheet" href="{css}"><style>@page{{size:A4;margin:0}}body{{margin:12px;font-size:18px}}</style>
<div id="formula">{content}</div><div id="error">MGFORMULARENDERFAILED</div>
<script src="{script}"></script><script>
try {{ katex.render(document.getElementById('formula').textContent, document.getElementById('formula'),
  {{throwOnError:true, trust:false, macros:{json.dumps(macros, ensure_ascii=True)}}});
  document.getElementById('error').remove(); }}
catch(e) {{ document.getElementById('formula').remove(); }}
</script>"""
    try:
        with tempfile.TemporaryDirectory(prefix="mg-formula-") as tmp:
            path = Path(tmp)
            source = path / "formula.html"
            source.write_text(page_html, encoding="utf8")
            pdf = doc._html_to_pdf(source, path / "formula.pdf")
    except OSError as exc:
        raise ValueError("Unable to render Word array") from exc
    if not pdf:
        raise ValueError("Unable to render Word array")
    try:
        document = pypdfium2.PdfDocument(pdf)
        if len(document) != 1:
            raise ValueError("Word array does not fit one page")
        page = document[0]
        if "MGFORMULARENDERFAILED" in page.get_textpage().get_text_range():
            raise ValueError("Unsupported Word array syntax")
        bitmap = page.render(scale=2)
        if bitmap.mode != "BGR":
            raise ValueError("Unsupported Word array image format")
        width, height, stride = bitmap.width, bitmap.height, bitmap.stride
        pixels = bytes(bitmap.buffer)
        left, top, right, bottom = width, height, 0, 0
        for y in range(height):
            row = pixels[y * stride:y * stride + width * 3]
            if row.strip(b"\xff"):
                left = min(left, (len(row) - len(row.lstrip(b"\xff"))) // 3)
                right = max(right, (len(row.rstrip(b"\xff")) + 2) // 3)
                top = min(top, y)
                bottom = y + 1
        if right <= left or bottom <= top or right >= width - 2 or bottom >= height - 2:
            raise ValueError("Empty or clipped Word array")
        left, top = max(0, left - 4), max(0, top - 4)
        right, bottom = min(width, right + 4), min(height, bottom + 4)
        cropped_width, cropped_height = right - left, bottom - top
        padding = b"\x00" * ((-cropped_width * 3) % 4)
        data = b"".join(pixels[y * stride + left * 3:y * stride + right * 3] + padding
                        for y in range(bottom - 1, top - 1, -1))
        header = (struct.pack("<2sIHHI", b"BM", 54 + len(data), 0, 0, 54)
                  + struct.pack("<IiiHHIIiiII", 40, cropped_width, cropped_height,
                                1, 24, 0, len(data), 5669, 5669, 0, 0))
        return header + data, min(5.8, cropped_width / 144.0)
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError("Unable to render Word array") from exc
