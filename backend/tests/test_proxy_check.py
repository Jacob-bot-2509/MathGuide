"""tools/proxy_check.py:反代/登录态判定的离线验证。

这些判定错了会给出**反向结论**(比如把「HTTPS 少了 Secure」判成合格),而上线当天
没人会去逐条核对属性,所以属性解析与判据都要有测试。
"""
from __future__ import annotations

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
