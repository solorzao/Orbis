"""The board's routes (/api/board/resolve, /links, /analyze), with the service stubbed.

The service is tested in tests/test_board.py and its SQL in tests/test_board_db.py.
"""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
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


# --- /api/board/links -------------------------------------------------------------


def _link(a: str, b: str):
    from app.models.links import Link
    from app.services.country_centroids import centroid

    def end(iso):
        point = centroid(iso)
        return {"iso": iso, "name": point.name, "lat": point.lat, "lng": point.lng}

    return Link.model_validate(
        {
            "a": end(a),
            "b": end(b),
            "n": 9,
            "lift": 3.1,
            "topic": "politics",
            "tone": -0.2,
            "from": a,
            "outlets": 5,
            "top_exclusive_share": 0.1,
        }
    )


def _edge(a, b, kind, label):
    return {"a": a, "b": b, "kind": kind, "label": label}


def _key(*ids: str) -> str:
    import hashlib

    return "db:board:links:v1:" + hashlib.sha256("\n".join(sorted(ids)).encode()).hexdigest()


# Computed over the items in id order: "article:..." < "place:..." < "thread:...".
SORTED_EDGES = [
    _edge(ARTICLE, "thread:7", "same_thread", "same thread"),
    _edge(ARTICLE, "thread:7", "shared_entity", "shared: Ann Lee"),
    _edge("place:6:3", "thread:7", "co_covered", "covered together: France and Nigeria"),
    _edge(ARTICLE, "place:6:3", "same_place", "same place"),
]


@pytest.fixture
def links(monkeypatch):
    import app.routers.board as board_router

    monkeypatch.setattr(board_router, "_now", lambda: NOW)
    with (
        patch("app.routers.board.board_edges", AsyncMock(return_value=SORTED_EDGES)) as edges,
        patch(
            "app.routers.board.cached_links_7d",
            AsyncMock(return_value=[_link("FR", "NG"), _link("DE", "US")]),
        ) as listed,
        patch("app.routers.board.get_cached", AsyncMock(return_value=None)) as get_cached,
        patch("app.routers.board.set_cached", new_callable=AsyncMock) as set_cached,
    ):
        yield SimpleNamespace(
            edges=edges, listed=listed, get_cached=get_cached, set_cached=set_cached
        )


BOARD = ["thread:7", "place:6:3", ARTICLE]  # board order


class TestLinks:
    @pytest.mark.asyncio
    async def test_edges_come_back_in_board_order(self, monkeypatch, links):
        resp = await _post(monkeypatch, "/api/board/links", {"items": BOARD})

        assert resp.status_code == 200
        assert resp.json() == {
            "edges": [
                # Each edge runs from the earlier pin; edges sort by pins, then kind.
                _edge(
                    "thread:7", "place:6:3", "co_covered", "covered together: France and Nigeria"
                ),
                _edge("thread:7", ARTICLE, "same_thread", "same thread"),
                _edge("thread:7", ARTICLE, "shared_entity", "shared: Ann Lee"),
                _edge("place:6:3", ARTICLE, "same_place", "same place"),
            ],
            "co_coverage_checked": True,
        }

    @pytest.mark.asyncio
    async def test_computed_over_the_items_in_id_order_with_the_listed_pairs(
        self, monkeypatch, links
    ):
        await _post(monkeypatch, "/api/board/links", {"items": BOARD})

        [items, listed, now] = links.edges.await_args.args
        assert [i.id for i in items] == sorted(BOARD)
        assert listed == {frozenset({"FR", "NG"}), frozenset({"DE", "US"})}
        assert now == NOW

    @pytest.mark.asyncio
    async def test_cached_for_ten_minutes_by_the_sorted_item_set(self, monkeypatch, links):
        await _post(monkeypatch, "/api/board/links", {"items": BOARD})
        await _post(monkeypatch, "/api/board/links", {"items": list(reversed(BOARD))})

        keys = [c.args[0] for c in links.get_cached.await_args_list]
        assert keys == [_key(*BOARD)] * 2
        key, value, ttl = links.set_cached.await_args.args
        assert (key, value, ttl) == (_key(*BOARD), {"edges": SORTED_EDGES}, 600)

    @pytest.mark.asyncio
    async def test_a_cached_answer_reads_nothing_and_keeps_board_order(self, monkeypatch, links):
        links.get_cached.return_value = {"edges": SORTED_EDGES}

        resp = await _post(monkeypatch, "/api/board/links", {"items": list(reversed(BOARD))})

        links.edges.assert_not_awaited()
        links.listed.assert_not_awaited()
        assert resp.json()["edges"][0] == _edge(ARTICLE, "place:6:3", "same_place", "same place")
        assert resp.json()["co_coverage_checked"] is True

    @pytest.mark.asyncio
    async def test_without_the_cached_7_day_links_co_coverage_is_skipped_and_nothing_cached(
        self, monkeypatch, links
    ):
        links.listed.return_value = None
        links.edges.return_value = SORTED_EDGES[:2]

        resp = await _post(monkeypatch, "/api/board/links", {"items": BOARD})

        assert links.edges.await_args.args[1] is None
        assert resp.json()["co_coverage_checked"] is False
        assert len(resp.json()["edges"]) == 2
        links.set_cached.assert_not_awaited()

    @pytest.mark.asyncio
    @pytest.mark.parametrize("body", MALFORMED)
    async def test_a_malformed_request_is_a_422_and_reads_nothing(self, monkeypatch, links, body):
        resp = await _post(monkeypatch, "/api/board/links", body)

        assert resp.status_code == 422
        links.get_cached.assert_not_awaited()
        links.edges.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_a_database_error_is_a_500_and_nothing_is_cached(self, monkeypatch, links):
        links.edges.side_effect = RuntimeError("connection reset")

        resp = await _post(monkeypatch, "/api/board/links", {"items": BOARD})

        assert resp.status_code == 500
        links.set_cached.assert_not_awaited()


# --- /api/board/analyze -----------------------------------------------------------

MEMO = {
    "sections": [
        {"heading": "Possible connections", "text": "The strikes [1] may be the thread [2]."},
        {"heading": "Contradictions", "text": "None apparent [1]."},
        {"heading": "Open questions", "text": "It is unclear whether [2] continues."},
    ],
    "citations": [{"n": 1, "item": ARTICLE}, {"n": 2, "item": "thread:7"}],
    "message": None,
}


@pytest.fixture
def analyze(monkeypatch):
    import app.routers.board as board_router

    monkeypatch.setattr(board_router, "_now", lambda: NOW)
    with patch("app.routers.board.analyze_board", AsyncMock(return_value=MEMO)) as mock:
        yield mock


class TestAnalyze:
    @pytest.mark.asyncio
    async def test_the_memo_with_its_sections_and_citations(self, monkeypatch, analyze):
        body = {"items": [{"item": ARTICLE}, {"item": "thread:7", "snapshot": None}]}

        resp = await _post(monkeypatch, "/api/board/analyze", body)

        assert resp.status_code == 200
        assert resp.json() == MEMO
        [items, saved, now] = analyze.await_args.args
        assert [i.id for i in items] == [ARTICLE, "thread:7"]
        assert saved == [None, None]
        assert now == NOW

    @pytest.mark.asyncio
    async def test_a_message_instead_of_a_memo(self, monkeypatch, analyze):
        paused = "AI summaries are paused until 00:00 UTC (daily limit reached)."
        analyze.return_value = {"sections": [], "citations": [], "message": paused}

        resp = await _post(
            monkeypatch, "/api/board/analyze", {"items": [{"item": ARTICLE}, {"item": "thread:7"}]}
        )

        assert resp.status_code == 200
        assert resp.json() == {"sections": [], "citations": [], "message": paused}

    @pytest.mark.asyncio
    async def test_saved_snapshots_pass_their_title_place_and_time_only(self, monkeypatch, analyze):
        snapshot = {**SNAPSHOT_JSON, "extra": "ignored"}  # as resolve gave it, and more

        await _post(
            monkeypatch,
            "/api/board/analyze",
            {"items": [{"item": "thread:7"}, {"item": ARTICLE, "snapshot": snapshot}]},
        )

        [_, saved, _] = analyze.await_args.args
        assert saved == [
            None,
            {
                "title": "Strikes spread across France",
                "place": "Paris, France",
                "time": datetime(2026, 10, 20, 9, tzinfo=timezone.utc),
            },
        ]

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "body",
        [
            {},
            {"items": []},
            {"items": ["thread:7", "thread:8"]},  # items are objects here
            {"items": [{"item": "thread:07"}]},
            {"items": [{"item": "thread:7"}, {"item": "thread:7"}]},
            {"items": [{"item": f"thread:{n}"} for n in range(1, 22)]},
            {"items": [{"item": "thread:7", "snapshot": {"place": "Paris"}}]},
            {"items": [{"item": "thread:7", "snapshot": {"title": "x" * 501}}]},
            {"items": [{"item": "thread:7", "snapshot": {"title": "x", "place": "y" * 201}}]},
            {"items": [{"item": "thread:7", "snapshot": {"title": "x", "time": "soon"}}]},
        ],
    )
    async def test_a_malformed_request_is_a_422_and_calls_no_one(self, monkeypatch, analyze, body):
        resp = await _post(monkeypatch, "/api/board/analyze", body)

        assert resp.status_code == 422
        analyze.assert_not_awaited()
