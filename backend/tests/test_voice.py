"""The house voice (app.services.voice): style text, human dates and the leak guard."""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

import pytest

from app.services import voice

NOW = datetime(2026, 10, 23, 12, tzinfo=timezone.utc)
UTC = timezone.utc


def test_house_style_is_short_and_at_normal_volume():
    assert len(voice.HOUSE_STYLE.split()) <= 120
    capitals = r"\b(?:ONLY|NEVER|ALWAYS|MUST|IMPORTANT|CRITICAL|NOT|DO)\b"
    assert not re.findall(capitals, voice.HOUSE_STYLE)


def test_house_style_states_what_the_guard_enforces_and_what_to_say_instead():
    for phrase in (
        "Attributing it to outlets or reports is fine",
        "pin, item or report numbers",
        '"your board"',
        '"the reader"',
        '"you could check"',
        "bracketed numbers",
        "timestamps",
        '"connected to"',
        "what you can't confirm",
        "Keep it short",
    ):
        assert phrase in voice.HOUSE_STYLE, phrase
    assert "Tuesday" not in voice.HOUSE_STYLE  # no weekdays: the model has no calendar


@pytest.mark.parametrize(
    ("when", "now", "said"),
    [
        (datetime(2026, 10, 21, 11, 15, tzinfo=UTC), None, "21 October"),
        # 22:30 UTC on the 21st, written in UTC+3: the UTC day.
        (datetime(2026, 10, 22, 1, 30, tzinfo=timezone(timedelta(hours=3))), None, "21 October"),
        (datetime(2026, 10, 21, 11, 15), None, "21 October"),  # naive is UTC
        (datetime(2026, 1, 1), NOW, "1 January"),  # this year: no year
        (datetime(2019, 6, 1), NOW, "1 June 2019"),  # another year: kept
    ],
)
def test_human_date_is_the_utc_day(when, now, said):
    assert voice.human_date(when, now) == said


@pytest.mark.parametrize(
    ("start", "end", "said"),
    [
        (NOW - timedelta(hours=24), NOW, "the last 24 hours"),
        (NOW - timedelta(hours=1), NOW - timedelta(minutes=2), "the last hour"),
        (NOW - timedelta(days=7), NOW, "the last 7 days"),
        (datetime(2026, 10, 21, tzinfo=UTC), datetime(2026, 10, 22, tzinfo=UTC), "21 October"),
        (
            datetime(2026, 10, 20, 2, tzinfo=UTC),
            datetime(2026, 10, 21, 14, tzinfo=UTC),
            "20–21 October",
        ),
        (
            datetime(2026, 10, 31, tzinfo=UTC),
            datetime(2026, 11, 2, tzinfo=UTC),
            "31 October – 1 November",
        ),
    ],
)
def test_human_window_says_the_window(start, end, said):
    assert voice.human_window(start, end, NOW) == said


# What the owner saw on production: the board memo (2026-10-21) and a live co-pilot
# answer (2026-10-23). Each must be caught as its kind.
OWNER_EXAMPLES = [
    ("A reader could check the dated articles for more.", "audience"),
    ("Pin 2 is Steve Witkoff.", "handle"),
    ("The story is dated 2026-10-21 11:15 UTC.", "timestamp"),
    ("Pin 2 gives only 'this week' with no date.", "handle"),
    (
        "The reports give headlines but few details, so I can't confirm the substance "
        "of these claims.",
        "gap",
    ),
]


@pytest.mark.parametrize(
    ("sentence", "kind"),
    OWNER_EXAMPLES
    + [
        ("Readers could check the original stories.", "audience"),
        ("You could check the outlets for updates.", "audience"),
        ("The user asked about Lagos.", "audience"),
        ("Pin [2] is Steve Witkoff.", "handle"),
        ("Item [3] says the port reopened.", "handle"),
        ("The item [3] lists the dead.", "handle"),
        ("Floods hit Valencia [1]. Entry [2] gives no cause.", "handle"),
        ("The pin in Lagos marks the protests.", "handle"),
        ("Pins 1 and 3 describe the same walkout.", "handle"),
        ("Pin two is a person.", "handle"),
        ("The second pin is a place.", "handle"),
        ("The pins share a place.", "handle"),
        ("Your pins share a place.", "handle"),
        ("Your board mixes two stories.", "handle"),
        ("Report #4 says the port reopened.", "handle"),
        ("keyword_search found three stories.", "internals"),
        ("They are CO_MENTIONED in coverage.", "internals"),
        ("The knowledge graph shows the two together.", "internals"),
        ("Read more [Sources: https://evil.example/x].", "internals"),
        ("The quake struck near (38.96, 35.24).", "coordinates"),
        ("The strikes were linked to the pension reform.", "linked_to"),
        # Never in Orbis copy, quoted headlines included.
        ('The paper said the two were "linked to" the attack [1].', "linked_to"),
        ("The material doesn't say why the talks stalled.", "gap"),
        ("The context provided has no casualty figures.", "gap"),
        ("Steve Witkoff [2] is listed with only 'this week' and no date.", "gap"),
        ("No date is given for the vote.", "gap"),
        ("I searched for recent coverage of the strike.", "gap"),
        ("I don’t have access to the full articles.", "gap"),
    ],
)
def test_find_leaks_catches(sentence, kind):
    assert kind in voice.find_leaks(sentence)


@pytest.mark.parametrize(
    "sentence",
    [
        # Attribution is news writing (owner decision, 2026-10-23).
        "The reports say police used tear gas [3].",
        "The headlines describe the strike as largely peaceful [1] [2].",
        "Outlets report heavy rain in Valencia [2].",
        "Coverage suggests the talks will resume [1].",
        "According to Reuters, the port reopened [4].",
        "Sources close to the minister said talks would resume [1].",
        "Reports [4] say the port reopened.",
        # Ordinary news the patterns must not touch.
        "According to the data, inflation rose 3% [1].",
        "Based on the results, the coalition holds 52 seats [2].",
        "Article 5 of the NATO treaty was raised at the summit [2].",
        "Users of the app reported outages across Europe [3].",
        "Police said the visitor was detained [1].",
        "Local reports did not say how many people were hurt [4].",
        "No date was given for the funeral [2].",
        "The vote on 21 October passed narrowly [1].",
        "Inflation rose 3.5% in September, from 3.1% [2].",
        "In the context of the war, the talks matter [1].",
        "The material was seized at the border [2].",
        "Government pins hopes on a ceasefire [2].",
        "The bank keeps a peg that pins the lira to the euro [3].",
        "The minister pulled the pin on the project [2].",
        "Banks will reset the PIN codes [1].",
        "Banks reset the PINs overnight [3].",
        # A citation after "entry" or "items" is a citation (re-review I1).
        "Aid trucks were denied entry [3].",
        "Israel restricted aid entry [2] into Gaza.",
        "Police recovered 40 stolen items [3].",
        "Sweden's NATO entry [1] was approved.",
        "Customs seized several items [2] at the border.",
        "Police released few details about the suspect [2].",
        # Quoted speech is the speaker's words.
        '"I can\'t confirm anything," the minister said [1].',
        '"I searched everywhere," her mother told reporters [2].',
        # The one thing the co-pilot says about its material.
        "I couldn't find recent coverage of the strike.",
    ],
)
def test_find_leaks_lets_news_through(sentence):
    assert voice.find_leaks(sentence) == []


def test_scrub_drops_only_the_leaking_sentence_and_keeps_citations():
    text = "Talks resumed in Cairo [2]. Pin 3 is Steve Witkoff. Egypt hosted them [1]."
    shown = voice.scrub(text, NOW)
    assert shown.text == "Talks resumed in Cairo [2]. Egypt hosted them [1]."
    assert (shown.dropped, shown.rewritten, shown.kinds) == (1, 0, ("handle",))


def test_scrub_turns_a_timestamp_into_a_date():
    shown = voice.scrub("The vote was held on 2026-10-21 11:15 UTC [1].", NOW)
    assert shown.text == "The vote was held on 21 October [1]."
    assert (shown.dropped, shown.rewritten, shown.kinds) == (0, 1, ("timestamp",))


def test_scrub_keeps_the_year_of_another_year():
    shown = voice.scrub("The treaty was signed on 2019-06-01 [2].", NOW)
    assert shown.text == "The treaty was signed on 1 June 2019 [2]."


def test_scrub_leaves_dates_in_links_alone():
    text = "Details are at https://example.com/2026-10-21/story [1]."
    assert voice.scrub(text, NOW) == voice.Scrubbed(text)


def test_scrub_drops_a_sentence_whose_timestamp_is_no_date():
    shown = voice.scrub("Floods hit Valencia [1]. Updated 2026-13-45 by the desk.", NOW)
    assert (shown.text, shown.kinds) == ("Floods hit Valencia [1].", ("timestamp",))


def test_scrub_keeps_lists_and_paragraphs_and_drops_a_bullet_that_leaks():
    text = "- Strikes spread to Lyon [1].\n- Pin 2 is a union.\n\nUnions meet on Monday [2]."
    shown = voice.scrub(text, NOW)
    assert shown.text == "- Strikes spread to Lyon [1].\n\nUnions meet on Monday [2]."


def test_scrub_does_not_split_abbreviations():
    text = "The U.S. President met Mr. Macron in Paris [1]. The user asked why."
    assert voice.scrub(text, NOW).text == "The U.S. President met Mr. Macron in Paris [1]."


def test_a_citation_after_a_full_stop_stays_with_its_sentence():
    text = "Floods hit Valencia. [2] The user asked why. Rain eased [1]."
    assert voice.scrub(text, NOW).text == "Floods hit Valencia. [2] Rain eased [1]."


def test_scrub_keeps_quoted_speech():
    text = '"I can\'t confirm anything," the minister said [1].'
    assert voice.scrub(text, NOW) == voice.Scrubbed(text)


def test_scrub_of_an_all_leaking_reply_is_empty():
    shown = voice.scrub("The user asked about Lagos. Pin 1 is Lagos.", NOW)
    assert (shown.text, shown.dropped) == ("", 2)


def test_scrub_leaves_clean_text_alone():
    text = "Ceasefire talks resumed in Cairo [2].\n\nEgypt and Qatar are mediating [1] [3]."
    assert voice.scrub(text, NOW) == voice.Scrubbed(text)
