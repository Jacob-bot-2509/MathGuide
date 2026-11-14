"""math_table_render:把有规则(竖线/横线)的数组公式渲染成 Word 无损图片。

缺的 11 行全是**失败路径**:渲染进程出错、PDF 多页、KaTeX 报错、位图格式异常、
裁切后为空。这些分支写错的后果是"公式在 Word 里凭空消失",而不是报错 —— 所以必须测。
这里不真的跑 Chromium:假 pypdfium2 + 假 _html_to_pdf,只验判定逻辑与 BMP 组装。
"""
from __future__ import annotations

import sys
import types

import pytest

import math_table_render as mtr


class FakeBitmap:
    def __init__(self, mode="BGR", width=40, height=30, empty=False):
        self.mode = mode
        self.width = width
        self.height = height
        self.stride = width * 3
        # 全白表示"什么都没画出来";否则在中间留一块黑
        self.buffer = bytearray(b"\xff" * (self.stride * height))
        if not empty:
            for y in range(5, height - 5):
                row = y * self.stride
                self.buffer[row + 30:row + 90] = b"\x00" * 60


class FakePage:
    def __init__(self, text="", bitmap=None):
        self._text = text
        self._bitmap = bitmap or FakeBitmap()

    def get_textpage(self):
        page = self

        class _TextPage:
            def get_text_range(self):
                return page._text

        return _TextPage()

    def render(self, scale=1):
        return self._bitmap


class FakeDocument:
    def __init__(self, pages):
        self._pages = pages

    def __len__(self):
        return len(self._pages)

    def __getitem__(self, index):
        return self._pages[index]


def _install(monkeypatch, document=None, pdf="pdf-bytes", html_error=None):
    """把 pypdfium2 与 doc 的渲染两步都换掉。"""
    module = types.SimpleNamespace(
        PdfDocument=lambda _pdf: document if document is not None else FakeDocument([FakePage()]),
    )
    monkeypatch.setitem(sys.modules, "pypdfium2", module)
    monkeypatch.setattr(mtr.doc, "_katex_dir", lambda: __import__("pathlib").Path.cwd())

    def fake_html_to_pdf(_source, target):
        if html_error:
            raise html_error
        return pdf

    monkeypatch.setattr(mtr.doc, "_html_to_pdf", fake_html_to_pdf)


def test_renders_bmp_with_width(monkeypatch):
    _install(monkeypatch)

    data, width = mtr.render_table_image(r"\begin{array}{c|c} a & b \end{array}")

    assert data.startswith(b"BM")          # 无损位图头
    assert width > 0
    assert width <= 5.8                     # 超过版心就缩到 5.8 英寸


def test_render_failure_is_reported_as_value_error(monkeypatch):
    _install(monkeypatch, html_error=OSError("chromium missing"))

    with pytest.raises(ValueError, match="Unable to render Word array"):
        mtr.render_table_image("x")


def test_missing_pdf_is_rejected(monkeypatch):
    _install(monkeypatch, pdf=None)

    with pytest.raises(ValueError, match="Unable to render Word array"):
        mtr.render_table_image("x")


def test_multi_page_pdf_is_rejected(monkeypatch):
    _install(monkeypatch, document=FakeDocument([FakePage(), FakePage()]))

    with pytest.raises(ValueError, match="does not fit one page"):
        mtr.render_table_image("x")


def test_katex_error_marker_is_rejected(monkeypatch):
    """页面里残留错误标记 = KaTeX 没渲染成功,不能把空白图插进 Word。"""
    _install(monkeypatch, document=FakeDocument([FakePage(text="MGFORMULARENDERFAILED")]))

    with pytest.raises(ValueError, match="Unsupported Word array syntax"):
        mtr.render_table_image("x")


def test_unexpected_bitmap_mode_is_rejected(monkeypatch):
    _install(monkeypatch, document=FakeDocument([FakePage(bitmap=FakeBitmap(mode="RGB"))]))

    with pytest.raises(ValueError, match="Unsupported Word array image format"):
        mtr.render_table_image("x")


def test_empty_bitmap_is_rejected(monkeypatch):
    """全白位图说明没画出内容(常见于公式超出画布),必须报错而不是插空图。"""
    blank = FakeBitmap(empty=True)
    _install(monkeypatch, document=FakeDocument([FakePage(bitmap=blank)]))

    with pytest.raises(ValueError, match="Empty or clipped"):
        mtr.render_table_image("x")


def test_unexpected_render_exception_is_wrapped(monkeypatch):
    class Exploding:
        def __len__(self):
            raise RuntimeError("driver crashed")

    _install(monkeypatch, document=Exploding())

    with pytest.raises(ValueError, match="Unable to render Word array"):
        mtr.render_table_image("x")
