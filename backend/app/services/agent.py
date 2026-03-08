"""Two-step agent pipeline: plan retrieval, execute, synthesize answer.

Uses Claude Haiku for lightweight tool-planning and Claude Sonnet for
high-quality answer synthesis with citations and globe actions.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

import anthropic

from app.config import settings
from app.services import retrieval

logger = logging.getLogger("orbis.agent")

# ---------------------------------------------------------------------------
# Tool definitions exposed to the planning LLM
# ---------------------------------------------------------------------------

RETRIEVAL_TOOLS: list[dict] = [
    {
        "name": "semantic_search",
        "description": (
            "Search articles by semantic similarity to a natural-language query. "
            "Best for conceptual or thematic questions."
        ),
        "parameters": {
            "query": {"type": "string", "description": "Natural-language search query"},
            "limit": {"type": "integer", "description": "Max results (default 10)", "default": 10},
        },
    },
    {
        "name": "graph_traverse",
        "description": (
            "Traverse the knowledge graph starting from an entity (person, org, "
            "location). Returns connected entities, their relationship types "
            "(CO_MENTIONED, MENTIONED_IN, LOCATED_AT, ABOUT_TOPIC), and the "
            "source articles that establish those connections. Best for exploring "
            "networks and multi-hop relationships."
        ),
        "parameters": {
            "entity_name": {"type": "string", "description": "Starting entity name"},
            "rel_type": {"type": "string", "description": "Optional relationship type filter", "default": None},
            "depth": {"type": "integer", "description": "Max traversal depth (1-3)", "default": 2},
        },
    },
    {
        "name": "keyword_search",
        "description": (
            "Search articles using keyword and metadata filters. "
            "Supports terms, topic, country code, and time range."
        ),
        "parameters": {
            "terms": {"type": "string", "description": "Keyword(s) to search in titles", "default": None},
            "topic": {"type": "string", "description": "Topic tag filter", "default": None},
            "country": {"type": "string", "description": "Two-letter country code", "default": None},
            "time_range": {"type": "string", "description": "PostgreSQL interval, e.g. '24 hours'", "default": None},
            "limit": {"type": "integer", "description": "Max results (default 10)", "default": 10},
        },
    },
    {
        "name": "trending_topics",
        "description": "Return the top-20 trending topics over a recent time window.",
        "parameters": {
            "hours": {"type": "integer", "description": "Lookback window in hours (default 24)", "default": 24},
        },
    },
    {
        "name": "entity_lookup",
        "description": (
            "Look up a specific person, organization, or location in the "
            "knowledge graph. Returns the entity, its direct connections "
            "(co-mentioned people/orgs, related topics, locations), and the "
            "source articles where this entity appears. Best for answering "
            "'Who is X?' or 'What is X involved in?'"
        ),
        "parameters": {
            "name": {"type": "string", "description": "Entity name to look up"},
        },
    },
]

# Map tool names to actual retrieval functions
_TOOL_DISPATCH: dict[str, Any] = {
    "semantic_search": retrieval.semantic_search,
    "graph_traverse": retrieval.graph_traverse,
    "keyword_search": retrieval.keyword_search,
    "trending_topics": retrieval.trending_topics,
    "entity_lookup": retrieval.entity_lookup,
}

# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

_PLANNING_SYSTEM = (
    "You are a retrieval planner for a news intelligence system called Orbis. "
    "Given a user question, decide which 1-3 retrieval tools to call.\n\n"
    "Available tools:\n{tool_list}\n\n"
    "IMPORTANT guidelines:\n"
    "- For natural language questions, ALWAYS include semantic_search with a "
    "concise rephrased query (not the raw user question).\n"
    "- For keyword_search, extract only key terms (e.g. 'Los Angeles' not "
    "'What happened in Los Angeles today'). Use the country and time_range "
    "params to narrow results.\n"
    "- Prefer combining semantic_search + keyword_search for best coverage.\n"
    "- For questions about RELATIONSHIPS between people, organizations, or "
    "countries (e.g. 'How is X connected to Y?', 'Who is involved with Z?', "
    "'What organizations are linked to…'), use entity_lookup or graph_traverse "
    "to explore the knowledge graph. Combine with semantic_search for context.\n"
    "- Use entity_lookup when the question names a specific person or "
    "organization and you want their connections.\n"
    "- Use graph_traverse when you want to explore broader relationship "
    "networks (e.g. all entities connected to a person, multi-hop links).\n"
    "- For questions about patterns, networks, or recurring actors across "
    "stories, graph tools are essential.\n\n"
    "If the question is NOT about news, world events, geopolitics, or current "
    "affairs, respond with: {{\"tools\": [], \"off_topic\": true}}\n\n"
    "Otherwise respond with ONLY valid JSON: {{\"tools\": [{{\"name\": \"...\", \"args\": {{...}}}}]}}\n"
    "Do not include any other text."
)

_SYNTHESIS_SYSTEM = (
    "You are an expert news analyst for Orbis, a 3-D globe news explorer. "
    "Answer the user's question using ONLY the retrieved context below. "
    "Cite sources with [N] where N is the numbered entry. "
    "If relevant locations are mentioned, include globe_actions so the UI "
    "can highlight them.\n\n"
    "The context may include a Knowledge Graph section showing entity "
    "relationships (e.g. CO_MENTIONED, MENTIONED_IN). Use this to explain "
    "how people, organizations, and locations are connected. When describing "
    "relationships, cite the numbered articles that establish them.\n\n"
    "If the question is not about news, world events, or current affairs, "
    "politely decline and suggest the user ask about global news instead.\n\n"
    "Respond with ONLY valid JSON:\n"
    '{{"answer": "your answer with [N] citations", '
    '"citations": [{{"index": N, "title": "...", "source_url": "..."}}], '
    '"globe_actions": [{{"lat": 0.0, "lng": 0.0, "label": "..."}}]}}\n\n'
    "If you cannot produce valid JSON, just write the answer as plain text."
)


def _get_anthropic_client() -> anthropic.AsyncAnthropic:
    """Return an async Anthropic client."""
    return anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)


def _build_context(retrieval_results: list[dict], max_articles: int | None = None) -> tuple[str, list[dict]]:
    """Deduplicate and format retrieval results as numbered entries.

    Handles both article results (from semantic/keyword search) and
    graph results (from graph_traverse/entity_lookup).  Graph results
    produce a relationship-map section followed by their linked articles.

    Returns (context_str, article_index) where article_index is a list
    of dicts with full metadata keyed by 1-based citation index.
    """
    if max_articles is None:
        max_articles = settings.agent_max_retrieval_results

    seen_urls: set[str] = set()
    entries: list[str] = []
    article_index: list[dict] = []  # 0-based, maps to [1], [2], etc.
    graph_sections: list[str] = []

    def _add_article(item: dict) -> None:
        """Add an article item to entries and article_index."""
        if len(entries) >= max_articles:
            return
        url = item.get("source_url", "")
        if url and url in seen_urls:
            return
        if url:
            seen_urls.add(url)

        title = item.get("title") or item.get("name") or item.get("topic", "")
        if not title:
            return

        idx = len(entries) + 1
        parts = [f"[{idx}] {title}"]
        if url:
            parts.append(f"  URL: {url}")
        if item.get("source_name"):
            parts.append(f"  Source: {item['source_name']}")
        if item.get("latitude") is not None and item.get("longitude") is not None:
            parts.append(f"  Location: {item['latitude']}, {item['longitude']}")
        if item.get("sentiment_score") is not None:
            parts.append(f"  Sentiment: {item['sentiment_score']}")
        if item.get("count") is not None:
            parts.append(f"  Count: {item['count']}")

        entries.append("\n".join(parts))
        article_index.append({
            "title": title,
            "url": url,
            "source_name": item.get("source_name", ""),
            "lat": item.get("latitude"),
            "lng": item.get("longitude"),
        })

    for result in retrieval_results:
        tool_name = result.get("tool", "")
        data = result.get("result", [])

        # --- Graph tools: format relationship map + linked articles ---
        if tool_name in ("graph_traverse", "entity_lookup") and isinstance(data, dict):
            entity = data.get("entity") or data.get("node")
            connections = data.get("connections", [])
            articles = data.get("articles", [])

            if entity:
                entity_name = entity.get("name", "?")
                entity_type = entity.get("type", "?")
                lines = [f"=== Knowledge Graph: {entity_name} ({entity_type}) ==="]

                # Group connections by relationship type
                by_rel: dict[str, list[str]] = {}
                for conn in connections:
                    rel = conn.get("rel_type", "RELATED")
                    label = f"{conn.get('name', '?')} ({conn.get('type', '?')})"
                    weight = conn.get("weight")
                    if weight and weight > 1:
                        label += f" [x{weight}]"
                    by_rel.setdefault(rel, []).append(label)

                for rel, names in by_rel.items():
                    lines.append(f"  {rel}: {', '.join(names[:10])}")

                graph_sections.append("\n".join(lines))

            # Add linked articles as citable entries
            for art in articles:
                _add_article(art)

            continue

        # --- Standard list results (semantic/keyword/trending) ---
        if isinstance(data, list):
            for item in data:
                _add_article(item)
                if len(entries) >= max_articles:
                    break

    # Combine graph relationship map + numbered article entries
    parts = []
    if graph_sections:
        parts.append("\n\n".join(graph_sections))
    if entries:
        parts.append("\n\n".join(entries))

    context = "\n\n".join(parts) if parts else "(No results found.)"
    logger.info("Built context with %d entries, %d graph sections (%d chars)",
                len(entries), len(graph_sections), len(context))
    return context, article_index


def _enrich_citations(raw_citations: list, article_index: list[dict]) -> list[dict]:
    """Map LLM-generated citations back to full article metadata."""
    enriched = []
    for c in raw_citations:
        idx = c.get("index", 0)
        if 1 <= idx <= len(article_index):
            article = article_index[idx - 1]
            enriched.append({
                "title": article["title"],
                "url": article["url"],
                "source_name": article["source_name"],
                "lat": article.get("lat") or 0,
                "lng": article.get("lng") or 0,
            })
        else:
            # Fallback: use whatever the LLM provided
            enriched.append({
                "title": c.get("title", ""),
                "url": c.get("source_url", c.get("url", "")),
                "source_name": c.get("source_name", ""),
                "lat": c.get("lat", 0),
                "lng": c.get("lng", 0),
            })
    return enriched


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def plan_retrieval(
    question: str,
    conversation_history: list[dict] | None = None,
) -> list[dict]:
    """Use Haiku to decide which retrieval tools to call.

    Returns a list of ``{"name": str, "args": dict}`` dicts (1-3 tools).
    """
    tool_desc = "\n".join(
        f"- {t['name']}: {t['description']} (params: {list(t['parameters'].keys())})"
        for t in RETRIEVAL_TOOLS
    )
    system = _PLANNING_SYSTEM.format(tool_list=tool_desc)

    messages: list[dict] = []
    if conversation_history:
        messages.extend(conversation_history[-6:])
    messages.append({"role": "user", "content": question})

    try:
        client = _get_anthropic_client()
        response = await client.messages.create(
            model=settings.haiku_model_id,
            max_tokens=512,
            system=system,
            messages=messages,
        )
        text = response.content[0].text.strip()
        logger.info("Planner raw response: %s", text[:500])
        # Strip markdown code fences the model sometimes wraps around JSON
        if text.startswith("```"):
            text = text.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
        parsed = json.loads(text)
        # Off-topic detection: planner explicitly flags non-news questions
        if parsed.get("off_topic"):
            return []
        tools = parsed.get("tools", [])
        if not tools:
            raise ValueError("Empty tools list")
        # Validate tool names
        valid = [t for t in tools if t.get("name") in _TOOL_DISPATCH]
        logger.info("Planned tools: %s", [t["name"] for t in valid])
        return valid[:3] if valid else _fallback(question)
    except Exception:
        logger.warning("Plan retrieval failed -- falling back to keyword search.", exc_info=True)
        return _fallback(question)


_OFF_TOPIC_ANSWER = (
    "I'm designed to help with news and world events. "
    "Try asking about something happening in the world — "
    "conflicts, politics, economics, natural disasters, and more."
)


_STOP_WORDS = {
    "what", "when", "where", "who", "why", "how", "is", "are", "was", "were",
    "do", "does", "did", "has", "have", "had", "the", "a", "an", "in", "on",
    "at", "to", "for", "of", "with", "about", "from", "by", "up", "it",
    "and", "or", "but", "not", "this", "that", "there", "happened", "today",
    "tell", "me", "can", "you", "any", "some", "been", "going", "latest",
    "recent", "news", "currently", "happening",
}


def _extract_keywords(question: str) -> str:
    """Extract meaningful keywords from a question for fallback search."""
    words = [w for w in question.split() if w.lower().strip("?,!.") not in _STOP_WORDS]
    return " ".join(w.strip("?,!.") for w in words)[:200]


def _fallback(question: str) -> list[dict]:
    terms = _extract_keywords(question)
    return [{"name": "keyword_search", "args": {"terms": terms or question[:50]}}]


_ALLOWED_TIME_RANGES = {
    "1 hour", "6 hours", "12 hours", "24 hours", "48 hours", "7 days",
}


def _sanitize_tool_args(name: str, args: dict) -> dict:
    """Clamp and sanitize LLM-generated tool arguments."""
    clean = {}
    for k, v in args.items():
        if isinstance(v, str):
            clean[k] = v[:200].strip()
        elif isinstance(v, (int, float)):
            clean[k] = v

    if "limit" in clean:
        clean["limit"] = max(1, min(int(clean["limit"]), 20))
    if "depth" in clean:
        clean["depth"] = max(1, min(int(clean["depth"]), 3))
    if "hours" in clean:
        clean["hours"] = max(1, min(int(clean["hours"]), 168))
    if "time_range" in clean and clean["time_range"] not in _ALLOWED_TIME_RANGES:
        clean["time_range"] = "24 hours"

    return clean


async def execute_retrieval(tool_calls: list[dict]) -> list[dict]:
    """Run planned retrieval tool calls in parallel.

    Returns ``[{"tool": name, "result": data}]`` or
    ``{"tool": name, "error": msg}`` on failure.
    """

    async def _run(call: dict) -> dict:
        name = call["name"]
        args = _sanitize_tool_args(name, call.get("args", {}))
        fn = _TOOL_DISPATCH.get(name)
        if fn is None:
            return {"tool": name, "error": f"Unknown tool: {name}"}
        try:
            result = await fn(**args)
            return {"tool": name, "result": result}
        except Exception as exc:
            logger.error("Tool %s failed: %s", name, exc, exc_info=True)
            return {"tool": name, "error": str(exc)}

    results = await asyncio.gather(*[_run(c) for c in tool_calls])
    for r in results:
        data = r.get("result", r.get("error", "?"))
        count = len(data) if isinstance(data, list) else "n/a"
        logger.info("Tool %s returned %s results", r.get("tool"), count)
    return list(results)


async def synthesize_answer(
    question: str,
    context: str,
    conversation_history: list[dict] | None = None,
) -> dict:
    """Use Haiku to produce a cited answer with globe actions.

    Returns ``{"answer": str, "citations": list, "globe_actions": list}``.
    """
    messages: list[dict] = []
    if conversation_history:
        messages.extend(conversation_history[-6:])
    messages.append({
        "role": "user",
        "content": f"Question: {question}\n\nRetrieved context:\n{context}",
    })

    try:
        client = _get_anthropic_client()
        response = await client.messages.create(
            model=settings.haiku_model_id,
            max_tokens=1024,
            system=_SYNTHESIS_SYSTEM,
            messages=messages,
        )
        text = response.content[0].text.strip()
        # Strip markdown code fences the model sometimes adds
        if text.startswith("```"):
            text = text.split("\n", 1)[-1].rsplit("```", 1)[0].strip()

        try:
            parsed = json.loads(text)
            return {
                "answer": parsed.get("answer", text),
                "citations": parsed.get("citations", []),
                "globe_actions": parsed.get("globe_actions", []),
            }
        except json.JSONDecodeError:
            return {"answer": text, "citations": [], "globe_actions": []}
    except Exception:
        logger.error("Synthesis failed.", exc_info=True)
        return {
            "answer": "I'm sorry, I couldn't generate an answer right now.",
            "citations": [],
            "globe_actions": [],
        }


async def ask(
    question: str,
    conversation_history: list[dict] | None = None,
) -> dict:
    """Full agent pipeline: plan -> retrieve -> synthesize.

    Returns ``{"answer": str, "citations": list, "globe_actions": list, "tools_used": list}``.
    """
    # Step 1: Plan
    tool_calls = await plan_retrieval(question, conversation_history)

    # Off-topic: skip retrieval + synthesis entirely (saves 2 API calls)
    if not tool_calls:
        return {
            "answer": _OFF_TOPIC_ANSWER,
            "citations": [],
            "globe_actions": [],
            "tools_used": [],
        }

    # Step 2: Retrieve
    retrieval_results = await execute_retrieval(tool_calls)

    # Step 3: Build context
    context, article_index = _build_context(retrieval_results)

    # Step 4: Synthesize
    result = await synthesize_answer(question, context, conversation_history)
    result["citations"] = _enrich_citations(result.get("citations", []), article_index)
    result["tools_used"] = [tc["name"] for tc in tool_calls]
    return result
