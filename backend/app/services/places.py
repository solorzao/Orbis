"""Place names as the globe shows them."""

from __future__ import annotations

import re

# GDELT names a region it only knows at country or state level "X (General)".
_GENERAL = re.compile(r"\s*\(general\)", re.IGNORECASE)


def display_place(region: str | None) -> str:
    """A stored ``region`` as a place name to show.

    GDELT's ``(General)`` fragments go, and so does a country repeated at the
    end: ``South Island, New Zealand (General), New Zealand`` is shown as
    ``South Island, New Zealand``. Only the trailing repeat goes, so ``New
    York, New York, United States`` stays. The stored ``region`` stays raw.
    """
    if not region:
        return ""
    parts = [" ".join(part.split()) for part in _GENERAL.sub("", region).split(",")]
    parts = [part for part in parts if part]
    while len(parts) > 1 and parts[-1].casefold() == parts[-2].casefold():
        parts.pop()
    return ", ".join(parts)
