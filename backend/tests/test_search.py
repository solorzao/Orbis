"""Tests for global search: the service (pool mocked) and /api/search (service mocked)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest

from app.routers.http_cache import EDGE_CACHE_CONTROL
from app.services import entities, search, thread_reads

NOW = datetime(2026, 10, 18, 12, tzinfo=timezone.utc)


def _candidate(type_, name, n, sim=0.5, capped=False):
    """A candidate row: its distinct stories among the members read, and whether
    the member cap was hit."""
    return {
        "type": type_,
        "name": name,
        "stories": n,
        "capped": capped,
        "sim": sim,
        "full_sim": sim,
    }


class _Pool:
    """Answers search's queries: candidate names, their counts, then threads."""

    def __init__(self, candidates, threads=()):
        self.candidates, self.threads = candidates, list(threads)
        self.calls: list[tuple] = []

    async def fetch(self, sql, *args):
        self.calls.append((sql, args))
        if "FROM kg_entity_names" in sql:
            keys = ("type", "name", "sim", "full_sim")
            return [{k: c[k] for k in keys} for c in self.candidates]
        if "FROM unnest" in sql:
            [names, *_] = args
            return [
                {"name": c["name"], "stories": c["stories"], "capped": c["capped"]}
                for c in self.candidates
                if c["name"] in names
            ]
        if "FROM threads" in sql:
            return self.threads
        raise AssertionError(sql)


def _call(pool, needle):
    [call] = [c for c in pool.calls if needle in c[0]]
    return " ".join(call[0].split()), call[1]


async def _search(pool, q="abbas"):
    with patch("app.services.search.get_pool", new_callable=AsyncMock, return_value=pool):
        return await search.search(q, NOW)


class TestSearchService:
    @pytest.mark.asyncio
    async def test_people_and_orgs_by_mentions_then_similarity_without_the_unmentioned(self):
        pool = _Pool(
            [
                _candidate("PERSON", "Abbas Araghchi", 40, 0.6),
                _candidate("PERSON", "Abbas Abbasi", 40, 0.7),  # same mentions, closer name
                _candidate("PERSON", "Mahmoud Abbas", 90, 0.3),
                _candidate("PERSON", "Abbas Nobody", 0, 0.9),  # no mentions this week
                _candidate("ORG", "Abbas Foundation", 2, 0.5),
            ]
            + [_candidate("PERSON", f"Abbas {i}", 1, 0.4) for i in range(5)]
        )
        result = await _search(pool)

        assert result["people"] == [
            {"type": "person", "name": "Mahmoud Abbas", "n": 90, "capped": False},
            {"type": "person", "name": "Abbas Abbasi", "n": 40, "capped": False},
            {"type": "person", "name": "Abbas Araghchi", "n": 40, "capped": False},
            {"type": "person", "name": "Abbas 0", "n": 1, "capped": False},
            {"type": "person", "name": "Abbas 1", "n": 1, "capped": False},
        ]  # up to five
        assert result["orgs"] == [
            {"type": "org", "name": "Abbas Foundation", "n": 2, "capped": False}
        ]
        assert result["threads"] == []

    @pytest.mark.asyncio
    async def test_names_at_the_member_cap_come_first_the_closest_first(self):
        pool = _Pool(
            [
                _candidate("PERSON", "Donald Trump Jr", 99, 0.6),  # 99 stories, under the cap
                _candidate("PERSON", "Barron Trump", 12, 0.5),
                _candidate("PERSON", "Melania Trump", 90, 0.43, capped=True),  # 100+ members
                _candidate("PERSON", "Donald Trump", 40, 0.46, capped=True),
            ]
        )
        result = await _search(pool, "trump")

        # At the cap, a name has 100+ members this week: more coverage than any
        # name under it. Its n is a sample (whichever 100 members the scan met
        # first), so capped names rank by how close the name is; the rest by n.
        assert result["people"] == [
            {"type": "person", "name": "Donald Trump", "n": 40, "capped": True},
            {"type": "person", "name": "Melania Trump", "n": 90, "capped": True},
            {"type": "person", "name": "Donald Trump Jr", "n": 99, "capped": False},
            {"type": "person", "name": "Barron Trump", "n": 12, "capped": False},
        ]

    @pytest.mark.asyncio
    async def test_names_by_prefix_or_word_similarity_in_the_narrow_names_table(self):
        pool = _Pool([_candidate("PERSON", "Rishi Sunak", 3)])
        await _search(pool, "Sunak")

        sql, args = _call(pool, "FROM kg_entity_names")
        # Only people and organisations, a few MB that stay cached, never kg_nodes'
        # heap where names sit thinly among headlines. A word of the name must
        # resemble q (<%, word similarity), not just share two trigrams with it as
        # % allows: for "sunak", every name with a word starting "Su".
        assert "FROM kg_entity_names WHERE name ILIKE $2 OR $1 <% name" in sql
        assert "word_similarity($1, name) AS sim, similarity(name, $1) AS full_sim" in sql
        assert sql.endswith("ORDER BY sim DESC, full_sim DESC, name LIMIT 20")
        assert "kg_nodes" not in sql
        assert args == ("Sunak", "Sunak%")

    @pytest.mark.asyncio
    async def test_the_candidates_are_counted_from_thread_members_in_one_query(self):
        pool = _Pool(
            [_candidate("PERSON", "Hamas", 40, 1.0), _candidate("ORG", "Hamas", 40, 1.0)]
            + [_candidate("PERSON", "Hamad Das", 2, 0.6)]
        )
        await _search(pool, "hamas")

        sql, args = _call(pool, "FROM unnest")
        # Each name once (members don't record types), as the dossier counts them,
        # reading at most 100 members.
        mentions = " ".join(entities.member_mentions_sql("c.name", "$2", "$3").split())
        assert sql == (
            f"SELECT c.name, m.stories, m.capped FROM unnest($1::text[]) AS c(name)"
            f" CROSS JOIN LATERAL {mentions} m"
        )
        assert args == (
            ["Hamad Das", "Hamas"],
            NOW - timedelta(days=7),
            search.SEARCH_COUNT_CAP,
        )
        assert search.SEARCH_COUNT_CAP == 100

    @pytest.mark.asyncio
    async def test_no_names_no_count_query(self):
        pool = _Pool([])
        assert (await _search(pool, "zzz"))["people"] == []
        assert [c for c in pool.calls if "FROM unnest" in c[0]] == []

    @pytest.mark.asyncio
    async def test_a_slow_search_logs_each_phase(self, caplog):
        pool = _Pool([_candidate("PERSON", "Rishi Sunak", 3)])
        ticks = iter([0.0, 1.25, 1.5, 1.75])
        with (
            patch("app.services.search.time.perf_counter", side_effect=lambda: next(ticks)),
            caplog.at_level("INFO", logger="app.services.search"),
        ):
            await _search(pool, "sunak")

        [record] = caplog.records
        assert record.levelname == "INFO"
        # The query's length, never its text: it's what a visitor typed.
        assert record.getMessage() == (
            "Search of 5 characters took 1.75s: names 1.25s (1 candidates), counts 0.25s,"
            " threads 0.25s"
        )
        assert "sunak" not in record.getMessage()

    @pytest.mark.asyncio
    async def test_a_fast_search_logs_nothing(self, caplog):
        pool = _Pool([_candidate("PERSON", "Rishi Sunak", 3)])
        with caplog.at_level("INFO", logger="app.services.search"):
            await _search(pool, "sunak")
        assert caplog.records == []

    @pytest.mark.asyncio
    async def test_an_injection_looking_q_is_only_text(self):
        q = "%'; DROP TABLE kg_nodes; --_"
        pool = _Pool([])
        await _search(pool, q)
        sql, args = next(c for c in pool.calls if "FROM kg_entity_names" in c[0])
        assert q not in sql and "DROP" not in sql
        assert args[:2] == (q, "\\%'; DROP TABLE kg\\_nodes; --\\_%")

    @pytest.mark.asyncio
    async def test_listed_threads_by_title_or_lead_title(self):
        threads = [
            {"id": 7, "title": "Iran nuclear talks", "lead_title": "Talks resume in Vienna"},
            {"id": 9, "title": None, "lead_title": "Abbas speaks"},  # no AI title yet
        ]
        pool = _Pool([], threads=threads)
        result = await _search(pool, "Ab_%")

        assert result["threads"] == [
            {"id": 7, "title": "Iran nuclear talks"},
            {"id": 9, "title": "Abbas speaks"},
        ]
        [(sql, args)] = [c for c in pool.calls if "FROM threads" in c[0]]
        flat = " ".join(sql.split())
        assert "JOIN" not in flat  # threads alone
        # The thread list's own predicate, over its longest window.
        assert f"WHERE last_seen >= $1 AND {thread_reads.LISTED_SQL} AND" in flat
        assert "(title ILIKE $2 OR lead_title ILIKE $2)" in flat
        assert "ORDER BY velocity DESC, n_stories DESC, id LIMIT 5" in flat
        assert args == (NOW - timedelta(hours=max(thread_reads.LIST_HOURS)), "%Ab\\_\\%%")

    def test_the_listed_predicate_is_the_lists_with_literal_thresholds(self):
        # Literals, not parameters: every plan can match the partial idx_threads_listed.
        assert thread_reads.LISTED_SQL == "n_stories >= 3 AND n_sources >= 3"
        query, _ = thread_reads.list_query(NOW, 168, None, 20)
        assert f"WHERE last_seen >= $1 AND {thread_reads.LISTED_SQL}" in " ".join(query.split())
        assert max(thread_reads.LIST_HOURS) == 168

    @pytest.mark.asyncio
    async def test_no_listed_threads(self):
        assert (await _search(_Pool([])))["threads"] == []


# ── /api/search ────────────────────────────────────────────────────────


def _client(monkeypatch):
    from httpx import ASGITransport, AsyncClient

    from app.main import app
    from app.middleware import security

    monkeypatch.setattr(security.settings, "api_key", "")
    security._rate_buckets.clear()
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    return AsyncClient(transport=transport, base_url="http://test")


RESULTS = {
    "people": [{"type": "person", "name": "Abbas Araghchi", "n": 40, "capped": True}],
    "orgs": [],
    "threads": [{"id": 7, "title": "Iran nuclear talks"}],
}


@pytest.fixture
def service(monkeypatch):
    from app.routers import search as router

    monkeypatch.setattr(router, "_now", lambda: NOW)
    with (
        patch("app.routers.search.get_cached", new_callable=AsyncMock, return_value=None),
        patch("app.routers.search.set_cached", new_callable=AsyncMock) as set_cached,
        patch("app.routers.search.search", new_callable=AsyncMock, return_value=RESULTS) as run,
    ):
        yield run, set_cached


class TestSearchRoute:
    @pytest.mark.asyncio
    async def test_returns_people_orgs_and_threads(self, monkeypatch, service):
        run, _ = service
        async with _client(monkeypatch) as client:
            resp = await client.get("/api/search", params={"q": "  Abbas​  "})

        assert resp.status_code == 200
        assert resp.json() == RESULTS
        run.assert_awaited_once_with("Abbas", NOW)  # invisible characters and ends trimmed
        assert resp.headers["cache-control"] == EDGE_CACHE_CONTROL

    @pytest.mark.asyncio
    @pytest.mark.parametrize("q", ["a", " a ", "a​", "x" * 81, ""])
    async def test_q_is_two_to_eighty_characters(self, monkeypatch, service, q):
        run, _ = service
        async with _client(monkeypatch) as client:
            resp = await client.get("/api/search", params={"q": q})
        assert resp.status_code == 422
        run.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_q_is_required(self, monkeypatch, service):
        async with _client(monkeypatch) as client:
            resp = await client.get("/api/search")
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_cached_five_minutes_by_the_lowercased_q(self, monkeypatch, service):
        _, set_cached = service
        async with _client(monkeypatch) as client:
            await client.get("/api/search", params={"q": "ABBAS Araghchi"})
        key, value, ttl = set_cached.await_args.args
        assert (key, ttl) == ("db:search:v1:abbas araghchi", 300)
        assert value == RESULTS

    @pytest.mark.asyncio
    async def test_serves_the_cached_results(self, monkeypatch, service):
        run, _ = service
        with patch("app.routers.search.get_cached", new_callable=AsyncMock, return_value=RESULTS):
            async with _client(monkeypatch) as client:
                resp = await client.get("/api/search", params={"q": "abbas"})
        assert resp.json() == RESULTS
        run.assert_not_awaited()
