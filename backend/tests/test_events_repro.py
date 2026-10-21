"""The repro's --files bound (no network, no database: the run itself is CI-only)."""

import argparse

import pytest

from scripts.events_repro import MAX_FILES, _files


def test_files_is_an_integer_from_1_to_a_day():
    assert MAX_FILES == 96
    assert _files("1") == 1 and _files("96") == 96


@pytest.mark.parametrize("value", ["0", "97", "-1", "", "1e3", "96.0", "2; rm -rf /"])
def test_anything_else_is_refused(value):
    with pytest.raises(argparse.ArgumentTypeError):
        _files(value)
