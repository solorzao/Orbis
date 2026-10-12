"""Tests for place names as the globe shows them."""

import pytest

from app.services.places import display_place


@pytest.mark.parametrize(
    ("region", "shown"),
    [
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
    ],
)
def test_display_place(region, shown):
    assert display_place(region) == shown
