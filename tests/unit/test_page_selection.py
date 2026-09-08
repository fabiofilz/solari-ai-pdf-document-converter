"""T014 — failing-first unit tests for ``solari_converter.model.page_selection``.

GREEN owner: **T021** (`model/page_selection.py`). FR-004: reject invalid selections
(out of range, reversed ranges, non-numeric, overlapping) and produce no output; page
numbers are **1-based physical** positions (FR-003), never printed labels.
"""

from __future__ import annotations

import pytest

from solari_converter.errors import InvalidSelection
from solari_converter.model.page_selection import PageSelection

# --- parsing: single / range / discontinuous -----------------------------------------


def test_single_page() -> None:
    sel = PageSelection.parse("5")
    assert sel.ranges == [[5, 5]]
    assert sel.is_whole_document is False
    assert sel.resolve(page_count=10) == [5]


def test_contiguous_range() -> None:
    sel = PageSelection.parse("5-7")
    assert sel.ranges == [[5, 7]]
    assert sel.resolve(page_count=10) == [5, 6, 7]


def test_multiple_discontinuous_ranges_in_one_request() -> None:
    sel = PageSelection.parse("2,5-7,10-12")
    assert sel.ranges == [[2, 2], [5, 7], [10, 12]]
    assert sel.resolve(page_count=20) == [2, 5, 6, 7, 10, 11, 12]


def test_whole_document_selection() -> None:
    sel = PageSelection.whole_document()
    assert sel.is_whole_document is True
    assert sel.resolve(page_count=3) == [1, 2, 3]


# --- FR-004 rejections: produce no output -------------------------------------------


def test_reversed_range_10_5_is_rejected() -> None:
    with pytest.raises(InvalidSelection):
        PageSelection.parse("10-5")


def test_non_numeric_is_rejected() -> None:
    with pytest.raises(InvalidSelection):
        PageSelection.parse("2,foo,5")


def test_overlapping_input_ranges_are_rejected_naming_the_overlap() -> None:
    with pytest.raises(InvalidSelection) as exc:
        PageSelection.parse("2-6,5-9")
    assert "5" in str(exc.value) and "6" in str(exc.value)


def test_zero_and_negative_pages_are_rejected() -> None:
    for bad in ("0", "-1", "0-3"):
        with pytest.raises(InvalidSelection):
            PageSelection.parse(bad)


def test_out_of_range_page_is_rejected_against_page_count() -> None:
    sel = PageSelection.parse("5-12")
    with pytest.raises(InvalidSelection):
        sel.resolve(page_count=8)


# --- normalization: token + ordering ----------------------------------------------


def test_normalized_token_for_a_partial_selection() -> None:
    # research §14 / cli.md: canonical selector token uses "_" between parts, "-" in a range.
    assert PageSelection.parse("2,5-7,10-12").normalized_token() == "2_5-7_10-12"


def test_normalized_token_for_whole_document_is_all() -> None:
    assert PageSelection.whole_document().normalized_token() == "all"


def test_adjacent_ranges_merge_and_unordered_input_sorts() -> None:
    sel = PageSelection.parse("7,5-6,2")
    assert sel.ranges == [[2, 2], [5, 7]]
    assert sel.normalized_token() == "2_5-7"


def test_pages_are_physical_not_printed_labels() -> None:
    # The model has no concept of a printed label — the physical page IS the number.
    sel = PageSelection.parse("1-2")
    assert sel.resolve(page_count=2) == [1, 2]
