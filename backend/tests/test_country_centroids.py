"""Tests for the country centroid lookup module."""

from app.services.country_centroids import get_centroid, COUNTRY_CENTROIDS


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
