import re

import pytest

from skaldr.errors import ExportInvariantError
from skaldr.export.apportion import apportioned, apportioned_at_least


def test_all_zero_weights_are_an_invariant_error() -> None:
    with pytest.raises(
        ExportInvariantError,
        match=re.escape("cannot apportion 760 over weights that add up to nothing"),
    ):
        apportioned([0, 0], 760)


def test_no_weights_apportion_nothing() -> None:
    assert apportioned([], 760) == []


def test_a_part_under_the_minimum_takes_the_minimum_and_the_rest_share_what_is_left() -> None:
    assert apportioned_at_least([1, 6, 6, 6, 6, 6, 6, 6], 760, 60) == [60, 100, 100, 100, 100, 100, 100, 100]


def test_parts_over_the_minimum_are_left_as_apportioned() -> None:
    assert apportioned_at_least([1, 1], 760, 60) == apportioned([1, 1], 760)


def test_minimums_that_use_up_the_total_leave_each_part_its_minimum() -> None:
    assert apportioned_at_least([1] * 4, 200, 64) == [64, 64, 64, 64]
