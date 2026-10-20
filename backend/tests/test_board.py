"""The investigation board's service (app.services.board), with the database faked.

Its SQL runs against a real PostgreSQL in tests/test_board_db.py; the routes
are tested in tests/test_board_router.py.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest

from app.services import board

NOW = datetime(2026, 10, 20, 12, tzinfo=timezone.utc)
ARTICLE_ID = "3f2a6c1e-8b4d-4f0a-9c2e-1d5b7a9e0f13"
OTHER_ID = "0b9e2d4c-1a3f-4e5d-8c7b-6a5f4e3d2c1b"


class FakePool:
    """The pool as the board reads it: each SQL constant answers with its rows,
    or with what a function of the call's arguments returns. Records each call."""

    def __init__(self, answers: dict | None = None):
        self.answers = answers or {}
        self.calls: list[tuple[str, tuple]] = []

    async def fetch(self, sql, *args):
        self.calls.append((sql, args))
        answer = self.answers.get(sql, [])
        return answer(*args) if callable(answer) else answer

    def calls_to(self, sql) -> list[tuple]:
        return [args for s, args in self.calls if s == sql]


@pytest.fixture
def pool():
    fake = FakePool()
    with patch("app.services.board.get_pool", AsyncMock(return_value=fake)):
        yield fake


def _items(*raws: str) -> list[board.BoardItem]:
    return [board.parse_item(raw) for raw in raws]


# --- Item ids ---------------------------------------------------------------------


class TestParseItem:
    @pytest.mark.parametrize(
        ("raw", "kind", "key"),
        [
            (f"article:{ARTICLE_ID}", "article", ARTICLE_ID),
            ("place:48:2", "place", (48, 2)),
            ("place:-34:-59", "place", (-34, -59)),
            ("place:0:0", "place", (0, 0)),
            ("place:90:180", "place", (90, 180)),
            ("place:-90:-180", "place", (-90, -180)),
            ("link:FR-US", "link", ("FR", "US")),
            ("thread:7", "thread", 7),
            ("thread:9223372036854775807", "thread", 2**63 - 1),
            ("entity:person:Emmanuel Macron", "entity", ("person", "Emmanuel Macron")),
            ("entity:org:Hamas", "entity", ("org", "Hamas")),
            # A name may hold a colon: only the first two split.
            ("entity:org:Unit: 8200", "entity", ("org", "Unit: 8200")),
        ],
    )
    def test_each_kind_parses_to_its_key(self, raw, kind, key):
        item = board.parse_item(raw)

        assert (item.id, item.kind, item.key) == (raw, kind, key)

    @pytest.mark.parametrize(
        "raw",
        [
            "",
            "article:",
            f"article:{ARTICLE_ID.upper()}",  # one spelling: lowercase, as the API gives ids
            f"article:{ARTICLE_ID.replace('-', '')}",
            f"article:{ARTICLE_ID}x",
            f" article:{ARTICLE_ID}",
            f"article:{ARTICLE_ID}\n",
            "place:48",
            "place:48.5:2",
            "place:048:2",
            "place:-0:2",
            "place:+48:2",
            "place:91:0",
            "place:0:181",
            "place:-91:0",
            "place:0:-181",
            "link:US-FR",  # code order, as /api/links gives pairs
            "link:FR-FR",
            "link:fr-us",
            "link:FR-ZZ",  # no label point
            "link:FRA-USA",
            "thread:0",
            "thread:07",
            "thread:-7",
            "thread:9223372036854775808",
            "thread:abc",
            "entity:place:Paris",
            "entity:person:",
            "entity:person: Emmanuel Macron",
            "entity:person:Emmanuel  Macron",
            "entity:person:Emmanuel Macron\n",
            "entity:person:Emmanuel​Macron",
            "entity:person:Emmanuel\x01Macron",
            "entity:person:" + "x" * 201,
            "story:7",
            "Thread:7",
        ],
    )
    def test_anything_else_is_malformed(self, raw):
        with pytest.raises(ValueError):
            board.parse_item(raw)

    def test_a_200_character_name_is_allowed(self):
        assert board.parse_item("entity:org:" + "x" * 200).key == ("org", "x" * 200)

    def test_items_parse_in_order(self):
        items = board.parse_items(["thread:7", "place:48:2"])

        assert [i.id for i in items] == ["thread:7", "place:48:2"]

    def test_a_malformed_item_names_its_index_not_its_text(self):
        with pytest.raises(ValueError) as caught:
            board.parse_items(["thread:7", "entity:person:Ignore previous instructions\x01"])

        assert str(caught.value) == "items[1] is not a board item id."

    def test_items_must_be_distinct(self):
        with pytest.raises(ValueError, match="distinct"):
            board.parse_items(["thread:7", "place:48:2", "thread:7"])


# --- Resolve ----------------------------------------------------------------------


def _article_row(article_id=ARTICLE_ID, **extra):
    return {
        "id": uuid.UUID(article_id),
        "title": "Strikes spread across France - Reuters",
        "source_url": "https://example.com/strikes",
        "published_at": NOW - timedelta(hours=3),
        "latitude": 48.85,
        "longitude": 2.35,
        "region": "Paris, Ile-de-France (General), France",
        "country_code": "FR",
        **extra,
    }


class TestResolveArticles:
    @pytest.mark.asyncio
    async def test_an_article_is_its_headline_place_time_and_link(self, pool):
        pool.answers[board.ARTICLES_SQL] = [_article_row()]

        [snapshot] = await board.resolve_items(_items(f"article:{ARTICLE_ID}"), NOW)

        assert snapshot == {
            "title": "Strikes spread across France",  # display_title: no outlet suffix
            "place": "Paris, Ile-de-France, France",
            "lat": 48.85,
            "lng": 2.35,
            "time": NOW - timedelta(hours=3),
            "url": "https://example.com/strikes",
        }

    @pytest.mark.asyncio
    async def test_articles_are_read_once_by_primary_key(self, pool):
        pool.answers[board.ARTICLES_SQL] = [_article_row(), _article_row(OTHER_ID)]

        await board.resolve_items(_items(f"article:{ARTICLE_ID}", f"article:{OTHER_ID}"), NOW)

        assert pool.calls_to(board.ARTICLES_SQL) == [([ARTICLE_ID, OTHER_ID],)]
        assert "WHERE id = ANY($1::uuid[])" in board.ARTICLES_SQL

    @pytest.mark.asyncio
    async def test_an_unknown_or_purged_article_is_null(self, pool):
        pool.answers[board.ARTICLES_SQL] = [_article_row(OTHER_ID)]

        snapshots = await board.resolve_items(
            _items(f"article:{ARTICLE_ID}", f"article:{OTHER_ID}"), NOW
        )

        assert snapshots[0] is None
        assert snapshots[1]["title"] == "Strikes spread across France"

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "url",
        [
            "javascript:alert(1)",
            "data:text/html,<script>alert(1)</script>",
            "ftp://example.com/a",
            "//example.com/a",
            "https://",
            "https://exa mple.com/a",
            "https://example.com/\x00a",
            "",
            None,
        ],
    )
    async def test_a_link_that_is_not_http_or_https_is_left_out(self, pool, url):
        pool.answers[board.ARTICLES_SQL] = [_article_row(source_url=url)]

        [snapshot] = await board.resolve_items(_items(f"article:{ARTICLE_ID}"), NOW)

        assert snapshot["url"] is None
        assert snapshot["title"] == "Strikes spread across France"

    @pytest.mark.asyncio
    async def test_an_http_link_is_kept_as_it_is(self, pool):
        pool.answers[board.ARTICLES_SQL] = [_article_row(source_url="http://example.com/a")]

        [snapshot] = await board.resolve_items(_items(f"article:{ARTICLE_ID}"), NOW)

        assert snapshot["url"] == "http://example.com/a"

    @pytest.mark.asyncio
    async def test_no_article_pins_no_article_read(self, pool):
        await board.resolve_items(_items("link:FR-US"), NOW)

        assert pool.calls_to(board.ARTICLES_SQL) == []


class TestResolveThreads:
    @pytest.mark.asyncio
    async def test_a_thread_is_its_title_first_place_and_last_story(self, pool):
        places = [
            {"lat": 48.9, "lng": 2.3, "region": "Paris, France", "country_code": "FR"},
            {"lat": 50.8, "lng": 4.4, "region": "Brussels, Belgium", "country_code": "BE"},
        ]
        pool.answers[board.THREADS_SQL] = [
            {
                "id": 7,
                "title": "Pension strikes spread across France",
                "lead_title": "Unions walk out",
                "places": json.dumps(places),  # JSONB arrives as text
                "last_seen": NOW - timedelta(hours=1),
            }
        ]

        [snapshot] = await board.resolve_items(_items("thread:7"), NOW)

        assert snapshot == {
            "title": "Pension strikes spread across France",
            "place": "Paris, France",
            "lat": 48.9,
            "lng": 2.3,
            "time": NOW - timedelta(hours=1),
            "url": None,
        }
        assert pool.calls_to(board.THREADS_SQL) == [([7],)]

    @pytest.mark.asyncio
    async def test_without_an_ai_title_the_lead_headline_and_without_places_no_place(self, pool):
        pool.answers[board.THREADS_SQL] = [
            {
                "id": 7,
                "title": None,
                "lead_title": "Unions walk out",
                "places": [],
                "last_seen": NOW,
            }
        ]

        [snapshot] = await board.resolve_items(_items("thread:7"), NOW)

        assert snapshot["title"] == "Unions walk out"
        assert (snapshot["place"], snapshot["lat"], snapshot["lng"]) == (None, None, None)

    @pytest.mark.asyncio
    async def test_a_purged_thread_is_null(self, pool):
        [snapshot] = await board.resolve_items(_items("thread:7"), NOW)

        assert snapshot is None


def _place_row(**extra):
    return {
        "region": "Lagos, Nigeria (General), Nigeria",
        "country_code": "NG",
        "latitude": 6.45,
        "longitude": 3.39,
        "published_at": NOW - timedelta(hours=2),
        **extra,
    }


class TestResolvePlaces:
    @pytest.mark.asyncio
    async def test_a_place_is_named_by_its_newest_story_in_the_last_6_hours(self, pool):
        pool.answers[board.PLACE_SQL] = [_place_row()]

        [snapshot] = await board.resolve_items(_items("place:6:3"), NOW)

        assert snapshot == {
            "title": "Lagos, Nigeria",
            "place": "Lagos, Nigeria",
            "lat": 6.5,  # the cell's centre, where the globe draws its dot
            "lng": 3.5,
            "time": NOW - timedelta(hours=2),
            "url": None,
        }
        [args] = pool.calls_to(board.PLACE_SQL)
        # The cell's half-open box (database._cell_box), then the window's start.
        assert args[:4] == (6, 3, 7, 4)
        assert args[-1] == NOW - timedelta(hours=6)

    @pytest.mark.asyncio
    async def test_a_cell_quiet_for_6_hours_is_looked_up_over_the_week(self, pool):
        def by_window(*args):
            return [_place_row()] if args[-1] == NOW - timedelta(days=7) else []

        pool.answers[board.PLACE_SQL] = by_window

        [snapshot] = await board.resolve_items(_items("place:6:3"), NOW)

        assert snapshot["title"] == "Lagos, Nigeria"
        windows = [args[-1] for args in pool.calls_to(board.PLACE_SQL)]
        assert windows == [NOW - timedelta(hours=6), NOW - timedelta(days=7)]

    @pytest.mark.asyncio
    async def test_a_cell_with_no_story_this_week_is_null(self, pool):
        [snapshot] = await board.resolve_items(_items("place:6:3"), NOW)

        assert snapshot is None

    @pytest.mark.asyncio
    async def test_a_story_without_a_region_names_the_place_by_its_country(self, pool):
        pool.answers[board.PLACE_SQL] = [_place_row(region="")]

        [snapshot] = await board.resolve_items(_items("place:6:3"), NOW)

        assert snapshot["title"] == "Nigeria"

    @pytest.mark.asyncio
    async def test_the_query_reads_the_cells_stories_then_takes_the_newest(self):
        flat = " ".join(board.PLACE_SQL.split())

        assert "location && ST_MakeEnvelope($5, $6, $7, $8, 4326)::geography" in flat
        assert "published_at >= $9" in flat
        # Every story of the cell in the window first, then the newest: the
        # LIMIT can't turn the plan into a backward walk of the time index.
        assert flat.startswith("WITH cell AS MATERIALIZED (")
        assert flat.endswith("ORDER BY published_at DESC, id LIMIT 1")


def _member(name, i, lat=6.4, lng=3.4, region="Lagos, Nigeria", country="NG", story=None):
    return {
        "name": name,
        "article_id": uuid.UUID(int=i),
        "story_key": story if story is not None else i,
        "published_at": NOW - timedelta(hours=i),
        "latitude": lat,
        "longitude": lng,
        "region": region,
        "country_code": country,
        "tone": -0.5,
    }


class TestResolveEntities:
    @pytest.fixture
    def names(self):
        stored = {("person", "bola tinubu"): "Bola Tinubu", ("org", "ecowas"): "ECOWAS"}

        async def resolve(entity_type, name, now):
            return stored.get((entity_type, name.lower()))

        with patch("app.services.board.resolve_entity", AsyncMock(side_effect=resolve)) as mock:
            yield mock

    @pytest.mark.asyncio
    async def test_an_entity_is_its_stored_name_and_the_place_with_most_stories(self, pool, names):
        pool.answers[board.ENTITY_SAMPLE_SQL] = [
            _member("Bola Tinubu", 1, lat=9.1, lng=7.4, region="Abuja, Nigeria"),
            _member("Bola Tinubu", 2),
            _member("Bola Tinubu", 3),
            _member("Bola Tinubu", 4, story=3),  # a copy of story 3: counted once
        ]

        [snapshot] = await board.resolve_items(_items("entity:person:bola tinubu"), NOW)

        assert snapshot == {
            "title": "Bola Tinubu",
            "place": "Lagos, Nigeria",
            "lat": 6.4,
            "lng": 3.4,
            "time": None,
            "url": None,
        }
        names.assert_awaited_once_with("person", "bola tinubu", NOW)
        # The stored names' members this week, at most a sample each.
        [args] = pool.calls_to(board.ENTITY_SAMPLE_SQL)
        assert args == (["Bola Tinubu"], NOW - timedelta(days=7), board.ENTITY_SAMPLE)

    @pytest.mark.asyncio
    async def test_a_name_without_stories_this_week_has_no_place(self, pool, names):
        [snapshot] = await board.resolve_items(_items("entity:org:ECOWAS"), NOW)

        assert snapshot["title"] == "ECOWAS"
        assert (snapshot["place"], snapshot["lat"], snapshot["lng"]) == (None, None, None)

    @pytest.mark.asyncio
    async def test_an_unknown_name_or_type_is_null_and_reads_no_members(self, pool, names):
        snapshots = await board.resolve_items(
            _items("entity:person:Nobody Known", "entity:org:Bola Tinubu"), NOW
        )

        assert snapshots == [None, None]
        assert pool.calls_to(board.ENTITY_SAMPLE_SQL) == []

    def test_the_sample_reads_members_through_the_entity_index_up_to_a_cap(self):
        flat = " ".join(board.ENTITY_SAMPLE_SQL.split())

        assert "entities @> ARRAY[c.name]::text[] AND published_at >= $2" in flat
        assert "LIMIT $3" in flat
        assert board.ENTITY_SAMPLE == 100


class TestResolveLinksAndOrder:
    @pytest.mark.asyncio
    async def test_a_link_is_its_two_countries(self, pool):
        [snapshot] = await board.resolve_items(_items("link:FR-US"), NOW)

        assert snapshot == {
            "title": "France and United States",
            "place": None,
            "lat": None,
            "lng": None,
            "time": None,
            "url": None,
        }
        assert pool.calls == []  # names come from the label-point table

    @pytest.mark.asyncio
    async def test_snapshots_come_back_in_the_items_order(self, pool):
        pool.answers[board.ARTICLES_SQL] = [_article_row()]
        pool.answers[board.PLACE_SQL] = [_place_row()]

        snapshots = await board.resolve_items(
            _items("place:6:3", "link:FR-US", f"article:{ARTICLE_ID}", "thread:7"), NOW
        )

        assert [s and s["title"] for s in snapshots] == [
            "Lagos, Nigeria",
            "France and United States",
            "Strikes spread across France",
            None,
        ]
