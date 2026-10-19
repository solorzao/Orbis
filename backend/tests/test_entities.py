"""Tests for entity dossiers: the service (pool mocked) and /api/entities (service mocked)."""

from __future__ import annotations

import asyncio
import contextlib
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest

from app.routers.http_cache import EDGE_CACHE_CONTROL
from app.services import entities
from app.services.cache import cycle_ttl

NOW = datetime(2026, 10, 18, 12, tzinfo=timezone.utc)
SINCE = datetime(2026, 10, 15, 9, tzinfo=timezone.utc)


def _member(i, story=None, lat=10.5, lng=20.5, hours_ago=1.0, tone=0.2, **extra):
    """A thread_members row, as the dossier's member read returns it."""
    return {
        "article_id": uuid.UUID(int=i),
        "story_key": story if story is not None else i,
        "source_name": f"site{i}.example",
        "published_at": NOW - timedelta(hours=hours_ago),
        "latitude": lat,
        "longitude": lng,
        "region": "Tehran, Iran (General), Iran",
        "country_code": "IR",
        "entities": ["Abbas Araghchi"],
        "tone": tone,
        **extra,
    }


class TestLikeEscape:
    def test_like_metacharacters_are_literal(self):
        assert entities.like_escape("50%_off\\") == "50\\%\\_off\\\\"
        assert entities.like_escape("Abbas Araghchi") == "Abbas Araghchi"


class TestTrend:
    @pytest.mark.parametrize(
        ("h24", "prev24", "trend"), [(10, 5, 2.0), (3, 0, None), (0, 4, 0.0), (2, 3, 0.67)]
    )
    def test_the_last_day_against_the_one_before(self, h24, prev24, trend):
        assert entities.trend(h24, prev24) == trend


class TestStories:
    def test_one_row_per_story_its_newest_copy(self):
        rows = [
            _member(1, story=7, hours_ago=3),
            _member(2, story=7, hours_ago=1),  # newest copy of story 7
            _member(3, story=8, hours_ago=2),
            _member(4, hours_ago=5) | {"story_key": None},  # unkeyed: its own story
            _member(5, hours_ago=6) | {"story_key": None},
        ]
        stories = entities.newest_per_story(rows)
        assert [s["article_id"].int for s in stories] == [2, 3, 4, 5]  # newest first

    def test_places_count_stories_and_keep_the_top_twelve(self):
        stories = entities.newest_per_story(
            [_member(1, lat=10.5, lng=20.5, tone=0.5), _member(2, lat=10.9, lng=20.1, tone=-0.1)]
            + [_member(10 + i, lat=30.5 + i, lng=40.5) for i in range(14)]
        )
        places = entities.top_places(stories)
        assert len(places) == 12
        first = places[0]
        assert (first["n"], first["tone"], first["country_code"]) == (2, 0.2, "IR")
        assert first["place"] == "Tehran, Iran"  # display_place
        assert (first["lat"], first["lng"]) == (10.5, 20.5)  # the cell's newest story

    def test_a_place_without_tones_has_tone_zero(self):
        [place] = entities.top_places(entities.newest_per_story([_member(1, tone=None)]))
        assert place["tone"] == 0.0

    def test_timeline_hourly_for_a_day_daily_for_a_week(self):
        stories = entities.newest_per_story(
            [_member(1, hours_ago=0.5), _member(2, hours_ago=0.2), _member(3, hours_ago=30)]
        )
        hourly = entities.timeline(stories, NOW, "24h")
        assert len(hourly) == 24
        assert hourly[0]["t"] == NOW - timedelta(hours=24)
        assert [b["n"] for b in hourly] == [1] + [0] * 22 + [2]  # 30 h ago: clamped to the first
        daily = entities.timeline(stories, NOW, "168h")
        assert len(daily) == 7 and daily[0]["t"] == NOW - timedelta(days=7)
        assert [b["n"] for b in daily] == [0, 0, 0, 0, 0, 1, 2]

    def test_co_mentions_count_stories_without_the_entity_itself(self):
        members = [
            # one story, two copies: its entities count once, together
            _member(1, story=7, entities=["Abbas Araghchi", "Ali Khamenei"]),
            _member(2, story=7, entities=["abbas araghchi", "Ali Khamenei", "United Nations"]),
            _member(3, story=8, entities=["Abbas Araghchi", "United Nations"]),
            _member(4, story=9, entities=["Abbas Araghchi", "Ali Khamenei"]),
        ]
        assert entities.co_mentioned(members, "Abbas Araghchi") == [
            {"name": "Ali Khamenei", "n": 2},
            {"name": "United Nations", "n": 2},
        ]

    def test_at_most_fifteen_co_mentions(self):
        members = [_member(1, entities=["Abbas Araghchi"] + [f"Person {i:02}" for i in range(20)])]
        co = entities.co_mentioned(members, "Abbas Araghchi")
        assert [c["name"] for c in co] == [f"Person {i:02}" for i in range(15)]


class _Pool:
    """Answers the dossier's queries by what they read; records each call."""

    def __init__(self, members: list[dict], articles: set | None = None, nodes=()):
        self.members = members
        self.articles = articles  # the ids that resolve; None: every id
        self.nodes = list(nodes)  # (type, name) in kg_nodes
        self.calls: list[tuple] = []

    # As a connection too: acquire() yields the pool itself.
    @contextlib.asynccontextmanager
    async def acquire(self):
        yield self

    @contextlib.asynccontextmanager
    async def transaction(self):
        self.calls.append(("BEGIN", ()))
        yield
        self.calls.append(("COMMIT", ()))

    async def execute(self, sql, *args):
        self.calls.append((sql, args))

    async def fetchrow(self, sql, *args, **kwargs):
        self.calls.append((sql, args))
        return {
            "h24": 12,
            "prev24": 4,
            "d7": 3000,
            "country_codes": ["IR", "US"],
            "country_counts": [40, 3],
            "since": SINCE,
        }

    async def fetch(self, sql, *args, **kwargs):
        self.calls.append((sql, args))
        if "FROM thread_members" in sql:
            return self.members[: args[-1]]
        if "FROM articles" in sql:
            [ids] = args
            rows = [
                {
                    "id": i,
                    "title": f"Story {i.int} - Reuters",
                    "source_url": f"https://x.test/{i.int}",
                }
                for i in ids
            ]
            return [r for r in rows if self.articles is None or r["id"] in self.articles]
        if "FROM kg_nodes" in sql:
            [names] = args
            return [{"type": t, "name": n} for t, n in self.nodes if n in names]
        raise AssertionError(sql)


async def _dossier(pool, timespan="168h", name="Abbas Araghchi", entity_type="person"):
    with patch("app.services.entities.get_pool", new_callable=AsyncMock, return_value=pool):
        return await entities.get_entity_dossier(name, entity_type, timespan, NOW)


def _call(pool, needle):
    return [c for c in pool.calls if needle in " ".join(c[0].split())]


class TestGetEntityDossier:
    @pytest.mark.asyncio
    async def test_member_reads_are_planned_with_their_values(self):
        pool = _Pool([_member(1, entities=["Abbas Araghchi", "Ali Khamenei"])])
        await _dossier(pool)

        # asyncpg reuses prepared statements, and PostgreSQL may switch one to a
        # generic plan after five runs: default selectivities could then read the
        # week by published_at instead of the entity index. Both member reads run
        # in one transaction that plans every statement with its values.
        kinds = []
        for sql, _ in pool.calls:
            flat = " ".join(sql.split())
            if "count(DISTINCT" in flat:
                kinds.append("summary")
            elif "LIMIT $3" in flat:
                kinds.append("members")
            elif "FROM articles" in flat:
                kinds.append("articles")
            elif "FROM kg_nodes" in flat:
                kinds.append("types")
            else:
                kinds.append(flat)
        assert kinds == [
            "BEGIN",
            "SET LOCAL plan_cache_mode = force_custom_plan",
            "summary",
            "members",
            "COMMIT",
            "types",
            "articles",
        ]

    @pytest.mark.asyncio
    async def test_a_heavy_entity_reads_its_newest_members_up_to_the_cap(self):
        members = [_member(i, hours_ago=i / 100) for i in range(1, entities.MAX_MENTIONS + 2)]
        pool = _Pool(members)
        dossier = await _dossier(pool)

        [(sql, args)] = _call(pool, "ORDER BY published_at DESC, article_id LIMIT $3")
        flat = " ".join(sql.split())
        # Every match first, then the newest: the LIMIT can't tilt the plan toward
        # a backward scan of the week by published_at.
        assert flat.startswith("WITH m AS MATERIALIZED ( SELECT")
        assert (
            "FROM thread_members WHERE entities @> ARRAY[$1]::text[] AND published_at >= $2 )"
            in flat
        )
        assert flat.endswith(") SELECT * FROM m ORDER BY published_at DESC, article_id LIMIT $3")
        assert args == ("Abbas Araghchi", NOW - timedelta(days=7), entities.MAX_MENTIONS + 1)
        assert (dossier["capped"], dossier["cap"]) == (True, entities.MAX_MENTIONS)
        assert sum(p["n"] for p in dossier["places"]) == entities.MAX_MENTIONS
        assert (dossier["name"], dossier["type"]) == ("Abbas Araghchi", "person")

    @pytest.mark.asyncio
    async def test_counts_trend_countries_and_since_from_every_match(self):
        pool = _Pool([_member(1)])
        dossier = await _dossier(pool, timespan="24h")

        [(sql, args)] = [c for c in pool.calls if "count(DISTINCT" in c[0]]
        flat = " ".join(sql.split())
        reads = "FROM thread_members WHERE entities @> ARRAY[$1]::text[] AND published_at >= $2"
        assert reads in flat
        assert "LIMIT" not in flat  # d7 reads every match
        assert args == (
            "Abbas Araghchi",
            NOW - timedelta(days=7),
            NOW - timedelta(hours=24),
            NOW - timedelta(hours=48),
            NOW - timedelta(hours=24),  # the window, for countries
        )
        assert dossier["counts"] == {"h24": 12, "d7": 3000}
        assert dossier["trend"] == 3.0
        assert dossier["countries"] == [
            {"country_code": "IR", "n": 40},
            {"country_code": "US", "n": 3},
        ]
        assert dossier["since"] == SINCE
        assert dossier["capped"] is False
        [(_, member_args)] = _call(pool, "LIMIT $3")
        assert member_args[1] == NOW - timedelta(hours=24)

    @pytest.mark.asyncio
    async def test_articles_are_read_by_id_for_the_ten_headlines_only(self):
        members = [_member(i, story=i // 2, hours_ago=i) for i in range(1, 40)]  # copies in pairs
        pool = _Pool(members)
        dossier = await _dossier(pool)

        [(sql, (ids,))] = _call(pool, "FROM articles WHERE id = ANY($1::uuid[])")
        newest = entities.newest_per_story(members)[:10]
        assert ids == [s["article_id"] for s in newest]
        assert dossier["headlines"][0] == {
            "title": "Story 1",  # display_title: the outlet goes
            "source_name": "site1.example",
            "published_at": NOW - timedelta(hours=1),
            "source_url": "https://x.test/1",
            "place": "Tehran, Iran",
        }
        assert len(dossier["headlines"]) == 10
        assert not any("kg_edges" in c[0] for c in pool.calls)

    @pytest.mark.asyncio
    async def test_a_headline_whose_article_is_gone_is_left_out(self):
        members = [_member(1), _member(2, hours_ago=2)]
        pool = _Pool(members, articles={uuid.UUID(int=2)})
        dossier = await _dossier(pool)
        assert [h["source_url"] for h in dossier["headlines"]] == ["https://x.test/2"]

    @pytest.mark.asyncio
    async def test_co_mentions_carry_the_types_the_graph_knows(self):
        members = [
            _member(1, entities=["Abbas Araghchi", "Ali Khamenei", "Hamas", "Zz Unknown"]),
            _member(2, entities=["Abbas Araghchi", "Ali Khamenei", "Hamas"]),
            _member(3, entities=["Abbas Araghchi", "Ali Khamenei"]),
        ]
        nodes = [("PERSON", "Ali Khamenei"), ("ORG", "Hamas"), ("PERSON", "Hamas")]
        pool = _Pool(members, nodes=nodes)
        dossier = await _dossier(pool)

        assert dossier["co_mentions"] == [
            {"name": "Ali Khamenei", "n": 3, "types": ["person"]},
            {"name": "Hamas", "n": 2, "types": ["person", "org"]},  # both: the UI offers both
            {"name": "Zz Unknown", "n": 1, "types": []},  # no node: not trackable
        ]
        [(sql, args)] = _call(pool, "FROM kg_nodes")
        flat = " ".join(sql.split())
        # The UNIQUE (type, name) btree, one probe per type and name.
        assert "WHERE type IN ('PERSON', 'ORG') AND name = ANY($1::text[])" in flat
        assert args == (["Ali Khamenei", "Hamas", "Zz Unknown"],)

    @pytest.mark.asyncio
    async def test_no_members_no_article_or_type_read(self):
        pool = _Pool([])
        dossier = await _dossier(pool, entity_type="org", name="Nobody Inc")
        assert _call(pool, "FROM articles") == []
        assert _call(pool, "FROM kg_nodes") == []
        assert (dossier["places"], dossier["headlines"], dossier["co_mentions"]) == ([], [], [])
        assert [b["n"] for b in dossier["timeline"]] == [0] * 7


class TestResolveEntity:
    @pytest.mark.asyncio
    async def test_exact_name_of_that_type_any_case_as_stored(self):
        pool = AsyncMock()
        pool.fetchval.return_value = "Abbas Araghchi"
        with patch("app.services.entities.get_pool", new_callable=AsyncMock, return_value=pool):
            stored = await entities.resolve_entity("person", "abbas araghchi", NOW)
        assert stored == "Abbas Araghchi"

        sql, *args = pool.fetchval.await_args.args
        flat = " ".join(sql.split())
        # The literal type predicate: the partial trigram index of people and orgs.
        assert (
            "FROM kg_nodes n WHERE n.type IN ('PERSON', 'ORG') AND n.type = $1"
            " AND n.name ILIKE $2" in flat
        )
        # Spellings that differ only in case: the most mentioned this week in thread
        # members, which the dossier reads by that spelling (counted up to a cap),
        # then by name. Nothing depends on the request's case, so the dossier cached
        # under the lowercased name is the same whichever case asks.
        mentions = " ".join(entities.member_mentions_sql("n.name", "$3", "$4").split())
        assert f"ORDER BY {mentions} DESC, n.name LIMIT 1" in flat
        assert "kg_edges" not in flat
        assert args == [
            "PERSON",
            "abbas araghchi",
            NOW - timedelta(days=7),
            entities.MENTION_COUNT_CAP,
        ]

    @pytest.mark.asyncio
    async def test_like_metacharacters_match_only_themselves(self):
        pool = AsyncMock()
        pool.fetchval.return_value = None
        with patch("app.services.entities.get_pool", new_callable=AsyncMock, return_value=pool):
            assert await entities.resolve_entity("org", "100%_Fund", NOW) is None
        assert pool.fetchval.await_args.args[1:3] == ("ORG", "100\\%\\_Fund")


class TestMemberMentions:
    def test_stories_from_at_most_a_cap_of_members_as_the_dossier_counts_them(self):
        assert entities.MENTION_COUNT_CAP == 100
        sql = " ".join(entities.member_mentions_sql("c.name", "$3", "$4").split())
        # A name with the cap's worth of members shows the cap ("100+"); below it,
        # its distinct stories: the dossier's d7, copies counted once.
        assert sql == (
            "(SELECT CASE WHEN count(*) >= $4 THEN $4 ELSE count(DISTINCT story) END::int"
            f" FROM (SELECT {entities.STORY_SQL} AS story FROM thread_members"
            " WHERE entities @> ARRAY[c.name]::text[] AND published_at >= $3 LIMIT $4) x)"
        )
        assert "count(DISTINCT story)" in " ".join(entities._SUMMARY_SQL.split())
        assert f"SELECT {entities.STORY_SQL} AS story" in " ".join(entities._SUMMARY_SQL.split())


# ── /api/entities ──────────────────────────────────────────────────────


def _client(monkeypatch):
    from httpx import ASGITransport, AsyncClient

    from app.main import app
    from app.middleware import security

    monkeypatch.setattr(security.settings, "api_key", "")
    security._rate_buckets.clear()
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    return AsyncClient(transport=transport, base_url="http://test")


def _dossier_body(name="Abbas Araghchi", type_="person") -> dict:
    return {
        "name": name,
        "type": type_,
        "counts": {"h24": 12, "d7": 40},
        "trend": 1.5,
        "capped": False,
        "cap": 2000,
        "countries": [{"country_code": "IR", "n": 9}],
        "places": [
            {
                "lat": 35.7,
                "lng": 51.4,
                "place": "Tehran, Iran",
                "country_code": "IR",
                "n": 9,
                "tone": -0.2,
            }
        ],
        "timeline": [{"t": NOW - timedelta(days=1), "n": 3}],
        "co_mentions": [{"name": "Ali Khamenei", "n": 5, "types": ["person"]}],
        "headlines": [
            {
                "title": "Talks resume",
                "source_name": "reuters.com",
                "published_at": NOW,
                "source_url": "https://reuters.com/x",
                "place": "Tehran, Iran",
            }
        ],
        "since": SINCE,
    }


@pytest.fixture
def service(monkeypatch):
    from app.routers import entities as router

    monkeypatch.setattr(router, "_now", lambda: NOW)
    with (
        patch("app.routers.entities.get_cached", new_callable=AsyncMock, return_value=None),
        patch("app.routers.entities.set_cached", new_callable=AsyncMock) as set_cached,
        patch(
            "app.routers.entities.resolve_entity",
            new_callable=AsyncMock,
            return_value="Abbas Araghchi",
        ) as resolve,
        patch(
            "app.routers.entities.get_entity_dossier",
            new_callable=AsyncMock,
            return_value=_dossier_body(),
        ) as dossier,
    ):
        yield resolve, dossier, set_cached


class TestEntityRoute:
    @pytest.mark.asyncio
    async def test_a_dossier_by_type_and_name(self, monkeypatch, service):
        resolve, dossier, _ = service
        async with _client(monkeypatch) as client:
            resp = await client.get("/api/entities/person/abbas araghchi")

        assert resp.status_code == 200
        body = resp.json()
        assert (body["name"], body["type"], body["capped"], body["cap"]) == (
            "Abbas Araghchi",
            "person",
            False,
            2000,
        )
        assert body["co_mentions"] == [{"name": "Ali Khamenei", "n": 5, "types": ["person"]}]
        assert body["since"] == "2026-10-15T09:00:00Z"
        assert "linked" not in resp.text.lower()
        resolve.assert_awaited_once_with("person", "abbas araghchi", NOW)
        # The stored spelling from then on.
        dossier.assert_awaited_once_with("Abbas Araghchi", "person", "168h", NOW)
        assert resp.headers["cache-control"] == EDGE_CACHE_CONTROL

    @pytest.mark.asyncio
    async def test_a_name_with_a_slash(self, monkeypatch, service):
        resolve, _, _ = service
        async with _client(monkeypatch) as client:
            resp = await client.get("/api/entities/org/AC%2FDC")
        assert resp.status_code == 200
        resolve.assert_awaited_once_with("org", "AC/DC", NOW)

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "path",
        [
            "/api/entities/place/Tehran",  # not person or org
            "/api/entities/person/Abbas%20Araghchi?timespan=6h",
            "/api/entities/person/%E2%80%8B%20",  # nothing left once cleaned
            "/api/entities/person/" + "x" * 201,
        ],
    )
    async def test_invalid_requests_are_422(self, monkeypatch, service, path):
        resolve, _, _ = service
        async with _client(monkeypatch) as client:
            resp = await client.get(path)
        assert resp.status_code == 422
        resolve.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_an_unknown_name_is_404_and_not_cached(self, monkeypatch, service):
        resolve, dossier, set_cached = service
        resolve.return_value = None
        async with _client(monkeypatch) as client:
            resp = await client.get("/api/entities/org/Nobody At All")
        assert resp.status_code == 404
        dossier.assert_not_awaited()
        set_cached.assert_not_awaited()
        assert "cache-control" not in resp.headers

    @pytest.mark.asyncio
    async def test_cached_by_type_lowercased_name_and_window(self, monkeypatch, service):
        _, _, set_cached = service
        async with _client(monkeypatch) as client:
            await client.get("/api/entities/person/ABBAS  Araghchi", params={"timespan": "24h"})

        key, value, ttl = set_cached.await_args.args
        assert (key, ttl) == ("db:entity:v1:person:abbas araghchi:24h", cycle_ttl(300))
        assert value["name"] == "Abbas Araghchi"
        assert value["since"] == SINCE.isoformat().replace("+00:00", "Z")

    @pytest.mark.asyncio
    async def test_serves_the_cached_dossier(self, monkeypatch, service):
        resolve, dossier, _ = service
        cached = _dossier_body()
        cached["timeline"][0]["t"] = cached["timeline"][0]["t"].isoformat()
        cached["headlines"][0]["published_at"] = NOW.isoformat()
        cached["since"] = None  # no members yet
        with patch("app.routers.entities.get_cached", new_callable=AsyncMock, return_value=cached):
            async with _client(monkeypatch) as client:
                resp = await client.get("/api/entities/person/Abbas Araghchi")
        assert resp.json()["name"] == "Abbas Araghchi"
        assert resp.json()["since"] is None
        resolve.assert_not_awaited()
        dossier.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_concurrent_misses_share_one_computation(self, monkeypatch, service):
        resolve, dossier, _ = service
        release = asyncio.Event()

        async def slow(*_args):
            await release.wait()
            return _dossier_body()

        dossier.side_effect = slow
        async with _client(monkeypatch) as client:
            first = asyncio.create_task(client.get("/api/entities/person/Abbas Araghchi"))
            second = asyncio.create_task(client.get("/api/entities/person/abbas araghchi"))
            await asyncio.sleep(0.05)
            release.set()
            responses = await asyncio.gather(first, second)

        assert [r.status_code for r in responses] == [200, 200]
        resolve.assert_awaited_once()
        dossier.assert_awaited_once()
