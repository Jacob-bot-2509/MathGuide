"""下载 URL 的纯校验:只放行可信 OA 域,不在这里做网络请求。"""
from __future__ import annotations

import asyncio
import ipaddress
import socket
from urllib.parse import urlparse

TRUSTED_PDF_HOSTS = (
    "arxiv.org",
    "europepmc.org",
    "ebi.ac.uk",
    "ncbi.nlm.nih.gov",
    "plos.org",
    "mdpi.com",
    "frontiersin.org",
    "biomedcentral.com",
)


def is_https_url(url: str) -> bool:
    try:
        parsed = urlparse(str(url or ""))
    except ValueError:
        return False
    host = (parsed.hostname or "").strip().lower()
    return bool(
        parsed.scheme == "https"
        and host
        and not parsed.username
        and not parsed.password
        and not any(c.isspace() or ord(c) < 32 for c in str(url))
    )


def is_forbidden_host(host: str) -> bool:
    name = str(host or "").strip().lower().strip("[]")
    if not name:
        return True
    if name == "localhost" or name.endswith(".localhost") or name.endswith(".local"):
        return True
    try:
        address = ipaddress.ip_address(name)
    except ValueError:
        return False
    return not address.is_global


def is_trusted_pdf_host(url: str) -> bool:
    try:
        parsed = urlparse(str(url or ""))
    except ValueError:
        return False
    host = (parsed.hostname or "").strip().lower()
    if not host:
        return False
    return any(host == suffix or host.endswith("." + suffix)
               for suffix in TRUSTED_PDF_HOSTS)


def is_safe_pdf_url(url: str) -> bool:
    if not is_https_url(url):
        return False
    try:
        host = urlparse(str(url)).hostname or ""
    except ValueError:
        return False
    return not is_forbidden_host(host) and is_trusted_pdf_host(url)


async def resolves_to_public_host(url: str) -> bool:
    """下载前解析 DNS,拒绝私有/回环/保留地址,降低 DNS rebinding 风险。"""
    if not is_https_url(url):
        return False
    try:
        host = urlparse(str(url)).hostname or ""
    except ValueError:
        return False
    if is_forbidden_host(host):
        return False
    try:
        infos = await asyncio.to_thread(
            socket.getaddrinfo, host, 443, type=socket.SOCK_STREAM)
    except OSError:
        return False
    if not infos:
        return False
    return not any(is_forbidden_host(info[4][0]) for info in infos)
