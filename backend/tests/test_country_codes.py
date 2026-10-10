from app.services.country_codes import fips_to_iso2


def test_known_fips_codes_map_to_iso():
    assert fips_to_iso2("CH") == "CN"  # China
    assert fips_to_iso2("SP") == "ES"  # Spain
    assert fips_to_iso2("UK") == "GB"  # United Kingdom
    assert fips_to_iso2("AS") == "AU"  # Australia
    assert fips_to_iso2("RS") == "RU"  # Russia
    assert fips_to_iso2("NI") == "NG"  # Nigeria


def test_unknown_or_empty_returns_empty_string():
    assert fips_to_iso2("ZZ") == ""
    assert fips_to_iso2("") == ""
    assert fips_to_iso2(None) == ""
