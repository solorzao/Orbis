"""The board's routes (/api/board/resolve, /links, /analyze), with the service stubbed.

The service is tested in tests/test_board.py and its SQL in tests/test_board_db.py.
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest

NOW = datetime(2026, 10, 20, 12, tzinfo=timezone.utc)
ARTICLE = "article:3f2a6c1e-8b4d-4f0a-9c2e-1d5b7a9e0f13"

SNAPSHOT = {
    "title": "Strikes spread across France",
    "place": "Paris, France",
    "lat": 48.85,
    "lng": 2.35,
    "time": datetime(2026, 10, 20, 9, tzinfo=timezone.utc),
    "url": "https://example.com/strikes",
}
SNAPSHOT_JSON = {**SNAPSHOT, "time": "2026-10-20T09:00:00Z"}


async def _post(monkeypatch, path, body):
    from httpx import ASGITransport, AsyncClient

    from app.main import app
    from app.middleware import security

    monkeypatch.setattr(security.settings, "api_key", "")
    security._rate_buckets.clear()
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.post(path, json=body)


def test_resolve_and_links_are_data_reads_and_analysis_spends_ai_calls():
    from app.middleware.security import _get_rate_group

    assert _get_rate_group("/api/board/resolve") == "data"
    assert _get_rate_group("/api/board/links") == "data"
    assert _get_rate_group("/api/board/analyze") == "ai"


# Each of these is a 422 on every route, before anything is read.
MALFORMED = [
    {},
    {"items": []},
    {"items": "thread:7"},
    {"items": [7]},
    {"items": ["thread:7", "thread:07"]},
    {"items": ["story:7"]},
    {"items": ["thread:7", "thread:7"]},
    {"items": [f"thread:{n}" for n in range(1, 22)]},  # 21: a board holds 20
    {"items": ["entity:person:" + "x" * 300]},
]


class TestResolve:
    @pytest.fixture
    def resolve(self, monkeypatch):
        import app.routers.board as board_router

        monkeypatch.setattr(board_router, "_now", lambda: NOW)
        with patch(
            "app.routers.board.resolve_items", AsyncMock(return_value=[SNAPSHOT, None])
        ) as mock:
            yield mock

    @pytest.mark.asyncio
    async def test_each_item_with_its_snapshot_or_null_in_order(self, monkeypatch, resolve):
        resp = await _post(monkeypatch, "/api/board/resolve", {"items": [ARTICLE, "thread:7"]})

        assert resp.status_code == 200
        assert resp.json() == {
            "items": [
                {"item": ARTICLE, "snapshot": SNAPSHOT_JSON},
                {"item": "thread:7", "snapshot": None},
            ]
        }
        [items, now] = resolve.await_args.args
        assert [i.id for i in items] == [ARTICLE, "thread:7"]
        assert now == NOW

    @pytest.mark.asyncio
    async def test_twenty_items_is_the_most(self, monkeypatch, resolve):
        resolve.return_value = [None] * 20

        resp = await _post(
            monkeypatch,
            "/api/board/resolve",
            {"items": [f"thread:{n}" for n in range(1, 21)]},
        )

        assert resp.status_code == 200
        assert len(resp.json()["items"]) == 20

    @pytest.mark.asyncio
    @pytest.mark.parametrize("body", MALFORMED)
    async def test_a_malformed_request_is_a_422_and_reads_nothing(self, monkeypatch, resolve, body):
        resp = await _post(monkeypatch, "/api/board/resolve", body)

        assert resp.status_code == 422
        resolve.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_the_422_names_the_bad_item_by_index(self, monkeypatch, resolve):
        resp = await _post(monkeypatch, "/api/board/resolve", {"items": ["thread:7", "link:US-FR"]})

        assert resp.status_code == 422
        assert resp.json() == {"detail": "items[1] is not a board item id."}

    @pytest.mark.asyncio
    async def test_is_never_edge_cached(self, monkeypatch, resolve):
        resp = await _post(monkeypatch, "/api/board/resolve", {"items": [ARTICLE, "thread:7"]})

        assert "cache-control" not in resp.headers
