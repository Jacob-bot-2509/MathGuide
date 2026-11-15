"""导出 PDF 的部署自检:一条命令回答"这台机器能不能出 PDF"。

用法(在 backend 目录下):
    python tools/check_pdf.py            # 自检
    python tools/check_pdf.py --out x.pdf  # 顺便留下一份样例

检查五项,任一失败都给出可执行的修复建议并以退出码 1 结束:
    1. 浏览器是否可发现(含版本号);
    2. 系统是否有中文字体(缺了 PDF 里中文会变方块,代码兜不住);
    3. 能否真的打印出 PDF(含 headless 参数回退),并回答**要不要放开沙箱**;
    4. PDF 里是否嵌入了 CJK 字体(否则仍是方块);
    5. PDF 文本层能不能读到中文。

为什么需要它:`_html_to_pdf` 失败时**完全静默**(返回 None,不抛异常),
部署后往往要等用户点「导出」才发现。把上面五项压成一条命令,
上线前跑一次就能定位是"没装浏览器""没装字体""参数不兼容"还是"沙箱起不来"。

第 3 项会把样张在 `MG_EDGE_NO_SANDBOX` 的两种取值下各印一次:沙箱起不来时
浏览器只返回非 0、什么都不说,所以只有真的再印一次才能确定该不该开这个开关。
自检通过 ≠ 生产可用 —— 若结论是"必须开",生产配置里也必须留着那一行。
"""
from __future__ import annotations

import argparse
import os
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
    print("RESULT: FAIL")
    return 1


def _ensure_utf8_stdout() -> None:
    """把标准输出切到 UTF-8:Windows 控制台默认 GBK,中文会显示成 `???`。

    这纯粹是显示问题(文件/PDF 内容是好的),但自检输出一旦乱码,人就无法判断
    "是终端的问题还是 PDF 的问题",所以这里主动修正;失败也不影响检查结果。
    """
    stream = sys.stdout
    if hasattr(stream, "reconfigure"):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (OSError, ValueError):
            pass


def _pdf_text(data: bytes) -> str | None:
    """从 PDF 里提取文本层;没有 pypdf 或提取失败返回 None(不是硬失败)。"""
    try:
        import io

        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(data))
        return "".join((page.extract_text() or "") for page in reader.pages)
    except Exception:  # noqa: BLE001 提取失败只影响"内容检查",不影响 PDF 能否生成
        return None


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


def _render_with_env(value: str | None) -> bytes | None:
    """按指定的 `MG_EDGE_NO_SANDBOX` 值打印一次,结束后恢复原环境。

    value=None 表示强制走"保留沙箱"的默认档。用来回答"这台机器到底要不要放开沙箱":
    同一个样张在两种设置下各印一次,比看日志可靠 —— 沙箱起不来时浏览器只返回非 0。
    """
    key = "MG_EDGE_NO_SANDBOX"
    saved = os.environ.get(key)
    try:
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value
        return doc.render_pdf_bytes(SAMPLE_DOC, "zh", "自检")
    finally:
        if saved is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = saved


def main(argv: list[str] | None = None) -> int:
    _ensure_utf8_stdout()
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
    opt_out = bool(doc._edge_compat_flags())
    print(
        "       沙箱: "
        + ("已放开(MG_EDGE_NO_SANDBOX 生效,--no-sandbox 兜底档可用)" if opt_out else "保留(默认)")
    )
    data = doc.render_pdf_bytes(SAMPLE_DOC, "zh", "自检")
    if not data or not data.startswith(b"%PDF"):
        if not opt_out:
            # 默认档打不出来 → 再试一次放开沙箱,区分"参数/浏览器问题"和"沙箱起不来"
            relaxed = _render_with_env("1")
            if relaxed and relaxed.startswith(b"%PDF"):
                return _fail(
                    "浏览器沙箱起不来(保留沙箱时打印不出 PDF,放开后可打印)",
                    "在 backend/.env.local 写 MG_EDGE_NO_SANDBOX=1 后重跑本自检;"
                    "生产必须保留同一行,否则线上导出仍是 500 pdf render failed。",
                )
        return _fail(
            "浏览器没有产出合法 PDF",
            "手工验证命令行:chromium --headless=new --disable-gpu "
            "--print-to-pdf=/tmp/t.pdf https://example.com;若提示未知参数,说明版本过旧。",
        )
    print(f"[ OK ] {len(data)} 字节")

    if opt_out:
        # 当前已放开沙箱:反过来验证"其实能不能不放开",结论直接决定生产配置
        strict = _render_with_env(None)
        if strict and strict.startswith(b"%PDF"):
            print("[注意] 保留沙箱也能打印:建议去掉 MG_EDGE_NO_SANDBOX(生产开沙箱更安全)。")
        else:
            print(
                "[注意] 这台机器只有放开沙箱才能打印。生产环境的 MG_EDGE_NO_SANDBOX 必须同为 1,\n"
                "       否则线上导出是 500 pdf render failed —— 自检通过不代表生产可用。"
            )

    print("== 4. PDF 内字体嵌入 ==")
    cjk_fonts = data.count(b"/Type0")
    if cjk_fonts == 0:
        return _fail(
            "PDF 里没有嵌入 CJK 字体(中文会显示为方块)",
            "apt install -y fonts-noto-cjk 后重跑本自检。",
        )
    print(f"[ OK ] 嵌入 CJK 字体 {cjk_fonts} 个")

    print("== 5. PDF 里的中文内容 ==")
    text = _pdf_text(data)
    if text is None:
        print("[SKIP] 未安装 pypdf,跳过内容检查")
    elif "极限" in text:
        print(f"[ OK ] 文本层可读到中文(共 {len(text)} 字符)")
    else:
        return _fail(
            "PDF 文本层读不到中文 —— 字体缺失时 Chromium 会画方块,文字不会丢失但看起来是乱码",
            "apt install -y fonts-noto-cjk;然后重跑本自检,并肉眼确认一次导出结果。",
        )

    if args.out:
        Path(args.out).write_bytes(data)
        print(f"       样例已保存: {args.out}")

    print("\n结论: 这台机器可以导出 PDF。建议再手工导出一份带数组公式的文档,肉眼确认表格线。")
    print("RESULT: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
