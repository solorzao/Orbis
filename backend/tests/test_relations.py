from datetime import date, datetime, timedelta, timezone

from app.services.relations import (
    MIN_EVENTS,
    MIN_OUTLETS,
    lens_days,
    rank_relations,
    summarise_detail,
)

UTC = timezone.utc


def test_the_lens_is_the_last_7_utc_days_including_today():
    assert lens_days(datetime(2026, 10, 21, 0, 30, tzinfo=UTC)) == (
        date(2026, 10, 15),
        date(2026, 10, 21),
    )


def test_the_lens_follows_utc_not_local_time():
    # 23:30 on the 21st in UTC-5 is 04:30 on the 22nd in UTC.
    local = datetime(2026, 10, 21, 23, 30, tzinfo=timezone(timedelta(hours=-5)))
    assert lens_days(local) == (date(2026, 10, 16), date(2026, 10, 22))


def _row(a="IR", b="US", n=20, q=(2, 1, 12, 5), from_a=5, mentions=300, **over):
    row = {
        "a": a,
        "b": b,
        "n": n,
        "outlets": 4,
        "mentions": mentions,
        "goldstein": -2.0,
        "tone": -3.0,
        "q1": q[0],
        "q2": q[1],
        "q3": q[2],
        "q4": q[3],
        "from_a": from_a,
    }
    row.update(over)
    return row


def test_rank_names_the_class_the_acting_country_and_the_label_points():
    [rel] = rank_relations([_row()], "all", limit=40)
    assert rel["kind"] == "conflict"
    assert rel["from"] == "US"  # IR acts in 5 of 20
    assert rel["a"]["name"] == "Iran" and rel["b"]["iso"] == "US"
    assert rel["quad"] == {
        "verbal_cooperation": 2,
        "material_cooperation": 1,
        "verbal_conflict": 12,
        "material_conflict": 5,
    }
    assert "reports" not in rel


def test_a_class_tie_goes_by_the_goldstein_sign():
    assert (
        rank_relations([_row(q=(5, 5, 5, 5), goldstein=1.0)], "all", 40)[0]["kind"] == "cooperation"
    )
    assert (
        rank_relations([_row(q=(5, 5, 5, 5), goldstein=-1.0)], "all", 40)[0]["kind"] == "conflict"
    )


def test_a_from_tie_goes_to_a():
    assert rank_relations([_row(n=20, from_a=10)], "all", 40)[0]["from"] == "IR"


def test_a_class_filter_names_itself_and_zeroes_the_other_class():
    [rel] = rank_relations([_row(n=17, q=(0, 0, 12, 5), goldstein=1.5)], "conflict", 40)
    assert rel["kind"] == "conflict"  # the filter, whatever the Goldstein sign says
    assert rel["quad"] == {
        "verbal_cooperation": 0,
        "material_cooperation": 0,
        "verbal_conflict": 12,
        "material_conflict": 5,
    }


def test_pairs_without_a_label_point_are_dropped_and_hubs_are_capped():
    rows = [_row(a="ZZ")] + [
        _row(a=c, b="US", mentions=100 - i)
        for i, c in enumerate(["CN", "DE", "FR", "GB", "IL", "IN", "JP"])
    ]
    ranked = rank_relations(rows, "all", 40)
    assert all(r["a"]["iso"] != "ZZ" for r in ranked)
    assert sum("US" in (r["a"]["iso"], r["b"]["iso"]) for r in ranked) == 6


D = date(2026, 10, 21)


def _rows():
    return [
        {
            "a_iso": "US",
            "b_iso": "IR",
            "day": D,
            "quad_class": 3,
            "n_events": 4,
            "mentions": 40,
            "goldstein_sum": -8.0,
            "tone_sum": -12.0,
            "sample_urls": ["https://a.test/1", "javascript:x"],
            "outlets": ["a.test"],
        },
        {
            "a_iso": "IR",
            "b_iso": "US",
            "day": date(2026, 10, 20),
            "quad_class": 1,
            "n_events": 1,
            "mentions": 5,
            "goldstein_sum": 1.0,
            "tone_sum": 2.0,
            "sample_urls": ["https://b.test/2", "https://a.test/1"],
            "outlets": ["b.test"],
        },
    ]


def test_detail_sums_directions_days_and_samples_in_code_order():
    first = date(2026, 10, 15)
    titles = {"https://a.test/1": "Talks - Reuters"}
    detail = summarise_detail("IR", "US", first, D, date(2026, 10, 20), _rows(), titles)
    assert detail["a"]["iso"] == "IR" and detail["b"]["iso"] == "US"
    assert (detail["first_day"], detail["last_day"], detail["since"]) == (
        first,
        D,
        date(2026, 10, 20),
    )
    assert detail["n"] == 5 and detail["outlets"] == 2 and detail["from"] == "US"
    assert "reports" not in detail
    assert [(x["from"], x["to"]) for x in detail["directions"]] == [("IR", "US"), ("US", "IR")]
    assert [x["day"] for x in detail["daily"]] == [first + timedelta(days=i) for i in range(7)]
    assert [s["url"] for s in detail["samples"]] == ["https://a.test/1", "https://b.test/2"]
    assert detail["samples"][0]["title"] == "Talks" and detail["samples"][1]["title"] is None


def test_detail_applies_no_threshold():
    """One event is enough for a detail; only the list has MIN_EVENTS and MIN_OUTLETS."""
    [one] = [r for r in _rows() if r["n_events"] == 1]
    detail = summarise_detail("IR", "US", date(2026, 10, 15), D, D, [one], {})
    assert detail["n"] == 1 < MIN_EVENTS and detail["outlets"] == 1 < MIN_OUTLETS


def test_detail_of_no_rows_is_none():
    assert summarise_detail("IR", "US", date(2026, 10, 15), D, None, [], {}) is None


def test_thresholds_are_named():
    assert (MIN_EVENTS, MIN_OUTLETS) == (5, 2)
