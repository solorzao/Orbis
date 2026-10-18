"""Tests for story identity: titles without their outlet, and the stored story key."""

from __future__ import annotations

import hashlib

import pytest

from app.services.titles import dedup_key, display_title, story_key, story_key_sql


class TestDedupKey:
    @pytest.mark.parametrize(
        ("title", "key"),
        [
            ("Quake hits Kathmandu - Reuters", "quake hits kathmandu"),
            ("Quake hits Kathmandu | BBC News", "quake hits kathmandu"),
            ("Quake hits Kathmandu : NPR", "quake hits kathmandu"),
            ("Quake hits Kathmandu — The Wall-Street Journal", "quake hits kathmandu"),
            ("Quake hits Kathmandu – Le Monde", "quake hits kathmandu"),
            ("Quake hits Kathmandu", "quake hits kathmandu"),
            ("  Quake hits Kathmandu  ", "quake hits kathmandu"),
            # Only the last separator goes.
            ("Nepal - Quake hits Kathmandu - AP", "nepal - quake hits kathmandu"),
            # A separator needs whitespace both sides.
            ("Prices rise: inflation hits 5%", "prices rise: inflation hits 5%"),
            ("Post-quake Kathmandu rebuilds", "post-quake kathmandu rebuilds"),
            # An outlet name is under 40 characters; anything longer is headline.
            ("Headline - " + "x" * 39, "headline"),
            ("Headline - " + "x" * 40, "headline - " + "x" * 40),
            ("Trailing separator - ", "trailing separator"),
            (" - Reuters", ""),
            ("", ""),
        ],
    )
    def test_strips_the_outlet_and_lowercases(self, title, key):
        assert dedup_key(title) == key

    @pytest.mark.parametrize(
        ("title", "key"),
        [
            # NFKC: full-width letters, no-break spaces, the ellipsis character.
            ("\uff31uake hits Kathmandu", "quake hits kathmandu"),
            ("Quake\u00a0hits\u00a0Kathmandu", "quake hits kathmandu"),
            # Curly quotes are straight ones.
            ("PM says \u201cno deal\u201d on Brexit", 'pm says "no deal" on brexit'),
            ("Kathmandu\u2019s quake toll rises", "kathmandu's quake toll rises"),
            # Every dash style is "-".
            ("Pre\u2011quake Kathmandu rebuilds", "pre-quake kathmandu rebuilds"),
            ("Nepal \u2014 Quake hits Kathmandu \u2013 AP", "nepal - quake hits kathmandu"),
            ("Temperatures fall to \u221220C", "temperatures fall to -20c"),
            # HTML entities are their characters.
            ("Q&amp;A: what we know", "q&a: what we know"),
            ("Kathmandu&#8217;s quake toll rises", "kathmandu's quake toll rises"),
            # Inner whitespace is one space.
            ("Quake   hits\tKathmandu", "quake hits kathmandu"),
            # Trailing punctuation goes.
            ("Quake hits Kathmandu.", "quake hits kathmandu"),
            ("Quake hits Kathmandu!", "quake hits kathmandu"),
            ("Quake hits Kathmandu\u2026", "quake hits kathmandu"),
            ("Will the quake hit Kathmandu?", "will the quake hit kathmandu"),
            # Common leading tags go, before the outlet's name does.
            ("WATCH: Quake hits Kathmandu", "quake hits kathmandu"),
            ("LIVE: Quake hits Kathmandu", "quake hits kathmandu"),
            ("Live updates - Quake hits Kathmandu", "quake hits kathmandu"),
            ("BREAKING: Quake hits Kathmandu - Reuters", "quake hits kathmandu"),
            ("Breaking News | Quake hits Kathmandu", "quake hits kathmandu"),
            ("UPDATE 2-Quake hits Kathmandu", "quake hits kathmandu"),
            ("VIDEO: Quake hits Kathmandu", "quake hits kathmandu"),
            # Not tags: a word that only starts like one.
            ("Live-action remake tops box office", "live-action remake tops box office"),
            ("Update on the quake: toll rises", "update on the quake: toll rises"),
            ("Watchdog fines bank", "watchdog fines bank"),
        ],
    )
    def test_folds_typography_and_tags(self, title, key):
        """Newsrooms' copies of one headline differ in typography: one story key for them."""
        assert dedup_key(title) == key

    def test_typographic_variants_are_one_story(self):
        variants = [
            "Quake hits Kathmandu",
            "WATCH: Quake hits Kathmandu.",
            "Quake hits Kathmandu \u2013 Reuters",
            "Quake  hits Kathmandu\u2026",
        ]
        assert len({story_key(v, f"https://a.example/{i}") for i, v in enumerate(variants)}) == 1


class TestDisplayTitle:
    @pytest.mark.parametrize(
        ("title", "shown"),
        [
            ("Quake hits Kathmandu - Reuters", "Quake hits Kathmandu"),
            ("WATCH: Kathmandu\u2019s quake toll rises | BBC News", "Kathmandu's quake toll rises"),
            ("Q&amp;A:  what we know", "Q&A: what we know"),
            ("Will the quake hit Kathmandu?", "Will the quake hit Kathmandu?"),
            ("Headline - " + "x" * 40, "Headline - " + "x" * 40),
        ],
    )
    def test_case_and_end_punctuation_are_kept(self, title, shown):
        """What dedup_key builds on, for headlines to show."""
        assert display_title(title) == shown
        assert dedup_key(title) == display_title(title).rstrip("?").lower()


class TestStoryKey:
    def test_golden_value(self):
        """blake2b, not hash(): the same in every process, so stored keys stay comparable."""
        assert story_key("Quake hits Kathmandu - Reuters", "https://a.example/1") == (
            3149721319931743552
        )

    def test_is_blake2b_of_the_dedup_key_as_a_signed_64_bit_int(self):
        digest = hashlib.blake2b(b"quake hits kathmandu", digest_size=8).digest()
        expected = int.from_bytes(digest, "big", signed=True)
        assert story_key("Quake hits Kathmandu", "https://a.example/1") == expected

    def test_syndicated_copies_share_a_key(self):
        reuters = story_key("Quake hits Kathmandu - Reuters", "https://reuters.example/q")
        bbc = story_key("Quake hits Kathmandu | BBC News", "https://bbc.example/q")
        assert reuters == bbc

    def test_different_stories_differ(self):
        assert story_key("Quake hits Kathmandu", "https://a.example/1") != story_key(
            "Floods hit Dhaka", "https://a.example/1"
        )

    def test_the_url_does_not_matter_when_there_is_a_title(self):
        assert story_key("Quake hits Kathmandu", "https://a.example/1") == story_key(
            "Quake hits Kathmandu", "https://b.example/2"
        )

    @pytest.mark.parametrize("title", ["", "   ", " - Reuters"])
    def test_an_untitled_article_is_its_own_story(self, title):
        """No headline left: keyed by URL, so untitled rows do not collapse into one story."""
        assert story_key(title, "https://example.com/untitled") == 7466465246215001944
        assert story_key(title, "https://example.com/a") != story_key(
            title, "https://example.com/b"
        )

    def test_fits_a_postgresql_bigint_either_sign(self):
        keys = [story_key(f"Story {i}", "") for i in range(64)]
        assert all(-(2**63) <= k < 2**63 for k in keys)
        assert min(keys) < 0 < max(keys)


class TestStoryKeySql:
    """Run on PostgreSQL in test_story_keys_db."""

    def test_the_stored_key_else_a_hash_of_the_lowercased_title(self):
        assert story_key_sql() == "COALESCE(a.story_key, hashtextextended(lower(a.title), 0))"

    def test_any_alias(self):
        assert story_key_sql("articles") == (
            "COALESCE(articles.story_key, hashtextextended(lower(articles.title), 0))"
        )

    @pytest.mark.parametrize("alias", ["", "a.b", "a; DROP TABLE articles", "1a", "a b", "a--"])
    def test_an_alias_is_a_plain_identifier(self, alias):
        """It is written into SQL as it is."""
        with pytest.raises(ValueError):
            story_key_sql(alias)
