"""Literature providers must not supply executable browser links."""
import asyncio
import socket

import httpx
import pytest
import research_lit as rl
import research_urls as ru


@pytest.mark.parametrize("url", ["javascript:alert(1)", "data:text/html,hello", "//example.org/paper", "https://"])
def test_invalid_literature_links_are_not_returned(url):
    result = rl._crossref_item({"title": ["Paper"], "URL": url})
    assert result["url"] == ""
    assert rl._result(title="Paper", pdfUrl=url)["pdfUrl"] == ""


def test_valid_literature_links_are_preserved():
    url = "https://example.org/paper"
    assert rl._crossref_item({"title": ["Paper"], "URL": url})["url"] == url


def test_private_and_local_urls_are_rejected():
    for url in (
        "http://example.org/a.pdf",
        "https://localhost/a.pdf",
        "https://127.0.0.1/a.pdf",
        "https://10.0.0.1/a.pdf",
        "https://192.168.1.2/a.pdf",
        "https://169.254.1.1/a.pdf",
        "https://user:pass@example.org/a.pdf",
    ):
        assert not ru.is_safe_pdf_url(url)


def test_trusted_pdf_host_allows_subdomains_only_for_known_hosts():
    assert ru.is_trusted_pdf_host("https://arxiv.org/pdf/2410.12345")
    assert ru.is_trusted_pdf_host("https://export.arxiv.org/pdf/2410.12345")
    assert ru.is_trusted_pdf_host("https://pmc.ncbi.nlm.nih.gov/articles/PMC1/pdf")
    assert not ru.is_trusted_pdf_host("https://link.springer.com/content/pdf/1.pdf")
    assert not ru.is_trusted_pdf_host("https://evil-arxiv.org/a.pdf")


def test_safe_page_url_only_trusted_https_hosts():
    assert ru.is_safe_page_url("https://arxiv.org/abs/2410.12345")
    assert ru.is_safe_page_url("https://europepmc.org/article/MED/1")
    assert not ru.is_safe_page_url("http://arxiv.org/abs/2410.12345")
    assert not ru.is_safe_page_url("https://evil.example/a")
    assert not ru.is_safe_page_url("https://127.0.0.1/a")
    assert not ru.is_safe_page_url("javascript:alert(1)")


def test_dns_resolving_to_private_ip_is_rejected(monkeypatch):
    monkeypatch.setattr(
        socket, "getaddrinfo",
        lambda *args, **kwargs: [(socket.AF_INET, socket.SOCK_STREAM, 6, "",
                                  ("127.0.0.1", 443))])
    assert not asyncio.run(
        ru.resolves_to_public_host("https://example.org/a.pdf"))


def test_dns_fake_ipv6_does_not_reject_public_ipv4(monkeypatch):
    """本机代理常把 AAAA 映射到保留段;下载走 IPv4,不能因此拒绝整篇论文。"""
    def fake(*args, **kwargs):
        return [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("28.0.0.208", 443)),
            (socket.AF_INET6, socket.SOCK_STREAM, 6, "",
             ("2001:2::a2", 443, 0, 0)),
        ]

    monkeypatch.setattr(socket, "getaddrinfo", fake)
    assert asyncio.run(
        ru.resolves_to_public_host("https://arxiv.org/pdf/1"))


def test_dns_private_ipv4_is_still_rejected_with_fake_ipv6(monkeypatch):
    def fake(*args, **kwargs):
        return [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.2", 443)),
            (socket.AF_INET6, socket.SOCK_STREAM, 6, "",
             ("2001:2::a2", 443, 0, 0)),
        ]

    monkeypatch.setattr(socket, "getaddrinfo", fake)
    assert not asyncio.run(
        ru.resolves_to_public_host("https://arxiv.org/pdf/1"))


def test_download_rejects_html_body(monkeypatch):
    async def public(url):
        return True

    monkeypatch.setattr(rl.research_urls, "resolves_to_public_host", public)
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, content=b"<html>login</html>"))
    async def run():
        async with httpx.AsyncClient(transport=transport) as client:
            await rl._download_pdf(client, "https://arxiv.org/pdf/1")
    with pytest.raises(ValueError, match="不是 PDF"):
        asyncio.run(run())


def test_download_page_accepts_html(monkeypatch):
    async def public(url):
        return True

    monkeypatch.setattr(rl.research_urls, "resolves_to_public_host", public)
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200, headers={"content-type": "text/html; charset=utf-8"},
            content=b"<html><body><h1>Paper</h1><p>Full text</p></body></html>"))
    async def run():
        async with httpx.AsyncClient(transport=transport) as client:
            return await rl._download_page(client, "https://arxiv.org/abs/1")
    data = asyncio.run(run())
    assert b"Full text" in data


def test_download_page_rejects_binary(monkeypatch):
    async def public(url):
        return True

    monkeypatch.setattr(rl.research_urls, "resolves_to_public_host", public)
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200, headers={"content-type": "application/pdf"},
            content=b"%PDF-1.4"))
    async def run():
        async with httpx.AsyncClient(transport=transport) as client:
            await rl._download_page(client, "https://arxiv.org/abs/1")
    with pytest.raises(ValueError, match="不是网页"):
        asyncio.run(run())
