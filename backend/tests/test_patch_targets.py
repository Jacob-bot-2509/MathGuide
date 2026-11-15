"""守住 `monkeypatch.setattr(chat, "<名字>")` 这类补丁的有效性。

背景:`tests/` 里有 60 处 `setattr(chat, ...)`。它们的语义是"改 chat 模块的全局,让被测
代码读到假实现"。一旦某个符号从 chat.py 搬去别的模块,补丁就对**搬迁后的代码无效了** ——
但测试往往仍然是绿的(它在跑真实现),这就是 `chat.FRAME_MS` 那次踩过的坑。

这里做静态校验:扫测试源码,把 `setattr(chat, "x")` 里的 x 全部与 chat 模块现有的属性比对。
- 符号搬走而测试没跟着改 => 本用例变红,逼你搬迁时一起改;
- 顺手给出搬迁清单:`pytest -q tests/test_patch_targets.py` 失败信息里就是待改清单。

扫描器自身也要防"静默失效":断言匹配数不少于 50,避免测试写法变了以后这个守卫空转。
"""
from __future__ import annotations

import re
from pathlib import Path

import chat

TESTS_DIR = Path(__file__).resolve().parent

# setattr(chat, "名字"  /  setattr(chat, '名字'
_TARGET_RE = re.compile(r"""setattr\(\s*chat\s*,\s*["']([^"']+)["']""")

# 允许测试显式"制造不存在"的写法:raising=False 表示"没有也不报错",不在守卫范围
_RAISING_FALSE_RE = re.compile(r"setattr\(\s*chat\s*,\s*[\"'][^\"']+[\"'][^)]*raising\s*=\s*False")


def _iter_patch_targets() -> list[tuple[str, int, str]]:
    found: list[tuple[str, int, str]] = []
    for path in sorted(TESTS_DIR.glob("*.py")):
        if path.name == Path(__file__).name:
            continue
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if "setattr(chat" not in line:
                continue
            if _RAISING_FALSE_RE.search(line):
                continue
            for name in _TARGET_RE.findall(line):
                found.append((path.name, lineno, name))
    return found


def test_chat_patch_targets_still_exist() -> None:
    targets = _iter_patch_targets()

    # 守卫不能空转:写法若整体改变(比如改用 pytest.MonkeyPatch 上下文),这里要先提醒。
    assert len(targets) >= 50, (
        "只扫到 %d 处 setattr(chat, ...) 补丁,明显少于预期的 60 余处;"
        "若测试写法调整过,请同步更新 test_patch_targets.py 的扫描规则" % len(targets)
    )

    missing = [
        "%s:%d 补丁 chat.%s,但 chat 模块里已没有该名字(符号搬走了?请改补丁目标)"
        % (filename, lineno, name)
        for filename, lineno, name in targets
        if not hasattr(chat, name)
    ]
    assert not missing, "\n".join(missing)
