"""T050 — failing-first tests for the OCR extraction path C adapter
(GREEN owner: **T050**, ``src/solari_converter/extract/ocr_path.py``).

Frozen behaviour under test (FR-024b/FR-025/FR-027/FR-027a; Constitution V):

* routing — the needs-OCR decision comes from ``native_reliability`` (T049), never
  reimplemented here; OCR only runs on the regions it flags;
* geometry — an OCR line's raster-pixel bbox is converted back to the same
  top-left-origin PDF-point convention paths A/B use, accounting for both the
  rasterization scale and the region's own crop offset;
* provenance — ``origin_kind="ocr"``, ``extraction_technique="ocr:<engine>"``,
  confidence always 0-100, language source `auto` vs `override`;
* engine-neutral — the same mapping logic runs unchanged regardless of which
  ``OcrEngine`` is configured; a missing engine raises ``OcrUnavailable`` (exit 8);
* independence — this module imports neither ``extract/plumber_path`` nor
  ``extract/docling_path`` nor another extraction candidate.

Most tests inject a fake ``OcrEngine`` (mirroring the ``_run_docling`` injection seam
T046 uses) so the mapping logic is exercised without depending on a real OCR engine
binary being installed. One real-Tesseract integration test is included since
Tesseract 5 is this project's frozen default and is present in this environment.
"""

from __future__ import annotations

import ast
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # tests/ for `fixtures`

MODULE_PATH = (
    Path(__file__).resolve().parents[2] / "src" / "solari_converter" / "extract" / "ocr_path.py"
)


def _mod():
    import solari_converter.extract.ocr_path as ocr_path  # GREEN owner: T050

    return ocr_path


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
# Independence
# ---------------------------------------------------------------------------------------


def test_module_imports_no_sibling_extraction_path_or_reconciliation() -> None:
    tree = ast.parse(MODULE_PATH.read_text())
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    forbidden = ("docling_path", "plumber_path", "reconcile")
    for name in imported:
        for bad in forbidden:
            assert bad not in name, f"ocr_path.py must not import {name!r} ({bad!r})"


# ---------------------------------------------------------------------------------------
# Geometry — pixel-region bbox -> full-page PDF-point bbox
# ---------------------------------------------------------------------------------------


def test_crop_margins_from_whole_page_region() -> None:
    m = _mod()
    margins = m._crop_margins(None, page_width=612.0, page_height=792.0)
    assert margins == (0.0, 0.0, 0.0, 0.0)


def test_crop_margins_from_a_sub_region_bbox() -> None:
    m = _mod()
    # bbox = (x0, top, x1, bottom) in top-left convention
    margins = m._crop_margins((72.0, 100.0, 540.0, 230.0), page_width=612.0, page_height=792.0)
    # pypdfium2 crop=(left, bottom, right, top) margins to remove from each edge
    assert margins == (72.0, 792.0 - 230.0, 612.0 - 540.0, 100.0)


def test_pixel_bbox_to_pdf_bbox_whole_page_scale_one() -> None:
    m = _mod()
    pdf_bbox = m._pixel_to_pdf_bbox((10.0, 20.0, 30.0, 40.0), origin_x=0.0, origin_y=0.0, scale=1.0)
    assert pdf_bbox == (10.0, 20.0, 30.0, 40.0)


def test_pixel_bbox_to_pdf_bbox_with_scale() -> None:
    m = _mod()
    pdf_bbox = m._pixel_to_pdf_bbox((20.0, 40.0, 60.0, 80.0), origin_x=0.0, origin_y=0.0, scale=2.0)
    assert pdf_bbox == (10.0, 20.0, 30.0, 40.0)


def test_pixel_bbox_to_pdf_bbox_with_region_offset() -> None:
    """A cropped sub-region's pixel (0,0) maps to the region's own top-left corner in
    full-page PDF-point space -- not the page origin."""
    m = _mod()
    pdf_bbox = m._pixel_to_pdf_bbox(
        (0.0, 0.0, 20.0, 10.0), origin_x=72.0, origin_y=100.0, scale=1.0
    )
    assert pdf_bbox == (72.0, 100.0, 92.0, 110.0)


# ---------------------------------------------------------------------------------------
# Fake engine — mirrors extract/docling_path.py's `_run_docling` injection seam
# ---------------------------------------------------------------------------------------


@dataclass
class FakeOcrLine:
    text: str
    bbox: tuple[float, float, float, float] | None
    confidence: float


class FakeOcrEngine:
    name = "fake"

    def __init__(self, lines_by_call=None, available=True):
        self._lines_by_call = lines_by_call or []
        self._available = available
        self.calls: list[tuple[object, list[str]]] = []

    def is_available(self) -> bool:
        return self._available

    def recognize(self, image, languages):
        self.calls.append((image, languages))
        idx = len(self.calls) - 1
        return self._lines_by_call[idx] if idx < len(self._lines_by_call) else []


class FakeSource:
    """A minimal `pdf/loader.PdfSource`-shaped stand-in."""

    def __init__(self, page_count, plumber_pages, pdfium_pages):
        self.page_count = page_count
        self.path = "fake.pdf"
        self._plumber_pages = plumber_pages
        self._pdfium_pages = pdfium_pages

    def plumber_page(self, n):
        return self._plumber_pages[n]

    def pdfium_page(self, n):
        return self._pdfium_pages[n]


class FakePlumberPage:
    def __init__(self, width=612.0, height=792.0, text=""):
        self.width = width
        self.height = height
        self._text = text

    def extract_text(self):
        return self._text


class FakeBitmap:
    def __init__(self, image):
        self._image = image

    def to_pil(self):
        return self._image


class FakePdfiumPage:
    def __init__(self, image):
        self._image = image
        self.render_calls: list[dict] = []

    def render(self, *, scale=1.0, crop=(0, 0, 0, 0)):
        self.render_calls.append({"scale": scale, "crop": crop})
        return FakeBitmap(self._image)


# ---------------------------------------------------------------------------------------
# Engine selection / OcrUnavailable
# ---------------------------------------------------------------------------------------


def test_unknown_engine_name_raises_ocr_unavailable() -> None:
    from solari_converter.errors import OcrUnavailable

    m = _mod()
    with pytest.raises(OcrUnavailable):
        m._build_engine("not-a-real-engine")


def test_technique_reflects_configured_engine() -> None:
    m = _mod()
    path = m.OcrExtractionPath(engine=FakeOcrEngine())
    assert path.technique == "ocr:fake"


def test_unavailable_engine_raises_before_processing(monkeypatch: pytest.MonkeyPatch) -> None:
    from solari_converter.errors import OcrUnavailable

    m = _mod()
    engine = FakeOcrEngine(available=False)
    path = m.OcrExtractionPath(
        engine=engine, native_reliability_knobs={"ocr_required_ratio_threshold": 0.0}
    )

    plumber_page = FakePlumberPage(text="")
    pdfium_page = FakePdfiumPage(image=object())
    source = FakeSource(1, {1: plumber_page}, {1: pdfium_page})

    # Force the routing decision to require OCR by monkeypatching the classifier.
    import solari_converter.extract.native_reliability as nr

    monkeypatch.setattr(
        path._classifier,
        "classify_page",
        lambda src, page_no: nr.PageReliability(
            page=page_no,
            page_class=nr.PageClass.OCR_REQUIRED,
            ocr_regions=[nr.OcrTriggerRegion(page=page_no, bbox=None, reason="test")],
        ),
    )
    with pytest.raises(OcrUnavailable):
        path.extract(source, envelope=_envelope())


# ---------------------------------------------------------------------------------------
# End-to-end mapping with a fake engine + fake native-reliability routing
# ---------------------------------------------------------------------------------------


def _path_with_forced_routing(
    engine, page_class, regions, *, lang_override=None, confidence_threshold=70, raster_scale=1.0
):
    import solari_converter.extract.native_reliability as nr

    m = _mod()
    path = m.OcrExtractionPath(
        engine=engine,
        ocr_lang_override=lang_override,
        confidence_threshold=confidence_threshold,
        raster_scale=raster_scale,
    )
    path._classifier.classify_page = lambda src, page_no: nr.PageReliability(
        page=page_no, page_class=page_class, ocr_regions=regions
    )
    return path, nr


def test_native_text_sufficient_page_runs_no_ocr_and_records_ran_ocr_false() -> None:
    engine = FakeOcrEngine()
    path, nr = _path_with_forced_routing(engine, None, [])
    import solari_converter.extract.native_reliability as nrmod

    path._classifier.classify_page = lambda src, page_no: nrmod.PageReliability(
        page=page_no, page_class=nrmod.PageClass.NATIVE_TEXT_SUFFICIENT, ocr_regions=[]
    )
    plumber_page = FakePlumberPage(text="already fine")
    pdfium_page = FakePdfiumPage(image=object())
    source = FakeSource(1, {1: plumber_page}, {1: pdfium_page})

    candidate = path.extract(source, envelope=_envelope())
    assert candidate.segments == []
    assert len(candidate.page_ocr) == 1
    assert candidate.page_ocr[0].ran_ocr is False
    assert engine.calls == []  # engine never invoked


def test_whole_page_ocr_required_runs_engine_once_on_full_page() -> None:
    import solari_converter.extract.native_reliability as nrmod

    engine = FakeOcrEngine(
        lines_by_call=[
            [FakeOcrLine(text="Recovered text", bbox=(10.0, 20.0, 200.0, 40.0), confidence=88.0)]
        ]
    )
    path, _ = _path_with_forced_routing(
        engine,
        nrmod.PageClass.OCR_REQUIRED,
        [nrmod.OcrTriggerRegion(page=1, bbox=None, reason="whole_page")],
    )
    plumber_page = FakePlumberPage(text="")
    pdfium_page = FakePdfiumPage(image=object())
    source = FakeSource(1, {1: plumber_page}, {1: pdfium_page})

    candidate = path.extract(source, envelope=_envelope())
    assert len(engine.calls) == 1
    assert pdfium_page.render_calls == [{"scale": path._raster_scale, "crop": (0.0, 0.0, 0.0, 0.0)}]
    assert len(candidate.segments) == 1
    seg = candidate.segments[0]
    assert seg.text == "Recovered text"
    assert seg.source.origin_kind == "ocr"
    assert seg.source.extraction_technique == "ocr:fake"
    assert seg.source.ocr_confidence == 88.0
    assert seg.source.bbox == (10.0, 20.0, 200.0, 40.0)
    assert candidate.reading_order.technique == "ocr:fake"
    assert candidate.reading_order.order == [seg.segment_id]
    record = candidate.page_ocr[0]
    assert record.ran_ocr is True
    assert record.region_bbox is None
    assert record.mean_confidence == 88.0


def test_hybrid_region_crop_offset_is_applied_to_segment_geometry() -> None:
    import solari_converter.extract.native_reliability as nrmod

    engine = FakeOcrEngine(
        lines_by_call=[
            [FakeOcrLine(text="stamp text", bbox=(0.0, 0.0, 100.0, 20.0), confidence=70.0)]
        ]
    )
    region_bbox = (72.0, 600.0, 540.0, 720.0)
    path, _ = _path_with_forced_routing(
        engine,
        nrmod.PageClass.HYBRID_NATIVE_AND_OCR,
        [nrmod.OcrTriggerRegion(page=1, bbox=region_bbox, reason="no_native_text")],
    )
    plumber_page = FakePlumberPage(text="some native text on the page")
    pdfium_page = FakePdfiumPage(image=object())
    source = FakeSource(1, {1: plumber_page}, {1: pdfium_page})

    candidate = path.extract(source, envelope=_envelope())
    seg = candidate.segments[0]
    # region origin is (72.0, 600.0); the OCR line's own bbox is offset by that origin
    assert seg.source.bbox == (72.0, 600.0, 172.0, 620.0)
    assert candidate.page_ocr[0].region_bbox == region_bbox


def test_explicit_language_override_wins_and_is_recorded() -> None:
    import solari_converter.extract.native_reliability as nrmod

    engine = FakeOcrEngine(
        lines_by_call=[[FakeOcrLine(text="x", bbox=(0, 0, 10, 10), confidence=90.0)]]
    )
    path, _ = _path_with_forced_routing(
        engine,
        nrmod.PageClass.OCR_REQUIRED,
        [nrmod.OcrTriggerRegion(page=1, bbox=None, reason="whole_page")],
        lang_override="es",
    )
    plumber_page = FakePlumberPage(text="")  # no native text to auto-detect from
    pdfium_page = FakePdfiumPage(image=object())
    source = FakeSource(1, {1: plumber_page}, {1: pdfium_page})

    candidate = path.extract(source, envelope=_envelope())
    assert candidate.page_ocr[0].languages == ["es"]
    assert candidate.page_ocr[0].language_source == "override"
    assert engine.calls[0][1] == ["es"]
    assert candidate.segments[0].source.ocr_languages == ["es"]


def test_low_confidence_regions_counted_against_threshold() -> None:
    import solari_converter.extract.native_reliability as nrmod

    engine = FakeOcrEngine(
        lines_by_call=[
            [
                FakeOcrLine(text="good", bbox=(0, 0, 10, 10), confidence=90.0),
                FakeOcrLine(text="bad", bbox=(0, 20, 10, 30), confidence=40.0),
            ]
        ]
    )
    path, _ = _path_with_forced_routing(
        engine,
        nrmod.PageClass.OCR_REQUIRED,
        [nrmod.OcrTriggerRegion(page=1, bbox=None, reason="whole_page")],
        confidence_threshold=70,
    )
    plumber_page = FakePlumberPage(text="")
    pdfium_page = FakePdfiumPage(image=object())
    source = FakeSource(1, {1: plumber_page}, {1: pdfium_page})

    candidate = path.extract(source, envelope=_envelope())
    record = candidate.page_ocr[0]
    assert record.low_confidence_regions == 1
    assert record.confidence_threshold == 70


def test_no_ocr_lines_returned_yields_no_segments_but_records_region() -> None:
    import solari_converter.extract.native_reliability as nrmod

    engine = FakeOcrEngine(lines_by_call=[[]])
    path, _ = _path_with_forced_routing(
        engine,
        nrmod.PageClass.OCR_REQUIRED,
        [nrmod.OcrTriggerRegion(page=1, bbox=None, reason="whole_page")],
    )
    plumber_page = FakePlumberPage(text="")
    pdfium_page = FakePdfiumPage(image=object())
    source = FakeSource(1, {1: plumber_page}, {1: pdfium_page})

    candidate = path.extract(source, envelope=_envelope())
    assert candidate.segments == []
    assert candidate.page_ocr[0].ran_ocr is True
    assert candidate.page_ocr[0].mean_confidence == 0.0


# ---------------------------------------------------------------------------------------
# Real Tesseract integration (frozen default; installed in this environment)
# ---------------------------------------------------------------------------------------


@pytest.fixture
def scanned_pdf(tmp_path: Path) -> Path:
    from fixtures.build_fixtures import build_scanned

    return build_scanned(tmp_path)


def test_real_tesseract_recovers_text_from_scanned_pdf(scanned_pdf: Path) -> None:
    from solari_converter.extract.ocr_engines.tesseract_engine import TesseractEngine
    from solari_converter.pdf.loader import load_pdf

    engine = TesseractEngine()
    if not engine.is_available():
        pytest.skip("tesseract binary not installed")

    m = _mod()
    path = m.OcrExtractionPath(engine=engine, ocr_lang_override="pt")
    with load_pdf(scanned_pdf) as source:
        candidate = path.extract(source, envelope=_envelope(source_pdf=str(scanned_pdf)))

    assert candidate.technique == "ocr:tesseract"
    assert candidate.segments
    joined = " ".join(s.text for s in candidate.segments)
    assert "ESCRITURA" in joined.upper()
    for seg in candidate.segments:
        assert seg.source.origin_kind == "ocr"
        assert 0.0 <= seg.source.ocr_confidence <= 100.0
