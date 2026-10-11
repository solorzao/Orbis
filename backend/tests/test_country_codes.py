import re
from pathlib import Path

from app.services.country_codes import fips_to_iso2

SEED_SQL = Path(__file__).resolve().parents[2] / "database" / "seed.sql"


def test_known_fips_codes_map_to_iso():
    assert fips_to_iso2("CH") == "CN"  # China
    assert fips_to_iso2("SP") == "ES"  # Spain
    assert fips_to_iso2("UK") == "GB"  # United Kingdom
    assert fips_to_iso2("AS") == "AU"  # Australia
    assert fips_to_iso2("RS") == "RU"  # Russia
    assert fips_to_iso2("NI") == "NG"  # Nigeria


def test_gaza_maps_to_palestine():
    # GeoNames lists only WE (West Bank) for PS; GZ comes from the generator's overrides.
    assert fips_to_iso2("GZ") == "PS"
    assert fips_to_iso2("WE") == "PS"


def test_unknown_or_empty_returns_empty_string():
    assert fips_to_iso2("ZZ") == ""
    assert fips_to_iso2("") == ""
    assert fips_to_iso2(None) == ""


def test_seed_rows_carry_matching_fips():
    """Seeded rows must set country_fips, or the backfill would misread their ISO codes."""
    sql = SEED_SQL.read_text(encoding="utf-8")
    columns = re.search(r"INSERT INTO articles \(([^)]*)\)", sql).group(1)
    assert [c.strip() for c in columns.split(",")][7:9] == ["country_code", "country_fips"]

    # "<lat>, <lng>, '<iso>', '<fips>', '<region>'," on each row's coordinates line
    pairs = re.findall(r"-?[\d.]+, -?[\d.]+, '([A-Z]{2})', '([A-Z]{2})', '", sql)
    assert len(pairs) == sql.count("ST_SetSRID")
    for iso, fips in pairs:
        assert fips_to_iso2(fips) == iso, (iso, fips)
