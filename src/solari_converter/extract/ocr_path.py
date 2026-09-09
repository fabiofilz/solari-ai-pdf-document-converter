"""OCR extraction path C adapter (T050).

Path C (FR-024/FR-024a/FR-024b/FR-025/FR-027/FR-027a) processes the **original
source PDF** directly — never another extraction path's output — running OCR only on
the pages/regions ``extract/native_reliability.py`` (T049) flags as needing it. The
needs-OCR *decision* is entirely T049's; this module never reimplements or overrides
that routing logic.

**Engine-neutral** (FR per research §9a / the OCR Benchmark Gate, T013): the same
mapping logic runs unchanged regardless of which ``OcrEngine`` (``extract/ocr_engines``,
T017) is configured — Tesseract 5 (the frozen project default) or RapidOCR. Docling
(path A) never performs OCR of any kind (``do_ocr=False``, T046) — this module is the
project's sole OCR authority, selected explicitly via ``--ocr-engine`` /
``config.ocr_engine``; a missing/unusable engine raises ``OcrUnavailable`` (exit 8,
T008/T016) rather than silently falling back to another engine or to Docling.

**Geometry**: an ``OcrEngine`` returns line bboxes in the *rasterized region's own
pixel space* (top-left origin). This module rasterizes each flagged region via
pypdfium2 (never a page image produced by another path) and converts every recognized
line's bbox back into the same full-page, top-left-origin PDF-point convention paths
A (T046) and B (T047) use — accounting for both the raster scale and, for a
sub-region, the crop's own top-left offset within the page (see
``_pixel_to_pdf_bbox`` / ``_crop_margins``).

**Page/region classification** (FR-024b): ``PageClass`` itself is not a field on the
frozen ``ExtractionCandidate`` schema (an additional field would be an architecture
change out of this task's scope). It is recorded *implicitly* on the OCR candidate,
in exactly the shape ``RegionOcrRecord`` already frozen for this purpose:
``native_text_sufficient`` -> one record with ``ran_ocr=False``;
``ocr_required`` -> one record with ``ran_ocr=True, region_bbox=None`` (whole page);
``hybrid_native_and_ocr`` -> one ``ran_ocr=True`` record per flagged region, each with
its own ``region_bbox``. A later stage (canonical-document assembly) can derive the
page class from this pattern without a schema change.

**Independence** (M2 / SC-024): this module imports neither ``extract/plumber_path``
nor ``extract/docling_path``, nor anything under ``reconcile/``, nor another
extraction candidate. It uses ``extract/native_reliability.py`` (T049) only for
routing evidence, and ``extract/language_detect.py`` (T045) only for a language
guess — neither is treated as literal source content.
"""

from __future__ import annotations

from typing import Any

from solari_converter.errors import OcrUnavailable
from solari_converter.extract.language_detect import detect_language
from solari_converter.extract.native_reliability import (
    NativeReliabilityClassifier,
    OcrTriggerRegion,
    PageClass,
)
from solari_converter.extract.ocr_engines.base import OcrEngine, OcrLine
from solari_converter.model.candidate import (
    CandidateReadingOrder,
    ExtractionCandidate,
    RegionOcrRecord,
)
from solari_converter.model.provenance import SourceRef
from solari_converter.model.segment import SourceBackedSegment, segment_id

from .base import EnvelopeFields

__all__ = ["TECHNIQUE_PREFIX", "OcrExtractionPath"]

TECHNIQUE_PREFIX = "ocr"

_ENGINE_BUILDERS: dict[str, str] = {
    "tesseract": "solari_converter.extract.ocr_engines.tesseract_engine:TesseractEngine",
    "rapidocr": "solari_converter.extract.ocr_engines.rapidocr_engine:RapidOcrEngine",
}


def _build_engine(name: str) -> OcrEngine:
    """Construct the configured ``OcrEngine`` by name (``--ocr-engine`` /
    ``config.ocr_engine``, T017) — engine-neutral: the caller never branches on which
    one it got. An unknown name raises ``OcrUnavailable`` rather than silently
    defaulting to another engine."""
    target = _ENGINE_BUILDERS.get(name)
    if target is None:
        raise OcrUnavailable(
            f"unknown OCR engine {name!r}; expected one of {sorted(_ENGINE_BUILDERS)}"
        )
    module_name, class_name = target.split(":")
    import importlib

    module = importlib.import_module(module_name)
    return getattr(module, class_name)()


def _crop_margins(
    bbox: tuple[float, float, float, float] | None, *, page_width: float, page_height: float
) -> tuple[float, float, float, float]:
    """pypdfium2's ``render(crop=(left, bottom, right, top))`` margins-to-remove, from
    a ``(x0, top, x1, bottom)`` region bbox in this project's top-left-origin
    convention. ``bbox=None`` means the whole page — zero margins."""
    if bbox is None:
        return (0.0, 0.0, 0.0, 0.0)
    x0, top, x1, bottom = bbox
    return (x0, page_height - bottom, page_width - x1, top)


def _pixel_to_pdf_bbox(
    pixel_bbox: tuple[float, float, float, float], *, origin_x: float, origin_y: float, scale: float
) -> tuple[float, float, float, float]:
    """Convert an OCR engine's raster-pixel-space bbox (top-left origin, the rendered
    region's own coordinate frame) back into full-page PDF-point space. ``origin_x``/
    ``origin_y`` are the region's own top-left corner in full-page PDF points (0,0 for
    a whole-page region)."""
    x0, y0, x1, y1 = pixel_bbox
    return (
        origin_x + x0 / scale,
        origin_y + y0 / scale,
        origin_x + x1 / scale,
        origin_y + y1 / scale,
    )


def _requested_pages(page_selection_token: str | None, page_count: int) -> set[int] | None:
    """Decode the already-validated canonical page-selection token. Mirrors
    ``extract/docling_path.py`` / ``extract/plumber_path.py``'s identical helper."""
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


class OcrExtractionPath:
    """Path C: local OCR, region-aware via ``native_reliability`` routing, operating
    on raster evidence from the original source PDF (``PdfSource`` — never another
    path's output; FR-060). Implements the ``ExtractionPath`` protocol from
    ``extract/base.py``.

    No import of ``extract/plumber_path``, ``extract/docling_path``, or anything under
    ``reconcile/`` anywhere in this module (verified by
    ``test_module_imports_no_sibling_extraction_path_or_reconciliation``).
    """

    def __init__(
        self,
        *,
        engine: OcrEngine | None = None,
        ocr_engine: str = "tesseract",
        ocr_lang_override: str | list[str] | None = None,
        confidence_threshold: float = 70.0,
        native_reliability_knobs: dict[str, Any] | None = None,
        raster_scale: float = 2.0,
    ) -> None:
        self._engine: OcrEngine = engine if engine is not None else _build_engine(ocr_engine)
        self.technique = f"{TECHNIQUE_PREFIX}:{self._engine.name}"
        self._lang_override = ocr_lang_override
        self._confidence_threshold = float(confidence_threshold)
        self._classifier = NativeReliabilityClassifier(knobs=native_reliability_knobs)
        self._raster_scale = raster_scale

    # -- ExtractionPath protocol --------------------------------------------------------

    def extract(self, source: Any, *, envelope: EnvelopeFields) -> ExtractionCandidate:
        """Read ``source`` (a ``pdf/loader.PdfSource`` handle) directly. May raise;
        ``extract/base.py``'s ``run_path()`` converts any raise (including
        ``OcrUnavailable``) into a ``status="failed"`` candidate (FR-060 edge case)."""
        page_count = source.page_count
        requested = _requested_pages(envelope.get("page_selection"), page_count)
        pages = requested if requested is not None else set(range(1, page_count + 1))

        segments: list[SourceBackedSegment] = []
        order: list[str] = []
        page_ocr_records: list[RegionOcrRecord] = []
        pages_covered: list[int] = []

        for page_no in sorted(pages):
            pages_covered.append(page_no)
            reliability = self._classifier.classify_page(source, page_no)

            if reliability.page_class == PageClass.NATIVE_TEXT_SUFFICIENT:
                page_ocr_records.append(
                    RegionOcrRecord(
                        physical_page=page_no,
                        region_bbox=None,
                        ran_ocr=False,
                        languages=[],
                        language_source="auto",
                        mean_confidence=0.0,
                        confidence_threshold=self._confidence_threshold,
                        low_confidence_regions=0,
                    )
                )
                continue

            page_native_text = source.plumber_page(page_no).extract_text() or ""
            for region in reliability.ocr_regions:
                record, region_segments, region_order = self._process_region(
                    source, page_no, region, page_native_text
                )
                page_ocr_records.append(record)
                segments.extend(region_segments)
                order.extend(region_order)

        index_by_id = {sid: idx for idx, sid in enumerate(order)}
        for segment in segments:
            segment.reading_order_index = index_by_id[segment.segment_id]

        env = {
            k: envelope[k]
            for k in ("run_id", "tool_version", "source_pdf", "source_sha256", "page_selection")
        }
        return ExtractionCandidate(
            **env,
            technique=self.technique,
            status="ok",
            status_detail=None,
            segments=segments,
            reading_order=CandidateReadingOrder(technique=self.technique, order=order),
            pages_covered=pages_covered,
            page_ocr=page_ocr_records,
        )

    # -- region processing --------------------------------------------------------------

    def _process_region(
        self, source: Any, page_no: int, region: OcrTriggerRegion, page_native_text: str
    ) -> tuple[RegionOcrRecord, list[SourceBackedSegment], list[str]]:
        plumber_page = source.plumber_page(page_no)
        page_width, page_height = float(plumber_page.width), float(plumber_page.height)

        lang_result = detect_language(page_native_text, override=self._lang_override)
        languages = list(lang_result.languages) if lang_result.languages else [lang_result.primary]

        if not self._engine.is_available():
            raise OcrUnavailable(f"configured OCR engine {self._engine.name!r} is not available")

        crop = _crop_margins(region.bbox, page_width=page_width, page_height=page_height)
        pdfium_page = source.pdfium_page(page_no)
        bitmap = pdfium_page.render(scale=self._raster_scale, crop=crop)
        image = bitmap.to_pil()

        lines: list[OcrLine] = self._engine.recognize(image, languages)

        origin_x = region.bbox[0] if region.bbox is not None else 0.0
        origin_y = region.bbox[1] if region.bbox is not None else 0.0

        segments: list[SourceBackedSegment] = []
        order: list[str] = []
        for line in lines:
            segment = self._build_segment(
                line,
                page_no=page_no,
                languages=languages,
                origin_x=origin_x,
                origin_y=origin_y,
            )
            segments.append(segment)
            order.append(segment.segment_id)

        confidences = [line.confidence for line in lines]
        mean_confidence = sum(confidences) / len(confidences) if confidences else 0.0
        low_confidence_count = sum(1 for c in confidences if c < self._confidence_threshold)

        record = RegionOcrRecord(
            physical_page=page_no,
            region_bbox=region.bbox,
            ran_ocr=True,
            languages=languages,
            language_source=lang_result.language_source,
            mean_confidence=mean_confidence,
            confidence_threshold=self._confidence_threshold,
            low_confidence_regions=low_confidence_count,
        )
        return record, segments, order

    def _build_segment(
        self,
        line: OcrLine,
        *,
        page_no: int,
        languages: list[str],
        origin_x: float,
        origin_y: float,
    ) -> SourceBackedSegment:
        pixel_bbox = line.bbox if line.bbox is not None else (0.0, 0.0, 0.0, 0.0)
        bbox = _pixel_to_pdf_bbox(
            pixel_bbox, origin_x=origin_x, origin_y=origin_y, scale=self._raster_scale
        )
        sid = segment_id(page=page_no, bbox=bbox, text=line.text)
        return SourceBackedSegment(
            segment_id=sid,
            text=line.text,
            source=SourceRef(
                physical_page=page_no,
                bbox=bbox,
                origin_kind="ocr",
                extraction_technique=self.technique,
                ocr_languages=languages,
                ocr_confidence=line.confidence,
            ),
            reading_order_index=0,  # patched once the candidate's global order is known
            structural_hints=[],
        )
