"""导出 PDF 的部署自检:一条命令回答"这台机器能不能出 PDF"。

用法(在 backend 目录下):
    python tools/check_pdf.py            # 自检
    python tools/check_pdf.py --out x.pdf  # 顺便留下一份样例

检查四项,任一失败都给出可执行的修复建议并以退出码 1 结束:
    1. 浏览器是否可发现(含版本号);
    2. 系统是否有中文字体(缺了 PDF 里中文会变方块,代码兜不住);
    3. 能否真的打印出 PDF(含 headless 参数回退);
    4. PDF 里是否嵌入了 CJK 字体(否则仍是方块)。

为什么需要它:`_html_to_pdf` 失败时**完全静默**(返回 None,不抛异常),
部署后往往要等用户点「导出」才发现。把上面四项压成一条命令,
上线前跑一次就能定位是"没装浏览器""没装字体"还是"参数不兼容"。
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import doc  # noqa: E402

SAMPLE_DOC = {
    "title": "导出链路自检",
    "abstract": "含中文与公式的最小文档。",
    "sections": [
        {"heading": "一、极限", "paragraphs": [r"极限的定义:$\lim_{x\to 0}\frac{\sin x}{x}=1$。"]},
        {"heading": "二、矩阵", "paragraphs": [r"行内矩阵:$\begin{pmatrix}1&2\\3&4\end{pmatrix}$"]},
    ],
    "references": [{"id": 1, "title": "自检来源", "source": "local", "url": ""}],
}


def _fail(message: str, fix: str) -> int:
    print(f"[FAIL] {message}")
    print(f"       修复: {fix}")
    return 1


def _browser_version(edge: str) -> str:
    try:
        out = subprocess.run([edge, "--version"], capture_output=True, timeout=20, check=False)
        text = (out.stdout or out.stderr or b"").decode("utf-8", "replace").strip()
        return text.splitlines()[0] if text else "(版本未知)"
    except (OSError, subprocess.TimeoutExpired):
        return "(无法获取版本)"


def _has_cjk_font() -> tuple[bool, str]:
    """尽力检查系统里有没有中文字体。Windows/macOS 自带,Linux 需要 fonts-noto-cjk。"""
    if sys.platform.startswith("win"):
        return True, "Windows 自带中文字体"
    if sys.platform == "darwin":
        return True, "macOS 自带中文字体"
    try:
        out = subprocess.run(["fc-list", ":lang=zh"], capture_output=True, timeout=20, check=False)
        lines = [line for line in (out.stdout or b"").decode("utf-8", "replace").splitlines() if line.strip()]
        if lines:
            return True, f"fc-list 找到 {len(lines)} 个中文字体"
        return False, "fc-list 没有中文字体"
    except (OSError, subprocess.TimeoutExpired):
        return False, "没有 fc-list,无法确认中文字体"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="导出 PDF 的部署自检")
    parser.add_argument("--out", default="", help="把样例 PDF 保存到该路径")
    args = parser.parse_args(argv)

    print("== 1. 浏览器 ==")
    edge = doc._find_edge()
    if edge is None:
        return _fail(
            "找不到 headless 浏览器",
            "apt install -y chromium 后设置 MG_EDGE_PATH=/usr/bin/chromium"
            "(Windows 装 Edge 即可;检查 MG_EDGE_PATH 是否写错)。",
        )
    print(f"[ OK ] {edge}")
    print(f"       版本: {_browser_version(edge)}")
    print(f"       超时: {doc._pdf_timeout():.0f}s(可用 MG_PDF_TIMEOUT 调整)")

    print("== 2. 中文字体 ==")
    ok, detail = _has_cjk_font()
    if not ok:
        return _fail(
            f"中文字体不可用({detail})",
            "apt install -y fonts-noto-cjk —— 缺字体时 PDF 里的中文会是方块,代码兜不住。",
        )
    print(f"[ OK ] {detail}")

    print("== 3. 打印 PDF ==")
    data = doc.render_pdf_bytes(SAMPLE_DOC, "zh", "自检")
    if not data or not data.startswith(b"%PDF"):
        return _fail(
            "浏览器没有产出合法 PDF",
            "手工验证命令行:chromium --headless=new --disable-gpu "
            "--print-to-pdf=/tmp/t.pdf https://example.com;若提示未知参数,说明版本过旧。",
        )
    print(f"[ OK ] {len(data)} 字节")

    print("== 4. PDF 内字体嵌入 ==")
    cjk_fonts = data.count(b"/Type0")
    if cjk_fonts == 0:
        return _fail(
            "PDF 里没有嵌入 CJK 字体(中文会显示为方块)",
            "apt install -y fonts-noto-cjk 后重跑本自检。",
        )
    print(f"[ OK ] 嵌入 CJK 字体 {cjk_fonts} 个")

    if args.out:
        Path(args.out).write_bytes(data)
        print(f"       样例已保存: {args.out}")

    print("\n结论: 这台机器可以导出 PDF。建议再手工导出一份带数组公式的文档,肉眼确认表格线。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
