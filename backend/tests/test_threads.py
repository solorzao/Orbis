"""Unit tests for story-thread assignment (app.services.threads), with a fake connection.

The SQL itself runs in tests/test_threads_db.py against a real PostgreSQL.
"""

from __future__ import annotations

import hashlib
import inspect
import logging
import re
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
    is_section_label,
    parse_vector,
    story_entities,
    threadable,
    title_words,
)
from app.services.titles import display_title

T0 = datetime(2001, 1, 10, 12, tzinfo=timezone.utc)
# display_title's source, as shown_title_sql mirrors it.
DISPLAY_TITLE_SHA256 = "3f8ddc927aa4be628776f9ecfd7d0ce80dd018f1ee19617910c75f5b5178d0ae"


@pytest.fixture(autouse=True)
def caught_up(monkeypatch):
    """No catch-up merge pass (test_thread_merges.py tests it)."""
    monkeypatch.setattr(threads, "_caught_up", True)


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


def test_the_backlog_judges_the_title_as_shown_with_the_same_rule():
    """A title Python drops but the backlog's SQL keeps would come back every cycle and
    crowd the backlog (tests/test_threads_db.py runs both on the same titles)."""
    sql = " ".join(threads.BACKLOG_SQL.split())
    assert " ".join(threads.shown_title_sql("a.title").split()) in sql
    assert " ".join(threads.threadable_sql("st.shown", "$2", "a.persons || a.orgs").split()) in sql
    assert "a.title !~*" not in sql


@pytest.mark.parametrize(
    "title",
    [
        "National - The Hindu",  # one word once the outlet's name is off
        "Health | Reuters",
        f"World {chr(0x2013)} BBC News",  # an en dash
        "Police arrest man - BBC News",  # three words shown
        "LIVE: Top stories this morning - CNN",  # a digest once the tag and outlet are off
        "Latest News and Updates - The Hindu",  # four words, all a section's
        "Sports & Business News - Times of India",
    ],
)
def test_titles_are_judged_as_shown(title):
    """Thread 9574, "National": its stories show as "National", "Health" and "World"."""
    assert not threadable(title)


@pytest.mark.parametrize(
    "title",
    [
        "Floods kill twenty in Sindh - The Hindu",
        "Opinion | Why the Fed should wait for more data",
        "Live updates: Storm Austen hits the coast",
        "World leaders meet in Geneva on Tuesday",
        "Health workers strike across Kenya - Nation",
        "Live-action remake tops the box office",
        "Sports: India beat Pakistan in the final",
    ],
)
def test_stories_are_threadable_as_shown(title):
    assert threadable(title)


@pytest.mark.parametrize(
    ("title", "persons", "orgs"),
    [
        ("Queen Elizabeth dies - BBC News", ["Queen Elizabeth"], []),
        ("Biden drops out - Reuters", ["Joe Biden"], []),
        ("Fed holds rates | CNBC", [], ["Federal Reserve"]),
    ],
)
def test_three_words_shown_thread_when_the_article_names_someone(title, persons, orgs):
    """Short headlines about someone ("Biden drops out") are stories; "Police arrest
    man" isn't. Before #102 the outlet's name padded them to MIN_TITLE_WORDS."""
    assert threadable(title, persons, orgs)


@pytest.mark.parametrize(
    ("title", "persons", "orgs"),
    [
        ("Biden drops out - Reuters", [], []),  # no one named
        ("Police arrest man - BBC News", [], []),
        ("Police arrest man - BBC News", [""], [""]),  # empty names name no one
        ("Trump indicted | CNN", ["Donald Trump"], []),  # two words: never
        ("Top News Today - CNN", [], ["CNN"]),  # a section label
        ("News in Brief - AP", [], ["AP"]),  # a digest
    ],
)
def test_short_titles_shown_stay_out_otherwise(title, persons, orgs):
    assert not threadable(title, persons, orgs)


def test_shown_title_sql_mirrors_this_display_title():
    """shown_title_sql repeats display_title's steps in SQL (tests/test_threads_db.py
    compares them, on PostgreSQL only): a change to one needs the other."""
    source = inspect.getsource(display_title)
    assert hashlib.sha256(source.encode()).hexdigest() == DISPLAY_TITLE_SHA256, (
        "display_title changed: update shown_title_sql to match"
    )


def test_the_sql_whitespace_is_pythons():
    """display_title collapses Python's \\s (str.isspace); Postgres' own \\s follows the
    database's locale, so shown_title_sql spells Python's out."""
    spaces = {c for c in map(chr, range(0x110000)) if c.isspace()}
    assert spaces == {c for c in map(chr, range(0x110000)) if re.fullmatch(r"\s", c)}
    assert set(threads.SPACE_CHARS) == spaces


@pytest.mark.parametrize(
    "title",
    [
        "National",
        "World",
        "Health",
        "Business",
        "Sport",
        "Sports",
        "Opinion",
        "Live",
        "Latest News",
        "Breaking News",
        "News & Updates",
        "Latest News and Updates",
        "Top News Headlines Today",
        "  world news  ",
    ],
)
def test_bare_section_labels_are_not_stories(title):
    assert is_section_label(title)


@pytest.mark.parametrize(
    "title",
    [
        "World leaders meet in Geneva",
        "Health workers strike",
        "Newsom signs climate bill",
        "Sports: India win",
        "Livestock prices fall",
        "National Guard deployed to Memphis",
        "Business as usual at the Fed",
    ],
)
def test_stories_are_not_section_labels(title):
    assert not is_section_label(title)


def test_the_section_pattern_is_the_same_in_postgres_and_python():
    """Plain ERE, as DIGEST_PATTERN: no \\b (a backspace in Postgres), no lookarounds."""
    assert "\\b" not in threads.SECTION_PATTERN
    assert "(?" not in threads.SECTION_PATTERN
    assert "'" not in threads.SECTION_PATTERN


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
    assert backlog_args == (T0 - timedelta(hours=6), threads.MIN_TITLE_WORDS, 500, [a, b])
    assert conn.args_of(threads.LOAD_SQL) == [([a, b, c], threads.MAX_BATCH)]


def test_a_cycle_loads_at_most_a_batch_oldest_first():
    """So setup scales with the batch, and a backlog drains over a few cycles."""
    sql = " ".join(threads.LOAD_SQL.split())
    assert sql.endswith("ORDER BY a.published_at, a.id LIMIT $2")


def test_the_backlog_skips_this_cycles_ids_and_takes_the_oldest_first():
    """Its 500 are all left for leftovers (a budget cut, a big embedding cycle), and the
    oldest go first, before they age out of the 6-hour window unassigned."""
    sql = " ".join(threads.BACKLOG_SQL.split())
    assert "AND NOT (a.id = ANY($4::uuid[]))" in sql
    assert "ORDER BY a.published_at LIMIT $3" in sql


@pytest.mark.asyncio
async def test_articles_are_placed_in_published_order_with_the_id_tie_break():
    """A GDELT batch shares one timestamp: the id makes the order deterministic."""
    assert "ORDER BY a.published_at, a.id" in threads.LOAD_SQL
    first, second = _row(), _row(published_at=T0 + timedelta(minutes=1))
    conn = _conn([first, second])

    await _assign(conn, [second["id"], first["id"]])

    assert [m[0] for m in _member_threads(conn)] == [first["id"], second["id"]]


@pytest.mark.asyncio
async def test_a_three_word_title_naming_someone_seeds_a_thread():
    named = _row(title="Biden drops out - Reuters", persons=["Joe Biden"])
    unnamed = _row(title="Police arrest man - BBC News")
    conn = _conn([named, unnamed])

    stats = await _assign(conn, [named["id"], unnamed["id"]])

    assert [m[0] for m in _member_threads(conn)] == [named["id"]]
    assert stats.started == 1


@pytest.mark.asyncio
async def test_section_labels_neither_join_nor_seed_a_thread():
    label = _row(title="National - The Hindu")
    conn = _conn([label], **{threads.SCORE_SQL: [{"ord": 0, "thread_id": 7, "sim": 0.99}]})

    stats = await _assign(conn, [label["id"]])

    assert _member_threads(conn) == []
    assert conn.args_of(threads.NEW_THREAD_SQL) == []
    assert stats.assigned == 0


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
async def test_the_score_query_runs_on_the_hnsw_index_with_a_raised_ef_search():
    article = _row()
    conn = _conn([article])

    await _assign(conn, [article["id"]])

    i = next(i for i, c in enumerate(conn.calls) if c[1] == threads.SCORE_SQL)
    assert conn.calls[i - 4 : i + 2] == [
        ("begin", None, ()),
        ("execute", "SET LOCAL hnsw.ef_search = 100", ()),
        # A seq scan computes every pair: with a few thousand active threads, minutes.
        ("execute", "SET LOCAL enable_seqscan = off", ()),
        # Planned each time under these settings, never from a cached generic plan.
        ("execute", "SET LOCAL plan_cache_mode = force_custom_plan", ()),
        ("fetch", threads.SCORE_SQL, ([0], ["[1,0]"], threads.CANDIDATES)),
        ("commit", None, ()),
    ]


def test_the_score_query_parses_each_query_vector_once():
    """Not once per (article, centroid) pair inside the LATERAL: 2M parses a cycle."""
    sql = " ".join(threads.SCORE_SQL.split())
    assert sql.startswith(
        "WITH q AS MATERIALIZED ( SELECT a.ord, a.t::halfvec(512) AS v"
        " FROM unnest($1::int[], $2::text[]) AS a(ord, t) )"
    )
    lateral = sql[sql.index("CROSS JOIN LATERAL") :]
    assert "::halfvec" not in lateral
    assert "ORDER BY centroid <#> q.v LIMIT $3" in lateral


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
    assert conn.args_of(threads.REACTIVATE_SQL) == [(7,)]
    assert threads.REACTIVATE_SQL.rstrip().endswith("ON CONFLICT (thread_id) DO NOTHING")
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
        **{threads.RESCORE_SQL: [{"thread_id": 101, "sim": 0.9}], threads.SUM_SQL: "[1,0]"},
    )

    stats = await _assign(conn, [first["id"], second["id"]])

    assert conn.args_of(threads.RESCORE_SQL) == [("[0.9,0.43]", [101])]
    assert _member_threads(conn) == [(first["id"], 101, 1.0), (second["id"], 101, 0.9)]
    assert (stats.started, stats.joined) == (1, 1)


@pytest.mark.asyncio
async def test_a_thread_started_this_cycle_shares_its_members_entities():
    first = _row(persons=["Zz Jane Specific"])
    second = _row(persons=["Zz Jane Specific"], published_at=T0 + timedelta(minutes=1))
    conn = _conn([first, second], **{threads.RESCORE_SQL: [{"thread_id": 101, "sim": 0.7}]})

    stats = await _assign(conn, [first["id"], second["id"]])

    assert _member_threads(conn) == [(first["id"], 101, 1.0), (second["id"], 101, 0.7)]
    assert stats.joined == 1


@pytest.mark.asyncio
async def test_a_candidate_joined_earlier_in_the_cycle_is_rescored_on_its_new_centroid():
    first = _row(v="[1,0]")
    second = _row(v="[0.8,0.6]", published_at=T0 + timedelta(minutes=1))
    conn = _conn(
        [first, second],
        **{
            threads.SCORE_SQL: [
                {"ord": 0, "thread_id": 7, "sim": 0.9},
                {"ord": 1, "thread_id": 7, "sim": 0.7},  # against 7's centroid before `first`
            ],
            threads.RESCORE_SQL: [{"thread_id": 7, "sim": 0.85}],
            threads.SUM_SQL: "[1,0]",
        },
    )

    stats = await _assign(conn, [first["id"], second["id"]])

    assert conn.args_of(threads.RESCORE_SQL) == [("[0.8,0.6]", [7])]  # only for `second`
    assert _member_threads(conn) == [(first["id"], 7, 0.9), (second["id"], 7, 0.85)]
    assert stats.joined == 2


@pytest.mark.asyncio
async def test_a_thread_started_this_cycle_matches_on_its_top_8_entities():
    """As an existing thread matches on its top_entities: counted per story."""
    common = [f"Zz Person {i}" for i in range(8)]
    seed = _row(persons=common, orgs=["Zz Rare Org"])
    again = _row(persons=common, v="[0.9,0.1]", published_at=T0 + timedelta(minutes=1))
    rare = _row(persons=["Zz Rare Org"], v="[0.7,0.3]", published_at=T0 + timedelta(minutes=2))
    conn = _conn(
        [seed, again, rare],
        **{
            threads.RESCORE_SQL: lambda v, ids: [
                {"thread_id": 101, "sim": 0.9 if v == again["v"] else 0.7}
            ]
        },
    )

    await _assign(conn, [seed["id"], again["id"], rare["id"]])

    assert _member_threads(conn) == [
        (seed["id"], 101, 1.0),
        (again["id"], 101, 0.9),
        (rare["id"], 102, 1.0),  # its only shared name isn't in 101's top 8
    ]


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
    """Once the minimum is placed, oldest first."""
    clock = [0.0]
    monkeypatch.setattr(threads, "time", SimpleNamespace(monotonic=lambda: clock[0]))
    monkeypatch.setattr(threads, "MIN_PLACED", 2)

    def member(*args):
        clock[0] += threads.TIME_BUDGET_S + 1
        return args[0]

    rows = [_row(), _row(), _row(), _row()]
    conn = _conn(rows, **{threads.MEMBER_SQL: member})

    stats = await _assign(conn, [r["id"] for r in rows])

    assert [m[0] for m in _member_threads(conn)] == [rows[0]["id"], rows[1]["id"]]
    assert (stats.assigned, stats.deferred) == (2, 2)
    assert conn.args_of(threads.AGGREGATE_SQL)  # the cycle still finishes


@pytest.mark.asyncio
async def test_slow_setup_never_starves_placement(monkeypatch):
    """The 2026-10-19 stall: scoring took 4 minutes, the budget (counted from the
    start) had run out at the first article, and every article was deferred, every
    cycle. The budget counts placement only."""
    clock = [0.0]
    monkeypatch.setattr(threads, "time", SimpleNamespace(monotonic=lambda: clock[0]))

    def slow_score(*_args):
        clock[0] += 300  # setup far over the budget
        return []

    rows = [_row(), _row(), _row()]
    conn = _conn(rows, **{threads.SCORE_SQL: slow_score})

    stats = await _assign(conn, [r["id"] for r in rows])

    assert (stats.assigned, stats.deferred) == (3, 0)
    assert stats.score_seconds == 300


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
    assert conn.args_of(threads.AGGREGATE_SQL) == [([], T0)]
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
    # Centroid rows are written only when the centroid changes: never here.
    assert not [c for c in conn.calls if "UPDATE thread_centroids" in (c[1] or "")]


def test_deactivation_reads_the_threads_last_seen_and_stories():
    """Not thread_centroids' own columns, so they never need rewriting (each rewrite
    leaves a dead HNSW entry)."""
    sql = " ".join(threads.DEACTIVATE_SQL.split())
    assert sql == (
        "DELETE FROM thread_centroids c USING threads t WHERE c.thread_id = t.id"
        " AND (t.last_seen < $1 OR (t.n_stories <= 1 AND t.last_seen < $2))"
    )


def test_the_repair_pick_up_is_every_unaggregated_thread():
    sql = " ".join(threads.AGGREGATE_SQL.split())
    assert "WHERE id = ANY($1::bigint[]) OR aggregated_at IS NULL )" in sql
    assert "aggregated_at IS NULL OR last_seen > aggregated_at" not in sql


@pytest.mark.asyncio
async def test_articles_past_the_batch_count_as_left_to_the_backlog(monkeypatch, caplog):
    monkeypatch.setattr(threads, "MAX_BATCH", 2)
    a, b, c = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    rows = [_row(id=a), _row(id=b)]  # LOAD_SQL's oldest two
    conn = _conn(rows, **{threads.BACKLOG_SQL: [{"id": c}]})

    with caplog.at_level(logging.WARNING, logger="orbis.threads"):
        stats = await _assign(conn, [a, b])

    assert (stats.assigned, stats.deferred) == (2, 1)
    assert "1 left to the backlog" in caplog.text


@pytest.mark.asyncio
async def test_logs_one_summary_line(caplog):
    article = _row()
    conn = _conn([article], **{threads.ACTIVE_SQL: 3, threads.AGGREGATE_SQL: [{"id": 101}]})

    with caplog.at_level(logging.INFO, logger="orbis.threads"):
        await _assign(conn, [article["id"]])

    lines = [r.getMessage() for r in caplog.records if r.getMessage().startswith("Threads:")]
    [summary] = lines
    assert summary.startswith("Threads: 1 assigned (0 joined, 1 started, 0 copies) in ")
    # Each phase's time, so a slow one shows in the log.
    assert re.search(
        r" s \(load [\d.]+, score [\d.]+, place [\d.]+, finish [\d.]+ s\);"
        r" 1 aggregated, 0 merged, 3 active\.$",
        summary,
    ), summary


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
