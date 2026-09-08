"""OCR benchmark smoke test (T011) — run with ``-m acceptance``.

REOPENED 2026-09-07 — coverage extended to the primary benchmark languages
(Portuguese, English, Spanish): each required engine loads and returns text for
one clean page **per primary language** plus one degraded page. (Structural /
degraded fixtures are not duplicated per language — research §4.1 / T007 — so the
degraded page is Portuguese.)

The engine list is **fixed** (`tesseract`, `rapidocr`) so a clean clone that has
not run ``benchmarks/ocr/models/fetch_latin_model.py`` shows an explicit
``SKIPPED`` for RapidOCR rather than a silent green — and never substitutes the
bundled Chinese model.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.acceptance

from benchmarks.ocr.run import (  # noqa: E402
    DEGRADED_SMOKE_PAGE,
    SMOKE_CLEAN_PAGES,
    load_engines,
)

from solari_converter.extract.ocr_engines.rapidocr_engine import RapidOcrEngine  # noqa: E402
from solari_converter.extract.ocr_engines.tesseract_engine import TesseractEngine  # noqa: E402

_PAGES = list(SMOKE_CLEAN_PAGES.items())
_PAGES.append(("pt", DEGRADED_SMOKE_PAGE))
_IDS = [f"{lang}:{page.stem}" for lang, page in _PAGES]

_REQUIRED_ENGINES = {"tesseract": TesseractEngine, "rapidocr": RapidOcrEngine}
_SKIP_REASON = {
    "tesseract": "tesseract binary / traineddata not installed",
    "rapidocr": "RapidOCR Latin model not fetched — run benchmarks/ocr/models/fetch_latin_model.py",
}


def _engine(name: str):
    for e in load_engines():
        if e.name == name:
            return e
    pytest.skip(f"{name}: {_SKIP_REASON[name]}")


@pytest.mark.parametrize("engine_name", sorted(_REQUIRED_ENGINES))
@pytest.mark.parametrize(("lang", "page"), _PAGES, ids=_IDS)
def test_engine_returns_text(engine_name, lang, page):
    engine = _engine(engine_name)
    assert engine.is_available(), f"{engine.name} reported unavailable"
    lines = engine.recognize(str(page), [lang])
    joined = " ".join(ln.text for ln in lines).strip()
    assert joined, f"{engine.name} returned no text for {page.name} ({lang})"
    assert all(0.0 <= ln.confidence <= 100.0 for ln in lines)


def test_gate_requires_both_engines():
    """The OCR Benchmark Gate is a two-engine comparison; on a clean clone missing
    one engine this SKIPs with the bootstrap instruction rather than passing."""
    have = {e.name for e in load_engines()}
    missing = set(_REQUIRED_ENGINES) - have
    if missing:
        pytest.skip("gate needs both engines; missing: "
                    + ", ".join(f"{m} ({_SKIP_REASON[m]})" for m in sorted(missing)))
    assert have >= set(_REQUIRED_ENGINES)
