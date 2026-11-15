"""反代 / 登录态 / 语音入口 / 告警出口的真实链路自检(部署项 2.7 · 2.8 · 2.13)。

这四件事本机一个都测不出来:
  * 证书是否有效、还剩几天;
  * HSTS 该不该发(HTTPS 下不发 = 没有钉子;HTTP 下发了 = scheme 判定有问题);
  * 会话 Cookie 的 `Secure` / `SameSite` / `HttpOnly` / `Domain` 是否真的对;
  * 反代有没有把 `X-Forwarded-Proto` 递到应用手里 —— 没递到时,HTTPS 站点会下发
    不带 Secure 的 cookie,用户看到的是「登录成功,刷新就掉线」。

前四项错起来的症状都指向别处,所以固定成脚本,装机时跑一次。

`--webhook` 会把和线上**完全一样**的告警载荷(`diagram_alerts.build_payload`)投一次,
证明接收端能吃下这个形状;`--voice` 检查 `Permissions-Policy` 是否放行麦克风
(非 localhost 的 http 下 `getUserMedia` 直接不可用,所以语音入口必须 HTTPS)。

用法(在目标机上,直接对真实域名跑):
    python tools/proxy_check.py --base-url https://math.example.com
    python tools/proxy_check.py --base-url https://math.example.com --phone 138... --password ******
    python tools/proxy_check.py --base-url https://math.example.com --webhook https://hooks.example/xxx
    python tools/proxy_check.py --base-url http://127.0.0.1:8000 --spa-path ""   # 只验应用层

退出码:0 = 无 FAIL(WARN 不计);1 = 有 FAIL。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import socket
import ssl
import sys
import time
import urllib.error
import urllib.request
from collections import namedtuple
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

urllib.request.install_opener(urllib.request.build_opener(urllib.request.ProxyHandler({})))

RED, GREEN, YELLOW, GREY, RESET = "\033[91m", "\033[92m", "\033[93m", "\033[90m", "\033[0m"
Resp = namedtuple("Resp", "status headers body")
#: HSTS 建议下限(180 天)。低于它等于「钉子太松」,浏览器很快会忘掉。
HSTS_MIN_MAX_AGE = 15552000
#: 会话 Cookie 名(与 auth.COOKIE_NAME 一致);用于在多个 Set-Cookie 里挑出会话那条。
SESSION_COOKIE = "mg_session"


def parse_cookie(header: str) -> dict:
    """`Set-Cookie` → {"name","value","attrs"}。属性名统一小写,便于判 `Secure` 之类。"""
    parts = [item.strip() for item in (header or "").split(";") if item.strip()]
    if not parts:
        return {"name": "", "value": "", "attrs": {}}
    name, _, value = parts[0].partition("=")
    attrs: dict[str, str] = {}
    for item in parts[1:]:
        key, _, val = item.partition("=")
        attrs[key.strip().lower()] = val.strip()
    return {"name": name.strip(), "value": value.strip(), "attrs": attrs}


def session_cookie_header(headers: list[str]) -> str:
    """从多个 `Set-Cookie` 里挑会话那条;都没有就返回第一条(便于报错时说人话)。"""
    for header in headers:
        if parse_cookie(header)["name"] == SESSION_COOKIE:
            return header
    return headers[0] if headers else ""


def cookie_problems(header: str, *, https: bool) -> list[str]:
    """会话 Cookie 的属性问题清单(空 = 合格)。"""
    attrs = parse_cookie(header)["attrs"]
    problems: list[str] = []
    if "httponly" not in attrs:
        problems.append("缺 HttpOnly:前端脚本能读到会话 cookie")
    samesite = attrs.get("samesite", "")
    if not samesite:
        problems.append("缺 SameSite:跨站表单提交会带上会话 cookie(CSRF 面变大)")
    elif samesite.lower() not in ("lax", "strict"):
        problems.append(f"SameSite={samesite}:None 必须同时有 Secure,且放弃了一道 CSRF 防线")
    if https and "secure" not in attrs:
        problems.append("HTTPS 下缺 Secure:同域 http 请求也会带上它,等于把会话暴露给明文链路")
    if not https and "secure" in attrs:
        problems.append("HTTP 下带 Secure:浏览器不会回传,表现为「登录成功但立刻掉线」")
    return problems


def hsts_issues(value: str, *, https: bool) -> list[str]:
    """HSTS 的硬问题(空 = 合格)。HTTP 直连下出现 HSTS 属于 WARN,不在这里判。"""
    if not https:
        return []
    if not value:
        return ["HTTPS 响应没有 Strict-Transport-Security:浏览器不会被钉在 HTTPS,首次跳转可被降级"]
    match = re.search(r"max-age\s*=\s*(\d+)", value, re.I)
    if not match:
        return [f"HSTS 没有 max-age(值 {value!r}),浏览器视为无效"]
    age = int(match.group(1))
    if age < HSTS_MIN_MAX_AGE:
        return [f"HSTS max-age={age} 低于建议值 {HSTS_MIN_MAX_AGE}(180 天)"]
    return []


def cert_days(not_after: str) -> int | None:
    """证书 `notAfter`(ASN.1 时间串)→ 剩余天数;解析失败返回 None。"""
    try:
        expires = ssl.cert_time_to_seconds(not_after)
    except ValueError:
        return None
    return int((expires - time.time()) // 86400)


def tls_info(host: str, port: int, timeout: float = 10.0) -> tuple[dict, str]:
    """握手一次拿证书信息;证书链有问题时返回 ({}, 原因)。

    这里**不**跳过校验:`create_default_context()` 走系统信任库,校验失败说明服务器
    证书链不全或过期 —— 那正是浏览器会拦、而 `curl -k` 看不出来的情形。
    """
    context = ssl.create_default_context()
    try:
        with socket.create_connection((host, port), timeout=timeout) as raw:
            with context.wrap_socket(raw, server_hostname=host) as tls:
                cert = tls.getpeercert() or {}
                return {"not_after": cert.get("notAfter", ""), "protocol": tls.version() or ""}, ""
    except ssl.SSLCertVerificationError as exc:
        return {}, f"证书校验失败:{exc.verify_message or exc}"
    except (OSError, ssl.SSLError) as exc:
        return {}, f"TLS 握手失败:{exc}"


@dataclass
class Probe:
    """一次探测的会话状态(token 可选)。"""

    base: str
    timeout: float = 20.0
    token: str = ""

    def url(self, path: str) -> str:
        return self.base.rstrip("/") + path

    def call(self, method: str, path: str, body: object = None,
             headers: dict | None = None, timeout: float | None = None) -> Resp:
        data = json.dumps(body).encode("utf-8") if body is not None else None
        final = {"User-Agent": "mg-proxy-check", "Accept": "*/*"}
        if data is not None:
            final["Content-Type"] = "application/json"
        if self.token:
            final["Authorization"] = f"Bearer {self.token}"
        final.update(headers or {})
        request = urllib.request.Request(self.url(path), data=data, method=method, headers=final)
        try:
            with urllib.request.urlopen(request, timeout=timeout or self.timeout) as response:
                return Resp(response.status, dict(response.headers), response.read())
        except urllib.error.HTTPError as exc:
            return Resp(exc.code, dict(exc.headers or {}), exc.read() or b"")
        except OSError as exc:
            # 连不上/TLS 失败/读超时(socket.timeout 也是 OSError)都要落成一条结果,
            # 否则整轮自检会被一个异常打断 —— 而"断了"本身就是最该报告的信息。
            return Resp(0, {}, str(exc).encode("utf-8", "replace"))


def header(resp: Resp, name: str) -> str:
    for key, value in resp.headers.items():
        if key.lower() == name.lower():
            return value
    return ""


def set_cookies(resp: Resp) -> list[str]:
    return [value for key, value in resp.headers.items() if key.lower() == "set-cookie"]


class Report:
    """PASS/FAIL/WARN/SKIP 计数与打印。WARN 不升级成 FAIL:部署窗口里软告警挡路最误事。"""

    def __init__(self) -> None:
        self.passed = self.failed = self.skipped = self.warned = 0

    def ok(self, message: str) -> None:
        self.passed += 1
        print(f"{GREEN}[ OK ]{RESET} {message}")

    def skip(self, message: str) -> None:
        self.skipped += 1
        print(f"{GREY}[SKIP]{RESET} {message}")

    def warn(self, message: str) -> None:
        self.warned += 1
        print(f"{YELLOW}[WARN]{RESET} {message}")

    def fail(self, message: str, hint: str = "") -> None:
        self.failed += 1
        print(f"{RED}[FAIL]{RESET} {message}")
        if hint:
            print(f"        {YELLOW}修复: {hint}{RESET}")


def webhook_payload() -> dict:
    """尽量复用线上同一份载荷构造(形状不对接收端会 400);导入失败退化成等价字面量。"""
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
        import diagram_alerts

        return diagram_alerts.build_payload("deploy_check")
    except Exception:  # noqa: BLE001 探测脚本不能因为导入失败而整体崩溃
        return {"service": "mathguide", "event": "diagram_alert",
                "reason": "deploy_check", "ts": int(time.time())}


def post_webhook(url: str, timeout: float = 10.0) -> tuple[bool, str]:
    """把告警载荷投一次 → (是否 2xx, 说明)。"""
    data = json.dumps(webhook_payload()).encode("utf-8")
    request = urllib.request.Request(url, data=data, method="POST", headers={
        "Content-Type": "application/json", "User-Agent": "mg-proxy-check"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return 200 <= response.status < 300, f"HTTP {response.status} · 投出 {len(data)} 字节"
    except urllib.error.HTTPError as exc:
        return False, f"HTTP {exc.code}(接收端拒收这个载荷形状?)"
    except Exception as exc:  # noqa: BLE001
        return False, f"{exc.__class__.__name__}: {exc}"


def check_tls(report: Report, *, host: str, port: int) -> None:
    info, error = tls_info(host, port)
    if error:
        report.fail(f"TLS:{error}",
                    "证书链要带中间证书、域名要匹配、别过期;nginx 用 ssl_certificate 指向全链文件")
        return
    days = cert_days(info.get("not_after", ""))
    protocol = info.get("protocol", "")
    if days is None:
        report.warn(f"证书到期时间解析不了({info.get('not_after')!r})· 协议 {protocol}")
    elif days < 0:
        report.fail(f"证书已过期 {-days} 天", "立即续期 —— 浏览器会直接拦下整个站点")
    elif days < 7:
        report.fail(f"证书 {days} 天后到期", "现在就续,别等部署收尾再想起")
    elif days < 30:
        report.warn(f"证书 {days} 天后到期(建议提前续期)")
    else:
        report.ok(f"证书校验通过 · {days} 天后到期 · {protocol}")


def check_hsts(probe: Probe, report: Report, *, https: bool) -> None:
    resp = probe.call("GET", "/api/health")
    if resp.status != 200:
        report.fail(f"健康检查 HTTP {resp.status}", "后端没起来?先跑 python tools/smoke_deploy.py")
        return
    value = header(resp, "strict-transport-security")
    issues = hsts_issues(value, https=https)
    if issues:
        report.fail("; ".join(issues),
                    "确认请求真的是 HTTPS(scheme 或 X-Forwarded-Proto);必要时 MG_ENABLE_HSTS=1 强制")
        return
    if https:
        report.ok(f"HSTS 已发 · {value}")
    elif value:
        report.warn(f"HTTP 直连也发了 HSTS({value}):要么 MG_ENABLE_HSTS=1(确认是有意的),"
                    "要么 scheme 判定有误")
    else:
        report.ok("HTTP 直连未发 HSTS(正确:否则浏览器会把这个 http 主机记成只走 HTTPS)")


def check_forwarded_proto(probe: Probe, report: Report, *, https: bool) -> None:
    if https:
        report.skip("X-Forwarded-Proto(已经直连 HTTPS,这一项只在验证反代到应用这一段时才有意义)")
        return
    resp = probe.call("GET", "/api/health", headers={"X-Forwarded-Proto": "https"})
    if header(resp, "strict-transport-security"):
        report.ok("X-Forwarded-Proto 被应用采纳(反代传 https 时会按 HTTPS 处理:Secure cookie + HSTS)")
    else:
        report.fail("应用没有采纳 X-Forwarded-Proto",
                    "反代要 proxy_set_header X-Forwarded-Proto $scheme;否则 HTTPS 站点下发"
                    "不带 Secure 的 cookie,表现为「登录成功,刷新掉线」")


def check_cookie(probe: Probe, report: Report, *, https: bool, phone: str,
                 password: str, cookie_domain: str) -> None:
    if not (phone and password):
        report.skip("会话 Cookie 属性(没给 --phone/--password)")
        return
    resp = probe.call("POST", "/api/auth/login", {"phone": phone, "password": password}, timeout=20)
    if resp.status != 200:
        report.fail(f"登录失败 HTTP {resp.status}: {resp.body[:120]!r}",
                    "确认账号存在且密码正确;429 是 auth 限流(10 次/分/IP),等 60 秒再跑")
        return
    headers = set_cookies(resp)
    if not headers:
        report.fail("登录没下发 Set-Cookie",
                    "auth._auth_json 里的 set_cookie 是否还在;反代是否剥掉了 Set-Cookie")
        return
    session = session_cookie_header(headers)
    problems = cookie_problems(session, https=https)
    if problems:
        report.fail("会话 Cookie:" + "; ".join(problems),
                    "看 auth.py 的 set_cookie(httponly/samesite/secure)与 _is_https 判定")
        return
    attrs = parse_cookie(session)["attrs"]
    actual = attrs.get("domain", "").lstrip(".").lower()
    expected = cookie_domain.strip().lstrip(".").lower()
    if expected and actual != expected:
        report.fail(f"Cookie Domain={actual or '(未设置,仅当前主机)'} 与期望 {expected} 不符",
                    "跨子域共享登录要设 MG_COOKIE_DOMAIN;单域部署应留空")
        return
    if actual and not expected:
        report.warn(f"Cookie Domain={actual}(本机环境没有 MG_COOKIE_DOMAIN,确认线上是否真要跨子域共享)")
    flags = [name for name, key in (("Secure", "secure"), ("HttpOnly", "httponly"))
             if key in attrs]
    flags.append("SameSite=" + attrs.get("samesite", "?"))
    report.ok("会话 Cookie:" + "/".join(flags) + (f" · Domain={actual}" if actual else " · 仅当前主机"))


def check_permissions_policy(probe: Probe, report: Report) -> None:
    """2.8 的前置条件:浏览器侧放不放行麦克风由这个头决定,与有没有 HTTPS 同等重要。"""
    resp = probe.call("GET", "/api/health")
    value = header(resp, "permissions-policy")
    if not value:
        report.fail("缺 Permissions-Policy 头", "security_headers.py 是否挂在 main.py 上")
        return
    if "microphone=(self)" in value.replace(" ", ""):
        report.ok(f"Permissions-Policy 放行麦克风 · {value}")
    else:
        report.warn(f"Permissions-Policy 未放行 microphone=(self):{value}(语音入口在浏览器侧会被禁)")


def check_spa_csp(probe: Probe, report: Report, path: str) -> None:
    if not path:
        report.skip("前端 CSP(--spa-path 为空)")
        return
    resp = probe.call("GET", path)
    if resp.status != 200:
        report.skip(f"前端 {path} 返回 {resp.status}(这台机器不提供前端静态资源,跳过)")
        return
    csp = header(resp, "content-security-policy")
    if not csp:
        report.fail(f"{path} 没有 Content-Security-Policy", "CSP 属于 deploy/ 的反代配置(API 中间件不管 HTML)")
        return
    if "default-src" not in csp:
        report.warn("CSP 缺 default-src(建议给默认兜底,别逐个指令漏)")
    report.ok("前端 CSP:" + (csp[:70] + "…" if len(csp) > 70 else csp))


def check_webhook(report: Report, url: str) -> None:
    if not url:
        report.skip("告警 webhook(未配置 --webhook / MG_DIAGRAM_ALERT_WEBHOOK 为空即关闭)")
        return
    ok, detail = post_webhook(url)
    if ok:
        report.ok(f"告警 webhook 可投递 · {detail}")
        return
    report.fail(f"告警 webhook 投递失败 · {detail}",
                "确认地址可达(需要在**服务器上**跑才有意义)、接收端接受这些字段;"
                "没准备好就把它留空,别留一个永远失败的出口")


def run(probe: Probe, args: argparse.Namespace) -> int:
    parsed = urlsplit(probe.base)
    https = parsed.scheme == "https"
    host = parsed.hostname or ""
    port = parsed.port or (443 if https else 80)
    report = Report()

    print("=" * 68)
    print(f"  MathGuide · 反代/登录态自检(部署项 2.7 · 2.8 · 2.13) · {probe.base}")
    print("  注意:webhook 与证书两项必须在**目标网络**里跑才有意义")
    print("=" * 68)

    # 先确认「连得上」:连不上时后面每一项都会 FAIL,刷一屏误导性的"安全头缺失"
    health = probe.call("GET", "/api/health")
    if health.status == 0:
        detail = (health.body or b"").decode("utf-8", "replace")[:160]
        report.fail(f"连不上 {probe.base}:{detail}",
                    "先确认服务在跑(浏览器或 curl 打开 <base>/api/health);HTTPS 站点还要确认"
                    "这台机器能校验它的证书链")
        print(f"{RED}未通过{RESET}:连通性不成立,其余检查已跳过(它们此时只会误导)")
        return 1

    if https:
        check_tls(report, host=host, port=port)
    else:
        report.skip("TLS 证书(HTTP 直连;真实域名请对 https:// 跑一遍)")
    check_hsts(probe, report, https=https)
    check_forwarded_proto(probe, report, https=https)
    check_cookie(probe, report, https=https, phone=args.phone,
                 password=args.password, cookie_domain=args.cookie_domain)
    check_permissions_policy(probe, report)
    check_spa_csp(probe, report, args.spa_path)
    check_webhook(report, args.webhook or os.getenv("MG_DIAGRAM_ALERT_WEBHOOK", "").strip())

    print("=" * 68)
    print(f"合计:PASS {report.passed} · FAIL {report.failed} · WARN {report.warned} · "
          f"SKIP {report.skipped}")
    if report.failed:
        print(f"{RED}未通过{RESET}:FAIL 项要当场修;WARN 记进部署记录(不是阻断项)")
        return 1
    print(f"{GREEN}通过{RESET}" + ("(WARN 项确认属预期即可)" if report.warned else ""))
    return 0


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # Windows 控制台
        except (OSError, ValueError):
            pass
    parser = argparse.ArgumentParser(description="反代/登录态/语音/webhook 自检")
    parser.add_argument("--base-url", default="https://example.com", help="站点地址(真实域名优先)")
    parser.add_argument("--phone", default="", help="已有账号手机号(验 Cookie 属性用)")
    parser.add_argument("--password", default="", help="已有账号密码")
    parser.add_argument("--cookie-domain", default=os.getenv("MG_COOKIE_DOMAIN", ""),
                        help="期望的 Cookie Domain(默认读 MG_COOKIE_DOMAIN;单域留空)")
    parser.add_argument("--webhook", default="", help="告警 webhook 地址(默认读环境变量)")
    parser.add_argument("--spa-path", default="/", help="前端入口路径(置空则跳过 CSP 检查)")
    parser.add_argument("--timeout", type=float, default=20.0, help="单请求超时(秒)")
    args = parser.parse_args(argv)

    parsed = urlsplit(args.base_url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        print(f"{RED}[FAIL]{RESET} --base-url 不合法:{args.base_url}(要 http(s)://host[:port])")
        return 1

    return run(Probe(base=args.base_url, timeout=args.timeout), args)


if __name__ == "__main__":
    sys.exit(main())



