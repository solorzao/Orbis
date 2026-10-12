"""Tests for the co-coverage links between countries (the pool is mocked; no live database)."""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest

from app.services import links
from app.services.links import TOPIC_TAGS, dominant_topic, links_query, rank_links

START = datetime(2026, 10, 5, 12, tzinfo=timezone.utc)
END = datetime(2026, 10, 12, 12, tzinfo=timezone.utc)


def _sql(query: str) -> str:
    return " ".join(query.split())


def _pair(a="IR", b="US", n=10, n_a=20, n_b=50, total=100, **extra) -> dict:
    """A row as the links query returns it."""
    row = {
        "a": a,
        "b": b,
        "n": n,
        "n_a": n_a,
        "n_b": n_b,
        "total": total,
        "tone": -0.3123,
        "from_iso": b,
        **{tag: 0 for tag in TOPIC_TAGS},
    }
    row.update(extra)
    return row


class TestLinksQuery:
    def test_window_without_topic(self):
        sql, *args = links_query(START, END, None)
        flat = _sql(sql)
        assert args == [START, END]
        assert "published_at >= $1 AND published_at <= $2" in flat
        assert "topic_tags &&" not in flat.split("touched AS")[0]
        assert max(int(n) for n in re.findall(r"\$(\d+)", sql)) == len(args)

    def test_topic_filters_the_window(self):
        sql, *args = links_query(START, END, "politics")
        assert args == [START, END, "politics"]
        assert "AND topic_tags && ARRAY[$3::text]" in _sql(sql)
        assert max(int(n) for n in re.findall(r"\$(\d+)", sql)) == len(args)

    def test_drops_self_pairs_and_merges_unordered_pairs(self):
        flat = _sql(links_query(START, END, None)[0])
        assert "array_remove(mentioned_countries, country_code) AS others" in flat
        assert "WHERE cardinality(others) > 0" in flat  # stories naming only themselves
        assert "LEAST(l.country_code, m) AS a, GREATEST(l.country_code, m) AS b" in flat
        assert "FROM linking l, unnest(l.others) AS m GROUP BY 1, 2" in flat
        assert "country_code <> ''" in flat

    def test_from_is_the_most_common_origin(self):
        flat = _sql(links_query(START, END, None)[0])
        # A pair's origin is one of its ends: a when the story's country sorts first.
        assert "count(*) FILTER (WHERE l.country_code < m) AS from_a" in flat
        # Ties go to a, as mode() would break them.
        assert "CASE WHEN 2 * g.from_a >= g.n THEN g.a ELSE g.b END AS from_iso" in flat

    def test_aggregates_hash_rather_than_sort(self):
        """count(DISTINCT) and mode() sort every pair row: 0.40 s, not 0.15, at 7 days locally."""
        flat = _sql(links_query(START, END, None)[0])
        assert "DISTINCT" not in flat and "mode()" not in flat

    def test_counts_each_topic_and_the_totals_for_lift(self):
        flat = _sql(links_query(START, END, None)[0])
        for tag in TOPIC_TAGS:
            assert f"count(*) FILTER (WHERE l.topic_tags && '{{{tag}}}') AS {tag}" in flat
        # Every linking story counts once for each country it touches, its own included.
        assert "unnest(l.others || l.country_code) AS c" in flat
        assert "(SELECT count(*) FROM linking) AS total" in flat
        assert "ta.n AS n_a, tb.n AS n_b" in flat

    @pytest.mark.asyncio
    async def test_get_link_pairs_runs_the_query(self):
        pool = AsyncMock()
        pool.fetch.return_value = [_pair()]
        with patch("app.services.links.get_pool", new_callable=AsyncMock, return_value=pool):
            rows = await links.get_link_pairs(START, END, "conflict")
        assert rows == [_pair()]
        assert pool.fetch.await_args.args[1:] == (START, END, "conflict")


class TestLift:
    def test_lift_is_pair_stories_times_all_over_each_countrys(self):
        # 10 of 100 linking stories join IR (20) and US (50): 10 * 100 / (20 * 50) = 1.0
        [link] = rank_links([_pair()], rank="count", limit=40)
        assert link["lift"] == 1.0
        [link] = rank_links([_pair(n=6, n_a=8, n_b=30, total=200)], rank="count", limit=40)
        assert link["lift"] == 5.0  # 6 * 200 / (8 * 30)

    def test_rounded_to_two_places(self):
        [link] = rank_links([_pair(n=7, n_a=9, n_b=11, total=40)], rank="count", limit=40)
        assert link["lift"] == 2.83  # 280 / 99


class TestRanking:
    def test_lift_needs_five_stories(self):
        rows = [_pair("FR", "US", n=4, n_a=4, n_b=4), _pair("IR", "US", n=5)]
        ranked = rank_links(rows, rank="lift", limit=40)
        assert [(r["a"]["iso"], r["b"]["iso"]) for r in ranked] == [("IR", "US")]

    def test_count_ranks_every_pair_by_stories(self):
        rows = [_pair("FR", "US", n=4), _pair("IR", "US", n=50), _pair("CN", "RU", n=9)]
        ranked = rank_links(rows, rank="count", limit=40)
        assert [r["n"] for r in ranked] == [50, 9, 4]

    def test_lift_ranks_by_lift_then_stories(self):
        rows = [
            _pair("CN", "RU", n=10, n_a=10, n_b=10, total=10),  # lift 1.0
            _pair("IR", "US", n=6, n_a=6, n_b=6, total=60),  # lift 10.0
            _pair("SA", "YE", n=12, n_a=12, n_b=12, total=120),  # lift 10.0, more stories
        ]
        ranked = rank_links(rows, rank="lift", limit=40)
        assert [(r["a"]["iso"], r["b"]["iso"]) for r in ranked] == [
            ("SA", "YE"),
            ("IR", "US"),
            ("CN", "RU"),
        ]

    def test_caps_each_country_at_six_arcs(self):
        partners = ["CA", "CN", "DE", "FR", "GB", "IN", "IR", "JP", "MX", "RU"]
        rows = [_pair(p, "US", n=100 - i) for i, p in enumerate(partners)]
        rows.append(_pair("CN", "RU", n=5))
        ranked = rank_links(rows, rank="count", limit=40)
        us = [r for r in ranked if "US" in (r["a"]["iso"], r["b"]["iso"])]
        assert [r["a"]["iso"] for r in us] == partners[:6]
        assert ("CN", "RU") in [(r["a"]["iso"], r["b"]["iso"]) for r in ranked]

    def test_limit(self):
        rows = [_pair(a, b) for a, b in [("CN", "RU"), ("IR", "US"), ("SA", "YE"), ("FR", "DE")]]
        assert len(rank_links(rows, rank="count", limit=2)) == 2

    def test_pairs_without_a_label_point_are_dropped_and_logged(self, caplog):
        rows = [_pair("SG", "US", n=90), _pair("IR", "US", n=10)]
        with caplog.at_level(logging.DEBUG, logger="app.services.links"):
            ranked = rank_links(rows, rank="count", limit=1)
        assert [(r["a"]["iso"], r["b"]["iso"]) for r in ranked] == [("IR", "US")]
        assert "1 country pair" in caplog.text


class TestLinkFields:
    def test_shape_with_names_and_label_points(self):
        [link] = rank_links([_pair(from_iso="US")], rank="count", limit=40)
        assert link["a"] == {"iso": "IR", "name": "Iran", "lat": 32.52, "lng": 54.29}
        assert link["b"]["name"] == "United States"
        assert link["from"] == "US"
        assert link["n"] == 10
        assert link["tone"] == -0.31

    def test_missing_tone_is_neutral(self):
        [link] = rank_links([_pair(tone=None)], rank="count", limit=40)
        assert link["tone"] == 0.0

    def test_topic_is_the_dominant_one_or_the_filter(self):
        row = _pair(politics=3, conflict=7, health=1)
        assert rank_links([row], rank="count", limit=40)[0]["topic"] == "conflict"
        assert rank_links([row], rank="count", limit=40, topic="health")[0]["topic"] == "health"


class TestDominantTopic:
    def test_most_stories_wins(self):
        assert dominant_topic(_pair(economy=4, technology=2)) == "economy"

    def test_ties_go_to_the_first_of_the_six(self):
        assert dominant_topic(_pair(health=3, politics=3)) == "politics"

    def test_none_is_general(self):
        assert dominant_topic(_pair()) == "general"
