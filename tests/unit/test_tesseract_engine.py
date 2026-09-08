"""M2 — automated coverage of the TesseractEngine language contract (T009).

The mapping function is exercised directly (pure); the executable / traineddata
boundary is the only thing mocked, so these run without every language pack being
installed on the workstation. The real PT/EN/ES recognition path stays covered by
``tests/acceptance/test_ocr_benchmark_smoke.py`` and the OCR benchmark.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from solari_converter.errors import OcrUnavailable
from solari_converter.extract.ocr_engines.tesseract_engine import TesseractEngine, _tess_lang

_CORPUS = Path(__file__).resolve().parents[2] / "benchmarks" / "ocr" / "corpus"
_PNG = _CORPUS / "en_text_01.png"


# --------------------------------------------------------------------------------------
# language-id -> traineddata mapping (pure function, no mocks)
# --------------------------------------------------------------------------------------

@pytest.mark.parametrize(
    ("lang", "code"),
    [("pt", "por"), ("en", "eng"), ("es", "spa"),
     ("fr", "fra"), ("it", "ita"), ("de", "deu")],
)
def test_primary_language_maps_to_expected_traineddata(lang, code):
    assert _tess_lang([lang]) == code


@pytest.mark.parametrize(
    ("langs", "expected"),
    [
        (["pt-BR"], "por"),
        (["POR"], "por"),
        (["EN"], "eng"),
    ],
)
def test_aliases_and_case_fold(langs, expected):
    assert _tess_lang(langs) == expected


def test_multi_language_produces_plus_form_in_request_order():
    assert _tess_lang(["pt", "en"]) == "por+eng"
    assert _tess_lang(["es", "fr", "de", "it"]) == "spa+fra+deu+ita"


def test_duplicate_language_requests_are_deduplicated():
    assert _tess_lang(["pt", "pt-br", "por", "pt"]) == "por"
    assert _tess_lang(["en", "eng", "en"]) == "eng"
    assert _tess_lang(["pt", "en", "pt"]) == "por+eng"


def test_empty_request_defaults_to_portuguese():
    assert _tess_lang([]) == "por"


def test_unknown_code_passes_through_unchanged():
    # documents (does not assert-away) the passthrough behaviour — a genuinely
    # unknown code reaches tesseract and fails the traineddata check there.
    assert _tess_lang(["xx"]) == "xx"


# --------------------------------------------------------------------------------------
# executable / traineddata boundary (mocked at pytesseract only)
# --------------------------------------------------------------------------------------

def _min_tsv_dict():
    return {
        "text": [""], "conf": ["-1"],
        "block_num": [0], "par_num": [0], "line_num": [0],
        "left": [0], "top": [0], "width": [0], "height": [0],
    }


def test_missing_required_traineddata_raises_ocr_unavailable(monkeypatch):
    import pytesseract

    monkeypatch.setattr(pytesseract, "get_languages", lambda **_kw: ["eng"])
    monkeypatch.setattr(
        pytesseract, "image_to_data",
        lambda *_a, **_k: pytest.fail("image_to_data must not run when traineddata is missing"),
    )
    with pytest.raises(OcrUnavailable, match="fra"):
        TesseractEngine().recognize(str(_PNG), ["fr"])


def test_missing_one_of_several_required_traineddata_raises(monkeypatch):
    import pytesseract

    monkeypatch.setattr(pytesseract, "get_languages", lambda **_kw: ["por", "eng"])
    monkeypatch.setattr(pytesseract, "image_to_data",
                        lambda *_a, **_k: pytest.fail("should not reach the executable"))
    with pytest.raises(OcrUnavailable, match="spa"):
        TesseractEngine().recognize(str(_PNG), ["pt", "en", "es"])


def test_binary_not_found_raises_ocr_unavailable(monkeypatch):
    import pytesseract

    monkeypatch.setattr(pytesseract, "get_languages", lambda **_kw: ["eng"])

    def _boom(*_a, **_k):
        raise pytesseract.TesseractNotFoundError()

    monkeypatch.setattr(pytesseract, "image_to_data", _boom)
    with pytest.raises(OcrUnavailable, match="binary not found"):
        TesseractEngine().recognize(str(_PNG), ["en"])


def test_combined_plus_lang_string_reaches_the_executable(monkeypatch):
    import pytesseract

    seen = {}
    monkeypatch.setattr(pytesseract, "get_languages", lambda **_kw: ["por", "eng"])

    def _capture(img, lang, output_type):  # noqa: ANN001
        seen["lang"] = lang
        return _min_tsv_dict()

    monkeypatch.setattr(pytesseract, "image_to_data", _capture)
    lines = TesseractEngine().recognize(str(_PNG), ["pt", "en"])
    assert seen["lang"] == "por+eng"
    assert lines == []  # empty TSV -> no OcrLine, no crash


def test_is_available_reflects_the_binary(monkeypatch):
    import pytesseract

    monkeypatch.setattr(pytesseract, "get_tesseract_version", lambda: "5.5.3")
    assert TesseractEngine().is_available() is True

    def _boom():
        raise pytesseract.TesseractNotFoundError()

    monkeypatch.setattr(pytesseract, "get_tesseract_version", _boom)
    assert TesseractEngine().is_available() is False
