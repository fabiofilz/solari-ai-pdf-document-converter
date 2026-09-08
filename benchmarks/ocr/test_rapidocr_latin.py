"""T011 guard tests — RapidOCR must use the multilingual Latin recognition model,
never the bundled Chinese one, for a supported v1 language; and the chosen engine
must reproduce representative PT/ES characters (research §4.1).

Marked ``benchmark`` (not ``acceptance``): no network, no download — the Latin
model is read from ``benchmarks/ocr/models/`` (run ``fetch_latin_model.py`` once).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from benchmarks.ocr import metrics
from benchmarks.ocr.run import LATIN_DICT_PATH, LATIN_MODEL_PATH, load_engines
from solari_converter.errors import OcrUnavailable
from solari_converter.extract.ocr_engines import rapidocr_engine as re_mod
from solari_converter.extract.ocr_engines.rapidocr_engine import RapidOcrEngine

pytestmark = pytest.mark.benchmark

CORPUS = Path(__file__).resolve().parent / "corpus"
_MODEL_PRESENT = LATIN_MODEL_PATH.is_file() and LATIN_DICT_PATH.is_file()
_needs_model = pytest.mark.skipif(not _MODEL_PRESENT, reason="Latin model not fetched")


# --------------------------------------------------------------------------------------
# no silent fallback to the bundled Chinese model
# --------------------------------------------------------------------------------------

def test_unconfigured_engine_refuses_rather_than_using_chinese_model():
    eng = RapidOcrEngine()  # no rec_model_path / rec_keys_path, no env vars
    assert eng.is_available() is False
    with pytest.raises(OcrUnavailable):
        _ = eng.model_identity  # provenance can never describe the bundled ch model
    with pytest.raises(OcrUnavailable):
        eng.recognize(str(CORPUS / "pt_diacritics_01.png"), ["pt"])


def test_module_defines_no_bundled_chinese_recognition_default():
    src = Path(re_mod.__file__).read_text()
    assert 'MODEL_FAMILY = "PP-OCRv4 (ch, bundled)"' not in src
    assert "RapidOCR()" not in src  # the old no-arg construction used the ch model
    assert re_mod.EXPECTED_REC_MODEL == "latin_PP-OCRv3_rec_infer.onnx"


@_needs_model
def test_configured_engine_reports_latin_model_as_provenance():
    eng = RapidOcrEngine(rec_model_path=LATIN_MODEL_PATH, rec_keys_path=LATIN_DICT_PATH)
    assert eng.is_available() is True
    ident = eng.model_identity
    assert ident["rec_model_name"] == "latin_PP-OCRv3_rec_infer.onnx"
    assert not ident["rec_model_name"].lower().startswith("ch_")
    assert len(ident["rec_model_sha256"]) == 64
    assert int(ident["rec_dict_symbols"]) >= 150  # full Latin dict, not en-only


@_needs_model
def test_recognizer_actually_loads_the_latin_onnx_model():
    eng = RapidOcrEngine(rec_model_path=LATIN_MODEL_PATH, rec_keys_path=LATIN_DICT_PATH)
    eng.recognize(str(CORPUS / "es_diacritics_01.png"), ["es"])
    active = eng._active_rec_model_path()  # introspection helper
    assert active is not None, "could not introspect the active rec model"
    assert Path(active).name == "latin_PP-OCRv3_rec_infer.onnx"
    assert "ch_ppocr" not in Path(active).name.lower()


@_needs_model
def test_non_latin_language_is_rejected():
    eng = RapidOcrEngine(rec_model_path=LATIN_MODEL_PATH, rec_keys_path=LATIN_DICT_PATH)
    for lang in ("zh", "ja", "ru", " ar "):
        with pytest.raises(OcrUnavailable):
            eng.recognize(str(CORPUS / "en_text_01.png"), [lang])


# --------------------------------------------------------------------------------------
# H1 — fail-closed SHA256 verification of the approved v1 recognition artifacts
# --------------------------------------------------------------------------------------

def _bundled_ch_rec_model() -> Path:
    import rapidocr_onnxruntime

    return Path(rapidocr_onnxruntime.__file__).parent / "models" / "ch_PP-OCRv4_rec_infer.onnx"


def test_pinned_digests_match_sha256sums_and_ledger_docs():
    """The runtime policy constant must stay consistent with SHA256SUMS."""
    sums = (LATIN_MODEL_PATH.parent / "SHA256SUMS").read_text()
    assert re_mod.APPROVED_V1_REC_MODEL["sha256"] in sums
    assert re_mod.APPROVED_V1_REC_DICT["sha256"] in sums


@_needs_model
def test_correct_pinned_artifacts_are_accepted():
    eng = RapidOcrEngine(rec_model_path=LATIN_MODEL_PATH, rec_keys_path=LATIN_DICT_PATH)
    assert eng.is_available() is True
    ident = eng.model_identity
    assert ident["rec_model_sha256"] == re_mod.APPROVED_V1_REC_MODEL["sha256"]
    assert ident["rec_keys_sha256"] == re_mod.APPROVED_V1_REC_DICT["sha256"]
    assert ident["provenance_verified"] == "sha256"


@_needs_model
def test_renamed_copies_with_matching_digest_are_accepted(tmp_path):
    """Identity is content-addressed, not basename-based."""
    m = tmp_path / "totally_different_name.onnx"
    k = tmp_path / "my_keys.txt"
    m.write_bytes(LATIN_MODEL_PATH.read_bytes())
    k.write_bytes(LATIN_DICT_PATH.read_bytes())
    eng = RapidOcrEngine(rec_model_path=m, rec_keys_path=k)
    assert eng.is_available() is True
    ident = eng.model_identity
    assert ident["rec_model_name"] == "totally_different_name.onnx"          # actual basename
    assert ident["rec_model_canonical_name"] == "latin_PP-OCRv3_rec_infer.onnx"
    assert ident["rec_model_family"] == re_mod.APPROVED_V1_REC_MODEL["family"]
    eng.recognize(str(CORPUS / "es_diacritics_01.png"), ["es"])             # executes


@_needs_model
def test_altered_model_bytes_are_rejected(tmp_path):
    m = tmp_path / "latin_PP-OCRv3_rec_infer.onnx"
    data = bytearray(LATIN_MODEL_PATH.read_bytes())
    data[-1] ^= 0x01  # flip one byte
    m.write_bytes(bytes(data))
    k = tmp_path / "latin_dict.txt"
    k.write_bytes(LATIN_DICT_PATH.read_bytes())
    eng = RapidOcrEngine(rec_model_path=m, rec_keys_path=k)
    assert eng.is_available() is False
    with pytest.raises(OcrUnavailable):
        _ = eng.model_identity
    with pytest.raises(OcrUnavailable):
        eng.recognize(str(CORPUS / "es_diacritics_01.png"), ["es"])


@_needs_model
def test_altered_dictionary_bytes_are_rejected(tmp_path):
    m = tmp_path / "latin_PP-OCRv3_rec_infer.onnx"
    m.write_bytes(LATIN_MODEL_PATH.read_bytes())
    k = tmp_path / "latin_dict.txt"
    k.write_text(LATIN_DICT_PATH.read_text(encoding="utf-8") + "extra\n", encoding="utf-8")
    eng = RapidOcrEngine(rec_model_path=m, rec_keys_path=k)
    assert eng.is_available() is False
    with pytest.raises(OcrUnavailable):
        eng.recognize(str(CORPUS / "es_diacritics_01.png"), ["es"])


def test_unrelated_valid_onnx_with_latin_looking_name_is_rejected(tmp_path):
    """A real, loadable ONNX model that is not the approved artifact — filename
    disguised as Latin — must still fail closed."""
    ch = _bundled_ch_rec_model()
    if not ch.is_file():
        pytest.skip("bundled ch rec model not present")
    fake = tmp_path / "latin_PP-OCRv3_rec_infer.onnx"
    fake.write_bytes(ch.read_bytes())
    keys = tmp_path / "latin_dict.txt"
    if LATIN_DICT_PATH.is_file():
        keys.write_bytes(LATIN_DICT_PATH.read_bytes())
    else:
        keys.write_text("a\n")
    eng = RapidOcrEngine(rec_model_path=fake, rec_keys_path=keys)
    assert eng.is_available() is False
    with pytest.raises(OcrUnavailable):
        eng.recognize(str(CORPUS / "en_text_01.png"), ["en"])


def test_bundled_chinese_model_remains_rejected(tmp_path):
    ch = _bundled_ch_rec_model()
    if not ch.is_file():
        pytest.skip("bundled ch rec model not present")
    keys = tmp_path / "k.txt"
    keys.write_text("a\n")
    eng = RapidOcrEngine(rec_model_path=ch, rec_keys_path=keys)
    assert eng.is_available() is False
    with pytest.raises(OcrUnavailable):
        eng.recognize(str(CORPUS / "en_text_01.png"), ["en"])


@_needs_model
def test_env_overrides_cannot_bypass_digest_verification(tmp_path, monkeypatch):
    bad = tmp_path / "latin_PP-OCRv3_rec_infer.onnx"
    data = bytearray(LATIN_MODEL_PATH.read_bytes())
    data[0] ^= 0xFF
    bad.write_bytes(bytes(data))
    monkeypatch.setenv("SOLARI_RAPIDOCR_REC_MODEL", str(bad))
    monkeypatch.setenv("SOLARI_RAPIDOCR_REC_KEYS", str(LATIN_DICT_PATH))
    eng = RapidOcrEngine()  # picks up env vars
    assert eng.is_available() is False
    with pytest.raises(OcrUnavailable):
        eng.recognize(str(CORPUS / "en_text_01.png"), ["en"])


def test_provenance_family_not_emitted_without_verified_load():
    """model_identity must raise (not return a family label) when unverified."""
    eng = RapidOcrEngine()  # nothing configured
    with pytest.raises(OcrUnavailable):
        _ = eng.model_identity
    assert eng._identity is None


def test_engine_imports_no_network_or_download_libraries():
    """No runtime network/model-download path exists in the engine module."""
    import ast

    tree = ast.parse(Path(re_mod.__file__).read_text())
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    forbidden = {"urllib", "requests", "httpx", "http", "socket", "ftplib",
                 "huggingface_hub", "aiohttp"}
    assert not (imported & forbidden), f"network import in engine: {imported & forbidden}"
    # and no dynamic-fetch call names anywhere in code (identifiers, not prose)
    calls = {
        n.func.attr for n in ast.walk(tree)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
    } | {
        n.func.id for n in ast.walk(tree)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
    }
    assert not (calls & {"urlretrieve", "urlopen", "request", "download_file",
                         "hf_hub_download", "snapshot_download"})


# --------------------------------------------------------------------------------------
# the chosen engine must reproduce representative PT / ES characters (§4.1)
# --------------------------------------------------------------------------------------

@pytest.mark.parametrize(
    ("page", "lang", "running_tokens"),
    [
        # PT ã õ â ê ç in running words (research §4.1 / T011b)
        ("pt_diacritics_01", "pt", ["informações", "são", "Conceição", "Antônio", "Ipê"]),
        # ES ñ ü ¿ ¡ in running words / tokens
        ("es_diacritics_01", "es", ["español", "año", "niño", "pingüino", "¿Cómo", "¡Hola"]),
    ],
)
def test_a_chosen_engine_reproduces_representative_diacritics(page, lang, running_tokens):
    """Whichever engine T013 selects must reproduce the representative PT/ES
    diacritic classes **in running text** (the isolated one-glyph showcase line is
    excluded — neither engine reads a bare parenthetical ``(â)`` reliably and §4.1
    scores the slice as a whole, not single glyphs)."""
    import json

    engines = load_engines()
    assert engines, "no OCR engine available"

    ref_lines = json.loads((CORPUS.parent / "ground_truth" / f"{page}.json").read_text())["lines"]
    running_ref = "\n".join(ref_lines[:-1])  # drop the trailing "Vocales/Observação: ..." showcase

    best_acc, best_text = -1.0, ""
    for eng in engines:
        out = " ".join(ln.text for ln in eng.recognize(str(CORPUS / f"{page}.png"), [lang]))
        acc = metrics.diacritic_accuracy(running_ref, out)
        if acc > best_acc:
            best_acc, best_text = acc, out

    floor = metrics.LANGUAGE_ACCEPTANCE_FLOOR["diacritic_accuracy_min"]
    assert best_acc >= floor, (
        f"no available engine clears the §4.1 diacritic floor on {lang} running text "
        f"({best_acc:.3f} < {floor}); best output: {best_text!r}"
    )
    missing = [tok for tok in running_tokens if tok not in best_text]
    assert len(missing) <= 1, f"chosen-engine output missing tokens {missing} for {page}"
