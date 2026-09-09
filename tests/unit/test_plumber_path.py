"""T047 — failing-first tests for the pdfplumber extraction path B adapter
(GREEN owner: **T047**, ``src/solari_converter/extract/plumber_path.py``).

Frozen behaviour under test (plan.md ledger; FR-060/FR-060a/FR-060b):

* literal fidelity — a line's text is the plain left-to-right join of its words'
  exact ``pdfplumber`` text, with no dehyphenation, no paragraph merging, no case
  changes;
* geometry — bbox is ``(x0, top, x1, bottom)``, pdfplumber's top-left-origin
  convention, matching path A's convention (T046) rather than PDF-native bottom-left;
* reading order — a **geometric** candidate: x-gap column detection (left-to-right
  columns), top-to-bottom within a column;
* structural hints — pdfplumber's table finder only, carried as evidence, never
  applied;
* independence — this module imports neither ``extract/docling_path`` nor
  ``extract/ocr_path`` nor ``extract/native_reliability``.

Most tests here run against literal ``pdfplumber``-shaped word dicts (fast, precise
control over geometry) or against real ``reportlab``-built PDFs via
``tests/fixtures/build_fixtures.py`` (no ML, so real pdfplumber is cheap to run).
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # tests/ for `fixtures`

MODULE_PATH = (
    Path(__file__).resolve().parents[2] / "src" / "solari_converter" / "extract" / "plumber_path.py"
)


def _mod():
    import solari_converter.extract.plumber_path as plumber_path  # GREEN owner: T047

    return plumber_path


def _w(text: str, x0: float, top: float, x1: float, bottom: float) -> dict:
    """A minimal pdfplumber-shaped word dict — only the keys this adapter reads."""
    return {"text": text, "x0": x0, "top": top, "x1": x1, "bottom": bottom}


def _envelope(**overrides) -> dict:
    base = {
        "run_id": "a" * 16,
        "tool_version": "0.1.0",
        "source_pdf": "doc.pdf",
        "source_sha256": "b" * 64,
        "page_selection": "all",
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------------------
# Independence — no import of a sibling extraction path (M2 / SC-024)
# ---------------------------------------------------------------------------------------


def test_module_imports_no_sibling_extraction_path_or_reconciliation() -> None:
    tree = ast.parse(MODULE_PATH.read_text())
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    forbidden = ("docling_path", "ocr_path", "native_reliability", "reconcile")
    for name in imported:
        for bad in forbidden:
            assert bad not in name, f"plumber_path.py must not import {name!r} ({bad!r})"


# ---------------------------------------------------------------------------------------
# Geometry / bbox convention
# ---------------------------------------------------------------------------------------


def test_word_bbox_is_x0_top_x1_bottom() -> None:
    m = _mod()
    word = _w("hi", 10.0, 20.0, 30.0, 40.0)
    assert m._word_bbox(word) == (10.0, 20.0, 30.0, 40.0)


def test_line_bbox_is_union_of_word_bboxes() -> None:
    m = _mod()
    words = [_w("Hello", 10.0, 20.0, 40.0, 32.0), _w("world", 45.0, 21.0, 80.0, 33.0)]
    bbox = m._line_bbox(words)
    assert bbox == (10.0, 20.0, 80.0, 33.0)


# ---------------------------------------------------------------------------------------
# Row-band (line) grouping
# ---------------------------------------------------------------------------------------


def test_words_on_the_same_top_form_one_row_band() -> None:
    m = _mod()
    words = [_w("A", 10, 100, 20, 112), _w("B", 25, 100, 35, 112), _w("C", 40, 101, 50, 113)]
    bands = m._group_into_row_bands(words)
    assert len(bands) == 1
    assert {w["text"] for w in bands[0]} == {"A", "B", "C"}


def test_words_on_different_tops_form_separate_row_bands() -> None:
    m = _mod()
    words = [_w("Line1", 10, 100, 50, 112), _w("Line2", 10, 130, 50, 142)]
    bands = m._group_into_row_bands(words)
    assert len(bands) == 2


def test_row_bands_are_ordered_top_to_bottom() -> None:
    m = _mod()
    words = [_w("Second", 10, 130, 50, 142), _w("First", 10, 100, 50, 112)]
    bands = m._group_into_row_bands(words)
    assert [b[0]["text"] for b in bands] == ["First", "Second"]


# ---------------------------------------------------------------------------------------
# Column detection (x-gap)
# ---------------------------------------------------------------------------------------


def _two_column_words(n_rows: int = 6) -> list[dict]:
    words = []
    for i in range(n_rows):
        top = 100 + i * 20
        words.append(_w(f"L{i}", 60, top, 120, top + 12))
        words.append(_w(f"R{i}", 330, top, 400, top + 12))
    return words


def test_wide_persistent_gap_is_detected_as_two_columns() -> None:
    m = _mod()
    words = _two_column_words()
    bands = m._group_into_row_bands(words)
    columns = m._detect_column_ranges(words, bands, page_width=612.0)
    assert len(columns) == 2
    assert columns[0][1] <= columns[1][0]  # left column ends before right column starts


def test_single_line_sidebar_gap_is_not_treated_as_a_column() -> None:
    """A running-header pattern — one line with a left title and a far-right date —
    must not be mistaken for a two-column layout the rest of the page doesn't have."""
    m = _mod()
    words = [_w("Title", 60, 40, 150, 52), _w("Rev. 2026-09", 480, 40, 560, 52)]
    # a single-column body below, spanning the full width across many lines
    for i in range(8):
        top = 80 + i * 14
        words.append(_w(f"Body{i}", 60, top, 560, top + 12))
    bands = m._group_into_row_bands(words)
    columns = m._detect_column_ranges(words, bands, page_width=612.0)
    assert len(columns) == 1


def test_no_gap_yields_a_single_column() -> None:
    m = _mod()
    words = [_w(f"word{i}", 60 + i * 20, 100, 75 + i * 20, 112) for i in range(10)]
    bands = m._group_into_row_bands(words)
    columns = m._detect_column_ranges(words, bands, page_width=612.0)
    assert len(columns) == 1


def test_tiny_intra_word_gaps_do_not_fragment_a_single_column() -> None:
    """Repeated identical short lines (e.g. a bulleted list) leave small residual gaps
    in the whole-page x-profile between words -- those must never be mistaken for
    column boundaries."""
    m = _mod()
    words = []
    for i in range(10):
        top = 100 + i * 14
        words.append(_w("Item", 60, top, 90, top + 12))
        words.append(_w("value", 95, top, 130, top + 12))  # 5pt gap, repeats every row
    bands = m._group_into_row_bands(words)
    columns = m._detect_column_ranges(words, bands, page_width=612.0)
    assert len(columns) == 1


# ---------------------------------------------------------------------------------------
# Reading order — columns left-to-right, top-to-bottom within column
# ---------------------------------------------------------------------------------------


def test_reading_order_visits_left_column_fully_before_right_column() -> None:
    m = _mod()
    words = _two_column_words(n_rows=4)
    segments, order = m._segments_and_order_for_page(words, page_no=1, page_width=612.0)
    texts_in_order = []
    for sid in order:
        seg = next(s for s in segments if s.segment_id == sid)
        texts_in_order.append(seg.text)
    left_texts = [t for t in texts_in_order if t.startswith("L")]
    right_texts = [t for t in texts_in_order if t.startswith("R")]
    assert texts_in_order == left_texts + right_texts
    assert left_texts == ["L0", "L1", "L2", "L3"]
    assert right_texts == ["R0", "R1", "R2", "R3"]


def test_reading_order_index_matches_position_in_candidate_reading_order() -> None:
    m = _mod()
    words = _two_column_words(n_rows=3)
    segments, order = m._segments_and_order_for_page(words, page_no=1, page_width=612.0)
    for idx, sid in enumerate(order):
        seg = next(s for s in segments if s.segment_id == sid)
        assert seg.reading_order_index == idx


def test_single_column_reading_order_is_top_to_bottom() -> None:
    m = _mod()
    words = [_w(f"line{i}", 60, 100 + i * 14, 200, 112 + i * 14) for i in range(5)]
    segments, order = m._segments_and_order_for_page(words, page_no=1, page_width=612.0)
    texts_in_order = [next(s for s in segments if s.segment_id == sid).text for sid in order]
    assert texts_in_order == ["line0", "line1", "line2", "line3", "line4"]


# ---------------------------------------------------------------------------------------
# Literal fidelity
# ---------------------------------------------------------------------------------------


def test_line_text_is_plain_left_to_right_join_no_transformation() -> None:
    m = _mod()
    words = [_w("Café", 10, 100, 40, 112), _w("naïve", 45, 100, 80, 112)]
    segments, _ = m._segments_and_order_for_page(words, page_no=1, page_width=612.0)
    assert segments[0].text == "Café naïve"


def test_hyphenated_line_final_word_is_not_repaired() -> None:
    m = _mod()
    words = [_w("algo-", 10, 100, 40, 112)]
    segments, _ = m._segments_and_order_for_page(words, page_no=1, page_width=612.0)
    assert segments[0].text == "algo-"


def test_no_paragraph_merging_across_lines() -> None:
    m = _mod()
    words = [
        _w("First", 10, 100, 40, 112),
        _w("line.", 45, 100, 75, 112),
        _w("Second", 10, 120, 50, 132),
        _w("line.", 55, 120, 85, 132),
    ]
    segments, _ = m._segments_and_order_for_page(words, page_no=1, page_width=612.0)
    texts = [s.text for s in segments]
    assert texts == ["First line.", "Second line."]
    assert "First line. Second line." not in texts


# ---------------------------------------------------------------------------------------
# Segment / provenance shape
# ---------------------------------------------------------------------------------------


def test_segment_source_ref_is_native_text_pdfplumber() -> None:
    m = _mod()
    words = [_w("hi", 10, 100, 20, 112)]
    segments, _ = m._segments_and_order_for_page(words, page_no=3, page_width=612.0)
    seg = segments[0]
    assert seg.source.physical_page == 3
    assert seg.source.origin_kind == "native_text"
    assert seg.source.extraction_technique == "pdfplumber"
    assert seg.source.ocr_languages == []
    assert seg.source.ocr_confidence is None
    assert seg.structural_hints == []


def test_segment_id_deterministic_and_geometry_sensitive() -> None:
    m = _mod()
    words_a = [_w("same", 10, 100, 40, 112)]
    words_b = [_w("same", 10, 100, 40, 112)]
    seg_a, _ = m._segments_and_order_for_page(words_a, page_no=1, page_width=612.0)
    seg_b, _ = m._segments_and_order_for_page(words_b, page_no=1, page_width=612.0)
    assert seg_a[0].segment_id == seg_b[0].segment_id

    words_c = [_w("same", 99, 200, 130, 212)]
    seg_c, _ = m._segments_and_order_for_page(words_c, page_no=1, page_width=612.0)
    assert seg_c[0].segment_id != seg_a[0].segment_id


# ---------------------------------------------------------------------------------------
# Structural hints — table detector only, carried not applied
# ---------------------------------------------------------------------------------------


def test_table_hint_kind_and_source_technique() -> None:
    m = _mod()
    words = [_w("r0c0", 80, 210, 110, 222)]
    table_bbox = (72.0, 172.8, 374.4, 259.2)
    segments, _ = m._segments_and_order_for_page(words, page_no=1, page_width=612.0)
    m._attach_table_hints(segments, [table_bbox])
    seg = segments[0]
    assert any(h.kind == "table" for h in seg.structural_hints)
    assert seg.structural_hints[0].source_technique == "pdfplumber"


def test_segment_outside_table_bbox_gets_no_table_hint() -> None:
    m = _mod()
    words = [_w("outside", 500, 500, 550, 512)]
    table_bbox = (72.0, 172.8, 374.4, 259.2)
    segments, _ = m._segments_and_order_for_page(words, page_no=1, page_width=612.0)
    m._attach_table_hints(segments, [table_bbox])
    assert segments[0].structural_hints == []


# ---------------------------------------------------------------------------------------
# Empty page
# ---------------------------------------------------------------------------------------


def test_empty_page_yields_no_segments() -> None:
    m = _mod()
    segments, order = m._segments_and_order_for_page([], page_no=1, page_width=612.0)
    assert segments == []
    assert order == []


# ---------------------------------------------------------------------------------------
# Real-fixture integration (real pdfplumber, no ML — cheap to run for real)
# ---------------------------------------------------------------------------------------


@pytest.fixture
def fixtures_dir(tmp_path: Path) -> Path:
    from fixtures.build_fixtures import build_agreement, build_native_text, build_two_column

    build_native_text(tmp_path)
    build_two_column(tmp_path)
    build_agreement(tmp_path)
    return tmp_path


def test_extract_native_text_pdf_end_to_end(fixtures_dir: Path) -> None:
    from solari_converter.pdf.loader import load_pdf

    m = _mod()
    path = m.PlumberExtractionPath()
    with load_pdf(fixtures_dir / "native_text.pdf") as source:
        candidate = path.extract(
            source, envelope=_envelope(source_pdf=str(fixtures_dir / "native_text.pdf"))
        )
    assert candidate.technique == "pdfplumber"
    assert candidate.status == "ok"
    assert candidate.segments
    texts = [s.text for s in candidate.segments]
    assert any("Native Text Document" in t for t in texts)
    assert candidate.reading_order.technique == "pdfplumber"
    assert len(candidate.reading_order.order) == len(candidate.segments)


def test_extract_two_column_pdf_orders_left_before_right(fixtures_dir: Path) -> None:
    from solari_converter.pdf.loader import load_pdf

    m = _mod()
    path = m.PlumberExtractionPath()
    with load_pdf(fixtures_dir / "two_column.pdf") as source:
        candidate = path.extract(
            source, envelope=_envelope(source_pdf=str(fixtures_dir / "two_column.pdf"))
        )
    order = candidate.reading_order.order
    seg_by_id = {s.segment_id: s for s in candidate.segments}
    ordered_texts = [
        seg_by_id[sid].text for sid in order if seg_by_id[sid].source.physical_page == 1
    ]
    left_positions = [i for i, t in enumerate(ordered_texts) if "Left column" in t]
    right_positions = [i for i, t in enumerate(ordered_texts) if "Right column" in t]
    assert left_positions and right_positions
    assert max(left_positions) < min(right_positions)


def test_extract_agreement_pdf_page1_single_column_no_false_split(fixtures_dir: Path) -> None:
    """Regression for the empirically-observed running-header artifact: a title +
    far-right revision date on one line must not fragment page 1 into columns."""
    from solari_converter.pdf.loader import load_pdf

    m = _mod()
    path = m.PlumberExtractionPath()
    with load_pdf(fixtures_dir / "agreement.pdf") as source:
        candidate = path.extract(
            source, envelope=_envelope(source_pdf=str(fixtures_dir / "agreement.pdf"))
        )
    page1_segments = [s for s in candidate.segments if s.source.physical_page == 1]
    order = candidate.reading_order.order
    page1_order = [sid for sid in order if sid in {s.segment_id for s in page1_segments}]
    seg_by_id = {s.segment_id: s for s in page1_segments}
    tops = [seg_by_id[sid].source.bbox[1] for sid in page1_order]
    assert tops == sorted(tops), "page 1 must read strictly top-to-bottom (single column)"


def test_extract_never_imports_ocr_or_docling_state(fixtures_dir: Path) -> None:
    """No network / no model — plain proof this path never touches path A/C machinery."""
    from solari_converter.pdf.loader import load_pdf

    m = _mod()
    path = m.PlumberExtractionPath()
    with load_pdf(fixtures_dir / "native_text.pdf") as source:
        candidate = path.extract(
            source, envelope=_envelope(source_pdf=str(fixtures_dir / "native_text.pdf"))
        )
    assert candidate.page_ocr == []
