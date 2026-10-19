"""Tests for the OpenAI embedding generation service."""

import uuid
from contextlib import ExitStack
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import openai
import pytest


def _fake_embedding(dim: int = 1536) -> list[float]:
    """Return a deterministic fake embedding vector."""
    return [0.01 * (i % 100) for i in range(dim)]


def _rows(n: int) -> list[dict]:
    """Return ``n`` fake article rows."""
    return [{"id": uuid.uuid4(), "title": f"Headline {i}"} for i in range(n)]


def _pool(rows: list[dict]) -> AsyncMock:
    """Return a mock pool whose ``fetch`` returns ``rows``."""
    pool = AsyncMock()
    pool.fetch = AsyncMock(return_value=rows)
    pool.executemany = AsyncMock()
    return pool


def _response(n: int, embedding: list[float] | None = None) -> MagicMock:
    """Return a mock OpenAI embeddings response holding ``n`` vectors."""
    emb = MagicMock()
    emb.embedding = embedding if embedding is not None else _fake_embedding()
    response = MagicMock()
    response.data = [emb] * n
    return response


def _client(**create_kwargs) -> AsyncMock:
    """Return a mock OpenAI client; by default ``create`` returns one vector per input."""
    if not create_kwargs:
        create_kwargs = {"side_effect": lambda **kw: _response(len(kw["input"]))}
    client = AsyncMock()
    client.embeddings.create = AsyncMock(**create_kwargs)
    return client


def _bad_request() -> openai.BadRequestError:
    return openai.BadRequestError(
        "Invalid input",
        response=httpx.Response(400, request=httpx.Request("POST", "https://x")),
        body=None,
    )


async def _run(client: AsyncMock, pool: AsyncMock, **settings_overrides) -> list:
    """Run ``generate_embeddings`` against mocks, with optional settings overrides."""
    from app.config import settings
    from app.services.embeddings import generate_embeddings

    with ExitStack() as stack:
        stack.enter_context(
            patch("app.services.embeddings._get_openai_client", return_value=client)
        )
        stack.enter_context(
            patch("app.services.embeddings.get_pool", new_callable=AsyncMock, return_value=pool)
        )
        for name, value in settings_overrides.items():
            stack.enter_context(patch.object(settings, name, value))
        return await generate_embeddings()


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

        with (
            patch(
                "app.services.embeddings._get_openai_client",
                return_value=mock_client,
            ),
            patch(
                "app.services.embeddings.get_pool",
                new_callable=AsyncMock,
                return_value=mock_pool,
            ),
        ):
            ids = await generate_embeddings()

        assert ids == article_ids  # the ids it embedded, for thread assignment
        mock_client.embeddings.create.assert_called_once()
        call_kwargs = mock_client.embeddings.create.call_args
        assert call_kwargs.kwargs["input"] == [
            "Breaking news headline",
            "Another headline here",
        ]
        mock_pool.executemany.assert_called_once()

    @pytest.mark.asyncio
    async def test_generate_embeddings_embeds_fetched_backlog_in_batches(self):
        rows = _rows(4)
        pool = _pool(rows)
        client = _client()

        ids = await _run(client, pool, embedding_batch_size=2)

        assert ids == [r["id"] for r in rows]
        pool.fetch.assert_awaited_once()
        assert client.embeddings.create.await_count == 2
        written = [u[1] for call in pool.executemany.await_args_list for u in call.args[1]]
        assert written == [r["id"] for r in rows]

    @pytest.mark.asyncio
    async def test_generate_embeddings_fetches_once_up_to_the_cycle_cap(self):
        pool = _pool(_rows(5))
        client = _client()

        ids = await _run(client, pool, embedding_max_per_cycle=5, embedding_batch_size=2)

        assert len(ids) == 5
        pool.fetch.assert_awaited_once()
        assert pool.fetch.await_args.args[1] == 5
        sizes = [len(call.kwargs["input"]) for call in client.embeddings.create.await_args_list]
        assert sizes == [2, 2, 1]

    @pytest.mark.asyncio
    async def test_generate_embeddings_writes_nothing_when_response_has_no_vectors(self):
        pool = _pool(_rows(2))
        client = _client(return_value=_response(0))

        ids = await _run(client, pool)

        assert ids == []
        client.embeddings.create.assert_awaited_once()
        pool.executemany.assert_not_called()

    @pytest.mark.asyncio
    async def test_generate_embeddings_returns_the_ids_embedded_before_an_unexpected_error(self):
        rows = _rows(6)
        pool = _pool(rows)
        client = _client(side_effect=[_response(2), RuntimeError("boom"), _response(2)])

        ids = await _run(client, pool, embedding_batch_size=2)

        # The error in the middle chunk stops the run; the last chunk is never sent.
        assert ids == [r["id"] for r in rows[:2]]
        assert client.embeddings.create.await_count == 2
        pool.executemany.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_generate_embeddings_skips_a_batch_openai_rejects(self):
        rows = _rows(4)
        pool = _pool(rows)
        client = _client(side_effect=[_bad_request(), _response(2)])

        ids = await _run(client, pool, embedding_batch_size=2)

        assert ids == [r["id"] for r in rows[2:]]
        pool.executemany.assert_awaited_once()
        written = [u[1] for u in pool.executemany.await_args.args[1]]
        assert written == [r["id"] for r in rows[2:]]

    @pytest.mark.asyncio
    async def test_generate_embeddings_formats_vectors_compactly(self):
        rows = _rows(1)
        pool = _pool(rows)
        # 0.10000000149011612 is float32(0.1) widened to a Python float, as the SDK returns it.
        client = _client(return_value=_response(1, embedding=[0.5, 0.25, 0.10000000149011612]))

        await _run(client, pool)

        assert pool.executemany.await_args.args[1] == [("[0.5,0.25,0.100000001]", rows[0]["id"])]

    @pytest.mark.asyncio
    async def test_generate_embeddings_skips_when_no_api_key(self):
        from app.services.embeddings import generate_embeddings

        with patch(
            "app.services.embeddings._get_openai_client",
            return_value=None,
        ):
            ids = await generate_embeddings()

        assert ids == []


class TestGetOpenAIClient:
    def test_client_uses_a_short_timeout(self):
        from app.config import settings
        from app.services.embeddings import _get_openai_client

        with patch.object(settings, "openai_api_key", "test-key"):
            client = _get_openai_client()

        assert client.timeout == 30.0
