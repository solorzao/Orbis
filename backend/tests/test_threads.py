"""Unit tests for story-thread assignment (app.services.threads), with a fake connection.

The SQL itself runs in tests/test_threads_db.py against a real PostgreSQL.
"""

from __future__ import annotations

import logging
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.services import threads
from app.services.threads import (
    JOIN_SIM,
    JOIN_SIM_WITH_ENTITY,
    choose,
    decayed_sum,
    format_vector,
    parse_vector,
    story_entities,
    title_words,
)

T0 = datetime(2001, 1, 10, 12, tzinfo=timezone.utc)


class FakeTransaction:
    def __init__(self, conn):
        self.conn = conn

    async def __aenter__(self):
        self.conn.calls.append(("begin", None, ()))
        return self

    async def __aexit__(self, exc_type, exc, tb):
        self.conn.calls.append(("rollback" if exc_type else "commit", None, ()))
        return False


class FakeConn:
    """Records every call; answers each statement from *results*, keyed by its SQL.

    A result is a value, or a function of the call's arguments.
    """

    def __init__(self, results=None):
        self.results = dict(results or {})
        self.calls: list[tuple[str, str | None, tuple]] = []

    def _answer(self, sql, args, default):
        result = self.results.get(sql, default)
        return result(*args) if callable(result) else result

    async def fetch(self, sql, *args):
        self.calls.append(("fetch", sql, args))
        return self._answer(sql, args, [])

    async def fetchval(self, sql, *args):
        self.calls.append(("fetchval", sql, args))
        return self._answer(sql, args, None)

    async def execute(self, sql, *args):
        self.calls.append(("execute", sql, args))
        return self._answer(sql, args, "UPDATE 0")

    async def executemany(self, sql, args):
        self.calls.append(("executemany", sql, (args,)))

    def transaction(self):
        return FakeTransaction(self)

    def args_of(self, sql):
        return [args for _, called, args in self.calls if called == sql]


def _row(title="Zz quake hits the old city", story_key=None, v="[1,0]", **fields):
    row = {
        "id": uuid.uuid4(),
        "v": v,
        "persons": [],
        "orgs": [],
        "title": title,
        "story_key": story_key,
        "source_name": "zz.example",
        "published_at": T0,
        "latitude": 10.5,
        "longitude": 20.5,
        "region": "Zz City",
        "country_code": "ZZ",
        "topic": "politics",
        "sentiment_score": -1.5,
        "has_https_image": True,
    }
    row.update(fields)
    return row


def _new_thread_ids(start=101):
    ids = iter(range(start, start + 100))
    return lambda *_args: next(ids)


def _member_threads(conn):
    """(article id, thread id, similarity) per member insert, in order."""
    return [(args[0], args[1], args[13]) for args in conn.args_of(threads.MEMBER_SQL)]


def _conn(rows, **results):
    """A connection that loads *rows* and inserts every member."""
    answers = {
        threads.LOAD_SQL: rows,
        threads.MEMBER_SQL: lambda *args: args[0],
        threads.NEW_THREAD_SQL: _new_thread_ids(),
        threads.SUM_SQL: "[0,0]",
        threads.ACTIVE_SQL: 0,
    }
    answers.update(results)
    return FakeConn(answers)


async def _assign(conn, ids=None):
    return await threads.assign_threads(conn, ids if ids is not None else [], now=T0)


# --- pure rules ---------------------------------------------------------------


def test_title_words_is_the_backlog_sql_rule():
    """btrim(title) drops spaces only, then '\\s+' splits: a leading tab or newline
    counts an empty first word, in SQL and here alike."""
    assert title_words("Police arrest man") == 3
    assert title_words("  Police arrest   local man  ") == 4
    assert title_words("\tPolice arrest man") == 4
    assert title_words("Police arrest man\n") == 4
    assert title_words("") == 1
    assert title_words(None) == 1


def test_the_backlog_filters_short_titles_with_the_same_rule():
    assert (
        r"array_length(regexp_split_to_array(btrim(a.title), '\s+'), 1) >= $2"
        in threads.BACKLOG_SQL
    )


def test_story_entities_caps_persons_and_orgs_separately():
    persons = [f"Person {i}" for i in range(10)]
    orgs = [f"Org {i}" for i in range(3)]
    assert story_entities(persons, orgs) == persons[:8] + orgs
    assert story_entities(None, ["Org", "Org", ""]) == ["Org"]


@pytest.mark.parametrize(
    ("sim", "joins"),
    [(JOIN_SIM, True), (JOIN_SIM - 0.001, False), (0.95, True)],
)
def test_choose_joins_on_similarity_alone_at_join_sim(sim, joins):
    choice = choose({7: sim}, [], {7: set()}, set())
    assert choice == ((7, sim) if joins else None)


@pytest.mark.parametrize(
    ("sim", "joins"),
    [(JOIN_SIM_WITH_ENTITY, True), (JOIN_SIM_WITH_ENTITY - 0.001, False), (0.7, True)],
)
def test_choose_joins_at_the_lower_threshold_with_a_shared_specific_entity(sim, joins):
    choice = choose({7: sim}, ["Jane Doe"], {7: {"Jane Doe", "Acme"}}, set())
    assert choice == ((7, sim) if joins else None)


def test_choose_ignores_generic_entities():
    assert choose({7: 0.7}, ["Donald Trump"], {7: {"Donald Trump"}}, {"Donald Trump"}) is None
    assert choose(
        {7: 0.7}, ["Donald Trump", "Jane Doe"], {7: {"Donald Trump", "Jane Doe"}}, {"Donald Trump"}
    ) == (7, 0.7)


def test_choose_without_a_shared_entity_needs_join_sim():
    assert choose({7: 0.7}, ["Jane Doe"], {7: {"Acme"}}, set()) is None


def test_choose_takes_the_most_similar_then_the_lower_id():
    entities = {3: {"Jane Doe"}, 4: set(), 5: set()}
    assert choose({3: 0.7, 4: 0.85, 5: 0.9}, ["Jane Doe"], entities, set()) == (5, 0.9)
    assert choose({5: 0.85, 4: 0.85}, [], entities, set()) == (4, 0.85)


def test_decayed_sum_and_vector_text():
    assert decayed_sum([1.0, 2.0], [0.5, 0.0]) == pytest.approx([threads.DECAY + 0.5, 2 * 0.97])
    assert parse_vector("[0.5,-1,2e-3]") == [0.5, -1.0, 0.002]
    assert parse_vector(format_vector([0.123456789, -1.0])) == pytest.approx([0.123456789, -1.0])


# --- assign_threads -----------------------------------------------------------


@pytest.mark.asyncio
async def test_loads_the_input_and_the_backlog_once_each():
    a, b, c = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    conn = _conn([], **{threads.BACKLOG_SQL: [{"id": b}, {"id": c}]})

    await _assign(conn, [a, b])

    [backlog_args] = conn.args_of(threads.BACKLOG_SQL)
    assert backlog_args == (T0 - timedelta(hours=6), threads.MIN_TITLE_WORDS, 500)
    assert conn.args_of(threads.LOAD_SQL) == [([a, b, c],)]


@pytest.mark.asyncio
async def test_articles_are_placed_in_published_order_with_the_id_tie_break():
    """A GDELT batch shares one timestamp: the id makes the order deterministic."""
    assert "ORDER BY a.published_at, a.id" in threads.LOAD_SQL
    first, second = _row(), _row(published_at=T0 + timedelta(minutes=1))
    conn = _conn([first, second])

    await _assign(conn, [second["id"], first["id"]])

    assert [m[0] for m in _member_threads(conn)] == [first["id"], second["id"]]


@pytest.mark.asyncio
async def test_short_titles_neither_join_nor_seed_a_thread():
    short = _row(title="Police arrest man")
    conn = _conn([short], **{threads.SCORE_SQL: [{"ord": 0, "thread_id": 7, "sim": 0.99}]})

    stats = await _assign(conn, [short["id"]])

    assert _member_threads(conn) == []
    assert conn.args_of(threads.NEW_THREAD_SQL) == []
    assert conn.args_of(threads.SCORE_SQL) == []
    assert stats.assigned == 0


@pytest.mark.asyncio
async def test_a_new_story_seeds_a_thread_with_its_vector_and_display_title():
    article = _row(title="Zz quake hits the old city - Reuters", v="[0.6,0.8]")
    conn = _conn([article])

    stats = await _assign(conn, [article["id"]])

    [(v, published_at, lead_id, lead_title)] = conn.args_of(threads.NEW_THREAD_SQL)
    assert (v, published_at, lead_id) == ("[0.6,0.8]", T0, article["id"])
    assert lead_title == "Zz quake hits the old city"
    assert conn.args_of(threads.NEW_CENTROID_SQL) == [(101, T0, "[0.6,0.8]")]
    assert _member_threads(conn) == [(article["id"], 101, 1.0)]
    assert (stats.started, stats.assigned, stats.touched) == (1, 1, {101})


@pytest.mark.asyncio
async def test_the_score_query_runs_under_a_raised_ef_search():
    article = _row()
    conn = _conn([article])

    await _assign(conn, [article["id"]])

    i = next(i for i, c in enumerate(conn.calls) if c[1] == threads.SCORE_SQL)
    assert conn.calls[i - 2 : i + 2] == [
        ("begin", None, ()),
        ("execute", "SET LOCAL hnsw.ef_search = 100", ()),
        ("fetch", threads.SCORE_SQL, ([0], ["[1,0]"], threads.CANDIDATES)),
        ("commit", None, ()),
    ]


@pytest.mark.asyncio
async def test_a_story_joins_its_best_candidate_with_the_decayed_sum():
    article = _row(v="[0,1]")
    conn = _conn(
        [article],
        **{
            threads.SCORE_SQL: [
                {"ord": 0, "thread_id": 7, "sim": 0.81},
                {"ord": 0, "thread_id": 8, "sim": 0.9},
            ],
            threads.SUM_SQL: "[1,0]",
        },
    )

    stats = await _assign(conn, [article["id"]])

    assert _member_threads(conn) == [(article["id"], 8, 0.9)]
    assert conn.args_of(threads.SUM_SQL) == [(8,)]
    [(thread_id, new_sum, last_seen)] = conn.args_of(threads.JOIN_THREAD_SQL)
    assert (thread_id, last_seen) == (8, T0)
    assert parse_vector(new_sum) == pytest.approx([threads.DECAY, 1.0])
    assert conn.args_of(threads.JOIN_CENTROID_SQL) == [(8,)]
    assert conn.args_of(threads.NEW_THREAD_SQL) == []
    assert (stats.joined, stats.touched) == (1, {8})


@pytest.mark.asyncio
async def test_a_copy_joins_its_storys_thread_without_adding_its_vector():
    copy = _row(story_key=42, v="[0,1]")
    conn = _conn(
        [copy],
        **{
            threads.STORY_THREADS_SQL: [{"story_key": 42, "thread_id": 7}],
            threads.SCORE_SQL: [{"ord": 0, "thread_id": 9, "sim": 0.99}],
        },
    )

    stats = await _assign(conn, [copy["id"]])

    assert conn.args_of(threads.STORY_THREADS_SQL) == [([42],)]
    assert _member_threads(conn) == [(copy["id"], 7, 1.0)]
    assert conn.args_of(threads.COPY_THREAD_SQL) == [(7, T0)]
    assert conn.args_of(threads.COPY_CENTROID_SQL) == [(7,)]
    assert conn.args_of(threads.SUM_SQL) == []
    assert conn.args_of(threads.JOIN_THREAD_SQL) == []
    assert (stats.copies, stats.joined, stats.touched) == (1, 0, {7})


@pytest.mark.asyncio
async def test_a_copy_of_a_story_assigned_earlier_in_the_cycle_joins_its_thread():
    first = _row(story_key=42)
    copy = _row(story_key=42, v="[0,1]", published_at=T0 + timedelta(minutes=1))
    conn = _conn([first, copy])

    stats = await _assign(conn, [first["id"], copy["id"]])

    assert _member_threads(conn) == [(first["id"], 101, 1.0), (copy["id"], 101, 1.0)]
    assert conn.args_of(threads.COPY_THREAD_SQL) == [(101, copy["published_at"])]
    assert (stats.started, stats.copies) == (1, 1)


@pytest.mark.asyncio
async def test_a_story_joins_a_thread_started_earlier_in_the_cycle():
    first = _row(v="[1,0]")
    second = _row(v="[0.9,0.43]", published_at=T0 + timedelta(minutes=1))
    conn = _conn(
        [first, second],
        **{threads.NEW_SCORE_SQL: [{"thread_id": 101, "sim": 0.9}], threads.SUM_SQL: "[1,0]"},
    )

    stats = await _assign(conn, [first["id"], second["id"]])

    assert conn.args_of(threads.NEW_SCORE_SQL) == [("[0.9,0.43]", [101])]
    assert _member_threads(conn) == [(first["id"], 101, 1.0), (second["id"], 101, 0.9)]
    assert (stats.started, stats.joined) == (1, 1)


@pytest.mark.asyncio
async def test_a_thread_started_this_cycle_shares_its_members_entities():
    first = _row(persons=["Zz Jane Specific"])
    second = _row(persons=["Zz Jane Specific"], published_at=T0 + timedelta(minutes=1))
    conn = _conn([first, second], **{threads.NEW_SCORE_SQL: [{"thread_id": 101, "sim": 0.7}]})

    stats = await _assign(conn, [first["id"], second["id"]])

    assert _member_threads(conn) == [(first["id"], 101, 1.0), (second["id"], 101, 0.7)]
    assert stats.joined == 1


@pytest.mark.asyncio
async def test_generic_entities_do_not_count_as_shared():
    article = _row(persons=["Zz Generic"])
    conn = _conn(
        [article],
        **{
            threads.GENERIC_SQL: [{"e": "Zz Generic"}],
            threads.SCORE_SQL: [{"ord": 0, "thread_id": 7, "sim": 0.7}],
            threads.CANDIDATE_ENTITIES_SQL: [{"id": 7, "top_entities": ["Zz Generic"]}],
        },
    )

    await _assign(conn, [article["id"]])

    assert conn.args_of(threads.GENERIC_SQL) == [(threads.GENERIC_ENTITY_SHARE,)]
    assert conn.args_of(threads.CANDIDATE_ENTITIES_SQL) == [([7],)]
    assert _member_threads(conn) == [(article["id"], 101, 1.0)]  # a thread of its own


@pytest.mark.asyncio
async def test_an_article_already_a_member_changes_no_centroid():
    article = _row()
    conn = _conn(
        [article],
        **{
            threads.SCORE_SQL: [{"ord": 0, "thread_id": 7, "sim": 0.9}],
            threads.MEMBER_SQL: None,  # ON CONFLICT DO NOTHING
        },
    )

    stats = await _assign(conn, [article["id"]])

    assert conn.args_of(threads.SUM_SQL) == []
    assert conn.args_of(threads.JOIN_THREAD_SQL) == []
    assert conn.args_of(threads.JOIN_CENTROID_SQL) == []
    assert (stats.assigned, stats.joined, stats.touched) == (0, 0, set())


@pytest.mark.asyncio
async def test_a_new_thread_for_an_article_already_a_member_is_rolled_back():
    article = _row()
    conn = _conn([article], **{threads.MEMBER_SQL: None})

    stats = await _assign(conn, [article["id"]])

    member = next(i for i, c in enumerate(conn.calls) if c[1] == threads.MEMBER_SQL)
    assert conn.calls[member + 1] == ("rollback", None, ())
    assert (stats.assigned, stats.started, stats.failed) == (0, 0, 0)


@pytest.mark.asyncio
async def test_the_time_budget_leaves_the_rest_to_the_backlog(monkeypatch):
    clock = [0.0]
    monkeypatch.setattr(threads, "time", SimpleNamespace(monotonic=lambda: clock[0]))

    def member(*args):
        clock[0] += threads.TIME_BUDGET_S + 1
        return args[0]

    rows = [_row(), _row(), _row()]
    conn = _conn(rows, **{threads.MEMBER_SQL: member})

    stats = await _assign(conn, [r["id"] for r in rows])

    assert [m[0] for m in _member_threads(conn)] == [rows[0]["id"]]
    assert (stats.assigned, stats.deferred) == (1, 2)
    assert conn.args_of(threads.AGGREGATE_SQL)  # the cycle still finishes


@pytest.mark.asyncio
async def test_one_failed_article_does_not_stop_the_others(caplog):
    bad, good = _row(), _row(published_at=T0 + timedelta(minutes=1))

    def member(*args):
        if args[0] == bad["id"]:
            raise RuntimeError("boom")
        return args[0]

    conn = _conn([bad, good], **{threads.MEMBER_SQL: member})
    with caplog.at_level(logging.WARNING, logger="orbis.threads"):
        stats = await _assign(conn, [bad["id"], good["id"]])

    assert (stats.failed, stats.assigned) == (1, 1)
    assert f"Thread assignment failed for article {bad['id']}" in caplog.text
    assert "1 failed" in caplog.text


@pytest.mark.asyncio
async def test_every_cycle_finishes_even_with_nothing_to_assign():
    conn = _conn([])

    stats = await _assign(conn, [])

    assert conn.args_of(threads.LOAD_SQL) == []
    assert conn.args_of(threads.AGGREGATE_SQL) == [([], T0, T0 - timedelta(hours=72))]
    assert conn.args_of(threads.VELOCITY_SQL) == [
        (T0 - timedelta(hours=6), T0 - timedelta(hours=72))
    ]
    assert conn.args_of(threads.DEACTIVATE_SQL) == [
        (T0 - timedelta(hours=72), T0 - timedelta(hours=24))
    ]
    assert stats.assigned == 0


@pytest.mark.asyncio
async def test_aggregates_cover_the_touched_threads_and_set_display_lead_titles():
    article = _row()
    conn = _conn(
        [article],
        **{
            threads.AGGREGATE_SQL: [{"id": 101}, {"id": 5}],
            threads.LEAD_TITLES_SQL: [
                {"id": 101, "title": "Zz quake hits the old city | BBC News"},
                {"id": 5, "title": "WATCH: Zz floods rise - AP"},
            ],
        },
    )

    await _assign(conn, [article["id"]])

    assert conn.args_of(threads.AGGREGATE_SQL)[0][0] == [101]
    assert conn.args_of(threads.LEAD_TITLES_SQL) == [([101, 5],)]
    assert conn.args_of(threads.LEAD_TITLE_SQL) == [
        ([(101, "Zz quake hits the old city"), (5, "Zz floods rise")],)
    ]
    assert conn.args_of(threads.CENTROID_COUNTS_SQL) == [([101, 5],)]


@pytest.mark.asyncio
async def test_logs_one_summary_line(caplog):
    article = _row()
    conn = _conn([article], **{threads.ACTIVE_SQL: 3})

    with caplog.at_level(logging.INFO, logger="orbis.threads"):
        await _assign(conn, [article["id"]])

    [line] = [r.getMessage() for r in caplog.records if r.getMessage().startswith("Threads:")]
    assert line.startswith("Threads: 1 assigned (0 joined, 1 started, 0 copies) in ")
    assert line.endswith(" s; 3 active.")


@pytest.mark.asyncio
async def test_takes_a_pool_or_a_connection():
    conn = _conn([])

    class Pool:
        @asynccontextmanager
        async def acquire(self):
            yield conn

    await threads.assign_threads(Pool(), [], now=T0)

    assert conn.args_of(threads.AGGREGATE_SQL)


@pytest.mark.asyncio
async def test_purge_threads_deletes_members_then_threads_before_the_window():
    conn = FakeConn()

    await threads.purge_threads(conn, 30, now=T0)

    assert [(c[1], c[2]) for c in conn.calls] == [
        (threads.PURGE_MEMBERS_SQL, (T0, 30)),
        (threads.PURGE_THREADS_SQL, (T0, 30)),
    ]
