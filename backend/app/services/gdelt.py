"""Client for GDELT raw data files and APIs."""

from __future__ import annotations

import asyncio
import html as html_mod
import io
import logging
import math
import re
import zipfile
from datetime import date, datetime, timezone
from urllib.parse import urlsplit, urlunsplit

import httpx

from app.config import settings
from app.services.country_codes import fips_to_iso2

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Keyword-based sentiment estimation (fallback when GDELT omits tone)
# ---------------------------------------------------------------------------

_NEGATIVE_WORDS = {
    "killed",
    "dead",
    "death",
    "dies",
    "attack",
    "murder",
    "crash",
    "war",
    "bomb",
    "shooting",
    "stabbing",
    "victim",
    "fatal",
    "tragedy",
    "arrest",
    "charged",
    "fraud",
    "scandal",
    "crisis",
    "threat",
    "riot",
    "fire",
    "explosion",
    "collapse",
    "drought",
    "flood",
    "earthquake",
    "hurricane",
    "devastat",
    "destroy",
    "terror",
    "hostage",
    "kidnap",
    "abuse",
    "assault",
    "protest",
    "strike",
    "lawsuit",
    "sued",
    "indict",
    "convict",
    "sentence",
    "layoff",
    "bankrupt",
    "recession",
    "shutdown",
    "fail",
    "reject",
    "deportat",
    "detain",
    "sanction",
    "condemn",
    "flee",
    "refugee",
}

_POSITIVE_WORDS = {
    "win",
    "wins",
    "won",
    "victory",
    "success",
    "celebrate",
    "record",
    "breakthrough",
    "award",
    "honor",
    "rescue",
    "save",
    "recover",
    "boost",
    "surge",
    "grow",
    "growth",
    "profit",
    "deal",
    "launch",
    "achieve",
    "approve",
    "peace",
    "agreement",
    "cure",
    "champion",
    "hero",
    "milestone",
    "innovate",
    "discover",
    "partnership",
    "donate",
}


def _estimate_sentiment(title: str) -> float:
    """Estimate sentiment from title keywords. Returns -1.0 to 1.0."""
    words = set(title.lower().split())
    neg = sum(1 for w in words if any(w.startswith(n) for n in _NEGATIVE_WORDS))
    pos = sum(1 for w in words if any(w.startswith(p) for p in _POSITIVE_WORDS))
    if neg > pos:
        return -0.6 if neg >= 2 else -0.3
    if pos > neg:
        return 0.7 if pos >= 2 else 0.4
    return 0.0


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_MAX_RETRIES = 3
_BACKOFF_BASE = 1.5  # seconds

_GKG_LASTUPDATE_URL = "https://data.gdeltproject.org/gdeltv2/lastupdate.txt"

# Max concurrent title-scrape connections
_SCRAPE_CONCURRENCY = 30
_SCRAPE_TIMEOUT = 5.0  # seconds per request
_SCRAPE_MAX_BYTES = 15_000  # only read enough for <title>


_GDELT_HOST = "data.gdeltproject.org"


def _gdelt_https_url(url: str) -> str | None:
    """Return *url* upgraded to https if it points at GDELT's data host, else None.

    lastupdate.txt still lists http:// file URLs, but GDELT now redirects them
    to https. Rewriting up front (rather than following redirects) keeps every
    request on TLS and pinned to GDELT's host.
    """
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or parts.hostname != _GDELT_HOST:
        return None
    return urlunsplit(("https", _GDELT_HOST, parts.path, parts.query, ""))


async def _download_bytes(url: str) -> bytes | None:
    """Download raw bytes from a URL with retries."""
    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                resp = await client.get(url)
                resp.raise_for_status()
                return resp.content
        except Exception as exc:
            wait = _BACKOFF_BASE**attempt
            logger.warning(
                "Download attempt %d/%d failed for %s (%s). Retrying in %.1fs …",
                attempt,
                _MAX_RETRIES,
                url.split("/")[-1],
                exc,
                wait,
            )
            if attempt < _MAX_RETRIES:
                await asyncio.sleep(wait)
    logger.error("Download failed after %d attempts: %s", _MAX_RETRIES, url)
    return None


def _parse_gkg_date(date_str: str) -> datetime:
    """Parse GKG record date (YYYYMMDDHHMMSS format)."""
    try:
        return datetime.strptime(date_str.strip(), "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)
    except (ValueError, AttributeError):
        return datetime.now(timezone.utc)


def _is_usable_title(title: str) -> bool:
    """Return False for titles that are clearly not real article headlines."""
    t = title.lower().strip()
    # Cloudflare / bot-check pages
    if any(
        phrase in t
        for phrase in (
            "cloudflare",
            "just a moment",
            "please wait",
            "checking your browser",
            "access denied",
            "attention required",
            "are you a robot",
            "one moment, please",
            "loading...",
            "please enable cookies",
            "website is unavailable",
        )
    ):
        return False
    # HTTP error pages
    if re.match(r"^(4\d\d|5\d\d)\b", t):
        return False
    # Looks like a hex hash / UUID (e.g. "Article C3E3E6A6 08B2 4876 ...")
    alphanum = re.sub(r"[\s\-]", "", t)
    hex_chars = sum(c in "0123456789abcdef" for c in alphanum)
    if len(alphanum) > 8 and hex_chars / len(alphanum) > 0.7:
        return False
    # Starts with "article" followed by hex/digits (GDELT artifact)
    if re.match(r"^article\s+[\da-f]", t, re.IGNORECASE):
        return False
    return True


# ---------------------------------------------------------------------------
# GKG field parsers (one per field, so each is tested on its own)
# ---------------------------------------------------------------------------

_MAX_TITLE_CHARS = 300
_MAX_THEMES = 64
_MAX_ENTITIES = 30  # persons, organizations
_MAX_NAMES = 15
_MAX_COUNTS = 10
# V2.1COUNTS also carries theme names (e.g. SOC_GENERALCRIME); keep the count types.
_COUNT_TYPES = frozenset({"AFFECT", "ARREST", "KIDNAP", "KILL", "PROTEST", "SEIZE", "WOUND"})

# Only the first 2,000 raw characters are cleaned: the output is capped at 300,
# and the cap bounds the regex work on hostile input.
_MAX_RAW_TITLE_CHARS = 2000
# An unterminated comment runs to the end of the text. Without the "|$"
# alternative, every "<!--" rescans to the end: quadratic (16.8 s on 80 KB).
_HTML_COMMENT_RE = re.compile(r"<!--.*?(?:-->|$)", re.DOTALL)
# Real tags only (a letter after "<" or "</"), so "Inflation < 2%" survives.
# Text shaped like a tag ("x<y>z") is stripped too.
_HTML_TAG_RE = re.compile(r"</?[A-Za-z][^<>]*>")
_PAGE_TITLE_OPEN = "<PAGE_TITLE>"
_PAGE_TITLE_CLOSE = "</PAGE_TITLE>"


def _clean_title(raw: str) -> str:
    """Return a display-ready headline from a raw page title, or '' if unusable.

    Shared by GDELT's PAGE_TITLE and scraped <title> tags so both are cleaned
    alike: drop NUL bytes (Postgres rejects them), strip HTML comments (React
    leaves ``<!-- -->`` in some titles) and tags, unescape entities, collapse
    whitespace, cap at 300 characters. Comments are stripped again after
    unescaping in case they arrived escaped; tags are not, so a headline
    quoting ``&lt;div&gt;`` keeps it.
    """
    text = raw[:_MAX_RAW_TITLE_CHARS].replace("\x00", "")
    text = _HTML_TAG_RE.sub("", _HTML_COMMENT_RE.sub("", text))
    text = _HTML_COMMENT_RE.sub("", html_mod.unescape(text))
    text = " ".join(text.split())
    if len(text) <= 5 or not _is_usable_title(text):
        return ""
    return text[:_MAX_TITLE_CHARS].rstrip()


def _field(fields: list[str], index: int) -> str:
    """GKG column *index*, or '' when the record is shorter."""
    return fields[index] if len(fields) > index else ""


def _parse_page_title(extras: str) -> str:
    """Title from V2EXTRASXML's ``<PAGE_TITLE>``, cleaned; '' if missing or unusable.

    Uses str.find rather than a lazy regex, which rescans to the end from
    every unclosed opener (11.5 s on 120 KB of them).
    """
    start = extras.find(_PAGE_TITLE_OPEN)
    if start < 0:
        return ""
    start += len(_PAGE_TITLE_OPEN)
    end = extras.find(_PAGE_TITLE_CLOSE, start)
    return _clean_title(extras[start:end]) if end >= 0 else ""


def _parse_themes(raw: str) -> list[str]:
    """V1THEMES: distinct, non-empty themes in first-seen order, capped."""
    themes = dict.fromkeys(t.strip() for t in raw.split(";"))
    themes.pop("", None)
    return list(themes)[:_MAX_THEMES]


def _parse_entities(raw: str) -> list[str]:
    """V1PERSONS / V1ORGANIZATIONS: title-cased, distinct, in order, capped."""
    names = dict.fromkeys(p.strip().title() for p in raw.split(";") if p.strip())
    return list(names)[:_MAX_ENTITIES]


def _parse_names(raw: str) -> list[str]:
    """V2.1ALLNAMES (``Name,offset;...``): the most repeated names.

    Ties go to the name that occurs earliest in the text. Blocks without an
    integer offset are skipped.
    """
    counts: dict[str, int] = {}
    first_offset: dict[str, int] = {}
    for block in raw.split(";"):
        name, _, offset = block.rpartition(",")  # names may contain commas
        name = name.strip()
        try:
            pos = int(offset)
        except ValueError:
            continue
        if not name:
            continue
        counts[name] = counts.get(name, 0) + 1
        first_offset[name] = min(pos, first_offset.get(name, pos))
    ranked = sorted(counts, key=lambda n: (-counts[n], first_offset[n]))
    return ranked[:_MAX_NAMES]


def _parse_counts(v21_counts: str, v1_counts: str) -> list[dict]:
    """V2.1COUNTS (else V1COUNTS): typed counts such as people killed or arrested.

    Blocks are ``TYPE#N#OBJECT#LOCTYPE#LOCNAME#FIPS#ADM1#LAT#LNG#FEATUREID[#OFFSET]``.
    Only the count types are kept; blocks whose N is not an integer are
    skipped, exact duplicates (e.g. the same count at two offsets) dropped.
    """
    results: list[dict] = []
    seen: set[tuple] = set()
    for block in (v21_counts or v1_counts).split(";"):
        parts = block.split("#")
        if len(parts) < 2 or parts[0] not in _COUNT_TYPES:
            continue
        try:
            n = int(parts[1])
        except ValueError:
            continue
        parts += [""] * (6 - len(parts))
        count = {
            "type": parts[0],
            "n": n,
            "object": parts[2],
            "country": fips_to_iso2(parts[5]) or "",
            "place": parts[4],
        }
        key = tuple(count.values())
        if key in seen:
            continue
        seen.add(key)
        results.append(count)
        if len(results) == _MAX_COUNTS:
            break
    return results


def _parse_tone_detail(raw: str) -> dict | None:
    """V1.5TONE: tone, positive, negative, polarity (0-3) and word count (6).

    None when the field is malformed, including non-finite values, which
    JSONB cannot store.
    """
    parts = raw.split(",")
    if len(parts) < 7:
        return None
    try:
        tone, pos, neg, polarity = (float(p) for p in parts[:4])
        words = int(parts[6])
    except ValueError:
        return None
    if not all(math.isfinite(v) for v in (tone, pos, neg, polarity)):
        return None
    return {"tone": tone, "pos": pos, "neg": neg, "polarity": polarity, "words": words}


# ---------------------------------------------------------------------------
# Stale re-crawls: GKG sometimes lists pages published years ago, and the
# record's date (which becomes published_at) is when GDELT saw them.
# ---------------------------------------------------------------------------

_PUBTIME_OPEN = "<PAGE_PRECISEPUBTIMESTAMP>"
_PUBTIME_CLOSE = "</PAGE_PRECISEPUBTIMESTAMP>"
# The value is 14 digits: the closing tag is looked for only just past the opener.
_PUBTIME_MAX_CHARS = 32
# Earlier page dates are malformed: news sites barely existed.
_MIN_PAGE_YEAR = 1995

# A date starting a URL path segment: /2005/07/11/, /2020-08-04-slug, /20200804/.
# One delimiter throughout (none: 8 digits), ending a segment or followed by ".",
# "-" or "_". A date inside a slug ("what-happened-on-2001-09-11") or inside a
# longer number or word (IDs) never matches. No nested repetition: linear.
_URL_DATE_RE = re.compile(r"(?<=/)((?:19|20)[0-9]{2})([/_-]?)([0-9]{2})\2([0-9]{2})(?=[/._-]|$)")


def _page_published_at(extras_xml: str) -> datetime | None:
    """V2EXTRASXML's ``<PAGE_PRECISEPUBTIMESTAMP>`` (YYYYMMDDHHMMSS, UTC).

    None when absent or malformed. Uses str.find, bounded to just past the
    opening tag, rather than a regex over the whole field.
    """
    start = extras_xml.find(_PUBTIME_OPEN)
    if start < 0:
        return None
    start += len(_PUBTIME_OPEN)
    end = extras_xml.find(_PUBTIME_CLOSE, start, start + _PUBTIME_MAX_CHARS + len(_PUBTIME_CLOSE))
    if end < 0:
        return None
    value = extras_xml[start:end].strip()
    if len(value) != 14 or not (value.isascii() and value.isdigit()):
        return None
    try:
        published = datetime.strptime(value, "%Y%m%d%H%M%S")
    except ValueError:
        return None
    if published.year < _MIN_PAGE_YEAR:
        return None
    return published.replace(tzinfo=timezone.utc)


def _url_date(url: str) -> date | None:
    """The publication date in a web URL's path, or None if it has no clear one.

    Only the path is read (not the host, query string or fragment), only a
    date starting a segment counts (a slug about a past event must not make a
    new page look old), and only valid calendar dates from 1995 to this year.
    When the path holds several, the latest wins.
    """
    try:
        parts = urlsplit(url)
    except ValueError:
        return None
    if parts.scheme not in ("http", "https"):
        return None
    this_year = datetime.now(timezone.utc).year
    latest = None
    for match in _URL_DATE_RE.finditer(parts.path):
        year, _, month, day = match.groups()
        if not _MIN_PAGE_YEAR <= int(year) <= this_year:
            continue
        try:
            found = date(int(year), int(month), int(day))
        except ValueError:
            continue
        if latest is None or found > latest:
            latest = found
    return latest


def _page_date(extras_xml: str, url: str) -> date | None:
    """When the page itself was published: GDELT's precise timestamp, else its URL's date."""
    published = _page_published_at(extras_xml)
    return published.date() if published else _url_date(url)


def _is_stale_recrawl(page_date: date | None, seen_at: datetime) -> bool:
    """Whether a page dated *page_date* is older than the retention window at *seen_at*.

    *seen_at* is the GKG record's date. Pages without a date are kept.
    """
    if page_date is None:
        return False
    return (seen_at.date() - page_date).days > settings.retention_days


# ---------------------------------------------------------------------------
# Public API — raw GKG data files
# ---------------------------------------------------------------------------


async def fetch_raw_gkg() -> list[dict]:
    """Download the latest GDELT GKG data file and extract city-level articles.

    Each 15-minute GKG file contains ~1000+ records.  We filter to records
    with city-level locations (type 3=USCITY or 4=WORLDCITY), skip stale
    re-crawls (pages published over ``retention_days`` before GDELT listed
    them) and deduplicate by URL, returning a few hundred unique articles with
    city-level coordinates.

    Returns a list of dicts with keys:
        url, domain, lat, lng, location_name, country_code, country_fips,
        tone, tone_detail (only when V1.5TONE is well formed), page_title
        ('' when GDELT has no usable one), themes, persons, organizations,
        names, counts, mentioned_locations, image_url, published_at
    """
    # 1. Find the latest GKG file URL
    index_bytes = await _download_bytes(_GKG_LASTUPDATE_URL)
    if not index_bytes:
        logger.error("Could not fetch GDELT lastupdate index.")
        return []

    gkg_url = None
    for line in index_bytes.decode("utf-8", errors="replace").strip().split("\n"):
        parts = line.strip().split()
        if len(parts) >= 3 and "gkg" in parts[2].lower():
            gkg_url = parts[2]
            break

    if not gkg_url:
        logger.error("No GKG file URL found in lastupdate index.")
        return []

    safe_url = _gdelt_https_url(gkg_url)
    if not safe_url:
        logger.error("Refusing GKG file URL outside %s: %s", _GDELT_HOST, gkg_url)
        return []
    gkg_url = safe_url

    # 2. Download and unzip
    logger.info("Downloading GKG file: %s", gkg_url.split("/")[-1])
    zip_bytes = await _download_bytes(gkg_url)
    if not zip_bytes:
        return []

    try:
        zf = zipfile.ZipFile(io.BytesIO(zip_bytes))
        raw = zf.read(zf.namelist()[0]).decode("utf-8", errors="replace")
    except Exception:
        logger.error("Failed to unzip GKG file.", exc_info=True)
        return []
    # NUL survives decoding, and Postgres TEXT, TEXT[] and JSONB reject it: one
    # such record would roll back the whole upsert transaction.
    raw = raw.replace("\x00", "")

    # 3. Parse off the event loop: the per-record work is CPU-bound, and the
    # container also serves the API.
    return await asyncio.to_thread(_parse_gkg, raw)


def _parse_gkg(raw: str) -> list[dict]:
    """Parse a decoded GKG 2.1 file into city-level articles (see fetch_raw_gkg)."""
    # One record per line, tab-separated.
    # GKG 2.1 field indices (0-based, tab-delimited):
    #  0: GKGRECORDID
    #  1: V2.1DATE (YYYYMMDDHHMMSS)
    #  3: V2SOURCECOMMONNAME (domain)
    #  4: V2DOCUMENTIDENTIFIER (article URL)
    #  5: V1COUNTS (fallback for 6; same blocks without the offset)
    #  6: V2.1COUNTS (semicolon-delimited TYPE#N#OBJECT#LOCTYPE#LOCNAME#FIPS#...#OFFSET)
    #  7: V1THEMES (semicolon-delimited)
    #  9: V1LOCATIONS (semicolon-delimited blocks, #-delimited fields)
    # 11: V1PERSONS (semicolon-delimited)
    # 13: V1ORGANIZATIONS (semicolon-delimited)
    # 15: V1.5TONE (comma-separated: tone, pos, neg, polarity, act, self, words)
    # 18: V2.1SHARINGIMAGE (URL)
    # 23: V2.1ALLNAMES (semicolon-delimited Name,offset)
    # 26: V2EXTRASXML (<PAGE_TITLE>, <PAGE_PRECISEPUBTIMESTAMP> among other tags)
    articles: dict[str, dict] = {}  # keyed by URL for dedup
    stale = 0

    lines = raw.strip().split("\n")
    for line in lines:
        fields = line.split("\t")
        if len(fields) < 16:
            continue

        url = fields[4] if len(fields) > 4 else ""
        if not url or url in articles:
            continue

        # Find first city-level location (type 3 or 4)
        locations_raw = fields[9] if len(fields) > 9 else ""
        if not locations_raw:
            continue

        city_loc = None
        # Collect all mentioned countries/locations for knowledge graph
        mentioned_locations: list[dict] = []
        seen_countries: set[str] = set()
        for loc_block in locations_raw.split(";"):
            parts = loc_block.split("#")
            # Fields: Type#FullName#CountryCode#ADM1Code#Lat#Lng#FeatureID
            # CountryCode is FIPS 10-4; we store ISO 3166-1 alpha-2 and keep the raw code.
            if len(parts) < 7:
                continue
            loc_type = parts[0]
            try:
                lat = float(parts[4])
                lng = float(parts[5])
            except (ValueError, IndexError):
                continue

            # Use first city-level location as article geolocation
            if loc_type in ("3", "4") and city_loc is None:
                city_loc = {
                    "fullname": parts[1],
                    "country_code": fips_to_iso2(parts[2]),
                    "country_fips": parts[2],
                    "lat": lat,
                    "lng": lng,
                }

            # Collect country-level mentions (type 1) for KG
            if loc_type == "1" and parts[2] not in seen_countries:
                seen_countries.add(parts[2])
                mentioned_locations.append(
                    {
                        "name": parts[1].strip(),
                        "country_code": fips_to_iso2(parts[2]),
                        "country_fips": parts[2],
                        "lat": lat,
                        "lng": lng,
                    }
                )

        if not city_loc:
            continue

        # Old pages GDELT re-crawled are not news, whatever the record's date.
        extras = _field(fields, 26)
        published_at = _parse_gkg_date(_field(fields, 1))
        if _is_stale_recrawl(_page_date(extras, url), published_at):
            stale += 1
            continue

        # Extract tone (first value in comma-separated V1.5TONE)
        tone_raw = fields[15] if len(fields) > 15 else ""
        tone = 0.0
        if tone_raw:
            try:
                tone = float(tone_raw.split(",")[0])
            except (ValueError, IndexError):
                pass

        image_url = _field(fields, 18).strip()

        article = {
            "url": url,
            "domain": _field(fields, 3),
            "lat": city_loc["lat"],
            "lng": city_loc["lng"],
            "location_name": city_loc["fullname"],
            "country_code": city_loc["country_code"],
            "country_fips": city_loc["country_fips"],
            "tone": tone,
            "page_title": _parse_page_title(extras),
            "themes": _parse_themes(_field(fields, 7)),
            "persons": _parse_entities(_field(fields, 11)),
            "organizations": _parse_entities(_field(fields, 13)),
            "names": _parse_names(_field(fields, 23)),
            "counts": _parse_counts(_field(fields, 6), _field(fields, 5)),
            "mentioned_locations": mentioned_locations,
            "image_url": image_url if image_url.startswith("http") else "",
            "published_at": published_at,
        }
        tone_detail = _parse_tone_detail(tone_raw)
        if tone_detail is not None:
            article["tone_detail"] = tone_detail
        articles[url] = article

    logger.info(
        "GKG raw file: %d records, %d with city-level locations, %d stale re-crawls skipped.",
        len(lines),
        len(articles),
        stale,
    )
    return list(articles.values())


async def scrape_titles(articles: list[dict]) -> list[dict]:
    """Concurrently scrape <title> tags from article URLs.

    Sets each article's ``title`` to its page's <title>, cleaned by
    ``_clean_title``. Articles whose page fails or has no usable title are
    left without one (ingestion drops them).
    """
    semaphore = asyncio.Semaphore(_SCRAPE_CONCURRENCY)

    async def _scrape_one(article: dict) -> None:
        url = article["url"]
        async with semaphore:
            try:
                async with httpx.AsyncClient(
                    timeout=_SCRAPE_TIMEOUT,
                    follow_redirects=True,
                    max_redirects=3,
                ) as client:
                    resp = await client.get(url)
                    # Only read enough bytes for <title>
                    text = resp.content[:_SCRAPE_MAX_BYTES].decode("utf-8", errors="replace")
                    match = re.search(r"<title[^>]*>(.*?)</title>", text, re.IGNORECASE | re.DOTALL)
                    if match:
                        title = _clean_title(match.group(1))
                        if title:
                            article["title"] = title
            except Exception:
                pass  # title stays empty → article will be dropped

    await asyncio.gather(*[_scrape_one(a) for a in articles])
    return articles
