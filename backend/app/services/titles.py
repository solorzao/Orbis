"""Story identity: a title without its outlet suffix, and a stable key for it.

Syndicated copies of one story carry its headline with different outlet
names ("Quake hits Kathmandu - Reuters", "... | BBC News"): ``dedup_key``
is what they share, and ``story_key`` is that as the 64-bit integer
ingestion stores in ``articles.story_key``, so queries can count stories
rather than copies.
"""

from __future__ import annotations

import hashlib
import re

# Pattern: "Headline : NPR", "Headline | WXXJ News", "Headline - The Post"
_OUTLET_SEP = re.compile(r"\s+[|:–—-]\s+")


def dedup_key(title: str) -> str:
    """Normalize a title for dedup by stripping the trailing outlet name."""
    # Split on the last separator; if suffix is short it's likely an outlet name
    parts = list(_OUTLET_SEP.finditer(title))
    if parts:
        last = parts[-1]
        suffix = title[last.end() :]
        if len(suffix) < 40:
            title = title[: last.start()]
    return title.strip().lower()


def story_key(title: str, source_url: str) -> int:
    """The story an article is a copy of, as a signed 64-bit integer (a PostgreSQL BIGINT).

    BLAKE2b with an 8-byte digest (``digest_size=8``, which is not
    BLAKE2b-512 truncated) of ``dedup_key(title)`` as UTF-8, read as a
    big-endian signed integer: the same in every process and every deploy,
    unlike ``hash()``, so keys written months apart compare. An article with
    no headline left is keyed by ``"url:" + source_url`` instead, so untitled
    articles do not all count as one story.
    """
    text = dedup_key(title) or f"url:{source_url}"
    digest = hashlib.blake2b(text.encode("utf-8"), digest_size=8).digest()
    return int.from_bytes(digest, "big", signed=True)
