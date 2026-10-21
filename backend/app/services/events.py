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

import io
import math
import re
import zipfile
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import NamedTuple

from app.config import settings
from app.services.cameo_countries import cameo_to_iso2
from app.services.gdelt import _GDELT_HOST
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
# The whole step's bound: on a timeout nothing is claimed, so it's retried
# next cycle. Catch-up files get one retry and a short timeout; the newest
# gets download_capped's defaults (3 tries, 30 s each).
EVENTS_STEP_TIMEOUT_S = 60
CATCHUP_ATTEMPTS = 2
CATCHUP_TIMEOUT_S = 10.0
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
        event = _event(line.split("\t"))
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
                    stats.unmapped[code] += 1
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
