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
    result = classify_topic("President announces new military strike campaign")
    assert "politics" in result
    assert "conflict" in result


def test_case_insensitive():
    assert classify_topic("WAR breaks out") == classify_topic("war breaks out")


def test_topic_keywords_dict_is_populated():
    assert len(TOPIC_KEYWORDS) >= 7
    for topic, keywords in TOPIC_KEYWORDS.items():
        assert len(keywords) >= 5, f"Topic '{topic}' has too few keywords"


def test_no_false_positives_from_substrings():
    """Word-boundary matching should prevent common false positives."""
    # "ai" should NOT match "Ukraine" or "explained"
    assert "technology" not in classify_topic("Ukraine peace talks continue")
    assert "technology" not in classify_topic("Expert explained the situation")
    # "app" should NOT match "apple" or "happy"
    assert "technology" not in classify_topic("Apple orchard hosts harvest festival")
    # "win" should NOT match "winter"
    assert "sports" not in classify_topic("Winter storms hit the northeast")


def test_multi_word_keywords_still_match():
    """Multi-word keywords like 'interest rate' should still work."""
    assert "economy" in classify_topic("Central bank raises interest rate")
