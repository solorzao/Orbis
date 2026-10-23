"""The article scraper fetches public pages only.

Its URLs come from GDELT, which is untrusted: neither a URL nor a redirect may
take it to the container's own network (loopback, the metadata endpoints,
private ranges). Fetches go through httpx.MockTransport, DNS through a table.
"""

from __future__ import annotations

import asyncio
import ipaddress
import logging
import sys
import time
import tracemalloc
import zlib
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from app.services import scraper
from app.services.scraper import extract_article_text, fetch_public, is_public_ip

REAL_RESOLVE = scraper._resolve  # before any test stands in for it

PUBLIC = "93.184.216.34"
MIRROR = "151.101.65.1"
DNS = {
    "news.example": [PUBLIC],
    "mirror.example": [MIRROR],
    "two.example": [PUBLIC, MIRROR],
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
    by ``web.handler`` (an article unless the test sets one). ``web.requests``,
    ``web.lookups`` and ``web.clients`` (each client's arguments) record what
    reached it."""
    web = SimpleNamespace(
        requests=[],
        lookups=[],
        clients=[],
        handler=lambda request: httpx.Response(200, text=ARTICLE),
    )

    async def resolve(host, port):
        web.lookups.append(host)
        return DNS[host]

    def handle(request):
        web.requests.append(request)
        response = web.handler(request)  # an async handler's coroutine is awaited
        return _unread(response) if isinstance(response, httpx.Response) else response

    real = httpx.AsyncClient

    def client(**kw):
        web.clients.append(kw)
        return real(transport=httpx.MockTransport(handle), **kw)

    monkeypatch.setattr(scraper.httpx, "AsyncClient", client)
    monkeypatch.setattr(scraper, "_resolve", resolve)
    monkeypatch.setattr(scraper, "get_cached", AsyncMock(return_value=None))
    monkeypatch.setattr(scraper, "set_cached", AsyncMock())
    return web


def _unread(response: httpx.Response) -> httpx.Response:
    """*response* with its body still to read, as the network gives one: httpx
    reads (and decodes) a body given as bytes at once, and fetch_public reads
    the raw stream. A compressed body is given as a stream (_streamed)."""
    if not response.is_stream_consumed:
        return response
    stream = httpx.ByteStream(response.content)
    return httpx.Response(response.status_code, headers=response.headers, stream=stream)


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


# --- Several addresses, one deadline, no proxy ----------------------------------------


class TestConnecting:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("error", [httpx.ConnectError, httpx.ConnectTimeout])
    async def test_a_dead_address_falls_back_to_the_next_checked_one(self, web, error):
        def handler(request):
            if request.url.host == PUBLIC:
                raise error("dead", request=request)
            return httpx.Response(200, text=ARTICLE)

        web.handler = handler

        page = await fetch_public("https://two.example/a", max_bytes=100, timeout=5)

        assert page is not None and page.status == 200
        assert [r.url.host for r in web.requests] == [PUBLIC, MIRROR]
        assert _hosts(web) == ["two.example", "two.example"]
        assert web.lookups == ["two.example"]  # the same checked answer, not a new one

    @pytest.mark.asyncio
    async def test_each_address_has_a_share_of_the_time_left_to_connect(self, web):
        def handler(request):
            if request.url.host == PUBLIC:
                raise httpx.ConnectTimeout("dead", request=request)
            return httpx.Response(200)

        web.handler = handler

        await fetch_public("https://two.example/a", max_bytes=100, timeout=5)

        first, second = (r.extensions["timeout"]["connect"] for r in web.requests)
        assert 2.0 < first <= 2.5  # half the deadline: one address of two
        assert 4.0 < second <= 5.0  # all that is left: the last address

    @pytest.mark.asyncio
    async def test_only_a_failed_connection_moves_on(self, web):
        def handler(request):
            raise httpx.ReadError("reset", request=request)

        web.handler = handler

        with pytest.raises(httpx.ReadError):
            await fetch_public("https://two.example/a", max_bytes=100, timeout=5)
        assert len(web.requests) == 1

    @pytest.mark.asyncio
    async def test_when_every_address_is_dead_the_scrape_fails(self, web):
        def handler(request):
            raise httpx.ConnectError("dead", request=request)

        web.handler = handler

        result = await extract_article_text("https://two.example/story")

        assert result["quality"] == "failed"
        assert len(web.requests) == 2

    @pytest.mark.asyncio
    async def test_the_whole_fetch_has_one_deadline(self, web):
        """Each hop answers inside any per-request timeout, but the hops add up."""

        async def slow(request):
            await asyncio.sleep(0.2)
            return _redirect(f"{request.url.path}/again")

        web.handler = slow
        started = time.monotonic()

        with pytest.raises(TimeoutError):
            await fetch_public("https://news.example/a", max_bytes=100, timeout=0.5)

        assert 0.45 < time.monotonic() - started < 1.0
        assert len(web.requests) == 3  # cut short in the third hop

    @pytest.mark.asyncio
    async def test_no_proxy_from_the_environment(self, web, monkeypatch):
        monkeypatch.setenv("HTTPS_PROXY", "http://10.0.0.9:3128")

        await fetch_public("https://news.example/a", max_bytes=100, timeout=5)

        [client] = web.clients
        assert client["trust_env"] is False


@pytest.mark.skipif(sys.platform != "linux", reason="glibc and musl read these as IPv4")
@pytest.mark.asyncio
@pytest.mark.parametrize("host", ["2130706433", "0x7f.1", "127.1"])
async def test_a_numeric_host_is_resolved_and_refused(web, monkeypatch, host):
    """Not IP literals to ipaddress, but the resolver reads them as 127.0.0.1."""
    looked_up = []

    async def real_resolve(name, port):
        looked_up.append(name)
        return await REAL_RESOLVE(name, port)

    monkeypatch.setattr(scraper, "_resolve", real_resolve)

    assert await fetch_public(f"http://{host}/", max_bytes=100, timeout=5) is None
    assert looked_up == [host]
    assert web.requests == []


# --- Compressed bodies are inflated no further than the cap ---------------------------


def _deflated(size: int, wbits: int) -> bytes:
    """*size* zero bytes compressed at zlib's best (*wbits* as zlib takes them):
    64 MiB is about 64 KB on the wire."""
    compressor = zlib.compressobj(9, zlib.DEFLATED, wbits)
    zeros = bytes(1 << 20)
    return b"".join(compressor.compress(zeros) for _ in range(size >> 20)) + compressor.flush()


def _streamed(body: bytes, sent: list[int], chunk: int = 64 * 1024):
    """*body* as a stream of *chunk*-byte reads, counting each in *sent*."""

    async def stream():
        for i in range(0, len(body), chunk):
            sent.append(i)
            yield body[i : i + chunk]

    return stream()


GZIP, ZLIB, RAW = 16 + zlib.MAX_WBITS, zlib.MAX_WBITS, -zlib.MAX_WBITS


class TestCompressedBodies:
    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("encoding", "wbits"),
        [("gzip", GZIP), ("x-gzip", GZIP), ("deflate", ZLIB), ("deflate", RAW)],
    )
    async def test_a_compression_bomb_inflates_no_further_than_the_cap(self, web, encoding, wbits):
        """64 MiB of zeros, about one 64 KB read on the wire. httpx's decoding
        inflates each read whole (to 64 MiB here): the peak memory shows it was
        inflated only to the cap."""
        bomb = _deflated(64 << 20, wbits)
        web.handler = lambda request: httpx.Response(
            200, content=_streamed(bomb, []), headers={"content-encoding": encoding}
        )

        tracemalloc.start()
        try:
            page = await fetch_public("https://news.example/a", max_bytes=15_000, timeout=5)
            _, peak = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()

        assert page.body == bytes(15_000)
        assert peak < 4 << 20, f"peak {peak >> 20} MiB"

    @pytest.mark.asyncio
    @pytest.mark.parametrize(("encoding", "wbits"), [("gzip", GZIP), ("deflate", RAW)])
    async def test_a_compressed_page_is_read_as_before(self, web, encoding, wbits):
        compressor = zlib.compressobj(6, zlib.DEFLATED, wbits)
        body = compressor.compress(ARTICLE.encode()) + compressor.flush()
        web.handler = lambda request: httpx.Response(
            200, content=_streamed(body, []), headers={"content-encoding": encoding}
        )

        result = await extract_article_text("https://news.example/story")

        assert result["title"] == "Storm hits the coast"
        assert "landfall" in result["text"]

    @pytest.mark.asyncio
    async def test_nothing_after_the_compressed_stream_is_read(self, web):
        compressor = zlib.compressobj(6, zlib.DEFLATED, GZIP)
        page_gz = compressor.compress(b"<title>Storm</title>") + compressor.flush()
        sent = []
        web.handler = lambda request: httpx.Response(
            200,
            content=_streamed(page_gz + bytes(64 * 1024) * 100, sent),
            headers={"content-encoding": "gzip"},
        )

        page = await fetch_public("https://news.example/a", max_bytes=15_000, timeout=5)

        assert page.body == b"<title>Storm</title>"
        assert len(sent) == 1

    @pytest.mark.asyncio
    @pytest.mark.parametrize("encoding", ["zstd", "br", "compress", "gzip, gzip"])
    async def test_an_encoding_not_asked_for_is_refused(self, web, caplog, encoding):
        zstd_frame = b"\x28\xb5\x2f\xfd" + bytes(100)
        web.handler = lambda request: httpx.Response(
            200, content=_streamed(zstd_frame, []), headers={"content-encoding": encoding}
        )

        with caplog.at_level(logging.WARNING, logger="orbis.scraper"):
            page = await fetch_public("https://news.example/a?k=zzsecret", max_bytes=100, timeout=5)

        assert page is None
        assert f"content-encoding {encoding!r}" in caplog.text
        assert "zzsecret" not in caplog.text

    @pytest.mark.asyncio
    @pytest.mark.parametrize("encoding", [None, "identity"])
    async def test_an_uncompressed_body_is_capped(self, web, encoding):
        headers = {"content-encoding": encoding} if encoding else {}
        web.handler = lambda request: httpx.Response(
            200, content=_streamed(b"x" * 640 * 1024, []), headers=headers
        )

        page = await fetch_public("https://news.example/a", max_bytes=1000, timeout=5)

        assert page.body == b"x" * 1000

    @pytest.mark.asyncio
    async def test_asks_for_gzip_and_deflate_only(self, web):
        await extract_article_text("https://news.example/story")

        [request] = web.requests
        assert request.headers["accept-encoding"] == "gzip, deflate"
        assert request.headers["user-agent"].startswith("Mozilla/5.0 (compatible; OrbisBot")


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
        ("fec0::1", False),  # site-local (deprecated), which is_global lets through
        ("::ffff:127.0.0.1", False),
        ("::ffff:169.254.169.254", False),
        (f"::ffff:{PUBLIC}", True),
        ("64:ff9b::7f00:1", False),  # NAT64 of 127.0.0.1
    ],
)
def test_is_public_ip(address, public):
    assert is_public_ip(ipaddress.ip_address(address)) is public
