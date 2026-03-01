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
                break

    return matched if matched else ["general"]
