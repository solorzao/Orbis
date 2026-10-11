"""The globe's grid: which cell a coordinate falls in."""

from __future__ import annotations

import math


def cell_index(value: float, cell_size: float) -> int:
    """Index of the grid cell holding *value*, a latitude or a longitude.

    ``FLOOR(value / cell_size)``, exactly as the globe dots' SQL computes it
    (``//`` can differ: ``1.0 // 0.1`` is 9), so a value on an edge belongs to
    the cell above it. Cell queries and summary cache keys both use this.
    """
    return math.floor(value / cell_size)
