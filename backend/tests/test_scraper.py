"""The article scraper fetches public pages only.

Its URLs come from GDELT, which is untrusted: neither a URL nor a redirect may
take it to the container's own network (loopback, the metadata endpoints,
private ranges). Fetches go through httpx.MockTransport, DNS through a table.
"""

from __future__ import annotations

import ipaddress
import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from app.services import scraper
from app.services.scraper import extract_article_text, fetch_public, is_public_ip

PUBLIC = "93.184.216.34"
MIRROR = "151.101.65.1"
DNS = {
    "news.example": [PUBLIC],
    "mirror.example": [MIRROR],
    "v6.example": ["2606:4700::6810:84e5"],
    "dual.example": ["2606:4700::6810:84e5", MIRROR],
    "inside.example": ["10.1.2.3"],
    "mapped.example": ["::ffff:10.1.2.3"],
    "split.example": [PUBLIC, "127.0.0.1"],
    "localhost": ["127.0.0.1", "::1"],
}
ARTICLE = (
    "<html><head><title>Storm hits the coast</title></head><body><article>"
    + "<p>The storm made landfall overnight, flooding the harbour and cutting power.</p>" * 5
    + "</article></body></html>"
)


@pytest.fixture
def web(monkeypatch):
    """The scraper's network: names resolved from DNS, and each request answered
    by ``web.handler`` (an article unless the test sets one). ``web.requests``
    and ``web.lookups`` record what reached it."""
    web = SimpleNamespace(
        requests=[], lookups=[], handler=lambda request: httpx.Response(200, text=ARTICLE)
    )

    async def resolve(host, port):
        web.lookups.append(host)
        return DNS[host]

    def handle(request):
        web.requests.append(request)
        return web.handler(request)

    real = httpx.AsyncClient
    monkeypatch.setattr(
        scraper.httpx,
        "AsyncClient",
        lambda **kw: real(transport=httpx.MockTransport(handle), **kw),
    )
    monkeypatch.setattr(scraper, "_resolve", resolve)
    monkeypatch.setattr(scraper, "get_cached", AsyncMock(return_value=None))
    monkeypatch.setattr(scraper, "set_cached", AsyncMock())
    return web


def _redirect(location: str, status: int = 302) -> httpx.Response:
    return httpx.Response(status, headers={"location": location})


def _redirects_to(location: str):
    """A handler: news.example redirects to *location*; anything else is a page."""

    def handler(request):
        if request.headers["host"] == "news.example":
            return _redirect(location)
        return httpx.Response(200, text=ARTICLE)

    return handler


def _hosts(web) -> list[str]:
    """The host each request was for (its Host header), in order."""
    return [r.headers["host"] for r in web.requests]


# --- Redirects inward are refused ------------------------------------------------------


class TestRedirectsInward:
    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "location",
        [
            "http://127.0.0.1/admin",
            "http://169.254.169.254/metadata/identity/oauth2/token",
            "http://[::1]/",
            "http://[::ffff:127.0.0.1]/",
            "http://[::ffff:169.254.169.254]/latest/meta-data/",
            "http://0.0.0.0:8080/",
            "http://100.64.0.1/",
            "http://[fd00::1]/",
            "http://[fe80::1]/",
            "http://168.63.129.16/machine",
        ],
    )
    async def test_a_redirect_to_an_internal_ip_is_a_failed_scrape(self, web, location):
        web.handler = _redirects_to(location)

        result = await extract_article_text("https://news.example/story")

        assert result["quality"] == "failed" and result["text"] == ""
        assert _hosts(web) == ["news.example"]  # the redirect was never followed

    @pytest.mark.asyncio
    @pytest.mark.parametrize("host", ["inside.example", "mapped.example", "localhost"])
    async def test_a_redirect_to_a_name_that_resolves_inward_is_refused(self, web, host):
        """inside.example is 10.1.2.3; mapped.example is ::ffff:10.1.2.3."""
        web.handler = _redirects_to(f"http://{host}/x")

        result = await extract_article_text("https://news.example/story")

        assert result["quality"] == "failed"
        assert _hosts(web) == ["news.example"]
        assert web.lookups == ["news.example", host]

    @pytest.mark.asyncio
    async def test_a_name_with_any_internal_address_is_refused(self, web):
        """split.example has a public address and 127.0.0.1: either could be used."""
        web.handler = _redirects_to("http://split.example/x")

        result = await extract_article_text("https://news.example/story")

        assert result["quality"] == "failed"
        assert _hosts(web) == ["news.example"]

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "location", ["file:///etc/passwd", "ftp://mirror.example/story", "gopher://mirror.example/"]
    )
    async def test_a_redirect_to_another_scheme_is_refused(self, web, location):
        web.handler = _redirects_to(location)

        result = await extract_article_text("https://news.example/story")

        assert result["quality"] == "failed"
        assert _hosts(web) == ["news.example"]

    @pytest.mark.asyncio
    async def test_a_redirect_loop_stops_at_three_redirects(self, web):
        web.handler = lambda request: _redirect(f"{request.url.path}/again")

        result = await extract_article_text("https://news.example/story")

        assert result["quality"] == "failed"
        assert len(web.requests) == 4  # the page and three redirects, no more

    @pytest.mark.asyncio
    async def test_a_refusal_is_logged_without_the_query_string(self, web, caplog):
        web.handler = _redirects_to("http://127.0.0.1/")

        with caplog.at_level(logging.WARNING, logger="orbis.scraper"):
            await extract_article_text("https://news.example/story?token=zzsecret#frag")

        [line] = [r.getMessage() for r in caplog.records if r.name == "orbis.scraper"]
        assert line == "Refused to fetch https://news.example/story: non-public address 127.0.0.1"
        assert "zzsecret" not in caplog.text

    @pytest.mark.asyncio
    async def test_a_name_resolving_inward_is_named_in_the_log(self, web, caplog):
        web.handler = _redirects_to("http://inside.example/x")

        with caplog.at_level(logging.WARNING, logger="orbis.scraper"):
            await extract_article_text("https://news.example/story")

        assert "non-public address 10.1.2.3 (inside.example)" in caplog.text

    @pytest.mark.asyncio
    async def test_a_refusal_is_not_cached(self, web):
        web.handler = _redirects_to("http://127.0.0.1/")

        await extract_article_text("https://news.example/story")

        scraper.set_cached.assert_not_awaited()


# --- URLs pointing inward are refused before any request -----------------------------


class TestDirectUrls:
    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "url",
        [
            "http://127.0.0.1:8080/admin",
            "http://169.254.169.254/metadata/instance",
            "http://[::1]/",
            "http://[::ffff:10.0.0.1]/",
            "http://10.0.0.1/",
            "http://192.168.1.1/",
            "http://172.16.0.1/",
            "http://localhost:42356/msi/token",
            "http://inside.example/",
            "file:///etc/passwd",
            "javascript:alert(1)",
            "not a url",
        ],
    )
    async def test_a_url_that_points_inward_is_never_requested(self, web, url):
        result = await extract_article_text(url)

        assert result["quality"] == "failed"
        assert web.requests == []


# --- Public pages still work ------------------------------------------------------------


class TestPublicPages:
    @pytest.mark.asyncio
    async def test_a_public_redirect_chain_is_followed(self, web):
        def handler(request):
            host, path = request.headers["host"], request.url.path
            if (request.url.scheme, host) == ("http", "news.example"):
                return _redirect("https://news.example/story", 301)
            if host == "news.example":
                return _redirect("//mirror.example/amp/story")
            if path == "/amp/story":
                return _redirect("/story", 307)
            return httpx.Response(200, text=ARTICLE)

        web.handler = handler

        result = await extract_article_text("http://news.example/story")

        assert result["quality"] != "failed"
        assert result["title"] == "Storm hits the coast"
        assert "landfall" in result["text"]
        assert [str(r.url) for r in web.requests] == [
            f"http://{PUBLIC}/story",
            f"https://{PUBLIC}/story",
            f"https://{MIRROR}/amp/story",
            f"https://{MIRROR}/story",
        ]
        assert _hosts(web) == ["news.example", "news.example", "mirror.example", "mirror.example"]

    @pytest.mark.asyncio
    async def test_three_redirects_are_allowed(self, web):
        def handler(request):
            hops = request.url.path.count("/again")
            return _redirect(f"{request.url.path}/again") if hops < 3 else httpx.Response(200)

        web.handler = handler

        page = await fetch_public("https://news.example/a", max_bytes=100, timeout=5)

        assert page is not None and page.status == 200
        assert len(web.requests) == 4

    @pytest.mark.asyncio
    async def test_each_hop_connects_to_the_address_it_checked(self, web, monkeypatch):
        """DNS rebinding: the client never looks the name up again, so a second
        answer pointing inward is never used. The name stays in the Host header
        and the TLS server name, which the certificate is checked against."""
        answers = iter([[PUBLIC], ["127.0.0.1"]])

        async def rebinding(host, port):
            web.lookups.append(host)
            return next(answers)

        monkeypatch.setattr(scraper, "_resolve", rebinding)

        page = await fetch_public("https://rebind.example/a", max_bytes=100, timeout=5)

        assert page is not None and page.status == 200
        [request] = web.requests
        assert request.url.host == PUBLIC
        assert request.headers["host"] == "rebind.example"
        assert request.extensions["sni_hostname"] == "rebind.example"
        assert web.lookups == ["rebind.example"]

    @pytest.mark.asyncio
    async def test_ipv4_is_preferred_and_ipv6_only_hosts_still_work(self, web):
        await fetch_public("https://dual.example/a", max_bytes=100, timeout=5)
        await fetch_public("https://v6.example:8443/a", max_bytes=100, timeout=5)

        assert [str(r.url) for r in web.requests] == [
            f"https://{MIRROR}/a",
            "https://[2606:4700::6810:84e5]:8443/a",
        ]
        assert _hosts(web) == ["dual.example", "v6.example:8443"]

    @pytest.mark.asyncio
    async def test_reads_at_most_max_bytes(self, web):
        web.handler = lambda request: httpx.Response(200, content=b"x" * 50_000)

        page = await fetch_public("https://news.example/a", max_bytes=1000, timeout=5)

        assert page.body == b"x" * 1000

    @pytest.mark.asyncio
    async def test_decodes_by_the_declared_charset(self, web):
        body = ARTICLE.replace("Storm", "Tormenta en Cádiz").encode("latin-1")
        web.handler = lambda request: httpx.Response(
            200, content=body, headers={"content-type": "text/html; charset=iso-8859-1"}
        )

        result = await extract_article_text("https://news.example/story")

        assert result["title"] == "Tormenta en Cádiz hits the coast"

    @pytest.mark.asyncio
    async def test_an_error_status_is_a_failed_scrape(self, web):
        web.handler = lambda request: httpx.Response(404, text=ARTICLE)

        result = await extract_article_text("https://news.example/story")

        assert result["quality"] == "failed"


# --- The address check ------------------------------------------------------------------


@pytest.mark.parametrize(
    ("address", "public"),
    [
        (PUBLIC, True),
        ("2606:4700::6810:84e5", True),
        ("127.0.0.1", False),
        ("10.1.2.3", False),
        ("172.31.255.255", False),
        ("192.168.0.1", False),
        ("169.254.169.254", False),
        ("100.64.0.1", False),  # CGNAT
        ("0.0.0.0", False),
        ("224.0.0.1", False),  # multicast, which is_global alone lets through
        ("255.255.255.255", False),
        ("168.63.129.16", False),  # Azure's platform address
        ("::1", False),
        ("::", False),
        ("fd12:3456::1", False),  # ULA
        ("fe80::1", False),
        ("ff02::1", False),
        ("::ffff:127.0.0.1", False),
        ("::ffff:169.254.169.254", False),
        (f"::ffff:{PUBLIC}", True),
        ("64:ff9b::7f00:1", False),  # NAT64 of 127.0.0.1
    ],
)
def test_is_public_ip(address, public):
    assert is_public_ip(ipaddress.ip_address(address)) is public
