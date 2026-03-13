"""Tests for the country centroid lookup module."""

from app.services.country_centroids import COUNTRY_CENTROIDS, get_centroid, normalize_country


def test_known_country_returns_coords():
    result = get_centroid("US")
    assert result is not None
    lat, lng = result
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
    for code in ["US", "GB", "FR", "DE", "CN", "RU", "IN", "BR", "AU", "JP"]:
        assert code in COUNTRY_CENTROIDS, f"Missing country: {code}"


def test_all_centroids_have_valid_ranges():
    for code, (lat, lng) in COUNTRY_CENTROIDS.items():
        assert -90.0 <= lat <= 90.0, f"{code} lat out of range: {lat}"
        assert -180.0 <= lng <= 180.0, f"{code} lng out of range: {lng}"


def test_full_country_name_lookup():
    """GDELT sends full names like 'United States', not ISO codes."""
    result = get_centroid("United States")
    assert result is not None
    assert 30.0 < result[0] < 50.0


def test_normalize_country_full_name():
    assert normalize_country("United States") == "US"
    assert normalize_country("United Kingdom") == "GB"
    assert normalize_country("France") == "FR"


def test_normalize_country_iso_code():
    assert normalize_country("US") == "US"
    assert normalize_country("gb") == "GB"


def test_normalize_country_unknown():
    assert normalize_country("ZZ") == "ZZ"
    assert normalize_country("") == ""
