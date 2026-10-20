"""Story identity: a title without its outlet suffix, and a stable key for it.

Syndicated copies of one story carry its headline with different outlet
names ("Quake hits Kathmandu - Reuters", "... | BBC News") and different
typography (curly or straight quotes, an en dash or a hyphen, "WATCH:" in
front, a full stop at the end): ``dedup_key`` is what they share, and
``story_key`` is that as the 64-bit integer ingestion stores in
``articles.story_key``, so queries can count stories rather than copies.
``display_title`` is the same headline with its case, to show.
"""

from __future__ import annotations

import hashlib
import html
import re
import unicodedata

# Pattern: "Headline : NPR", "Headline | WXXJ News", "Headline - The Post"
# (dashes are folded to "-" first). The patterns here are Postgres ARE too:
# threads.shown_title_sql applies them in SQL.
OUTLET_SEP_PATTERN = r"\s+[|:-]\s+"
_OUTLET_SEP = re.compile(OUTLET_SEP_PATTERN)
OUTLET_MAX_CHARS = 40  # text after the last separator shorter than this is the outlet's name

# Curly quotes as straight ones; every dash style as "-" (NFKC leaves these).
_QUOTES = str.maketrans(
    {
        "\u2018": "'",
        "\u2019": "'",
        "\u201a": "'",
        "\u201b": "'",
        "\u2032": "'",
        "\u201c": '"',
        "\u201d": '"',
        "\u201e": '"',
        "\u201f": '"',
        "\u2033": '"',
    }
)
# The dashes as characters, for SQL's translate() too (threads.shown_title_sql).
DASH_CHARS = "".join(
    map(chr, (*range(0x2010, 0x2016), 0x2212, 0x2E3A, 0x2E3B, 0xFE58, 0xFE63, 0xFF0D))
)
_DASHES = re.compile(f"[{DASH_CHARS}]")
_SPACES = re.compile(r"\s+")

# Tags newsrooms put before a headline: "WATCH:", "LIVE |", "Live updates - ",
# "BREAKING NEWS:", and Reuters' "UPDATE 2-". A tag needs a colon, a bar or a
# spaced dash after it ("Live-action remake" keeps its word), except UPDATE n.
LEADING_TAGS_PATTERN = (
    r"^\s*(?:"
    r"(?:breaking(?: news)?|live(?: updates?)?|watch|video|exclusive|analysis|opinion)"
    r"\s*(?::|\||\s-\s)\s*"
    r"|update(?:d)?(?: \d+)?\s*(?::|\||-)\s*"
    r")+"
)
_LEADING_TAGS = re.compile(LEADING_TAGS_PATTERN, re.IGNORECASE)
_TRAILING_PUNCTUATION = re.compile(r"[\s.,;:!?]+$")


def display_title(title: str) -> str:
    """A title as one headline to show, its case kept.

    HTML entities decoded, NFKC, straight quotes, every dash as "-", one
    space between words; a leading tag ("WATCH:", "UPDATE 2-") dropped; then
    the outlet's name: the text after the last separator (whitespace, one of
    | : -, whitespace), when it is shorter than OUTLET_MAX_CHARS (40).
    """
    text = unicodedata.normalize("NFKC", html.unescape(title))
    text = _SPACES.sub(" ", _DASHES.sub("-", text.translate(_QUOTES)))
    text = _LEADING_TAGS.sub("", text)
    parts = list(_OUTLET_SEP.finditer(text))
    if parts:
        last = parts[-1]
        if len(text[last.end() :]) < OUTLET_MAX_CHARS:
            text = text[: last.start()]
    return text.strip()


def dedup_key(title: str) -> str:
    """A title's story: ``display_title`` without trailing punctuation, lowercased."""
    return _TRAILING_PUNCTUATION.sub("", display_title(title)).lower()


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


def story_key_sql(alias: str = "a") -> str:
    """The story a row belongs to, as a SQL expression: its story_key, or for a row
    written before ingestion keyed it (migration 012), a hash of its lowercased title,
    so an unkeyed row still counts, and exact-title copies still collapse.

    *alias* is the articles table's alias in the query, written into the SQL
    as it is, so it must be a plain identifier (ValueError otherwise).
    """
    if not alias.isidentifier():
        raise ValueError(f"Not a plain SQL alias: {alias!r}")
    return f"COALESCE({alias}.story_key, hashtextextended(lower({alias}.title), 0))"
