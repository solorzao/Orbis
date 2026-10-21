"""GDELT Events parsing and aggregation (no database, no network)."""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import io
import logging
import zipfile
from datetime import date, datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

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
from app.services.gdelt import Download, LastUpdateEntry

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


def test_unmapped_codes_that_arent_three_letters_are_counted_as_other():
    """The counts reach the log: raw GDELT text never does."""
    rows = (_event(a="<script>"), _event(b="usa\x1b[31m"), _event(a="ABCD"), _event(b="AFR"))
    _, stats = _parse(*rows)
    assert stats.unmapped == {"other": 3, "AFR": 1}


def test_a_giant_row_is_split_no_further_than_a_row_has_fields(monkeypatch):
    """str.split without a limit would allocate a list as long as the row has tabs
    (an OOM kill can't be caught); the field count still rejects the row."""
    seen: list[int] = []
    real = events._event
    monkeypatch.setattr(events, "_event", lambda fields: seen.append(len(fields)) or real(fields))
    _, stats = _parse(_event() + "\t" * 100_000)
    assert stats.malformed == 1
    assert seen == [events.COLUMNS + 1]


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


def _export_zip(*rows: str) -> bytes:
    return _zip({"20261021123000.export.CSV": ("\n".join(rows) + "\n").encode()})


class _Pool:
    def __init__(self, done=()):
        self.done = [{"slot": s} for s in done]

    async def fetch(self, sql, *args):
        return self.done


def _index(body: bytes, size: int | None = None) -> dict:
    return {
        "export": LastUpdateEntry(
            len(body) if size is None else size,
            hashlib.md5(body).hexdigest(),
            "http://data.gdeltproject.org/gdeltv2/20261021123000.export.CSV.zip",
        )
    }


def _patches(index, downloads, pool, store):
    return (
        patch("app.services.events.fetch_lastupdate", AsyncMock(return_value=index)),
        patch("app.services.events.download_capped", AsyncMock(side_effect=downloads)),
        patch("app.services.events.get_pool", AsyncMock(return_value=pool)),
        patch("app.services.events.store_rollups", store),
    )


@pytest.fixture(autouse=True)
def _fresh_process(monkeypatch):
    """Each test starts as a process that hasn't run a cycle yet."""
    monkeypatch.setattr(events, "_last_newest", None)


class TestIngestEvents:
    @pytest.mark.asyncio
    async def test_first_run_adds_only_the_newest_file(self):
        body = _export_zip(_event())
        store = AsyncMock(return_value=1)
        p = _patches(_index(body), [Download("ok", body)], _Pool(), store)
        with p[0], p[1], p[2], p[3]:
            await events.ingest_events(now=T + timedelta(minutes=5))
        _, rollups, files = store.await_args.args
        assert list(rollups) == [("US", "IR", TODAY, 3)]
        assert files == [events.FileResult(T, "ok", 1, 1)]

    @pytest.mark.asyncio
    async def test_a_newest_file_failing_its_md5_is_not_added(self, caplog):
        body = _export_zip(_event())
        store = AsyncMock()
        p = _patches(_index(body), [Download("ok", body + b"x")], _Pool(), store)
        with p[0], p[1], p[2], p[3], caplog.at_level(logging.WARNING, logger="orbis.events"):
            await events.ingest_events(now=T)
        store.assert_not_awaited()
        assert "MD5" in caplog.text

    @pytest.mark.asyncio
    async def test_a_newest_file_over_the_cap_is_never_downloaded(self):
        body = _export_zip(_event())
        download = AsyncMock()
        index = _index(body, size=events.MAX_ZIP_BYTES + 1)
        with (
            patch("app.services.events.fetch_lastupdate", AsyncMock(return_value=index)),
            patch("app.services.events.download_capped", download),
            patch("app.services.events.get_pool", AsyncMock(return_value=_Pool())),
            patch("app.services.events.store_rollups", AsyncMock()),
        ):
            await events.ingest_events(now=T)
        download.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_a_missing_older_slot_is_recorded_missing(self, monkeypatch):
        monkeypatch.setattr(events, "MAX_FILES_PER_CYCLE", 2)  # the newest and one before
        body = _export_zip(_event())
        store = AsyncMock(return_value=1)
        downloads = [Download("ok", body), Download("missing")]
        p = _patches(_index(body), downloads, _Pool(done=[T - 2 * Q]), store)
        with p[0], p[1], p[2], p[3]:
            await events.ingest_events(now=T)
        _, _, files = store.await_args.args
        assert files == [
            events.FileResult(T, "ok", 1, 1),
            events.FileResult(T - Q, "missing", 0, 0),
        ]

    @pytest.mark.asyncio
    async def test_switched_off_it_does_nothing(self, monkeypatch):
        monkeypatch.setattr(events.settings, "events_ingestion_enabled", False)
        fetch = AsyncMock()
        with patch("app.services.events.fetch_lastupdate", fetch):
            await events.ingest_events(now=T)
        fetch.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_a_failure_is_a_warning(self, caplog):
        with (
            patch(
                "app.services.events.fetch_lastupdate",
                AsyncMock(side_effect=RuntimeError("boom")),
            ),
            caplog.at_level(logging.WARNING, logger="orbis.events"),
        ):
            await events.ingest_events(now=T)  # does not raise
        assert "Events ingestion failed" in caplog.text

    @pytest.mark.asyncio
    async def test_logs_one_summary_line(self, caplog):
        body = _export_zip(_event(), _event(a="USA", b="USA"), "bad")
        p = _patches(_index(body), [Download("ok", body)], _Pool(), AsyncMock(return_value=1))
        with p[0], p[1], p[2], p[3], caplog.at_level(logging.INFO, logger="orbis.events"):
            await events.ingest_events(now=T)
        [line] = [
            r.getMessage() for r in caplog.records if r.getMessage().startswith("Events: 1 file")
        ]
        assert "3 rows, 1 kept (0 not root" in line and "1 same country, 1 malformed" in line

    @pytest.mark.asyncio
    async def test_an_unreadable_file_is_recorded_so_it_is_never_retried(self):
        body = b"not a zip at all"
        store = AsyncMock(return_value=0)
        p = _patches(_index(body), [Download("ok", body)], _Pool(), store)
        with p[0], p[1], p[2], p[3]:
            await events.ingest_events(now=T)
        _, rollups, files = store.await_args.args
        assert rollups == {} and files == [events.FileResult(T, "unreadable", 0, 0)]

    @pytest.mark.asyncio
    async def test_a_file_that_fails_halfway_adds_nothing_and_is_recorded(self):
        body = _export_zip(_event())

        def half_then_fail(raw, today, part):
            part[("US", "IR", today, 3)] = Rollup(n_events=7)
            raise RuntimeError("a bug, or a hostile file")

        store = AsyncMock(return_value=0)
        p = _patches(_index(body), [Download("ok", body)], _Pool(), store)
        with p[0], p[1], p[2], p[3], patch("app.services.events.parse_events", half_then_fail):
            await events.ingest_events(now=T)
        _, rollups, files = store.await_args.args
        assert rollups == {}  # its half never merged
        assert files == [events.FileResult(T, "unreadable", 0, 0)]

    @pytest.mark.asyncio
    async def test_catch_up_files_get_one_retry_and_a_short_timeout(self, monkeypatch):
        monkeypatch.setattr(events, "MAX_FILES_PER_CYCLE", 2)
        body = _export_zip(_event())
        download = AsyncMock(side_effect=[Download("ok", body), Download("failed")])
        store = AsyncMock(return_value=1)
        with (
            patch("app.services.events.fetch_lastupdate", AsyncMock(return_value=_index(body))),
            patch("app.services.events.download_capped", download),
            patch(
                "app.services.events.get_pool",
                AsyncMock(return_value=_Pool(done=[T - 2 * Q])),
            ),
            patch("app.services.events.store_rollups", store),
        ):
            await events.ingest_events(now=T)
        newest_call, catch_up_call = download.await_args_list
        assert newest_call.kwargs == {
            "attempts": events.NEWEST_ATTEMPTS,
            "timeout": events.NEWEST_TIMEOUT_S,
        }
        assert catch_up_call.kwargs == {
            "attempts": events.CATCHUP_ATTEMPTS,
            "timeout": events.CATCHUP_TIMEOUT_S,
        }
        _, _, files = store.await_args.args
        assert files == [events.FileResult(T, "ok", 1, 1)]  # the failed one: next cycle

    @pytest.mark.asyncio
    async def test_a_hanging_step_times_out_and_claims_nothing(self, monkeypatch, caplog):
        monkeypatch.setattr(events, "EVENTS_STEP_TIMEOUT_S", 0.05)

        async def hang():
            await asyncio.Event().wait()

        store = AsyncMock()
        with (
            patch("app.services.events.fetch_lastupdate", hang),
            patch("app.services.events.store_rollups", store),
            caplog.at_level(logging.WARNING, logger="orbis.events"),
        ):
            await events.ingest_events(now=T)  # returns, doesn't hang
        store.assert_not_awaited()
        # A COMMIT can complete as the timeout fires: the log can't say "nothing added".
        assert "timed out" in caplog.text and "may not have been added" in caplog.text

    @pytest.mark.asyncio
    async def test_slots_that_left_the_window_unadded_are_logged_as_lost(self, monkeypatch, caplog):
        monkeypatch.setattr(events, "MAX_FILES_PER_CYCLE", 1)
        monkeypatch.setattr(events, "_last_newest", T - 2 * Q)
        window = timedelta(hours=events.CATCHUP_HOURS)
        body = _export_zip(_event())
        p = _patches(
            _index(body),
            [Download("ok", body)],
            _Pool(done=[T - window - Q]),
            AsyncMock(return_value=1),
        )
        with p[0], p[1], p[2], p[3], caplog.at_level(logging.WARNING, logger="orbis.events"):
            await events.ingest_events(now=T)
        assert "1 slot lost" in caplog.text
        assert f"{T - window:%Y%m%d%H%M%S}" in caplog.text
        assert events._last_newest == T

    @pytest.mark.asyncio
    async def test_after_a_restart_slots_lost_meanwhile_are_still_reported(
        self, monkeypatch, caplog
    ):
        """A deploy or an outage: the new process has no previous cycle, so it counts
        from the newest slot the database says was added."""
        monkeypatch.setattr(events, "MAX_FILES_PER_CYCLE", 1)
        last_added = T - timedelta(hours=3)  # the old process's last cycle
        body = _export_zip(_event())
        p = _patches(
            _index(body),
            [Download("ok", body)],
            _Pool(done=[last_added]),
            AsyncMock(return_value=1),
        )
        with p[0], p[1], p[2], p[3], caplog.at_level(logging.WARNING, logger="orbis.events"):
            await events.ingest_events(now=T)
        # Left the window since: (last_added - 2 h, T - 2 h], 12 slots, one of them added.
        assert "11 slots lost" in caplog.text

    @pytest.mark.asyncio
    async def test_catch_up_waits_for_the_next_cycle_once_the_download_budget_is_spent(
        self, monkeypatch, caplog
    ):
        """A slow host: the newest file is always tried, and a catch-up file only while
        it can finish its tries inside DOWNLOAD_BUDGET_S, so the step never times out
        and loses what it downloaded."""
        monkeypatch.setattr(events, "MAX_FILES_PER_CYCLE", 3)
        monkeypatch.setattr(events, "DOWNLOAD_BUDGET_S", 0.0)
        body = _export_zip(_event())
        download = AsyncMock(side_effect=[Download("ok", body)])
        store = AsyncMock(return_value=1)
        with (
            patch("app.services.events.fetch_lastupdate", AsyncMock(return_value=_index(body))),
            patch("app.services.events.download_capped", download),
            patch(
                "app.services.events.get_pool",
                AsyncMock(return_value=_Pool(done=[T - 3 * Q])),
            ),
            patch("app.services.events.store_rollups", store),
            caplog.at_level(logging.INFO, logger="orbis.events"),
        ):
            await events.ingest_events(now=T)
        assert download.await_count == 1  # the newest only
        _, _, files = store.await_args.args
        assert files == [events.FileResult(T, "ok", 1, 1)]  # T - Q, T - 2Q: next cycle
        assert "2 catch-up slots left for the next cycle" in caplog.text


def test_every_download_fits_the_steps_time_bound():
    """At worst every attempt times out: lastupdate.txt, then the newest file, take
    the download budget, catch-up files only start inside it, and the parse and the
    store keep STORE_ALLOWANCE_S, all under EVENTS_STEP_TIMEOUT_S."""
    from app.services import gdelt

    index = gdelt.download_worst_case_s(gdelt.LASTUPDATE_ATTEMPTS, gdelt.LASTUPDATE_TIMEOUT_S)
    newest = gdelt.download_worst_case_s(events.NEWEST_ATTEMPTS, events.NEWEST_TIMEOUT_S)
    catch_up = gdelt.download_worst_case_s(events.CATCHUP_ATTEMPTS, events.CATCHUP_TIMEOUT_S)
    assert (index, newest, catch_up) == (21.5, 31.5, 21.5)
    assert index + newest <= events.DOWNLOAD_BUDGET_S
    assert events.DOWNLOAD_BUDGET_S + events.STORE_ALLOWANCE_S <= events.EVENTS_STEP_TIMEOUT_S
    assert events.STORE_ALLOWANCE_S >= 5


@contextlib.asynccontextmanager
async def _no_transaction():
    yield


class TestPurgeEvents:
    @pytest.mark.asyncio
    async def test_forces_custom_plans_before_deleting(self):
        sent: list[str] = []

        class Conn:
            async def execute(self, sql, *args):
                sent.append(sql)

            def transaction(self):
                return _no_transaction()

        class Pool:
            @contextlib.asynccontextmanager
            async def acquire(self):
                yield Conn()

        await events.purge_events(Pool(), 7, T)
        assert sent[0] == "SET LOCAL plan_cache_mode = force_custom_plan"
        assert sent[1:] == [events.PURGE_PAIRS_SQL, events.PURGE_FILES_SQL]
