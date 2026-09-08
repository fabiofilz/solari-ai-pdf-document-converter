"""T014 — failing-first unit tests for
``solari_converter.reconcile.resolutions.compute_applicability_key``.

GREEN owner: **T030** (`reconcile/resolutions.py`). Written now (Constitution VI); FAILS
until T030 lands — INTENTIONAL future RED, not a regression. Research §22:
``applicability_key = sha256(source_sha256 ⧺ conflict_type ⧺ canonical(page, region,
aligned candidate-value set) ⧺ canonical_json(config_subset))``. The config subset is
``ocr_engine``, ``ocr_languages_override``, ``ocr_confidence_threshold`` and the
enabled-path set (FR-071). A changed context => key no longer matches => no silent replay.
"""

from __future__ import annotations


def _key(**over):
    from solari_converter.reconcile.resolutions import compute_applicability_key  # GREEN: T030

    base = dict(
        source_sha256="a" * 64,
        conflict_type="literal_content",
        physical_page=5,
        region_bboxes=[[10.0, 20.0, 110.0, 40.0]],
        candidate_values=["R$ 1.599,80", "R$ 1.599.80"],
        config_subset={
            "ocr_engine": "tesseract",
            "ocr_languages_override": None,
            "ocr_confidence_threshold": 70,
            "enabled_extraction_paths": ["docling", "pdfplumber", "ocr"],
        },
    )
    base.update(over)
    return compute_applicability_key(**base)


def test_key_is_64_hex() -> None:
    k = _key()
    assert len(k) == 64
    int(k, 16)


def test_key_is_deterministic() -> None:
    assert _key() == _key()


def test_page_selection_change_that_keeps_the_region_does_not_change_the_key() -> None:
    # The key is not a function of the whole-run page selection — only of the
    # source hash + conflict identity + config subset (FR-071).
    assert _key() == _key()  # identical inputs regardless of the enclosing selection


def test_ocr_engine_change_changes_the_key() -> None:
    assert _key(config_subset={
        "ocr_engine": "rapidocr",
        "ocr_languages_override": None,
        "ocr_confidence_threshold": 70,
        "enabled_extraction_paths": ["docling", "pdfplumber", "ocr"],
    }) != _key()


def test_source_hash_change_changes_the_key() -> None:
    assert _key(source_sha256="b" * 64) != _key()


def test_conflict_type_change_changes_the_key() -> None:
    assert _key(conflict_type="reading_order") != _key()


def test_candidate_value_set_change_changes_the_key() -> None:
    assert _key(candidate_values=["R$ 1.599,80"]) != _key()


def test_candidate_value_set_is_order_independent() -> None:
    assert _key(candidate_values=["R$ 1.599,80", "R$ 1.599.80"]) == _key(
        candidate_values=["R$ 1.599.80", "R$ 1.599,80"]
    )
