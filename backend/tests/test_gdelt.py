"""Tests for GDELT raw GKG file parsing and title scraping."""

import io
import threading
import time
import zipfile
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services import gdelt
from app.services.gdelt import (
    _HTML_COMMENT_RE,
    _clean_title,
    _gdelt_https_url,
    _is_usable_title,
    _parse_counts,
    _parse_entities,
    _parse_gkg_date,
    _parse_names,
    _parse_page_title,
    _parse_themes,
    _parse_tone_detail,
    fetch_raw_gkg,
    scrape_titles,
)

# A production title scraped with a React SSR comment left in it.
ZEROHEDGE_RAW = (
    "American Express Hit With $350 Million Fine For Anti-Money Laundering Lapses"
    "<!-- --> | ZeroHedge"
)
ZEROHEDGE_CLEAN = (
    "American Express Hit With $350 Million Fine For Anti-Money Laundering Lapses | ZeroHedge"
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_gkg_zip(records: list[str]) -> bytes:
    """Create a ZIP file containing a fake GKG TSV with the given records."""
    tsv_content = "\n".join(records)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("test.gkg.csv", tsv_content)
    return buf.getvalue()


def _make_gkg_record(
    url: str = "https://example.com/article-1",
    domain: str = "example.com",
    date: str = "20260305120000",
    locations: str = "4#Tehran, Tehran, Iran#IR#IR00#35.6944#51.4215#-3039671",
    persons: str = "",
    organizations: str = "",
    themes: str = "TAX_FNCACT;GENERAL_GOVERNMENT",
    tone: str = "-2.5,1.0,3.5,0.5",
    image: str = "https://example.com/image.jpg",
    v1_counts: str = "",
    counts: str = "",
    names: str = "",
    extras: str = "",
) -> str:
    """Build a tab-delimited GKG record with city-level location.

    GKG 2.1 fields (tab-delimited, 0-indexed):
     0: GKGRECORDID, 1: DATE, 2: SOURCECOLLECTION, 3: DOMAIN,
     4: URL, 5: V1COUNTS, 6: V2.1COUNTS, 7: V1THEMES,
     8: V2ENHANCEDTHEMES, 9: V1LOCATIONS, 10: V2ENHANCEDLOCATIONS,
     11: V1PERSONS, 12: V2ENHANCEDPERSONS, 13: V1ORGANIZATIONS,
     14: V2ENHANCEDORGANIZATIONS, 15: V1.5TONE, 16: DATES, 17: GCAM,
     18: SHARINGIMAGE, 19: RELATEDIMAGES, 20: SOCIALIMAGEEMBEDS,
     21: SOCIALVIDEOEMBEDS, 22: QUOTATIONS, 23: ALLNAMES, 24: AMOUNTS,
     25: TRANSLATIONINFO, 26: EXTRASXML
    """
    fields = [""] * 27
    fields[0] = "20260305120000-T1"
    fields[1] = date
    fields[2] = "1"
    fields[3] = domain
    fields[4] = url
    fields[5] = v1_counts
    fields[6] = counts
    fields[7] = themes
    fields[9] = locations
    fields[11] = persons
    fields[13] = organizations
    fields[15] = tone
    fields[18] = image
    fields[23] = names
    fields[26] = extras
    return "\t".join(fields)


# ---------------------------------------------------------------------------
# _parse_gkg_date
# ---------------------------------------------------------------------------


class TestParseGkgDate:
    def test_parses_standard_format(self):
        dt = _parse_gkg_date("20260305120000")
        assert dt.year == 2026
        assert dt.month == 3
        assert dt.day == 5
        assert dt.hour == 12

    def test_returns_now_on_invalid(self):
        dt = _parse_gkg_date("garbage")
        assert dt.year >= 2026


# ---------------------------------------------------------------------------
# _is_usable_title
# ---------------------------------------------------------------------------


class TestIsUsableTitle:
    def test_accepts_normal_headline(self):
        assert _is_usable_title("Breaking News: Major Event Unfolds") is True

    def test_rejects_cloudflare_page(self):
        assert _is_usable_title("Attention Required! | Cloudflare") is False

    def test_rejects_just_a_moment(self):
        assert _is_usable_title("Just a moment...") is False

    def test_rejects_access_denied(self):
        assert _is_usable_title("Access Denied") is False

    def test_rejects_http_error(self):
        assert _is_usable_title("403 Forbidden") is False
        assert _is_usable_title("503 Service Unavailable") is False

    def test_rejects_hex_hash_title(self):
        assert _is_usable_title("Article C3E3E6A6 08B2 4876 98E1 17Ce31993Dab") is False

    def test_rejects_article_hex_pattern(self):
        assert _is_usable_title("Article 4E1F21C3 394C 492D A1E7 9545273Fa9D3") is False


# ---------------------------------------------------------------------------
# Field helpers
# ---------------------------------------------------------------------------


class TestCleanTitle:
    def test_strips_html_comments(self):
        assert _clean_title(ZEROHEDGE_RAW) == ZEROHEDGE_CLEAN

    def test_strips_tags_then_unescapes(self):
        assert _clean_title("<b>Floods</b> hit &amp; <i>close</i> roads") == (
            "Floods hit & close roads"
        )

    def test_keeps_angle_brackets_that_are_not_tags(self):
        assert _clean_title("Inflation < 2% for first time in years") == (
            "Inflation < 2% for first time in years"
        )

    def test_collapses_whitespace(self):
        assert _clean_title("  Storm\n   hits\tthe coast  ") == "Storm hits the coast"

    def test_caps_at_300_characters(self):
        assert len(_clean_title("x" * 400)) == 300
        # Cut at 300, without the trailing space the cut lands on.
        assert _clean_title("word " * 100) == ("word " * 60).strip()

    @pytest.mark.parametrize("raw", ["", "Home", "<!-- -->Hi!", "  a   b  ", "<p></p>"])
    def test_rejects_five_characters_or_fewer(self, raw):
        assert _clean_title(raw) == ""

    def test_rejects_unusable_titles(self):
        assert _clean_title("Just a moment...") == ""
        assert _clean_title("<title>Attention Required! | Cloudflare</title>") == ""

    def test_strips_tag_like_text(self):
        # Documented trade-off: anything shaped like a tag goes, even if it was text.
        assert _clean_title("Rates x<y>z today") == "Rates xz today"

    def test_strips_nul_bytes(self):
        # Postgres TEXT rejects NUL; one bad title would roll back the whole upsert.
        assert _clean_title("Storm\x00 hits the\x00 coast") == "Storm hits the coast"

    def test_unterminated_comment_is_dropped_to_the_end(self):
        assert _clean_title("Headline before a comment <!-- never closed") == (
            "Headline before a comment"
        )

    def test_reads_at_most_2000_characters(self):
        # Output is capped at 300, so nothing past the first 2,000 raw characters matters.
        assert _clean_title("Headline words" + " " * 2000 + "tail") == "Headline words"

    @pytest.mark.parametrize(
        "raw",
        ["<!--" * 50_000, "<a" * 100_000, "<!--" + "x" * 200_000, "<PAGE_TITLE>" * 17_000],
        ids=["open-comments", "open-tags", "one-open-comment", "page-title-tags"],
    )
    def test_pathological_markup_is_fast(self, raw):
        t0 = time.perf_counter()
        _clean_title(raw)
        assert time.perf_counter() - t0 < 0.5


class TestCommentRegex:
    def test_unterminated_comments_are_linear(self):
        """Lazy `.*?-->` alone retries from every `<!--` to the end: 16.8 s on 80 KB."""
        t0 = time.perf_counter()
        assert _HTML_COMMENT_RE.sub("", "<!--" * 50_000) == ""
        assert time.perf_counter() - t0 < 0.5

    def test_closed_comments_still_end_at_the_first_close(self):
        assert _HTML_COMMENT_RE.sub("", "a<!-- x -->b<!-- y -->c") == "abc"


class TestParsePageTitle:
    def test_reads_page_title_from_extras(self):
        extras = (
            "<PAGE_LINKS>https://a.example/x</PAGE_LINKS>"
            "<PAGE_TITLE>Ceasefire talks resume in Cairo</PAGE_TITLE>"
            "<PAGE_AUTHORS>Jane Doe</PAGE_AUTHORS>"
        )
        assert _parse_page_title(extras) == "Ceasefire talks resume in Cairo"

    def test_cleans_like_scraped_titles(self):
        assert _parse_page_title(f"<PAGE_TITLE>{ZEROHEDGE_RAW}</PAGE_TITLE>") == ZEROHEDGE_CLEAN

    def test_unescapes_entities(self):
        extras = "<PAGE_TITLE>Trade &amp; tariffs: what&#39;s next</PAGE_TITLE>"
        assert _parse_page_title(extras) == "Trade & tariffs: what's next"

    def test_strips_an_escaped_comment_too(self):
        escaped = ZEROHEDGE_RAW.replace("<!-- -->", "&lt;!-- --&gt;")
        assert _parse_page_title(f"<PAGE_TITLE>{escaped}</PAGE_TITLE>") == ZEROHEDGE_CLEAN

    def test_unterminated_tag_gives_empty(self):
        assert _parse_page_title("<PAGE_TITLE>Ceasefire talks resume in Cairo") == ""

    @pytest.mark.parametrize(
        "extras",
        [
            "<PAGE_TITLE>" * 17_000,  # 200 KB of openers, no closer: 11.5 s with the old regex
            "<PAGE_TITLE>" + "<!--" * 50_000 + "</PAGE_TITLE>",
        ],
        ids=["open-tags", "comment-flood"],
    )
    def test_pathological_extras_are_fast(self, extras):
        t0 = time.perf_counter()
        assert _parse_page_title(extras) == ""
        assert time.perf_counter() - t0 < 0.5

    @pytest.mark.parametrize(
        "extras",
        [
            "",
            "<PAGE_AUTHORS>Jane Doe</PAGE_AUTHORS>",
            "<PAGE_TITLE>News</PAGE_TITLE>",
            "<PAGE_TITLE>Just a moment...</PAGE_TITLE>",
        ],
    )
    def test_empty_when_missing_short_or_unusable(self, extras):
        assert _parse_page_title(extras) == ""


class TestParseThemes:
    def test_distinct_non_empty_in_first_seen_order(self):
        raw = "KILL;TERROR;;KILL;ARMEDCONFLICT; ;TERROR;TAX_FNCACT;"
        assert _parse_themes(raw) == ["KILL", "TERROR", "ARMEDCONFLICT", "TAX_FNCACT"]

    def test_capped_at_64(self):
        themes = _parse_themes(";".join(f"T{i}" for i in range(100)))
        assert themes == [f"T{i}" for i in range(64)]

    def test_empty(self):
        assert _parse_themes("") == []


class TestParseEntities:
    def test_title_cased_distinct_in_order(self):
        assert _parse_entities("barack obama;angela merkel;barack obama;") == [
            "Barack Obama",
            "Angela Merkel",
        ]

    def test_capped_at_30(self):
        raw = ";".join(f"person {i}" for i in range(50))
        assert _parse_entities(raw) == [f"Person {i}" for i in range(30)]

    def test_empty(self):
        assert _parse_entities("") == []


class TestParseNames:
    def test_counts_repeats_most_frequent_first(self):
        raw = "Gaza Strip,73;Yellow Line,101;Gaza Strip,231;Yellow Line,489;Rafah,20;Gaza Strip,600"
        assert _parse_names(raw) == ["Gaza Strip", "Yellow Line", "Rafah"]

    def test_ties_broken_by_earliest_offset(self):
        # Both appear twice; Bravo is listed first but Alpha occurs earlier in the text.
        assert _parse_names("Bravo,50;Alpha,10;Bravo,60;Alpha,70;Charlie,5") == [
            "Alpha",
            "Bravo",
            "Charlie",
        ]

    def test_names_may_contain_commas(self):
        assert _parse_names("Washington, D.C.,40;Washington, D.C.,90") == ["Washington, D.C."]

    def test_skips_malformed_blocks(self):
        assert _parse_names("NoOffset;Bad,offset;,12;Good Name,3") == ["Good Name"]

    def test_keeps_top_15(self):
        raw = ";".join(f"Name {i},{i}" for i in range(20))
        assert _parse_names(raw) == [f"Name {i}" for i in range(15)]

    def test_empty(self):
        assert _parse_names("") == []


BEITBRIDGE = "Beitbridge, South Africa (General), South Africa#SF#SF00#-22.2254#29.9862#-1209923"


class TestParseCounts:
    def test_keeps_typed_counts_and_skips_theme_names(self):
        raw = f"ARREST#30##4#{BEITBRIDGE}#1884;SOC_GENERALCRIME#30##4#{BEITBRIDGE}#1884"
        assert _parse_counts(raw, "") == [
            {
                "type": "ARREST",
                "n": 30,
                "object": "",
                "country": "ZA",
                "place": "Beitbridge, South Africa (General), South Africa",
            }
        ]

    def test_all_kept_types(self):
        types = ["AFFECT", "ARREST", "KIDNAP", "KILL", "PROTEST", "SEIZE", "WOUND"]
        raw = ";".join(f"{t}#2#people#0######" for t in types)
        assert [c["type"] for c in _parse_counts(raw, "")] == types

    def test_unknown_or_missing_location(self):
        raw = "KILL#12#soldiers#1#Somewhere#ZZ#ZZ#1#2#3#40;WOUND#3#civilians#0#####"
        assert _parse_counts(raw, "") == [
            {"type": "KILL", "n": 12, "object": "soldiers", "country": "", "place": "Somewhere"},
            {"type": "WOUND", "n": 3, "object": "civilians", "country": "", "place": ""},
        ]

    def test_skips_non_integer_counts(self):
        raw = "KILL#dozens#people#0#####;KILL##people#0#####;KILL#4.5#people#0#####;KILL#7#people"
        assert _parse_counts(raw, "") == [
            {"type": "KILL", "n": 7, "object": "people", "country": "", "place": ""}
        ]

    def test_drops_duplicates_that_differ_only_by_offset(self):
        raw = f"KILL#5##4#{BEITBRIDGE}#100;KILL#5##4#{BEITBRIDGE}#900;KILL#6##4#{BEITBRIDGE}#950"
        assert [c["n"] for c in _parse_counts(raw, "")] == [5, 6]

    def test_capped_at_10(self):
        raw = ";".join(f"PROTEST#{n}#people#0#####" for n in range(1, 20))
        assert [c["n"] for c in _parse_counts(raw, "")] == list(range(1, 11))

    def test_falls_back_to_v1_counts(self):
        v1 = f"KIDNAP#2#journalists#4#{BEITBRIDGE}"
        assert _parse_counts("", v1) == [
            {
                "type": "KIDNAP",
                "n": 2,
                "object": "journalists",
                "country": "ZA",
                "place": "Beitbridge, South Africa (General), South Africa",
            }
        ]

    def test_prefers_v21_counts(self):
        assert _parse_counts("KILL#1#a#0#####9", "KILL#2#b#0#####") == [
            {"type": "KILL", "n": 1, "object": "a", "country": "", "place": ""}
        ]

    def test_empty(self):
        assert _parse_counts("", "") == []


class TestParseToneDetail:
    def test_reads_positions_0_1_2_3_and_6(self):
        assert _parse_tone_detail("-3.2,1.5,4.7,6.2,22.1,0.5,512") == {
            "tone": -3.2,
            "pos": 1.5,
            "neg": 4.7,
            "polarity": 6.2,
            "words": 512,
        }

    @pytest.mark.parametrize(
        "raw",
        [
            "",
            "-2.5,1.0,3.5,0.5",  # too few values
            "-3.2,x,4.7,6.2,22.1,0.5,512",
            "-3.2,1.5,4.7,6.2,22.1,0.5,many",
            "-3.2,1.5,4.7,6.2,22.1,0.5,51.5",
            "nan,1.5,4.7,6.2,22.1,0.5,512",  # JSONB rejects NaN
            "-3.2,inf,4.7,6.2,22.1,0.5,512",
        ],
    )
    def test_none_when_malformed(self, raw):
        assert _parse_tone_detail(raw) is None


# ---------------------------------------------------------------------------
# fetch_raw_gkg
# ---------------------------------------------------------------------------


class TestFetchRawGkg:
    @pytest.mark.asyncio
    async def test_parses_city_level_articles(self):
        record = _make_gkg_record()
        zip_bytes = _make_gkg_zip([record])

        index_text = "100 abc123 http://data.gdeltproject.org/gdeltv2/test.gkg.csv.zip"

        async def mock_download(url):
            if "lastupdate" in url:
                return index_text.encode()
            return zip_bytes

        with patch(
            "app.services.gdelt._download_bytes",
            new_callable=AsyncMock,
            side_effect=mock_download,
        ):
            articles = await fetch_raw_gkg()
            assert len(articles) == 1
            assert articles[0]["url"] == "https://example.com/article-1"
            assert articles[0]["lat"] == pytest.approx(35.6944)
            assert articles[0]["lng"] == pytest.approx(51.4215)
            assert articles[0]["location_name"] == "Tehran, Tehran, Iran"
            assert articles[0]["domain"] == "example.com"
            assert articles[0]["image_url"] == "https://example.com/image.jpg"

    @pytest.mark.asyncio
    async def test_skips_country_level_locations(self):
        # Type 1 = COUNTRY (should be skipped)
        record = _make_gkg_record(locations="1#United States#US##37.09#-95.71#US")
        zip_bytes = _make_gkg_zip([record])
        index_text = "100 abc http://data.gdeltproject.org/gdeltv2/test.gkg.csv.zip"

        async def mock_download(url):
            if "lastupdate" in url:
                return index_text.encode()
            return zip_bytes

        with patch(
            "app.services.gdelt._download_bytes",
            new_callable=AsyncMock,
            side_effect=mock_download,
        ):
            articles = await fetch_raw_gkg()
            assert len(articles) == 0

    @pytest.mark.asyncio
    async def test_deduplicates_by_url(self):
        record1 = _make_gkg_record(url="https://example.com/same")
        record2 = _make_gkg_record(url="https://example.com/same")
        zip_bytes = _make_gkg_zip([record1, record2])
        index_text = "100 abc http://data.gdeltproject.org/gdeltv2/test.gkg.csv.zip"

        async def mock_download(url):
            if "lastupdate" in url:
                return index_text.encode()
            return zip_bytes

        with patch(
            "app.services.gdelt._download_bytes",
            new_callable=AsyncMock,
            side_effect=mock_download,
        ):
            articles = await fetch_raw_gkg()
            assert len(articles) == 1

    @pytest.mark.asyncio
    async def test_returns_empty_on_download_failure(self):
        with patch(
            "app.services.gdelt._download_bytes",
            new_callable=AsyncMock,
            return_value=None,
        ):
            articles = await fetch_raw_gkg()
            assert articles == []

    @pytest.mark.asyncio
    async def test_parses_tone(self):
        record = _make_gkg_record(tone="-5.0,2.0,7.0,1.5")
        zip_bytes = _make_gkg_zip([record])
        index_text = "100 abc http://data.gdeltproject.org/gdeltv2/test.gkg.csv.zip"

        async def mock_download(url):
            if "lastupdate" in url:
                return index_text.encode()
            return zip_bytes

        with patch(
            "app.services.gdelt._download_bytes",
            new_callable=AsyncMock,
            side_effect=mock_download,
        ):
            articles = await fetch_raw_gkg()
            assert articles[0]["tone"] == pytest.approx(-5.0)

    @pytest.mark.asyncio
    async def test_fetch_raw_gkg_extracts_persons_and_orgs(self):
        record = _make_gkg_record(
            persons="barack obama;angela merkel",
            organizations="united nations;world bank",
        )
        zip_bytes = _make_gkg_zip([record])
        index_text = "100 abc http://data.gdeltproject.org/gdeltv2/test.gkg.csv.zip"

        async def mock_download(url):
            if "lastupdate" in url:
                return index_text.encode()
            return zip_bytes

        with patch(
            "app.services.gdelt._download_bytes",
            new_callable=AsyncMock,
            side_effect=mock_download,
        ):
            articles = await fetch_raw_gkg()
            assert len(articles) == 1
            assert articles[0]["persons"] == ["Barack Obama", "Angela Merkel"]
            assert articles[0]["organizations"] == ["United Nations", "World Bank"]

    @pytest.mark.asyncio
    async def test_fetch_raw_gkg_handles_empty_entity_fields(self):
        record = _make_gkg_record(persons="", organizations="")
        zip_bytes = _make_gkg_zip([record])
        index_text = "100 abc http://data.gdeltproject.org/gdeltv2/test.gkg.csv.zip"

        async def mock_download(url):
            if "lastupdate" in url:
                return index_text.encode()
            return zip_bytes

        with patch(
            "app.services.gdelt._download_bytes",
            new_callable=AsyncMock,
            side_effect=mock_download,
        ):
            articles = await fetch_raw_gkg()
            assert len(articles) == 1
            assert articles[0]["persons"] == []
            assert articles[0]["organizations"] == []


async def _fetch_records(records: list[str]) -> list[dict]:
    """Run fetch_raw_gkg against a fake GKG file holding *records*."""
    zip_bytes = _make_gkg_zip(records)
    index_text = "100 abc http://data.gdeltproject.org/gdeltv2/test.gkg.csv.zip"

    async def mock_download(url):
        if "lastupdate" in url:
            return index_text.encode()
        return zip_bytes

    with patch(
        "app.services.gdelt._download_bytes",
        new_callable=AsyncMock,
        side_effect=mock_download,
    ):
        return await fetch_raw_gkg()


class TestCountryCodes:
    """GKG location codes are FIPS 10-4; articles store ISO and keep the raw code."""

    @pytest.mark.asyncio
    async def test_city_location_country_is_iso_with_raw_fips_kept(self):
        record = _make_gkg_record(
            locations="4#London, London, United Kingdom#UK#UKH9#51.5#-0.12#-2643743"
        )
        articles = await _fetch_records([record])
        assert len(articles) == 1
        assert articles[0]["country_code"] == "GB"
        assert articles[0]["country_fips"] == "UK"

    @pytest.mark.asyncio
    async def test_country_mentions_are_iso_with_raw_fips_kept(self):
        record = _make_gkg_record(
            locations=(
                "1#China#CH##35#105#CH;"
                "1#Spain#SP##40#-4#SP;"
                "4#London, London, United Kingdom#UK#UKH9#51.5#-0.12#-2643743"
            )
        )
        articles = await _fetch_records([record])
        mentions = articles[0]["mentioned_locations"]
        assert [(m["name"], m["country_code"], m["country_fips"]) for m in mentions] == [
            ("China", "CN", "CH"),
            ("Spain", "ES", "SP"),
        ]

    @pytest.mark.asyncio
    async def test_unknown_fips_gives_empty_iso_but_keeps_raw_code(self):
        record = _make_gkg_record(locations="4#Somewhere#ZZ#ZZ00#10.0#20.0#123")
        articles = await _fetch_records([record])
        assert articles[0]["country_code"] == ""
        assert articles[0]["country_fips"] == "ZZ"


class TestGkgFields:
    """Fields stored on the article row: title, themes, people, names, counts, tone."""

    @pytest.mark.asyncio
    async def test_record_with_every_field(self):
        record = _make_gkg_record(
            themes="KILL;TERROR;KILL;ARMEDCONFLICT",
            persons="benjamin netanyahu",
            organizations="united nations",
            tone="-3.2,1.5,4.7,6.2,22.1,0.5,512",
            counts=f"KILL#4#people#4#{BEITBRIDGE}#1884;SOC_GENERALCRIME#4##4#{BEITBRIDGE}#1884",
            names="Gaza Strip,73;Yellow Line,101;Gaza Strip,231",
            extras=f"<PAGE_TITLE>{ZEROHEDGE_RAW}</PAGE_TITLE><PAGE_AUTHORS>X</PAGE_AUTHORS>",
        )
        [article] = await _fetch_records([record])

        assert article["page_title"] == ZEROHEDGE_CLEAN
        assert article["themes"] == ["KILL", "TERROR", "ARMEDCONFLICT"]
        assert article["persons"] == ["Benjamin Netanyahu"]
        assert article["organizations"] == ["United Nations"]
        assert article["names"] == ["Gaza Strip", "Yellow Line"]
        assert article["counts"] == [
            {
                "type": "KILL",
                "n": 4,
                "object": "people",
                "country": "ZA",
                "place": "Beitbridge, South Africa (General), South Africa",
            }
        ]
        assert article["tone"] == pytest.approx(-3.2)
        assert article["tone_detail"] == {
            "tone": -3.2,
            "pos": 1.5,
            "neg": 4.7,
            "polarity": 6.2,
            "words": 512,
        }

    @pytest.mark.asyncio
    async def test_v1_counts_used_when_v21_counts_empty(self):
        record = _make_gkg_record(v1_counts="PROTEST#200#students#0#####")
        [article] = await _fetch_records([record])
        assert article["counts"] == [
            {"type": "PROTEST", "n": 200, "object": "students", "country": "", "place": ""}
        ]

    @pytest.mark.asyncio
    async def test_missing_fields_give_empty_values(self):
        record = _make_gkg_record(themes="", tone="-2.5,1.0,3.5,0.5")
        [article] = await _fetch_records([record])
        assert article["page_title"] == ""
        assert article["themes"] == []
        assert article["names"] == []
        assert article["counts"] == []
        assert "tone_detail" not in article  # malformed: too few values
        assert article["tone"] == pytest.approx(-2.5)

    @pytest.mark.asyncio
    async def test_short_records_without_the_later_fields_still_parse(self):
        record = "\t".join(_make_gkg_record().split("\t")[:19])
        [article] = await _fetch_records([record])
        assert article["page_title"] == ""
        assert article["names"] == []

    @pytest.mark.asyncio
    async def test_nul_bytes_are_removed_from_every_field(self):
        """Postgres TEXT, TEXT[] and JSONB reject NUL; one record must not sink the upsert."""
        record = _make_gkg_record(
            url="https://example.com/a\x00b",
            domain="exam\x00ple.com",
            themes="KILL\x00;TERROR",
            persons="benjamin\x00 netanyahu",
            organizations="united\x00 nations",
            counts="KILL#4#peo\x00ple#0#####",
            names="Gaza\x00 Strip,73",
            extras="<PAGE_TITLE>Storm\x00 hits the coast</PAGE_TITLE>",
        )
        [article] = await _fetch_records([record])

        def strings(value):
            if isinstance(value, str):
                yield value
            elif isinstance(value, dict):
                for v in value.values():
                    yield from strings(v)
            elif isinstance(value, list):
                for v in value:
                    yield from strings(v)

        assert not [s for s in strings(article) if "\x00" in s]
        assert article["url"] == "https://example.com/ab"
        assert article["page_title"] == "Storm hits the coast"
        assert article["themes"] == ["KILL", "TERROR"]
        assert article["persons"] == ["Benjamin Netanyahu"]
        assert article["counts"][0]["object"] == "people"

    @pytest.mark.asyncio
    async def test_records_are_parsed_off_the_event_loop(self):
        threads = []
        real_parse = gdelt._parse_gkg

        def spy(raw):
            threads.append(threading.current_thread())
            return real_parse(raw)

        with patch("app.services.gdelt._parse_gkg", side_effect=spy):
            [article] = await _fetch_records([_make_gkg_record()])

        assert article["url"] == "https://example.com/article-1"
        assert threads and threads[0] is not threading.main_thread()

    @pytest.mark.asyncio
    async def test_persons_and_organizations_capped_at_30(self):
        record = _make_gkg_record(
            persons=";".join(f"person {i}" for i in range(40)),
            organizations=";".join(f"org {i}" for i in range(40)),
        )
        [article] = await _fetch_records([record])
        assert len(article["persons"]) == 30
        assert len(article["organizations"]) == 30


# ---------------------------------------------------------------------------
# scrape_titles
# ---------------------------------------------------------------------------


class TestScrapeTitles:
    @pytest.mark.asyncio
    async def test_scrapes_title_from_html(self):
        articles = [{"url": "https://example.com/story", "domain": "example.com"}]

        mock_resp = MagicMock()
        mock_resp.content = b"<html><head><title>Breaking News Story</title></head></html>"

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_resp
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await scrape_titles(articles)
            assert result[0]["title"] == "Breaking News Story"

    @pytest.mark.asyncio
    async def test_leaves_title_empty_on_failure(self):
        articles = [{"url": "https://example.com/big-news-story", "domain": "example.com"}]

        mock_client = AsyncMock()
        mock_client.get.side_effect = Exception("Connection refused")
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await scrape_titles(articles)
            assert not result[0].get("title")

    @pytest.mark.asyncio
    async def test_skips_cloudflare_titles(self):
        articles = [{"url": "https://example.com/real-article-here", "domain": "example.com"}]

        mock_resp = MagicMock()
        mock_resp.content = b"<html><title>Attention Required! | Cloudflare</title></html>"

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_resp
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await scrape_titles(articles)
            # Should have no title (article will be dropped by ingestion)
            assert not result[0].get("title")

    @pytest.mark.asyncio
    async def test_cleans_scraped_titles_like_gdelt_titles(self):
        articles = [{"url": "https://www.zerohedge.com/markets/amex", "domain": "zerohedge.com"}]

        mock_resp = MagicMock()
        mock_resp.content = f"<html><title>\n  {ZEROHEDGE_RAW}\n</title></html>".encode()

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_resp
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await scrape_titles(articles)
        assert result[0]["title"] == ZEROHEDGE_CLEAN

    @pytest.mark.asyncio
    async def test_strips_nul_from_scraped_titles(self):
        articles = [{"url": "https://example.com/storm", "domain": "example.com"}]

        mock_resp = MagicMock()
        mock_resp.content = b"<html><title>Storm\x00 hits the coast</title></html>"

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_resp
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await scrape_titles(articles)
        assert result[0]["title"] == "Storm hits the coast"


# ---------------------------------------------------------------------------
# _gdelt_https_url
# ---------------------------------------------------------------------------


class TestGdeltHttpsUrl:
    def test_upgrades_http_to_https(self):
        assert (
            _gdelt_https_url("http://data.gdeltproject.org/gdeltv2/x.gkg.csv.zip")
            == "https://data.gdeltproject.org/gdeltv2/x.gkg.csv.zip"
        )

    def test_keeps_https(self):
        url = "https://data.gdeltproject.org/gdeltv2/x.gkg.csv.zip"
        assert _gdelt_https_url(url) == url

    @pytest.mark.parametrize(
        "url",
        [
            "http://169.254.169.254/metadata/identity",
            "http://data.gdeltproject.org.evil.example/x.zip",
            "http://user@evil.example/x.zip",
            "file:///etc/passwd",
        ],
    )
    def test_rejects_other_hosts_and_schemes(self, url):
        assert _gdelt_https_url(url) is None

    @pytest.mark.asyncio
    async def test_fetch_raw_gkg_downloads_over_https(self):
        """lastupdate.txt lists http:// URLs; the file must be fetched via https."""
        index = b"100 abc http://data.gdeltproject.org/gdeltv2/test.gkg.csv.zip"
        mock = AsyncMock(side_effect=[index, None])
        with patch("app.services.gdelt._download_bytes", mock):
            await fetch_raw_gkg()
        assert mock.await_args_list[1].args[0] == (
            "https://data.gdeltproject.org/gdeltv2/test.gkg.csv.zip"
        )

    @pytest.mark.asyncio
    async def test_fetch_raw_gkg_refuses_foreign_host(self):
        index = b"100 abc http://169.254.169.254/latest.gkg.csv.zip"
        mock = AsyncMock(side_effect=[index])
        with patch("app.services.gdelt._download_bytes", mock):
            assert await fetch_raw_gkg() == []
        assert mock.await_count == 1
