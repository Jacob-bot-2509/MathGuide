"""接口与资源契约。

三道护栏,全部只读文件、不启动服务、不读 `.env.local`:

1. `main.py` 注册的每个 `/api/*` 路由都必须写进 `backend/README.md` 的接口表
   (v1.25.0 时有 31 条只在代码里,v1.26.0 起由本测试守住);
2. `auth.py` 模块文档串里写的「方法 + 路径」必须与 `main.py` 的注册方式一致
   (曾出现文档写 POST、实际 GET 的情况);
3. 聊天渲染用 npm `katex`,PDF/Word 导出用 `backend/static/katex/`,
   两边版本必须一致,否则会出现「聊天能渲染、导出报错」。
"""
from __future__ import annotations

import json
import re
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
REPO_DIR = BACKEND_DIR.parent
README = BACKEND_DIR / "README.md"
MAIN_PY = BACKEND_DIR / "main.py"
AUTH_PY = BACKEND_DIR / "auth.py"
KATEX_JS = BACKEND_DIR / "static" / "katex" / "katex.min.js"
PACKAGE_LOCK = REPO_DIR / "frontend" / "package-lock.json"

_ROUTE_RE = re.compile(r'Route\(\s*"(/api/[^"]+)"\s*,\s*[\w.]+(.*?)\)\s*,?\s*$', re.M)
_METHOD_RE = re.compile(r'"(GET|POST|PUT|PATCH|DELETE)"')
_BACKTICK_RE = re.compile(r"`([^`]*)`")
_DOC_LINE_RE = re.compile(r"^-\s*(GET|POST|PUT|PATCH|DELETE)\s+(/api/\S+)", re.M)


def _norm(path: str) -> str:
    """把 `{doc_id}` / `{table_id}` 一律归一,README 里两种写法都能匹配。"""
    return re.sub(r"\{[^}]*\}", "X", path.rstrip("/"))


def _routes() -> list[tuple[str, set[str]]]:
    routes: list[tuple[str, set[str]]] = []
    for match in _ROUTE_RE.finditer(MAIN_PY.read_text(encoding="utf-8")):
        methods = set(_METHOD_RE.findall(match.group(2))) or {"GET"}
        routes.append((match.group(1), methods))
    return routes


def _documented_paths() -> set[str]:
    """README 里反引号包起来的路径;去掉 `?query` 与行内说明后归一。"""
    paths: set[str] = set()
    for token in _BACKTICK_RE.findall(README.read_text(encoding="utf-8")):
        match = re.match(r"(/api/[A-Za-z0-9_\-/{}.]*)", token)
        if match:
            paths.add(_norm(match.group(1)))
    return paths


def test_route_table_is_parsed() -> None:
    """护栏本身要是坏了,下面的断言会静默通过 —— 先确认解析到足够多的路由。"""
    routes = _routes()
    assert len(routes) >= 70, f"只解析到 {len(routes)} 条路由,正则可能失效"


def test_every_route_is_documented() -> None:
    documented = _documented_paths()
    missing = [path for path, _ in _routes() if _norm(path) not in documented]
    assert not missing, "backend/README.md 接口表缺以下路由:\n" + "\n".join(sorted(missing))


def test_documented_routes_exist() -> None:
    """反向检查:README 许了但代码没有的路由(说明删接口忘了改文档)。"""
    registered = {_norm(path) for path, _ in _routes()}
    stale = [path for path in _documented_paths() if path not in registered]
    assert not stale, "backend/README.md 写了但 main.py 未注册:\n" + "\n".join(sorted(stale))


def test_auth_docstring_matches_registration() -> None:
    """auth.py 文档串的方法必须与 main.py 注册的一致(文档漏改会直接红)。"""
    registered: dict[str, set[str]] = {}
    for path, methods in _routes():
        registered.setdefault(_norm(path), set()).update(methods)

    declared = _DOC_LINE_RE.findall(AUTH_PY.read_text(encoding="utf-8"))
    assert declared, "auth.py 文档串里没有解析到接口行,契约测试失效"
    for method, path in declared:
        actual = registered.get(_norm(path))
        assert actual, f"auth.py 文档写了 {path},但 main.py 没有注册"
        assert method in actual, f"{path} 文档写 {method},实际注册为 {'/'.join(sorted(actual))}"


def test_katex_version_matches_frontend_lock() -> None:
    """前后端 KaTeX 必须同版本:聊天用 npm 包,PDF/Word 用 backend/static。"""
    assert KATEX_JS.is_file(), "缺少 backend/static/katex/katex.min.js"
    assert PACKAGE_LOCK.is_file(), "缺少 frontend/package-lock.json"

    backend = re.search(r'version:"([0-9]+\.[0-9]+\.[0-9]+)"', KATEX_JS.read_text(encoding="utf-8"))
    assert backend, "katex.min.js 里找不到版本号"
    lock = json.loads(PACKAGE_LOCK.read_text(encoding="utf-8"))
    frontend = (
        lock.get("packages", {}).get("node_modules/katex", {}).get("version")
        or lock.get("dependencies", {}).get("katex", {}).get("version")
    )
    assert frontend, "package-lock.json 里找不到 katex 版本"
    assert backend.group(1) == frontend, (
        f"KaTeX 版本不一致:backend/static {backend.group(1)} vs 前端 {frontend};"
        "升级前端依赖时需同步 backend/static/katex/"
    )
