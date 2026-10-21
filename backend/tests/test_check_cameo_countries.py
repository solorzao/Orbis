from scripts.check_cameo_countries import diff, expected_table

ISO = {"USA": "US", "ROU": "RO", "TLS": "TL", "SSD": "SS"}
CAMEO = {"USA": "United States", "ROM": "Romania", "AFR": "Africa", "ANT": "Netherlands Antilles"}
RULES = {
    "exceptions": {"ROM": "RO"},
    "regional": frozenset({"AFR"}),
    "withdrawn": frozenset({"ANT"}),
    "extra": frozenset({"SSD"}),
}


def test_the_references_give_the_table():
    expected, problems = expected_table(ISO, CAMEO, **RULES)
    assert expected == {"ROM": "RO", "SSD": "SS", "USA": "US"}
    assert problems == []
    assert diff(expected, expected) == []


def test_a_differing_table_is_reported_line_by_line():
    expected, _ = expected_table(ISO, CAMEO, **RULES)
    committed = {"ROM": "RU", "USA": "US", "XYZ": "XY"}
    assert diff(committed, expected) == [
        "  missing  SSD -> SS",
        "  extra    XYZ -> XY",
        "  wrong    ROM -> RU (expected RO)",
    ]


def test_a_code_with_no_decision_is_a_problem():
    _, problems = expected_table(ISO, {**CAMEO, "KSV": "Kosovo"}, **RULES)
    assert any(p.startswith("KSV (Kosovo)") for p in problems)


def test_stale_rules_are_problems():
    rules = {
        **RULES,
        "exceptions": {"ROM": "RO", "USA": "US"},
        "extra": frozenset({"USA", "SSD"}),
    }
    _, problems = expected_table(ISO, CAMEO, **rules)
    assert "EXCEPTIONS USA: an ISO alpha-3 code (US); drop the exception" in problems
    assert "EXTRA USA: already in CAMEO's list; drop it from EXTRA" in problems
