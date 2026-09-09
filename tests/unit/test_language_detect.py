"""T044 [US1] — failing-first tests for the OCR language detector (GREEN owner: **T045**).

Frozen behaviour (research §5, FR-027a, benchmark decision `benchmarks/ocr/RESULTS.md`):

* the default detector is **lingua**; **langdetect** (``DetectorFactory.seed = 0``) is the
  fallback; primary validated languages are Portuguese / English / Spanish (French / Italian /
  German are coverage-only);
* a ``--ocr-lang`` override **wins** over auto-detection and is recorded as
  ``language_source == "override"``; auto-detection records ``"auto"``;
* the detector is **seed-pinned** — the same text yields the same result across two runs;
* detection is **per page / region** (a mapping of region key → text in, region key → result out);
* unknown / empty / featureless text yields a **safe default** (``"und"``), never a crash (M3);
* the result is **routing / evidence metadata only** — it is never accepted as source content.
"""

from __future__ import annotations

import pytest


def _mod():
    import solari_converter.extract.language_detect as language_detect  # GREEN owner: T045

    return language_detect


_PT = "A cláusula quarta do presente contrato estabelece as obrigações das partes."
_EN = "The fourth clause of this agreement sets out the obligations of the parties."
_ES = "La cuarta cláusula del presente contrato establece las obligaciones de las partes."


# --- override vs auto -----------------------------------------------------------------


def test_override_wins_over_auto_detection() -> None:
    m = _mod()
    res = m.detect_language(_EN, override=["pt"])
    assert res.primary == "pt"
    assert res.language_source == "override"


def test_auto_detection_records_auto_source() -> None:
    m = _mod()
    for text, expected in ((_PT, "pt"), (_EN, "en"), (_ES, "es")):
        res = m.detect_language(text)
        assert res.primary == expected, text
        assert res.language_source == "auto"


def test_override_accepts_a_bare_string_and_multiple_languages() -> None:
    m = _mod()
    assert m.detect_language(_ES, override="pt").primary == "pt"
    multi = m.detect_language(_ES, override=["pt", "en"])
    assert tuple(multi.languages) == ("pt", "en")


# --- determinism / seed pinning -----------------------------------------------------


def test_detector_is_seed_pinned_and_stable_across_runs() -> None:
    m = _mod()
    a = m.detect_language(_PT)
    b = m.detect_language(_PT)
    assert (a.primary, a.language_source, a.detector) == (b.primary, b.language_source, b.detector)
    # a freshly built detector agrees too
    det = m.build_detector()
    assert (
        m.detect_language(_PT, detector=det).primary
        == m.detect_language(_PT, detector=det).primary
    )


def test_langdetect_fallback_is_seed_pinned() -> None:
    m = _mod()
    det = m.build_detector("langdetect")
    assert m.detect_language(_PT, detector=det).primary == "pt"
    assert (
        m.detect_language(_PT, detector=det).primary
        == m.detect_language(_PT, detector=det).primary
    )


# --- per page / region ------------------------------------------------------------


def test_per_region_detection() -> None:
    m = _mod()
    out = m.detect_regions({"p1": _PT, "p2": _EN, "p3": _ES})
    assert {k: v.primary for k, v in out.items()} == {"p1": "pt", "p2": "en", "p3": "es"}
    assert all(v.language_source == "auto" for v in out.values())


def test_per_region_override_applies_to_every_region() -> None:
    m = _mod()
    out = m.detect_regions({"p1": _PT, "p2": _EN}, override=["es"])
    assert all(v.primary == "es" and v.language_source == "override" for v in out.values())


# --- safe default (M3) ----------------------------------------------------------------


@pytest.mark.parametrize("text", ["", "   ", "\n\t", "12345 67.89", "€ $ %"])
def test_unknown_or_empty_text_yields_a_safe_default_not_a_crash(text: str) -> None:
    m = _mod()
    res = m.detect_language(text)
    assert res.primary == "und"
    assert res.language_source == "auto"


def test_langdetect_fallback_also_degrades_safely() -> None:
    m = _mod()
    det = m.build_detector("langdetect")
    assert m.detect_language("", detector=det).primary == "und"


# --- evidence only ----------------------------------------------------------------


def test_result_is_metadata_not_source_content() -> None:
    m = _mod()
    res = m.detect_language(_PT)
    # no text payload on the result — it is routing/provenance metadata (FR-027a)
    assert not hasattr(res, "text")
    assert set(vars(res)) <= {"languages", "language_source", "detector"}
