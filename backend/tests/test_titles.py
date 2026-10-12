"""Tests for story identity: titles without their outlet, and the stored story key."""

from __future__ import annotations

import hashlib

import pytest

from app.services.titles import dedup_key, story_key, story_key_sql


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
