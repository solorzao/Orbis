"""Tests for the globe grid helper shared by cell queries and summary keys."""

import pytest

from app.services.grid import cell_index


@pytest.mark.parametrize(
    ("value", "cell_size", "expected"),
    [
        (40.5, 1.0, 40),
        (40.999, 1.0, 40),
        (51.0, 1.0, 51),  # on an edge: the cell above it, as SQL FLOOR puts it
        (-0.3, 1.0, -1),
        (-33.87, 1.0, -34),
        (-74.0, 1.0, -74),
        (1.0, 0.1, 10),  # FLOOR(1.0 / 0.1) in SQL; 1.0 // 0.1 would give 9
    ],
)
def test_cell_index_floors_like_the_globe_sql(value, cell_size, expected):
    assert cell_index(value, cell_size) == expected
