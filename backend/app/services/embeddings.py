"""OpenAI embedding generation for articles.

Generates text-embedding-3-small vectors for article titles and stores
them in the ``embedding`` column (VECTOR(1536)) of the articles table.
"""

from __future__ import annotations

import logging
from typing import Any

from app.config import settings
from app.services.database import get_pool

logger = logging.getLogger("orbis.embeddings")


def _get_openai_client() -> Any | None:
    """Return an AsyncOpenAI client, or None if unavailable."""
    if not settings.openai_api_key:
        return None
    try:
        from openai import AsyncOpenAI

        return AsyncOpenAI(api_key=settings.openai_api_key)
    except ImportError:
        logger.warning("openai package not installed — skipping embeddings.")
        return None


async def generate_embeddings() -> int:
    """Embed the backlog of articles that lack a vector and store results in PostgreSQL.

    Works through the backlog in batches of ``embedding_batch_size``, newest
    first, until none are left or ``embedding_max_per_cycle`` articles have
    been embedded in this call.

    Returns the number of articles successfully embedded.
    """
    client = _get_openai_client()
    if client is None:
        return 0

    total = 0
    try:
        pool = await get_pool()
        while total < settings.embedding_max_per_cycle:
            rows = await pool.fetch(
                "SELECT id, title FROM articles "
                "WHERE embedding IS NULL "
                "ORDER BY ingested_at DESC "
                "LIMIT $1",
                settings.embedding_batch_size,
            )
            if not rows:
                break
            response = await client.embeddings.create(
                model=settings.embedding_model,
                input=[r["title"] for r in rows],
            )
            updates: list[tuple[str, Any]] = [
                ("[" + ",".join(str(v) for v in emb.embedding) + "]", row["id"])
                for row, emb in zip(rows, response.data)
            ]
            await pool.executemany(
                "UPDATE articles SET embedding = $1::vector WHERE id = $2",
                updates,
            )
            total += len(updates)
        if total:
            logger.info("Generated embeddings for %d articles.", total)
        return total
    except Exception:
        logger.error("Embedding generation failed after %d articles.", total, exc_info=True)
        return total
