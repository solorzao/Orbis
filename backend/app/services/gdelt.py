"""Client for GDELT raw data files and APIs."""

from __future__ import annotations

import asyncio
import html as html_mod
import io
import logging
import re
import zipfile
from datetime import datetime, timezone

import httpx

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


async def _download_bytes(url: str) -> bytes | None:
    """Download raw bytes from a URL with retries."""
    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            # GDELT redirects http:// to https://, and the file URLs listed in
            # lastupdate.txt are still http://, so redirects must be followed.
            async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as client:
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
# Public API — raw GKG data files
# ---------------------------------------------------------------------------


async def fetch_raw_gkg() -> list[dict]:
    """Download the latest GDELT GKG data file and extract city-level articles.

    Each 15-minute GKG file contains ~1000+ records.  We filter to records
    with city-level locations (type 3=USCITY or 4=WORLDCITY) and deduplicate
    by URL, returning ~600 unique articles with city-level coordinates.

    Returns a list of dicts with keys:
        url, domain, lat, lng, location_name, tone, themes,
        image_url, published_at
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

    # 3. Parse TSV — one record per document
    # GKG 2.1 field indices (0-based, tab-delimited):
    #  0: GKGRECORDID
    #  1: V2.1DATE (YYYYMMDDHHMMSS)
    #  3: V2SOURCECOMMONNAME (domain)
    #  4: V2DOCUMENTIDENTIFIER (article URL)
    #  7: V1THEMES (semicolon-delimited)
    #  9: V1LOCATIONS (semicolon-delimited blocks, #-delimited fields)
    # 15: V1.5TONE (comma-separated: tone, pos, neg, polarity, ...)
    # 18: V2.1SHARINGIMAGE (URL)
    articles: dict[str, dict] = {}  # keyed by URL for dedup

    for line in raw.strip().split("\n"):
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
                    "country_code": parts[2],
                    "lat": lat,
                    "lng": lng,
                }

            # Collect country-level mentions (type 1) for KG
            if loc_type == "1" and parts[2] not in seen_countries:
                seen_countries.add(parts[2])
                mentioned_locations.append(
                    {
                        "name": parts[1].strip(),
                        "country_code": parts[2],
                        "lat": lat,
                        "lng": lng,
                    }
                )

        if not city_loc:
            continue

        # Extract tone (first value in comma-separated V1.5TONE)
        tone_raw = fields[15] if len(fields) > 15 else ""
        tone = 0.0
        if tone_raw:
            try:
                tone = float(tone_raw.split(",")[0])
            except (ValueError, IndexError):
                pass

        domain = fields[3] if len(fields) > 3 else ""
        # GKG field 11 = V1PERSONS, field 13 = V1ORGANIZATIONS (semicolon-delimited)
        persons_raw = fields[11] if len(fields) > 11 else ""
        orgs_raw = fields[13] if len(fields) > 13 else ""
        persons = (
            list(dict.fromkeys(p.strip().title() for p in persons_raw.split(";") if p.strip()))
            if persons_raw
            else []
        )
        organizations = (
            list(dict.fromkeys(o.strip().title() for o in orgs_raw.split(";") if o.strip()))
            if orgs_raw
            else []
        )
        themes = fields[7] if len(fields) > 7 else ""
        image_url = fields[18].strip() if len(fields) > 18 else ""
        date_str = fields[1] if len(fields) > 1 else ""

        articles[url] = {
            "url": url,
            "domain": domain,
            "lat": city_loc["lat"],
            "lng": city_loc["lng"],
            "location_name": city_loc["fullname"],
            "country_code": city_loc["country_code"],
            "tone": tone,
            "themes": themes,
            "persons": persons,
            "organizations": organizations,
            "mentioned_locations": mentioned_locations,
            "image_url": image_url if image_url.startswith("http") else "",
            "published_at": _parse_gkg_date(date_str),
        }

    logger.info(
        "GKG raw file: %d records, %d with city-level locations.",
        len(raw.strip().split("\n")),
        len(articles),
    )
    return list(articles.values())


async def scrape_titles(articles: list[dict]) -> list[dict]:
    """Concurrently scrape <title> tags from article URLs.

    For each article dict, adds a ``title`` key with the scraped title
    or a fallback derived from the URL path.
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
                        title = html_mod.unescape(match.group(1)).strip()
                        if len(title) > 5 and _is_usable_title(title):
                            article["title"] = title[:300]
                            return
            except Exception:
                pass  # title stays empty → article will be dropped

    await asyncio.gather(*[_scrape_one(a) for a in articles])

    scraped = sum(1 for a in articles if a.get("title"))
    logger.info(
        "Title scraping: %d/%d got usable titles, %d dropped.",
        scraped,
        len(articles),
        len(articles) - scraped,
    )
    return articles
