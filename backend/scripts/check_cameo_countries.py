"""Check app/services/cameo_countries.py against its two references.

Run on CI only, by .github/workflows/cameo-countries.yml, which downloads on
the runner:
- GeoNames countryInfo.txt: ISO 3166-1 alpha-3 to alpha-2, about 31 KB;
- GDELT's CAMEO.country.txt: the documented CAMEO country list, about 5 KB.
Never run it on a developer's machine: the owner approves downloads case by case.

Read-only: it never writes the table. It prints, and writes to the job summary,
either "matches" or a diff (missing, extra and wrong codes, and any rule that no
longer fits the references), and exits 1 on a diff. Fix the table by hand, not
this check.

Usage (CI): cd backend && python -m scripts.check_cameo_countries
"""

from __future__ import annotations

import hashlib
import os
import sys
import urllib.request

from app.services import cameo_countries as table

GEONAMES = "https://download.geonames.org/export/dump/countryInfo.txt"
CAMEO = "https://www.gdeltproject.org/data/lookups/CAMEO.country.txt"


def fetch(url: str) -> bytes:
    return urllib.request.urlopen(url, timeout=30).read()


def iso3_to_iso2(raw: bytes) -> dict[str, str]:
    """GeoNames countryInfo.txt's ISO3 column to its ISO column."""
    pairs: dict[str, str] = {}
    for line in raw.decode("utf-8").splitlines():
        if not line or line.startswith("#"):
            continue
        cols = line.split("\t")
        if len(cols) > 1 and cols[0].strip() and cols[1].strip():
            pairs[cols[1].strip()] = cols[0].strip()
    return pairs


def cameo_codes(raw: bytes) -> dict[str, str]:
    """CAMEO.country.txt's codes and labels (its first line is the header)."""
    codes: dict[str, str] = {}
    for line in raw.decode("utf-8", errors="replace").splitlines()[1:]:
        code, _, label = line.partition("\t")
        if code.strip():
            codes[code.strip()] = label.strip()
    return codes


def expected_table(
    iso: dict[str, str],
    cameo: dict[str, str],
    *,
    exceptions: dict[str, str],
    regional: frozenset[str],
    withdrawn: frozenset[str],
    extra: frozenset[str],
) -> tuple[dict[str, str], list[str]]:
    """The table the references and the module's rules call for, and any rule that
    no longer fits the references."""
    expected: dict[str, str] = {}
    problems: list[str] = []
    for code in sorted(set(cameo) | extra):
        if code in regional or code in withdrawn:
            continue
        iso2 = exceptions.get(code) or iso.get(code)
        if iso2:
            expected[code] = iso2
        else:
            problems.append(
                f"{code} ({cameo.get(code, 'in EXTRA')}): not an ISO alpha-3 code, and not in"
                " EXCEPTIONS, REGIONAL or WITHDRAWN"
            )
    problems += [
        f"EXCEPTIONS {c}: an ISO alpha-3 code ({iso[c]}); drop the exception"
        for c in sorted(exceptions)
        if c in iso
    ]
    problems += [
        f"{name} {c}: not in CAMEO's list"
        for name, codes in (("REGIONAL", regional), ("WITHDRAWN", withdrawn))
        for c in sorted(codes)
        if c not in cameo
    ]
    problems += [
        f"EXTRA {c}: already in CAMEO's list; drop it from EXTRA"
        for c in sorted(extra)
        if c in cameo
    ]
    return expected, problems


def diff(committed: dict[str, str], expected: dict[str, str]) -> list[str]:
    """One line per code the committed table lacks, has extra or maps wrongly."""
    missing = sorted(expected.keys() - committed.keys())
    extra = sorted(committed.keys() - expected.keys())
    lines = [f"  missing  {c} -> {expected[c]}" for c in missing]
    lines += [f"  extra    {c} -> {committed[c]}" for c in extra]
    lines += [
        f"  wrong    {c} -> {committed[c]} (expected {expected[c]})"
        for c in sorted(committed.keys() & expected.keys())
        if committed[c] != expected[c]
    ]
    return lines


def main() -> int:
    geonames_raw, cameo_raw = fetch(GEONAMES), fetch(CAMEO)
    expected, problems = expected_table(
        iso3_to_iso2(geonames_raw),
        cameo_codes(cameo_raw),
        exceptions=table.EXCEPTIONS,
        regional=table.REGIONAL,
        withdrawn=table.WITHDRAWN,
        extra=table.EXTRA,
    )
    lines = problems + diff(table.CAMEO_TO_ISO2, expected)
    sources = (
        f"GeoNames sha256 {hashlib.sha256(geonames_raw).hexdigest()[:12]},"
        f" CAMEO list sha256 {hashlib.sha256(cameo_raw).hexdigest()[:12]}"
    )
    if lines:
        report = f"CAMEO_TO_ISO2 differs from its references ({sources}):\n" + "\n".join(lines)
    else:
        report = f"CAMEO_TO_ISO2 matches its references: {len(expected)} codes ({sources})."
    print(report)
    if summary := os.environ.get("GITHUB_STEP_SUMMARY"):
        fence = "`" * 3  # a Markdown code block, so the diff keeps its columns
        with open(summary, "a", encoding="utf-8") as fh:
            fh.write(f"{fence}\n{report}\n{fence}\n")
    return 1 if lines else 0


if __name__ == "__main__":
    sys.exit(main())
