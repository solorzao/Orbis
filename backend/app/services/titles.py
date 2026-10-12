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


# dedup_key in SQL, for queries that key titles as they read them.

# The characters Python's \s matches (str.isspace), spelled out: PostgreSQL's
# \s follows the database's locale, which leaves out the no-break spaces.
_WS = r"[\t\n\v\f\r\u001c-\u001f \u0085\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000]"

# _OUTLET_SEP: whitespace, one of | : – — -, whitespace.
_SEP = rf"{_WS}+[|:–—-]{_WS}+"

# What may follow the last separator: text with no whitespace-separator-
# whitespace run in it (so the separator is the last), e.g. "Post-Gazette".
# Spelled without a lookahead per character, which cost 3 times as much.
_NOT_WS = rf"[^{_WS[1:-1]}]"
_PLAIN = rf"[^{_WS[1:-1]}|:–—-]"  # neither whitespace nor a separator
_NO_SEP = rf"(?:{_NOT_WS}|{_WS}+{_PLAIN}|{_WS}+[|:–—-]{_NOT_WS})*(?:{_WS}+[|:–—-]?)?"

# The outlet: fewer than 40 characters after the last separator, to the end.
_SUFFIX = rf"(?=.{{0,39}}$){_NO_SEP}$"


def dedup_title_sql(column: str = "title") -> str:
    """``dedup_key(column)`` as a SQL expression; *column* is a text expression.

    The last separator goes, with everything after it, when fewer than 40
    characters follow it (an outlet's name, not the headline's second half);
    then whitespace at either end, then the case. A suffix holding a hyphen
    ("Post-Gazette") still goes, as in Python. The regexes are literals, so
    the expression adds no bind parameters to the query it sits in.

    The key is collated "C": it is only ever compared, to tell stories apart,
    and sorting it bytewise rather than by the locale made count(DISTINCT)
    over a week of stories a third faster. Equality is unchanged (a
    deterministic collation's is bytewise too).
    """
    stripped = f"regexp_replace({column}, '{_SEP}{_SUFFIX}', '')"
    return f"""(lower(regexp_replace({stripped}, '^{_WS}+|{_WS}+$', '', 'g')) COLLATE "C")"""
