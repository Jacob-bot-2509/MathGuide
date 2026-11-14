"""rag/route + research_urls:链路裁决与下载 URL 白名单。

两处都是"错了不会报错、只会做错事"的地方:
路由判错 = 该搜索的问题被当成闲聊;URL 白名单判松 = SSRF(内网地址被当论文下载)。
"""
from __future__ import annotations

import asyncio
import socket

import pytest

import research_urls as ru
from rag import route

# ---------- rag/route ----------

def test_research_intent_markers_zh_and_en():
    assert route.is_research_intent("泰勒展开的最新研究进展") is True
    assert route.is_research_intent("give me a survey on SOTA") is True
    assert route.is_research_intent("求导怎么算") is False


def test_decide_order_research_first_then_knowledge_then_math():
    # 研究意图优先于知识命中
    assert route.decide("最新研究进展", has_chunks=True, is_math=True) == route.RESEARCH
    # 命中知识库 → 零成本快答
    assert route.decide("极限的定义", has_chunks=True, is_math=True) == route.KNOWLEDGE
    # 没命中但确属数学题 → 方法论框架
    assert route.decide("极限的定义", has_chunks=False, is_math=True) == route.FRAMEWORK
    # 其余 → 会话
    assert route.decide("你好", has_chunks=False, is_math=False) == route.CHAT


# ---------- research_urls:https 与 host 校验 ----------

@pytest.mark.parametrize("url,expected", [
    ("https://arxiv.org/pdf/2401.00001.pdf", True),
    ("http://arxiv.org/pdf/x.pdf", False),          # 非 https
    ("https://user:pw@arxiv.org/x.pdf", False),      # 带凭据
    ("https:///nohost.pdf", False),                  # 没有 host
    ("https://arxiv.org/x.pdf\n", False),            # 含控制字符
    ("http://[::1", False),                          # urlparse 抛错
])
def test_is_https_url(url, expected):
    assert ru.is_https_url(url) is expected


@pytest.mark.parametrize("host,expected", [
    ("", True),
    ("localhost", True),
    ("api.localhost", True),
    ("printer.local", True),
    ("127.0.0.1", True),          # 非 global
    ("10.0.0.5", True),
    ("[::1]", True),              # 方括号 IPv6 也要判为禁止
    ("8.8.8.8", False),
    ("arxiv.org", False),         # 域名不是 IP,交给白名单判
])
def test_is_forbidden_host(host, expected):
    assert ru.is_forbidden_host(host) is expected


@pytest.mark.parametrize("url,expected", [
    ("https://arxiv.org/x.pdf", True),
    ("https://sub.arxiv.org/x.pdf", True),      # 子域放行
    ("https://notarxiv.org/x.pdf", False),      # 后缀伪装要拦住
    ("https:///x.pdf", False),
])
def test_is_trusted_pdf_host(url, expected):
    assert ru.is_trusted_pdf_host(url) is expected


def test_malformed_urls_are_rejected_everywhere():
    """urlparse 抛 ValueError 时,四个入口都必须安全返回 False(而不是崩)。"""
    bad = "http://[::1"
    assert ru.is_trusted_pdf_host(bad) is False
    assert ru.is_safe_pdf_url(bad) is False
    assert asyncio.run(ru.resolves_to_public_host(bad)) is False


def test_is_safe_pdf_url_requires_https_public_and_trusted():
    assert ru.is_safe_pdf_url("https://arxiv.org/x.pdf") is True
    assert ru.is_safe_pdf_url("http://arxiv.org/x.pdf") is False
    assert ru.is_safe_pdf_url("https://localhost/x.pdf") is False
    assert ru.is_safe_pdf_url("https://evil.example/x.pdf") is False
    # 落地页走同一套规则
    assert ru.is_safe_page_url("https://arxiv.org/abs/1") is True


# ---------- research_urls:DNS 解析防护 ----------

def _patch_dns(monkeypatch, result):
    def fake_getaddrinfo(*_args, **_kwargs):
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)


def test_resolves_to_public_host_rejects_non_https_and_forbidden(monkeypatch):
    _patch_dns(monkeypatch, [])
    assert asyncio.run(ru.resolves_to_public_host("http://arxiv.org/x.pdf")) is False
    assert asyncio.run(ru.resolves_to_public_host("https://localhost/x.pdf")) is False


def test_resolves_to_public_host_handles_dns_failure(monkeypatch):
    _patch_dns(monkeypatch, OSError("dns down"))
    assert asyncio.run(ru.resolves_to_public_host("https://arxiv.org/x.pdf")) is False


def test_resolves_to_public_host_requires_ipv4(monkeypatch):
    # 只有 IPv6 记录 → 不做下载(客户端绑 IPv4,避免被假 AAAA 误杀)
    _patch_dns(monkeypatch, [(socket.AF_INET6, 0, 0, "", ("::1", 443, 0, 0))])
    assert asyncio.run(ru.resolves_to_public_host("https://arxiv.org/x.pdf")) is False


def test_resolves_to_public_host_rejects_private_ipv4(monkeypatch):
    _patch_dns(monkeypatch, [(socket.AF_INET, 0, 0, "", ("10.1.2.3", 443))])
    assert asyncio.run(ru.resolves_to_public_host("https://arxiv.org/x.pdf")) is False


def test_resolves_to_public_host_accepts_public_ipv4(monkeypatch):
    _patch_dns(monkeypatch, [(socket.AF_INET, 0, 0, "", ("151.101.1.91", 443))])
    assert asyncio.run(ru.resolves_to_public_host("https://arxiv.org/x.pdf")) is True
