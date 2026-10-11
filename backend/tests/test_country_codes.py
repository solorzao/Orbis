import re
from pathlib import Path

from app.services import country_codes
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


def test_overrides_cover_gdelt_only_territories():
    assert fips_to_iso2("JN") == "SJ"  # Jan Mayen
    assert fips_to_iso2("WQ") == "UM"  # Wake Island
    assert fips_to_iso2("BQ") == "UM"  # Navassa Island
    assert fips_to_iso2("EU") == "TF"  # Europa Island
    assert fips_to_iso2("CR") == "AU"  # Coral Sea Islands


def test_withdrawn_iso_codes_are_unmapped():
    assert fips_to_iso2("NT") == ""  # Netherlands Antilles (ISO AN withdrawn)
    assert fips_to_iso2("YI") == ""  # Serbia and Montenegro (ISO CS withdrawn)


def test_generated_header_records_source_and_checksum():
    doc = country_codes.__doc__
    assert "https://download.geonames.org/export/dump/countryInfo.txt" in doc
    assert re.search(r"SHA-256: [0-9a-f]{64}\b", doc)
