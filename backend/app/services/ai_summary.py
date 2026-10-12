"""AI-powered cluster summarisation using Claude Haiku."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

import anthropic

from app.config import settings
from app.middleware.security import has_injection_pattern, sanitise_text
from app.models.news import NewsArticle
from app.services import llm_budget
from app.services.cache import get_cached, set_cached
from app.services.grid import cell_index
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


def _window_key(start_time: datetime | None, end_time: datetime | None) -> str:
    """The time window as a cache-key part: each bound floored to the hour.

    The frontend's day window shifts by milliseconds between clicks, so exact
    bounds would never hit the cache. ``live`` means no window.
    """
    if start_time is None and end_time is None:
        return "live"

    def hour(dt: datetime | None) -> str:
        return dt.astimezone(timezone.utc).strftime("%Y%m%d%H") if dt else ""

    return f"{hour(start_time)}-{hour(end_time)}"


async def summarise_cluster(
    articles: list[NewsArticle],
    lat: float,
    lng: float,
    topic: str | None = None,
    *,
    cell_size: float,
    start_time: datetime | None = None,
    end_time: datetime | None = None,
) -> str:
    """Generate a 2-3 sentence summary for a cluster of articles.

    Uses Claude Haiku via the Anthropic SDK.  Results are cached in Redis
    for ``settings.summary_cache_ttl`` seconds, keyed by grid cell (of
    *cell_size* degrees, the globe dots' grid), time window and topic, so
    each dot, window and topic filter gets its own summary. Every prompt
    input derives from the cell's articles, so the key is complete.
    """
    if not articles:
        return ""

    # Snap to the dots' grid → one stable cache key per dot.
    cell_lat = cell_index(lat, cell_size)
    cell_lng = cell_index(lng, cell_size)
    window = _window_key(start_time, end_time)
    topic_suffix = f":{topic}" if topic else ""
    # v3: 1° cells and a time window (v2 keys were 2° cells over all time)
    cache_key = f"summary:v3:{cell_lat}:{cell_lng}:{window}{topic_suffix}"

    cached = await get_cached(cache_key)
    if cached is not None:
        return str(cached)

    # Name the place when we know it. Never send raw coordinates: Haiku 5.5
    # narrates working out where they are instead of summarising.
    location = _cell_place(articles)
    lines = []
    for a in articles[:30]:
        title = sanitise_text(a.title, max_length=200)
        line = f"- {title} ({sanitise_text(a.source_name, max_length=50)})"
        # Checked once cleaned: sanitise_text deletes control characters, which
        # would otherwise hide an injection phrase from the check ("Ig\x01nore").
        if not has_injection_pattern(line):
            lines.append(line)
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
    # Checked once cleaned, as in summarise_cluster.
    cleaned = [sanitise_text(h, max_length=200) for h in headlines[:10]]
    clean = [h for h in cleaned if not has_injection_pattern(h)]
    if not clean:
        return ""
    lines = [f"- {h}" for h in clean]
    user_msg = f"{location}Headlines:\n" + "\n".join(lines)

    try:
        client_msg = await _call_claude(
            user_msg, system=_SELECTION_SYSTEM_PROMPT, budget_share=llm_budget.UNCACHED_SHARE
        )
    except SummaryUnavailable as exc:
        return str(exc)

    if client_msg.strip().upper() == "NONE":
        return ""
    return client_msg


async def _call_claude(
    user_message: str, system: str | None = None, budget_share: float = 1.0
) -> str:
    """Call the Anthropic messages API.  Returns the text response.

    ``budget_share`` is the share of the daily cap this call may draw on.
    Raises ``SummaryUnavailable`` when there is no summary to return.
    """
    if not settings.anthropic_api_key:
        logger.warning("ANTHROPIC_API_KEY not set — returning placeholder summary.")
        raise SummaryUnavailable("AI summary unavailable (API key not configured).")

    if not await llm_budget.has_budget(share=budget_share):
        logger.info(
            "%.0f%% of the daily Claude budget is spent — returning fallback.", budget_share * 100
        )
        raise SummaryUnavailable("AI summaries are paused until 00:00 UTC (daily limit reached).")

    try:
        client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
        response = await client.messages.create(
            model=settings.haiku_model_id,
            max_tokens=1024,  # room for adaptive thinking plus the short summary
            output_config={"effort": "low"},
            system=system or _SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_message}],
        )
        # Before response_text: refusals are billed too.
        await llm_budget.record(response.usage, response.model)
        text = response_text(response).strip()
    except anthropic.RateLimitError:
        logger.warning("Anthropic rate-limited — returning fallback.")
        raise SummaryUnavailable("Summary temporarily unavailable due to rate limits.")
    except Exception:
        logger.error("Anthropic API call failed.", exc_info=True)
        raise SummaryUnavailable("Summary generation failed.")

    if response.stop_reason == "max_tokens" or not text:
        logger.warning("No usable summary from Claude (stop_reason=%s).", response.stop_reason)
        raise SummaryUnavailable("Summary generation failed.")
    return text
