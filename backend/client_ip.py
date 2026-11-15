"""客户端 IP 解析:把「反代信任链」收进代码,不再依赖启动参数。

为什么要有这个模块
------------------
登录/注册/登出/账号导出/账号注销这 5 个入口按「10 次/分/IP」限流,key 来自
`auth._client_key`,而它原来直接取 `request.client.host` —— 这个值对不对**完全**
取决于「uvicorn 有没有开 `--proxy-headers`、`--forwarded-allow-ips` 写的是什么、
反代有没有追加 `X-Forwarded-For`」三处是否同时正确。三者任一不对,结果不是报错,
而是**静默**变成下面两种之一:

  * **塌陷**:所有用户算成反代的地址 → 全站共享一个桶,第 11 个登录的人直接 429
    (本来只是「同一个出口 NAT 共用一个桶」),日志里也再没有真实 IP;
  * **绕过**:白名单写 `*` → uvicorn 采信 XFF 最左边那个(客户端可随意改),
    「10 次/分/IP」等于不存在,日志里的 IP 还能被伪造。

现在改成本模块是唯一决策点,规则只有两条:

    MG_TRUSTED_PROXIES=127.0.0.1,172.17.0.1/32      # 我们自己反代的地址(可含 CIDR)
  1. 直连对端**不在**白名单 → `X-Forwarded-For` 一律忽略(伪造无效);
  2. 在 → 从右往左取第一个不在白名单里的地址(nginx 追加的那个),跳过自己叠的每一层反代。

`*` / `0.0.0.0/0` / `::/0` 直接拒绝启动:那不是配置,是把限流关掉。

配套(缺一不可,见 deploy/ 与 docs/DEPLOY_PLAYBOOK.md §一.4)
-----------------------------------------------------------
  * **必须显式加 `--no-proxy-headers`**:uvicorn 0.52 的 `--proxy-headers` 是**默认开启**的
    (白名单默认 `127.0.0.1`),只要对端命中它自己的白名单,它就会在应用之前把
    `scope["client"]` 改写成「右起第一个不在它白名单里的地址」——后端根本看不到真实对端,
    也就无从校验。此时本模块只能退回「认 uvicorn 给的值」(via=`uvicorn`)并打 WARN;
    单层反代能凑巧正确,多挂一层 CDN 就会变成「按 CDN 节点分桶」。
  * 反代必须保留 `proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;`。
  * 前面再挂 CDN 时把 CDN 回源网段也加进白名单(或让 nginx 做 `set_real_ip_from`)。
"""
from __future__ import annotations

import hashlib
import ipaddress
import os
import sys
import time
from dataclasses import dataclass, field

from log import get_logger

log = get_logger(__name__)

#: 受信反代白名单(逗号分隔的 IP 或 CIDR)。不配 = 谁都不信,只按直连对端计。
TRUST_ENV = "MG_TRUSTED_PROXIES"
#: 设为 1 时 /api/health 带一条客户端 IP 摘要(哈希 + 来源),供 tools/proxy_check.py 验收。
#: 默认关闭:健康检查是公开接口,没必要长期暴露这条信息。
DIAG_ENV = "MG_DIAG_CLIENT_IP"
#: 通配写法一律拒绝(见模块注释的「绕过」);`any` 也算通配,避免有人以为是域名。
WILDCARDS = {"*", "any", "0.0.0.0/0", "::/0"}
#: XFF 链最大回溯跳数:反代层数不会多,给个上界以免畸形头把单次判定拖长。
MAX_HOPS = 16
#: 同一类告警的最小间隔(秒)。塌陷时每个请求都会命中,不限速会把日志刷满。
WARN_WINDOW = 60.0
LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}


@dataclass(frozen=True)
class Chain:
    """受信反代集合。`raw` 只用于日志与测试断言。"""

    raw: str = ""
    networks: tuple = field(default_factory=tuple)

    @property
    def empty(self) -> bool:
        return not self.networks

    def trusts(self, addr) -> bool:
        """addr 是本模块解析出的 ip 对象(None 表示对端不是合法 IP,一律不信)。"""
        if addr is None:
            return False
        return any(addr.version == net.version and addr in net for net in self.networks)


def parse_ip(text: str):
    """把一段地址文本解析成 ip 对象;失败返回 None。

    容忍反代/日志里常见的三种写法:`1.2.3.4:5000`、`[::1]:5000`、`::ffff:1.2.3.4`。
    解析失败**不抛异常**:XFF 是外部输入,一个畸形 token 不应该让登录接口 500。
    """
    token = (text or "").strip()
    if not token:
        return None
    if token.startswith("["):  # [::1] / [::1]:5000
        token = token[1:].split("]", 1)[0]
    elif token.count(":") == 1 and "." in token:  # 1.2.3.4:5000
        token = token.split(":", 1)[0]
    try:
        addr = ipaddress.ip_address(token)
    except ValueError:
        return None
    if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped:
        return addr.ipv4_mapped  # ::ffff:1.2.3.4 与 1.2.3.4 必须落进同一个桶
    return addr


def parse_trusted(raw: str) -> Chain:
    """解析 MG_TRUSTED_PROXIES。

    配错就抛 `ValueError`(由 `configure()` 在启动时转成拒绝启动):白名单写错时
    最坏结果不是「多信一点」,而是按 IP 限流整体失效且没有任何症状。
    """
    tokens = [token.strip() for token in (raw or "").split(",") if token.strip()]
    for token in tokens:
        if token in WILDCARDS:
            raise ValueError(
                f"{TRUST_ENV} 不能写 {token!r}:放行任意对端等于采信客户端自己塞的 "
                "X-Forwarded-For,「10 次/分/IP」形同虚设,日志里的 IP 也能被伪造。"
                "请写反代的实际地址,如 127.0.0.1 或 172.17.0.1/32"
            )
    networks = []
    for token in tokens:
        try:
            networks.append(ipaddress.ip_network(token, strict=False))
        except ValueError:
            raise ValueError(
                f"{TRUST_ENV} 里的 {token!r} 不是合法 IP/CIDR(逗号分隔,如 "
                "127.0.0.1,172.17.0.1/32)"
            ) from None
    return Chain(raw=",".join(tokens), networks=tuple(networks))


_CACHE: tuple[str, Chain] | None = None
_WARN_AT: dict[str, float] = {}
#: uvicorn 的 --proxy-headers 是否还开着(默认就是开的):开着时后端看不到真实对端。
_OWNED = False


def _emit(message: str) -> None:
    """告警出口(单列出来,测试可以直接替换)。"""
    log.error(message)


def _warn(kind: str, message: str, now: float | None = None) -> None:
    """同类告警按 WARN_WINDOW 限频:塌陷时每个请求都会命中,刷屏等于没有告警。"""
    moment = time.monotonic() if now is None else now
    last = _WARN_AT.get(kind)
    if last is not None and moment - last < WARN_WINDOW:
        return
    _WARN_AT[kind] = moment
    _emit(message)


def settings() -> Chain:
    """当前生效的白名单(按 env 字符串记忆化:好测,也不怕 .env 装载顺序)。"""
    global _CACHE
    raw = os.getenv(TRUST_ENV, "")
    if _CACHE is not None and _CACHE[0] == raw:
        return _CACHE[1]
    try:
        chain = parse_trusted(raw)
    except ValueError:
        # 启动时 configure() 已经拒绝过这种配置;能走到这里的是运行中被改了 env,
        # 这时宁可「谁都不信」(XFF 忽略)也不能采信客户端可控的头。
        _warn("bad-config", f"[client-ip] {TRUST_ENV}={raw!r} 非法,已按「不信任任何反代」处理")
        chain = Chain(raw=raw, networks=())
    _CACHE = (raw, chain)
    return chain


def resolve(peer: str, forwarded_for: str, chain: Chain | None = None,
            owned: bool = False) -> tuple[str, str]:
    """(客户端 IP, 来源)。来源用于告警与自检:

    `forwarded`       —— 白名单命中,取到的是 XFF 里反代追加的真实地址(正常)
    `peer`            —— 按直连对端计:要么没有 XFF,要么整条链全是自己的反代
    `peer-untrusted`  —— 有 XFF 但对端不在白名单 → 已经塌陷,必须告警
    `uvicorn`         —— uvicorn 的 --proxy-headers 已经改写过后端看到的值(无法校验)

    `owned=True` 表示 uvicorn 的代理头中间件仍开着:此时 `peer` 可能已被它改写,
    再按自己的白名单走一遍只会得到"对端不可信"的假警报,所以直接认它的结果。
    """
    chain = settings() if chain is None else chain
    addr = parse_ip(peer)
    forwarded = (forwarded_for or "").strip()
    if not chain.trusts(addr):
        # 对端不可信:XFF 是客户端可控字符串,读了就等于把限流交给攻击者。
        text = str(addr) if addr is not None else (peer or "").strip() or "unknown"
        if forwarded and owned and addr is not None:
            # uvicorn 改写时取的是「右起第一个非受信地址」,所以被改写的对端必然等于
            # XFF 最右一跳;不相等 = 它根本没改写(对端是真的反代地址)→ 仍按塌陷报警。
            hops = [hop for hop in (parse_ip(token) for token in forwarded.split(","))
                    if hop is not None]
            if hops and hops[-1] == addr:
                return text, "uvicorn"
        return text, ("peer-untrusted" if forwarded else "peer")
    tokens = forwarded.split(",")
    if len(tokens) > MAX_HOPS:
        tokens = tokens[-MAX_HOPS:]
    for token in reversed(tokens):
        hop = parse_ip(token)
        if hop is None or chain.trusts(hop):
            continue  # 畸形 token 跳过;自己的反代/CDN 回源继续往左找
        return str(hop), "forwarded"
    # XFF 为空,或整条链都是我们自己的地址:退回直连对端(总比认一个不可信的强)
    return str(addr), "peer"


def client_key(request) -> str:
    """按 IP 限流用的 key(供 auth._client_key 调用)。"""
    peer = getattr(getattr(request, "client", None), "host", "") or ""
    forwarded = request.headers.get("x-forwarded-for", "")
    key, via = resolve(peer, forwarded, owned=uvicorn_owned())
    if via == "peer-untrusted":
        _warn(
            "untrusted-peer",
            f"[client-ip] 收到 X-Forwarded-For 但直连对端 {peer} 不在 {TRUST_ENV} 里,"
            "已忽略该头 → 所有用户会塌成同一个 IP 桶(登录 10 次/分全站共享)。"
            f"请把反代地址填进 {TRUST_ENV}(如 127.0.0.1 或 172.17.0.1/32)后重启后端;"
            "详见 docs/DEPLOY_PLAYBOOK.md §一.4",
        )
    return key


def diag_enabled() -> bool:
    return os.getenv(DIAG_ENV, "").strip().lower() in ("1", "true", "yes", "on")


def uvicorn_owned() -> bool:
    """真实 IP 是否被 uvicorn 的代理头中间件抢走了(由 configure() 设置)。"""
    return _OWNED


def health_hint(request) -> dict:
    """`/api/health` 的诊断字段:`MG_DIAG_CLIENT_IP=1` 时才返回,否则空字典。

    只给 12 位 SHA-256 摘要 + 来源,不含明文 IP:足够让 proxy_check.py 判断
    「两个不同客户端是不是两个桶」「伪造的 XFF 有没有生效」,又不会把 IP 变成公开信息。
    """
    if not diag_enabled():
        return {}
    peer = getattr(getattr(request, "client", None), "host", "") or ""
    key, via = resolve(peer, request.headers.get("x-forwarded-for", ""), owned=_OWNED)
    ref = hashlib.sha256(key.encode("utf-8")).hexdigest()[:12]
    return {"client": {"ref": ref, "via": via, "proxies": len(settings().networks)}}


def reset(chain: Chain | None = None) -> None:
    """清空记忆与告警限频(测试用)。传 chain 可跳过 env 直接注入。"""
    global _CACHE, _OWNED
    _WARN_AT.clear()
    _OWNED = False
    _CACHE = (os.getenv(TRUST_ENV, ""), chain) if chain is not None else None


def _forwarded_allow_ips(argv: list[str] | None = None) -> str | None:
    """取 uvicorn 的 --forwarded-allow-ips(两种写法),没写返回 None。"""
    args = sys.argv[1:] if argv is None else argv
    value = None
    for index, arg in enumerate(args):
        if arg == "--forwarded-allow-ips" and index + 1 < len(args):
            value = args[index + 1].strip()
        elif arg.startswith("--forwarded-allow-ips="):
            value = arg.split("=", 1)[1].strip()
    return value


def _has_flag(name: str, argv: list[str] | None = None) -> bool:
    args = sys.argv[1:] if argv is None else argv
    return name in args


def configure(*, demo: bool, bound: str, argv: list[str] | None = None) -> Chain:
    """启动校验 + 打印生效链路。由 main.py 在 env 装载后调用。

    这里做的每一件都是「静默变形 → 部署窗口内报错」:参数错了当场拒绝启动,
    而不是让线上跑着一个人人共享的 10 次/分桶。
    """
    raw = os.getenv(TRUST_ENV, "")
    try:
        chain = parse_trusted(raw)
    except ValueError as exc:
        raise RuntimeError(
            f"{exc}。真实 IP 判定错时按 IP 限流会静默变形(全员一个桶或被伪造绕过),"
            "所以这里直接拒绝启动"
        ) from None
    reset(chain)  # 让记忆化立刻切到这份已校验的配置

    allow = _forwarded_allow_ips(argv)
    if allow is not None and allow in WILDCARDS:
        raise RuntimeError(
            f"--forwarded-allow-ips={allow} 是「把限流关掉」的写法:uvicorn 会直接采信 "
            "X-Forwarded-For 最左边那个(客户端可随意改),「10 次/分/IP」等于不存在。"
            f"请去掉 --proxy-headers/--forwarded-allow-ips、改用 --no-proxy-headers + "
            f"{TRUST_ENV}=<反代地址>"
        )
    # uvicorn 0.52 的 --proxy-headers 默认开启(--forwarded-allow-ips 默认 127.0.0.1):
    # 只要对端命中它自己的白名单,它就会在应用之前改写 scope["client"],后端拿到的
    # 已经是「它算出来的值」。想自己判定就必须显式 --no-proxy-headers。
    global _OWNED
    _OWNED = not _has_flag("--no-proxy-headers", argv)
    if _OWNED and not chain.empty:
        log.warning(
            f"[client-ip] uvicorn 的代理头中间件仍开着(--proxy-headers 默认开启"
            f"{'，当前 ' + allow if allow else ''}):真实 IP 已由它按**它自己的白名单**改写,"
            f"后端无法再校验链路。单层反代能凑巧正确,多挂一层 CDN 会按 CDN 节点分桶。"
            f"请在启动命令加 --no-proxy-headers,让 {TRUST_ENV} 成为唯一判定(见 "
            "deploy/mathguide.service)"
        )
    if not demo and bound in LOOPBACK_HOSTS and chain.empty:
        raise RuntimeError(
            f"{TRUST_ENV} 为空,但服务绑在 {bound}:公网部署只能经反代进来,"
            "此时所有请求都会被算成反代地址 → 全站共享一个 IP 桶(登录 10 次/分),"
            "而且不会有任何报错。请在 .env.local 里填反代地址:"
            f"{TRUST_ENV}=127.0.0.1(反代在 Docker/另一台机器时填它的实际地址,"
            "如 172.17.0.1/32)"
        )

    if chain.empty:
        log.info(
            f"[client-ip] 未配置 {TRUST_ENV}:只按直连对端计,X-Forwarded-For 一律忽略"
            "(适合本机/直接暴露的部署;经反代时必须配置,否则全员一个桶)"
        )
    else:
        owner = "后端判定(uvicorn 已关闭代理头)" if not _OWNED else "**实际仍由 uvicorn 改写**"
        log.info(
            f"[client-ip] 信任反代 {chain.raw}:真实 IP = X-Forwarded-For 从右往左"
            f"第一个不在白名单里的地址(最多回溯 {MAX_HOPS} 跳)· {owner}"
        )
    return chain
