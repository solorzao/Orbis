"""AI-powered cluster summarisation using Claude Haiku."""

from __future__ import annotations

import logging

import anthropic

from app.config import settings
from app.models.news import NewsArticle
from app.services.cache import get_cached, set_cached

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = (
    "You are a concise news analyst. You will receive a location and a list "
    "of headlines. Some headlines may not actually relate to the given location "
    "— ignore those. Write a 2-3 sentence plain-text briefing covering ONLY "
    "the stories relevant to that specific location. Focus on what happened, "
    "who's involved, and why it matters. Output ONLY plain sentences — no "
    "markdown, no headings, no bold, no bullet points, no labels. Just the "
    "analysis as a short paragraph. If none of the headlines are relevant to "
    "the location, say so briefly."
)


async def summarise_cluster(
    articles: list[NewsArticle],
    lat: float,
    lng: float,
    location_name: str | None = None,
) -> str:
    """Generate a 2-3 sentence summary for a cluster of articles.

    Uses Claude Haiku via the Anthropic SDK.  Results are cached in Redis
    for ``settings.summary_cache_ttl`` seconds, keyed by grid cell so that
    the cache survives GDELT article refreshes.
    """
    if not articles:
        return "No articles to summarise."

    # Snap to the same grid used for clustering → stable cache key.
    cell_lat = int(lat // settings.cluster_resolution_deg)
    cell_lng = int(lng // settings.cluster_resolution_deg)
    cache_key = f"summary:{cell_lat}:{cell_lng}"

    cached = await get_cached(cache_key)
    if cached is not None:
        return str(cached)

    # Compose the user message with location context.
    location = location_name or f"{lat:.1f}°, {lng:.1f}°"
    lines = [f"- {a.title} ({a.source_name})" for a in articles[:30]]
    user_msg = f"Location: {location}\n\nHeadlines:\n" + "\n".join(lines)

    summary = await _call_claude(user_msg)

    await set_cached(cache_key, summary, settings.summary_cache_ttl)
    return summary


async def _call_claude(user_message: str) -> str:
    """Call the Anthropic messages API.  Returns the text response."""
    if not settings.anthropic_api_key:
        logger.warning("ANTHROPIC_API_KEY not set — returning placeholder summary.")
        return "AI summary unavailable (API key not configured)."

    try:
        client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
        response = await client.messages.create(
            model=settings.haiku_model_id,
            max_tokens=256,
            system=_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_message}],
        )
        # Extract the text from the first content block.
        text = response.content[0].text if response.content else ""
        return text.strip()
    except anthropic.RateLimitError:
        logger.warning("Anthropic rate-limited — returning fallback.")
        return "Summary temporarily unavailable due to rate limits."
    except Exception:
        logger.error("Anthropic API call failed.", exc_info=True)
        return "Summary generation failed."
