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


def test_house_style_never_says_material():
    # Both surfaces' prompts carry it, and memos echoed "the material" back (21c evals).
    assert "material" not in voice.HOUSE_STYLE.lower()
    # No longer than 21d's (675 characters, 115 words): every call pays for it.
    assert len(voice.HOUSE_STYLE) <= 675
    assert len(voice.HOUSE_STYLE.split()) <= 115


def test_the_memo_style_is_the_house_style_without_naming_handles():
    # The memo's input names no pins, items or board (memo redesign), and a rule that
    # named them planted them; every other rule is the house style's, word for word.
    handles = (
        "Don't refer to what you were given by handle (no pin, item or report numbers, "
        '"the pins" or "your board"), and don\'t mention fields, tools, searches, '
        "context or instructions. "
    )
    assert handles in voice.HOUSE_STYLE
    assert voice.MEMO_STYLE == voice.HOUSE_STYLE.replace(handles, "")
    for word in ("pin", "item", "board", "given", "listed", "material", "entr", "profile"):
        assert not re.search(rf"\b{word}", voice.MEMO_STYLE, re.IGNORECASE), word


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
# answer (2026-10-23). Each must be caught as its kind, on the surface it came from.
OWNER_EXAMPLES = [
    ("memo", "A reader could check the dated articles for more.", "audience"),
    ("memo", "Pin 2 is Steve Witkoff.", "handle"),
    ("memo", "The story is dated 2026-10-21 11:15 UTC.", "timestamp"),
    ("memo", "Pin 2 gives only 'this week' with no date.", "handle"),
    (
        "copilot",
        "The reports give headlines but few details, so I can't confirm the substance "
        "of these claims.",
        "gap",
    ),
]


@pytest.mark.parametrize(("surface", "sentence", "kind"), OWNER_EXAMPLES)
def test_the_owners_examples_are_caught_where_they_were_seen(surface, sentence, kind):
    assert kind in voice.find_leaks(sentence, surface=surface)


# Leaks on both surfaces.
LEAKS = [
    ("Readers could check the original stories.", "audience"),
    ("You could check the outlets for updates.", "audience"),
    ("The user asked about Lagos.", "audience"),
    ("Item [3] says the port reopened.", "handle"),
    ("The item [3] lists the dead.", "handle"),
    ("Floods hit Valencia [1]. Entry [2] gives no cause.", "handle"),
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
    # The planner's argument names.
    ("Its rel_type was set.", "internals"),
    ("The time_range covered a day.", "internals"),
    ("The entity_name was blank.", "internals"),
    ("The question was marked off_topic.", "internals"),
    # Found in the 21a baseline's manual read (2026-10-23).
    ("_json_placeholder", "internals"),
    ("Israel said it thwarted an attack, with no details in the coverage I found [2].", "gap"),
    ("The reports I have don't include a response from him.", "gap"),
    ("I couldn't find the deal's details, so I can't explain its terms.", "gap"),
    ("What the allegations are, and who made them, is not stated.", "gap"),
    ("The cause of death is not stated.", "gap"),
    ("The latest update should be confirmed against current reporting [3].", "audience"),
    ("Its details could be checked in the original articles.", "audience"),
    # A single-quoted phrase doesn't hide the sentence after it.
    ("The fans' chant 'we are the champions.' rang out. I can't confirm the score.", "gap"),
    # The prompt's words echoed (polish eval): the kind of question, and "the lead
    # story" as a label.
    (
        "Broad question about what matters now, so here are the three stories with the "
        "widest coverage.",
        "internals",
    ),
    ("Broad question, so here are the three stories with the widest coverage.", "internals"),
    (
        "This is a broad question about what matters now, so here are the three stories "
        "with the widest coverage.",
        "internals",
    ),
    ("That is a general question, so here is an overview [1].", "internals"),
    ("As a follow-up question, so the earlier reports still apply [2].", "internals"),
    ("The lead story is covered widely across national and regional UK outlets.", "internals"),
    (
        "Storms hit Cornwall [2]. The lead story is Putin agreeing to resume Ukraine talks [1].",
        "internals",
    ),
]


@pytest.mark.parametrize("surface", voice.SURFACES)
@pytest.mark.parametrize(("sentence", "kind"), LEAKS)
def test_find_leaks_catches(surface, sentence, kind):
    assert kind in voice.find_leaks(sentence, surface=surface)


# The board's words: pins, and the memo's story threads, country pairs and story
# times. Only a memo has them; the co-pilot has no pins (21a re-review).
BOARD_LEAKS = [
    ("Pin [2] is Steve Witkoff.", "handle"),
    ("The pin in Lagos marks the protests.", "handle"),
    ("Pins 1 and 3 describe the same walkout.", "handle"),
    ("Pin two is a person.", "handle"),
    ("The second pin is a place.", "handle"),
    ("The pins share a place.", "handle"),
    ("Your pins share a place.", "handle"),
    ("Your board mixes two stories.", "handle"),
    # Found in the 21a baseline's manual read (2026-10-23).
    ("The Tel Aviv place pin carries the same newest-story time window.", "handle"),
    ("The Congo country pin is covered together with Canada.", "handle"),
    ("The two dated pins share a date.", "handle"),
    ("The three pins agree on the subject of the election.", "handle"),
    ("The other two pins cover different subjects.", "handle"),
    ("It is unclear, since no pin states the subject of that coverage.", "handle"),
    ("Neither pin names the countries.", "handle"),
    ("It is unclear whether the article in [1] matches the thread in [2].", "handle"),
    ("The board has two story threads in the same window.", "internals"),
    ("The third is only a country pair.", "internals"),
    ("Both carry the same latest-story timestamp.", "internals"),
    ("They share a newest story time of 21 October.", "internals"),
]


@pytest.mark.parametrize(("sentence", "kind"), BOARD_LEAKS)
def test_board_words_are_leaks_in_a_memo_only(sentence, kind):
    assert kind in voice.find_leaks(sentence, surface="memo")
    assert kind not in voice.find_leaks(sentence, surface="copilot")


# News on both surfaces: each kind's near misses, and attribution among them.
NEWS = [
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
    # Quoted speech is the speaker's words, in double quotes or single.
    '"I can\'t confirm anything," the minister said [1].',
    '"I searched everywhere," her mother told reporters [2].',
    "'I can't describe the pain,' the victim's mother told the BBC [2].",
    "'The reports I have seen are alarming,' the minister said [3].",
    # The one thing the co-pilot says about its material.
    "I couldn't find recent coverage of the strike.",
    # Beside the patterns the 21a baseline added (and its re-review).
    "He wore a lapel pin at the summit [1].",
    "Surgeons inserted two pins in his wrist [3].",
    "Floods hit Valencia in October [1].",
    "The pair [2] were arrested in Madrid.",
    "Musk posted a thread [3] criticising the ruling.",
    "A thread of optimism ran through the speech [1].",
    "He posted a news thread on X defending the ruling [1].",
    "The board voted to replace the chief executive [1].",
    "The protest dominated the news cycle [2].",
    "The latest story from the BBC says rain will ease [1].",
    "In its latest update, the ministry raised the toll [2].",
    "The post by @gov_press was deleted [1].",
    "Health officials tracked the COVID_19 variant [1].",
    "The agency's NASA_JPL team confirmed it [2].",
    "A spreadsheet named passwords_2024.xlsx was leaked [1].",
    "The leaked file name report_final was traced to an aide [1].",
    "Hackers used user names like john_doe to log in [2].",
    # Markdown italics, not a placeholder name.
    "He was tried _in absentia_ in Paris [1].",
    "The group is the _de facto_ government in the north [2].",
    "Food is not given to detainees, the report says [2].",
    "The motive is not stated in court documents [1].",
    "Terms are not stated publicly, the company said [2].",
    "The amount is not stated in the filing [3].",
    "The death toll could be confirmed in the coming days [1].",
    "Police said the claim could not be independently verified [2].",
    "The claims could be verified against satellite images, analysts said [1].",
    "Results can be checked against official tallies at each polling station [2].",
    "Bags may be checked in up to 24 hours before the flight [2].",
    "The DNA can be confirmed against samples held by police [1].",
    # A bracketed number after in, from or under is a citation, unless a pin's
    # kind comes before it ("the article in [1]", in a memo).
    "As reported in [3], the talks resumed.",
    "According to coverage from [2], the ceasefire held overnight.",
    "Details came from [1] and [4].",
    "In [1], the ministry said the toll had risen to 40.",
    "The new president was sworn in [2].",
    "The White House weighed in [1].",
    "The tariffs kicked in [2] on Monday.",
    "The airline went under [1].",
    "The army moved in [1] at dawn.",
    # Beside the polish eval's narration and label: questions and lead stories in the
    # news.
    "A broad question of jurisdiction remains [1].",
    "The court left a broad question open.",
    "Broad questions remain about the deal's terms [2].",
    "The senator asked a specific question about funding [1].",
    "The Times' lead story on Sunday reported the leak [2].",
    "The newspaper's lead story accused the minister [1].",
    "The lead story in Sunday's Observer named the donor [3].",
    "The strike was the lead story on the BBC website [1].",
    "The strike was the lead story everywhere that week [1].",
    "Its lead story said talks would resume [2].",
    # A coverage answer's lead stories (#152 re-review).
    "The lead story about the strike ran on page one [2].",
    "The lead story by Reuters said talks would resume [1].",
    "The lead story, in The Times, said the talks had stalled [3].",
]


@pytest.mark.parametrize("surface", voice.SURFACES)
@pytest.mark.parametrize("sentence", NEWS)
def test_find_leaks_lets_news_through(surface, sentence):
    assert voice.find_leaks(sentence, surface=surface) == []


# Ordinary English to the co-pilot, which has no pins; words about pins in a memo.
BOARD_WORDS_IN_THE_NEWS = [
    "Surgeons removed the two pins from his ankle [3].",
    "The bowler knocked down the remaining pins for a spare [1].",
    "Neither pin was recovered from the wreck [3].",
    "He wore a country pin on his lapel [2].",
    "The other pins were found in the rubble [1].",
    "She added another pin to her collection [2].",
    "The new cards need no pin code at all [1].",
    "Users can now share saved pins with friends, Google said [2].",
    "The rivalry is the story thread of the season [2].",
    "Economists modelled trade for each country pair [3].",
    # The 21c eval's misses made these memo words too (memo only, accepted).
    "The country pairing in the final drew a record audience [1].",
    # A name, then "entry" and a citation, is how memos name a pin ("the Netanyahu
    # entry [3]"); "Sweden's NATO entry [1]" and "the UK's Eurovision entry [2]" pass.
    "The NATO entry [1] was approved in March.",
    "The Indian Oscar entry [3] was withdrawn.",  # as "the Tel Aviv entry [3]" (21c-3)
    # Items as a set, as the 21c memos wrote them (#147 re-review B1, accepted).
    "One of the items is a diadem [2].",
    "Both items share a maker's mark [1].",
    "Thieves took the three items in under eight minutes [2].",
    "The items appear in a 1923 catalogue [1].",
    "The items describe a 17th-century voyage [3].",
    # Counted entries read as counted items do, and a pin's kind before "profile" as
    # memos name a pin (held-out runs, #152 review: accepted).
    "The three entries in the contest drew record votes [1].",
    "Both entries are favourites to win the contest [2].",
    "The paper ran a person profile of the suspect [1].",
]


@pytest.mark.parametrize("sentence", BOARD_WORDS_IN_THE_NEWS)
def test_board_words_are_english_to_the_copilot(sentence):
    assert voice.find_leaks(sentence, surface="copilot") == []
    assert voice.find_leaks(sentence, surface="memo") != []


# Found in the 21c eval's manual read (2026-10-23): shown memos still described what
# they were given as a set ("the material", "the board", "the three items"). Memo only:
# the co-pilot reads these as English.
MEMO_21C_LEAKS = [
    ("It is unclear from the material what Netanyahu said in Washington.", "gap"),
    ("It is not settled from this material who carried out the attack.", "gap"),
    ("It is unclear from these items what the Hebron shooting involved.", "gap"),
    ("It is unclear from the gathered material who will win the election.", "gap"),
    ("The extent of the damage is not settled in the material.", "gap"),
    ("Neither story's full timeline is confirmed in the material.", "gap"),
    ("The stories differ, and nothing in the material shows them disagreeing.", "gap"),
    ("The material gives no shared people or events beyond that timing.", "gap"),
    ("The board does not show whether his visit concerns the closure.", "handle"),
    ("The newest coverage on the board is placed in Tel Aviv on 23 October [3].", "handle"),
    ("Al-Momani [1] appears alongside these items on the board.", "handle"),
    ("The three items sit on the same country without conflicting details.", "handle"),
    ("The three items share a country [1] [2] [3].", "handle"),
    ("Several items share the 23 October date [1][2][5].", "handle"),
    ("The items cover separate subjects, and none of them conflict.", "handle"),
    ("The two items do not give conflicting places or dates.", "handle"),
    ("Three pins share a Jordanian setting.", "handle"),
    ("Storms hit the coast. Two pins name the same town [1] [2].", "handle"),
    ("The Canada and Switzerland pairing [3] is a country pairing with no detail.", "internals"),
    ("The tanker story [1] is set in Petersburg, a standalone news location [5].", "internals"),
    # From the 21c-2 eval's read: a pin called an item or an entry, and "the material".
    ("The story [1], the Netanyahu item [2] and the Tel Aviv item [3] agree.", "handle"),
    ("The Netanyahu item lists Washington as its location rather than Israel.", "handle"),
    ("They were covered together [3], the only item linking countries.", "handle"),
    ("The storm's reporting from 23 October [1] is the only dated item.", "handle"),
    ("Petersburg is the city in the Russia place entry [5].", "handle"),
    ("The place and organisation entries do not conflict with the stories.", "handle"),
    ("The Netanyahu entry [3] places him in Washington.", "handle"),
    ("The Tel Aviv entry [3] is also in Israel, so the locations fit together.", "handle"),
    ("The given items share no person or place.", "handle"),
    ("The Post's link to that story is not stated in the material.", "gap"),
    ("No shared place or people are named in the material.", "gap"),
    ("The stories concern different subjects and do not conflict on the facts given.", "gap"),
    # Forms the narrowed patterns (#147 review) still catch.
    ("The two items describe different events in different countries.", "handle"),
    ("The three items are separate and do not give conflicting accounts.", "handle"),
    ("These items all share a Washington setting [1] [2].", "handle"),
    ("The third item names Washington as its location.", "handle"),
    ("Washington is named in the item [2].", "handle"),
    ("The material shows no link between the closure and the storm.", "gap"),
    # From the 21c-3 and 21c-3b memos, which the narrowing would otherwise let through.
    ("Both items are developing stories with coverage dated 23 October.", "handle"),
    ("He is the central figure, so the three items may be covered together.", "handle"),
    ("The two items may share a source or setting.", "handle"),
    ("The three items may therefore be covered together as one story.", "handle"),
    ("The three items all frame Netanyahu as a figure whose return is in doubt.", "handle"),
    ("The three items focus on the same election question from different angles.", "handle"),
    ("The agency may be tied to the outbreak, though the item does not confirm this.", "handle"),
    ("Two of the three items are developing stories from 23 October.", "handle"),
    ("Two of the items are unrelated in subject.", "handle"),
    ("The church and the attack are both in Karak, and nothing in them conflicts.", "gap"),
    # From the 21c-4 memos (#147 re-review B1): a counted set with other verbs.
    ("Two of the items are stories about named public figures [1].", "handle"),
    ("Two of the items involve high-profile people in the United States [1] [2].", "handle"),
    ("The three items are consistent in focusing on Netanyahu's return to power.", "handle"),
    ("Both items may appear in coverage of UK news on the same days.", "handle"),
    ("Both White House and Washington locations appear across the three items.", "handle"),
    ("The three items place their stories in Washington and the White House [3].", "handle"),
    ("The three items place the events in Jordan.", "handle"),
    ("This item [2] is about the floods.", "handle"),
    ("The floods are the subject of that item [3].", "handle"),
    # From the held-out runs' memos (21c-3, 21c-5): uncertain from the material, counted
    # entries, a pin's kind before "item" or "profile", and what the material names.
    (
        "It is uncertain from the material whether Al-Momani had a role at the church or "
        "at the funeral.",
        "gap",
    ),
    (
        "The three entries place the church and the attack in Karak, while the person is "
        "listed from Amman.",
        "handle",
    ),
    ("The three entries describe an outlet, a person and a developing story.", "handle"),
    ("Both entries place the closure in Hebron [1] [3].", "handle"),
    ("Two of the entries are developing stories [1] [2].", "handle"),
    ("The storms appear across the three entries.", "handle"),
    (
        "The closure story and the Tel Aviv place item share the same city of first "
        "reporting [1] [3].",
        "handle",
    ),
    ("The person item names Netanyahu as the central figure [2].", "handle"),
    (
        "The storm story and the person profile sit in different places and do not make "
        "conflicting claims.",
        "handle",
    ),
    ("The place and organisation profiles do not conflict [2] [4].", "handle"),
    (
        "They appear in the same news coverage of that day but do not share people, "
        "places or causes that the material names.",
        "gap",
    ),
    ("Neither story adds to the dates that the material gives [1] [2].", "gap"),
    ("No other place appears beyond those that the material shows, so both fit.", "gap"),
]


@pytest.mark.parametrize(("sentence", "kind"), MEMO_21C_LEAKS)
def test_the_21c_misses_are_leaks_in_a_memo_only(sentence, kind):
    assert kind in voice.find_leaks(sentence, surface="memo")
    assert voice.find_leaks(sentence, surface="copilot") == []


# Their near misses: news on both surfaces.
MEMO_21C_NEWS = [
    "Items seized at the border were counterfeit [2].",
    "Police found several items of clothing near the river [1].",
    "Police recovered 40 stolen items [3].",
    "Customs seized several items [2] at the border.",
    "The items seized in the raid were returned to the museum [2].",
    "The two items stolen from the Louvre were recovered [1].",
    "The items listed in the indictment include a rifle [3].",
    "The board voted to replace the chief executive [1].",
    "She won a seat on the board of directors [2].",
    "He has served on the board since 2019 [1].",
    "She sits on the board at the central bank [3].",
    "A board meeting is set for Friday [1].",
    "He resigned from the board in March [1].",
    "Prices rose across the board in September [2].",
    "The board's chair resigned [2].",
    "It is unclear from the statement whether talks will resume [1].",
    "The material was seized at the border [2].",
    "Leaked material shows the minister knew of the plan [1].",
    "Nothing in the report explains the delay [2].",
    "Surgeons inserted two pins in his wrist [3].",
    "The two countries signed a pact in Lagos [1].",
    "The pair [2] were arrested in Madrid.",
    # The 21c-2 patterns' near misses.
    "The only item on the agenda was the budget [2].",
    "The item in question was a rifle [1].",
    "The most expensive item sold at the auction was a Monet [3].",
    "The first item recovered was a necklace [2].",
    "Troops blocked the entry of aid convoys [2].",
    "The treaty's entry into force was delayed [1].",
    "The US entry ban was extended to six countries [2].",
    "Each entry costs $5 at the gate [1].",
    "Police listed items stolen from the house [1].",
    "The facts given in court were disputed [2].",
    "Details were listed in the indictment [3].",
    "Aid trucks were denied entry [3].",
    "Sweden's NATO entry [1] was approved.",
    # The #147 review's probes: governance, theft and spending news a memo may carry.
    "His appointment was confirmed by the board on Monday [2].",
    "The dispute was settled by the board in March [1].",
    "The board does not expect to meet again until March [2].",
    "Musk will remain on the board [1].",
    "She is the only woman on the board [3].",
    "A vacancy on the board was filled in June [2].",
    "The proposal is now on the board's agenda [3].",
    "Arsenal put two goals on the board before half-time [2].",
    "The items were stolen from the museum in 2019 [2].",
    "The items include a rifle and two pistols [3].",
    "These items are banned under the new law [3].",
    "Police said two items were missing [1].",
    "All items were returned to the museum [2].",
    "Both items were sold at auction [2].",
    "The item was stolen in 2019 [2].",
    "One item was a rifle [2].",
    "The most valuable item was a Monet painting [2].",
    "The biggest item is defence spending [3].",
    "The UK's Eurovision entry [2] finished last.",
    "The material shows the minister knew of the plan [1].",
    "Three officials named in the material have denied wrongdoing [2].",
    # Beside the forms won back from the 21c-3 memos.
    "Two of the items were recovered by police [1].",
    "The items may be sold at auction next year [3].",
    "The item does not work without a charger, the company said [2].",
    "These items place the suspect at the scene, prosecutors said [2].",
    "The boxes had nothing in them when police arrived [1].",
    # The #147 review's probe sentences for the other 21c patterns.
    "Illegal people entry rose sharply [1].",
    "The story entry was edited [2].",
    "The judge said the case could not be settled on the facts given [1].",
    "No names were given in the material released by police [2].",
    "It is clear from these items that the shipment was illegal, officials said [2].",
    "The cause is unknown in the material released [1].",
    "His role was confirmed in the material released by the court [3].",
    "Several pins were found in the bread [1].",
    "Two pins were removed from his ankle [2].",
    "Some pins carried the party logo [3].",
    "Officials want a standalone location for the embassy [1].",
    "The kiosk is a standalone location [2].",
    # The #147 re-review: a counted set's news, and facts given in court.
    "None of the items are insured [1].",
    "The eight items stolen from the Louvre appear in Interpol's database [1].",
    "Police recovered both items [2].",
    "The two items, a crown and a necklace, were found [1].",
    "Both items went missing in 2019 [3].",
    "The three items are expected at auction in May [2].",
    "Witnesses disagree on the facts given in court [2].",
    # Beside the held-out runs' patterns: uncertainty, entries, profiles and material in
    # the news.
    "Pentagon officials were uncertain from the start [2].",
    "It is uncertain from the evidence whether the ship sank [1].",
    "Italy has three entries in the competition [1].",
    "Both entries were disqualified from the contest [2].",
    "The two entries, a song and a dance, were shortlisted [1].",
    "Two of the entries were withdrawn before the final [3].",
    "The actor sat for a Hollywood profile in Vanity Fair [2].",
    "In a People profile, the actor said she would return [1].",
    "The scandal raised the story's profile abroad [2].",
    "Shoppers must place items in clear bags at the stadium [2].",
    "The material damage was large, officials said [1].",
    "Prosecutors said that the material shows the minister knew of the plan [1].",
    "Investigators confirmed that the material names three officials [2].",
]


@pytest.mark.parametrize("sentence", MEMO_21C_NEWS)
def test_the_21c_patterns_let_news_through(sentence):
    assert voice.find_leaks(sentence, surface="memo") == []
    assert voice.find_leaks(sentence, surface="copilot") == []


def test_a_surface_is_the_copilot_or_the_memo():
    with pytest.raises(ValueError):
        voice.find_leaks("Floods hit Valencia [1].", surface="board")
    with pytest.raises(ValueError):
        voice.scrub("Floods hit Valencia [1].", NOW, surface="board")


def test_a_caller_must_say_its_surface():
    # A memo read by the co-pilot's rules would let "Pin 2 is Lagos." through.
    with pytest.raises(TypeError):
        voice.find_leaks("Pin 2 is Lagos.")  # type: ignore[call-arg]
    with pytest.raises(TypeError):
        voice.scrub("Pin 2 is Lagos.", NOW)  # type: ignore[call-arg]
    with pytest.raises(TypeError):
        voice.find_leaks("Pin 2 is Lagos.", "memo")  # type: ignore[misc]


def test_scrub_drops_only_the_leaking_sentence_and_keeps_citations():
    text = "Talks resumed in Cairo [2]. Pin 3 is Steve Witkoff. Egypt hosted them [1]."
    shown = voice.scrub(text, NOW, surface="memo")
    assert shown.text == "Talks resumed in Cairo [2]. Egypt hosted them [1]."
    assert (shown.dropped, shown.rewritten, shown.kinds) == (1, 0, ("handle",))


def test_scrub_turns_a_timestamp_into_a_date():
    shown = voice.scrub("The vote was held on 2026-10-21 11:15 UTC [1].", NOW, surface="copilot")
    assert shown.text == "The vote was held on 21 October [1]."
    assert (shown.dropped, shown.rewritten, shown.kinds) == (0, 1, ("timestamp",))


def test_scrub_keeps_the_year_of_another_year():
    shown = voice.scrub("The treaty was signed on 2019-06-01 [2].", NOW, surface="copilot")
    assert shown.text == "The treaty was signed on 1 June 2019 [2]."


def test_scrub_leaves_dates_in_links_alone():
    text = "Details are at https://example.com/2026-10-21/story [1]."
    assert voice.scrub(text, NOW, surface="copilot") == voice.Scrubbed(text)


def test_scrub_drops_a_sentence_whose_timestamp_is_no_date():
    shown = voice.scrub(
        "Floods hit Valencia [1]. Updated 2026-13-45 by the desk.", NOW, surface="copilot"
    )
    assert (shown.text, shown.kinds) == ("Floods hit Valencia [1].", ("timestamp",))


def test_scrub_keeps_lists_and_paragraphs_and_drops_a_bullet_that_leaks():
    text = "- Strikes spread to Lyon [1].\n- Pin 2 is a union.\n\nUnions meet on Monday [2]."
    shown = voice.scrub(text, NOW, surface="memo")
    assert shown.text == "- Strikes spread to Lyon [1].\n\nUnions meet on Monday [2]."


def test_scrub_does_not_split_abbreviations():
    text = "The U.S. President met Mr. Macron in Paris [1]. The user asked why."
    assert (
        voice.scrub(text, NOW, surface="copilot").text
        == "The U.S. President met Mr. Macron in Paris [1]."
    )


def test_a_citation_after_a_full_stop_stays_with_its_sentence():
    text = "Floods hit Valencia. [2] The user asked why. Rain eased [1]."
    assert (
        voice.scrub(text, NOW, surface="copilot").text == "Floods hit Valencia. [2] Rain eased [1]."
    )


def test_scrub_keeps_quoted_speech():
    text = '"I can\'t confirm anything," the minister said [1].'
    assert voice.scrub(text, NOW, surface="copilot") == voice.Scrubbed(text)


def test_scrub_of_an_all_leaking_reply_is_empty():
    shown = voice.scrub("The user asked about Lagos. Pin 1 is Lagos.", NOW, surface="memo")
    assert (shown.text, shown.dropped) == ("", 2)


def test_scrub_reads_a_reply_as_its_surface():
    text = "Surgeons removed the two pins from his ankle [3]. He walked out [1]."
    assert voice.scrub(text, NOW, surface="copilot") == voice.Scrubbed(text)
    assert voice.scrub(text, NOW, surface="memo").text == "He walked out [1]."


def test_scrub_leaves_clean_text_alone():
    text = "Ceasefire talks resumed in Cairo [2].\n\nEgypt and Qatar are mediating [1] [3]."
    assert voice.scrub(text, NOW, surface="copilot") == voice.Scrubbed(text)
