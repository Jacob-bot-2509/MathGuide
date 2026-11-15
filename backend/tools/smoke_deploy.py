"""部署验收:25 项 HTTP 检查,一条命令出 PASS/FAIL 表。

为什么要有它:`docs/DEPLOY_PLAYBOOK.md` §五 原来是一串 curl,失败了靠人眼比对输出。
脚本化之后,"哪一项红了 + 下一步查什么"本身就是输出的一部分 —— 部署窗口里不用猜。

用法(部署机,服务已起;只依赖标准库,服务器上不需要装项目依赖):
    python tools/smoke_deploy.py                        # 默认打 http://127.0.0.1:8000
    python tools/smoke_deploy.py --base-url https://math.example.com --invite CODE
    python tools/smoke_deploy.py --skip-pdf             # 目标机出不了 PDF 时(记已知限制)
    python tools/smoke_deploy.py --skip-mutating        # 只读:不建号、不导数据

会**真的注册一个临时账号**并在末尾注销(`--keep-account` 可保留,便于事后查日志)。
退出码:0 = 全通过(允许 SKIP);1 = 有 FAIL。
"""
from __future__ import annotations

import argparse
import json
import random
import secrets
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections import namedtuple
from dataclasses import dataclass, field
from http.cookiejar import CookieJar

# 本机/内网直连:不能让系统代理(Clash 之类)截胡 127.0.0.1 的请求,
# 否则自检会报"后端不可达",而真相是请求根本没发出去。
urllib.request.install_opener(urllib.request.build_opener(urllib.request.ProxyHandler({})))

RED, GREEN, YELLOW, GREY, RESET = "\033[91m", "\033[92m", "\033[93m", "\033[90m", "\033[0m"
Resp = namedtuple("Resp", "status headers body")
QA_ITEMS = [{
    "question": "什么是函数极限?",
    "answer": "函数极限描述自变量趋于某点时函数值的趋势。例:lim(x→0) sin x / x = 1。",
}]
MUTATING = "mutating"
NEEDS_AUTH = "auth"


class Failure(Exception):
    """检查失败:message 是"看到了什么",hint 是"下一步查什么"。

    `fatal=True` 用于"前置条件不成立"的项(注册拿不到账号):一旦出现,后面所有
    依赖登录态的检查都失去意义,直接标 SKIP 比刷一屏 FAIL 有用得多。
    """

    def __init__(self, message: str, hint: str = "", *, fatal: bool = False) -> None:
        super().__init__(message)
        self.hint = hint
        self.fatal = fatal


class Skip(Exception):
    """不适用(如目标机本来就不提供 PDF),不算失败。"""


@dataclass
class Ctx:
    base: str
    invite: str = ""
    timeout: float = 30.0
    pdf: bool = True
    mutating: bool = True
    keep_account: bool = False
    phone: str = ""
    password: str = field(default_factory=lambda: "Smoke-" + secrets.token_hex(4))
    token: str = ""
    demo: bool = True
    jar: CookieJar = field(default_factory=CookieJar)
    opener: urllib.request.OpenerDirector = field(init=False)

    def __post_init__(self) -> None:
        self.opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({}),
            urllib.request.HTTPCookieProcessor(self.jar),
        )

    def url(self, path: str) -> str:
        return self.base.rstrip("/") + path


def call(ctx: Ctx, method: str, path: str, body: object = None, *,
         token: str = "", headers: dict | None = None,
         timeout: float | None = None, raw: bytes | None = None) -> Resp:
    """发一次请求并把 HTTPError 也当普通响应(状态码是要断言的,不是要抛的)。"""
    data = raw
    if body is not None:
        data = json.dumps(body).encode("utf-8")
    final_headers = {"User-Agent": "mg-smoke-deploy", "Accept": "*/*"}
    if data is not None:
        final_headers["Content-Type"] = "application/json"
    if token:
        final_headers["Authorization"] = f"Bearer {token}"
    final_headers.update(headers or {})
    request = urllib.request.Request(ctx.url(path), data=data, method=method,
                                     headers=final_headers)
    try:
        with ctx.opener.open(request, timeout=timeout or ctx.timeout) as response:
            return Resp(response.status, dict(response.headers), response.read())
    except urllib.error.HTTPError as exc:
        return Resp(exc.code, dict(exc.headers or {}), exc.read() or b"")


def expect(condition: object, message: str, hint: str = "") -> None:
    if not condition:
        raise Failure(message, hint)


def _json(resp: Resp) -> dict:
    try:
        parsed = json.loads(resp.body or b"{}")
    except json.JSONDecodeError as exc:
        raise Failure(f"响应不是 JSON({len(resp.body)} 字节)",
                      "看服务端日志有无 500;反代可能返回了 HTML 错误页") from exc
    expect(isinstance(parsed, dict), "响应不是 JSON 对象", "反代改写/返回了 HTML")
    return parsed


def _header(resp: Resp, name: str) -> str:
    for key, value in resp.headers.items():
        if key.lower() == name.lower():
            return value
    return ""


def _new_phone() -> str:
    """随机 11 位手机号(合法前缀,避免和真实数据撞号)。"""
    return "1" + random.choice("3456789") + "".join(
        random.choice("0123456789") for _ in range(9))


# ------------------------------------------------------------ 1-5 基础可用
def check_health(ctx: Ctx) -> str:
    resp = call(ctx, "GET", "/api/health")
    expect(resp.status == 200, f"期望 200,实际 {resp.status}", "后端没起来?看 systemctl/journalctl")
    body = _json(resp)
    expect(body.get("ok") is True, f"health 非 ok: {body}", "接口被占位页/反代拦截?")
    ctx.demo = bool(body.get("demo"))
    return f"200 ok · service={body.get('service')} · demo={ctx.demo}"


def check_session_anonymous(ctx: Ctx) -> str:
    resp = call(ctx, "GET", "/api/auth/session")
    expect(resp.status == 401, f"未登录应为 401,实际 {resp.status}", "会话校验可能被跳过")
    return "401(未登录)"


def check_security_headers(ctx: Ctx) -> str:
    resp = call(ctx, "GET", "/api/health")
    required = ("x-content-type-options", "x-frame-options", "referrer-policy")
    missing = [name for name in required if not _header(resp, name)]
    expect(not missing, f"缺安全头: {missing}", "检查 main.py 是否挂了 SecurityHeadersMiddleware")
    hsts = "HSTS 已发" if _header(resp, "strict-transport-security") else "HSTS 未发(HTTP 下正常)"
    return "nosniff / DENY / no-referrer 齐全 · " + hsts


def check_malformed_json(ctx: Ctx) -> str:
    resp = call(ctx, "POST", "/api/auth/login", raw=b"{not json",
                headers={"Content-Type": "application/json"})
    expect(resp.status == 400, f"畸形 JSON 应为 400,实际 {resp.status}",
           "http_utils.read_json_object 是否仍在用?")
    return "400"


# ------------------------------------------------------------ 6-14 鉴权
def check_register(ctx: Ctx) -> str:
    ctx.phone = ctx.phone or _new_phone()
    body: dict = {"phone": ctx.phone, "password": ctx.password}
    if ctx.invite:
        body["invite"] = ctx.invite
    resp = call(ctx, "POST", "/api/auth/register", body)
    if resp.status == 429:
        raise Failure("注册被限流(429)",
                      "auth 接口默认 10 次/分/IP:等 60 秒再跑,别连着跑两遍", fatal=True)
    if resp.status == 403:
        raise Failure("注册被邀请码拦下",
                      "非演示模式需要邀请码:--invite <MG_INVITE_CODES 里的值>", fatal=True)
    expect(resp.status == 200, f"注册失败: {resp.status} {resp.body[:120]!r}",
           "手机号格式/密码长度?MG_INVITE_CODES?")
    data = _json(resp)
    ctx.token = str(data.get("token") or "")
    expect(ctx.token, "注册没返回 token", "auth.register 的 _auth_json 是否被改动?")
    expect("mg_session" in _header(resp, "set-cookie"), "注册没下发 mg_session Cookie",
           "COOKIE_NAME / Cookie Domain 配置")
    return f"{ctx.phone} 注册成功(token + Cookie)"


def check_session_cookie(ctx: Ctx) -> str:
    resp = call(ctx, "GET", "/api/auth/session")
    expect(resp.status == 200, f"Cookie 会话应为 200,实际 {resp.status}",
           "Cookie 没带回?检查 SameSite/Domain/反代")
    return "200(Cookie)"


def check_session_bearer(ctx: Ctx) -> str:
    resp = call(ctx, "GET", "/api/auth/session", token=ctx.token)
    expect(resp.status == 200, f"Bearer 会话应为 200,实际 {resp.status}",
           "Authorization 头被反代丢掉?")
    return "200(Bearer)"


def check_weak_password(ctx: Ctx) -> str:
    resp = call(ctx, "POST", "/api/auth/register", {"phone": _new_phone(), "password": "123"})
    expect(resp.status == 400, f"弱口令应为 400,实际 {resp.status}", "密码强度校验被绕过?")
    return "400(weak password)"


def check_duplicate_phone(ctx: Ctx) -> str:
    resp = call(ctx, "POST", "/api/auth/register",
                {"phone": ctx.phone, "password": ctx.password})
    expect(resp.status == 409, f"重复手机号应为 409,实际 {resp.status}",
           "唯一索引失效?查 users.phone")
    return "409(exists)"


def check_cross_site_post(ctx: Ctx) -> str:
    resp = call(ctx, "POST", "/api/chat/stream", {"prompt": ""}, token=ctx.token,
                headers={"Origin": "https://evil.example"})
    expect(resp.status == 403, f"跨站 POST 应为 403,实际 {resp.status}",
           "origin_guard 是否挂上?MG_CORS_ORIGINS 是否过宽?")
    return "403(跨站 Origin 被拒)"


def check_logout(ctx: Ctx) -> str:
    resp = call(ctx, "POST", "/api/auth/logout", {}, token=ctx.token)
    expect(resp.status == 200, f"登出应为 200,实际 {resp.status}", "看 auth.logout 是否抛异常")
    return "200"


def check_post_logout_credentials(ctx: Ctx) -> str:
    """登出必须**两个凭据都失效**:只清 Cookie 会让旧 Bearer 继续可用(用户以为已登出)。"""
    cookie = call(ctx, "GET", "/api/auth/session")
    expect(cookie.status == 401, f"登出后 Cookie 仍可用({cookie.status})",
           "logout 没清 Cookie,或 token 未吊销")
    bearer = call(ctx, "GET", "/api/auth/session", token=ctx.token)
    expect(bearer.status == 401, f"登出后旧 Bearer 仍可用({bearer.status})",
           "token 吊销失效(store.revoke_token)")
    return "401(Cookie 与 Bearer 双失效)"


def check_relogin(ctx: Ctx) -> str:
    """后面几项要带凭据:重新登录一次(顺带验证"登出后还能登回来")。"""
    resp = call(ctx, "POST", "/api/auth/login", {"phone": ctx.phone, "password": ctx.password})
    expect(resp.status == 200, f"重新登录失败 {resp.status}: {resp.body[:120]!r}",
           "密码哈希/账号状态?看 auth.login 日志")
    ctx.token = str(_json(resp).get("token") or "")
    expect(ctx.token, "重新登录没返回 token", "auth.login 的 _auth_json")
    return "200(新 token)"


# ------------------------------------------------------------ 15-18 链路
def check_sse(ctx: Ctx) -> str:
    # 空 prompt 走罐头欢迎语:不调用模型、不占额度,但把 SSE 帧协议整条走通
    resp = call(ctx, "POST", "/api/chat/stream", {"prompt": ""}, token=ctx.token)
    expect(resp.status == 200, f"SSE 应为 200,实际 {resp.status}", "看后端日志;反代是否缓冲了流?")
    text = resp.body.decode("utf-8", "replace")
    expect("data:" in text, "响应里没有 data: 帧", "反代可能把 SSE 当普通响应缓冲")
    expect("[DONE]" in text, "SSE 未以 [DONE] 收尾", "流被中途切断(超时/反代缓冲)")
    return f"200 · {len(text)} 字节 · 以 [DONE] 收尾"


def check_research_docs(ctx: Ctx) -> str:
    resp = call(ctx, "GET", "/api/research/docs", token=ctx.token)
    expect(resp.status == 200, f"论文库列表 {resp.status}", "research_corpus 路由 / data 目录权限")
    docs = _json(resp).get("docs", [])
    storage = call(ctx, "GET", "/api/research/storage", token=ctx.token)
    expect(storage.status == 200, f"存储用量 {storage.status}", "data/research 目录可写?")
    return f"200 · 当前 {len(docs)} 篇 · 存储用量可用"


def check_research_tables(ctx: Ctx) -> str:
    resp = call(ctx, "GET", "/api/research/tables", token=ctx.token)
    expect(resp.status == 200, f"数据表列表 {resp.status}", "research_tables 路由")
    tables = _json(resp).get("tables", [])
    return f"200 · 当前 {len(tables)} 张"


def check_not_found_semantics(ctx: Ctx) -> str:
    """三种 404 一起看:未注册路由、不存在的文档、不存在的数据表。

    反代把 404 改成 200(软 404 页面)是部署里最常见的一种"看不出来的错",
    前端会拿到 HTML 当 JSON 解析,报一堆看不懂的错。
    """
    unknown = call(ctx, "GET", "/api/__no_such_route__")
    expect(unknown.status == 404, f"未知路径应为 404,实际 {unknown.status}",
           "反代把 404 改写成了 200?检查 error_page / try_files")
    doc = call(ctx, "GET", "/api/research/docs/__no_such_doc__", token=ctx.token)
    expect(doc.status == 404, f"不存在的文档应为 404,实际 {doc.status}", "路径参数校验")
    # 用 GET 而不是 compute:compute 会先校验请求体(缺 columns 时 400 才是对的),
    # 拿它验 404 会把"参数校验"误判成"资源不存在"。
    table = call(ctx, "GET", "/api/research/tables/__no_such_table__", token=ctx.token)
    expect(table.status == 404, f"不存在的表应为 404,实际 {table.status}", "数据表路径参数校验")
    return "404 · 路由 / 文档 / 数据表"


# ------------------------------------------------------------ 19-23 导出与守卫
def check_export_markdown(ctx: Ctx) -> str:
    resp = call(ctx, "POST", "/api/doc/qa", {"items": QA_ITEMS, "format": "md", "lang": "zh"},
                token=ctx.token)
    expect(resp.status == 200, f"Markdown 导出 {resp.status}: {resp.body[:120]!r}", "看后端日志")
    expect("text/markdown" in _header(resp, "content-type"), "Content-Type 不是 text/markdown",
           "docgen._render 的 md 分支")
    expect("attachment" in _header(resp, "content-disposition"), "缺 Content-Disposition",
           "下载头被反代剥离?")
    return f"200 · {len(resp.body)} 字节"


def check_export_pdf(ctx: Ctx) -> str:
    if not ctx.pdf:
        raise Skip("--skip-pdf")
    resp = call(ctx, "POST", "/api/doc/qa", {"items": QA_ITEMS, "format": "pdf", "lang": "zh"},
                token=ctx.token, timeout=180)
    if resp.status == 429:
        raise Failure("导出被并发闸门拒绝(429)",
                      "此刻正有人在导出;等 20 秒重跑这一项即可")
    expect(resp.status == 200, f"PDF 导出 {resp.status}: {resp.body[:200]!r}",
           "先在服务器跑 python tools/check_pdf.py;再看 MG_EDGE_NO_SANDBOX")
    expect(resp.body.startswith(b"%PDF"), "产物不是 PDF(没有 %PDF 头)",
           "浏览器起得来但打印失败:字体 / 沙箱 / --headless 参数")
    expect("application/pdf" in _header(resp, "content-type"), "Content-Type 不是 application/pdf", "")
    return f"200 · {len(resp.body)} 字节 · %PDF 头正确"


def check_export_docx(ctx: Ctx) -> str:
    resp = call(ctx, "POST", "/api/doc/qa", {"items": QA_ITEMS, "format": "docx", "lang": "zh"},
                token=ctx.token, timeout=180)
    if resp.status == 429:
        raise Failure("Word 导出被并发闸门拒绝(429)", "等 20 秒重跑")
    expect(resp.status == 200, f"Word 导出 {resp.status}: {resp.body[:200]!r}", "看后端日志")
    expect(resp.body.startswith(b"PK"), "产物不是 docx(zip)", "python-docx 写入失败?")
    return f"200 · {len(resp.body)} 字节"


def check_export_too_much_content(ctx: Ctx) -> str:
    # 6 × 8000 字 > MAX_TOTAL_CHARS(40000):必须在**渲染前**拒绝,
    # 而不是先起浏览器跑 30 秒再报错(那条路径在低配机上很贵)
    items = [{"question": "q" * 100, "answer": "a" * 8000} for _ in range(6)]
    resp = call(ctx, "POST", "/api/doc/qa", {"items": items, "format": "md"}, token=ctx.token)
    expect(resp.status == 413, f"超量内容应为 413,实际 {resp.status}", "MAX_TOTAL_CHARS 校验丢失?")
    return "413(too much content)"


def check_print_guard(ctx: Ctx) -> str:
    resp = call(ctx, "POST", "/api/research/tables/__no_such_table__/print", {},
                token=ctx.token, headers={"Host": "mathguide.example.com"})
    expect(resp.status == 403, f"公网 Host 触发打印应为 403,实际 {resp.status}",
           "生产不要开 MG_PRINT_OPEN;检查 research_tables._print_allowed")
    return "403(打印仅本机)"


def check_stats_requires_admin(ctx: Ctx) -> str:
    resp = call(ctx, "GET", "/api/stats", token=ctx.token)
    expect(resp.status in (401, 403), f"非管理员访问统计应为 401/403,实际 {resp.status}",
           "admin 判定被绕过?查 auth.require_admin")
    return f"{resp.status}(非管理员被拒)"


# ------------------------------------------------------------ 24-25 收尾
def check_delete_account(ctx: Ctx) -> str:
    resp = call(ctx, "POST", "/api/account/delete", {"password": ctx.password}, token=ctx.token)
    expect(resp.status == 200, f"注销 {resp.status}: {resp.body[:120]!r}",
           "看 auth.delete_account 日志(级联删除 research_*/diagnosis)")
    ctx.keep_account = True  # 已经删掉了,收尾不必再删
    return "200"


def check_after_delete_cookie(ctx: Ctx) -> str:
    resp = call(ctx, "GET", "/api/auth/session")
    expect(resp.status == 401, f"注销后 Cookie 仍可用({resp.status})", "users/tokens 未级联删除")
    return "401(账号已不存在)"


CHECKS = [
    ("健康检查", check_health, frozenset()),
    ("未登录 401", check_session_anonymous, frozenset()),
    ("安全响应头", check_security_headers, frozenset()),
    ("畸形 JSON 400", check_malformed_json, frozenset()),
    ("注册下发凭据", check_register, frozenset({MUTATING})),
    ("Cookie 会话", check_session_cookie, frozenset({MUTATING, NEEDS_AUTH})),
    ("Bearer 会话", check_session_bearer, frozenset({MUTATING, NEEDS_AUTH})),
    ("弱口令 400", check_weak_password, frozenset({MUTATING})),
    ("重复手机号 409", check_duplicate_phone, frozenset({MUTATING})),
    ("跨站 POST 403", check_cross_site_post, frozenset({MUTATING, NEEDS_AUTH})),
    ("登出", check_logout, frozenset({MUTATING, NEEDS_AUTH})),
    ("登出后双凭据失效", check_post_logout_credentials, frozenset({MUTATING, NEEDS_AUTH})),
    ("重新登录", check_relogin, frozenset({MUTATING, NEEDS_AUTH})),
    ("SSE 以 [DONE] 收尾", check_sse, frozenset({MUTATING, NEEDS_AUTH})),
    ("论文库与存储", check_research_docs, frozenset({MUTATING, NEEDS_AUTH})),
    ("数据表列表", check_research_tables, frozenset({MUTATING, NEEDS_AUTH})),
    ("404 语义", check_not_found_semantics, frozenset({MUTATING, NEEDS_AUTH})),
    ("Markdown 导出", check_export_markdown, frozenset({MUTATING, NEEDS_AUTH})),
    ("PDF 导出", check_export_pdf, frozenset({MUTATING, NEEDS_AUTH})),
    ("Word 导出", check_export_docx, frozenset({MUTATING, NEEDS_AUTH})),
    ("超量内容 413", check_export_too_much_content, frozenset({MUTATING, NEEDS_AUTH})),
    ("打印守卫 403", check_print_guard, frozenset({MUTATING, NEEDS_AUTH})),
    ("统计需管理员", check_stats_requires_admin, frozenset({MUTATING, NEEDS_AUTH})),
    ("注销账号", check_delete_account, frozenset({MUTATING, NEEDS_AUTH})),
    ("注销后 Cookie 401", check_after_delete_cookie, frozenset({MUTATING, NEEDS_AUTH})),
]


def _cleanup(ctx: Ctx) -> None:
    """中途失败时别把临时账号留在线上(否则统计里会多出一个陌生人)。"""
    if not ctx.mutating or ctx.keep_account or not ctx.token or not ctx.phone:
        return
    resp = call(ctx, "POST", "/api/account/delete", {"password": ctx.password}, token=ctx.token)
    if resp.status == 200:
        print(f"{GREY}[i]{RESET} 已清理临时账号 {ctx.phone}")


def run(ctx: Ctx) -> int:
    print("=" * 64)
    print(f"  MathGuide 部署验收 · {ctx.base}")
    print("  模式:" + ("只读(--skip-mutating)" if not ctx.mutating else "完整")
          + ("" if ctx.pdf else " · 跳过 PDF"))
    print("=" * 64)

    passed = failed = skipped = 0
    auth_broken = False
    for index, (name, func, flags) in enumerate(CHECKS, 1):
        if not ctx.mutating and MUTATING in flags:
            skipped += 1
            print(f"{GREY}[{index:2d}] SKIP{RESET}  {name}(--skip-mutating)")
            continue
        if auth_broken and NEEDS_AUTH in flags:
            skipped += 1
            print(f"{GREY}[{index:2d}] SKIP{RESET}  {name}(前置注册失败,没有可用账号)")
            continue
        try:
            detail = func(ctx)
            passed += 1
            print(f"{GREEN}[{index:2d}] PASS{RESET}  {name} · {detail}")
        except Skip as reason:
            skipped += 1
            print(f"{GREY}[{index:2d}] SKIP{RESET}  {name}({reason})")
        except Failure as exc:
            failed += 1
            print(f"{RED}[{index:2d}] FAIL{RESET}  {name} · {exc}")
            if exc.hint:
                print(f"        {YELLOW}修复:{exc.hint}{RESET}")
            auth_broken = auth_broken or exc.fatal
        except Exception as exc:  # noqa: BLE001 任何异常都落成一条 FAIL,不能中断整轮
            failed += 1
            print(f"{RED}[{index:2d}] FAIL{RESET}  {name} · {exc.__class__.__name__}: {exc}")
            print(f"        {YELLOW}修复:看服务端日志与 docs/DEPLOY_PLAYBOOK.md §五{RESET}")

    print("=" * 64)
    print(f"合计:PASS {passed} · FAIL {failed} · SKIP {skipped}")
    if failed:
        print(f"{RED}验收未通过{RESET}:先修 FAIL 项;SKIP 项要记进已知限制(playbook §六)")
    else:
        tail = f"(SKIP {skipped} 项请确认属于预期)" if skipped else ""
        print(f"{GREEN}全部通过{RESET}{tail}")
    return 1 if failed else 0


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # Windows 控制台
    parser = argparse.ArgumentParser(description="部署验收 25 项")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000", help="服务地址")
    parser.add_argument("--invite", default="", help="非演示模式的注册邀请码")
    parser.add_argument("--phone", default="", help="指定注册手机号(默认随机)")
    parser.add_argument("--timeout", type=float, default=30.0, help="单请求超时(秒)")
    parser.add_argument("--skip-pdf", action="store_true", help="跳过 PDF 导出(目标机不具备时)")
    parser.add_argument("--skip-mutating", action="store_true", help="只读检查:不注册、不导出")
    parser.add_argument("--keep-account", action="store_true", help="保留临时账号便于查日志")
    args = parser.parse_args(argv)

    parsed = urllib.parse.urlsplit(args.base_url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        print(f"{RED}[FAIL]{RESET} --base-url 不合法: {args.base_url}(要 http(s)://host[:port])")
        return 1

    ctx = Ctx(base=args.base_url, invite=args.invite, timeout=args.timeout,
              pdf=not args.skip_pdf, mutating=not args.skip_mutating,
              keep_account=args.keep_account, phone=args.phone)
    try:
        return run(ctx)
    finally:
        _cleanup(ctx)


if __name__ == "__main__":
    sys.exit(main())



