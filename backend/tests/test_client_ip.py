"""client_ip.py:反代信任链的唯一定点(伪造 XFF / 塌陷 / 通配白名单)。

这组用例对应 docs/DEPLOY_PLAYBOOK.md §一.4 的四条静默失效路径:
伪造的 X-Forwarded-For 必须无效、白名单对不上必须能被发现、`*` 必须拒绝启动。
"""
from __future__ import annotations

import ipaddress

import pytest
from starlette.requests import Request

import client_ip
from rate_limit import SlidingWindowLimiter


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    monkeypatch.delenv(client_ip.TRUST_ENV, raising=False)
    monkeypatch.delenv(client_ip.DIAG_ENV, raising=False)
    client_ip.reset()
    yield
    client_ip.reset()


def _chain(*cidrs: str) -> client_ip.Chain:
    return client_ip.Chain(
        raw=",".join(cidrs),
        networks=tuple(ipaddress.ip_network(cidr, strict=False) for cidr in cidrs),
    )


def _req(peer: str, xff: str = "") -> Request:
    headers = [(b"x-forwarded-for", xff.encode("utf-8"))] if xff else []
    return Request({
        "type": "http", "method": "GET", "path": "/", "headers": headers,
        "query_string": b"", "client": (peer, 12345),
    })


# ---------- 伪造 XFF:对端不在白名单时必须无效 ----------

def test_direct_peer_ignores_spoofed_header():
    """最危险的一条:对端不可信时若还去读 XFF,限流等于交给客户端。"""
    key, via = client_ip.resolve("203.0.113.5", "1.2.3.4", _chain())
    assert (key, via) == ("203.0.113.5", "peer-untrusted")


def test_trusted_proxy_takes_appended_address():
    chain = _chain("127.0.0.1")
    assert client_ip.resolve("127.0.0.1", "10.0.0.7", chain) == ("10.0.0.7", "forwarded")


def test_spoofed_leftmost_is_ignored():
    """客户端自己塞的 6.6.6.6 在最左边;nginx 追加的真实地址在右边,必须取右边。"""
    chain = _chain("127.0.0.1")
    assert client_ip.resolve("127.0.0.1", "6.6.6.6, 10.0.0.7", chain)[0] == "10.0.0.7"


def test_multi_hop_skips_every_trusted_proxy():
    """CDN 回源 + nginx:两层都是自己的地址,真实 IP 还在更左边。"""
    chain = _chain("127.0.0.1", "172.17.0.0/16")
    assert client_ip.resolve("127.0.0.1", "10.0.0.7, 172.17.0.9", chain) == ("10.0.0.7", "forwarded")


def test_all_trusted_hops_fall_back_to_peer():
    """整条链都是自己的地址(反代忘了追加):退回对端,不认一个可疑值。"""
    chain = _chain("127.0.0.1")
    assert client_ip.resolve("127.0.0.1", "127.0.0.1", chain) == ("127.0.0.1", "peer")


def test_missing_header_falls_back_to_peer():
    assert client_ip.resolve("127.0.0.1", "", _chain("127.0.0.1")) == ("127.0.0.1", "peer")


def test_garbage_hops_are_skipped():
    """畸形 token 不能让登录接口 500,也不能被当成"某个桶"。"""
    chain = _chain("127.0.0.1")
    assert client_ip.resolve("127.0.0.1", "unknown, , 10.0.0.7", chain)[0] == "10.0.0.7"


def test_chain_length_is_bounded():
    """超长头只回溯最后 MAX_HOPS 跳(上界内仍是「右起第一个非受信」)。"""
    chain = _chain("127.0.0.1")
    hops = ",".join(f"10.1.{i}.1" for i in range(40)) + ",10.0.0.7"
    assert client_ip.resolve("127.0.0.1", hops, chain)[0] == "10.0.0.7"


def test_port_and_brackets_are_stripped():
    assert client_ip.parse_ip("1.2.3.4:5000") == ipaddress.ip_address("1.2.3.4")
    assert client_ip.parse_ip("[::1]:5000") == ipaddress.ip_address("::1")
    assert client_ip.parse_ip("[::1]") == ipaddress.ip_address("::1")


def test_ipv4_mapped_ipv6_shares_the_bucket():
    """::ffff:1.2.3.4 与 1.2.3.4 是同一个客户端,不能各拿一个桶。"""
    assert str(client_ip.parse_ip("::ffff:1.2.3.4")) == "1.2.3.4"


def test_non_ip_peer_is_kept_verbatim():
    """TestClient 之类的对端不是 IP:照样给出稳定的 key,不能变成 unknown 全都挤一起。"""
    assert client_ip.resolve("testclient", "", _chain())[0] == "testclient"


def test_uvicorn_owned_is_reported_not_collapsed():
    """uvicorn 已先改写时(默认行为),不能把「它算出来的值」当成塌陷来报警。"""
    chain = _chain("127.0.0.1")
    assert client_ip.resolve("203.0.113.9", "10.0.0.1, 203.0.113.9", chain,
                             owned=True) == ("203.0.113.9", "uvicorn")
    # 没有 XFF 时仍然按普通对端算(直连部署不该出现 uvicorn 这个来源)
    assert client_ip.resolve("203.0.113.9", "", chain, owned=True) == ("203.0.113.9", "peer")


def test_uvicorn_owned_still_detects_real_collapse():
    """对端是真反代(不在 uvicorn 白名单)时它不会改写:必须仍然报塌陷,不能吞掉。"""
    chain = _chain("127.0.0.1")
    assert client_ip.resolve("172.17.0.1", "10.0.0.7", chain,
                             owned=True) == ("172.17.0.1", "peer-untrusted")


# ---------- 白名单本身:通配与拼错都必须拒绝 ----------

@pytest.mark.parametrize("token", ["*", "any", "0.0.0.0/0", "::/0"])
def test_wildcard_whitelist_is_rejected(token):
    with pytest.raises(ValueError, match="不能写"):
        client_ip.parse_trusted(token)


def test_invalid_cidr_is_rejected():
    with pytest.raises(ValueError, match="不是合法"):
        client_ip.parse_trusted("127.0.0.1,not-an-ip")


def test_whitelist_accepts_bare_ip_and_cidr():
    chain = client_ip.parse_trusted("127.0.0.1, 172.17.0.0/16")
    assert len(chain.networks) == 2
    assert chain.trusts(ipaddress.ip_address("172.17.0.9")) is True
    assert chain.trusts(ipaddress.ip_address("10.0.0.9")) is False


# ---------- 启动校验:把「静默变形」挡在部署窗口内 ----------

def test_configure_rejects_wildcard_uvicorn_flag():
    """`--forwarded-allow-ips=*` 是绕过写法的源头,必须在启动时挡住。"""
    with pytest.raises(RuntimeError, match="10 次/分"):
        client_ip.configure(demo=False, bound="0.0.0.0",
                            argv=["--proxy-headers", "--forwarded-allow-ips=*"])


def test_configure_requires_whitelist_behind_loopback_bind():
    """公网部署绑 127.0.0.1 = 只能经反代进来;白名单空着必然全员一个桶。"""
    with pytest.raises(RuntimeError, match=client_ip.TRUST_ENV):
        client_ip.configure(demo=False, bound="127.0.0.1", argv=[])


def test_configure_rejects_wildcard_env(monkeypatch):
    monkeypatch.setenv(client_ip.TRUST_ENV, "*")
    with pytest.raises(RuntimeError, match="不能写"):
        client_ip.configure(demo=False, bound="0.0.0.0", argv=[])


def test_configure_allows_direct_public_bind_without_whitelist():
    """直接暴露(0.0.0.0)时对端就是真客户端,XFF 忽略即可,不必强制白名单。"""
    chain = client_ip.configure(demo=False, bound="0.0.0.0", argv=[])
    assert chain.empty is True


def test_configure_demo_mode_does_not_block_local_testing():
    """演示模式只提示,方便本机反复起停(与 assert_single_worker 口径一致)。"""
    assert client_ip.configure(demo=True, bound="127.0.0.1", argv=[]).empty is True


def test_configure_tolerates_old_uvicorn_flags(monkeypatch):
    """老 unit 文件(--proxy-headers + 具体白名单)仍能启动:只打 WARN 要求迁移。"""
    monkeypatch.setenv(client_ip.TRUST_ENV, "127.0.0.1")
    chain = client_ip.configure(demo=False, bound="127.0.0.1",
                               argv=["--proxy-headers", "--forwarded-allow-ips=127.0.0.1"])
    assert chain.empty is False
    # 代理头中间件还开着 = 后端看不到真实对端,必须如实标记(否则会误报塌陷)
    assert client_ip.uvicorn_owned() is True


def test_configure_takes_ownership_with_no_proxy_headers(monkeypatch):
    monkeypatch.setenv(client_ip.TRUST_ENV, "127.0.0.1")
    client_ip.configure(demo=False, bound="127.0.0.1", argv=["--no-proxy-headers"])
    assert client_ip.uvicorn_owned() is False


def test_configure_prefers_env_whitelist_after_reset(monkeypatch):
    monkeypatch.setenv(client_ip.TRUST_ENV, "127.0.0.1,172.17.0.1/32")
    assert client_ip.configure(demo=False, bound="127.0.0.1", argv=[]).networks
    assert client_ip.settings().trusts(ipaddress.ip_address("172.17.0.1"))


# ---------- 塌陷告警:不许静默 ----------

def test_untrusted_peer_with_header_warns_once():
    messages: list[str] = []
    original = client_ip._emit
    client_ip._emit = messages.append
    try:
        client_ip.client_key(_req("203.0.113.5", "10.0.0.1"))
        client_ip.client_key(_req("203.0.113.5", "10.0.0.2"))
    finally:
        client_ip._emit = original
    assert len(messages) == 1
    assert client_ip.TRUST_ENV in messages[0]


def test_warning_repeats_after_window():
    messages: list[str] = []
    original = client_ip._emit
    client_ip._emit = messages.append
    try:
        client_ip._warn("k", "m", now=0.0)
        client_ip._warn("k", "m", now=1.0)
        client_ip._warn("k", "m", now=client_ip.WARN_WINDOW + 1)
    finally:
        client_ip._emit = original
    assert len(messages) == 2


# ---------- 诊断字段:够用但不泄露明文 ----------

def test_health_hint_is_off_by_default():
    assert client_ip.health_hint(_req("127.0.0.1", "10.0.0.7")) == {}


def test_health_hint_reports_hash_and_source(monkeypatch):
    monkeypatch.setenv(client_ip.DIAG_ENV, "1")
    monkeypatch.setenv(client_ip.TRUST_ENV, "127.0.0.1")
    hint = client_ip.health_hint(_req("127.0.0.1", "10.0.0.7"))["client"]
    assert len(hint["ref"]) == 12
    assert hint["via"] == "forwarded"
    assert "10.0.0.7" not in str(hint)  # 公开接口不给明文 IP


# ---------- 接到 auth 上:限流分桶必须跟真实客户端走 ----------

def test_auth_client_key_delegates_to_shared_resolver(monkeypatch):
    import auth

    monkeypatch.setenv(client_ip.TRUST_ENV, "127.0.0.1")
    assert auth._client_key(_req("127.0.0.1", "10.0.0.7")) == "10.0.0.7"


def test_two_clients_behind_proxy_get_separate_buckets(monkeypatch):
    """塌陷的直接防线:同一反代后面的两个客户端必须是两个桶(否则全站共享 10 次/分)。"""
    monkeypatch.setenv(client_ip.TRUST_ENV, "127.0.0.1")
    limiter = SlidingWindowLimiter(1, 60)
    first = client_ip.client_key(_req("127.0.0.1", "10.0.0.1"))
    second = client_ip.client_key(_req("127.0.0.1", "10.0.0.2"))
    assert first != second
    assert limiter.allow(first, now=0) is True
    assert limiter.allow(second, now=0) is True
    # 同一个客户端再来一次:同一个桶,超限
    assert client_ip.client_key(_req("127.0.0.1", "10.0.0.1")) == first
    assert limiter.allow(first, now=1) is False


def test_spoofed_header_cannot_escape_the_bucket():
    """不带白名单时,伪造 XFF 无法把自己从桶里摘出去(攻击者最想做的事)。"""
    first = client_ip.client_key(_req("203.0.113.5", "1.1.1.1"))
    second = client_ip.client_key(_req("203.0.113.5", "2.2.2.2"))
    assert first == second == "203.0.113.5"
