"""GDELT 2.0 Events: daily country-pair rollups (Phase 5, PR 19).

Each ingestion cycle adds the newest 15-minute Event export (the
export.CSV.zip line of lastupdate.txt) to event_pairs_daily, plus earlier
slots no cycle has added: a cycle starts about every half hour, so every
other file would otherwise be missed, and rollups are counts. Nothing is
stored per event. Each file is parsed in memory; its root events between two
different mapped countries are aggregated in Python by (actor 1 country,
actor 2 country, UTC day added, QuadClass); the cycle's rollups go to the
database in one batched upsert, in the transaction that records the files in
event_files, so no file is ever added twice.

GDELT data is untrusted: only https URLs on GDELT's data host are fetched
(no redirects), the zip, its CSV and its rows are capped, malformed rows are
counted and skipped, a file that can't be read is recorded unreadable (never
retried), and source URLs are kept only when they are http(s). The whole step
is time-bounded (EVENTS_STEP_TIMEOUT_S).
"""

from __future__ import annotations

import asyncio
import hashlib
import io
import logging
import math
import re
import time
import zipfile
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any, NamedTuple

from app.config import settings
from app.services.cameo_countries import cameo_to_iso2
from app.services.database import get_pool
from app.services.gdelt import (
    _GDELT_HOST,
    LASTUPDATE_ATTEMPTS,
    LASTUPDATE_TIMEOUT_S,
    LastUpdateEntry,
    _gdelt_https_url,
    download_capped,
    download_worst_case_s,
    fetch_lastupdate,
)
from app.services.urls import outlet, web_url

# GDELT 2.0 Event export (Event Codebook V2.0): 61 tab-separated columns, no header.
COLUMNS = 61
_ACTOR1_COUNTRY = 7
_ACTOR2_COUNTRY = 17
_IS_ROOT = 25
_QUAD_CLASS = 29
_GOLDSTEIN = 30
_NUM_MENTIONS = 31
_AVG_TONE = 34
_DATE_ADDED = 59
_SOURCE_URL = 60

SLOT = timedelta(minutes=15)
# The newest file plus missed ones: a cycle starts about every 30 minutes, so
# about 2 files a cycle; 4 covers a long cycle. Never further back than this.
MAX_FILES_PER_CYCLE = 4
CATCHUP_HOURS = 2
# The whole step's bound: on a timeout the claim and the upsert roll back
# together (unless the COMMIT completed as it fired), and the files are retried
# next cycle.
EVENTS_STEP_TIMEOUT_S = 60
# The downloads fit inside it, so a slow host can't make every cycle time out and
# lose what it did download: lastupdate.txt (gdelt.LASTUPDATE_*) and the newest
# file take the download budget at worst; a catch-up file starts only while it
# could finish its tries inside the budget, else it waits for the next cycle
# (its slot stays in the catch-up window). The parse and the store keep
# STORE_ALLOWANCE_S at worst (tests/test_events.py checks the sum).
NEWEST_ATTEMPTS = 2
NEWEST_TIMEOUT_S = 15.0
CATCHUP_ATTEMPTS = 2
CATCHUP_TIMEOUT_S = 10.0
DOWNLOAD_BUDGET_S = download_worst_case_s(
    LASTUPDATE_ATTEMPTS, LASTUPDATE_TIMEOUT_S
) + download_worst_case_s(NEWEST_ATTEMPTS, NEWEST_TIMEOUT_S)
STORE_ALLOWANCE_S = 5.0
# Caps on untrusted input. Exports are about 80 KB zipped (2026-10-21), about
# 1,200 rows; these leave 25x headroom and bound the work.
MAX_ZIP_BYTES = 2_000_000
MAX_CSV_BYTES = 20_000_000
MAX_ROWS = 30_000
MAX_EVENT_MENTIONS = 10_000  # one event's NumMentions, clamped
MAX_URL_CHARS = 1_000
MAX_SAMPLES = 3  # per rollup row: sample_urls
MAX_OUTLETS = 8  # per rollup row: outlets

_EXPORT_URL = re.compile(r"/(\d{14})\.export\.CSV\.zip$", re.IGNORECASE)
_EXPORT_MEMBER = re.compile(r"\d{14}\.export\.CSV", re.IGNORECASE)
# An unmapped actor code is counted (and logged) as itself only when it looks like
# one; anything else in that untrusted field is counted as "other".
_CAMEO_CODE = re.compile(r"[A-Z]{3}")

Key = tuple[str, str, date, int]  # (a_iso, b_iso, day, quad_class)


@dataclass
class Rollup:
    """One (a, b, day, quad) group's sums from this cycle's files."""

    n_events: int = 0
    mentions: int = 0
    goldstein_sum: float = 0.0
    tone_sum: float = 0.0
    samples: list[str] = field(default_factory=list)
    outlets: list[str] = field(default_factory=list)

    def add(self, mentions: int, goldstein: float, tone: float, url: str | None) -> None:
        self.n_events += 1
        self.mentions += mentions
        self.goldstein_sum += goldstein
        self.tone_sum += tone
        if url is not None:
            self._keep([url], [outlet(url)])

    def merge(self, other: Rollup) -> None:
        """Add another file's rollup for the same group (a file merges only once it
        has parsed whole, so a file that fails halfway adds nothing)."""
        self.n_events += other.n_events
        self.mentions += other.mentions
        self.goldstein_sum += other.goldstein_sum
        self.tone_sum += other.tone_sum
        self._keep(other.samples, other.outlets)

    def _keep(self, urls: list[str], hosts: list[str]) -> None:
        """Keep the first-seen sample URLs and outlets, without repeats, up to their caps."""
        for url in urls:
            if len(self.samples) < MAX_SAMPLES and url not in self.samples:
                self.samples.append(url)
        for host in hosts:
            if host and len(self.outlets) < MAX_OUTLETS and host not in self.outlets:
                self.outlets.append(host)


@dataclass
class ParseStats:
    """What a file held, for the cycle's log line and the repro."""

    rows: int = 0
    kept: int = 0
    malformed: int = 0
    not_root: int = 0
    no_pair: int = 0
    same_country: int = 0
    stale: int = 0
    truncated: bool = False
    unmapped: Counter = field(default_factory=Counter)

    def add(self, other: ParseStats) -> None:
        for name in ("rows", "kept", "malformed", "not_root", "no_pair", "same_country", "stale"):
            setattr(self, name, getattr(self, name) + getattr(other, name))
        self.truncated = self.truncated or other.truncated
        self.unmapped.update(other.unmapped)


class _Event(NamedTuple):
    a: str
    b: str
    quad: int
    goldstein: float
    mentions: int
    tone: float
    day: date
    root: bool
    url: str | None


def _event(fields: list[str]) -> _Event | None:
    """The fields this module reads from one export row, or None when it is malformed."""
    if len(fields) != COLUMNS:
        return None
    added = fields[_DATE_ADDED].strip()
    if len(added) != 14 or not (added.isascii() and added.isdigit()):
        return None
    try:
        quad = int(fields[_QUAD_CLASS])
        goldstein = float(fields[_GOLDSTEIN])
        mentions = int(fields[_NUM_MENTIONS])
        tone = float(fields[_AVG_TONE])
        day = datetime.strptime(added, "%Y%m%d%H%M%S").date()
    except ValueError:
        return None
    if quad not in (1, 2, 3, 4) or mentions < 0:
        return None
    if not (math.isfinite(goldstein) and -10 <= goldstein <= 10 and math.isfinite(tone)):
        return None
    url = fields[_SOURCE_URL].strip()
    return _Event(
        a=fields[_ACTOR1_COUNTRY].strip(),
        b=fields[_ACTOR2_COUNTRY].strip(),
        quad=quad,
        goldstein=goldstein,
        mentions=min(mentions, MAX_EVENT_MENTIONS),
        tone=max(-100.0, min(100.0, tone)),
        day=day,
        root=fields[_IS_ROOT].strip() == "1",
        url=web_url(url) if len(url) <= MAX_URL_CHARS else None,
    )


def parse_events(raw: str, today: date, rollups: dict[Key, Rollup]) -> ParseStats:
    """Add a decoded export file's events to *rollups*; return what the file held.

    Kept: a root event (IsRootEvent = 1, the lead paragraph: the higher signal),
    whose actors' countries both map to ISO and differ, added within retention
    (up to a day ahead, for clock skew). CPU-bound: run it in a worker thread.
    """
    stats = ParseStats()
    oldest = today - timedelta(days=settings.retention_days)
    newest = today + timedelta(days=1)
    # "\n" only: str.splitlines() also splits on \x0b, \x0c, \x1c-\x1e, \x85,
    #   and  , which can sit inside a field and would break the row.
    for line in raw.split("\n"):
        line = line.rstrip("\r")
        if not line:
            continue
        if stats.rows == MAX_ROWS:
            stats.truncated = True
            break
        stats.rows += 1
        # At most COLUMNS + 1 pieces, however many tabs a hostile row holds (an
        # unbounded split could exhaust memory); _event rejects a longer row.
        event = _event(line.split("\t", COLUMNS))
        if event is None:
            stats.malformed += 1
            continue
        if not event.root:
            stats.not_root += 1
            continue
        if not oldest <= event.day <= newest:
            stats.stale += 1
            continue
        a, b = cameo_to_iso2(event.a), cameo_to_iso2(event.b)
        if not a or not b:
            stats.no_pair += 1
            for code, iso in ((event.a, a), (event.b, b)):
                if code and not iso:
                    stats.unmapped[code if _CAMEO_CODE.fullmatch(code) else "other"] += 1
            continue
        if a == b:
            stats.same_country += 1
            continue
        stats.kept += 1
        rollup = rollups.setdefault((a, b, event.day, event.quad), Rollup())
        rollup.add(event.mentions, event.goldstein, event.tone, event.url)
    return stats


def read_export(body: bytes) -> str | None:
    """A downloaded export zip's CSV, decoded, or None unless the zip holds exactly
    one export member within MAX_CSV_BYTES (whatever size it declares).

    The bytes are untrusted, and unzipping them can raise almost anything
    (BadZipFile, zlib.error, NotImplementedError for an odd compression method,
    EOFError, ...): every error is None, so a bad file is recorded unreadable
    rather than failing the step.
    """
    try:
        with zipfile.ZipFile(io.BytesIO(body)) as zf:
            members = zf.infolist()
            if len(members) != 1 or not _EXPORT_MEMBER.fullmatch(members[0].filename):
                return None
            if members[0].file_size > MAX_CSV_BYTES:
                return None
            with zf.open(members[0]) as fh:
                # More than its declared size, so the read reaches the member's end,
                # where zipfile checks its CRC32 (BadZipFile on a mismatch).
                data = fh.read(MAX_CSV_BYTES + 1)
    except Exception:
        return None
    if len(data) > MAX_CSV_BYTES:
        return None
    # NUL survives decoding, and Postgres TEXT rejects it.
    return data.decode("utf-8", errors="replace").replace("\x00", "")


def slot_of(url: str) -> datetime | None:
    """The 15-minute slot an export file URL is for, or None if it isn't one."""
    match = _EXPORT_URL.search(url)
    if not match:
        return None
    try:
        return datetime.strptime(match.group(1), "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def slot_url(slot: datetime) -> str:
    """The export file for *slot*, on GDELT's data host over https."""
    return f"https://{_GDELT_HOST}/gdeltv2/{slot:%Y%m%d%H%M%S}.export.CSV.zip"


def plan_slots(newest: datetime, done: set[datetime]) -> list[datetime]:
    """The slots to add this cycle, newest first.

    The newest file, then each earlier 15-minute slot no cycle has added, at
    most MAX_FILES_PER_CYCLE, and none older than CATCHUP_HOURS before the
    newest. Before any file has been added (*done* is empty), only the
    newest: there is no backfill.
    """
    if not done:
        return [newest]
    earliest = newest - timedelta(hours=CATCHUP_HOURS)
    slots: list[datetime] = []
    slot = newest
    while slot > earliest and len(slots) < MAX_FILES_PER_CYCLE:
        if slot not in done:
            slots.append(slot)
        slot -= SLOT
    return slots


# A long outage counts as at most a day of lost slots.
LOST_LOOKBACK = timedelta(days=1)


def lost_slots(
    prev_newest: datetime | None, newest: datetime, done: set[datetime]
) -> list[datetime]:
    """The slots that left the catch-up window since the previous cycle, never added:
    their events are lost for good (rollups are counts). Newest first.

    A slot is in the window while it's later than newest - CATCHUP_HOURS
    (plan_slots). Empty before this process has run a cycle (*prev_newest* is
    None); after a long gap, at most LOST_LOOKBACK of them. *done* must hold
    the added slots that far back (DONE_SQL reads them).
    """
    if prev_newest is None:
        return []
    window = timedelta(hours=CATCHUP_HOURS)
    high = newest - window
    low = max(prev_newest - window, high - LOST_LOOKBACK)
    lost: list[datetime] = []
    slot = high
    while slot > low:
        if slot not in done:
            lost.append(slot)
        slot -= SLOT
    return lost


logger = logging.getLogger("orbis.events")

_MD5 = re.compile(r"[0-9a-f]{32}")
# pg_advisory_xact_lock key: one events writer at a time, even when two
# revisions overlap during a deploy.
_EVENTS_LOCK = 20_261_021


class FileResult(NamedTuple):
    slot: datetime
    status: str  # ok | missing | unreadable
    n_rows: int
    n_kept: int


class AlreadyIngested(RuntimeError):
    """Another process added one of this cycle's files first; nothing was written."""


DONE_SQL = "SELECT slot FROM event_files WHERE slot >= $1"

CLAIM_SQL = """
INSERT INTO event_files (slot, status, n_rows, n_kept)
SELECT * FROM unnest($1::timestamptz[], $2::text[], $3::int[], $4::int[])
ON CONFLICT (slot) DO NOTHING
RETURNING slot
"""

# Sums add up. Sample URLs and outlets keep the first seen, without repeats,
# up to their caps ($11, $12: MAX_SAMPLES, MAX_OUTLETS).
UPSERT_SQL = """
INSERT INTO event_pairs_daily AS e
    (a_iso, b_iso, day, quad_class, n_events, mentions,
     goldstein_sum, tone_sum, sample_urls, outlets)
VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
ON CONFLICT (a_iso, b_iso, day, quad_class) DO UPDATE SET
    n_events      = e.n_events + EXCLUDED.n_events,
    mentions      = e.mentions + EXCLUDED.mentions,
    goldstein_sum = e.goldstein_sum + EXCLUDED.goldstein_sum,
    tone_sum      = e.tone_sum + EXCLUDED.tone_sum,
    sample_urls   = ARRAY(
        SELECT u FROM unnest(e.sample_urls || EXCLUDED.sample_urls) WITH ORDINALITY AS s(u, i)
        GROUP BY u ORDER BY min(i) LIMIT $11),
    outlets       = ARRAY(
        SELECT o FROM unnest(e.outlets || EXCLUDED.outlets) WITH ORDINALITY AS s(o, i)
        GROUP BY o ORDER BY min(i) LIMIT $12)
"""

PURGE_PAIRS_SQL = "DELETE FROM event_pairs_daily WHERE day < $1::date - $2::int"
PURGE_FILES_SQL = "DELETE FROM event_files WHERE slot < $1::timestamptz - interval '2 days'"


async def store_rollups(pool: Any, rollups: dict[Key, Rollup], files: list[FileResult]) -> int:
    """Record *files* and add *rollups* in one transaction; return the rows upserted.

    One executemany (asyncpg pipelines the rows), as upsert_articles does. The
    advisory lock and the claim keep a file from being added twice; if any file
    was already recorded, nothing is written (AlreadyIngested). Cancelled (the
    step's timeout), the transaction rolls back and nothing is claimed.
    """
    rows = [
        (
            a,
            b,
            day,
            quad,
            r.n_events,
            r.mentions,
            r.goldstein_sum,
            r.tone_sum,
            r.samples,
            r.outlets,
            MAX_SAMPLES,
            MAX_OUTLETS,
        )
        for (a, b, day, quad), r in sorted(rollups.items())
    ]
    slots = [f.slot for f in files]
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute("SELECT pg_advisory_xact_lock($1)", _EVENTS_LOCK)
            claimed = await conn.fetch(
                CLAIM_SQL,
                slots,
                [f.status for f in files],
                [f.n_rows for f in files],
                [f.n_kept for f in files],
            )
            if len(claimed) != len(files):
                taken = sorted(set(slots) - {r["slot"] for r in claimed})
                raise AlreadyIngested(", ".join(f"{s:%Y%m%d%H%M%S}" for s in taken))
            if rows:
                await conn.executemany(UPSERT_SQL, rows)
    return len(rows)


async def purge_events(pool: Any, retention_days: int, now: datetime | None = None) -> None:
    """Delete rollups older than *retention_days* UTC days, and the file log after 2 days.

    Custom plans only: a generic plan guesses that ``day < $1`` matches a third of
    the table and seq-scans it every cycle, as 18a found for place lookups. With
    the values, it is an index range that is empty on all but one cycle a day.
    Runs whatever EVENTS_INGESTION_ENABLED says, so switched off, rows age out.
    """
    now = now or datetime.now(timezone.utc)
    async with pool.acquire() as conn, conn.transaction():
        await conn.execute("SET LOCAL plan_cache_mode = force_custom_plan")
        await conn.execute(PURGE_PAIRS_SQL, now.date(), retention_days)
        await conn.execute(PURGE_FILES_SQL, now)


# The previous cycle's newest slot, in this process: where lost_slots counts from.
_last_newest: datetime | None = None


async def ingest_events(now: datetime | None = None) -> None:
    """Add the newest export, and missed ones, to the rollups. Never raises.

    Bounded by EVENTS_STEP_TIMEOUT_S (its downloads by DOWNLOAD_BUDGET_S). On a
    timeout the claim and the upsert, one transaction, roll back together when
    cancelled, so the same files are tried again next cycle; but a COMMIT can
    complete as the timeout fires, so the files may have been added after all
    (and then aren't tried again). Either way no file is added twice or in
    part. A parse already running in its worker thread finishes on its own and
    is dropped.
    """
    if not settings.events_ingestion_enabled:
        return
    try:
        await asyncio.wait_for(_ingest(now or datetime.now(timezone.utc)), EVENTS_STEP_TIMEOUT_S)
    except TimeoutError:
        logger.warning(
            "Events: the step timed out after %s s; this cycle's files may not have been"
            " added (any that weren't are retried next cycle).",
            EVENTS_STEP_TIMEOUT_S,
        )
    except AlreadyIngested as exc:
        logger.warning("Events: another process added %s; nothing added this cycle.", exc)
    except Exception:
        logger.warning("Events ingestion failed; continuing.", exc_info=True)


def _name(slot: datetime) -> str:
    return slot_url(slot).rsplit("/", 1)[-1]


async def _ingest(now: datetime) -> None:
    global _last_newest
    began = time.monotonic()
    index = await fetch_lastupdate()
    entry = (index or {}).get("export")
    newest = slot_of(entry.url) if entry and _gdelt_https_url(entry.url) else None
    if newest is None:
        logger.warning("Events: no GDELT export file in lastupdate.txt.")
        return
    pool = await get_pool()
    window = timedelta(hours=CATCHUP_HOURS)
    # The added slots back to lost_slots' reach (a primary-key range, ~100 rows at most).
    done = {r["slot"] for r in await pool.fetch(DONE_SQL, newest - window - LOST_LOOKBACK)}
    # After a restart (a deploy, an outage) this process has run no cycle: count
    # from the newest slot added, so slots lost meanwhile are still reported.
    previous = _last_newest if _last_newest is not None else max(done, default=None)
    lost = lost_slots(previous, newest, done)
    rollups: dict[Key, Rollup] = {}
    files: list[FileResult] = []
    totals = ParseStats()
    timing = {"download": 0.0, "parse": 0.0, "store": 0.0}
    catch_up_worst = download_worst_case_s(CATCHUP_ATTEMPTS, CATCHUP_TIMEOUT_S)
    slots = plan_slots(newest, done)
    for i, slot in enumerate(slots):
        if slot != newest and time.monotonic() - began + catch_up_worst > DOWNLOAD_BUDGET_S:
            left = len(slots) - i
            logger.info(
                "Events: download budget (%.0f s) spent; %d catch-up slot%s left for the"
                " next cycle.",
                DOWNLOAD_BUDGET_S,
                left,
                "" if left == 1 else "s",
            )
            break
        try:
            result = await _add_file(
                slot, entry if slot == newest else None, now.date(), rollups, totals, timing
            )
        except Exception:
            # A bug or a hostile file: recorded, so it can't fail every cycle.
            logger.warning("Events: %s failed; recorded unreadable.", _name(slot), exc_info=True)
            result = FileResult(slot, "unreadable", 0, 0)
        if result is not None:
            files.append(result)
    upserted = 0
    if files:
        started = time.monotonic()
        upserted = await store_rollups(pool, rollups, files)
        timing["store"] = time.monotonic() - started
    _last_newest = newest
    if lost:
        logger.warning(
            "Events: %d slot%s lost (left the catch-up window unadded): %s.",
            len(lost),
            "" if len(lost) == 1 else "s",
            ", ".join(f"{s:%Y%m%d%H%M%S}" for s in lost[:8]) + (" …" if len(lost) > 8 else ""),
        )
    if not files:
        return
    ok = sum(f.status == "ok" for f in files)
    logger.info(
        "Events: %d file%s (%d caught up, %d missing, %d unreadable), %d rows, %d kept "
        "(%d not root, %d no country pair, %d same country, %d malformed, %d stale%s), "
        "%d rollups, %d slot%s lost, in %.2f s (download %.2f s, parse %.2f s, store %.2f s).",
        ok,
        "" if ok == 1 else "s",
        sum(f.status == "ok" and f.slot != newest for f in files),
        sum(f.status == "missing" for f in files),
        sum(f.status == "unreadable" for f in files),
        totals.rows,
        totals.kept,
        totals.not_root,
        totals.no_pair,
        totals.same_country,
        totals.malformed,
        totals.stale,
        ", truncated" if totals.truncated else "",
        upserted,
        len(lost),
        "" if len(lost) == 1 else "s",
        time.monotonic() - began,
        timing["download"],
        timing["parse"],
        timing["store"],
    )
    if totals.unmapped:
        top = ", ".join(f"{c} {n}" for c, n in totals.unmapped.most_common(5))
        logger.info("Events: unmapped actor codes: %s.", top)


async def _add_file(
    slot: datetime,
    entry: LastUpdateEntry | None,
    today: date,
    rollups: dict[Key, Rollup],
    totals: ParseStats,
    timing: dict[str, float],
) -> FileResult | None:
    """Fetch, check, read and parse one slot's file. Its rollups merge into
    *rollups* only once it has parsed whole. Returns what to record, or None to
    try the slot again next cycle (a failed download, a failed MD5 check).

    *entry* is lastupdate.txt's line for the newest file (its size and MD5), which
    gets NEWEST_ATTEMPTS of NEWEST_TIMEOUT_S; None for a catch-up slot, which
    gets CATCHUP_ATTEMPTS of CATCHUP_TIMEOUT_S.
    """
    name = _name(slot)
    if entry is not None and entry.size > MAX_ZIP_BYTES:
        logger.warning(
            "Events: %s is %d bytes, over %d; recorded unreadable.", name, entry.size, MAX_ZIP_BYTES
        )
        return FileResult(slot, "unreadable", 0, 0)
    started = time.monotonic()
    if entry is None:
        got = await download_capped(
            slot_url(slot), MAX_ZIP_BYTES, attempts=CATCHUP_ATTEMPTS, timeout=CATCHUP_TIMEOUT_S
        )
    else:
        got = await download_capped(
            slot_url(slot), MAX_ZIP_BYTES, attempts=NEWEST_ATTEMPTS, timeout=NEWEST_TIMEOUT_S
        )
    timing["download"] += time.monotonic() - started
    if got.status == "missing" and entry is None:
        return FileResult(slot, "missing", 0, 0)
    if got.status == "too_big":
        logger.warning("Events: %s is over %d bytes; recorded unreadable.", name, MAX_ZIP_BYTES)
        return FileResult(slot, "unreadable", 0, 0)
    if got.status != "ok":
        logger.warning("Events: %s download %s; retried next cycle.", name, got.status)
        return None
    # lastupdate.txt gives only the newest file's MD5, so a file that fails it is
    # retried as a catch-up slot, without one: there the zip's CRC32 (read_export)
    # still catches a damaged file, and the pinned HTTPS host a tampered one.
    if (
        entry is not None
        and _MD5.fullmatch(entry.md5)
        and hashlib.md5(got.body, usedforsecurity=False).hexdigest() != entry.md5
    ):
        logger.warning("Events: %s failed its MD5 check; retried next cycle.", name)
        return None
    raw = read_export(got.body)
    if raw is None:
        logger.warning("Events: %s is not one capped export CSV; recorded unreadable.", name)
        return FileResult(slot, "unreadable", 0, 0)
    started = time.monotonic()
    part: dict[Key, Rollup] = {}
    stats = await asyncio.to_thread(parse_events, raw, today, part)
    timing["parse"] += time.monotonic() - started
    for key, rollup in part.items():
        rollups.setdefault(key, Rollup()).merge(rollup)
    totals.add(stats)
    return FileResult(slot, "ok", stats.rows, stats.kept)
