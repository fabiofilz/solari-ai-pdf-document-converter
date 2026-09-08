"""T014 — failing-first unit tests for ``solari_converter.model.segment``.

GREEN owner: **T019**. data-model.md: ``segment_id`` is stable across candidates and
geometry-derived — ``sha1(f"{page}:{round(bbox)}:{nfc_text_hash}")[:12]``; used across
candidates and in review items.
"""

from __future__ import annotations

import hashlib
import unicodedata

from solari_converter.model.segment import SourceBackedSegment, segment_id


def test_segment_id_is_12_hex() -> None:
    sid = segment_id(page=3, bbox=[10.0, 20.0, 110.0, 40.0], text="Cláusula 1")
    assert len(sid) == 12
    int(sid, 16)


def test_segment_id_is_deterministic() -> None:
    args = dict(page=3, bbox=[10.1, 20.2, 110.3, 40.4], text="hello")
    assert segment_id(**args) == segment_id(**args)


def test_segment_id_is_stable_across_candidates_with_slightly_different_geometry() -> None:
    # Sub-pixel jitter between two extraction techniques must not change the id
    # (bbox is rounded before hashing).
    a = segment_id(page=3, bbox=[10.0, 20.0, 110.0, 40.0], text="Article 4")
    b = segment_id(page=3, bbox=[10.49, 19.51, 110.0, 40.49], text="Article 4")
    assert a == b


def test_segment_id_changes_with_page() -> None:
    assert segment_id(page=3, bbox=[1, 2, 3, 4], text="x") != segment_id(
        page=4, bbox=[1, 2, 3, 4], text="x"
    )


def test_segment_id_changes_with_bbox_beyond_rounding() -> None:
    assert segment_id(page=1, bbox=[10, 20, 110, 40], text="x") != segment_id(
        page=1, bbox=[60, 20, 160, 40], text="x"
    )


def test_segment_id_changes_with_text() -> None:
    assert segment_id(page=1, bbox=[1, 2, 3, 4], text="foo") != segment_id(
        page=1, bbox=[1, 2, 3, 4], text="bar"
    )


def test_segment_id_uses_an_nfc_text_hash() -> None:
    # "é" as one codepoint (NFC) vs "e" + combining acute (NFD) must hash the same.
    nfc = "café"
    nfd = unicodedata.normalize("NFD", nfc)
    assert nfc != nfd  # different byte sequences
    assert segment_id(page=1, bbox=[1, 2, 3, 4], text=nfc) == segment_id(
        page=1, bbox=[1, 2, 3, 4], text=nfd
    )


def test_segment_id_matches_the_documented_sha1_construction() -> None:
    page, bbox, text = 3, [10.0, 20.0, 110.0, 40.0], "Cláusula"
    nfc_hash = hashlib.sha1(unicodedata.normalize("NFC", text).encode("utf-8")).hexdigest()
    rounded = [round(v) for v in bbox]
    expect = hashlib.sha1(f"{page}:{rounded}:{nfc_hash}".encode()).hexdigest()[:12]
    assert segment_id(page=page, bbox=bbox, text=text) == expect


def test_source_backed_segment_keeps_text_verbatim() -> None:
    seg = SourceBackedSegment(
        segment_id="abc123abc123",
        text="  spaced  value  ",
        source={
            "physical_page": 1,
            "bbox": [1.0, 2.0, 3.0, 4.0],
            "origin_kind": "native_text",
            "extraction_technique": "pdfplumber",
            "ocr_languages": [],
            "ocr_confidence": None,
        },
        reading_order_index=0,
        structural_hints=[],
    )
    assert seg.text == "  spaced  value  "  # never normalized
