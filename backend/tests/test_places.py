"""Tests for place names as the globe shows them."""

import pytest

from app.services.places import display_place

_WITHOUT_A_COUNTRY = [
    # GDELT's "(General)" fragment and the country it repeats.
    ("South Island, New Zealand (General), New Zealand", "South Island, New Zealand"),
    ("Gaza, Israel (General), Israel", "Gaza, Israel"),
    ("Israel (General), Israel", "Israel"),
    ("Queensland (General), Australia", "Queensland, Australia"),
    ("Kherson, Ukraine (general), ukraine", "Kherson, Ukraine"),
    ("Singapore, Singapore", "Singapore"),
    # Already clean: unchanged.
    (
        "Washington, District Of Columbia, United States",
        "Washington, District Of Columbia, United States",
    ),
    ("Paris, France", "Paris, France"),
    ("Ukraine", "Ukraine"),
    # Only a repeat at the end goes: a city named after its state stays.
    ("New York, New York, United States", "New York, New York, United States"),
    # Stray spaces and empty parts.
    ("  Lagos ,  Lagos State,   Nigeria ", "Lagos, Lagos State, Nigeria"),
    ("(General)", ""),
    ("", ""),
    (None, ""),
]


@pytest.mark.parametrize(("region", "shown"), _WITHOUT_A_COUNTRY)
def test_display_place(region, shown):
    """The one-argument call (other callers rely on it) behaves as it always has."""
    assert display_place(region) == shown


@pytest.mark.parametrize(("region", "shown"), _WITHOUT_A_COUNTRY)
@pytest.mark.parametrize("country_code", ["", None])
def test_without_a_country_code_nothing_changes(region, shown, country_code):
    assert display_place(region, country_code) == shown


@pytest.mark.parametrize(
    ("region", "country_code", "shown"),
    [
        # GDELT files Gaza and the West Bank under Israel; their ISO code is PS.
        ("Gaza, Israel", "PS", "Gaza, Palestine"),
        ("Gaza, Israel (General), Israel", "PS", "Gaza, Palestine"),
        ("Ramallah, West Bank, Israel", "PS", "Ramallah, West Bank, Palestine"),
        ("Ramallah, West Bank, Israel", "ps", "Ramallah, West Bank, Palestine"),
        # The corrected country is not repeated.
        ("Palestine, Israel", "PS", "Palestine"),
        # Already the country's name (in any case): unchanged.
        (
            "Washington, District Of Columbia, United States",
            "US",
            "Washington, District Of Columbia, United States",
        ),
        ("South Island, New Zealand (General), New Zealand", "NZ", "South Island, New Zealand"),
        ("Kherson, Ukraine (general), ukraine", "UA", "Kherson, Ukraine"),
        ("Jerusalem, Israel (General), Israel", "IL", "Jerusalem, Israel"),
        ("New York, New York, United States", "US", "New York, New York, United States"),
        # Another name for the country gives way to the one the globe's arcs use.
        ("Yangon, Burma", "MM", "Yangon, Myanmar"),
        # A one-part region names the place itself, not a country it is in.
        ("Gaza Strip", "PS", "Gaza Strip"),
        ("Israel (General), Israel", "IL", "Israel"),
        # A code with no known name, or no region: unchanged.
        ("Gaza, Israel", "ZZ", "Gaza, Israel"),
        ("", "PS", ""),
        (None, "PS", ""),
    ],
)
def test_the_country_follows_the_articles_country_code(region, country_code, shown):
    assert display_place(region, country_code) == shown
