"""Generate backend/app/services/country_centroids.py: a name and label point per country.

Usage:
    python scripts/gen_country_centroids.py <ne_110m_admin_0_countries.geojson> \\
        --supplement scripts/data/gdelt_country_points.json

Each ISO 3166-1 alpha-2 code gets a display name and a label point, from
three sources in order of precedence:

1. Natural Earth's 1:110m admin-0 countries, the file three-globe ships,
   pinned at 2.45.0 by the frontend's npm override:
   frontend/node_modules/three-globe/example/country-polygons/
   ne_110m_admin_0_countries.geojson (after npm ci in frontend/). Its
   LABEL_X/LABEL_Y are used when the file has them; this version does not,
   so the point is the centroid of the country's largest polygon, or its
   pole of inaccessibility when that centroid falls outside it (Croatia,
   say). Either way the point lies on the country's main landmass.
2. --supplement: GDELT's own country coordinates, for the small states and
   territories the 110m file lacks (scripts/data/gdelt_country_points.json
   holds its source note and query). SUPPLEMENT_CORRECTIONS replaces the
   points in it that are wrong.
3. MANUAL_POINTS: hand-entered points for the codes neither has.

It refuses to write unless every ISO code ingestion can store (the values
of backend/app/services/country_codes.py) has exactly one point.
"""

import argparse
import hashlib
import heapq
import itertools
import json
import math
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "backend/app/services/country_centroids.py"
SOURCE = "three-globe 2.45.0, example/country-polygons/ne_110m_admin_0_countries.geojson"

Point = tuple[str, float, float]  # name, lat, lng

# Supplement points that are wrong, replaced (keyed by ISO code).
SUPPLEMENT_CORRECTIONS: dict[str, Point] = {
    # GDELT's median (16.0, 146.0) lies in the Northern Mariana Islands.
    "MU": ("Mauritius", -20.28, 57.58),
    # GDELT's median (19.4, 144.9) is among the northern islands; most people live on Saipan.
    "MP": ("Northern Mariana Islands", 15.2, 145.75),
}

# Codes in neither source. Approximate: they only anchor arcs.
MANUAL_POINTS: dict[str, Point] = {
    "BL": ("Saint Barthélemy", 17.9, -62.83),  # Gustavia
    "BV": ("Bouvet Island", -54.42, 3.36),  # the island itself
    "CC": ("Cocos (Keeling) Islands", -12.17, 96.83),  # West Island
    "CW": ("Curaçao", 12.17, -68.97),  # the island, by Willemstad
    "FO": ("Faroe Islands", 62.0, -6.78),  # Tórshavn
    "GS": ("South Georgia and the South Sandwich Islands", -54.28, -36.51),  # Grytviken
    "HM": ("Heard Island and McDonald Islands", -53.08, 73.5),  # Heard Island
    "IM": ("Isle of Man", 54.23, -4.55),  # the island's middle
    "IO": ("British Indian Ocean Territory", -7.31, 72.41),  # Diego Garcia
    "KN": ("Saint Kitts and Nevis", 17.3, -62.72),  # Basseterre
    "NF": ("Norfolk Island", -29.04, 167.95),  # Kingston
    "PM": ("Saint Pierre and Miquelon", 46.78, -56.18),  # Saint-Pierre
    "PN": ("Pitcairn Islands", -25.07, -130.1),  # Adamstown
    "SH": ("Saint Helena", -15.93, -5.72),  # Jamestown
    "ST": ("São Tomé and Príncipe", 0.34, 6.73),  # São Tomé
    "SX": ("Sint Maarten", 18.03, -63.05),  # Philipsburg
    "TC": ("Turks and Caicos Islands", 21.7, -71.8),  # between Providenciales and Grand Turk
    "VC": ("Saint Vincent and the Grenadines", 13.16, -61.22),  # Kingstown
    "WF": ("Wallis and Futuna", -13.28, -176.18),  # Mata-Utu
    "YT": ("Mayotte", -12.78, 45.23),  # Mamoudzou
}

# Natural Earth gives some countries ISO_A2 -99. Newer files carry the code in
# ISO_A2_EH; this one does not, so these are keyed by ADM0_A3. Still skipped,
# as they have no ISO code: Northern Cyprus and Somaliland.
ISO_BY_ADM0 = {"FRA": "FR", "NOR": "NO"}

# Display names where a source's is formal, out of date or not the country's.
NAME_OVERRIDES = {
    "AG": "Antigua and Barbuda",  # GDELT: "Antigua And Barbuda"
    "BN": "Brunei",
    "CZ": "Czechia",
    "KP": "North Korea",
    "KR": "South Korea",
    "LA": "Laos",
    "MK": "North Macedonia",
    "RU": "Russia",
    "SZ": "Eswatini",
    "UM": "US Minor Outlying Islands",  # GDELT: "Howland Island", one of them
    "VI": "US Virgin Islands",  # GDELT: "Virgin Islands"
}

REQUIRED = ("FR", "NO", "US", "CN", "RU", "BR", "ZA", "AU")


def check(ok: bool, message: str) -> None:
    if not ok:
        raise SystemExit(f"refusing to write {OUT.name}: {message}")


def ring_area_centroid(ring: list) -> tuple[float, float, float]:
    """Signed area and centroid of a closed ring (shoelace, planar lng/lat)."""
    area = cx = cy = 0.0
    for (x0, y0), (x1, y1) in zip(ring, ring[1:] + ring[:1]):
        cross = x0 * y1 - x1 * y0
        area += cross
        cx += (x0 + x1) * cross
        cy += (y0 + y1) * cross
    area /= 2
    if area == 0:
        return 0.0, ring[0][0], ring[0][1]
    return area, cx / (6 * area), cy / (6 * area)


def polygon_area_centroid(rings: list) -> tuple[float, float, float]:
    """Area and centroid of a polygon: its outer ring less its holes."""
    parts = [ring_area_centroid([tuple(p[:2]) for p in ring]) for ring in rings]
    outer, holes = parts[0], parts[1:]
    area = abs(outer[0]) - sum(abs(h[0]) for h in holes)
    x = (abs(outer[0]) * outer[1] - sum(abs(h[0]) * h[1] for h in holes)) / area
    y = (abs(outer[0]) * outer[2] - sum(abs(h[0]) * h[2] for h in holes)) / area
    return area, x, y


def signed_distance(x: float, y: float, rings: list) -> float:
    """Distance from (x, y) to the polygon's outline: positive inside, negative outside."""
    inside = False
    best = math.inf
    for ring in rings:
        for (ax, ay), (bx, by) in zip(ring, ring[1:] + ring[:1]):
            if (ay > y) != (by > y) and x < (bx - ax) * (y - ay) / (by - ay) + ax:
                inside = not inside
            dx, dy = bx - ax, by - ay
            t = 0.0
            if dx or dy:
                t = max(0.0, min(1.0, ((x - ax) * dx + (y - ay) * dy) / (dx * dx + dy * dy)))
            best = min(best, math.hypot(x - ax - t * dx, y - ay - t * dy))
    return best if inside else -best


def pole_of_inaccessibility(rings: list, precision: float = 0.01) -> tuple[float, float]:
    """The interior point farthest from the outline (Mapbox's polylabel), in ring units."""
    xs = [p[0] for p in rings[0]]
    ys = [p[1] for p in rings[0]]
    min_x, min_y, max_x, max_y = min(xs), min(ys), max(xs), max(ys)
    size = min(max_x - min_x, max_y - min_y)
    if size == 0:
        return min_x, min_y
    order = itertools.count()
    queue: list = []

    def cell(x: float, y: float, half: float) -> tuple:
        d = signed_distance(x, y, rings)
        return (d, half, x, y, d + half * math.sqrt(2))

    def push(c: tuple) -> None:
        heapq.heappush(queue, (-c[4], next(order), c))

    x = min_x
    while x < max_x:
        y = min_y
        while y < max_y:
            push(cell(x + size / 2, y + size / 2, size / 2))
            y += size
        x += size
    best = cell((min_x + max_x) / 2, (min_y + max_y) / 2, 0)
    while queue:
        _, _, c = heapq.heappop(queue)
        if c[0] > best[0]:
            best = c
        if c[4] - best[0] <= precision:
            continue
        half = c[1] / 2
        for dx, dy in ((-half, -half), (half, -half), (-half, half), (half, half)):
            push(cell(c[2] + dx, c[3] + dy, half))
    return best[2], best[3]


def label_point(geometry: dict) -> tuple[float, float]:
    """(lat, lng) on the country's largest polygon (see the module docstring)."""
    polygons = geometry["coordinates"]
    if geometry["type"] == "Polygon":
        polygons = [polygons]
    rings_of = [[[tuple(p[:2]) for p in ring] for ring in polygon] for polygon in polygons]

    def true_area(rings: list) -> float:  # planar degrees shrink with latitude
        area, _, lat = polygon_area_centroid(rings)
        return area * math.cos(math.radians(lat))

    rings = max(rings_of, key=true_area)
    _, lng, lat = polygon_area_centroid(rings)
    if signed_distance(lng, lat, rings) > 0:
        return lat, lng
    # Scale longitude by the cosine of the middle latitude, so distances are
    # roughly true while looking for the point farthest from the outline.
    ys = [p[1] for p in rings[0]]
    scale = math.cos(math.radians((min(ys) + max(ys)) / 2))
    x, lat = pole_of_inaccessibility([[(px * scale, py) for px, py in ring] for ring in rings])
    return lat, x / scale


def iso_code(props: dict) -> str:
    for key in ("ISO_A2", "ISO_A2_EH"):
        code = str(props.get(key) or "")
        if re.fullmatch(r"[A-Z]{2}", code):
            return code
    return ISO_BY_ADM0.get(props.get("ADM0_A3", ""), "")


def natural_earth_points(features: list) -> tuple[dict[str, Point], list[str]]:
    """Each feature's ISO code, name and label point; and the features without a code."""
    points: dict[str, Point] = {}
    skipped = []
    for feature in features:
        props = feature["properties"]
        iso = iso_code(props)
        if not iso:
            skipped.append(props.get("NAME_LONG") or props.get("ADMIN"))
            continue
        check(iso not in points, f"{iso} is listed twice")
        if props.get("LABEL_Y") is not None and props.get("LABEL_X") is not None:
            lat, lng = float(props["LABEL_Y"]), float(props["LABEL_X"])
        else:
            lat, lng = label_point(feature["geometry"])
        points[iso] = (str(props["NAME_LONG"]), lat, lng)
    return points, skipped


def read_supplement(path: str) -> tuple[dict[str, Point], str]:
    """The supplement's points, and its SHA-256 with line endings normalised to LF.

    Normalised so that a Windows checkout (core.autocrlf) hashes the same.
    """
    raw = Path(path).read_bytes()
    sha256 = hashlib.sha256(raw.replace(b"\r\n", b"\n")).hexdigest()
    entries = json.loads(raw.decode("utf-8"))["points"]
    bad = sorted(iso for iso in entries if not re.fullmatch(r"[A-Z]{2}", iso))
    check(not bad, f"supplement codes that are not ISO alpha-2: {bad}")
    points = {iso: (str(p["name"]), float(p["lat"]), float(p["lng"])) for iso, p in entries.items()}
    return points, sha256


def merge_points(
    natural_earth: dict[str, Point],
    supplement: dict[str, Point],
    corrections: dict[str, Point],
    manual: dict[str, Point],
) -> dict[str, Point]:
    """Natural Earth's points, then the supplement's (corrected) for codes it lacks, then manual."""
    points = dict(natural_earth)
    for iso, point in supplement.items():
        points.setdefault(iso, corrections.get(iso, point))
    for iso, point in manual.items():
        points.setdefault(iso, point)
    return points


def stored_iso_codes() -> set[str]:
    """Every ISO code ingestion can store: the values of country_codes.FIPS_TO_ISO2."""
    sys.path.insert(0, str(ROOT / "backend"))
    from app.services.country_codes import FIPS_TO_ISO2

    return set(FIPS_TO_ISO2.values())


def display_path(path: str) -> str:
    resolved = Path(path).resolve()
    return resolved.relative_to(ROOT).as_posix() if resolved.is_relative_to(ROOT) else path


def main(geojson: str, supplement_path: str | None) -> None:
    raw = Path(geojson).read_bytes()
    sha256 = hashlib.sha256(raw).hexdigest()
    natural_earth, skipped = natural_earth_points(json.loads(raw.decode("utf-8"))["features"])
    check(170 <= len(natural_earth) <= 260, f"{len(natural_earth)} countries, expected 170-260")
    missing = [iso for iso in REQUIRED if iso not in natural_earth]
    check(not missing, f"Natural Earth lacks {missing}")

    supplement: dict[str, Point] = {}
    supplement_sha256 = ""
    if supplement_path:
        supplement, supplement_sha256 = read_supplement(supplement_path)
        stray = sorted(set(SUPPLEMENT_CORRECTIONS) - (set(supplement) - set(natural_earth)))
        check(not stray, f"corrections for points the supplement does not supply: {stray}")
    stale = sorted(set(MANUAL_POINTS) & (set(natural_earth) | set(supplement)))
    check(not stale, f"manual points a source now supplies (remove them): {stale}")

    merged = merge_points(natural_earth, supplement, SUPPLEMENT_CORRECTIONS, MANUAL_POINTS)
    points: dict[str, Point] = {}
    for iso, (name, lat, lng) in merged.items():
        name = " ".join(NAME_OVERRIDES.get(iso, name).split())
        check(-90 <= lat <= 90 and -180 <= lng <= 180, f"{iso} is off the globe: {lat}, {lng}")
        points[iso] = (name, round(lat, 2), round(lng, 2))

    stored = stored_iso_codes()
    uncovered = sorted(stored - set(points))
    hint = "" if supplement_path else "; pass --supplement scripts/data/gdelt_country_points.json"
    check(not uncovered, f"no point for {len(uncovered)} codes: {uncovered}{hint}")
    unknown = sorted(set(points) - stored)
    check(not unknown, f"codes ingestion never stores: {unknown}")
    abbreviated = sorted(iso for iso, (name, _, _) in points.items() if "." in name)
    check(not abbreviated, f"abbreviated names: {abbreviated}")
    unquotable = sorted(iso for iso, (name, _, _) in points.items() if re.search(r'["\\]', name))
    check(not unquotable, f"names with quotes or backslashes: {unquotable}")

    body = "\n".join(
        f'    "{iso}": Centroid("{name}", {lat}, {lng}),'
        for iso, (name, lat, lng) in sorted(points.items())
    )
    supplement_doc = (
        "- GDELT's own country coordinates for the small states and territories\n"
        "  that file lacks (some corrected in the script).\n"
        f"  Source: {display_path(supplement_path)} (LF line endings)\n"
        f"  Source SHA-256: {supplement_sha256}\n"
        if supplement_path
        else ""
    )
    with open(OUT, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(
            '"""Country names and label points for link arcs, by ISO 3166-1 alpha-2 code.\n\n'
            "Generated by scripts/gen_country_centroids.py. Do not edit by hand. Every\n"
            "ISO code ingestion can store has a point, from the first of these that has it:\n\n"
            "- Natural Earth's 1:110m admin-0 countries: the centroid of the country's\n"
            "  largest polygon, or its pole of inaccessibility when that centroid falls\n"
            "  outside it.\n"
            f"  Source: {SOURCE}\n"
            f"  Source SHA-256: {sha256}\n"
            f"{supplement_doc}"
            "- Hand-entered points (MANUAL_POINTS in the script) for the rest.\n"
            '"""\n\nfrom __future__ import annotations\n\n'
            "from typing import NamedTuple\n\n\n"
            "class Centroid(NamedTuple):\n"
            '    """A country\'s display name and label point."""\n\n'
            "    name: str\n"
            "    lat: float\n"
            "    lng: float\n\n\n"
            f"COUNTRY_CENTROIDS: dict[str, Centroid] = {{\n{body}\n}}\n\n\n"
            "def centroid(iso: str | None) -> Centroid | None:\n"
            '    """The name and label point for an ISO alpha-2 code (any case), or None."""\n'
            '    return COUNTRY_CENTROIDS.get((iso or "").strip().upper())\n'
        )
    print(
        f"wrote {len(points)} countries to {OUT}: {len(natural_earth)} from Natural Earth, "
        f"{len(set(supplement) - set(natural_earth))} from the supplement "
        f"({len(SUPPLEMENT_CORRECTIONS)} corrected), {len(MANUAL_POINTS)} by hand"
    )
    print(f"Natural Earth features skipped (no ISO code): {', '.join(skipped) or 'none'}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("geojson", help="three-globe's ne_110m_admin_0_countries.geojson")
    parser.add_argument("--supplement", help="scripts/data/gdelt_country_points.json")
    args = parser.parse_args()
    main(args.geojson, args.supplement)
