"""tools/proxy_check.py:反代/登录态判定的离线验证。

这些判定错了会给出**反向结论**(比如把「HTTPS 少了 Secure」判成合格),而上线当天
没人会去逐条核对属性,所以属性解析与判据都要有测试。
"""
from __future__ import annotations

import json

from tools import proxy_check


def test_parse_cookie_splits_attributes():
    cookie = proxy_check.parse_cookie("mg_session=abc123; Path=/; HttpOnly; SameSite=lax; Secure")
    assert cookie["name"] == "mg_session"
    assert cookie["value"] == "abc123"
    assert cookie["attrs"]["path"] == "/"
    assert "httponly" in cookie["attrs"]
    assert cookie["attrs"]["samesite"] == "lax"
    assert proxy_check.parse_cookie("")["name"] == ""


def test_session_cookie_prefers_session_name():
    headers = ["other=1; HttpOnly", "mg_session=xyz; HttpOnly; SameSite=lax"]
    assert proxy_check.session_cookie_header(headers).startswith("mg_session=")
    # 一条都没有会话 cookie 时退回第一条,好让报错信息具体
    assert proxy_check.session_cookie_header(["other=1"]) == "other=1"
    assert proxy_check.session_cookie_header([]) == ""


def test_cookie_problems_accepts_healthy_cookie():
    healthy = "mg_session=abc; Path=/; HttpOnly; SameSite=lax; Secure; Max-Age=604800"
    assert proxy_check.cookie_problems(healthy, https=True) == []


def test_cookie_problems_flags_missing_httponly_and_samesite():
    problems = proxy_check.cookie_problems("mg_session=abc; Path=/", https=True)
    assert any("HttpOnly" in item for item in problems)
    assert any("SameSite" in item for item in problems)
    assert any("Secure" in item for item in problems)


def test_cookie_problems_flags_samesite_none():
    problems = proxy_check.cookie_problems("mg_session=abc; HttpOnly; SameSite=None", https=True)
    assert any("None" in item for item in problems)


def test_cookie_problems_flags_secure_on_plain_http():
    """HTTP 下带 Secure 的 cookie 浏览器不回传 —— 症状是「登录成功但刷新掉线」。"""
    problems = proxy_check.cookie_problems("mg_session=abc; HttpOnly; SameSite=lax; Secure",
                                          https=False)
    assert len(problems) == 1 and "立刻掉线" in problems[0]


def test_hsts_issues_requires_header_on_https():
    assert proxy_check.hsts_issues("", https=True)
    assert proxy_check.hsts_issues("", https=False) == []


def test_hsts_issues_checks_max_age():
    assert proxy_check.hsts_issues("max-age=31536000", https=True) == []
    assert proxy_check.hsts_issues("includeSubDomains", https=True)  # 没有 max-age = 无效
    short = proxy_check.hsts_issues("max-age=600", https=True)
    assert short and "低于建议值" in short[0]


def test_cert_days_parses_and_rejects_garbage():
    assert proxy_check.cert_days("Nov 15 12:00:00 2099 GMT") > 1000
    assert proxy_check.cert_days("Jan  1 00:00:00 2000 GMT") < 0
    assert proxy_check.cert_days("not-a-date") is None


def test_report_counts_warn_separately(capsys):
    report = proxy_check.Report()
    report.ok("a")
    report.warn("b")
    report.skip("c")
    report.fail("d", "hint")
    assert (report.passed, report.warned, report.skipped, report.failed) == (1, 1, 1, 1)
    out = capsys.readouterr().out
    assert "[WARN]" in out and "hint" in out


def test_check_webhook_skips_when_unset(capsys):
    report = proxy_check.Report()
    proxy_check.check_webhook(report, "")
    assert report.skipped == 1
    assert "[SKIP]" in capsys.readouterr().out


def test_run_short_circuits_when_unreachable(monkeypatch, capsys):
    """连不上时只报一条,不能刷一屏"安全头缺失" —— 那种输出会把真实原因埋掉。"""
    import argparse

    probe = proxy_check.Probe(base="http://127.0.0.1:8099")
    monkeypatch.setattr(probe, "call", lambda *args, **kwargs: proxy_check.Resp(0, {}, b"boom"))
    args = argparse.Namespace(phone="", password="", cookie_domain="", webhook="", spa_path="/")
    assert proxy_check.run(probe, args) == 1
    out = capsys.readouterr().out
    assert "连不上" in out
    assert "Permissions-Policy" not in out  # 后面的检查确实没跑


# ---------- 真实 IP 链路(§一.4):判反了就是「限流能绕过」被当成合格 ----------

def _probe_with(monkeypatch, client_for):
    """按请求头返回 /api/health 的假探针;client_for(xff) 决定返回的 client 字段。"""
    probe = proxy_check.Probe(base="https://mg.example.com")

    def fake(method, path, body=None, headers=None, timeout=None):
        client = client_for((headers or {}).get("X-Forwarded-For", ""))
        payload = {"ok": True}
        if client is not None:
            payload["client"] = client
        return proxy_check.Resp(200, {}, json.dumps(payload).encode())

    monkeypatch.setattr(probe, "call", fake)
    return probe


def test_client_ip_ok_when_forwarded_and_spoofing_ignored(monkeypatch, capsys):
    probe = _probe_with(monkeypatch, lambda xff: {"ref": "aaaaaaaaaaaa", "via": "forwarded",
                                                   "proxies": 1})
    report = proxy_check.Report()
    proxy_check.check_client_ip_chain(probe, report, local_direct=False)
    assert (report.passed, report.failed) == (1, 0)
    assert "真实 IP 链路有效" in capsys.readouterr().out


def test_client_ip_fails_when_spoofed_header_takes_effect(monkeypatch, capsys):
    """两次不同伪造 XFF 得到不同 ref = 白名单过宽或 `*`,限流等于不存在。"""
    probe = _probe_with(monkeypatch, lambda xff: {"ref": xff[-1] * 12, "via": "forwarded",
                                                   "proxies": 1})
    report = proxy_check.Report()
    proxy_check.check_client_ip_chain(probe, report, local_direct=False)
    assert report.failed == 1
    assert "可被绕过" in capsys.readouterr().out


def test_client_ip_fails_on_collapse_behind_proxy(monkeypatch, capsys):
    """对端不在白名单 → 所有人一个桶:这是公网部署最常见、也最静默的失效。"""
    probe = _probe_with(monkeypatch, lambda xff: {"ref": "bbbbbbbbbbbb",
                                                  "via": "peer-untrusted", "proxies": 0})
    report = proxy_check.Report()
    proxy_check.check_client_ip_chain(probe, report, local_direct=False)
    assert report.failed == 1
    assert "塌成一个 IP 桶" in capsys.readouterr().out


def test_client_ip_fails_when_proxy_sends_no_header(monkeypatch):
    probe = _probe_with(monkeypatch, lambda xff: {"ref": "cccccccccccc", "via": "peer",
                                                  "proxies": 1})
    report = proxy_check.Report()
    proxy_check.check_client_ip_chain(probe, report, local_direct=False)
    assert report.failed == 1


def test_client_ip_does_not_judge_collapse_on_local_direct(monkeypatch, capsys):
    """`--base-url http://127.0.0.1:8000` 只验应用层:via=peer 是正常状态,不能判 FAIL。"""
    probe = _probe_with(monkeypatch, lambda xff: {"ref": "dddddddddddd", "via": "peer",
                                                  "proxies": 0})
    report = proxy_check.Report()
    proxy_check.check_client_ip_chain(probe, report, local_direct=True)
    assert (report.passed, report.failed) == (1, 0)
    assert "不判断是否塌陷" in capsys.readouterr().out


def test_client_ip_warns_when_diag_is_off(monkeypatch, capsys):
    probe = _probe_with(monkeypatch, lambda xff: None)
    report = proxy_check.Report()
    proxy_check.check_client_ip_chain(probe, report, local_direct=False)
    assert report.warned == 1
    assert "MG_DIAG_CLIENT_IP" in capsys.readouterr().out


def test_client_ip_fails_when_uvicorn_trusts_spoofed_header(monkeypatch, capsys):
    """uvicorn 默认开着 --proxy-headers:对端命中它自己的白名单时会采信客户端 XFF。"""
    probe = _probe_with(monkeypatch, lambda xff: {"ref": xff[-1] * 12, "via": "uvicorn",
                                                  "proxies": 1})
    report = proxy_check.Report()
    proxy_check.check_client_ip_chain(probe, report, local_direct=False)
    assert report.failed == 1
    assert "--no-proxy-headers" in capsys.readouterr().out


def test_client_ip_only_warns_on_uvicorn_owned_local_run(monkeypatch, capsys):
    """本机自测时 uvicorn 采信 XFF 是"自己伪造自己",不该判 FAIL 挡住验收。"""
    probe = _probe_with(monkeypatch, lambda xff: {"ref": xff[-1] * 12, "via": "uvicorn",
                                                  "proxies": 1})
    report = proxy_check.Report()
    proxy_check.check_client_ip_chain(probe, report, local_direct=True)
    assert (report.warned, report.failed) == (1, 0)
    assert "CDN 节点分桶" in capsys.readouterr().out
