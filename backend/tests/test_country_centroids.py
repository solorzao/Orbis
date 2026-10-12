"""Tests for the generated country label points (scripts/gen_country_centroids.py)."""

import math
import re

import pytest

from app.services import country_centroids
from app.services.country_centroids import COUNTRY_CENTROIDS, Centroid, centroid
from app.services.country_codes import FIPS_TO_ISO2

# Well-known centre points, within 3 degrees of which each label point must lie.
_KNOWN_POINTS = {
    "US": (39.83, -98.58),  # Lebanon, Kansas: the centre of the contiguous states
    "AU": (-25.61, 134.35),  # the Lambert Centre
    "FR": (46.54, 2.43),  # Vesdun, the centre of metropolitan France
    "DE": (51.16, 10.45),  # Niederdorla
    "ES": (40.31, -3.69),  # Cerro de los Angeles, the centre of mainland Spain
    "IR": (32.0, 53.7),
    "IN": (21.15, 79.08),  # Nagpur's Zero Mile Stone
}


def _degrees_apart(a: tuple[float, float], b: tuple[float, float]) -> float:
    """Great-circle distance in degrees."""
    lat1, lng1, lat2, lng2 = map(math.radians, (*a, *b))
    cos = math.sin(lat1) * math.sin(lat2) + math.cos(lat1) * math.cos(lat2) * math.cos(lng1 - lng2)
    return math.degrees(math.acos(max(-1.0, min(1.0, cos))))


@pytest.mark.parametrize("iso", sorted(_KNOWN_POINTS))
def test_anchor_points_are_within_3_degrees_of_known_centres(iso):
    point = COUNTRY_CENTROIDS[iso]
    assert _degrees_apart((point.lat, point.lng), _KNOWN_POINTS[iso]) <= 3.0, point


def test_countries_natural_earth_codes_as_minus_99_are_present():
    """Natural Earth gives France and Norway ISO_A2 -99; the generator recovers them."""
    for iso in ("FR", "NO", "US", "CN", "RU", "BR", "ZA", "AU"):
        assert iso in COUNTRY_CENTROIDS, iso
    assert COUNTRY_CENTROIDS["FR"].name == "France"
    assert COUNTRY_CENTROIDS["NO"].name == "Norway"


def test_covers_at_least_170_of_the_codes_ingestion_can_store():
    """Stands in for "every code in the last 7 days has a point" (gaps: small states)."""
    covered = set(COUNTRY_CENTROIDS) & set(FIPS_TO_ISO2.values())
    assert len(covered) >= 170


def test_every_code_is_an_iso_code_ingestion_can_store():
    assert set(COUNTRY_CENTROIDS) <= set(FIPS_TO_ISO2.values())


def test_names_are_one_readable_line():
    assert COUNTRY_CENTROIDS["US"].name == "United States"
    assert COUNTRY_CENTROIDS["IR"].name == "Iran"
    for iso, point in COUNTRY_CENTROIDS.items():
        assert point.name and point.name == " ".join(point.name.split()), iso
        assert "." not in point.name, iso  # no abbreviations ("Dem. Rep. Congo")


def test_points_are_on_the_globe():
    for iso, point in COUNTRY_CENTROIDS.items():
        assert -90 <= point.lat <= 90 and -180 <= point.lng <= 180, iso


def test_lookup_takes_any_case_and_misses_with_none():
    assert centroid("us") == centroid("US") == COUNTRY_CENTROIDS["US"]
    assert isinstance(centroid("US"), Centroid)
    assert centroid("ZZ") is None
    assert centroid("") is None
    assert centroid(None) is None


def test_generated_header_records_source_and_checksum():
    doc = country_centroids.__doc__
    assert "ne_110m_admin_0_countries.geojson" in doc
    assert "three-globe 2.45.0" in doc
    assert re.search(r"SHA-256: [0-9a-f]{64}\b", doc)
