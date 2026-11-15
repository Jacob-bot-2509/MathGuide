"""tools/lint_rlimits.py:守卫本身必须真的能报错 —— 否则它就是一段装饰。

同时把"真实代码树是干净的"变成一条用例:CI 里 ruff/compileall 之间多一道门,
本地跑测试也能立刻发现有人把 rlimit 挪回主进程。
"""
from __future__ import annotations

from tools import lint_rlimits


def test_real_backend_tree_has_no_inline_rlimit():
    assert lint_rlimits.scan(lint_rlimits.ROOT) == []


def test_flags_setrlimit_in_app_module(tmp_path):
    (tmp_path / "app_module.py").write_text(
        "import resource\n"
        "def boot():\n"
        "    resource.setrlimit(resource.RLIMIT_AS, (512 << 20, 512 << 20))\n",
        encoding="utf-8")
    findings = lint_rlimits.scan(tmp_path)
    assert len(findings) == 1
    assert findings[0].startswith("app_module.py:3:")
    assert "resource.setrlimit()" in findings[0]


def test_flags_prlimit_and_aliased_imports(tmp_path):
    (tmp_path / "a.py").write_text(
        "import resource\n"
        "resource.prlimit(1234, resource.RLIMIT_CPU, (30, 30))\n",
        encoding="utf-8")
    (tmp_path / "b.py").write_text(
        "from resource import setrlimit as _limit\n"
        "_limit(None, None)\n",
        encoding="utf-8")
    findings = lint_rlimits.scan(tmp_path)
    assert len(findings) == 2
    assert any("prlimit()" in item for item in findings)
    assert any(item.startswith("b.py:2:") for item in findings)


def test_allows_child_process_preamble_and_skips_tests_and_tools(tmp_path):
    (tmp_path / "analysis_client.py").write_text(
        "import resource\nresource.setrlimit(resource.RLIMIT_AS, (1, 1))\n",
        encoding="utf-8")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_x.py").write_text(
        "import resource\nresource.setrlimit(resource.RLIMIT_AS, (1, 1))\n",
        encoding="utf-8")
    (tmp_path / "tools").mkdir()
    (tmp_path / "tools" / "demo.py").write_text(
        "import resource\nresource.setrlimit(resource.RLIMIT_AS, (1, 1))\n",
        encoding="utf-8")
    assert lint_rlimits.scan(tmp_path) == []


def test_import_without_call_is_clean(tmp_path):
    (tmp_path / "safe.py").write_text("import resource\nprint(resource.RLIMIT_AS)\n",
                                      encoding="utf-8")
    assert lint_rlimits.scan(tmp_path) == []


def test_main_exit_codes(tmp_path, capsys):
    assert lint_rlimits.main(["--root", str(tmp_path)]) == 0
    assert "通过" in capsys.readouterr().out

    (tmp_path / "bad.py").write_text("import resource\nresource.setrlimit(1, (1, 1))\n",
                                     encoding="utf-8")
    assert lint_rlimits.main(["--root", str(tmp_path)]) == 1
    assert "bad.py:2:" in capsys.readouterr().out
