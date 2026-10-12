"""Generate backend/app/services/country_centroids.py from Natural Earth's countries.

Usage: python scripts/gen_country_centroids.py <ne_110m_admin_0_countries.geojson>

The file is the one three-globe ships, pinned at 2.45.0 by the frontend's npm
override: frontend/node_modules/three-globe/example/country-polygons/
ne_110m_admin_0_countries.geojson (after npm ci in frontend/).

Each country gets its ISO 3166-1 alpha-2 code, a display name and a label
point. Natural Earth's LABEL_X/LABEL_Y are used when the file has them; this
version does not, so the point is the centroid of the country's largest
polygon, or its pole of inaccessibility when that centroid falls outside it
(Croatia, say). Either way the point lies on the country's main landmass.
"""

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

# Natural Earth gives some countries ISO_A2 -99. Newer files carry the code in
# ISO_A2_EH; this one does not, so these are keyed by ADM0_A3. Still skipped,
# as they have no ISO code: Northern Cyprus and Somaliland.
ISO_BY_ADM0 = {"FRA": "FR", "NOR": "NO"}

# Display names where NAME_LONG is formal or out of date.
NAME_OVERRIDES = {
    "BN": "Brunei",
    "CZ": "Czechia",
    "KP": "North Korea",
    "KR": "South Korea",
    "LA": "Laos",
    "MK": "North Macedonia",
    "RU": "Russia",
    "SZ": "Eswatini",
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


def main(path: str) -> None:
    raw = Path(path).read_bytes()
    sha256 = hashlib.sha256(raw).hexdigest()
    features = json.loads(raw.decode("utf-8"))["features"]

    points: dict[str, tuple[str, float, float]] = {}
    skipped = []
    for feature in features:
        props = feature["properties"]
        iso = iso_code(props)
        if not iso:
            skipped.append(props.get("NAME_LONG") or props.get("ADMIN"))
            continue
        check(iso not in points, f"{iso} is listed twice")
        name = NAME_OVERRIDES.get(iso) or " ".join(str(props["NAME_LONG"]).split())
        if props.get("LABEL_Y") is not None and props.get("LABEL_X") is not None:
            lat, lng = float(props["LABEL_Y"]), float(props["LABEL_X"])
        else:
            lat, lng = label_point(feature["geometry"])
        check(-90 <= lat <= 90 and -180 <= lng <= 180, f"{iso} is off the globe: {lat}, {lng}")
        points[iso] = (name, round(lat, 2), round(lng, 2))

    check(170 <= len(points) <= 260, f"{len(points)} countries, expected 170 to 260")
    missing = [iso for iso in REQUIRED if iso not in points]
    check(not missing, f"missing {missing}")
    abbreviated = sorted(iso for iso, (name, _, _) in points.items() if "." in name)
    check(not abbreviated, f"abbreviated names: {abbreviated}")
    unquotable = sorted(iso for iso, (name, _, _) in points.items() if re.search(r'["\\]', name))
    check(not unquotable, f"names with quotes or backslashes: {unquotable}")

    body = "\n".join(
        f'    "{iso}": Centroid("{name}", {lat}, {lng}),'
        for iso, (name, lat, lng) in sorted(points.items())
    )
    with open(OUT, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(
            '"""Country names and label points for link arcs, by ISO 3166-1 alpha-2 code.\n\n'
            "Generated by scripts/gen_country_centroids.py from Natural Earth's 1:110m\n"
            "admin-0 countries plus the overrides in that script. Do not edit by hand.\n"
            "Each point is the centroid of the country's largest polygon, or its pole\n"
            "of inaccessibility when that centroid falls outside it.\n\n"
            f"Source: {SOURCE}\n"
            f"Source SHA-256: {sha256}\n"
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
    print(f"wrote {len(points)} countries to {OUT}")
    print(f"skipped (no ISO code): {', '.join(skipped) or 'none'}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit(__doc__.splitlines()[2])
    main(sys.argv[1])
