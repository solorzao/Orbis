"""AI-powered cluster summarisation using Claude Haiku."""

from __future__ import annotations

import logging

import anthropic

from app.config import settings
from app.middleware.security import has_injection_pattern, sanitise_text
from app.models.news import NewsArticle
from app.services import llm_budget
from app.services.cache import get_cached, set_cached
from app.services.llm import response_text

logger = logging.getLogger(__name__)


class SummaryUnavailable(Exception):
    """Claude produced no summary; the message is the text to show instead.

    That text must never be cached: Claude may be back long before the TTL ends.
    """


_SYSTEM_PROMPT = (
    "You are a concise news analyst. You will receive a location and a list "
    "of headlines. Prioritize stories that relate to or near the given "
    "location, but include nearby or related regional stories too — be "
    "generous with relevance. Write a 2-3 sentence objective, third-person "
    "summary of the events. Focus on what happened, who is involved, and why "
    "it matters. Do not address the reader or use phrases like 'your area' or "
    "'your feed'. Do not reference news sources, media outlets, or where the "
    "information comes from. Output ONLY plain sentences — no markdown, no "
    "headings, no bold, no bullet points, no labels. Never explain your "
    "reasoning or mention which stories you excluded. If nothing seems "
    "relevant, just briefly summarize the headlines you have. Respond with "
    'exactly "NONE" (and nothing else) only if the headlines are completely '
    "unrelated gibberish."
)


def _clean_place(name: str | None) -> str:
    """A place name safe to put in a prompt: one line, no injection phrases."""
    if not name:
        return ""
    candidate = " ".join(sanitise_text(name, max_length=100).split())
    return "" if has_injection_pattern(candidate) else candidate


def _cell_place(articles: list[NewsArticle]) -> str:
    """The cell's place name, taken from its articles the way the globe does.

    Resolved server-side so a client cannot steer a summary that is cached
    and shown to every visitor of the cell.
    """
    for article in articles:
        place = _clean_place(article.region)
        if place:
            return place
    return ""


async def summarise_cluster(
    articles: list[NewsArticle],
    lat: float,
    lng: float,
    topic: str | None = None,
) -> str:
    """Generate a 2-3 sentence summary for a cluster of articles.

    Uses Claude Haiku via the Anthropic SDK.  Results are cached in Redis
    for ``settings.summary_cache_ttl`` seconds, keyed by grid cell and
    topic so that different topic filters get separate summaries. Every
    prompt input derives from the cell's articles, so the key is complete.
    """
    if not articles:
        return ""

    # Snap to the same grid used for clustering → stable cache key.
    cell_lat = int(lat // settings.cluster_resolution_deg)
    cell_lng = int(lng // settings.cluster_resolution_deg)
    topic_suffix = f":{topic}" if topic else ""
    # v2: Haiku 5.5 prompt without raw coordinates (older entries narrate them)
    cache_key = f"summary:v2:{cell_lat}:{cell_lng}{topic_suffix}"

    cached = await get_cached(cache_key)
    if cached is not None:
        return str(cached)

    # Name the place when we know it. Never send raw coordinates: Haiku 5.5
    # narrates working out where they are instead of summarising.
    location = _cell_place(articles)
    lines = [
        f"- {sanitise_text(a.title, max_length=200)}"
        f" ({sanitise_text(a.source_name, max_length=50)})"
        for a in articles[:30]
        if not has_injection_pattern(a.title)
    ]
    if not lines:
        return ""
    header = f"Location: {location}\n\n" if location else ""
    user_msg = header + "Headlines:\n" + "\n".join(lines)

    try:
        summary = await _call_claude(user_msg, system=_SYSTEM_PROMPT)
    except SummaryUnavailable as exc:
        return str(exc)

    # Model returns "NONE" when headlines are completely irrelevant
    if summary.strip().upper() == "NONE":
        summary = ""

    await set_cached(cache_key, summary, settings.summary_cache_ttl)
    return summary


_SELECTION_SYSTEM_PROMPT = (
    "You are a concise news analyst. You will receive a set of headlines. "
    "Write a 2-3 sentence objective, third-person summary of the common "
    "themes and key events. Focus on what happened and why it matters. Do not "
    "address the reader or use phrases like 'your selection' or 'your feed'. "
    "Do not reference news sources, media outlets, or where the information "
    "comes from. Output ONLY plain sentences — no markdown, no headings, no "
    "bold, no bullet points, no labels. Never explain your reasoning or "
    "mention which stories you excluded."
)


async def summarise_selection(
    headlines: list[str],
    location_name: str | None = None,
) -> str:
    """Generate a 2-3 sentence summary for a user-selected set of headlines."""
    if not headlines:
        return ""

    place = _clean_place(location_name)
    location = f"Location: {place}\n\n" if place else ""
    clean = [
        sanitise_text(h, max_length=200) for h in headlines[:10] if not has_injection_pattern(h)
    ]
    if not clean:
        return ""
    lines = [f"- {h}" for h in clean]
    user_msg = f"{location}Headlines:\n" + "\n".join(lines)

    try:
        client_msg = await _call_claude(user_msg, system=_SELECTION_SYSTEM_PROMPT)
    except SummaryUnavailable as exc:
        return str(exc)

    if client_msg.strip().upper() == "NONE":
        return ""
    return client_msg


async def _call_claude(user_message: str, system: str | None = None) -> str:
    """Call the Anthropic messages API.  Returns the text response.

    Raises ``SummaryUnavailable`` when there is no summary to return.
    """
    if not settings.anthropic_api_key:
        logger.warning("ANTHROPIC_API_KEY not set — returning placeholder summary.")
        raise SummaryUnavailable("AI summary unavailable (API key not configured).")

    try:
        if not await llm_budget.has_budget():
            raise llm_budget.LLMBudgetExceeded()
        client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
        response = await client.messages.create(
            model=settings.haiku_model_id,
            max_tokens=1024,  # room for adaptive thinking plus the short summary
            output_config={"effort": "low"},
            system=system or _SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_message}],
        )
        await llm_budget.record(response.usage)  # before response_text: refusals cost too
        return response_text(response).strip()
    except llm_budget.LLMBudgetExceeded:
        logger.warning("Daily Claude budget spent — returning fallback.")
        raise SummaryUnavailable("AI summaries are paused until tomorrow (daily limit reached).")
    except anthropic.RateLimitError:
        logger.warning("Anthropic rate-limited — returning fallback.")
        raise SummaryUnavailable("Summary temporarily unavailable due to rate limits.")
    except Exception:
        logger.error("Anthropic API call failed.", exc_info=True)
        raise SummaryUnavailable("Summary generation failed.")
