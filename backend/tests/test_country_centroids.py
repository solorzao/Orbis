"""Tests for the generated country label points (scripts/gen_country_centroids.py)."""

import importlib.util
import math
import re
from pathlib import Path

import pytest

from app.services import country_centroids
from app.services.country_centroids import COUNTRY_CENTROIDS, Centroid, centroid
from app.services.country_codes import FIPS_TO_ISO2

GENERATOR = Path(__file__).resolve().parents[2] / "scripts" / "gen_country_centroids.py"


def _generator():
    spec = importlib.util.spec_from_file_location("gen_country_centroids", GENERATOR)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


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


def test_every_code_ingestion_can_store_has_a_point():
    """No link is dropped for want of a point, whatever countries the stories name."""
    assert set(COUNTRY_CENTROIDS) == set(FIPS_TO_ISO2.values())


@pytest.mark.parametrize(
    ("iso", "name", "lat", "lng"),
    [
        ("SG", "Singapore", 1.37, 103.8),
        ("HK", "Hong Kong", 22.25, 114.17),
        ("VA", "Vatican City", 41.9, 12.45),
        ("BH", "Bahrain", 26.0, 50.5),
    ],
)
def test_small_states_come_from_gdelts_own_coordinates(iso, name, lat, lng):
    assert COUNTRY_CENTROIDS[iso] == Centroid(name, lat, lng)


def test_a_wrong_gdelt_point_is_corrected():
    # GDELT's median for Mauritius (16, 146) lies in the Northern Mariana Islands.
    point = COUNTRY_CENTROIDS["MU"]
    assert _degrees_apart((point.lat, point.lng), (-20.2, 57.5)) <= 1.0


@pytest.mark.parametrize(
    ("iso", "known"),
    [
        ("FO", (62.0, -6.8)),  # Faroe Islands
        ("CW", (12.2, -69.0)),  # Curacao
        ("IM", (54.2, -4.5)),  # Isle of Man
    ],
)
def test_the_rest_are_hand_entered(iso, known):
    point = COUNTRY_CENTROIDS[iso]
    assert _degrees_apart((point.lat, point.lng), known) <= 1.0


def test_supplement_names_read_as_country_names():
    assert COUNTRY_CENTROIDS["UM"].name == "US Minor Outlying Islands"  # not "Howland Island"
    assert COUNTRY_CENTROIDS["VI"].name == "US Virgin Islands"
    assert COUNTRY_CENTROIDS["AG"].name == "Antigua and Barbuda"


class TestMergePoints:
    """The generator's precedence: Natural Earth, then the supplement, then hand-entered points."""

    def test_natural_earth_wins_where_both_have_a_point(self):
        merged = _generator().merge_points(
            {"FR": ("France", 46.61, 2.34)},
            supplement={"FR": ("France", 46.0, 2.0), "SG": ("Singapore", 1.37, 103.8)},
            corrections={},
            manual={},
        )
        assert merged == {"FR": ("France", 46.61, 2.34), "SG": ("Singapore", 1.37, 103.8)}

    def test_corrections_replace_supplement_points_and_manual_points_fill_the_rest(self):
        merged = _generator().merge_points(
            {"FR": ("France", 46.61, 2.34)},
            supplement={"MU": ("Mauritius", 16.0, 146.0)},
            corrections={"MU": ("Mauritius", -20.28, 57.58)},
            manual={"FO": ("Faroe Islands", 62.0, -6.8), "FR": ("France", 0.0, 0.0)},
        )
        assert merged == {
            "FR": ("France", 46.61, 2.34),
            "MU": ("Mauritius", -20.28, 57.58),
            "FO": ("Faroe Islands", 62.0, -6.8),
        }


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


def test_generated_header_records_both_sources_and_checksums():
    doc = country_centroids.__doc__
    assert "ne_110m_admin_0_countries.geojson" in doc
    assert "three-globe 2.45.0" in doc
    assert "scripts/data/gdelt_country_points.json" in doc
    assert "MANUAL_POINTS" in doc
    assert len(re.findall(r"SHA-256: [0-9a-f]{64}\b", doc)) == 2
