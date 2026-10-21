"""GDELT Events parsing and aggregation (no database, no network)."""

from __future__ import annotations

import io
import zipfile
from datetime import date, datetime, timedelta, timezone

import pytest

from app.services import events
from app.services.events import (
    Rollup,
    lost_slots,
    parse_events,
    plan_slots,
    read_export,
    slot_of,
    slot_url,
)

TODAY = date(2026, 10, 21)


def _event(**over) -> str:
    """One 61-column export row: USA acts on IRN, verbal conflict, unless overridden."""
    fields = [""] * events.COLUMNS
    fields[0] = str(over.pop("event_id", 1))
    fields[events._ACTOR1_COUNTRY] = over.pop("a", "USA")
    fields[events._ACTOR2_COUNTRY] = over.pop("b", "IRN")
    fields[events._IS_ROOT] = over.pop("root", "1")
    fields[events._QUAD_CLASS] = over.pop("quad", "3")
    fields[events._GOLDSTEIN] = over.pop("goldstein", "-2.0")
    fields[events._NUM_MENTIONS] = over.pop("mentions", "10")
    fields[events._AVG_TONE] = over.pop("tone", "-3.5")
    fields[events._DATE_ADDED] = over.pop("added", "20261021121500")
    fields[events._SOURCE_URL] = over.pop("url", "https://www.example.com/a")
    assert not over, over
    return "\t".join(fields)


def _parse(*rows: str) -> tuple[dict, events.ParseStats]:
    rollups: dict = {}
    stats = parse_events("\n".join(rows) + "\n", TODAY, rollups)
    return rollups, stats


def test_one_event_makes_one_rollup():
    rollups, stats = _parse(_event())
    r = rollups[("US", "IR", TODAY, 3)]
    assert (r.n_events, r.mentions, r.goldstein_sum, r.tone_sum) == (1, 10, -2.0, -3.5)
    assert r.samples == ["https://www.example.com/a"]
    assert r.outlets == ["example.com"]
    assert (stats.rows, stats.kept, stats.not_root) == (1, 1, 0)


def test_only_root_events_count():
    """Decision 3: an event outside the lead paragraph adds nothing."""
    rollups, stats = _parse(_event(root="0"), _event(root=""))
    assert rollups == {}
    assert (stats.rows, stats.kept, stats.not_root) == (2, 0, 2)


def test_events_add_up_and_a_repeated_source_is_kept_once():
    rollups, _ = _parse(_event(), _event(mentions="5", goldstein="-4.0"))
    r = rollups[("US", "IR", TODAY, 3)]
    assert (r.n_events, r.mentions, r.goldstein_sum) == (2, 15, -6.0)
    assert r.samples == ["https://www.example.com/a"] and r.outlets == ["example.com"]


def test_a_control_character_inside_a_field_never_splits_a_row():
    """Rows split on "\\n" only: str.splitlines() would also split on \\x0c, \\x1c or
    \\u2028 inside a field (an actor name, a URL) and lose the event as malformed."""
    fields = _event().split("\t")
    fields[6] = "ACME\x0cCORP PLC"  # Actor1Name
    rollups, stats = _parse("\t".join(fields))
    assert (stats.rows, stats.kept, stats.malformed) == (1, 1, 0)


def test_unmapped_blank_and_regional_actors_are_dropped_and_counted():
    rollups, stats = _parse(_event(a=""), _event(b="AFR"), _event(a="EUR", b="XYZ"))
    assert rollups == {}
    assert stats.no_pair == 3
    assert stats.unmapped == {"AFR": 1, "EUR": 1, "XYZ": 1}


def test_domestic_events_are_dropped():
    rollups, stats = _parse(_event(a="USA", b="USA"))
    assert rollups == {} and stats.same_country == 1


@pytest.mark.parametrize(
    "row",
    [
        "too\tfew\tfields",
        _event(quad="5"),
        _event(quad="x"),
        _event(goldstein="nan"),
        _event(goldstein="11"),
        _event(mentions="-1"),
        _event(tone="inf"),
        _event(added="2026"),
        _event(added="2026102112150"),
    ],
)
def test_malformed_rows_are_counted_and_skipped(row):
    rollups, stats = _parse(row)
    assert rollups == {} and stats.malformed == 1


def test_events_added_before_retention_are_stale():
    old = (TODAY - timedelta(days=9)).strftime("%Y%m%d") + "000000"
    rollups, stats = _parse(_event(added=old))
    assert rollups == {} and stats.stale == 1


def test_a_non_web_source_still_counts_but_is_never_kept():
    rollups, _ = _parse(_event(url="javascript:alert(1)"), _event(url="BBC Monitoring, 21 Oct"))
    r = rollups[("US", "IR", TODAY, 3)]
    assert r.n_events == 2 and r.samples == [] and r.outlets == []


def test_samples_and_outlets_are_capped_first_seen_first():
    urls = [f"https://site{i}.test/a" for i in range(10)]
    rollups, _ = _parse(*(_event(url=u) for u in urls))
    r = rollups[("US", "IR", TODAY, 3)]
    assert r.samples == urls[: events.MAX_SAMPLES]
    assert r.outlets == [f"site{i}.test" for i in range(events.MAX_OUTLETS)]


def test_merging_a_files_rollup_adds_sums_and_keeps_caps():
    """A cycle parses each file on its own and merges it only once it parsed whole."""
    into, part = Rollup(), Rollup()
    into.add(10, -2.0, -3.0, "https://a.test/1")
    for i in range(9):
        part.add(1, 1.0, 1.0, f"https://s{i}.test/x")
    into.merge(part)
    assert (into.n_events, into.mentions, into.goldstein_sum, into.tone_sum) == (10, 19, 7.0, 6.0)
    assert into.samples == ["https://a.test/1", "https://s0.test/x", "https://s1.test/x"]
    assert len(into.outlets) == events.MAX_OUTLETS and into.outlets[0] == "a.test"


def test_mentions_and_tone_are_clamped():
    rollups, _ = _parse(_event(mentions="999999", tone="250"))
    r = rollups[("US", "IR", TODAY, 3)]
    assert r.mentions == events.MAX_EVENT_MENTIONS and r.tone_sum == 100.0


def test_rows_past_the_cap_are_not_read(monkeypatch):
    monkeypatch.setattr(events, "MAX_ROWS", 3)
    _, stats = _parse(*(_event() for _ in range(5)))
    assert stats.rows == 3 and stats.truncated


def test_windows_line_endings_parse():
    rollups, _ = _parse(_event() + "\r")
    assert ("US", "IR", TODAY, 3) in rollups


def _zip(members: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in members.items():
            zf.writestr(name, data)
    return buf.getvalue()


class TestReadExport:
    def test_reads_the_one_export_member(self):
        body = _zip({"20261021123000.export.CSV": b"a\tb\x00\n"})
        assert read_export(body) == "a\tb\n"

    @pytest.mark.parametrize(
        "body",
        [
            b"not a zip",
            _zip({"20261021123000.export.CSV": b"a", "x.txt": b"b"}),
            _zip({"evil.sh": b"a"}),
        ],
    )
    def test_refuses_anything_else(self, body):
        assert read_export(body) is None

    def test_refuses_an_oversized_member(self, monkeypatch):
        monkeypatch.setattr(events, "MAX_CSV_BYTES", 4)
        assert read_export(_zip({"20261021123000.export.CSV": b"12345"})) is None

    def test_a_corrupt_stream_is_none_whatever_it_raises(self):
        """Untrusted bytes: a damaged deflate stream raises zlib.error, an odd
        compression method NotImplementedError. Every error is None, never a raise."""
        body = bytearray(_zip({"20261021123000.export.CSV": bytes(range(256)) * 40}))
        body[60:120] = b"\xff" * 60  # inside the compressed data
        assert read_export(bytes(body)) is None


T = datetime(2026, 10, 21, 12, 30, tzinfo=timezone.utc)
Q = timedelta(minutes=15)


class TestSlots:
    def test_slot_round_trip(self):
        assert slot_url(T) == "https://data.gdeltproject.org/gdeltv2/20261021123000.export.CSV.zip"
        assert slot_of(slot_url(T)) == T
        assert slot_of("http://data.gdeltproject.org/gdeltv2/20261021123000.gkg.csv.zip") is None

    def test_first_run_takes_only_the_newest(self):
        assert plan_slots(T, set()) == [T]

    def test_catches_up_missed_slots_newest_first(self):
        done = {T - 3 * Q}
        assert plan_slots(T, done) == [T, T - Q, T - 2 * Q, T - 4 * Q]

    def test_skips_done_slots_and_the_newest_when_done(self):
        assert plan_slots(T, {T, T - Q}) == [T - 2 * Q, T - 3 * Q, T - 4 * Q, T - 5 * Q]

    def test_never_reaches_past_the_catch_up_window(self, monkeypatch):
        monkeypatch.setattr(events, "MAX_FILES_PER_CYCLE", 100)
        slots = plan_slots(T, {T - 30 * Q})
        assert min(slots) > T - timedelta(hours=events.CATCHUP_HOURS)


class TestLostSlots:
    """The slots that left the catch-up window since the last cycle, never added."""

    W = timedelta(hours=events.CATCHUP_HOURS)

    def test_none_before_this_process_ran_a_cycle(self):
        assert lost_slots(None, T, set()) == []

    def test_the_slots_that_left_the_window_unadded(self):
        # Two slots left the window since the last cycle (30 minutes ago); one was added.
        prev = T - 2 * Q
        assert lost_slots(prev, T, {T - self.W - Q}) == [T - self.W]

    def test_none_lost_when_every_slot_was_added(self):
        prev = T - 2 * Q
        assert lost_slots(prev, T, {T - self.W, T - self.W - Q}) == []

    def test_a_long_gap_counts_at_most_a_day(self):
        lost = lost_slots(T - timedelta(days=3), T, set())
        assert len(lost) == 96 and max(lost) == T - self.W


def test_a_rollup_records_each_event():
    r = Rollup()
    r.add(3, 1.5, 2.0, None)
    assert (r.n_events, r.mentions, r.goldstein_sum, r.tone_sum) == (1, 3, 1.5, 2.0)
