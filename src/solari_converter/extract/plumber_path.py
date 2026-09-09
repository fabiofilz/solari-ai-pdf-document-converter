"""pdfplumber extraction path B adapter (T047).

Path B (plan.md ledger; FR-060/FR-060a) processes the **original PDF directly** through
``pdfplumber`` and produces one ``ExtractionCandidate`` — the deterministic geometric
ground truth for reading-order reconciliation and segment alignment. It never touches
Docling (path A) or OCR (path C): each independent extraction path reads only the
original source (``pdf/loader.PdfSource``).

**Segment granularity**: one segment per visual line (words sharing a `top`
coordinate), matching path A's per-line granularity (``textline_cells``) so later
alignment operates on comparable units. A line's text is the plain left-to-right join
of its words' exact ``pdfplumber`` text — no dehyphenation, no paragraph merging
across lines, no case changes, no Markdown.

**Geometry**: bbox is ``(x0, top, x1, bottom)`` — pdfplumber's own top-left-origin
convention (``top``/``bottom`` measured from the page top), matching path A's
convention (T046's ``docling_path.py`` docstring) rather than the PDF-native
bottom-left space pdfplumber also exposes via ``y0``/``y1``. pdfplumber normalizes
these coordinates for a rotated page's ``/Rotate`` internally (``Page.rotation`` is
applied to ``page.width``/``page.height`` and every word/char bbox), so no separate
rotation handling is needed here.

**Reading order — geometric, evidence only** (FR-060b, never authoritative): x-gap
column detection over the whole page's word x-profile, confirmed only when the gap is
wide (≥2% of page width) **and** persists across a robust minimum number of distinct
lines on each side (empirically required: a single running-header line with a
far-right date/page-number must not be mistaken for a two-column layout the rest of
the page doesn't have — see ``test_single_line_sidebar_gap_is_not_treated_as_a_column``
and the real-fixture regression against ``agreement.pdf``). Confirmed columns are
visited left-to-right; lines within a column top-to-bottom.

**Structural hints — table detector only** (FR-061c): ``page.find_tables()`` region
bboxes are carried as ``kind="table"`` evidence on every line whose bbox falls inside
one, never applied (no row/column reconstruction here — later transform-stage
concern, matching the same conservative scope choice T046 made for Docling's
TableFormer output).

**Independence** (M2 / SC-024): this module imports neither ``extract/docling_path``,
``extract/ocr_path``, nor ``extract/native_reliability``, nor anything under
``reconcile/``.
"""

from __future__ import annotations

from typing import Any

from solari_converter.model.candidate import CandidateReadingOrder, ExtractionCandidate
from solari_converter.model.provenance import SourceRef
from solari_converter.model.segment import SourceBackedSegment, StructuralHint, segment_id

from .base import EnvelopeFields

__all__ = ["TECHNIQUE", "PlumberExtractionPath"]

TECHNIQUE = "pdfplumber"

# Column-gap detection thresholds (plan.md ledger — "deterministic geometric ground
# truth"; empirically calibrated against tests/fixtures/build_fixtures.py, notably
# `two_column.pdf` (real gap: 3.6% of page width, persists on all lines) versus
# `agreement.pdf` page 1's running-header artifact (a much wider gap, but present on
# only one line)).
_MIN_GAP_WIDTH_RATIO = 0.02  # a candidate gap must be >=2% of page width
_MIN_LINES_PER_SIDE_ABS = 3  # ...and at least 3 distinct lines must have content on
_MIN_LINES_PER_SIDE_RATIO = 0.15  # each side, or 15% of the page's lines, whichever is larger

# Row-band (visual line) clustering: two words are on the same line when their `top`
# values differ by less than this fraction of the taller word's own height.
_LINE_TOLERANCE_RATIO = 0.6


def _word_bbox(word: dict) -> tuple[float, float, float, float]:
    return (float(word["x0"]), float(word["top"]), float(word["x1"]), float(word["bottom"]))


def _line_bbox(words: list[dict]) -> tuple[float, float, float, float]:
    x0 = min(float(w["x0"]) for w in words)
    top = min(float(w["top"]) for w in words)
    x1 = max(float(w["x1"]) for w in words)
    bottom = max(float(w["bottom"]) for w in words)
    return (x0, top, x1, bottom)


def _group_into_row_bands(words: list[dict]) -> list[list[dict]]:
    """Cluster words into visual lines by `top` proximity, ordered top-to-bottom.
    Deterministic: words are sorted by `top`; a new band starts whenever the gap to
    the band's running-average `top` exceeds a font-height-relative tolerance."""
    if not words:
        return []
    ordered = sorted(words, key=lambda w: float(w["top"]))
    bands: list[list[dict]] = [[ordered[0]]]
    band_top_sum = float(ordered[0]["top"])
    for word in ordered[1:]:
        band = bands[-1]
        band_avg_top = band_top_sum / len(band)
        height = max(float(w["bottom"]) - float(w["top"]) for w in band + [word])
        tolerance = max(1.0, height * _LINE_TOLERANCE_RATIO)
        if abs(float(word["top"]) - band_avg_top) <= tolerance:
            band.append(word)
            band_top_sum += float(word["top"])
        else:
            bands.append([word])
            band_top_sum = float(word["top"])
    for band in bands:
        band.sort(key=lambda w: float(w["x0"]))
    return bands


def _merge_intervals(intervals: list[tuple[float, float]]) -> list[tuple[float, float]]:
    merged: list[list[float]] = []
    for x0, x1 in sorted(intervals):
        if merged and x0 <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], x1)
        else:
            merged.append([x0, x1])
    return [(a, b) for a, b in merged]


def _detect_column_ranges(
    words: list[dict], row_bands: list[list[dict]], *, page_width: float
) -> list[tuple[float, float]]:
    """Confirmed left-to-right column x-ranges. Returns a single page-spanning range
    when no gap survives the persistence check (the common single-column case)."""
    if not words:
        return [(0.0, page_width)]

    occupied = _merge_intervals([(float(w["x0"]), float(w["x1"])) for w in words])
    min_gap = _MIN_GAP_WIDTH_RATIO * page_width
    min_lines = max(_MIN_LINES_PER_SIDE_ABS, _MIN_LINES_PER_SIDE_RATIO * len(row_bands))

    confirmed_splits: list[float] = []  # x-coordinates where a column boundary is confirmed
    for i in range(len(occupied) - 1):
        gap_start, gap_end = occupied[i][1], occupied[i + 1][0]
        if gap_end - gap_start < min_gap:
            continue
        lines_with_left_content = sum(
            1 for band in row_bands if any(float(w["x0"]) < gap_start for w in band)
        )
        lines_with_right_content = sum(
            1 for band in row_bands if any(float(w["x1"]) > gap_end for w in band)
        )
        if lines_with_left_content >= min_lines and lines_with_right_content >= min_lines:
            confirmed_splits.append((gap_start + gap_end) / 2.0)

    if not confirmed_splits:
        return [(0.0, page_width)]

    boundaries = [0.0, *confirmed_splits, page_width]
    return [(boundaries[i], boundaries[i + 1]) for i in range(len(boundaries) - 1)]


def _assign_column(word: dict, columns: list[tuple[float, float]]) -> int:
    center = (float(word["x0"]) + float(word["x1"])) / 2.0
    for idx, (lo, hi) in enumerate(columns):
        if lo <= center < hi:
            return idx
    return len(columns) - 1  # last column catches the right edge (center == page_width)


def _build_segment(line_words: list[dict], *, page_no: int) -> SourceBackedSegment:
    ordered = sorted(line_words, key=lambda w: float(w["x0"]))
    text = " ".join(str(w["text"]) for w in ordered)
    bbox = _line_bbox(ordered)
    sid = segment_id(page=page_no, bbox=bbox, text=text)
    return SourceBackedSegment(
        segment_id=sid,
        text=text,
        source=SourceRef(
            physical_page=page_no,
            bbox=bbox,
            origin_kind="native_text",
            extraction_technique=TECHNIQUE,
            ocr_languages=[],
            ocr_confidence=None,
        ),
        reading_order_index=0,  # patched once the page's/candidate's order is known
        structural_hints=[],
    )


def _segments_and_order_for_page(
    words: list[dict], *, page_no: int, page_width: float
) -> tuple[list[SourceBackedSegment], list[str]]:
    """Pure per-page mapping: pdfplumber word dicts -> (segments, reading_order_ids).
    No pdfplumber ``Page`` object is required — every field read is a plain dict key,
    so this is exercised directly against literal word dicts in unit tests."""
    if not words:
        return [], []

    row_bands = _group_into_row_bands(words)
    columns = _detect_column_ranges(words, row_bands, page_width=page_width)

    # (column_index, band_index) -> words in that column within that row band
    cells: dict[tuple[int, int], list[dict]] = {}
    band_tops: dict[int, float] = {}
    for band_idx, band in enumerate(row_bands):
        band_tops[band_idx] = min(float(w["top"]) for w in band)
        for word in band:
            key = (_assign_column(word, columns), band_idx)
            cells.setdefault(key, []).append(word)

    segments: list[SourceBackedSegment] = []
    segment_by_key: dict[tuple[int, int], SourceBackedSegment] = {}
    for key, line_words in cells.items():
        segment = _build_segment(line_words, page_no=page_no)
        segments.append(segment)
        segment_by_key[key] = segment

    ordered_keys = sorted(cells.keys(), key=lambda key: (key[0], band_tops[key[1]]))
    order = [segment_by_key[key].segment_id for key in ordered_keys]

    index_by_id = {sid: idx for idx, sid in enumerate(order)}
    for segment in segments:
        segment.reading_order_index = index_by_id[segment.segment_id]

    return segments, order


def _attach_table_hints(
    segments: list[SourceBackedSegment], table_bboxes: list[tuple[float, float, float, float]]
) -> None:
    """Carry pdfplumber's table-region evidence onto every segment whose bbox falls
    inside a detected table — evidence only, never applied (FR-061c)."""
    for segment in segments:
        sx0, stop, sx1, sbottom = segment.source.bbox  # type: ignore[misc]
        for tx0, ttop, tx1, tbottom in table_bboxes:
            inside = (
                sx0 >= tx0 - 0.5
                and sx1 <= tx1 + 0.5
                and stop >= ttop - 0.5
                and sbottom <= tbottom + 0.5
            )
            if inside:
                segment.structural_hints.append(
                    StructuralHint(
                        kind="table",
                        source_technique=TECHNIQUE,
                        payload={"table_bbox": [tx0, ttop, tx1, tbottom]},
                    )
                )
                break


class PlumberExtractionPath:
    """Path B: pdfplumber, operating directly on the original source PDF
    (``PdfSource`` — never another path's output; FR-060). Implements the
    ``ExtractionPath`` protocol from ``extract/base.py``.

    No import of ``extract/docling_path``, ``extract/ocr_path``,
    ``extract/native_reliability``, or anything under ``reconcile/`` anywhere in this
    module (verified by
    ``test_module_imports_no_sibling_extraction_path_or_reconciliation``).
    """

    technique = TECHNIQUE

    def extract(self, source: Any, *, envelope: EnvelopeFields) -> ExtractionCandidate:
        """Read ``source`` (a ``pdf/loader.PdfSource`` handle) directly and return
        path B's candidate. May raise; ``extract/base.py``'s ``run_path()`` converts
        any raise into a ``status="failed"`` candidate (FR-060 edge case)."""
        page_count = source.page_count
        requested = _requested_pages(envelope.get("page_selection"), page_count)
        pages = requested if requested is not None else set(range(1, page_count + 1))

        segments: list[SourceBackedSegment] = []
        order: list[str] = []
        pages_covered: list[int] = []

        for page_no in sorted(pages):
            plumber_page = source.plumber_page(page_no)
            words = plumber_page.extract_words()
            page_segments, page_order = _segments_and_order_for_page(
                words, page_no=page_no, page_width=float(plumber_page.width)
            )
            if page_segments:
                tables = [tuple(t.bbox) for t in plumber_page.find_tables()]
                if tables:
                    _attach_table_hints(page_segments, tables)
            segments.extend(page_segments)
            order.extend(page_order)
            pages_covered.append(page_no)

        index_by_id = {sid: idx for idx, sid in enumerate(order)}
        for segment in segments:
            segment.reading_order_index = index_by_id[segment.segment_id]

        env = {
            k: envelope[k]
            for k in ("run_id", "tool_version", "source_pdf", "source_sha256", "page_selection")
        }
        return ExtractionCandidate(
            **env,
            technique=TECHNIQUE,
            status="ok",
            status_detail=None,
            segments=segments,
            reading_order=CandidateReadingOrder(technique=TECHNIQUE, order=order),
            pages_covered=pages_covered,
        )


def _requested_pages(page_selection_token: str | None, page_count: int) -> set[int] | None:
    """Decode the already-validated canonical page-selection token (research §14 /
    ``model/page_selection.py``'s ``normalized_token()``) into a concrete page set.
    Mirrors ``extract/docling_path.py``'s identical helper — this adapter does not
    re-validate the selection, only decodes an already-trusted, frozen wire format."""
    if not page_selection_token or page_selection_token == "all":
        return None
    pages: set[int] = set()
    for part in page_selection_token.split("_"):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            lo_s, _, hi_s = part.partition("-")
            pages.update(range(int(lo_s), int(hi_s) + 1))
        else:
            pages.add(int(part))
    resolved = {p for p in pages if 1 <= p <= page_count}
    return resolved or None
