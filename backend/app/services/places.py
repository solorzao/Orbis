"""Place names as the globe shows them."""

from __future__ import annotations

import re

from app.services.country_centroids import COUNTRY_CENTROIDS

# GDELT names a region it only knows at country or state level "X (General)".
_GENERAL = re.compile(r"\s*\(general\)", re.IGNORECASE)


def display_place(region: str | None, country_code: str | None = "") -> str:
    """A stored ``region`` as a place name to show.

    GDELT's ``(General)`` fragments go, and so does a country repeated at the
    end: ``South Island, New Zealand (General), New Zealand`` is shown as
    ``South Island, New Zealand``. Only the trailing repeat goes, so ``New
    York, New York, United States`` stays. The stored ``region`` stays raw.

    With the article's ISO ``country_code``, the trailing country is that
    country's name as the globe's arcs show it: GDELT files Gaza under Israel
    (``Gaza, Israel``) though its code is PS, so it is shown as ``Gaza,
    Palestine``. A one-part region names the place itself (``Gaza Strip``) and
    stays; so does every region when the code is empty or unknown.
    """
    if not region:
        return ""
    parts = [" ".join(part.split()) for part in _GENERAL.sub("", region).split(",")]
    parts = _without_trailing_repeats([part for part in parts if part])
    country = COUNTRY_CENTROIDS.get((country_code or "").strip().upper())
    if country and len(parts) > 1 and parts[-1].casefold() != country.name.casefold():
        parts = _without_trailing_repeats([*parts[:-1], country.name])
    return ", ".join(parts)


def _without_trailing_repeats(parts: list[str]) -> list[str]:
    """*parts* without the repeats of its last part at its end (case-insensitive)."""
    while len(parts) > 1 and parts[-1].casefold() == parts[-2].casefold():
        parts = parts[:-1]
    return parts
