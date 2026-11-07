"""Literature providers must not supply executable browser links."""
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
