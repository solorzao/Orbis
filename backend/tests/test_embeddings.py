"""Tests for the OpenAI embedding generation service."""

import uuid

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


def _fake_embedding(dim: int = 1536) -> list[float]:
    """Return a deterministic fake embedding vector."""
    return [0.01 * (i % 100) for i in range(dim)]


class TestGenerateEmbeddings:
    @pytest.mark.asyncio
    async def test_generate_embeddings_calls_openai(self):
        from app.services.embeddings import generate_embeddings

        article_ids = [uuid.uuid4(), uuid.uuid4()]
        db_rows = [
            {"id": article_ids[0], "title": "Breaking news headline"},
            {"id": article_ids[1], "title": "Another headline here"},
        ]

        mock_pool = AsyncMock()
        mock_pool.fetch = AsyncMock(return_value=db_rows)
        mock_pool.executemany = AsyncMock()

        # Build a mock OpenAI response
        emb_obj_1 = MagicMock()
        emb_obj_1.embedding = _fake_embedding()
        emb_obj_2 = MagicMock()
        emb_obj_2.embedding = _fake_embedding()
        mock_response = MagicMock()
        mock_response.data = [emb_obj_1, emb_obj_2]

        mock_client = AsyncMock()
        mock_client.embeddings.create = AsyncMock(return_value=mock_response)

        with patch(
            "app.services.embeddings._get_openai_client",
            return_value=mock_client,
        ), patch(
            "app.services.embeddings.get_pool",
            new_callable=AsyncMock,
            return_value=mock_pool,
        ):
            count = await generate_embeddings()

        assert count == 2
        mock_client.embeddings.create.assert_called_once()
        call_kwargs = mock_client.embeddings.create.call_args
        assert call_kwargs.kwargs["input"] == [
            "Breaking news headline",
            "Another headline here",
        ]
        mock_pool.executemany.assert_called_once()

    @pytest.mark.asyncio
    async def test_generate_embeddings_skips_when_no_api_key(self):
        from app.services.embeddings import generate_embeddings

        with patch(
            "app.services.embeddings._get_openai_client",
            return_value=None,
        ):
            count = await generate_embeddings()

        assert count == 0
