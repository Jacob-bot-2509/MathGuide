"""Literature providers must not supply executable browser links."""
import pytest
import research_lit as rl


@pytest.mark.parametrize("url", ["javascript:alert(1)", "data:text/html,hello", "//example.org/paper", "https://"])
def test_invalid_literature_links_are_not_returned(url):
    result = rl._crossref_item({"title": ["Paper"], "URL": url})
    assert result["url"] == ""
    assert rl._result(title="Paper", pdfUrl=url)["pdfUrl"] == ""


def test_valid_literature_links_are_preserved():
    url = "https://example.org/paper"
    assert rl._crossref_item({"title": ["Paper"], "URL": url})["url"] == url
