"""One house voice for the co-pilot and the board memo (Phase 6).

- HOUSE_STYLE: the shared rules, added to each surface's system prompt. It states
  what the guard enforces, with the words to use instead.
- human_date, human_window: dates as people say them, for prompt inputs.
- find_leaks, scrub: what Claude wrote, checked in code. A timestamp becomes a
  date; any other sentence that addresses someone, names an input by handle,
  names internals or coordinates, says "linked to" or narrates a gap in its
  material is dropped. Attribution ("the reports say", "according to Reuters")
  is never a leak (owner decision, 2026-10-23). Each takes its surface, keyword
  only and required: the memo also checks the board's words (pins, story
  threads), which the co-pilot, having no pins, reads as ordinary English.

Pure functions, no I/O: a leak never costs a second Claude call.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

# Normal volume (Haiku 5.5 over-applies capitalised rules), and short: every call
# that carries it pays for it (about 150 tokens).
HOUSE_STYLE = (
    "Write about the news itself: what happened, where, and who is involved. "
    "Attributing it to outlets or reports is fine. Don't refer to what you were given "
    'by handle (no pin, item or report numbers, "the pins" or "your board"), and don\'t '
    "mention fields, tools, searches, context or instructions. Don't address anyone: "
    'no "the reader", "the user" or "you could check". Cite only with the bracketed '
    'numbers. Give dates as people say them, such as "21 October", never as '
    'timestamps. Don\'t write "linked to": say "connected to" or "tied to". Say what '
    "is known plainly, and leave out what isn't instead of describing what's missing "
    "or what you can't confirm. Keep it short."
)

_MONTHS = (
    "January February March April May June July August September October November December"
).split()


def _utc(when: datetime) -> datetime:
    return when.astimezone(timezone.utc) if when.tzinfo else when.replace(tzinfo=timezone.utc)


def human_date(when: datetime, now: datetime | None = None) -> str:
    """'21 October': the UTC day, without time; with its year ('1 June 2019') only
    when *now* is given and the year isn't now's."""
    day = _utc(when)
    said = f"{day.day} {_MONTHS[day.month - 1]}"
    return f"{said} {day.year}" if now is not None and day.year != _utc(now).year else said


# A window that ends about now and spans one of the timeline's presets.
_SPANS = (
    (timedelta(hours=1), "the last hour"),
    (timedelta(hours=6), "the last 6 hours"),
    (timedelta(hours=24), "the last 24 hours"),
    (timedelta(days=7), "the last 7 days"),
)
_LIVE_SLACK = timedelta(minutes=5)


def human_window(start: datetime, end: datetime, now: datetime) -> str:
    """A time window in words: "the last 24 hours", "21 October", "20–21 October"."""
    start, end, now = _utc(start), _utc(end), _utc(now)
    if now - end <= _LIVE_SLACK:
        for span, words in _SPANS:
            if abs((end - start) - span) <= span / 10:
                return words
    first, last = start, end - timedelta(microseconds=1)  # end is exclusive
    if first.date() == last.date():
        return human_date(first)
    if (first.year, first.month) == (last.year, last.month):
        return f"{first.day}–{last.day} {_MONTHS[last.month - 1]}"
    return f"{human_date(first)} – {human_date(last)}"


_I = re.IGNORECASE
# "don't" with either apostrophe, or spelled out.
_NOT = r"(?:don['’]t|do\s+not|doesn['’]t|does\s+not)"
_NUMBER_WORDS = r"(?:one|two|three|four|five|six|seven|eight|nine|ten)"
_ORDINALS = r"(?:first|second|third|fourth|fifth|sixth|seventh|eighth|ninth|tenth|last)"

# What a reply must never say, by kind, on either surface. Narrow on purpose:
# tests/test_voice.py has ordinary news sentences each kind must let through,
# attribution among them.
LEAK_PATTERNS: dict[str, re.Pattern[str]] = {
    # Addressing someone instead of telling the news. Plurals ("users of the app")
    # and third persons ("police said the visitor was detained") are news.
    "audience": re.compile(
        r"\b(?:the|a)\s+reader\b"
        r"|\breaders?\s+(?:could|can|may|might|should|would)\b"
        r"|\bthe\s+user\b"
        r"|\byou\s+(?:could|can|may|might|should)\s+(?:check|verify|look\s+(?:up|into|at))\b"
        # The same advice without the reader, when what's checked is the material
        # (21a baseline): "could be checked in the original articles", "should be
        # confirmed against current reporting". "Could be verified against satellite
        # images", "bags may be checked in" and "could be confirmed in the coming
        # days" are news.
        r"|\b(?:could|can|should|might|may)\s+be\s+"
        r"(?:checked|verified|confirmed)\s+(?:against|in)\s+(?:the\s+)?"
        r"(?:(?:original|current|latest|later|other|full|primary|news)\s+)?"
        r"(?:articles?|reports?|reporting|coverage|sources?|stories|headlines?|outlets?"
        r"|material|links?)\b",
        _I,
    ),
    # Inputs by number: "item 3", "Item [3] says", "report #4". A bracketed number is a
    # citation after any other word ("Reports [4] say", "denied entry [3]", "stolen
    # items [2]"), so "item [3]" and "entry [3]" are handles only where a sentence
    # starts. Pins are the memo's (MEMO_PATTERNS).
    "handle": re.compile(
        r"(?i:\b(?:items?|entr(?:y|ies)|reports?|results?|headlines?|sources?)"
        r"\s*#?\s*\d{1,3}\b)"
        r"|(?:^|[.!?]\s+)\W*(?i:(?:the\s+)?(?:items?|entr(?:y|ies)))\s*\[\s*\d"
    ),
    # Internal names: tools, fields, graph labels, prompt tags and parts, and the
    # "[Sources: …]" block history stores (an answer that writes one could steer the
    # next turn's page reads).
    "internals": re.compile(
        r"\b(?:semantic_search|keyword_search|graph_traverse|entity_lookup"
        r"|top_stories|read_article|source_url|source_name|published_at|sentiment_score"
        r"|topic_tags|country_code|globe_actions|possible_connections|open_questions"
        r"|co_mentioned|mentioned_in|located_at|about_topic|rel_type|time_range|entity_name"
        r"|off_topic|screen\s+context|system\s+prompt|knowledge\s+graph|these\s+instructions)\b"
        r"|<\s*/?\s*(?:news|pins|headlines)\s*>"
        r"|\[\s*sources\s*:"
        # A placeholder name (21a baseline: twelve "_json_placeholder" lines in one
        # answer): a leading underscore and two parts at least. "john_doe",
        # "report_final", "COVID_19" and "passwords_2024.xlsx" are news, and so are
        # "@gov_press", "#breaking_news" and italics ("_in absentia_").
        r"|(?-i:(?<![\w@#/.])_[a-z]+(?:_[a-z0-9]+)+\b)(?![@.]\w)",
        _I,
    ),
    # Coordinates copied from the inputs: "(38.96, 35.24)", "38.9637, 35.2433".
    "coordinates": re.compile(
        r"\(\s*-?\d{1,2}\.\d+\s*,\s*-?\d{1,3}\.\d+\s*\)"
        r"|-?\b\d{1,2}\.\d{3,}\s*,\s*-?\d{1,3}\.\d{3,}\b"
    ),
    # Gaps in the material, and how the reply was made: the clearest forms only, so
    # news passes ("No date was given for the funeral", "the material was seized").
    # From the 21a baseline: "the coverage I found", "the reports I have", "I can't
    # explain", and "is not stated" ending its sentence ("…, is not stated."). "The
    # reports don't say…" is attribution, left to the prompts (owner decision 2), and
    # "the motive is not stated in court documents" and "food is not given to
    # detainees" are news.
    "gap": re.compile(
        r"\b(?:the|my)\s+(?:material|context)\s+"
        rf"(?:I\s+(?:was|have\s+been)\s+given|provided|given|{_NOT}\s+\w+)"
        r"|\bI\s+(?:can['’]t|cannot|couldn['’]t|could\s+not|am\s+unable\s+to"
        r"|was\s+unable\s+to)\s+(?:confirm|verify|determine|establish|access|tell|say"
        r"|explain|describe)\b"
        r"|\bI\s+(?:don['’]t|do\s+not)\s+have\s+(?:access|the\s+full|more|enough)\b"
        r"|\bI\s+(?:searched|retrieved|looked\s+up|was\s+(?:given|provided))\b"
        r"|\b(?:coverage|reports?|articles?|stories|headlines?|sources?|material)\s+I\s+"
        r"(?:found|have|had|was\s+given|retrieved|saw|looked\s+at)\b"
        r"|\b(?:is|are)\s+not\s+stated(?=\s*(?:[.!?;]|$))"
        r"|\bno\s+(?:exact\s+)?(?:date|time|timestamp)\s+is\s+"
        r"(?:given|provided|listed|stated|available)\b",
        _I,
    ),
}
# What the 21c evals' memos had their inputs do as a set, after a determiner or a
# sentence-start count: "the items share", "Three pins describe", "these items do not
# give", "the items may be covered together". Items and pins in the news do other
# things: "were stolen", "include a rifle", "are banned", "were removed from his
# ankle", "may be sold" (#147 review).
_SET_VERBS = (
    r"(?:(?:all|both|also)\s+)?(?:share[sd]?|cover(?:s|ed)?|agree[sd]?|describe[sd]?"
    r"|concern(?:s|ed)?|conflict(?:s|ed)?|sit|sat|appear(?:s|ed)?|give|gave|name[sd]?"
    r"|frame[sd]?|focus(?:es|ed)?|(?:are|were)\s+(?:all\s+)?(?:separate|unrelated"
    r"|developing)|do\s+not|don['’]t|did\s+not|didn['’]t|may\s+(?:also\s+|therefore\s+)?"
    r"(?:share|be\s+(?:covered|connected|tied|related|part)))\b"
)
# Material that was released, seized or found is news ("the material released by
# police"), not what a memo was given.
_NOT_RELEASED = r"(?!\s+(?:released|published|seized|leaked|obtained|recovered|found)\b)"
# After a counted set ("the three items", "both items", "two of the items"), what
# reads as news about objects: a citation, a comma, "of", a participle, were/was,
# "are stolen" (#147 re-review). Anything else is the memo counting its inputs: "two
# of the items involve", "the three items are consistent", "across the three items".
_COUNTED_NEWS = (
    r"(?!\s*\[)(?!,)(?!\s+(?:of|\w+ed|were|was|stolen|taken|sold|worth|valued|went"
    r"|remain)\b)(?!\s+(?:are|is)\s+\w+ed\b)"
)
# A pin's kind, as the held-out runs' memos named one pin: "the Tel Aviv place item",
# "the person profile". Lowercase only, so "a People profile" (the magazine) passes.
_PIN_KINDS = r"(?:place|person|people|organi[sz]ation|org|thread|story|link|article)"
# The board's words, read in a memo only (surface="memo"): pins, and the
# memo's story threads, country pairs and story times. The co-pilot has no pins, so
# to it these are ordinary English ("the two pins in his ankle", "neither pin was
# recovered", "a country pin on his lapel", "the story thread of the season").
MEMO_PATTERNS: dict[str, re.Pattern[str]] = {
    # A pin by number or word ("Pin 2", "Pin [2]", "pin two", "the second pin", "the
    # pins", "your board"), and from the 21a baseline by its kind ("the Tel Aviv place
    # pin", "the two dated pins", "neither pin"), and an item called by its number
    # after in, from or under ("the article in [1]"). Verbs and idioms pass ("pins
    # hopes on", "a peg that pins the lira", "pulled the pin on"), and so do "the PIN
    # codes" (the one-pin forms are case-sensitive) and "was sworn in [2]" (a pin's
    # kind comes before "in [N]").
    "handle": re.compile(
        r"(?i:\bpins?\s*(?:#\s*|\[\s*)?\d{1,3}\b"
        rf"|\bpins?\s+{_NUMBER_WORDS}\b"
        rf"|\b{_ORDINALS}\s+pins?\b"
        r"|\byour\s+(?:board|pins?|items?|notes?)\b"
        r"|\b(?:articles?|threads?|stor(?:y|ies)|places?|persons?|organi[sz]ations?|links?"
        r"|pairs?|entit(?:y|ies)|pins?|items?)\s+(?:in|from|under)\s+\[\s*\d)"
        r"|\b(?:[Tt]he|[Tt]hese|[Tt]hose|[Bb]oth|[Aa]ll|[Ee]ach|[Mm]y)\s+pins\b"
        r"|(?<!pulled )(?<!pull )(?<!pulls )(?<!pulling )"
        r"\b(?:[Tt]he|[Tt]his|[Tt]hat|[Ee]ach)\s+pin\b"
        r"|\b(?i:place|person|story|thread|article|country|link|entity|organi[sz]ation"
        r"|saved|expired|lost|dated)\s+pins?\b"
        rf"|\b(?:[Tt]he|[Tt]hese|[Tt]hose|[Bb]oth|[Aa]ll)\s+(?:other\s+)?(?:{_NUMBER_WORDS}"
        r"|other|remaining)\s+pins\b"
        r"|\b(?:[Nn]either|[Ee]ither|[Nn]o|[Ee]very|[Aa]nother)\s+pin\b"
        # From the 21c eval: the pins as a set, counted where a sentence starts and
        # doing what a set does ("Three pins share a setting"); "two pins in his wrist"
        # and "Two pins were removed from his ankle" pass.
        r"|(?:^|[.!?]\s+)\W*(?:Two|Three|Four|Five|Six|Seven|Eight|Nine|Ten|Several|Many"
        rf"|Some)\s+pins\s+{_SET_VERBS}"
        # The board as where the news sits or what it shows (21c eval): "the newest
        # coverage on the board", "these items on the board", "the board does not
        # show". Governance passes (#147 review): "remain on the board", "the only
        # woman on the board", "confirmed by the board", "the board does not expect to
        # meet", "on the board's agenda", "two goals on the board".
        r"|\b(?i:coverage|reporting|stor(?:y|ies)|items?|pins?|headlines?|news)\s+on\s+"
        r"(?:the|this|your)\s+board\b"
        r"|\b[Tt]he\s+board\s+(?:does\s+not|doesn['’]t)\s+(?:show|say|give|list|state"
        r"|mention|name|include)\b"
        # The items as a set: uncounted with _SET_VERBS ("the items share", "these
        # items describe"), counted unless _COUNTED_NEWS follows ("the three items are
        # consistent", "two of the items involve", "both items may appear"), and "the
        # item does not confirm". Items in the news pass (#147 review): "the items were
        # stolen", "the items include a rifle", "these items are banned", "two items
        # were missing", "the two items stolen", "two of the items were recovered",
        # "both items went missing", "these items place the suspect at the scene".
        # Entries are counted the same way (held-out runs: "the three entries place the
        # church"); "three entries in the competition" and "both entries were
        # disqualified" pass.
        r"|\b(?:[Tt]he|[Tt]hese|[Tt]hose|[Aa]ll|[Bb]oth|[Ss]everal|[Tt]wo|[Tt]hree|[Ff]our"
        r"|[Ff]ive|[Ss]ix)\s+(?:(?:two|three|four|five|six|other|remaining)\s+)?items\s+"
        rf"{_SET_VERBS}"
        r"|\b(?:(?:[Tt]he|[Tt]hese|[Tt]hose|[Aa]ll)\s+(?:two|three|four|five|six)|[Bb]oth)"
        rf"\s+(?:items|entries)\b{_COUNTED_NEWS}"
        r"|\b(?:[Oo]ne|[Tt]wo|[Tt]hree|[Bb]oth|[Aa]ll|[Ee]ach)\s+of\s+(?:the|these)\s+"
        rf"(?:(?:two|three|four|five|six)\s+)?(?:items|entries)\b{_COUNTED_NEWS}"
        r"|\b[Tt]he\s+item\s+(?:does\s+not|doesn['’]t)\s+(?:confirm|say|show|state|give"
        r"|mention|name|establish)\b"
        # One pin called an item (21c-2 eval), after a name ("the Netanyahu item", "the
        # Tel Aviv item [3]"), an ordinal ("the third item") or "only" ("the only
        # dated item", "the only item linking countries"), or before its number ("the
        # item [2]", "this item [2]"). News passes: "the item was stolen", "the most
        # valuable item",
        # "the UK's Eurovision item" (a possessive), "the only item on the agenda",
        # "the first item recovered".
        r"|(?:\b[Tt]he\s+(?:[A-Z][\w-]*\s+){1,2}"
        rf"|\b[Tt]he\s+{_ORDINALS}\s+"
        r"|\b(?:[Tt]he\s+)?[Oo]nly\s+(?:[\w-]+\s+)?)item\b"
        r"(?!\s+(?:of|on|in|to|into|for|\w+ed|sold|stolen|taken|worth)\b)"
        r"|\b(?:[Tt]he|[Tt]his|[Tt]hat|[Ee]ach)\s+item\s*\[\s*\d"
        # One pin called an entry: after a name and before its number ("the Netanyahu
        # entry [3]", "the Tel Aviv entry [3]"), or after a pin's kind ("the Russia
        # place entry", "the place and organisation entries"). "The UK's Eurovision
        # entry [2]" (a possessive), "Sweden's NATO entry [1]", "the entry of aid
        # convoys", "the US entry ban" and "people entry" pass.
        r"|\b[Tt]he\s+(?:[A-Z][\w-]*\s+){1,2}entr(?:y|ies)\s*\[\s*\d"
        r"|\b(?i:place|person|organi[sz]ation)\s+entr(?:y|ies)\b"
        r"|\b(?i:the|this|that|these|those|each|every|only|one|other|all|both)\s+"
        r"(?:only\s+)?(?i:dated|listed|given)\s+items?\b"
        # One pin by its kind, as an item or a profile (held-out runs): "the Tel Aviv
        # place item", "the storm story and the person profile". "Place items in clear
        # bags" (a verb, plural), "a Hollywood profile", "a People profile" and "the
        # story's profile" pass.
        rf"|\b{_PIN_KINDS}\s+(?:item|profiles?)\b"
    ),
    # What it was given, as material or items, said to settle nothing: a narrated gap
    # (21c evals). "It is unclear from the material", "unclear from these items", and
    # after a negation "not settled from this material", "neither … is confirmed in
    # the material", "not stated in the material", "no place is named in the
    # material"; "nothing in the material", "nothing in them conflicts", "the
    # material gives no…", "the material does not show", "do not conflict on the
    # facts given". News passes (#147 review): "the material shows the minister
    # knew", "officials named in the material have denied", "it is clear from these
    # items that", "the material released by police", "unclear from the statement",
    # "settled on the facts given", "disagree on the facts given in court", "nothing
    # in the report". From the held-out runs: "uncertain from the material", and a
    # clause that ends on what the material names, gives or shows ("causes that the
    # material names."); with an object after it, it's reported news ("said that the
    # material shows the minister knew"), and so is "uncertain from the start".
    "gap": re.compile(
        r"\b(?:unclear|unknown|uncertain)\s+(?:from|in|by)\s+(?:the|this|these)\s+"
        rf"(?:gathered\s+|given\s+)?(?:material|items|pins)\b{_NOT_RELEASED}"
        r"|\b(?:not|no|nothing|neither|none|never)\b[^.!?]*?\b(?:clear|known|settled"
        r"|established|confirmed)\s+(?:from|in|by)\s+(?:the|this|these)\s+"
        rf"(?:gathered\s+|given\s+)?(?:material|items|pins)\b{_NOT_RELEASED}"
        r"|\b(?:not|no|nothing|neither|none|never)\b[^.!?]*?\b(?:stated|named|given"
        r"|mentioned|shown|listed)\s+in\s+(?:the|this)\s+(?:gathered\s+|given\s+)?"
        rf"material\b{_NOT_RELEASED}"
        r"|\b(?:conflict|disagree|contradict|differ)\w*\s+on\s+the\s+facts\s+given\b"
        r"(?!\s+(?:in|by|at|to|during)\b)"
        r"|\bnothing\s+in\s+(?:the|this|these)\s+(?:gathered\s+|given\s+)?"
        r"(?:material|items|pins)\b"
        r"|\bnothing\s+in\s+them\s+(?:conflicts|contradicts|disagrees)\b"
        r"|\b(?:the|this)\s+(?:gathered\s+|given\s+)?material\s+(?:(?:does|did)\s+not"
        r"|doesn['’]t|didn['’]t)\s+(?:show|say|give|state|name|mention|include|offer"
        r"|provide|explain|confirm|establish|tie|connect)\b"
        r"|\b(?:the|this)\s+(?:gathered\s+|given\s+)?material\s+(?:gives|shows|says|offers"
        r"|provides|names|lists|contains|includes)\s+(?:no|nothing|little)\b"
        r"|\bthat\s+the\s+material\s+(?:names|gives|shows)"
        r"(?=\s*(?:[.,;:!?\[]|$)|\s+(?:and|or|but)\b)",
        _I,
    ),
    # The board's data model (21a baseline): "story threads", "a country pair", "the
    # newest-story time window", "latest-story timestamp"; from the 21c eval, "a
    # country pairing" and "a standalone news location". "A news thread", "the latest
    # story from the BBC" and "a standalone location for the embassy" pass.
    "internals": re.compile(
        r"\bstory\s+threads?\b|\bcountry\s+pair(?:ing)?s?\b"
        r"|\bstandalone\s+news\s+locations?\b"
        r"|\b(?:newest|latest)[\s-]+story\s+(?:time(?:\s+window)?|timestamp|dated?)\b",
        _I,
    ),
}
# Who wrote a reply: the co-pilot reads LEAK_PATTERNS, the memo those and MEMO_PATTERNS.
SURFACES = ("copilot", "memo")
# Checked on the reply as written, quoted text included: "linked to" is never in Orbis
# copy, not even inside a quoted headline (Phase 3 onward), and "only 'this week'"
# carries its own quotes.
AS_WRITTEN: dict[str, re.Pattern[str]] = {
    "linked_to": re.compile(r"\blinked\s+to\b", _I),
    "gap": re.compile(r"\bonly\s+[\"'“‘]this\s+week[\"'”’]", _I),
}

# An ISO date, with or without its time and zone: rewritten as a human date.
TIMESTAMP = re.compile(
    r"\b(\d{4})-(\d{2})-(\d{2})(?:[ T]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?)?(?:\s*(?:UTC|GMT|Z)\b)?"
)
# Links are left alone: a date in a URL's path isn't a timestamp in prose.
_URL = re.compile(r"\bhttps?://\S+", _I)
# Quoted speech is the speaker's words, not the reply's ("I can't confirm anything,"
# the minister said). In double quotes, or in single quotes that close after , . ! or
# ? as British outlets write speech ('I can't say,' he said); any other single quote
# may be an apostrophe.
_QUOTED = re.compile(
    r"[\"“][^\"“”]{1,300}[\"”]"
    r"|(?<![\w'’])['‘][^\n]{1,300}?[,.!?]['’](?=\s|$)"
)

# A sentence ends at . ! or ? (with any closing quote or bracket, and any citation
# markers right after it, which stay with it) before a space and a capital, a digit,
# or an opening quote or parenthesis...
_BOUNDARY = re.compile(r"([.!?][\"'”’)\]]*(?:\s*\[\d{1,3}\])*)\s+(?=[\"'“‘(]?[A-Z0-9])")
# ...unless its full stop belongs to an abbreviation: "the U.S. President".
_ABBREVIATION = re.compile(
    r"(?:\b(?:[A-Z]\.){2,}|\b(?:Mr|Mrs|Ms|Dr|St|Gen|Lt|Col|Sen|Rep|Gov|Prof|No|Jan|Feb"
    r"|Mar|Apr|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)\.)$"
)
# A Markdown list item's mark, kept apart from its sentences.
_LIST_MARK = re.compile(r"^(\s*(?:[-*+]|\d{1,2}[.)])\s+)")


@dataclass(frozen=True)
class Scrubbed:
    """A reply after scrub(): its text, and what was done to it (counts and kinds only)."""

    text: str
    dropped: int = 0  # sentences removed
    rewritten: int = 0  # timestamps said as dates
    kinds: tuple[str, ...] = ()  # leak kinds found, sorted


def find_leaks(text: str, *, surface: str) -> list[str]:
    """The kinds of leak in *text*, sorted; [] when it reads as news.

    *surface* is who wrote it, and every caller says so (no default: a memo read by
    the co-pilot's rules would pass "Pin 2 is Lagos."). "copilot" reads
    LEAK_PATTERNS, and "memo" reads MEMO_PATTERNS too, the board's words: 21b passes
    surface="copilot", 21c surface="memo". Links are never checked, and quoted
    speech (the speaker's words) only for AS_WRITTEN's kinds.
    """
    if surface not in SURFACES:
        raise ValueError(f"surface is one of {SURFACES}")
    patterns = [*LEAK_PATTERNS.items()]
    if surface == "memo":
        patterns += MEMO_PATTERNS.items()
    linkless = _URL.sub(" ", text)
    own = _QUOTED.sub(" ", linkless)
    kinds = {kind for kind, pattern in patterns if pattern.search(own)}
    kinds |= {kind for kind, pattern in AS_WRITTEN.items() if pattern.search(linkless)}
    if TIMESTAMP.search(own):
        kinds.add("timestamp")
    return sorted(kinds)


def _sentences(line: str) -> list[str]:
    """*line* split into sentences, conservatively: an unclear boundary isn't one."""
    parts, start = [], 0
    for match in _BOUNDARY.finditer(line):
        end = match.end(1)
        if _ABBREVIATION.search(line[start:end]):
            continue
        parts.append(line[start:end])
        start = match.end()
    parts.append(line[start:])
    return [part for part in parts if part.strip()]


def _rewrite_timestamps(text: str, now: datetime) -> tuple[str, int]:
    links = [match.span() for match in _URL.finditer(text)]
    count = 0

    def said(match: re.Match[str]) -> str:
        nonlocal count
        if any(start <= match.start() < end for start, end in links):
            return match[0]
        try:
            day = datetime(int(match[1]), int(match[2]), int(match[3]), tzinfo=timezone.utc)
        except ValueError:
            return match[0]  # not a date: find_leaks drops its sentence
        count += 1
        return human_date(day, now)

    return TIMESTAMP.sub(said, text), count


def scrub(text: str, now: datetime | None = None, *, surface: str) -> Scrubbed:
    """*text* with timestamps said as dates and every leaking sentence dropped.

    Works line by line, so paragraphs and Markdown list items keep their shape; a
    list item whose every sentence leaks goes, mark and all. [N] markers stay with
    the sentence they follow. *now* decides when a date keeps its year, and
    *surface* which patterns apply, with no default (find_leaks): 21b passes
    surface="copilot", 21c surface="memo".
    """
    if surface not in SURFACES:
        raise ValueError(f"surface is one of {SURFACES}")
    text, rewritten = _rewrite_timestamps(text, now or datetime.now(timezone.utc))
    kinds: set[str] = {"timestamp"} if rewritten else set()
    dropped = 0
    lines: list[str] = []
    for line in text.split("\n"):
        mark = _LIST_MARK.match(line)
        prefix = mark.group(1) if mark else ""
        kept = []
        for sentence in _sentences(line[len(prefix) :]):
            found = find_leaks(sentence, surface=surface)
            if found:
                kinds.update(found)
                dropped += 1
            else:
                kept.append(sentence.strip())
        if kept:
            lines.append(prefix + " ".join(kept))
        elif not line.strip():
            lines.append("")  # blank lines keep paragraphs apart
    shown = re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()
    return Scrubbed(shown, dropped, rewritten, tuple(sorted(kinds)))
