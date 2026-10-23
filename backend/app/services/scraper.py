"""Article text extraction with multi-strategy cascade and Redis caching.

Pages are fetched with fetch_public (ingestion's title scrape uses it too). The
URLs are untrusted (GDELT's, passed on by the co-pilot's planner), so only
http(s), only public addresses, and each redirect checked the same way.

Extraction order:
1. trafilatura (best quality, handles boilerplate removal)
2. BeautifulSoup <article>/<p> tag extraction
3. <meta name="description"> fallback

Results are cached in Redis with a 24-hour TTL keyed by URL hash.
"""

from __future__ import annotations

import asyncio
import codecs
import hashlib
import ipaddress
import logging
import re
import socket
from typing import Any, NamedTuple
from urllib.parse import urlsplit

import httpx

from app.services.cache import get_cached, set_cached
from app.services.urls import web_url

logger = logging.getLogger("orbis.scraper")

_CACHE_TTL = 86400  # 24 hours
_FETCH_TIMEOUT = 10.0  # seconds for a whole fetch, redirects included
_MAX_PAGE_BYTES = 3 * 1024 * 1024  # an article's HTML is cut off past this
_MAX_TEXT_WORDS = 500
_USER_AGENT = "Mozilla/5.0 (compatible; OrbisBot/1.0; +https://orbisapp.co)"


# ---------------------------------------------------------------------------
# Fetching untrusted URLs
# ---------------------------------------------------------------------------

_MAX_REDIRECTS = 3
# Azure's platform address (its DNS, health probes and WireServer): public by
# its number, internal by its use.
_AZURE_PLATFORM_IP = ipaddress.ip_address("168.63.129.16")
_LOG_UNSAFE = re.compile(r"[\x00-\x1f\x7f]")

IPAddress = ipaddress.IPv4Address | ipaddress.IPv6Address


class Refused(Exception):
    """A URL fetch_public won't fetch. The message says why and never holds the URL."""


class Page(NamedTuple):
    """A page fetch_public got: its status, at most max_bytes of its body, and the
    charset its Content-Type names (None if it names none)."""

    status: int
    body: bytes
    charset: str | None = None

    def text(self) -> str:
        """The body decoded as httpx's Response.text would: by its charset, else UTF-8."""
        encoding = self.charset or "utf-8"
        try:
            codecs.lookup(encoding)
        except LookupError:
            encoding = "utf-8"
        return self.body.decode(encoding, errors="replace")


def _unmapped(ip: IPAddress) -> IPAddress:
    """*ip*, or the IPv4 address an IPv4-mapped IPv6 address (::ffff:a.b.c.d) holds."""
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        return ip.ipv4_mapped
    return ip


def is_public_ip(ip: IPAddress) -> bool:
    """True for an address on the public internet. False for loopback, private
    (RFC 1918, ULA), link-local (the cloud metadata services), CGNAT, multicast,
    reserved and unspecified addresses, Azure's platform address, and any IPv4
    address in IPv4-mapped IPv6 form."""
    ip = _unmapped(ip)
    if ip == _AZURE_PLATFORM_IP:
        return False
    return ip.is_global and not (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
    )


async def _resolve(host: str, port: int) -> list[str]:
    """Every address DNS gives for *host* (tests stand in for it)."""
    infos = await asyncio.get_running_loop().getaddrinfo(host, port, type=socket.SOCK_STREAM)
    return [info[4][0] for info in infos]


async def _public_address(host: str, port: int) -> IPAddress:
    """The address to connect to for *host* (a name or an IP literal).

    Refused unless every address it has is public: a name that also resolves
    inward is never fetched. IPv4 is preferred, as the container may have no
    IPv6 route and a pinned connection doesn't fall back to another address.
    """
    try:
        addresses = [ipaddress.ip_address(host)]
    except ValueError:
        addresses = [ipaddress.ip_address(a) for a in await _resolve(host, port)]
    if not addresses:
        raise Refused(f"{host} has no address")
    for ip in addresses:
        if not is_public_ip(ip):
            name = "" if str(ip) == host else f" ({host})"
            raise Refused(f"non-public address {ip}{name}")
    addresses = [_unmapped(ip) for ip in addresses]
    return next((ip for ip in addresses if ip.version == 4), addresses[0])


async def _pin(url: str) -> tuple[httpx.URL, dict[str, str], dict[str, str]]:
    """*url* re-addressed to the public IP its host resolves to, with the headers
    and extensions that keep it the host's: the Host header, and the TLS server
    name (SNI, which the certificate is checked against).

    The address checked is the address connected to, so a name can't pass the
    check at one address and connect at another (DNS rebinding). Refused for
    anything but an http(s) URL on a public host. Any port is allowed: it's the
    address check that keeps internal services out of reach.
    """
    try:
        parsed = httpx.URL(url)
    except httpx.InvalidURL:
        raise Refused("not a valid URL") from None
    if web_url(str(parsed)) is None:
        raise Refused("not an http(s) URL")
    host = parsed.raw_host.decode("ascii")  # IDNA-encoded, as DNS and TLS want it
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    ip = await _public_address(host, port)
    return (
        parsed.copy_with(host=str(ip)),
        {"Host": parsed.netloc.decode("ascii")},
        {"sni_hostname": host},
    )


def _next_hop(url: str, location: str) -> str:
    """Where a redirect from *url* to *location* leads (absolute)."""
    try:
        return str(httpx.URL(url).join(location))
    except httpx.InvalidURL:
        raise Refused("redirect to an invalid URL") from None


async def _read_capped(resp: httpx.Response, max_bytes: int) -> bytes:
    """At most *max_bytes* of *resp*'s body: the rest is never read."""
    body = bytearray()
    async for chunk in resp.aiter_bytes():
        body += chunk
        if len(body) >= max_bytes:
            break
    return bytes(body[:max_bytes])


def _loggable_url(url: str) -> str:
    """*url* for a log line: scheme, host and path, without the query string,
    fragment or credentials, and no control characters."""
    try:
        parts = urlsplit(url)
        host = parts.hostname or ""
    except ValueError:
        return "(invalid URL)"
    return _LOG_UNSAFE.sub("?", f"{parts.scheme}://{host}{parts.path}"[:300])


async def fetch_public(
    url: str,
    *,
    max_bytes: int,
    timeout: float,
    headers: dict[str, str] | None = None,
) -> Page | None:
    """GET an untrusted *url*: http(s) only, public addresses only, at most
    _MAX_REDIRECTS redirects, each checked as the first URL is, and each hop
    connected to the address its check resolved (_pin).

    None when a URL on the way is refused, logged without its query string.
    Reads at most *max_bytes* of the final response's body. The fetch has
    *timeout* seconds in all, redirects included (TimeoutError past it), so a
    host dripping bytes can't hold it; httpx's own errors are raised as well.
    """
    hop = url
    try:
        async with asyncio.timeout(timeout):
            # trust_env=False: no proxy from the environment, so the address
            # checked is the address connected to.
            async with httpx.AsyncClient(
                timeout=timeout, headers=headers, trust_env=False
            ) as client:
                for _ in range(_MAX_REDIRECTS + 1):
                    target, host_header, extensions = await _pin(hop)
                    async with client.stream(
                        "GET", target, headers=host_header, extensions=extensions
                    ) as resp:
                        if resp.has_redirect_location:
                            hop = _next_hop(hop, resp.headers["location"])
                            continue
                        body = await _read_capped(resp, max_bytes)
                        return Page(resp.status_code, body, resp.charset_encoding)
                raise Refused(f"more than {_MAX_REDIRECTS} redirects")
    except Refused as exc:
        logger.warning("Refused to fetch %s: %s", _loggable_url(url), exc)
        return None


# ---------------------------------------------------------------------------
# Extraction
# ---------------------------------------------------------------------------


def _cache_key(url: str) -> str:
    """Deterministic cache key for a URL.

    v2: results cached before redirects were checked are never served.
    """
    h = hashlib.sha256(url.encode()).hexdigest()[:16]
    return f"scrape:v2:{h}"


def _smart_truncate(
    text: str,
    question_keywords: list[str],
    max_words: int = _MAX_TEXT_WORDS,
) -> str:
    """Truncate text to ~max_words, prioritising keyword-relevant paragraphs.

    Splits text into paragraphs, scores each by keyword hits, then assembles
    the output: lede paragraphs first, then highest-scoring paragraphs,
    until the word budget is exhausted.
    """
    paragraphs = [p.strip() for p in text.split("\n") if p.strip()]
    if not paragraphs:
        return text[: max_words * 7]  # rough char estimate

    # Score paragraphs by keyword relevance
    kw_lower = [k.lower() for k in question_keywords if len(k) > 2]
    scored: list[tuple[int, int, str]] = []  # (relevance, original_idx, text)
    for i, para in enumerate(paragraphs):
        para_lower = para.lower()
        hits = sum(1 for kw in kw_lower if kw in para_lower)
        scored.append((hits, i, para))

    # Always include the first 2 paragraphs (lede), then highest-scoring
    lede = scored[:2]
    rest = sorted(scored[2:], key=lambda x: (-x[0], x[1]))

    output: list[str] = []
    word_count = 0
    for _, _, para in lede + rest:
        words = para.split()
        if word_count + len(words) > max_words and output:
            break
        output.append(para)
        word_count += len(words)

    return "\n\n".join(output)


def _extract_trafilatura(html: str) -> str | None:
    """Try trafilatura extraction."""
    try:
        import trafilatura

        text = trafilatura.extract(html, include_comments=False, include_tables=False)
        return text if text and len(text) > 100 else None
    except Exception:
        logger.debug("trafilatura extraction failed", exc_info=True)
        return None


def _extract_bs4(html: str) -> str | None:
    """Try BeautifulSoup extraction from <article> or <p> tags."""
    try:
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html, "html.parser")

        # Remove script/style
        for tag in soup(["script", "style", "nav", "header", "footer"]):
            tag.decompose()

        # Try <article> first
        article = soup.find("article")
        if article:
            paragraphs = article.find_all("p")
            text = "\n\n".join(p.get_text(strip=True) for p in paragraphs if p.get_text(strip=True))
            if len(text) > 100:
                return text

        # Fall back to all <p> tags
        paragraphs = soup.find_all("p")
        text = "\n\n".join(p.get_text(strip=True) for p in paragraphs if p.get_text(strip=True))
        return text if len(text) > 100 else None
    except Exception:
        logger.debug("bs4 extraction failed", exc_info=True)
        return None


def _extract_meta(html: str) -> str | None:
    """Extract <meta name="description"> content."""
    try:
        match = re.search(
            r'<meta\s+(?:name|property)=["\'](?:description|og:description)["\']\s+content=["\']([^"\']+)["\']',
            html,
            re.IGNORECASE,
        )
        if match:
            desc = match.group(1).strip()
            return desc if len(desc) > 20 else None
        return None
    except Exception:
        return None


async def extract_article_text(
    url: str,
    question_keywords: list[str] | None = None,
) -> dict[str, Any]:
    """Fetch and extract article text from a URL.

    Returns:
        {"url": str, "title": str, "text": str, "quality": "full"|"partial"|"meta_only"|"failed"}
    """
    # Check cache first
    cached = await get_cached(_cache_key(url))
    if cached is not None:
        logger.info("Cache hit for %s", _loggable_url(url))
        return cached

    result: dict[str, Any] = {"url": url, "title": "", "text": "", "quality": "failed"}

    try:
        page = await fetch_public(
            url,
            max_bytes=_MAX_PAGE_BYTES,
            timeout=_FETCH_TIMEOUT,
            headers={"User-Agent": _USER_AGENT},
        )
    except Exception as exc:
        logger.warning("Failed to fetch %s: %r", _loggable_url(url), exc)
        return result
    if page is None:  # refused, and logged
        return result
    if not 200 <= page.status < 300:
        logger.warning("Failed to fetch %s: HTTP %d", _loggable_url(url), page.status)
        return result
    html = page.text()

    # Extract title
    title_match = re.search(r"<title>([^<]+)</title>", html, re.IGNORECASE)
    if title_match:
        result["title"] = title_match.group(1).strip()

    # Cascade: trafilatura -> bs4 -> meta
    text = _extract_trafilatura(html)
    if text:
        result["quality"] = "full"
    else:
        text = _extract_bs4(html)
        if text:
            result["quality"] = "partial"
        else:
            text = _extract_meta(html)
            if text:
                result["quality"] = "meta_only"

    if text:
        keywords = question_keywords or []
        result["text"] = _smart_truncate(text, keywords)

    # Cache the result (even failures, to avoid re-fetching broken URLs)
    try:
        await set_cached(_cache_key(url), result, ttl=_CACHE_TTL)
    except Exception:
        pass  # caching is best-effort

    logger.info(
        "Extracted %s quality from %s (%d chars)",
        result["quality"],
        _loggable_url(url),
        len(result.get("text", "")),
    )
    return result
