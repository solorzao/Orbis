# GDELT Data Pipeline Fix — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Fix the broken GDELT data pipeline so `/api/news` returns real geolocated, topic-tagged articles instead of an empty array.

**Architecture:** Replace the broken GEO API geo-enrichment with a country-centroid lookup using GDELT's `sourcecountry` field. Add keyword-based topic classification from article titles. Fix the default query from `*` (rejected by GDELT) to `sourcelang:english`.

**Tech Stack:** Python 3.12, FastAPI, pytest, httpx

---

### Task 1: Create country centroids module

**Files:**
- Create: `backend/app/services/country_centroids.py`
- Test: `backend/tests/test_country_centroids.py`

**Context:** GDELT DOC 2.0 returns a `sourcecountry` field (2-letter ISO code like "US", "GB", "FR") on every article but no per-article coordinates. We need a lookup table mapping country codes to approximate centroid lat/lng so articles can be plotted on the globe.

**Step 1: Write the failing test**

Create `backend/tests/test_country_centroids.py`:

```python
"""Tests for the country centroid lookup module."""

from app.services.country_centroids import get_centroid, COUNTRY_CENTROIDS


def test_known_country_returns_coords():
    result = get_centroid("US")
    assert result is not None
    lat, lng = result
    # US centroid should be roughly in the center of the continental US
    assert 30.0 < lat < 50.0
    assert -130.0 < lng < -70.0


def test_case_insensitive_lookup():
    assert get_centroid("us") == get_centroid("US")
    assert get_centroid("Gb") == get_centroid("GB")


def test_unknown_country_returns_none():
    assert get_centroid("ZZ") is None
    assert get_centroid("") is None
    assert get_centroid("INVALID") is None


def test_centroid_dict_has_major_countries():
    # Spot-check that major news-producing countries are present
    for code in ["US", "GB", "FR", "DE", "CN", "RU", "IN", "BR", "AU", "JP"]:
        assert code in COUNTRY_CENTROIDS, f"Missing country: {code}"


def test_all_centroids_have_valid_ranges():
    for code, (lat, lng) in COUNTRY_CENTROIDS.items():
        assert -90.0 <= lat <= 90.0, f"{code} lat out of range: {lat}"
        assert -180.0 <= lng <= 180.0, f"{code} lng out of range: {lng}"
```

**Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_country_centroids.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.services.country_centroids'`

**Step 3: Write minimal implementation**

Create `backend/app/services/country_centroids.py`:

```python
"""Country code → centroid coordinate lookup.

Maps ISO 3166-1 alpha-2 country codes to approximate geographic center
coordinates (latitude, longitude). Used to place GDELT articles on the
globe when the API only provides a `sourcecountry` field.
"""

from __future__ import annotations

# (latitude, longitude) — approximate geographic center of each country.
COUNTRY_CENTROIDS: dict[str, tuple[float, float]] = {
    "AF": (33.93, 67.71),    # Afghanistan
    "AL": (41.15, 20.17),    # Albania
    "DZ": (28.03, 1.66),     # Algeria
    "AR": (-38.42, -63.62),  # Argentina
    "AM": (40.07, 45.04),    # Armenia
    "AU": (-25.27, 133.78),  # Australia
    "AT": (47.52, 14.55),    # Austria
    "AZ": (40.14, 47.58),    # Azerbaijan
    "BD": (23.68, 90.36),    # Bangladesh
    "BY": (53.71, 27.95),    # Belarus
    "BE": (50.50, 4.47),     # Belgium
    "BR": (-14.24, -51.93),  # Brazil
    "BG": (42.73, 25.49),    # Bulgaria
    "CA": (56.13, -106.35),  # Canada
    "CL": (-35.68, -71.54),  # Chile
    "CN": (35.86, 104.20),   # China
    "CO": (4.57, -74.30),    # Colombia
    "HR": (45.10, 15.20),    # Croatia
    "CU": (21.52, -77.78),   # Cuba
    "CZ": (49.82, 15.47),    # Czech Republic
    "DK": (56.26, 9.50),     # Denmark
    "EG": (26.82, 30.80),    # Egypt
    "ET": (9.15, 40.49),     # Ethiopia
    "FI": (61.92, 25.75),    # Finland
    "FR": (46.23, 2.21),     # France
    "GE": (42.32, 43.36),    # Georgia
    "DE": (51.17, 10.45),    # Germany
    "GH": (7.95, -1.02),     # Ghana
    "GR": (39.07, 21.82),    # Greece
    "HU": (47.16, 19.50),    # Hungary
    "IN": (20.59, 78.96),    # India
    "ID": (-0.79, 113.92),   # Indonesia
    "IR": (32.43, 53.69),    # Iran
    "IQ": (33.22, 43.68),    # Iraq
    "IE": (53.14, -7.69),    # Ireland
    "IL": (31.05, 34.85),    # Israel
    "IT": (41.87, 12.57),    # Italy
    "JP": (36.20, 138.25),   # Japan
    "JO": (30.59, 36.24),    # Jordan
    "KZ": (48.02, 66.92),    # Kazakhstan
    "KE": (-0.02, 37.91),    # Kenya
    "KP": (40.34, 127.51),   # North Korea
    "KR": (35.91, 127.77),   # South Korea
    "KW": (29.31, 47.48),    # Kuwait
    "LB": (33.85, 35.86),    # Lebanon
    "LY": (26.34, 17.23),    # Libya
    "MY": (4.21, 101.98),    # Malaysia
    "MX": (23.63, -102.55),  # Mexico
    "MA": (31.79, -7.09),    # Morocco
    "MM": (21.91, 95.96),    # Myanmar
    "NL": (52.13, 5.29),     # Netherlands
    "NZ": (-40.90, 174.89),  # New Zealand
    "NG": (9.08, 8.68),      # Nigeria
    "NO": (60.47, 8.47),     # Norway
    "PK": (30.38, 69.35),    # Pakistan
    "PS": (31.95, 35.23),    # Palestine
    "PE": (-9.19, -75.02),   # Peru
    "PH": (12.88, 121.77),   # Philippines
    "PL": (51.92, 19.15),    # Poland
    "PT": (39.40, -8.22),    # Portugal
    "QA": (25.35, 51.18),    # Qatar
    "RO": (45.94, 24.97),    # Romania
    "RU": (61.52, 105.32),   # Russia
    "SA": (23.89, 45.08),    # Saudi Arabia
    "RS": (44.02, 21.01),    # Serbia
    "SG": (1.35, 103.82),    # Singapore
    "SK": (48.67, 19.70),    # Slovakia
    "ZA": (-30.56, 22.94),   # South Africa
    "ES": (40.46, -3.75),    # Spain
    "SD": (12.86, 30.22),    # Sudan
    "SE": (60.13, 18.64),    # Sweden
    "CH": (46.82, 8.23),     # Switzerland
    "SY": (34.80, 38.99),    # Syria
    "TW": (23.70, 120.96),   # Taiwan
    "TH": (15.87, 100.99),   # Thailand
    "TN": (33.89, 9.54),     # Tunisia
    "TR": (38.96, 35.24),    # Turkey
    "UA": (48.38, 31.17),    # Ukraine
    "AE": (23.42, 53.85),    # UAE
    "GB": (55.38, -3.44),    # United Kingdom
    "US": (37.09, -95.71),   # United States
    "UZ": (41.38, 64.59),    # Uzbekistan
    "VE": (6.42, -66.59),    # Venezuela
    "VN": (14.06, 108.28),   # Vietnam
    "YE": (15.55, 48.52),    # Yemen
    "ZW": (-19.02, 29.15),   # Zimbabwe
}


def get_centroid(country_code: str) -> tuple[float, float] | None:
    """Return (latitude, longitude) for the given ISO country code, or None."""
    return COUNTRY_CENTROIDS.get(country_code.upper().strip()) if country_code else None
```

**Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_country_centroids.py -v`
Expected: All 5 tests PASS

**Step 5: Commit**

```bash
git add backend/app/services/country_centroids.py backend/tests/test_country_centroids.py
git commit -m "feat: add country centroid lookup module for GDELT geolocation"
```

---

### Task 2: Create topic classifier

**Files:**
- Create: `backend/app/services/topic_classifier.py`
- Test: `backend/tests/test_topic_classifier.py`

**Context:** GDELT articles have no topic tags. We classify them from the article title using keyword matching. Each article gets zero or more topic tags. The topic list must match what the frontend will eventually display as filter options.

**Step 1: Write the failing test**

Create `backend/tests/test_topic_classifier.py`:

```python
"""Tests for keyword-based topic classification."""

from app.services.topic_classifier import classify_topic, TOPIC_KEYWORDS


def test_conflict_keywords():
    assert "conflict" in classify_topic("Russia launches missile strike on Ukraine")
    assert "conflict" in classify_topic("Troops deployed to border region")


def test_politics_keywords():
    assert "politics" in classify_topic("President signs new legislation into law")
    assert "politics" in classify_topic("Election results spark debate in parliament")


def test_economy_keywords():
    assert "economy" in classify_topic("Stock market rallies on inflation data")
    assert "economy" in classify_topic("Central bank raises interest rates")


def test_technology_keywords():
    assert "technology" in classify_topic("AI startup raises $100M in funding round")
    assert "technology" in classify_topic("New cyber security threat detected")


def test_health_keywords():
    assert "health" in classify_topic("WHO warns of new virus outbreak")
    assert "health" in classify_topic("Hospital workers go on strike over conditions")


def test_environment_keywords():
    assert "environment" in classify_topic("Climate summit reaches carbon deal")
    assert "environment" in classify_topic("Wildfire destroys thousands of acres")


def test_sports_keywords():
    assert "sports" in classify_topic("NBA finals draw record viewership")
    assert "sports" in classify_topic("FIFA announces World Cup schedule")


def test_no_match_returns_general():
    result = classify_topic("Local community celebrates annual festival")
    assert result == ["general"]


def test_empty_title_returns_general():
    assert classify_topic("") == ["general"]


def test_multiple_topics_possible():
    # An article can match multiple topics
    result = classify_topic("President announces new military strike campaign")
    assert "politics" in result
    assert "conflict" in result


def test_case_insensitive():
    assert classify_topic("WAR breaks out") == classify_topic("war breaks out")


def test_topic_keywords_dict_is_populated():
    assert len(TOPIC_KEYWORDS) >= 7
    for topic, keywords in TOPIC_KEYWORDS.items():
        assert len(keywords) >= 5, f"Topic '{topic}' has too few keywords"
```

**Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_topic_classifier.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.services.topic_classifier'`

**Step 3: Write minimal implementation**

Create `backend/app/services/topic_classifier.py`:

```python
"""Keyword-based topic classifier for news articles.

Scans an article title for topic-related keywords and returns
matching topic tags. Falls back to ["general"] if nothing matches.
"""

from __future__ import annotations

TOPIC_KEYWORDS: dict[str, list[str]] = {
    "conflict": [
        "war", "attack", "military", "troops", "bomb", "missile",
        "fighting", "armed", "strike", "soldier", "killed", "casualties",
        "conflict", "battle", "invasion", "combat", "airstrike",
    ],
    "politics": [
        "president", "election", "minister", "parliament", "government",
        "vote", "political", "campaign", "congress", "senate",
        "legislation", "policy", "diplomat", "sanction", "treaty",
    ],
    "economy": [
        "economy", "market", "stock", "trade", "inflation", "gdp",
        "recession", "bank", "financial", "investment", "economic",
        "tax", "tariff", "currency", "interest rate",
    ],
    "technology": [
        "ai", "tech", "startup", "software", "cyber", "data",
        "digital", "robot", "algorithm", "silicon", "innovation",
        "computing", "internet", "app", "semiconductor",
    ],
    "health": [
        "health", "covid", "virus", "vaccine", "hospital", "medical",
        "disease", "pandemic", "treatment", "drug", "patient", "doctor",
        "outbreak", "surgery", "diagnosis",
    ],
    "environment": [
        "climate", "environment", "carbon", "emission", "pollution",
        "renewable", "energy", "wildfire", "flood", "drought",
        "hurricane", "earthquake", "weather", "storm", "deforestation",
    ],
    "sports": [
        "game", "championship", "league", "coach", "player", "match",
        "tournament", "score", "win", "nba", "fifa", "olympic",
        "football", "soccer", "tennis",
    ],
}


def classify_topic(title: str) -> list[str]:
    """Return a list of topic tags for the given article title.

    Matches are case-insensitive. Returns ``["general"]`` if no
    keywords match.
    """
    if not title:
        return ["general"]

    title_lower = title.lower()
    matched: list[str] = []

    for topic, keywords in TOPIC_KEYWORDS.items():
        for kw in keywords:
            if kw in title_lower:
                matched.append(topic)
                break  # one keyword is enough to tag this topic

    return matched if matched else ["general"]
```

**Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_topic_classifier.py -v`
Expected: All 12 tests PASS

**Step 5: Commit**

```bash
git add backend/app/services/topic_classifier.py backend/tests/test_topic_classifier.py
git commit -m "feat: add keyword-based topic classifier for news articles"
```

---

### Task 3: Fix `_parse_doc_response` — assign coordinates and topics

**Files:**
- Modify: `backend/app/services/gdelt.py` (the `_parse_doc_response` function, lines 128-177)
- Test: `backend/tests/test_gdelt.py` (create)

**Context:** Currently `_parse_doc_response` creates articles with `latitude=0.0, longitude=0.0` and empty `topic_tags`. After this task, it will use the `sourcecountry` field from GDELT to look up centroids, and classify topics from the title.

**Step 1: Write the failing test**

Create `backend/tests/test_gdelt.py`:

```python
"""Tests for GDELT response parsing with centroid and topic enrichment."""

from datetime import datetime, timezone

from app.services.gdelt import _parse_doc_response


def _make_raw_article(**overrides):
    """Helper to build a raw GDELT article dict."""
    base = {
        "title": "Test article headline",
        "url": "https://example.com/article-1",
        "domain": "example.com",
        "language": "English",
        "seendate": "20260228T120000Z",
        "tone": "-1.5,2.0",
        "sourcecountry": "US",
    }
    base.update(overrides)
    return base


class TestParseDocResponse:
    def test_parses_basic_article(self):
        data = {"articles": [_make_raw_article()]}
        articles = _parse_doc_response(data)
        assert len(articles) == 1
        assert articles[0].title == "Test article headline"
        assert articles[0].source_name == "example.com"

    def test_assigns_centroid_from_sourcecountry(self):
        data = {"articles": [_make_raw_article(sourcecountry="US")]}
        articles = _parse_doc_response(data)
        assert len(articles) == 1
        # US centroid should be approximately (37.09, -95.71)
        assert 30.0 < articles[0].latitude < 50.0
        assert -130.0 < articles[0].longitude < -70.0

    def test_assigns_country_code(self):
        data = {"articles": [_make_raw_article(sourcecountry="GB")]}
        articles = _parse_doc_response(data)
        assert articles[0].country_code == "GB"

    def test_unknown_country_gets_zero_coords(self):
        data = {"articles": [_make_raw_article(sourcecountry="ZZ")]}
        articles = _parse_doc_response(data)
        assert articles[0].latitude == 0.0
        assert articles[0].longitude == 0.0

    def test_classifies_topics_from_title(self):
        data = {"articles": [_make_raw_article(
            title="President signs military spending bill"
        )]}
        articles = _parse_doc_response(data)
        assert "politics" in articles[0].topic_tags
        assert "conflict" in articles[0].topic_tags

    def test_general_topic_when_no_keywords(self):
        data = {"articles": [_make_raw_article(
            title="Local festival draws crowds"
        )]}
        articles = _parse_doc_response(data)
        assert articles[0].topic_tags == ["general"]

    def test_skips_articles_without_title(self):
        data = {"articles": [_make_raw_article(title="")]}
        articles = _parse_doc_response(data)
        assert len(articles) == 0

    def test_handles_none_input(self):
        assert _parse_doc_response(None) == []

    def test_handles_empty_articles_list(self):
        assert _parse_doc_response({"articles": []}) == []

    def test_parses_tone_string(self):
        data = {"articles": [_make_raw_article(tone="-3.5,1.2,4.0")]}
        articles = _parse_doc_response(data)
        assert articles[0].sentiment_score == -3.5

    def test_handles_multiple_articles_different_countries(self):
        data = {"articles": [
            _make_raw_article(title="News from France", sourcecountry="FR", url="https://a.com/1"),
            _make_raw_article(title="News from Japan", sourcecountry="JP", url="https://a.com/2"),
        ]}
        articles = _parse_doc_response(data)
        assert len(articles) == 2
        # France centroid approx (46.23, 2.21)
        assert 40.0 < articles[0].latitude < 50.0
        # Japan centroid approx (36.20, 138.25)
        assert 30.0 < articles[1].latitude < 40.0
```

**Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_gdelt.py -v`
Expected: `test_assigns_centroid_from_sourcecountry` FAILS (latitude is 0.0), `test_classifies_topics_from_title` FAILS (topic_tags is empty)

**Step 3: Modify `_parse_doc_response` in `backend/app/services/gdelt.py`**

Add imports near the top of `gdelt.py` (after line 14):

```python
from app.services.country_centroids import get_centroid
from app.services.topic_classifier import classify_topic
```

Replace the `_parse_doc_response` function (lines 128-177) with:

```python
def _parse_doc_response(data: Any) -> list[NewsArticle]:
    """Parse the raw JSON from GDELT DOC 2.0 into NewsArticle models."""
    if data is None:
        return []

    raw_articles: list[dict] = []
    if isinstance(data, dict):
        raw_articles = data.get("articles", [])
    elif isinstance(data, list):
        raw_articles = data

    now = datetime.now(timezone.utc)
    articles: list[NewsArticle] = []
    for item in raw_articles:
        try:
            title = item.get("title", "").strip()
            if not title:
                continue
            url = item.get("url", "")
            source = item.get("domain", item.get("source", ""))
            lang = item.get("language", "en") or "en"
            tone = item.get("tone", 0.0)
            if isinstance(tone, str):
                try:
                    tone = float(tone.split(",")[0])
                except (ValueError, IndexError):
                    tone = 0.0

            date_str = item.get("seendate", "")
            published_at = _parse_gdelt_date(date_str) if date_str else now

            article_id = hashlib.sha256(url.encode()).hexdigest()[:16]

            # Geo: look up centroid from sourcecountry
            country_code = item.get("sourcecountry", "")
            centroid = get_centroid(country_code)
            lat = centroid[0] if centroid else 0.0
            lng = centroid[1] if centroid else 0.0

            # Topics: classify from title
            topic_tags = classify_topic(title)

            articles.append(
                NewsArticle(
                    id=article_id,
                    title=title,
                    source_url=url,
                    source_name=source,
                    source_language=lang,
                    published_at=published_at,
                    ingested_at=now,
                    latitude=lat,
                    longitude=lng,
                    country_code=country_code,
                    sentiment_score=float(tone) if tone else 0.0,
                    topic_tags=topic_tags,
                )
            )
        except Exception:
            logger.debug("Skipping unparseable article: %s", item, exc_info=True)
    return articles
```

**Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_gdelt.py -v`
Expected: All 11 tests PASS

**Step 5: Commit**

```bash
git add backend/app/services/gdelt.py backend/tests/test_gdelt.py
git commit -m "feat: enrich GDELT articles with country centroids and topic tags"
```

---

### Task 4: Fix `fetch_articles` — remove GEO API, fix default query

**Files:**
- Modify: `backend/app/services/gdelt.py` (`fetch_articles` function, lines 63-105; delete `_fetch_geo` lines 108-125; delete `_merge_geo` lines 198-228)
- Modify: `backend/app/config.py` (remove `gdelt_geo_base_url`, line 58-63)
- Test: `backend/tests/test_gdelt.py` (add tests)

**Context:** The current `fetch_articles` function:
1. Defaults the query to `"*"` which GDELT rejects → returns empty
2. Calls the broken GEO API → URL matching fails, all articles get same coords
3. Drops articles with lat/lng 0,0 → drops everything since geo merge failed

After this task: default query is `sourcelang:english`, GEO API calls are removed, articles get coordinates from centroids (Task 3), and we only drop articles where the centroid lookup failed (unknown country).

**Step 1: Write the failing test**

Add to `backend/tests/test_gdelt.py`:

```python
import pytest
from unittest.mock import AsyncMock, patch

from app.services.gdelt import fetch_articles


class TestFetchArticles:
    @pytest.mark.asyncio
    async def test_default_query_is_sourcelang_english(self):
        """Ensure the default query uses sourcelang:english, not '*'."""
        mock_data = {"articles": [
            _make_raw_article(sourcecountry="US"),
        ]}

        with patch("app.services.gdelt._fetch_with_retry", new_callable=AsyncMock) as mock_fetch, \
             patch("app.services.gdelt.get_cached", new_callable=AsyncMock, return_value=None), \
             patch("app.services.gdelt.set_cached", new_callable=AsyncMock):
            mock_fetch.return_value = mock_data
            articles = await fetch_articles()
            # Check the query param sent to GDELT
            call_args = mock_fetch.call_args
            params = call_args[0][1]  # second positional arg
            assert params["query"] == "sourcelang:english"

    @pytest.mark.asyncio
    async def test_topic_appended_to_query(self):
        """When topic is provided, it's appended to the base query."""
        mock_data = {"articles": [_make_raw_article(sourcecountry="US")]}

        with patch("app.services.gdelt._fetch_with_retry", new_callable=AsyncMock) as mock_fetch, \
             patch("app.services.gdelt.get_cached", new_callable=AsyncMock, return_value=None), \
             patch("app.services.gdelt.set_cached", new_callable=AsyncMock):
            mock_fetch.return_value = mock_data
            await fetch_articles(topic="climate")
            params = mock_fetch.call_args[0][1]
            assert "climate" in params["query"]
            assert "sourcelang:english" in params["query"]

    @pytest.mark.asyncio
    async def test_drops_articles_without_coords(self):
        """Articles from unknown countries (no centroid) are dropped."""
        mock_data = {"articles": [
            _make_raw_article(sourcecountry="US", url="https://a.com/1"),
            _make_raw_article(sourcecountry="ZZ", url="https://a.com/2"),  # unknown
        ]}

        with patch("app.services.gdelt._fetch_with_retry", new_callable=AsyncMock) as mock_fetch, \
             patch("app.services.gdelt.get_cached", new_callable=AsyncMock, return_value=None), \
             patch("app.services.gdelt.set_cached", new_callable=AsyncMock):
            mock_fetch.return_value = mock_data
            articles = await fetch_articles()
            assert len(articles) == 1
            assert articles[0].country_code == "US"

    @pytest.mark.asyncio
    async def test_no_geo_api_call(self):
        """Ensure _fetch_geo is no longer called."""
        mock_data = {"articles": [_make_raw_article(sourcecountry="US")]}

        with patch("app.services.gdelt._fetch_with_retry", new_callable=AsyncMock) as mock_fetch, \
             patch("app.services.gdelt.get_cached", new_callable=AsyncMock, return_value=None), \
             patch("app.services.gdelt.set_cached", new_callable=AsyncMock):
            mock_fetch.return_value = mock_data
            await fetch_articles()
            # Should only call _fetch_with_retry once (DOC API), not twice (DOC + GEO)
            assert mock_fetch.call_count == 1

    @pytest.mark.asyncio
    async def test_returns_cached_results(self):
        """When cache has data, return it without calling GDELT."""
        cached = [_make_raw_article(sourcecountry="US", latitude=37.09, longitude=-95.71)]

        with patch("app.services.gdelt.get_cached", new_callable=AsyncMock, return_value=cached), \
             patch("app.services.gdelt._fetch_with_retry", new_callable=AsyncMock) as mock_fetch:
            articles = await fetch_articles()
            mock_fetch.assert_not_called()
            assert len(articles) == 1
```

**Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_gdelt.py::TestFetchArticles -v`
Expected: `test_default_query_is_sourcelang_english` FAILS (query is `*`), `test_no_geo_api_call` FAILS (2 calls)

**Step 3: Modify `fetch_articles` in `backend/app/services/gdelt.py`**

Replace the `fetch_articles` function (lines 63-105) with:

```python
async def fetch_articles(
    query: str = "",
    timespan: str = "24h",
    max_records: int = 250,
    topic: str | None = None,
) -> list[NewsArticle]:
    """Fetch articles from the GDELT DOC 2.0 API and return parsed models.

    Results are cached in Redis for ``settings.gdelt_cache_ttl`` seconds.
    """
    search_query = query or "sourcelang:english"
    if topic:
        search_query = f"{search_query} {topic}".strip()

    cache_k = _cache_key("gdelt:doc", q=search_query, ts=timespan, mr=str(max_records))
    cached = await get_cached(cache_k)
    if cached is not None:
        return [NewsArticle(**a) for a in cached]

    params: dict[str, Any] = {
        "query": search_query,
        "mode": "ArtList",
        "maxrecords": max_records,
        "format": "json",
        "timespan": timespan,
    }

    data = await _fetch_with_retry(settings.gdelt_doc_base_url, params)
    articles = _parse_doc_response(data)

    # Drop articles without a valid location — they cannot be plotted.
    articles = [a for a in articles if a.latitude != 0.0 or a.longitude != 0.0]

    # Cache the result.
    await set_cached(cache_k, [a.model_dump() for a in articles], settings.gdelt_cache_ttl)
    return articles
```

Delete the `_fetch_geo` function (lines 108-125) entirely.

Delete the `_merge_geo` function (lines 198-228) entirely.

Remove `gdelt_geo_base_url` from `backend/app/config.py` (lines 58-63).

**Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_gdelt.py -v`
Expected: All tests PASS (both `TestParseDocResponse` and `TestFetchArticles`)

**Step 5: Run full test suite**

Run: `cd backend && python -m pytest -v`
Expected: All tests PASS. If any existing tests referenced `_fetch_geo` or `_merge_geo`, they will need updating (unlikely — no test file existed for gdelt before this plan).

**Step 6: Commit**

```bash
git add backend/app/services/gdelt.py backend/app/config.py backend/tests/test_gdelt.py
git commit -m "fix: replace broken GEO API with country centroids, use sourcelang:english default"
```

---

### Task 5: Fix topic filtering in router

**Files:**
- Modify: `backend/app/routers/news.py` (the `get_globe_data` function, lines 29-45)
- Test: `backend/tests/test_news_router.py` (create)

**Context:** Currently the `topic` param is passed directly to `fetch_articles`, which appends it as a GDELT search term. This works for some topics (e.g., "climate") but not for our classified topic names (e.g., "conflict" would search GDELT for articles containing the word "conflict", missing articles about "war" or "missile"). We should post-filter articles by their classified `topic_tags` instead.

**Step 1: Write the failing test**

Create `backend/tests/test_news_router.py`:

```python
"""Tests for the news router topic filtering."""

import pytest
from unittest.mock import AsyncMock, patch

from app.models.news import NewsArticle
from datetime import datetime, timezone


def _make_article(title: str, topic_tags: list[str], lat: float = 40.0, lng: float = -74.0):
    now = datetime.now(timezone.utc)
    return NewsArticle(
        id="test",
        title=title,
        source_url="https://example.com",
        source_name="example.com",
        source_language="en",
        published_at=now,
        ingested_at=now,
        latitude=lat,
        longitude=lng,
        topic_tags=topic_tags,
    )


class TestTopicFiltering:
    @pytest.mark.asyncio
    async def test_topic_filter_narrows_results(self):
        from app.routers.news import get_globe_data

        articles = [
            _make_article("War in region", ["conflict"], lat=40.0, lng=-74.0),
            _make_article("Stock market up", ["economy"], lat=51.0, lng=-0.1),
            _make_article("Missile strike", ["conflict"], lat=33.0, lng=44.0),
        ]

        with patch("app.routers.news.fetch_articles", new_callable=AsyncMock, return_value=articles):
            points = await get_globe_data(topic="conflict")
            # Only conflict articles should remain
            assert all(p.topic == "conflict" for p in points)

    @pytest.mark.asyncio
    async def test_no_topic_returns_all(self):
        from app.routers.news import get_globe_data

        articles = [
            _make_article("War in region", ["conflict"], lat=40.0, lng=-74.0),
            _make_article("Stock market up", ["economy"], lat=51.0, lng=-0.1),
        ]

        with patch("app.routers.news.fetch_articles", new_callable=AsyncMock, return_value=articles):
            points = await get_globe_data(topic=None)
            assert len(points) == 2
```

**Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_news_router.py -v`
Expected: `test_topic_filter_narrows_results` may pass or fail depending on whether GDELT query filtering and post-filtering interact correctly. The key behavioral change is that topic filtering should be post-classification, not GDELT query-level.

**Step 3: Modify `get_globe_data` in `backend/app/routers/news.py`**

Replace the `get_globe_data` function (lines 29-45) with:

```python
@router.get("/news", response_model=list[GlobeDataPoint])
async def get_globe_data(
    topic: str | None = Query(None, description="Optional topic filter"),
    timespan: str = Query("24h", description="GDELT timespan, e.g. 24h, 48h"),
    limit: int = Query(100, ge=1, le=500, description="Max data points"),
) -> list[GlobeDataPoint]:
    """Return globe data points for rendering on the 3-D globe.

    Fetches articles from GDELT, optionally filters by classified topic,
    clusters nearby articles, and returns lightweight ``GlobeDataPoint``
    objects.
    """
    articles = await fetch_articles(timespan=timespan)

    # Post-filter by classified topic tags (not GDELT query)
    if topic:
        articles = [a for a in articles if topic in a.topic_tags]

    clusters = cluster_articles(articles)
    points = clusters_to_globe_points(clusters)
    # Sort by article count descending so the front-end gets the heaviest dots first.
    points.sort(key=lambda p: p.article_count, reverse=True)
    return points[:limit]
```

Also update `get_cluster_articles` (lines 48-61) to post-filter the same way:

```python
@router.get("/news/cluster", response_model=list[NewsArticle])
async def get_cluster_articles(
    lat: float = Query(..., description="Latitude of cluster center"),
    lng: float = Query(..., description="Longitude of cluster center"),
    radius: float = Query(2.0, description="Search radius in degrees"),
    topic: str | None = Query(None, description="Optional topic filter"),
) -> list[NewsArticle]:
    """Return full articles near a given lat/lng point.

    Used when a user clicks a dot on the globe.
    """
    articles = await fetch_articles()
    if topic:
        articles = [a for a in articles if topic in a.topic_tags]
    nearby = articles_near(articles, lat, lng, radius)
    return nearby
```

**Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_news_router.py -v`
Expected: All tests PASS

**Step 5: Run full test suite**

Run: `cd backend && python -m pytest -v`
Expected: All tests PASS

**Step 6: Commit**

```bash
git add backend/app/routers/news.py backend/tests/test_news_router.py
git commit -m "fix: post-filter articles by classified topic tags instead of GDELT query"
```

---

### Task 6: Smoke test against live GDELT API

**Files:** None (manual verification only)

**Context:** All code changes are done. This task verifies the pipeline works end-to-end by calling the local backend and confirming articles come back with real coordinates and topics.

**Step 1: Start the backend locally**

Run: `cd backend && uvicorn app.main:app --reload --port 8000`

**Step 2: Test the `/api/news` endpoint**

Run (in a separate terminal):
```bash
curl -s http://localhost:8000/api/news?limit=5 | python -m json.tool
```

Expected: JSON array of `GlobeDataPoint` objects with:
- Real `lat`/`lng` values (not 0.0)
- `topic` field set to a classified topic (e.g., "conflict", "politics", "general")
- `article_count >= 1`
- `top_headline` containing a real news headline

**Step 3: Test topic filtering**

Run:
```bash
curl -s "http://localhost:8000/api/news?topic=conflict&limit=5" | python -m json.tool
```

Expected: All returned points have `topic: "conflict"` (or are part of clusters dominated by conflict articles).

**Step 4: Test the `/api/topics` endpoint**

Run:
```bash
curl -s http://localhost:8000/api/topics | python -m json.tool
```

Expected: JSON array of `TopicCount` objects like:
```json
[
  {"topic": "politics", "count": 42},
  {"topic": "conflict", "count": 31},
  {"topic": "economy", "count": 28},
  ...
]
```

**Step 5: Test the `/api/news/cluster` endpoint**

Pick a `lat`/`lng` from a point returned in Step 2 and run:
```bash
curl -s "http://localhost:8000/api/news/cluster?lat=37.09&lng=-95.71&radius=5" | python -m json.tool
```

Expected: Full `NewsArticle` objects with `topic_tags`, `country_code`, and real coordinates.

**Step 6: Stop the local server and commit (if any adjustments were needed)**

If everything works, no commit needed. If adjustments were made, commit them:

```bash
git add -u
git commit -m "fix: adjustments from live GDELT smoke testing"
```
