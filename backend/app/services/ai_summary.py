"""AI-powered cluster summarisation using Claude Haiku."""

from __future__ import annotations

import logging

import anthropic

from app.config import settings
from app.models.news import NewsArticle
from app.services.cache import get_cached, set_cached

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = (
    "You are a concise news analyst providing briefings for a globe news app. "
    "You will receive a location and a list of headlines. Prioritize stories "
    "that relate to or near the given location, but include nearby or related "
    "regional stories too — be generous with relevance. Write a 2-3 sentence "
    "plain-text briefing. Focus on what happened, who's involved, and why it "
    "matters. Output ONLY plain sentences — no markdown, no headings, no bold, "
    "no bullet points, no labels. Never explain your reasoning or mention "
    "which stories you excluded. If nothing seems relevant, just briefly "
    'summarize the headlines you have. Respond with exactly "NONE" (and '
    "nothing else) only if the headlines are completely unrelated gibberish."
)


async def summarise_cluster(
    articles: list[NewsArticle],
    lat: float,
    lng: float,
    location_name: str | None = None,
    topic: str | None = None,
) -> str:
    """Generate a 2-3 sentence summary for a cluster of articles.

    Uses Claude Haiku via the Anthropic SDK.  Results are cached in Redis
    for ``settings.summary_cache_ttl`` seconds, keyed by grid cell and
    topic so that different topic filters get separate summaries.
    """
    if not articles:
        return ""

    # Snap to the same grid used for clustering → stable cache key.
    cell_lat = int(lat // settings.cluster_resolution_deg)
    cell_lng = int(lng // settings.cluster_resolution_deg)
    topic_suffix = f":{topic}" if topic else ""
    cache_key = f"summary:{cell_lat}:{cell_lng}{topic_suffix}"

    cached = await get_cached(cache_key)
    if cached is not None:
        return str(cached)

    # Compose the user message with location context.
    location = location_name or f"{lat:.1f}°, {lng:.1f}°"
    lines = [f"- {a.title} ({a.source_name})" for a in articles[:30]]
    user_msg = f"Location: {location}\n\nHeadlines:\n" + "\n".join(lines)

    summary = await _call_claude(user_msg, system=_SYSTEM_PROMPT)

    # Model returns "NONE" when headlines are completely irrelevant
    if summary.strip().upper() == "NONE":
        summary = ""

    await set_cached(cache_key, summary, settings.summary_cache_ttl)
    return summary


_SELECTION_SYSTEM_PROMPT = (
    "You are a concise news analyst providing briefings for a globe news app. "
    "You will receive a set of headlines the user has filtered to. Write a 2-3 "
    "sentence plain-text briefing summarizing the common themes, key events, "
    "and why they matter. Output ONLY plain sentences — no markdown, no "
    "headings, no bold, no bullet points, no labels. Never explain your "
    "reasoning or mention which stories you excluded."
)


async def summarise_selection(
    headlines: list[str],
    location_name: str | None = None,
) -> str:
    """Generate a 2-3 sentence summary for a user-selected set of headlines."""
    if not headlines:
        return ""

    location = f"Location: {location_name}\n\n" if location_name else ""
    lines = [f"- {h}" for h in headlines[:10]]
    user_msg = f"{location}Headlines:\n" + "\n".join(lines)

    client_msg = await _call_claude(user_msg, system=_SELECTION_SYSTEM_PROMPT)

    if client_msg.strip().upper() == "NONE":
        return ""
    return client_msg


async def _call_claude(user_message: str, system: str | None = None) -> str:
    """Call the Anthropic messages API.  Returns the text response."""
    if not settings.anthropic_api_key:
        logger.warning("ANTHROPIC_API_KEY not set — returning placeholder summary.")
        return "AI summary unavailable (API key not configured)."

    try:
        client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
        response = await client.messages.create(
            model=settings.haiku_model_id,
            max_tokens=256,
            system=system or _SYSTEM_PROMPT,
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
