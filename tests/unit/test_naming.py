"""T014 — failing-first unit tests for ``solari_converter.naming``.

GREEN owner: **T026** (`naming.py` — `selector_token`, `artifact_name`). Written now
(Constitution VI). These tests FAIL until T026 lands (the module import inside each test
raises ``ModuleNotFoundError``) — that is an INTENTIONAL future RED, not a regression.
FR-053: deterministic artifact names from the source stem + page-range token.
"""

from __future__ import annotations

from solari_converter.model.page_selection import PageSelection


def _naming():
    import solari_converter.naming as naming  # GREEN owner: T026

    return naming


def test_selector_token_matches_page_selection_normalized_token() -> None:
    sel = PageSelection.parse("2,5-7,10-12")
    assert _naming().selector_token(sel) == "2_5-7_10-12"


def test_whole_document_base_name_has_no_page_suffix_in_the_filename() -> None:
    # cli.md: <base> = <stem>[__p<sel>]; whole-doc => "" suffix (just the stem).
    base = _naming().artifact_name("agreement", PageSelection.whole_document(), kind="base")
    assert base == "agreement"


def test_whole_document_envelope_page_selection_is_all_not_empty() -> None:
    # data-model.md common envelope: page_selection is the canonical token OR "all".
    assert PageSelection.whole_document().normalized_token() == "all"


def test_partial_selection_base_name_encodes_the_selector() -> None:
    base = _naming().artifact_name(
        "agreement", PageSelection.parse("2,5-7,10-12"), kind="base"
    )
    assert base == "agreement__p2_5-7_10-12"


def test_artifact_names_are_deterministic() -> None:
    sel = PageSelection.parse("2,5-7")
    naming = _naming()
    a = naming.artifact_name("agreement", sel, kind="base")
    b = naming.artifact_name("agreement", sel, kind="base")
    assert a == b == "agreement__p2_5-7"
