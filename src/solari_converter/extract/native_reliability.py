"""Native-text reliability classifier — extraction-routing / evidence component (T049).

M2 / research §24: this module answers **whether the native text layer is reliable
enough for routing purposes**, per page and per region. It is:

* **not** a fourth extraction path — it produces no ``ExtractionCandidate`` and no
  ``SourceBackedSegment``;
* **not** a reconciler, a semantic validator, or a text-repair engine — it never
  rewrites content, never chooses canonical literal text, and never invokes an LLM;
* **routing evidence only** — its output (a :class:`PageClass` plus a list of
  per-region OCR-trigger recommendations) tells ``extract/ocr_path.py`` (T050) *where*
  OCR is needed. It does not decide what the final text is.

It reads **low-level native-text evidence directly from the source PDF** via
``pdf/loader`` — raw ``pdfplumber`` primitives (``page.chars``) and a raw
``pypdfium2`` raster on the same source handle — never another extraction path's
interpretation. It **must not** accept or import an ``ExtractionCandidate``, nor
``extract/plumber_path`` / ``extract/docling_path`` (verified by
``test_module_imports_no_extraction_path_or_candidate_or_reconciliation``).

**Method** (a page is divided into ``num_bands`` equal horizontal bands — spanning the
full page width, since every corpus fixture that needs region-level routing separates
its problem region vertically, not horizontally):

* **native-text coverage** — the fraction of a band's area covered by native character
  bounding boxes, compared against how much of the band is visually "ink" (rendered
  raster darker than a threshold). A band with real visual content but negligible
  native-character coverage needs OCR (``scanned.pdf``, ``missing_content_layer.pdf``);
* **encoding-gibberish / mojibake detection** — a band's extracted text is scanned for
  the classic UTF-8-decoded-as-Latin-1 fingerprint: ``U+00C2``/``U+00C3`` (the Latin-1
  reading of a UTF-8 2-byte lead byte) immediately followed by a character in
  ``U+0080``-``U+00BF`` (the Latin-1 reading of the UTF-8 continuation byte). This is a
  real, well-established mojibake signature — not exhaustive ToUnicode/CMap
  validation, which is out of scope for a routing-only heuristic. A band with any
  match needs OCR regardless of how much ink it has (``garbled_layer.pdf``);
* a band with negligible ink **and** no native text is inert (``"blank"``) and does
  not affect the page-level decision either way.

Every threshold above is a **knob**, plugged through ``config.py`` (T017)'s existing
``Config.native_reliability`` / ``with_native_reliability`` mechanism — never
hardcoded. The values in :data:`DEFAULT_KNOBS` were tuned against the fixture corpus;
see ``benchmarks/native_reliability/RESULTS.md`` for the tuning record and the T048
scores.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from solari_converter.model.candidate import PageClass

__all__ = [
    "DEFAULT_KNOBS",
    "PageClass",
    "BandEvidence",
    "OcrTriggerRegion",
    "PageReliability",
    "NativeReliabilityClassifier",
]

# Classic UTF-8-decoded-as-Latin-1 mojibake fingerprint: a Latin-1 lead-byte reading
# (U+00C2/U+00C3) immediately followed by a Latin-1 continuation-byte reading
# (U+0080-U+00BF). Written with explicit \u escapes (never a literal embedded byte --
# U+0080 is itself a non-printing C1 control character) so the codepoint range stays
# unambiguous in source.
_MOJIBAKE_RE = re.compile("[\u00c2\u00c3][\u0080-\u00bf]")

# Tuned against tests/fixtures/build_fixtures.py's native-reliability corpus (T048);
# see benchmarks/native_reliability/RESULTS.md for the calibration record.
DEFAULT_KNOBS: dict[str, Any] = {
    "num_bands": 12,
    "raster_scale": 1.0,
    "ink_luma_threshold": 250,  # a rendered pixel below this 0-255 luma counts as "ink"
    "blank_ink_ratio_threshold": 0.02,  # a band below this ink ratio (and no chars) is blank
    "min_coverage_ratio": 0.015,  # native-char-area / band-area floor for "adequate coverage"
    "ocr_required_ratio_threshold": 0.85,  # active-band needs-OCR ratio -> whole-page OCR_REQUIRED
}


@dataclass(frozen=True)
class BandEvidence:
    """One horizontal band's raw evidence — pure data, no PDF I/O. Exposed so the
    decision functions are testable against literal numbers."""

    index: int
    bbox: tuple[float, float, float, float]  # (0, top, page_width, bottom), top-left origin
    ink_ratio: float
    char_count: int
    native_area_ratio: float
    gibberish_matches: int


@dataclass(frozen=True)
class OcrTriggerRegion:
    """One region routing recommends for OCR (path C, T050). ``bbox=None`` means the
    whole page (used when the page-level decision is ``OCR_REQUIRED``)."""

    page: int
    bbox: tuple[float, float, float, float] | None
    reason: str


@dataclass(frozen=True)
class PageReliability:
    """Per-page routing evidence (FR-024b). Evidence only — never a candidate, never
    literal text."""

    page: int
    page_class: PageClass
    ocr_regions: list[OcrTriggerRegion]


def _classify_band(band: BandEvidence, *, knobs: Mapping[str, Any]) -> str:
    """One band's local decision: ``"blank"`` | ``"native_ok"`` | ``"needs_ocr"``.

    A band with native text present is never "blank", however faint its rendered ink
    is — but with genuinely zero visible ink it is also never flagged for OCR (nothing
    to recover). Gibberish overrides everything else: a mojibake region is a real
    problem regardless of how it happens to render visually.
    """
    has_ink = band.ink_ratio >= knobs["blank_ink_ratio_threshold"]
    has_text = band.char_count > 0

    if not has_ink and not has_text:
        return "blank"

    if has_text:
        if band.gibberish_matches > 0:
            return "needs_ocr"
        if has_ink and band.native_area_ratio < knobs["min_coverage_ratio"]:
            return "needs_ocr"
        return "native_ok"

    # has_ink and not has_text: visible content with nothing extractable there.
    return "needs_ocr"


def _aggregate_page_class(
    bands: list[BandEvidence],
    decisions: list[str],
    *,
    page: int,
    knobs: Mapping[str, Any],
) -> tuple[PageClass, list[OcrTriggerRegion]]:
    """Page-level decision from per-band decisions. "Active" bands are those that are
    not ``"blank"`` (real visual ink, or a confirmed gibberish match regardless of
    ink level) — a band with invisible/negligible native text and no ink never enters
    the ratio either way, since there is nothing there to recover."""
    active = [(b, d) for b, d in zip(bands, decisions, strict=True) if d != "blank"]
    if not active:
        return PageClass.NATIVE_TEXT_SUFFICIENT, []

    bad = [b for b, d in active if d == "needs_ocr"]
    ratio = len(bad) / len(active)

    if ratio == 0:
        return PageClass.NATIVE_TEXT_SUFFICIENT, []

    if ratio >= knobs["ocr_required_ratio_threshold"]:
        return PageClass.OCR_REQUIRED, [
            OcrTriggerRegion(page=page, bbox=None, reason="whole_page_native_text_unreliable")
        ]

    regions = [OcrTriggerRegion(page=page, bbox=b.bbox, reason=_region_reason(b)) for b in bad]
    return PageClass.HYBRID_NATIVE_AND_OCR, regions


def _region_reason(band: BandEvidence) -> str:
    if band.gibberish_matches > 0:
        return "encoding_gibberish"
    if band.char_count == 0:
        return "no_native_text"
    return "insufficient_native_coverage"


def _gather_bands(source: Any, page_no: int, *, knobs: Mapping[str, Any]) -> list[BandEvidence]:
    """Real evidence gathering — the only function in this module that touches
    ``pdf/loader`` primitives directly. Raw pdfplumber (``page.chars``) and a raw
    pypdfium2 raster on the **same source handle** — never another path's output."""
    import numpy as np

    plumber_page = source.plumber_page(page_no)
    page_width, page_height = float(plumber_page.width), float(plumber_page.height)
    chars = plumber_page.chars

    pdfium_page = source.pdfium_page(page_no)
    scale = float(knobs["raster_scale"])
    bitmap = pdfium_page.render(scale=scale)
    gray = np.array(bitmap.to_pil().convert("L"))

    num_bands = int(knobs["num_bands"])
    band_height = page_height / num_bands
    luma_threshold = float(knobs["ink_luma_threshold"])

    bands: list[BandEvidence] = []
    for i in range(num_bands):
        top = i * band_height
        bottom = (i + 1) * band_height
        row0, row1 = int(top * scale), max(int(bottom * scale), int(top * scale) + 1)
        row1 = min(row1, gray.shape[0])
        ink_ratio = float((gray[row0:row1, :] < luma_threshold).mean()) if row1 > row0 else 0.0

        band_chars = [c for c in chars if top <= (c["top"] + c["bottom"]) / 2.0 < bottom]
        text = "".join(c["text"] for c in band_chars)
        gibberish_matches = len(_MOJIBAKE_RE.findall(text))
        native_area = sum(
            (float(c["x1"]) - float(c["x0"])) * (float(c["bottom"]) - float(c["top"]))
            for c in band_chars
        )
        native_area_ratio = native_area / (page_width * band_height) if band_height > 0 else 0.0

        bands.append(
            BandEvidence(
                index=i,
                bbox=(0.0, top, page_width, bottom),
                ink_ratio=ink_ratio,
                char_count=len(band_chars),
                native_area_ratio=native_area_ratio,
                gibberish_matches=gibberish_matches,
            )
        )
    return bands


class NativeReliabilityClassifier:
    """Extraction-routing / evidence component (M2 / research §24). Reads the source
    PDF directly via ``pdf/loader`` — never an ``ExtractionCandidate``, never another
    extraction path's output."""

    def __init__(self, knobs: Mapping[str, Any] | None = None) -> None:
        self._knobs: dict[str, Any] = {**DEFAULT_KNOBS, **(dict(knobs) if knobs else {})}

    def classify_page(self, source: Any, page_no: int) -> PageReliability:
        """``source`` is a ``pdf/loader.PdfSource`` handle — never a candidate, never
        a list of segments."""
        bands = _gather_bands(source, page_no, knobs=self._knobs)
        decisions = [_classify_band(b, knobs=self._knobs) for b in bands]
        page_class, regions = _aggregate_page_class(
            bands, decisions, page=page_no, knobs=self._knobs
        )
        return PageReliability(page=page_no, page_class=page_class, ocr_regions=regions)

    def classify(self, source: Any, pages: list[int]) -> list[PageReliability]:
        return [self.classify_page(source, page_no) for page_no in pages]
