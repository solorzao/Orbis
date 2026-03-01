"""Tests for GDELT response parsing with centroid and topic enrichment."""

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
        assert 40.0 < articles[0].latitude < 50.0
        assert 30.0 < articles[1].latitude < 40.0
