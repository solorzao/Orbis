from app.services.urls import outlet, web_url


def test_web_url_keeps_http_and_https_links_only():
    assert web_url("https://example.com/a") == "https://example.com/a"
    assert web_url("http://example.com/a?b=1") == "http://example.com/a?b=1"
    for bad in (
        "javascript:alert(1)",
        "ftp://x.test/a",
        "//example.com/a",
        "https://",
        "https://exa mple.com/",
        "https://example.com/\x00",
        "BBC Monitoring, 21 Oct",
        "https://example.com/" + "a" * 2100,
        None,
        42,
    ):
        assert web_url(bad) is None, bad


def test_outlet_is_the_host_without_www():
    assert outlet("https://www.Reuters.com/world/x") == "reuters.com"
    assert outlet("http://news.bbc.co.uk/a") == "news.bbc.co.uk"
    assert outlet("not a url") == ""


def test_board_still_uses_the_shared_sanitiser():
    from app.services import board

    assert board.web_url is web_url
