"""下载 URL 的纯校验:只放行可信 OA 域,不在这里做网络请求。"""
from __future__ import annotations

import ipaddress
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
