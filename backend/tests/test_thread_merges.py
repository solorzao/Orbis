"""Thread merges and digest headlines (app.services.threads), with a fake connection.

The SQL runs in tests/test_threads_db.py against a real PostgreSQL.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone

import pytest

from app.services import threads
from app.services.threads import (
    MERGE_SIM,
    MERGE_SIM_WITH_ENTITY,
    ThreadInfo,
    is_digest,
    plan_merges,
)
from tests.test_threads import FakeConn, _row

T0 = datetime(2001, 1, 10, 12, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def caught_up(monkeypatch):
    """Each test says whether its cycle is the process's first (the catch-up)."""
    monkeypatch.setattr(threads, "_caught_up", True)


def _info(n_stories: int, *entities: str) -> ThreadInfo:
    return ThreadInfo(n_stories=n_stories, entities=set(entities))


# --- digest headlines -----------------------------------------------------------------


@pytest.mark.parametrize(
    "title",
    [
        "AP News Summary at 6:14 a.m. EDT",
        "AP News in Brief at 12:04 a.m. EDT",
        "  ap news summary at 5:57 a.m. EDT",
        "News in Brief: Tuesday",
        "Today in History: October 20",
        "Morning Briefing - Oct 20",
        "Top stories of the day",
    ],
)
def test_news_digests_are_not_stories(title):
    assert is_digest(title)


@pytest.mark.parametrize(
    "title",
    [
        "The Latest: Hurricane makes landfall in Florida",
        "Summary judgment ordered in Meta case",
        "AP source: Rays near deal with Guardians",
        "Newsom signs climate bill",
        "Top court rejects appeal",
        "Briefings resume at the White House",
    ],
)
def test_stories_are_not_digests(title):
    assert not is_digest(title)


def test_the_backlog_skips_digests_with_the_same_pattern():
    """As for short titles: a headline Python drops but SQL keeps would come back
    every cycle and crowd the backlog."""
    assert f"a.title !~* '{threads.DIGEST_PATTERN}'" in threads.BACKLOG_SQL


def test_the_pattern_is_the_same_in_postgres_and_python():
    """Plain ERE: no \\b (a backspace in Postgres) and no lookarounds."""
    assert "\\b" not in threads.DIGEST_PATTERN
    assert "(?" not in threads.DIGEST_PATTERN
    assert "'" not in threads.DIGEST_PATTERN


@pytest.mark.asyncio
async def test_digests_neither_join_nor_seed_a_thread():
    digest = _row(title="AP News Summary at 6:14 a.m. EDT")
    conn = FakeConn({threads.LOAD_SQL: [digest], threads.ACTIVE_SQL: 0})

    stats = await threads.assign_threads(conn, [digest["id"]], now=T0)

    assert conn.args_of(threads.MEMBER_SQL) == []
    assert stats.assigned == 0


# --- which threads merge --------------------------------------------------------------


def test_a_close_pair_merges_the_smaller_into_the_larger():
    merges = plan_merges([(1, 2, MERGE_SIM)], {1: _info(3), 2: _info(9)}, set())
    assert merges == [(1, 2)]


def test_below_merge_sim_a_pair_needs_a_shared_specific_entity():
    below = MERGE_SIM - 0.001
    infos = {1: _info(3, "Tiger Shroff"), 2: _info(9, "Tiger Shroff", "Mumbai Police")}
    assert plan_merges([(1, 2, below)], infos, set()) == [(1, 2)]
    assert plan_merges([(1, 2, MERGE_SIM_WITH_ENTITY)], infos, set()) == [(1, 2)]
    assert plan_merges([(1, 2, MERGE_SIM_WITH_ENTITY - 0.001)], infos, set()) == []
    assert plan_merges([(1, 2, below)], infos, {"Tiger Shroff"}) == []  # generic
    assert plan_merges([(1, 2, below)], {1: _info(3, "A"), 2: _info(9, "B")}, set()) == []


def test_equal_threads_merge_into_the_older():
    assert plan_merges([(7, 3, 0.9)], {3: _info(4), 7: _info(4)}, set()) == [(7, 3)]


def test_merges_chain_into_one_winner_most_similar_first():
    """A triple (the Houthi strike: 889/508/8780) ends as one thread."""
    infos = {889: _info(6), 508: _info(4), 8780: _info(3)}
    pairs = [(8780, 508, 0.86), (508, 889, 0.89), (889, 508, 0.89)]

    assert plan_merges(pairs, infos, set()) == [(508, 889), (8780, 889)]


def test_a_merge_counts_the_losers_stories_toward_the_next():
    """After 2 (3 stories) joins 1 (3), the group (6) outweighs 5 (5)."""
    infos = {1: _info(3), 2: _info(3), 5: _info(5)}
    merges = plan_merges([(1, 2, 0.95), (2, 5, 0.9)], infos, set())
    assert merges == [(2, 1), (5, 1)]


def test_a_pass_merges_at_most_max_merges(monkeypatch):
    monkeypatch.setattr(threads, "MAX_MERGES", 2)
    infos = {i: _info(1) for i in range(10)}
    pairs = [(i, i + 1, 0.9) for i in range(0, 10, 2)]
    assert len(plan_merges(pairs, infos, set())) == 2


def test_thresholds_are_ordered():
    assert threads.JOIN_SIM_WITH_ENTITY < MERGE_SIM_WITH_ENTITY < MERGE_SIM <= 0.9


# --- the merge pass, wired into the cycle ----------------------------------------------


def _merging_conn(**results):
    answers = {
        threads.LOAD_SQL: [],
        threads.MEMBER_SQL: lambda *args: args[0],
        threads.ACTIVE_SQL: 2,
        threads.AGGREGATE_SQL: [{"id": 1}, {"id": 2}],
        threads.NEIGHBOURS_SQL: [
            {"id": 1, "other": 2, "sim": 0.88},
            {"id": 2, "other": 1, "sim": 0.88},
        ],
        threads.MERGE_INFO_SQL: [
            {"id": 1, "n_stories": 3, "n_articles": 4, "top_entities": []},
            {"id": 2, "n_stories": 8, "n_articles": 9, "top_entities": []},
        ],
    }
    answers.update(results)
    return FakeConn(answers)


@pytest.mark.asyncio
async def test_the_cycles_touched_threads_merge_after_aggregation(caplog):
    article = _row()
    conn = _merging_conn(**{threads.LOAD_SQL: [article], threads.NEW_THREAD_SQL: 1})

    with caplog.at_level(logging.INFO, logger="orbis.threads"):
        stats = await threads.assign_threads(conn, [article["id"]], now=T0)

    # Neighbours of what this cycle touched, under the scoring settings (HNSW).
    assert conn.args_of(threads.NEIGHBOURS_SQL) == [([1], threads.MERGE_NEIGHBOURS)]
    i = next(i for i, c in enumerate(conn.calls) if c[1] == threads.NEIGHBOURS_SQL)
    assert [c[1] for c in conn.calls[i - len(threads.SCORE_SETTINGS) : i]] == list(
        threads.SCORE_SETTINGS
    )
    # 1 (3 stories) into 2 (8), each step in order, in one transaction.
    loser, winner = 1, 2
    merge = [c for c in conn.calls if c[1] in threads.MERGE_STEPS]
    assert [(c[1], c[2]) for c in merge] == [
        (threads.MERGE_MEMBERS_SQL, (winner, loser)),
        (threads.MERGE_WINNER_SQL, (winner, loser)),
        (threads.MERGE_LOSER_SQL, (winner, loser, T0)),
        (threads.DROP_CENTROID_SQL, (loser,)),
        (threads.JOIN_CENTROID_SQL, (winner,)),
    ]
    # The winner is aggregated again, with its new members.
    assert conn.args_of(threads.AGGREGATE_SQL)[-1] == ([winner], T0)
    assert stats.merged == 1
    [summary] = [r.getMessage() for r in caplog.records if " assigned " in r.getMessage()]
    assert re.search(r"; 2 aggregated, 1 merged, 2 active\.$", summary), summary


@pytest.mark.asyncio
async def test_no_neighbour_close_enough_merges_nothing():
    article = _row()
    conn = _merging_conn(
        **{
            threads.LOAD_SQL: [article],
            threads.NEW_THREAD_SQL: 1,
            threads.NEIGHBOURS_SQL: [{"id": 1, "other": 2, "sim": MERGE_SIM_WITH_ENTITY - 0.01}],
        }
    )

    stats = await threads.assign_threads(conn, [article["id"]], now=T0)

    assert conn.args_of(threads.NEIGHBOURS_SQL)
    assert not [c for c in conn.calls if c[1] in threads.MERGE_STEPS]
    assert stats.merged == 0


@pytest.mark.asyncio
async def test_the_first_cycle_catches_up_on_every_listed_active_thread(monkeypatch):
    """Today's duplicates, once per process: then only what each cycle touches."""
    monkeypatch.setattr(threads, "_caught_up", False)
    conn = _merging_conn(**{threads.CATCH_UP_SQL: [{"id": 1}, {"id": 2}]})

    first = await threads.assign_threads(conn, [], now=T0)
    second_conn = _merging_conn()
    await threads.assign_threads(second_conn, [], now=T0)

    catch_up = (T0 - timedelta(hours=72), threads.CATCH_UP_LIMIT)
    assert conn.args_of(threads.CATCH_UP_SQL) == [catch_up]
    assert conn.args_of(threads.NEIGHBOURS_SQL) == [([1, 2], threads.MERGE_NEIGHBOURS)]
    assert first.merged == 1
    assert second_conn.args_of(threads.CATCH_UP_SQL) == []
    assert second_conn.args_of(threads.NEIGHBOURS_SQL) == []  # nothing touched


@pytest.mark.asyncio
async def test_a_failed_merge_is_a_warning_and_the_cycle_finishes(caplog):
    def fail(*_args):
        raise RuntimeError("boom")

    article = _row()
    conn = _merging_conn(
        **{
            threads.MERGE_MEMBERS_SQL: fail,
            threads.LOAD_SQL: [article],
            threads.NEW_THREAD_SQL: 1,
        }
    )
    with caplog.at_level(logging.WARNING, logger="orbis.threads"):
        stats = await threads.assign_threads(conn, [article["id"]], now=T0)

    assert stats.merged == 0
    assert "Merging thread 1 into 2 failed" in caplog.text
    assert conn.args_of(threads.DEACTIVATE_SQL)  # the cycle still finishes


# --- a pass that fails, or stops short ------------------------------------------------


@pytest.mark.asyncio
async def test_a_failed_merge_pass_still_updates_velocity_and_deactivates(caplog):
    def fail(*_args):
        raise RuntimeError("HNSW unavailable")

    article = _row()
    conn = _merging_conn(
        **{threads.LOAD_SQL: [article], threads.NEW_THREAD_SQL: 1, threads.NEIGHBOURS_SQL: fail}
    )
    with caplog.at_level(logging.WARNING, logger="orbis.threads"):
        stats = await threads.assign_threads(conn, [article["id"]], now=T0)

    assert "Thread merge pass failed" in caplog.text
    assert conn.args_of(threads.VELOCITY_SQL) and conn.args_of(threads.DEACTIVATE_SQL)
    assert (stats.assigned, stats.merged) == (1, 0)


@pytest.mark.asyncio
async def test_a_failed_catch_up_is_tried_again_next_cycle(monkeypatch):
    monkeypatch.setattr(threads, "_caught_up", False)

    def fail(*_args):
        raise RuntimeError("boom")

    await threads.assign_threads(_merging_conn(**{threads.CATCH_UP_SQL: fail}), [], now=T0)
    assert threads._caught_up is False

    conn = _merging_conn(**{threads.CATCH_UP_SQL: [{"id": 1}, {"id": 2}]})
    await threads.assign_threads(conn, [], now=T0)
    assert conn.args_of(threads.CATCH_UP_SQL)
    assert threads._caught_up is True


@pytest.mark.asyncio
async def test_a_pass_that_hits_max_merges_catches_up_again_next_cycle(monkeypatch):
    """The rest of the duplicates wait for the next cycle's catch-up, not a restart."""
    monkeypatch.setattr(threads, "MAX_MERGES", 1)
    article = _row()
    conn = _merging_conn(**{threads.LOAD_SQL: [article], threads.NEW_THREAD_SQL: 1})

    stats = await threads.assign_threads(conn, [article["id"]], now=T0)

    assert stats.merged == 1
    assert threads._caught_up is False


@pytest.mark.asyncio
async def test_moved_members_are_budgeted_and_the_rest_wait(monkeypatch, caplog):
    """Each moved member is a non-HOT update into five indexes (about 16 GIN entries):
    a cycle moves at most MAX_MOVED_MEMBERS, always at least one merge, and catches
    up on the rest next cycle."""
    monkeypatch.setattr(threads, "MAX_MOVED_MEMBERS", 10)
    article = _row()
    conn = _merging_conn(
        **{
            threads.LOAD_SQL: [article],
            threads.NEW_THREAD_SQL: 1,
            threads.NEIGHBOURS_SQL: [
                {"id": 1, "other": 2, "sim": 0.9},
                {"id": 3, "other": 4, "sim": 0.89},
                {"id": 5, "other": 6, "sim": 0.88},
            ],
            threads.MERGE_INFO_SQL: [
                {"id": i, "n_stories": n, "n_articles": n, "top_entities": []}
                for i, n in ((1, 6), (2, 20), (3, 5), (4, 20), (5, 3), (6, 20))
            ],
        }
    )
    with caplog.at_level(logging.INFO, logger="orbis.threads"):
        stats = await threads.assign_threads(conn, [article["id"]], now=T0)

    # 6 members moved, then 5 more would pass 10: the third pair (3) waits too.
    moved = [args for args in conn.args_of(threads.MERGE_MEMBERS_SQL)]
    assert moved == [(2, 1)]
    assert stats.merged == 1
    assert threads._caught_up is False
    assert "merge budget" in caplog.text


@pytest.mark.asyncio
async def test_one_merge_bigger_than_the_budget_still_happens(monkeypatch):
    monkeypatch.setattr(threads, "MAX_MOVED_MEMBERS", 2)
    article = _row()
    conn = _merging_conn(**{threads.LOAD_SQL: [article], threads.NEW_THREAD_SQL: 1})

    stats = await threads.assign_threads(conn, [article["id"]], now=T0)

    assert stats.merged == 1  # the loser has 4 members: progress over the budget
