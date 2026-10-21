import re

from app.services.cameo_countries import (
    CAMEO_TO_ISO2,
    EXCEPTIONS,
    EXTRA,
    REGIONAL,
    WITHDRAWN,
    cameo_to_iso2,
)
from app.services.country_centroids import centroid


def test_iso_alpha3_codes_map_to_alpha2():
    assert cameo_to_iso2("USA") == "US"
    assert cameo_to_iso2("GBR") == "GB"
    assert cameo_to_iso2("RUS") == "RU"
    assert cameo_to_iso2("CHN") == "CN"
    assert cameo_to_iso2("IRN") == "IR"
    assert cameo_to_iso2("UKR") == "UA"
    assert cameo_to_iso2("COD") == "CD"
    assert cameo_to_iso2("COG") == "CG"


def test_cameo_exceptions_map_to_their_country():
    assert cameo_to_iso2("ROM") == "RO"
    assert cameo_to_iso2("TMP") == "TL"
    assert cameo_to_iso2("MTN") == "ME"
    assert cameo_to_iso2("WSB") == "PS"
    assert cameo_to_iso2("GZS") == "PS"
    assert cameo_to_iso2("PSE") == "PS"
    assert cameo_to_iso2("BAG") == "IQ"


def test_regional_withdrawn_and_unknown_codes_are_unmapped():
    for code in ("AFR", "EUR", "MEA", "WST", "SAS", "ANT", "SCG", "XYZ", "US", "", None):
        assert cameo_to_iso2(code) == "", code


def test_codes_gdelt_emits_beyond_cameos_list_are_mapped():
    """19b's repro found South Sudan (88 events in a day) unmapped: an ISO code
    newer than CAMEO's list."""
    assert "SSD" in EXTRA
    assert cameo_to_iso2("SSD") == "SS"


def test_case_and_spaces_are_ignored():
    assert cameo_to_iso2(" usa ") == "US"


def test_the_table_is_well_formed():
    assert 190 <= len(CAMEO_TO_ISO2) <= 260
    bad = [
        f"{c}->{i}"
        for c, i in CAMEO_TO_ISO2.items()
        if not (re.fullmatch(r"[A-Z]{3}", c) and re.fullmatch(r"[A-Z]{2}", i))
    ]
    assert bad == []


def test_exceptions_extras_regions_and_withdrawn_codes_agree_with_the_table():
    assert all(CAMEO_TO_ISO2[code] == iso for code, iso in EXCEPTIONS.items())
    assert EXTRA <= CAMEO_TO_ISO2.keys()
    assert not (REGIONAL | WITHDRAWN) & CAMEO_TO_ISO2.keys()
    assert len(REGIONAL) == 25


def test_mapped_countries_without_a_label_point_are_few_and_small():
    """The relations read drops a pair whose code has no label point, as /api/links
    does. Only small territories may lack one; list them in the PR."""
    missing = sorted({iso for iso in CAMEO_TO_ISO2.values() if centroid(iso) is None})
    assert len(missing) <= 10, missing
    assert not set(missing) & {"US", "CN", "RU", "UA", "IL", "PS", "IR", "IN", "GB", "FR"}
