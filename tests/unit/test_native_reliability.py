"""T048 — failing-first, **scored** tests for the native-text reliability classifier
(GREEN owner: **T049**, ``src/solari_converter/extract/native_reliability.py``).

M2 / research §24: the classifier is an **extraction-routing / evidence** component,
never a fourth extraction path. It reads low-level native-text evidence **directly
from the source PDF via `pdf/loader`** (raw pdfplumber primitives + a pypdfium2
raster on the source handle) — it never accepts or imports an ``ExtractionCandidate``,
nor ``extract/plumber_path`` / ``extract/docling_path``.

Scoring, per the frozen fixture corpus (``tests/fixtures/manifests.py``,
``EXPECTED_PAGE_CLASS`` / ``EXPECTED_OCR_TRIGGER_REGIONS``):

* ``native_text.pdf`` (healthy, fully selectable) and ``scanned.pdf`` (image-only)
  are the **unambiguous** cases — 100% required, individually asserted;
* ``missing_content_layer.pdf`` (severe native-text gap), ``garbled_layer.pdf``
  (one mojibake region), and ``hybrid.pdf`` (one image-only region) are scored as an
  **aggregate accuracy** over the 5-fixture set (coarse boxes — region overlap is
  checked, not per-pixel).
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # tests/ for `fixtures`

MODULE_PATH = (
    Path(__file__).resolve().parents[2]
    / "src"
    / "solari_converter"
    / "extract"
    / "native_reliability.py"
)


def _mod():
    import solari_converter.extract.native_reliability as native_reliability  # GREEN owner: T049

    return native_reliability


# ---------------------------------------------------------------------------------------
# Independence — routing/evidence only, never an extraction path (M2)
# ---------------------------------------------------------------------------------------


def test_module_imports_no_extraction_path_or_candidate_or_reconciliation() -> None:
    tree = ast.parse(MODULE_PATH.read_text())
    imported_modules: set[str] = set()
    imported_names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_modules.add(node.module)
            imported_names.update(alias.name for alias in node.names)
    forbidden = ("docling_path", "plumber_path", "ocr_path", "reconcile")
    for name in imported_modules:
        for bad in forbidden:
            assert bad not in name, f"native_reliability.py must not import {name!r} ({bad!r})"
    # PageClass (a shared enum this classifier legitimately produces, per FR-024b) is
    # fine; the ExtractionCandidate model itself -- the thing this module must never
    # accept, construct, or depend on as authoritative input -- must never be imported.
    assert "ExtractionCandidate" not in imported_names


def test_classify_page_signature_takes_a_pdf_source_not_a_candidate() -> None:
    """The classifier's entry point takes a `pdf/loader` handle -- never a candidate
    object, never a list of segments."""
    import inspect

    m = _mod()
    sig = inspect.signature(m.NativeReliabilityClassifier.classify_page)
    params = list(sig.parameters)
    assert "candidate" not in params
    assert "segments" not in params


# ---------------------------------------------------------------------------------------
# Pure per-band decision logic (no PDF I/O -- literal numeric evidence)
# ---------------------------------------------------------------------------------------


def _band(*, ink_ratio=0.0, char_count=0, native_area_ratio=0.0, gibberish_matches=0):
    m = _mod()
    return m.BandEvidence(
        index=0,
        bbox=(0.0, 0.0, 612.0, 66.0),
        ink_ratio=ink_ratio,
        char_count=char_count,
        native_area_ratio=native_area_ratio,
        gibberish_matches=gibberish_matches,
    )


def test_band_with_no_ink_and_no_text_is_blank() -> None:
    m = _mod()
    decision = m._classify_band(_band(ink_ratio=0.001, char_count=0), knobs=m.DEFAULT_KNOBS)
    assert decision == "blank"


def test_band_with_ink_and_good_native_coverage_is_ok() -> None:
    m = _mod()
    decision = m._classify_band(
        _band(ink_ratio=0.09, char_count=150, native_area_ratio=0.25, gibberish_matches=0),
        knobs=m.DEFAULT_KNOBS,
    )
    assert decision == "native_ok"


def test_band_with_ink_and_zero_native_text_needs_ocr() -> None:
    m = _mod()
    decision = m._classify_band(
        _band(ink_ratio=0.05, char_count=0, native_area_ratio=0.0, gibberish_matches=0),
        knobs=m.DEFAULT_KNOBS,
    )
    assert decision == "needs_ocr"


def test_band_with_gibberish_needs_ocr_even_with_low_ink() -> None:
    """A mojibake region can render with faint visual ink -- gibberish overrides a
    low ink reading; the text problem is real regardless of how it looks."""
    m = _mod()
    decision = m._classify_band(
        _band(ink_ratio=0.012, char_count=66, native_area_ratio=0.06, gibberish_matches=3),
        knobs=m.DEFAULT_KNOBS,
    )
    assert decision == "needs_ocr"


def test_band_with_invisible_text_and_zero_ink_is_harmless() -> None:
    """Text present but literally no visible ink (e.g. a stray fragment) -- nothing
    to recover, never flagged."""
    m = _mod()
    decision = m._classify_band(
        _band(ink_ratio=0.0, char_count=8, native_area_ratio=0.01, gibberish_matches=0),
        knobs=m.DEFAULT_KNOBS,
    )
    assert decision != "needs_ocr"


def test_band_with_severe_undercoverage_needs_ocr() -> None:
    m = _mod()
    decision = m._classify_band(
        _band(ink_ratio=0.08, char_count=2, native_area_ratio=0.001, gibberish_matches=0),
        knobs=m.DEFAULT_KNOBS,
    )
    assert decision == "needs_ocr"


# ---------------------------------------------------------------------------------------
# Page-level aggregation (pure)
# ---------------------------------------------------------------------------------------


def test_all_bands_ok_yields_native_text_sufficient() -> None:
    m = _mod()
    bands = [_band(ink_ratio=0.09, char_count=100, native_area_ratio=0.2) for _ in range(3)]
    decisions = ["native_ok"] * 3
    page_class, regions = m._aggregate_page_class(bands, decisions, page=1, knobs=m.DEFAULT_KNOBS)
    assert page_class == m.PageClass.NATIVE_TEXT_SUFFICIENT
    assert regions == []


def test_all_active_bands_needing_ocr_yields_ocr_required() -> None:
    m = _mod()
    bands = [_band(ink_ratio=0.05, char_count=0) for _ in range(2)]
    decisions = ["needs_ocr", "needs_ocr"]
    page_class, regions = m._aggregate_page_class(bands, decisions, page=1, knobs=m.DEFAULT_KNOBS)
    assert page_class == m.PageClass.OCR_REQUIRED
    assert regions  # at least one trigger region reported


def test_mixed_bands_yield_hybrid_with_specific_regions() -> None:
    m = _mod()
    ok_band = _band(ink_ratio=0.09, char_count=150, native_area_ratio=0.25)
    bad_band = _band(ink_ratio=0.05, char_count=0)
    page_class, regions = m._aggregate_page_class(
        [ok_band, bad_band], ["native_ok", "needs_ocr"], page=1, knobs=m.DEFAULT_KNOBS
    )
    assert page_class == m.PageClass.HYBRID_NATIVE_AND_OCR
    assert len(regions) == 1


def test_blank_bands_do_not_affect_the_ratio() -> None:
    m = _mod()
    blank = _band(ink_ratio=0.0, char_count=0)
    ok_band = _band(ink_ratio=0.1, char_count=100, native_area_ratio=0.3)
    page_class, _ = m._aggregate_page_class(
        [blank, blank, ok_band], ["blank", "blank", "native_ok"], page=1, knobs=m.DEFAULT_KNOBS
    )
    assert page_class == m.PageClass.NATIVE_TEXT_SUFFICIENT


def test_no_active_content_defaults_to_native_text_sufficient() -> None:
    m = _mod()
    blank = _band(ink_ratio=0.0, char_count=0)
    page_class, regions = m._aggregate_page_class(
        [blank, blank], ["blank", "blank"], page=1, knobs=m.DEFAULT_KNOBS
    )
    assert page_class == m.PageClass.NATIVE_TEXT_SUFFICIENT
    assert regions == []


# ---------------------------------------------------------------------------------------
# Real fixture corpus — scored (T006 ground truth)
# ---------------------------------------------------------------------------------------


@pytest.fixture
def fixture_paths(tmp_path: Path) -> dict[str, Path]:
    from fixtures.build_fixtures import build_all

    return build_all(tmp_path)


def _classify(path: Path):
    from solari_converter.pdf.loader import load_pdf

    m = _mod()
    classifier = m.NativeReliabilityClassifier()
    with load_pdf(path) as source:
        return classifier.classify_page(source, 1)


def test_unambiguous_native_text_never_triggers_ocr(fixture_paths: dict[str, Path]) -> None:
    m = _mod()
    result = _classify(fixture_paths["native_text.pdf"])
    assert result.page_class == m.PageClass.NATIVE_TEXT_SUFFICIENT
    assert result.ocr_regions == []


def test_unambiguous_scanned_always_triggers_ocr(fixture_paths: dict[str, Path]) -> None:
    m = _mod()
    result = _classify(fixture_paths["scanned.pdf"])
    assert result.page_class == m.PageClass.OCR_REQUIRED
    assert result.ocr_regions


def test_aggregate_accuracy_over_the_scored_fixture_set(fixture_paths: dict[str, Path]) -> None:
    """Aggregate scoring (not single-example) over the full T006 corpus, per T048's
    explicit wording. Requires 100% on the two unambiguous cases plus a strong
    majority match on PageClass across the whole 5-fixture set."""
    from fixtures.manifests import EXPECTED_PAGE_CLASS

    names = [
        "native_text.pdf",
        "scanned.pdf",
        "missing_content_layer.pdf",
        "garbled_layer.pdf",
        "hybrid.pdf",
    ]
    correct = 0
    unambiguous_correct = 0
    for name in names:
        result = _classify(fixture_paths[name])
        expected = EXPECTED_PAGE_CLASS[name][0]
        is_correct = result.page_class.value == expected
        correct += int(is_correct)
        if name in ("native_text.pdf", "scanned.pdf"):
            assert is_correct, f"{name}: expected {expected}, got {result.page_class.value}"
            unambiguous_correct += 1
    accuracy = correct / len(names)
    assert unambiguous_correct == 2
    assert accuracy >= 0.8, f"aggregate PageClass accuracy {accuracy:.2f} below 0.8 floor"


def test_hybrid_pdf_flags_the_image_only_region_not_the_native_paragraph(
    fixture_paths: dict[str, Path],
) -> None:
    result = _classify(fixture_paths["hybrid.pdf"])
    # the upper native-text region (top of the page) must not appear in any flagged
    # region -- only the lower image-only stamp should.
    for region in result.ocr_regions:
        if region.bbox is not None:
            assert region.bbox[1] > 300, "the native-text region must not be flagged"


def test_garbled_layer_pdf_is_hybrid_not_fully_ok_or_fully_ocr(
    fixture_paths: dict[str, Path],
) -> None:
    m = _mod()
    result = _classify(fixture_paths["garbled_layer.pdf"])
    assert result.page_class == m.PageClass.HYBRID_NATIVE_AND_OCR
    assert result.ocr_regions


# ---------------------------------------------------------------------------------------
# Configurability (T049 — knobs via config, not hardcoded)
# ---------------------------------------------------------------------------------------


def test_knobs_are_overridable_not_hardcoded() -> None:
    m = _mod()
    strict = m.NativeReliabilityClassifier(knobs={"blank_ink_ratio_threshold": 0.5})
    assert strict._knobs["blank_ink_ratio_threshold"] == 0.5
    default = m.NativeReliabilityClassifier()
    assert (
        default._knobs["blank_ink_ratio_threshold"] == m.DEFAULT_KNOBS["blank_ink_ratio_threshold"]
    )


def test_config_carries_native_reliability_knobs() -> None:
    """`config.py` (T017) already exposes `native_reliability` + `with_native_reliability`
    -- the T049-tuned knobs plug directly into that existing mechanism."""
    from solari_converter.config import Config

    cfg = Config.resolve()
    tuned = cfg.with_native_reliability({"blank_ink_ratio_threshold": 0.03})
    assert tuned.native_reliability == {"blank_ink_ratio_threshold": 0.03}
