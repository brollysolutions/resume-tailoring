from app.core.url_utils import normalize_url


def test_passthrough_https():
    assert normalize_url("https://example.com") == "https://example.com"
    assert normalize_url("http://example.com/x") == "http://example.com/x"


def test_bare_domain_gets_https():
    assert normalize_url("linkedin.com/in/jane") == "https://linkedin.com/in/jane"


def test_shorthand_returned_raw():
    assert normalize_url("in/john-doe") == "in/john-doe"


def test_none_and_empty():
    assert normalize_url(None) is None
    assert normalize_url("   ") is None


def test_mailto_stripped():
    # mailto: prefix removed; the bare address then gets https:// (has a dot).
    assert normalize_url("mailto:jane@example.com") == "https://jane@example.com"


def test_dangerous_schemes_rejected():
    assert normalize_url("javascript:alert(1)") is None
    assert normalize_url("JavaScript:alert(1)") is None
    assert normalize_url("data:text/html,<script>alert(1)</script>") is None
    assert normalize_url("vbscript:msgbox(1)") is None
    assert normalize_url("file:///etc/passwd") is None
    assert normalize_url("  javascript:alert(1)  ") is None
