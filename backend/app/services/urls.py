"""Untrusted URLs: the one http(s) sanitiser the board and GDELT Events share."""

from __future__ import annotations

import re
from urllib.parse import urlsplit

_MAX_URL = 2048
_URL_UNSAFE = re.compile(r"[\x00-\x20\x7f]")


def web_url(url: object) -> str | None:
    """*url* when it is an absolute http(s) link with a host, else None."""
    if not isinstance(url, str) or len(url) > _MAX_URL or _URL_UNSAFE.search(url):
        return None
    try:
        parts = urlsplit(url)
    except ValueError:
        return None
    if parts.scheme not in ("http", "https") or not parts.netloc or not parts.hostname:
        return None
    return url


def outlet(url: str) -> str:
    """The outlet an http(s) URL comes from: its host, lowercased, without "www."."""
    try:
        host = (urlsplit(url).hostname or "").lower()
    except ValueError:
        return ""
    return host.removeprefix("www.")
