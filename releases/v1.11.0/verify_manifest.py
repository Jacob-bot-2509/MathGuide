#!/usr/bin/env python3
"""校验 MANIFEST.sha256。

用法:
    # 校验解压后的源码树(目录内应包含 backend/、frontend/ 等)
    python verify_manifest.py path/to/MathGuide-v1.11.0

    # 或在仓库根目录校验当前工作树
    python releases/v1.11.0/verify_manifest.py .

清单里的路径相对源码根目录;任何缺失或哈希不一致都会以非零退出码结束。
"""
from __future__ import annotations

import hashlib
import pathlib
import sys

manifest = pathlib.Path(__file__).with_name("MANIFEST.sha256")
root = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else pathlib.Path.cwd()

checked = 0
failures = 0
for line in manifest.read_text(encoding="utf-8").splitlines():
    if not line.strip():
        continue
    expected, sep, rel = line.partition("  ")
    if not sep:
        print(f"MALFORMED {line!r}")
        failures += 1
        continue
    path = root / rel
    if not path.is_file():
        print(f"MISSING  {rel}")
        failures += 1
        continue
    actual = hashlib.sha256(path.read_bytes()).hexdigest()
    if actual != expected:
        print(f"MISMATCH {rel}")
        failures += 1
    checked += 1

print(f"checked={checked} failures={failures}")
sys.exit(1 if failures else 0)
