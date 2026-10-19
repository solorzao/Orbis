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

        # A short timeout so a hung call can't stall the ingestion cycle (default is 600 s).
        return AsyncOpenAI(api_key=settings.openai_api_key, timeout=30.0)
    except ImportError:
        logger.warning("openai package not installed — skipping embeddings.")
        return None


async def generate_embeddings() -> list[Any]:
    """Embed the backlog of articles that lack a vector and store results in PostgreSQL.

    Fetches up to ``embedding_max_per_cycle`` unembedded articles, newest
    first, in a single query, then embeds them in batches of
    ``embedding_batch_size``. A batch OpenAI rejects as a bad request is
    skipped; any other error stops the run.

    Returns the ids of the articles it embedded, in the order embedded (the
    ingestion cycle assigns them to story threads).
    """
    client = _get_openai_client()
    if client is None:
        return []

    from openai import BadRequestError

    embedded: list[Any] = []
    try:
        pool = await get_pool()
        rows = await pool.fetch(
            "SELECT id, title FROM articles "
            "WHERE embedding IS NULL "
            "ORDER BY ingested_at DESC "
            "LIMIT $1",
            settings.embedding_max_per_cycle,
        )
        size = settings.embedding_batch_size
        for start in range(0, len(rows), size):
            chunk = rows[start : start + size]
            try:
                response = await client.embeddings.create(
                    model=settings.embedding_model,
                    input=[r["title"] for r in chunk],
                )
                # %.9g round-trips float32 exactly and is cheaper than str().
                updates: list[tuple[str, Any]] = [
                    ("[" + ",".join("%.9g" % v for v in emb.embedding) + "]", row["id"])
                    for row, emb in zip(chunk, response.data)
                ]
                # A response with no vectors leaves nothing to write.
                if updates:
                    await pool.executemany(
                        "UPDATE articles SET embedding = $1::vector WHERE id = $2",
                        updates,
                    )
                    embedded.extend(article_id for _, article_id in updates)
            except BadRequestError as exc:
                logger.warning(
                    "OpenAI rejected a batch of %d titles; skipping it: %s", len(chunk), exc
                )
        if embedded:
            logger.info("Generated embeddings for %d articles.", len(embedded))
        return embedded
    except Exception:
        logger.error("Embedding generation failed after %d articles.", len(embedded), exc_info=True)
        return embedded
