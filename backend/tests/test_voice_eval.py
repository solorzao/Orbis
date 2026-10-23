"""scripts.voice_eval's pure parts, fixture builders and the committed fixtures.
No Claude, no network."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from types import SimpleNamespace

import httpx
import pytest

from app.config import settings
from app.services import board
from scripts import voice_eval

NOW = datetime(2026, 10, 23, 12, tzinfo=timezone.utc)


def _thread(i: int = 7, **changes) -> dict:
    """A thread as /api/threads/{id} answers, trimmed to what the builders read."""
    thread = {
        "id": i,
        "title": "Fuel queues grow in Lagos",
        "synopsis": "Queues for fuel grew across Lagos as supplies ran short.",
        "status": "developing",
        "n_sources": 12,
        "countries": ["NG", "GB"],
        "topic": "economy",
        "places": [{"lat": 6.45, "lng": 3.39, "place": "Lagos, Nigeria"}],
        "lead": {"source_name": "Punch"},
        "entities": [{"name": "Bola Tinubu", "n": 6}, {"name": "ECOWAS", "n": 3}],
        "articles": [
            {
                "title": "Fuel queues grow",
                "source_name": "Punch",
                "published_at": "2026-10-23T09:00:00+00:00",
                "source_url": "https://punchng.com/a",
                "place": "Lagos, Nigeria",
            }
        ],
    }
    return {**thread, **changes}


def _breaking(n: int = 1) -> dict:
    return {
        "headline": f"Storm hits coast {n}",
        "place": "Valencia, Spain",
        "lat": 39.5,
        "lng": -0.5,
        "outlets": 9,
        "lead": {"source_name": "EFE"},
    }


def _response(text: str, stop_reason: str = "end_turn"):
    thinking = SimpleNamespace(type="thinking", thinking="", signature="s")
    return SimpleNamespace(
        stop_reason=stop_reason,
        content=[thinking, SimpleNamespace(type="text", text=text)],
        usage=SimpleNamespace(input_tokens=3000, output_tokens=1000),
        model="claude-haiku-5-5",
    )


def _fixtures(name: str) -> list[dict]:
    path = voice_eval.FIXTURES / name
    if not path.exists():  # captured in Task 21a.4, committed with this PR
        pytest.skip(f"{name} not captured yet")
    return json.loads(path.read_text(encoding="utf-8"))


# --- Builders ---------------------------------------------------------------------------


def test_rows_carry_their_place_coordinates():
    [row] = voice_eval._rows(_thread())
    assert row == {
        "title": "Fuel queues grow",
        "source_url": "https://punchng.com/a",
        "source_name": "Punch",
        "latitude": 6.45,
        "longitude": 3.39,
    }


def test_graph_has_the_threads_names():
    graph = voice_eval._graph(_thread(), [])
    assert graph["node"]["name"] == "Bola Tinubu"
    assert [c["name"] for c in graph["connections"]] == ["ECOWAS"]


@pytest.mark.parametrize("i", range(len(voice_eval.SPECIFIC)))
def test_each_specific_case_is_its_template_filled_from_the_thread(i):
    case = voice_eval.copilot_case(i, _thread(), NOW)
    assert voice_eval.check_fixture(case) == []
    assert case["template"] == voice_eval.SPECIFIC[i]


def test_specific_cases_carry_their_screens_and_history():
    place, latest, follow_up = (voice_eval.copilot_case(i, _thread(), NOW) for i in (0, 5, 6))
    assert place["screen"]["place"] == "Lagos, Nigeria"
    assert latest["screen"]["topic"] == "Economy"
    assert [t["role"] for t in follow_up["history"]] == ["user", "assistant"]


def test_coverage_words():
    assert voice_eval.coverage_words(12, 1, "emerging") == "12 outlets, 1 country, emerging"
    assert voice_eval.coverage_words(3, 4, "fading") == "3 outlets, 4 countries, fading"


def test_top_rows_rank_by_outlets_then_countries_and_cap():
    threads = [
        _thread(1, n_sources=3),
        _thread(2, n_sources=12, countries=["NG"]),
        _thread(3, n_sources=12),
        *(_thread(i, n_sources=5) for i in range(4, 9)),
    ]
    rows = voice_eval.top_rows(threads, [_breaking(n) for n in range(4)], {3: "https://a.com/3"})
    assert len(rows) == voice_eval.TOP_THREADS + voice_eval.TOP_BREAKING
    assert [r["coverage"] for r in rows[:2]] == [
        "12 outlets, 2 countries, developing",
        "12 outlets, 1 country, developing",
    ]
    assert rows[0]["source_url"] == "https://a.com/3" and rows[1]["source_url"] == ""
    assert rows[-1]["coverage"] == "breaking: 9 outlets in the last 2 hours, Valencia, Spain"


def test_broad_cases_are_fixed_questions_over_top_stories():
    rows = voice_eval.top_rows([_thread()], [], {})
    for k, template in enumerate(voice_eval.BROAD):
        case = voice_eval.broad_case(k, rows, NOW)
        assert voice_eval.check_fixture(case) == []
        assert case["question"] == voice_eval.TEMPLATES[template]
        assert case["results"] == [{"tool": "top_stories", "result": rows}]
        assert "broad" in case["tags"]
    assert "screen" in voice_eval.broad_case(0, rows, NOW)  # the owner's "Last 24 h, live"


def test_broad_cases_say_what_the_breaking_list_was():
    rows = voice_eval.top_rows([_thread()], [], {})
    assert voice_eval.broad_case(0, rows, NOW, None)["breaking"] == "unavailable"
    assert voice_eval.broad_case(0, rows, NOW, [])["breaking"] == []
    listed = [_breaking(n) for n in range(4)]
    case = voice_eval.broad_case(0, voice_eval.top_rows([_thread()], listed, {}), NOW, listed)
    assert case["breaking"] == [f"Storm hits coast {n}" for n in range(voice_eval.TOP_BREAKING)]


def test_memo_boards_cover_each_pin_kind_and_parse():
    boards = voice_eval.memo_boards([_thread(i) for i in range(1, 9)])
    assert len(boards) == 8
    assert boards[0][0] == ["thread:1", "entity:person:Bola Tinubu", "place:6:3"]
    assert boards[1][0][2] == "link:GB-NG"
    assert boards[4][0][0] == voice_eval.EXPIRED[0]
    assert boards[4][1][0]["title"] == "Fuel queues grow"
    for items, saved in boards:
        assert len(items) == len(saved)
        for item in items:
            board.parse_item(item)


def test_pins_with_text():
    snapshots, saved = [None, {"title": "a"}, None], [{"title": "b"}, None, None]
    assert voice_eval.pins_with_text(snapshots, saved) == 2


def _http(status: int, body: object = None) -> httpx.AsyncClient:
    def answer(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json=body)

    return httpx.AsyncClient(transport=httpx.MockTransport(answer), base_url="https://x")


@pytest.mark.asyncio
async def test_capture_reads_the_breaking_list():
    async with _http(200, [_breaking()]) as http:
        assert await voice_eval._breaking(http) == [_breaking()]


@pytest.mark.asyncio
async def test_capture_says_so_and_goes_on_without_the_breaking_list(capsys):
    async with _http(500) as http:
        assert await voice_eval._breaking(http) is None
    assert "breaking list is unavailable (HTTP 500)" in capsys.readouterr().out


@pytest.mark.asyncio
async def test_capture_stops_when_it_asks_the_breaking_list_wrongly():
    async with _http(422) as http:
        with pytest.raises(httpx.HTTPStatusError):
            await voice_eval._breaking(http)


def _api(threads: int = 200, breaking: int = 200) -> httpx.MockTransport:
    """The public API, faked: eight usable threads, the breaking list, board resolve
    (an article pin is expired, every other pin resolves)."""
    listed = [_thread(i, title=f"Story {i}") for i in range(1, 9)]
    by_id = {t["id"]: t for t in listed}

    def answer(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/api/threads":
            return httpx.Response(threads, json=listed)
        if path.startswith("/api/threads/"):
            return httpx.Response(200, json=by_id[int(path.rsplit("/", 1)[1])])
        if path == "/api/news/breaking":
            return httpx.Response(breaking, json=[_breaking()])
        if path == "/api/board/resolve":
            items = json.loads(request.content)["items"]
            snapshots = [None if i.startswith("article:") else {"title": i} for i in items]
            return httpx.Response(
                200, json={"items": [{"item": i, "snapshot": s} for i, s in zip(items, snapshots)]}
            )
        return httpx.Response(404)

    return httpx.MockTransport(answer)


def _capture_from(monkeypatch, tmp_path, transport: httpx.MockTransport) -> None:
    real = httpx.AsyncClient
    monkeypatch.setattr(
        voice_eval.httpx, "AsyncClient", lambda **kw: real(transport=transport, **kw)
    )
    monkeypatch.setattr(voice_eval, "FIXTURES", tmp_path)


@pytest.mark.asyncio
async def test_capture_stops_when_the_threads_list_fails(tmp_path, monkeypatch):
    _capture_from(monkeypatch, tmp_path, _api(threads=500))
    with pytest.raises(httpx.HTTPStatusError):
        await voice_eval.capture("https://orbis.test")
    assert list(tmp_path.iterdir()) == []


@pytest.mark.asyncio
async def test_capture_writes_fixtures_without_the_breaking_list_and_marks_them(
    tmp_path, monkeypatch
):
    _capture_from(monkeypatch, tmp_path, _api(breaking=503))
    await voice_eval.capture("https://orbis.test")
    copilot = json.loads((tmp_path / "copilot.json").read_text(encoding="utf-8"))
    memo = json.loads((tmp_path / "memo.json").read_text(encoding="utf-8"))
    assert (len(copilot), len(memo)) == (len(voice_eval.SPECIFIC) + len(voice_eval.BROAD), 8)
    broad = [c for c in copilot if "broad" in c["tags"]]
    assert [c["breaking"] for c in broad] == ["unavailable"] * len(voice_eval.BROAD)
    assert all(len(c["results"][0]["result"]) == voice_eval.TOP_THREADS for c in broad)
    assert all(voice_eval.check_fixture(c) == [] for c in copilot)


# --- Fixture checks -----------------------------------------------------------------------


def test_a_question_typed_by_anyone_fails():
    case = voice_eval.copilot_case(0, _thread(), NOW)
    case["question"] = "what about my cousin in Lagos?"
    assert "question is not its template" in voice_eval.check_fixture(case)


def test_a_slot_not_from_the_thread_fails():
    case = voice_eval.copilot_case(0, _thread(), NOW)
    case["slots"]["place"] = "Somewhere typed"
    case["question"] = "What's happening in Somewhere typed?"
    assert "slot place is not from the thread" in voice_eval.check_fixture(case)


def test_a_history_turn_not_from_a_template_fails():
    case = voice_eval.copilot_case(6, _thread(), NOW)
    case["history"][0]["content"] = "hi, I'm Sam"
    problems = voice_eval.check_fixture(case)
    assert "history turn 0 is not from a template or a headline" in problems


def test_committed_copilot_fixtures_carry_no_visitor_text():
    cases = _fixtures("copilot.json")
    assert sum("broad" in c["tags"] for c in cases) == len(voice_eval.BROAD)
    for case in cases:
        assert voice_eval.check_fixture(case) == [], case["id"]


def test_committed_broad_fixtures_carry_the_top_threads_and_the_breaking_state():
    broad = [c for c in _fixtures("copilot.json") if "broad" in c["tags"]]
    for case in broad:
        [result] = case["results"]
        assert len(result["result"]) >= voice_eval.TOP_THREADS, case["id"]
        assert case["breaking"] == "unavailable" or isinstance(case["breaking"], list)


def test_committed_memo_fixtures_parse_align_and_have_two_pins_with_text():
    for case in _fixtures("memo.json"):
        items = [board.parse_item(i) for i in case["items"]]
        assert len(items) == len(case["snapshots"]) == len(case["saved"]), case["id"]
        assert voice_eval.pins_with_text(case["snapshots"], case["saved"]) >= 2, case["id"]


# --- Scoring --------------------------------------------------------------------------------


def test_raw_reply_is_the_answer_or_the_memos_sections_without_a_fence():
    fenced = _response('```json\n{"answer": "Pin 2 is Lagos.", "globe_actions": []}\n```')
    assert voice_eval.raw_reply("copilot", fenced) == ("Pin 2 is Lagos.", {}, False)
    memo = _response(
        '{"possible_connections": "A.", "contradictions": "B.", "open_questions": "C."}'
    )
    raw, sections, refused = voice_eval.raw_reply("memo", memo)
    assert (raw, list(sections), refused) == (
        "A. B. C.",
        ["possible_connections", "contradictions", "open_questions"],
        False,
    )
    assert voice_eval.raw_reply("copilot", _response("", stop_reason="refusal")) == ("", {}, True)


@pytest.mark.parametrize(
    ("shown", "expected"),
    [
        ("Floods hit Valencia [1].", "answer"),
        ("I'm sorry, I couldn't generate an answer right now.", "apology"),
        (board.MEMO_FAILED, "failed"),
        (board.NOT_ENOUGH_PINS, "not_enough"),
        ("AI summaries are paused until 00:00 UTC (daily limit reached).", "paused"),
    ],
)
def test_outcomes_are_told_apart(shown, expected):
    assert voice_eval.outcome(shown) == expected


def test_emptied_by_the_guard():
    assert voice_eval.emptied_by_guard("copilot", "Pin 1 is Lagos.", {})
    assert not voice_eval.emptied_by_guard("copilot", "Floods hit Valencia [1].", {})
    kept = {"contradictions": "None apparent: pin 2 and pin 3 differ."}
    assert not voice_eval.emptied_by_guard("memo", "", kept)
    assert voice_eval.emptied_by_guard("memo", "", {"possible_connections": "Pin 2 is Lagos."})


def test_score_counts_leaks_before_and_after_the_guard_and_the_cost():
    row = voice_eval.score(
        "copilot", "Floods [1]. Pin 2 is Lagos.", {}, "Floods [1].", _response(""), 2.5
    )
    assert (row["raw_kinds"], row["shown_kinds"], row["outcome"]) == (["handle"], [], "answer")
    assert row["guard_emptied"] is False and row["words"] == 2
    assert row["cost_usd"] == pytest.approx(0.0008)  # 3,000 in and 1,000 out on Haiku 5.5


def test_wilson_interval():
    assert voice_eval.wilson(0, 0) == (0.0, 0.0)
    low, high = voice_eval.wilson(0, 8)
    assert low == pytest.approx(0.0, abs=1e-9) and 0.3 < high < 0.35
    assert voice_eval.wilson(8, 8)[1] == pytest.approx(1.0)


def test_summary_counts_fixtures_and_outcomes():
    def row(i, kinds, outcome, emptied=False):
        return {
            "id": f"c{i}",
            "raw_kinds": kinds,
            "shown_kinds": [],
            "outcome": outcome,
            "guard_emptied": emptied,
            "refused": False,
            "input_tokens": 3000,
            "output_tokens": 1000,
            "cost_usd": 0.0008,
        }

    rows = [row(1, ["handle"], "answer"), row(1, [], "answer"), row(2, [], "failed", True)]
    s = voice_eval.summarise(rows)
    assert (s["n"], s["fixtures"], s["raw_leaks"], s["fixtures_leaking"]) == (3, 2, 1, 1)
    assert s["outcomes"] == {"answer": 2, "failed": 1} and s["guard_emptied"] == 1
    assert s["kinds"] == {"handle": 1} and s["cost_usd"] == pytest.approx(0.0024)


@pytest.mark.parametrize(
    ("tags", "tools", "ok"),
    [
        (["broad"], ["top_stories"], True),
        (["broad"], ["semantic_search", "keyword_search"], False),
        (["place"], ["semantic_search"], True),
        (["place"], ["top_stories", "semantic_search"], False),
    ],
)
def test_routing(tags, tools, ok):
    assert voice_eval.routed({"tags": tags}, tools) is ok


def test_one_spend_counts_the_whole_run():
    spend = voice_eval.Spend(0.001)
    assert spend.allows(0.0009)
    spend.add([_response("")], 0.0009)  # $0.0008, for its $0.0009 reservation
    assert not spend.allows(0.0009)


def test_spend_reserves_each_estimate_until_its_calls_are_counted():
    spend = voice_eval.Spend(0.002)
    assert spend.allows(0.0009) and spend.allows(0.0009)
    assert not spend.allows(0.0009)  # two calls in flight hold $0.0018
    spend.add([], 0.0009)  # one failed before any response: its reservation goes
    assert spend.allows(0.0009)


def _memo_cases(tmp_path, monkeypatch, n: int) -> None:
    cases = [
        {"id": f"memo-{k}", "items": ["thread:1", "thread:2"], "snapshots": [], "saved": []}
        for k in range(n)
    ]
    (tmp_path / "memo.json").write_text(json.dumps(cases), encoding="utf-8")
    monkeypatch.setattr(voice_eval, "FIXTURES", tmp_path)
    monkeypatch.setattr(voice_eval, "RESULTS", tmp_path / "results")


@pytest.mark.asyncio
async def test_concurrent_cases_cannot_all_pass_the_cap(tmp_path, monkeypatch):
    _memo_cases(tmp_path, monkeypatch, voice_eval.CONCURRENCY)

    async def memo(case: dict) -> str:
        await asyncio.sleep(0)  # every case is in flight before any is counted
        voice_eval._CALLS.get().append(_response('{"possible_connections": "Floods [1]."}'))
        return "Floods hit Valencia [1]."

    monkeypatch.setattr(voice_eval, "run_memo", memo)
    spend = voice_eval.Spend(2.5 * voice_eval.EST_USD["memo"])  # room for two estimates
    summary = await voice_eval.run_surface("memo", "t", 1, spend, False)
    assert summary["n"] == 2


@pytest.mark.asyncio
async def test_an_answer_with_no_recorded_call_stops_the_run(tmp_path, monkeypatch):
    _memo_cases(tmp_path, monkeypatch, 1)

    async def memo(case: dict) -> str:  # as if a surface built a client the run can't see
        return "Floods hit Valencia [1]."

    monkeypatch.setattr(voice_eval, "run_memo", memo)
    with pytest.raises(voice_eval.UncountedCall):
        await voice_eval.run_surface("memo", "t", 1, voice_eval.Spend(1.0), False)


@pytest.mark.asyncio
async def test_a_fixed_text_needs_no_call(tmp_path, monkeypatch):
    _memo_cases(tmp_path, monkeypatch, 1)

    async def memo(case: dict) -> str:
        return board.NOT_ENOUGH_PINS

    monkeypatch.setattr(voice_eval, "run_memo", memo)
    summary = await voice_eval.run_surface("memo", "t", 1, voice_eval.Spend(1.0), False)
    assert summary["outcomes"] == {"not_enough": 1}


def test_isolate_blanks_production_state(monkeypatch):
    monkeypatch.setattr(settings, "redis_url", "rediss://production")
    monkeypatch.setattr(settings, "database_url", "postgresql://production")
    monkeypatch.setattr(settings, "llm_daily_budget_usd", 0.05)
    monkeypatch.setattr(settings, "anthropic_api_key", "test-key")
    voice_eval.isolate()
    assert settings.redis_url == "" and settings.database_url == ""
    assert settings.llm_daily_budget_usd == 100.0  # nothing pauses mid-run
