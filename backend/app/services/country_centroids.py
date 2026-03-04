"""Country code -> centroid coordinate lookup.

Maps ISO 3166-1 alpha-2 country codes to approximate geographic center
coordinates (latitude, longitude). Used to place GDELT articles on the
globe when the API only provides a `sourcecountry` field.
"""

from __future__ import annotations

COUNTRY_CENTROIDS: dict[str, tuple[float, float]] = {
    "AF": (33.93, 67.71),
    "AL": (41.15, 20.17),
    "DZ": (28.03, 1.66),
    "AR": (-38.42, -63.62),
    "AM": (40.07, 45.04),
    "AU": (-25.27, 133.78),
    "AT": (47.52, 14.55),
    "AZ": (40.14, 47.58),
    "BD": (23.68, 90.36),
    "BY": (53.71, 27.95),
    "BE": (50.50, 4.47),
    "BR": (-14.24, -51.93),
    "BG": (42.73, 25.49),
    "CA": (56.13, -106.35),
    "CL": (-35.68, -71.54),
    "CN": (35.86, 104.20),
    "CO": (4.57, -74.30),
    "HR": (45.10, 15.20),
    "CU": (21.52, -77.78),
    "CZ": (49.82, 15.47),
    "DK": (56.26, 9.50),
    "EG": (26.82, 30.80),
    "ET": (9.15, 40.49),
    "FI": (61.92, 25.75),
    "FR": (46.23, 2.21),
    "GE": (42.32, 43.36),
    "DE": (51.17, 10.45),
    "GH": (7.95, -1.02),
    "GR": (39.07, 21.82),
    "HU": (47.16, 19.50),
    "IN": (20.59, 78.96),
    "ID": (-0.79, 113.92),
    "IR": (32.43, 53.69),
    "IQ": (33.22, 43.68),
    "IE": (53.14, -7.69),
    "IL": (31.05, 34.85),
    "IT": (41.87, 12.57),
    "JP": (36.20, 138.25),
    "JO": (30.59, 36.24),
    "KZ": (48.02, 66.92),
    "KE": (-0.02, 37.91),
    "KP": (40.34, 127.51),
    "KR": (35.91, 127.77),
    "KW": (29.31, 47.48),
    "LB": (33.85, 35.86),
    "LY": (26.34, 17.23),
    "MY": (4.21, 101.98),
    "MX": (23.63, -102.55),
    "MA": (31.79, -7.09),
    "MM": (21.91, 95.96),
    "NL": (52.13, 5.29),
    "NZ": (-40.90, 174.89),
    "NG": (9.08, 8.68),
    "NO": (60.47, 8.47),
    "PK": (30.38, 69.35),
    "PS": (31.95, 35.23),
    "PE": (-9.19, -75.02),
    "PH": (12.88, 121.77),
    "PL": (51.92, 19.15),
    "PT": (39.40, -8.22),
    "QA": (25.35, 51.18),
    "RO": (45.94, 24.97),
    "RU": (61.52, 105.32),
    "SA": (23.89, 45.08),
    "RS": (44.02, 21.01),
    "SG": (1.35, 103.82),
    "SK": (48.67, 19.70),
    "ZA": (-30.56, 22.94),
    "ES": (40.46, -3.75),
    "SD": (12.86, 30.22),
    "SE": (60.13, 18.64),
    "CH": (46.82, 8.23),
    "SY": (34.80, 38.99),
    "TW": (23.70, 120.96),
    "TH": (15.87, 100.99),
    "TN": (33.89, 9.54),
    "TR": (38.96, 35.24),
    "UA": (48.38, 31.17),
    "AE": (23.42, 53.85),
    "GB": (55.38, -3.44),
    "US": (37.09, -95.71),
    "UZ": (41.38, 64.59),
    "VE": (6.42, -66.59),
    "VN": (14.06, 108.28),
    "YE": (15.55, 48.52),
    "ZW": (-19.02, 29.15),
}


# GDELT uses full country names in `sourcecountry`, not ISO codes.
COUNTRY_NAME_TO_CODE: dict[str, str] = {
    "afghanistan": "AF",
    "albania": "AL",
    "algeria": "DZ",
    "argentina": "AR",
    "armenia": "AM",
    "australia": "AU",
    "austria": "AT",
    "azerbaijan": "AZ",
    "bangladesh": "BD",
    "belarus": "BY",
    "belgium": "BE",
    "brazil": "BR",
    "bulgaria": "BG",
    "canada": "CA",
    "chile": "CL",
    "china": "CN",
    "colombia": "CO",
    "croatia": "HR",
    "cuba": "CU",
    "czech republic": "CZ",
    "czechia": "CZ",
    "denmark": "DK",
    "egypt": "EG",
    "ethiopia": "ET",
    "finland": "FI",
    "france": "FR",
    "georgia": "GE",
    "germany": "DE",
    "ghana": "GH",
    "greece": "GR",
    "hungary": "HU",
    "india": "IN",
    "indonesia": "ID",
    "iran": "IR",
    "iraq": "IQ",
    "ireland": "IE",
    "israel": "IL",
    "italy": "IT",
    "japan": "JP",
    "jordan": "JO",
    "kazakhstan": "KZ",
    "kenya": "KE",
    "north korea": "KP",
    "south korea": "KR",
    "kuwait": "KW",
    "lebanon": "LB",
    "libya": "LY",
    "malaysia": "MY",
    "mexico": "MX",
    "morocco": "MA",
    "myanmar": "MM",
    "netherlands": "NL",
    "new zealand": "NZ",
    "nigeria": "NG",
    "norway": "NO",
    "pakistan": "PK",
    "palestine": "PS",
    "peru": "PE",
    "philippines": "PH",
    "poland": "PL",
    "portugal": "PT",
    "qatar": "QA",
    "romania": "RO",
    "russia": "RU",
    "saudi arabia": "SA",
    "serbia": "RS",
    "singapore": "SG",
    "slovakia": "SK",
    "south africa": "ZA",
    "spain": "ES",
    "sudan": "SD",
    "sweden": "SE",
    "switzerland": "CH",
    "syria": "SY",
    "taiwan": "TW",
    "thailand": "TH",
    "tunisia": "TN",
    "turkey": "TR",
    "ukraine": "UA",
    "united arab emirates": "AE",
    "united kingdom": "GB",
    "united states": "US",
    "uzbekistan": "UZ",
    "venezuela": "VE",
    "vietnam": "VN",
    "yemen": "YE",
    "zimbabwe": "ZW",
}


# Approximate geographic spread (degrees) per country.
# Large countries get more jitter so articles fan out across the landmass;
# small countries get less so dots stay on the map.
COUNTRY_SPREAD: dict[str, float] = {
    "RU": 30.0, "CA": 20.0, "US": 20.0, "CN": 15.0, "BR": 15.0,
    "AU": 15.0, "IN": 10.0, "AR": 12.0, "KZ": 10.0, "DZ": 10.0,
    "SA": 8.0, "MX": 8.0, "ID": 8.0, "SD": 8.0, "LY": 8.0,
    "IR": 7.0, "PE": 7.0, "CL": 7.0, "CO": 6.0, "ZA": 6.0,
    "ET": 6.0, "EG": 5.0, "NG": 5.0, "TR": 5.0, "PK": 5.0,
    "FR": 4.0, "ES": 4.0, "DE": 3.0, "PL": 3.0, "IT": 3.0,
    "GB": 3.0, "JP": 4.0, "UA": 4.0, "SE": 5.0, "NO": 5.0,
    "FI": 5.0, "VN": 4.0, "TH": 4.0, "MM": 4.0, "MY": 4.0,
    "PH": 4.0, "KE": 4.0, "NZ": 4.0, "RO": 3.0, "IQ": 3.0,
}


def normalize_country(raw: str) -> str:
    """Convert a GDELT sourcecountry value to an ISO 2-letter code.

    Accepts either an ISO code (\"US\") or a full name (\"United States\").
    Returns the ISO code, or the original string uppercased if no mapping found.
    """
    if not raw:
        return ""
    stripped = raw.strip()
    # Already a 2-letter ISO code?
    upper = stripped.upper()
    if len(upper) == 2 and upper in COUNTRY_CENTROIDS:
        return upper
    # Try full-name lookup
    code = COUNTRY_NAME_TO_CODE.get(stripped.lower())
    return code if code else upper


def get_centroid(country_code: str) -> tuple[float, float] | None:
    """Return (latitude, longitude) for the given ISO country code, or None.

    Also accepts full country names (e.g. \"United States\") which are
    normalized to ISO codes first.
    """
    if not country_code:
        return None
    normalized = normalize_country(country_code)
    return COUNTRY_CENTROIDS.get(normalized)
