"""On-demand voice eval for the co-pilot and the board memo (Phase 6).

Never run on CI: every run calls Claude. pytest collects tests/ only, and
tests/test_voice_eval.py covers this script's pure parts with stubs.

Run from backend/ (it reads backend/.env for ANTHROPIC_API_KEY):

    python -m scripts.voice_eval capture --base-url https://orbisapp.co
    python -m scripts.voice_eval run --pilot
    python -m scripts.voice_eval run --label baseline --planner --yes

capture reads the public API (GET threads, breaking; POST board resolve, which
caches each pin as any visitor's board does) and writes evals/voice/copilot.json
and memo.json. Questions come from TEMPLATES, filled with thread titles, places
and names, so no visitor text is ever an input; tests/test_voice_eval.py checks
every committed fixture.

run calls the production prompt paths (agent.synthesize_answer, then cite;
board.analyze_board; with --planner, agent.plan_retrieval) with Haiku 5.5 as
configured, --reps times per fixture (the planner once). It counts one spend for
the whole run and stops at --max-usd. Production's Redis and database are never
touched (isolate()): llm_budget counts in this process's memory, so visitors'
daily budget is untouched. Results go to ../.claude/hillclimb/voice-<surface>/
<label>/ (gitignored): results.jsonl, one row per (case, rep), written as each
finishes, and report.md for the manual read.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import sys
import time
from collections.abc import Sequence
from contextvars import ContextVar
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from unittest.mock import patch

import anthropic
import httpx

from app.config import settings
from app.services import agent, board, llm_budget, voice
from app.services.llm import ClaudeRefusalError, response_text

FIXTURES = Path(__file__).resolve().parent.parent / "evals" / "voice"
RESULTS = Path(__file__).resolve().parents[2] / ".claude" / "hillclimb"
SURFACES = ("copilot", "memo")
REPS = 3
MAX_USD = 0.25
CONCURRENCY = 4
# Estimated $ per call (the plan's "Expected cost"); --pilot prints the measured one.
EST_USD = {"copilot": 0.0009, "planner": 0.0003, "memo": 0.0006}

SPECIFIC = ("place", "briefing", "who", "connection", "why", "latest", "follow_up", "coverage")
BROAD = ("broad_biggest", "broad_new", "broad_know")
TEMPLATES = {
    "place": "What's happening in {place}?",
    "briefing": "Give me a briefing on {story}.",
    "who": "Who is {person}?",
    "connection": "How is {person} connected to {other}?",
    "why": "What's behind {story}?",
    "latest": "What's the latest on {story}?",
    "follow_up": "Tell me more about {person}.",
    "coverage": "How are outlets covering {story}?",
    # Broad questions (PR 21d): the owner's live case first.
    "broad_biggest": "What's the biggest story right now?",
    "broad_new": "What's new in the last few hours?",
    "broad_know": "What should I know about today?",
}
# Thread topics as the co-pilot's topic pills name them (agent.SCREEN_TOPICS).
SCREEN_TOPIC = {
    "politics": "Politics",
    "conflict": "Conflict",
    "technology": "Technology",
    "environment": "Climate",
    "economy": "Economy",
    "health": "Health",
}
# Article pins that no longer resolve: one with saved text, one without.
EXPIRED = (
    "article:00000000-0000-4000-8000-000000000001",
    "article:00000000-0000-4000-8000-000000000002",
)
TOP_THREADS = 5  # PR 21d's top_stories: threads, then breaking events
TOP_BREAKING = 3

# What a surface shows instead of an AI answer, by outcome.
OUTCOMES = {
    "I'm sorry, I couldn't generate an answer right now.": "apology",
    board.MEMO_FAILED: "failed",
    board.NOT_ENOUGH_PINS: "not_enough",
}
if getattr(agent, "_NO_ANSWER", None):  # from PR 21b
    OUTCOMES[agent._NO_ANSWER] = "no_answer"
_PAUSED = ("AI summaries are paused", "AI answers are paused")


def isolate() -> None:
    """No production state: llm_budget counts in memory (with a cap no run reaches, so
    nothing is paused), and nothing reads the database. The run's own cap governs."""
    settings.redis_url = ""
    settings.database_url = ""
    settings.llm_daily_budget_usd = 100.0
    if not settings.anthropic_api_key:
        sys.exit("ANTHROPIC_API_KEY is not set (backend/.env or the environment).")


# --- Fixtures: built from thread data only ------------------------------------------


def _places(d: dict) -> list[dict]:
    return d.get("spread") or d.get("places") or []


def _rows(d: dict) -> list[dict]:
    """The thread's newest stories as retrieval rows (_build_context's input)."""
    coords = {p["place"]: (p["lat"], p["lng"]) for p in _places(d)}
    rows = []
    for a in d["articles"][:12]:
        lat, lng = coords.get(a["place"], (None, None))
        rows.append(
            {
                "title": a["title"],
                "source_url": a["source_url"],
                "source_name": a["source_name"],
                "latitude": lat,
                "longitude": lng,
            }
        )
    return rows


def _graph(d: dict, rows: list[dict]) -> dict:
    """An entity_lookup-shaped result from the thread's names (their types unknown)."""
    names = d["entities"]
    return {
        "node": {"name": names[0]["name"], "type": "ENTITY"},
        "connections": [
            {"name": e["name"], "type": "ENTITY", "rel_type": "CO_MENTIONED", "weight": e["n"]}
            for e in names[1:8]
        ],
        "articles": rows[:5],
    }


def copilot_case(i: int, d: dict, now: datetime) -> dict:
    """A specific question about thread *d*, from SPECIFIC[i] and its data."""
    template = SPECIFIC[i % len(SPECIFIC)]
    names = [e["name"] for e in d["entities"]]
    places = [p["place"] for p in _places(d)]
    slots = {"place": places[0], "story": d["title"], "person": names[0], "other": names[1]}
    rows = _rows(d)
    results: list[dict] = [{"tool": "keyword_search", "result": rows}]
    if template in ("who", "connection", "follow_up"):
        results.insert(0, {"tool": "entity_lookup", "result": _graph(d, rows)})
    case = {
        "id": f"cp-{i + 1}-{template}",
        "tags": [template],
        "template": template,
        "slots": slots,
        "question": TEMPLATES[template].format(**slots),
        "source": {"title": d["title"], "names": names, "places": places},
        "now": now.isoformat(),
        "results": results,
        "history": [],
    }
    if template == "place":  # the live 24 h preset, on the thread's first place
        case["screen"] = {
            "place": places[0],
            "start": (now - timedelta(hours=24)).isoformat(),
            "end": now.isoformat(),
        }
    if template == "latest":  # yesterday's UTC day, with the thread's topic pill
        day = (now - timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        case["screen"] = {
            "topic": SCREEN_TOPIC.get(d.get("topic")),
            "start": day.isoformat(),
            "end": (day + timedelta(days=1)).isoformat(),
        }
    if template == "follow_up":
        case["history"] = [
            {"role": "user", "content": TEMPLATES["briefing"].format(**slots)},
            {"role": "assistant", "content": f"{rows[0]['title']} [1]."},
        ]
    return case


def coverage_words(outlets: int, countries: int, status: str) -> str:
    """A thread's breadth, as the top_stories context says it (PR 21d)."""
    places = "country" if countries == 1 else "countries"
    return f"{outlets} outlets, {countries} {places}, {status}"


def top_rows(threads: list[dict], breaking: list[dict], urls: dict[int, str]) -> list[dict]:
    """PR 21d's top_stories rows, from /api/threads and /api/news/breaking answers: the
    TOP_THREADS threads the most outlets, then countries, cover, then up to
    TOP_BREAKING breaking events. 21d moves this into app.services.retrieval and
    imports it here, so fixtures and the tool can't drift."""
    ranked = sorted(threads, key=lambda t: (-t["n_sources"], -len(t["countries"]), t["id"]))
    rows = []
    for t in ranked[:TOP_THREADS]:
        place = (_places(t) or [{}])[0]
        rows.append(
            {
                "title": t["title"],
                "summary": t.get("synopsis"),
                "source_url": urls.get(t["id"], ""),
                "source_name": (t.get("lead") or {}).get("source_name", ""),
                "latitude": place.get("lat"),
                "longitude": place.get("lng"),
                "coverage": coverage_words(t["n_sources"], len(t["countries"]), t["status"]),
            }
        )
    for b in breaking[:TOP_BREAKING]:
        rows.append(
            {
                "title": b["headline"],
                "summary": None,
                "source_url": "",
                "source_name": b["lead"]["source_name"],
                "latitude": b["lat"],
                "longitude": b["lng"],
                "coverage": f"breaking: {b['outlets']} outlets in the last 2 hours, {b['place']}",
            }
        )
    return rows


def broad_case(
    k: int, rows: list[dict], now: datetime, breaking: Sequence[dict] | None = ()
) -> dict:
    """A broad question (BROAD[k]) over the top-stories rows captured with it. Its
    "breaking" says what the breaking list was: the headlines taken, or "unavailable"
    when the API failed to give it (*breaking* None)."""
    template = BROAD[k]
    case = {
        "id": f"cp-{len(SPECIFIC) + k + 1}-{template}",
        "tags": ["broad"],
        "template": template,
        "slots": {},
        "question": TEMPLATES[template],
        "source": {"title": "", "names": [], "places": []},
        "now": now.isoformat(),
        "results": [{"tool": "top_stories", "result": rows}],
        "history": [],
        "breaking": (
            "unavailable" if breaking is None else [b["headline"] for b in breaking[:TOP_BREAKING]]
        ),
    }
    if template == "broad_biggest":  # the owner's live case: "Last 24 h, live"
        case["screen"] = {"start": (now - timedelta(hours=24)).isoformat(), "end": now.isoformat()}
    return case


def memo_boards(d: list[dict]) -> list[tuple[list[str], list[dict | None]]]:
    """Eight boards over eight threads: each pin kind, a saved pin, an expired one,
    names only, and unrelated stories."""

    def thread(x: dict) -> str:
        return f"thread:{x['id']}"

    def person(x: dict, k: int = 0) -> str:
        return f"entity:person:{x['entities'][k]['name']}"

    def place(x: dict) -> str:
        p = _places(x)[0]
        return f"place:{math.floor(p['lat'])}:{math.floor(p['lng'])}"

    def link(x: dict) -> str:
        a, b = sorted(x["countries"][:2])
        return f"link:{a}-{b}"

    boards = [
        [thread(d[0]), person(d[0]), place(d[0])],
        [thread(d[1]), thread(d[2]), link(d[1])],
        [person(d[3]), person(d[3], 1), thread(d[3])],
        [thread(d[4]), thread(d[5]), person(d[4]), person(d[5]), place(d[4]), link(d[5])],
        [EXPIRED[0], thread(d[6]), person(d[6])],  # an expired pin with saved text
        [thread(d[7]), EXPIRED[1], person(d[7])],  # an expired pin with nothing saved
        [person(d[0], 1), person(d[2]), thread(d[2])],  # mostly names: no dates
        [thread(d[0]), thread(d[7])],  # unrelated stories
    ]
    saved: list[list[dict | None]] = [[None] * len(b) for b in boards]
    a = d[6]["articles"][0]
    saved[4][0] = {"title": a["title"], "place": a["place"], "time": a["published_at"]}
    return list(zip(boards, saved))


def pins_with_text(snapshots: list[dict | None], saved: list[dict | None]) -> int:
    return sum(1 for snap, kept in zip(snapshots, saved) if snap is not None or kept is not None)


def _templated(slots: dict) -> set[str]:
    out = set()
    for template in TEMPLATES.values():
        try:
            out.add(template.format(**slots))
        except KeyError:
            pass
    return out


def _headlines(results: list[dict]) -> set[str]:
    titles = set()
    for result in results:
        data = result["result"]
        for row in data if isinstance(data, list) else data.get("articles", []):
            titles.add(row.get("title"))
    return titles


def check_fixture(case: dict) -> list[str]:
    """Why a co-pilot fixture could carry visitor text; [] when it can't."""
    problems = []
    if case["question"] != TEMPLATES[case["template"]].format(**case["slots"]):
        problems.append("question is not its template")
    source = case["source"]
    known = {source["title"], *source["names"], *source["places"]}
    problems += [
        f"slot {k} is not from the thread" for k, v in case["slots"].items() if v not in known
    ]
    headlines = _headlines(case["results"])
    for n, turn in enumerate(case.get("history", [])):
        if turn["role"] == "user":
            allowed = _templated(case["slots"])
        else:
            allowed = {f"{h} [1]." for h in headlines}
        if turn["content"] not in allowed:
            problems.append(f"history turn {n} is not from a template or a headline")
    return problems


# --- Scoring --------------------------------------------------------------------------


def _unfenced(text: str) -> str:
    """The reply without a Markdown code fence around it, as synthesize_answer read it."""
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
    return text


def raw_reply(surface: str, response: Any) -> tuple[str, dict[str, str], bool]:
    """What Claude wrote before any guard: (prose, memo sections, refused). The prose
    is the answer, or the memo's three sections joined."""
    try:
        text = _unfenced(response_text(response))
    except ClaudeRefusalError:
        return "", {}, True
    try:
        data = json.loads(text)
    except ValueError:
        return text, {}, False
    if surface == "copilot" and isinstance(data, dict) and isinstance(data.get("answer"), str):
        return data["answer"], {}, False
    if surface == "memo" and isinstance(data, dict):
        sections = {k: v for k, v in data.items() if isinstance(v, str)}
        return " ".join(sections.values()), sections, False
    return text, {}, False


def outcome(shown: str) -> str:
    text = shown.strip()
    if text.startswith(_PAUSED):
        return "paused"
    return OUTCOMES.get(text, "answer")


def emptied_by_guard(surface: str, raw: str, sections: dict[str, str]) -> bool:
    """Whether the guard alone would leave nothing: the answer, or a memo section
    (a Contradictions section that said "None apparent" keeps those words)."""
    if surface == "copilot":
        return bool(raw.strip()) and not voice.scrub(raw).text
    for key, text in sections.items():
        if key == "contradictions" and text.lower().startswith("none apparent"):
            continue
        if not voice.scrub(text).text:
            return True
    return False


def score(
    surface: str,
    raw: str,
    sections: dict[str, str],
    shown: str,
    response: Any,
    seconds: float,
    refused: bool = False,
) -> dict:
    """One output's grades: leak kinds before and after the guard, its outcome, whether
    the guard emptied it, its size and its cost. "Shown" leaks are 0 by construction
    once a surface is guarded (same detector): misses are counted in the manual read."""
    usage = getattr(response, "usage", None)
    return {
        "raw_kinds": voice.find_leaks(raw),
        "shown_kinds": voice.find_leaks(shown),
        "outcome": outcome(shown),
        "guard_emptied": emptied_by_guard(surface, raw, sections),
        "refused": refused,
        "words": len(shown.split()),
        "input_tokens": getattr(usage, "input_tokens", 0),
        "output_tokens": getattr(usage, "output_tokens", 0),
        "cost_usd": round(llm_budget.cost_usd(usage, response.model), 6) if usage else 0.0,
        "seconds": round(seconds, 2),
    }


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """The 95% Wilson interval of k in n. Reps of one fixture aren't independent, so
    use n = fixtures, not outputs, when reading it as a noise floor."""
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    d = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / d
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (max(0.0, centre - half), min(1.0, centre + half))


def summarise(rows: list[dict]) -> dict:
    n = len(rows)
    fixtures = len({r["id"] for r in rows})
    leaking = {r["id"] for r in rows if r["raw_kinds"]}
    kinds: dict[str, int] = {}
    outcomes: dict[str, int] = {}
    for r in rows:
        for kind in r["raw_kinds"]:
            kinds[kind] = kinds.get(kind, 0) + 1
        outcomes[r["outcome"]] = outcomes.get(r["outcome"], 0) + 1
    return {
        "n": n,
        "fixtures": fixtures,
        "raw_leaks": sum(1 for r in rows if r["raw_kinds"]),
        "fixtures_leaking": len(leaking),
        "fixtures_ci": wilson(len(leaking), fixtures),
        "shown_leaks": sum(1 for r in rows if r["shown_kinds"]),
        "guard_emptied": sum(1 for r in rows if r["guard_emptied"]),
        "outcomes": dict(sorted(outcomes.items())),
        "refusals": sum(1 for r in rows if r["refused"]),
        "mean_input_tokens": round(sum(r["input_tokens"] for r in rows) / n) if n else 0,
        "mean_output_tokens": round(sum(r["output_tokens"] for r in rows) / n) if n else 0,
        "cost_usd": round(sum(r["cost_usd"] for r in rows), 4),
        "kinds": dict(sorted(kinds.items())),
    }


def routed(case: dict, tools: list[str]) -> bool:
    """Broad questions go to top_stories alone; specific ones never do (PR 21d)."""
    if "broad" in case.get("tags", []):
        return tools == ["top_stories"]
    return "top_stories" not in tools


# --- Capture (public API, read-only) ------------------------------------------------------


async def _get(http: httpx.AsyncClient, path: str, **params: Any) -> Any:
    response = await http.get(path, params=params)
    response.raise_for_status()
    return response.json()


async def _breaking(http: httpx.AsyncClient) -> list[dict] | None:
    """The breaking ticker's list, or None when the server fails to give it:
    top_stories takes up to TOP_BREAKING events, none included, so the broad fixtures
    keep their threads, and each says "breaking": "unavailable". Said on the console
    too, so a capture never hides it. A client error is the capture's own mistake,
    and stops it."""
    try:
        return await _get(http, "/api/news/breaking")
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code
        if status < 500:
            raise
        print(
            f"The breaking list is unavailable (HTTP {status}): broad fixtures carry threads only."
        )
        return None


async def _resolve(http: httpx.AsyncClient, items: list[str]) -> list[dict | None]:
    response = await http.post("/api/board/resolve", json={"items": items})
    response.raise_for_status()
    return [r["snapshot"] for r in response.json()["items"]]


async def _board(http: httpx.AsyncClient, items: list[str], saved: list, spare: str) -> list:
    """Resolve a board: an unresolved person is asked again as an organisation, and a
    board left with fewer than two pins with text gets *spare* (a thread)."""
    snapshots = await _resolve(http, items)
    swapped = False
    for k, item in enumerate(items):
        if snapshots[k] is None and item.startswith("entity:person:"):
            items[k] = "entity:org:" + item.removeprefix("entity:person:")
            swapped = True
    if swapped:
        snapshots = await _resolve(http, items)
    if pins_with_text(snapshots, saved) < 2 and spare not in items:
        items.append(spare)
        saved.append(None)
        snapshots = await _resolve(http, items)
    if pins_with_text(snapshots, saved) < 2:
        sys.exit(f"A board has fewer than two pins with text: {items}")
    return snapshots


async def capture(base_url: str) -> None:
    """Fixtures from the public API. Board resolve caches each pin's record in Redis
    until the cycle ends, as any visitor's board does; nothing else is written."""
    async with httpx.AsyncClient(base_url=base_url, timeout=30) as http:
        listed = await _get(http, "/api/threads", timespan="168h", limit=50)
        details = []
        for t in listed:
            if len(details) == len(SPECIFIC):
                break
            if not t.get("synopsis") or len(t.get("countries", [])) < 2:
                continue
            d = await _get(http, f"/api/threads/{t['id']}")
            if len(d["entities"]) >= 2 and _places(d) and d["articles"]:
                details.append(d)
        if len(details) < len(SPECIFIC):
            sys.exit(f"Only {len(details)} usable threads; need {len(SPECIFIC)}.")
        now = datetime.now(timezone.utc).replace(microsecond=0)
        copilot = [copilot_case(i, d, now) for i, d in enumerate(details)]

        # Broad questions: what /api/threads (24 h, the rail's warmed list) and the
        # breaking ticker show now, with each top thread's newest story as its link.
        top = await _get(http, "/api/threads", timespan="24h", limit=20)
        breaking = await _breaking(http)
        ranked = sorted(top, key=lambda t: (-t["n_sources"], -len(t["countries"]), t["id"]))
        urls = {}
        for t in ranked[:TOP_THREADS]:
            d = await _get(http, f"/api/threads/{t['id']}")
            urls[t["id"]] = d["articles"][0]["source_url"] if d["articles"] else ""
        rows = top_rows(top, breaking or [], urls)
        copilot += [broad_case(k, rows, now, breaking) for k in range(len(BROAD))]

        memo = []
        for n, (items, saved) in enumerate(memo_boards(details), start=1):
            spare = f"thread:{details[n - 1]['id']}"
            snapshots = await _board(http, items, saved, spare)
            memo.append(
                {
                    "id": f"memo-{n}",
                    "items": items,
                    "snapshots": snapshots,
                    "saved": saved,
                    "now": now.isoformat(),
                }
            )
    FIXTURES.mkdir(parents=True, exist_ok=True)
    for name, data in (("copilot.json", copilot), ("memo.json", memo)):
        text = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
        (FIXTURES / name).write_text(text, encoding="utf-8")
    print(f"Wrote {len(copilot)} co-pilot and {len(memo)} memo fixtures to {FIXTURES}.")


# --- Run --------------------------------------------------------------------------------

# Each case's Claude responses, per asyncio task (gather gives each its own context).
_CALLS: ContextVar[list] = ContextVar("voice_eval_calls")
_SNAPSHOTS: ContextVar[list] = ContextVar("voice_eval_snapshots")
_REAL_CLIENT = anthropic.AsyncAnthropic


def _recording_client(*args: Any, **kwargs: Any) -> anthropic.AsyncAnthropic:
    """A real client whose responses are also kept for the running case."""
    client = _REAL_CLIENT(*args, **kwargs)
    create = client.messages.create

    async def recorded(**params: Any) -> Any:
        response = await create(**params)
        _CALLS.get().append(response)
        return response

    client.messages.create = recorded  # type: ignore[method-assign]
    return client


def _when(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def _snapshot(s: dict | None) -> dict | None:
    return None if s is None else {**s, "time": _when(s.get("time"))}


async def _fixture_snapshots(items: Any, now: Any) -> list:  # stands in for resolve_items
    return _SNAPSHOTS.get()


async def _no_cache(*args: Any, **kwargs: Any) -> None:
    return None


def _scope(case: dict) -> agent.ScreenScope | None:
    screen = case.get("screen")
    if not screen:
        return None
    return agent.clean_screen_context(
        screen.get("place"),
        screen.get("topic"),
        _when(screen.get("start")),
        _when(screen.get("end")),
        now=_when(case["now"]),
    )


def _history(case: dict) -> list[dict]:
    return [{"role": t["role"], "content": t["content"]} for t in case["history"]]


async def run_copilot(case: dict) -> str:
    """One answer through the production path, as both routes run it after retrieval."""
    context, index = agent._build_context(case["results"])
    result = await agent.synthesize_answer(case["question"], context, _history(case), _scope(case))
    if hasattr(agent, "cite"):  # PR 21b: the numbering the visitor sees
        result = agent.cite(result, index)
    return result["answer"]


async def run_memo(case: dict) -> str:
    _SNAPSHOTS.set([_snapshot(s) for s in case["snapshots"]])
    items = [board.parse_item(i) for i in case["items"]]
    saved = [_snapshot(s) for s in case["saved"]]
    memo = await board.analyze_board(items, saved, _when(case["now"]))
    return " ".join(s["text"] for s in memo["sections"]) or (memo["message"] or "")


def _rows_in(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


class Spend:
    """One spend counter for the whole run, every surface and the planner (review I4).

    allows() reserves a call's estimate, so calls in flight together can't all pass
    the cap; add() swaps that reservation for what the calls cost."""

    def __init__(self, cap: float) -> None:
        self.cap, self.spent, self.reserved = cap, 0.0, 0.0

    def allows(self, estimate: float) -> bool:
        if self.spent + self.reserved + estimate > self.cap:
            return False
        self.reserved += estimate
        return True

    def add(self, calls: list, estimate: float) -> None:
        self.reserved = max(0.0, self.reserved - estimate)
        self.spent += sum(llm_budget.cost_usd(c.usage, c.model) for c in calls)


class UncountedCall(RuntimeError):
    """An AI answer came back with no Claude call recorded: its spend is out of the
    cap's sight, so the run stops."""


def counted(calls: list, shown: str) -> None:
    """Stops the run (UncountedCall) when *shown* is an AI answer but no call was
    recorded: a surface that built its own client would otherwise run uncapped. A
    fixed text (not enough pins, paused, an apology) needs no call."""
    if not calls and outcome(shown) == "answer":
        raise UncountedCall("An AI answer came back with no recorded Claude call.")


async def run_surface(surface: str, label: str, reps: int, spend: Spend, pilot: bool) -> dict:
    cases = json.loads((FIXTURES / f"{surface}.json").read_text(encoding="utf-8"))
    if pilot:
        cases, reps, label = cases[:1], 1, "pilot"
    out = RESULTS / f"voice-{surface}" / label
    out.mkdir(parents=True, exist_ok=True)
    results = out / "results.jsonl"
    finished = {(r["id"], r["rep"]) for r in _rows_in(results)}
    sem = asyncio.Semaphore(CONCURRENCY)

    async def one(case: dict, rep: int) -> None:
        if (case["id"], rep) in finished:
            return
        async with sem:
            if not spend.allows(EST_USD[surface]):
                print(f"{case['id']} rep {rep}: skipped, the ${spend.cap} cap is reached.")
                return
            calls: list = []
            _CALLS.set(calls)
            began = time.monotonic()
            try:
                shown = await (run_copilot(case) if surface == "copilot" else run_memo(case))
            finally:
                spend.add(calls, EST_USD[surface])
            seconds = time.monotonic() - began
            counted(calls, shown)
            response = calls[-1] if calls else None
            raw, sections, refused = raw_reply(surface, response) if response else ("", {}, False)
            row = {
                "id": case["id"],
                "rep": rep,
                "tags": case.get("tags", []),
                "shown": shown,
                "raw": raw,
                **score(surface, raw, sections, shown, response, seconds, refused),
            }
            with results.open("a", encoding="utf-8") as f:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")

    await asyncio.gather(*(one(c, r) for c in cases for r in range(reps)))
    rows = _rows_in(results)
    summary = summarise(rows)
    _report(out / "report.md", surface, label, cases, rows, summary)
    return summary


async def run_planner(label: str, spend: Spend) -> dict:
    """Each co-pilot fixture's question through the planner once: the tools it picks."""
    cases = json.loads((FIXTURES / "copilot.json").read_text(encoding="utf-8"))
    out = RESULTS / "voice-planner" / label
    out.mkdir(parents=True, exist_ok=True)
    rows = []
    for case in cases:
        if not spend.allows(EST_USD["planner"]):
            break
        calls: list = []
        _CALLS.set(calls)
        try:
            planned = await agent.plan_retrieval(case["question"], _history(case), _scope(case))
        finally:
            spend.add(calls, EST_USD["planner"])
        tools = [c["name"] for c in planned]
        ok = routed(case, tools)
        rows.append({"id": case["id"], "tags": case["tags"], "tools": tools, "routed": ok})
    (out / "results.jsonl").write_text(
        "".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8"
    )
    broad = [r for r in rows if "broad" in r["tags"]]
    specific = [r for r in rows if "broad" not in r["tags"]]
    return {
        "broad_routed": f"{sum(r['routed'] for r in broad)}/{len(broad)}",
        "specific_routed": f"{sum(r['routed'] for r in specific)}/{len(specific)}",
        "misrouted": [(r["id"], r["tools"]) for r in rows if not r["routed"]],
    }


def _report(path: Path, surface: str, label: str, cases: list, rows: list, s: dict) -> None:
    low, high = s["fixtures_ci"]
    inputs = {c["id"]: c.get("question") or " | ".join(c["items"]) for c in cases}
    lines = [
        f"# Voice eval: {surface}, {label}",
        "",
        f"- Outputs: {s['n']} ({s['fixtures']} fixtures); cost ${s['cost_usd']}",
        f"- Raw leaks (before the guard): {s['raw_leaks']}/{s['n']} outputs; "
        f"{s['fixtures_leaking']}/{s['fixtures']} fixtures (95% CI {low:.0%}–{high:.0%}); "
        f"kinds {s['kinds']}",
        f"- Shown leaks: {s['shown_leaks']}/{s['n']} (0 by construction once guarded)",
        f"- Outcomes: {s['outcomes']}; emptied by the guard: {s['guard_emptied']}; "
        f"refusals: {s['refusals']}",
        f"- Mean tokens per call: {s['mean_input_tokens']} in / {s['mean_output_tokens']} out",
        "",
        "## Manual read: count misses (leaks shown), false positives (news dropped),",
        "## unsupported claims, and for broad questions whether it leads with the widest stories",
        "",
    ]
    for r in sorted(rows, key=lambda r: (r["id"], r["rep"])):
        lines += [
            f"### {r['id']} rep {r['rep']} {r['tags']} ({r['outcome']})",
            f"**Input:** {inputs.get(r['id'], '')}",
            "",
            r["shown"],
            "",
            f"Raw kinds: {r['raw_kinds'] or 'none'}",
            "",
        ]
    path.write_text("\n".join(lines), encoding="utf-8")


async def run(
    surfaces: list[str], label: str, reps: int, max_usd: float, pilot: bool, planner: bool
) -> None:
    isolate()
    spend = Spend(max_usd)
    with (
        patch.object(anthropic, "AsyncAnthropic", _recording_client),
        patch.object(board, "resolve_items", _fixture_snapshots),
        patch.object(board, "get_cached", _no_cache),
        patch.object(board, "set_cached", _no_cache),
    ):
        if planner and not pilot:
            print(f"planner: {await run_planner(label, spend)}")
        for surface in surfaces:
            print(f"{surface}: {await run_surface(surface, label, reps, spend, pilot)}")
    print(f"Spent ${spend.spent:.4f} of ${max_usd}.")


def _fixture_count(name: str) -> int:
    return len(json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8")))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    cap = sub.add_parser("capture")
    cap.add_argument("--base-url", required=True)
    go = sub.add_parser("run")
    go.add_argument("--surface", choices=(*SURFACES, "both"), default="both")
    go.add_argument("--label", default="baseline")
    go.add_argument("--reps", type=int, default=REPS)
    go.add_argument("--max-usd", type=float, default=MAX_USD, help="the cap for the whole run")
    go.add_argument("--planner", action="store_true", help="also route each question once")
    go.add_argument("--pilot", action="store_true", help="1 case per surface, 1 rep")
    go.add_argument("--yes", action="store_true", help="confirm a full, paid run")
    args = parser.parse_args()
    if args.command == "capture":
        asyncio.run(capture(args.base_url))
        return
    surfaces = list(SURFACES) if args.surface == "both" else [args.surface]
    if not args.pilot:
        estimate = sum(_fixture_count(s) * args.reps * EST_USD[s] for s in surfaces)
        if args.planner:
            estimate += _fixture_count("copilot") * EST_USD["planner"]
        print(f"Estimated ${estimate:.3f} for this run (cap ${args.max_usd}).")
        if estimate > args.max_usd:
            sys.exit("The estimate is over the cap: lower --reps or raise --max-usd.")
        if not args.yes:
            sys.exit("Add --yes to run it.")
    planner = args.planner and "copilot" in surfaces
    asyncio.run(run(surfaces, args.label, args.reps, args.max_usd, args.pilot, planner))


if __name__ == "__main__":
    main()
