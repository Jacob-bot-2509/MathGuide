"""静态守卫:进程内不许改 rlimit(唯一例外是"子进程预置")。

为什么需要它:Linux 上出现过"后端挂起、所有请求不再返回、日志一片空白"的故障,
根因是主进程里调了 `resource.setrlimit(...)`,把地址空间/CPU 收紧到模型侧需要的水位。
rlimit 是**进程级**开关,而且只对"之后的新分配"生效 —— 在 uvicorn 主进程里改它,
等于顺手给 SQLite、HTTP 连接、浏览器子进程一起上了锁,失败还没有任何日志。

正确做法(见 `analysis_client.py`):rlimit 只在**子进程启动时**设置,作用域仅限
那一个分析进程,主进程不受影响。

用法(CI 与本地同一条命令,backend 目录下):
    python tools/lint_rlimits.py

退出码:0 = 干净;1 = 发现违规(逐条打印 file:line:col)。
"""
from __future__ import annotations

import argparse
import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent  # backend/

# 唯一合法位置:在子进程的启动脚本里给"那一个进程"设限
ALLOWED_FILES = {
    "analysis_client.py",
}

FORBIDDEN_NAMES = {"setrlimit", "prlimit"}

# 这些目录不是运行时应用代码:测试可以随意构造(它要模拟子进程),
# 工具脚本自己也可能需要演示违规写法,一律不扫。
SKIP_DIRS = {"tests", "tools", "__pycache__", ".venv", ".pytest_cache", ".ruff_cache"}


def iter_python_files(root: Path):
    """遍历待扫的 .py(按路径排序,保证输出稳定、CI diff 好读)。"""
    for path in sorted(root.rglob("*.py")):
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        if path.name in ALLOWED_FILES:
            continue
        yield path


def _dotted(node: ast.AST) -> str:
    """把 `resource.setrlimit` 这类调用目标还原成点号串(还原不出返回空)。"""
    parts: list[str] = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
    return ".".join(reversed(parts))


def scan_file(path: Path, root: Path) -> list[str]:
    """返回该文件的违规清单(每项 `相对路径:行:列: 调用`)。"""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (OSError, SyntaxError) as exc:  # 语法错误交给 compileall,这里只报告不中断
        return [f"{path.relative_to(root)}:0:0: 无法解析({exc.__class__.__name__})"]

    # `from resource import setrlimit as _s` 之后,违规调用长得像 `_s(...)`,
    # 只按名字扫会漏 —— 先把这类别名收集起来。
    aliases: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and (node.module or "").endswith("resource"):
            for alias in node.names:
                if alias.name in FORBIDDEN_NAMES:
                    aliases.add(alias.asname or alias.name)

    findings: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        target = _dotted(node.func)
        last = target.rsplit(".", 1)[-1] if target else ""
        if last in FORBIDDEN_NAMES or (target and target in aliases):
            rel = path.relative_to(root)
            findings.append(f"{rel}:{node.lineno}:{node.col_offset}: {target}()")
    return findings


def scan(root: Path = ROOT) -> list[str]:
    """扫整棵后端代码树,返回全部违规(空列表 = 干净)。"""
    findings: list[str] = []
    for path in iter_python_files(root):
        findings.extend(scan_file(path, root))
    return findings


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # Windows 控制台
    parser = argparse.ArgumentParser(description="禁止在应用进程内修改 rlimit")
    parser.add_argument("--root", default=str(ROOT), help="要扫描的目录(默认 backend/)")
    args = parser.parse_args(argv)
    root = Path(args.root).resolve()

    findings = scan(root)
    if findings:
        print("发现进程内 rlimit 调用(应改到子进程启动脚本里,见 analysis_client.py):")
        for item in findings:
            print(f"  {item}")
        return 1
    print("rlimit 守卫通过:未发现进程内 setrlimit/prlimit 调用")
    return 0


if __name__ == "__main__":
    sys.exit(main())
