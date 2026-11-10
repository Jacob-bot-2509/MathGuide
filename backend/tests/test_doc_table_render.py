"""Ruled arrays must keep their lines in PDF and Word export."""
from io import BytesIO
from zipfile import ZipFile
import struct

import pytest
from lxml import etree

import doc
import docgen
import math_render


@pytest.mark.skipif(not doc._find_edge(), reason="Edge is unavailable")
def test_word_ruled_array_keeps_borders_and_neighboring_math():
    tex = r"\begin{array}{c|c}x&y\\\hline 2&-5\\p&-14\end{array}"
    document = {"title": "Math", "sections": [{"heading": "H", "paragraphs": [
        "Before $" + tex + "$ after $x^2$.",
    ]}]}
    with pytest.raises(ValueError, match="require visual rendering"):
        math_render.to_omml(tex)
    data = docgen._docx_bytes(document, "en")
    with ZipFile(BytesIO(data)) as archive:
        image_name = next(name for name in archive.namelist() if name.startswith("word/media/"))
        bitmap = archive.read(image_name)
        xml = etree.fromstring(archive.read("word/document.xml"))
    ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
          "m": "http://schemas.openxmlformats.org/officeDocument/2006/math",
          "wp": "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"}
    assert xml.xpath("count(//w:drawing)", namespaces=ns) == 1
    assert xml.xpath("count(//m:oMath)", namespaces=ns) == 1
    assert xml.xpath("string(//wp:docPr/@descr)", namespaces=ns) == tex
    visible = "".join(xml.xpath("//w:t/text()", namespaces=ns))
    assert "Before " in visible and " after " in visible and r"\hline" not in visible
    assert bitmap[:2] == b"BM"
    width, height = struct.unpack_from("<ii", bitmap, 18)
    stride = (width * 3 + 3) & ~3
    rows = [bitmap[54 + y * stride:54 + y * stride + width * 3] for y in range(height)]
    dark = lambda row, x: max(row[x * 3:x * 3 + 3]) < 128
    assert max(sum(dark(row, x) for x in range(width)) for row in rows) > width * 0.6
    assert max(sum(dark(row, x) for row in rows) for x in range(width)) > height * 0.6


def test_failed_table_renderer_preserves_original_source(monkeypatch):
    import math_table_render

    tex = r"\begin{array}{c|c}x&y\\\hline 2&-5\end{array}"
    monkeypatch.setattr(math_table_render, "render_table_image", lambda _tex: (_ for _ in ()).throw(ValueError("failed")))
    document = {"title": "Math", "sections": [{"heading": "H", "paragraphs": ["$" + tex + "$"]}]}
    with ZipFile(BytesIO(docgen._docx_bytes(document, "en"))) as archive:
        xml = etree.fromstring(archive.read("word/document.xml"))
    ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    assert tex in "".join(xml.xpath("//w:t/text()", namespaces=ns))
