"""Article text extraction with multi-strategy cascade and Redis caching.

Extraction order:
1. trafilatura (best quality, handles boilerplate removal)
2. BeautifulSoup <article>/<p> tag extraction
3. <meta name="description"> fallback

Results are cached in Redis with a 24-hour TTL keyed by URL hash.
"""

from __future__ import annotations

import hashlib
import logging
import re
from typing import Any

import httpx

from app.services.cache import get_cached, set_cached

logger = logging.getLogger("orbis.scraper")

_CACHE_TTL = 86400  # 24 hours
_FETCH_TIMEOUT = 5.0  # seconds per request
_MAX_TEXT_WORDS = 500
_USER_AGENT = "Mozilla/5.0 (compatible; OrbisBot/1.0; +https://orbisapp.co)"


def _cache_key(url: str) -> str:
    """Deterministic cache key for a URL."""
    h = hashlib.sha256(url.encode()).hexdigest()[:16]
    return f"scrape:{h}"


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
        logger.info("Cache hit for %s", url)
        return cached

    result: dict[str, Any] = {"url": url, "title": "", "text": "", "quality": "failed"}

    try:
        async with httpx.AsyncClient(
            follow_redirects=True,
            timeout=_FETCH_TIMEOUT,
            headers={"User-Agent": _USER_AGENT},
        ) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            html = resp.text
    except Exception as exc:
        logger.warning("Failed to fetch %s: %s", url, exc)
        return result

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
        url,
        len(result.get("text", "")),
    )
    return result
