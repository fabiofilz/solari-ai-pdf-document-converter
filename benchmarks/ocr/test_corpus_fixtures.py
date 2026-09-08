"""M6 — the tracked OCR corpus PNGs/JSONs are canonical, frozen fixtures and the
benchmark consumes them without regenerating.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

pytestmark = pytest.mark.benchmark

HERE = Path(__file__).resolve().parent
CORPUS = HERE / "corpus"
GT = HERE / "ground_truth"
MANIFEST = CORPUS / "FIXTURES.sha256"

_EXPECTED_PAGES = {
    "degraded_scan_01", "en_text_01", "es_diacritics_01", "es_numeric_01",
    "hybrid_native_ocr_01", "image_only_01", "latin_coverage_01",
    "multicolumn_legal_01", "multicolumn_legal_02", "numeric_monetary_01",
    "pt_diacritics_01", "simple_table_01", "small_text_01",
}


def _sha256(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _manifest_digests() -> dict[str, str]:
    out: dict[str, str] = {}
    for line in MANIFEST.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        digest, name = line.split()
        out[name] = digest
    return out


def test_exactly_13_png_and_13_json_fixtures():
    pngs = {p.stem for p in CORPUS.glob("*.png")}
    jsons = {p.stem for p in GT.glob("*.json")}
    assert pngs == _EXPECTED_PAGES
    assert jsons == _EXPECTED_PAGES
    assert len(pngs) == 13 and len(jsons) == 13


def test_tracked_pngs_match_the_pinned_manifest():
    want = _manifest_digests()
    assert set(want) == {f"{n}.png" for n in _EXPECTED_PAGES}, "manifest page set drift"
    for name, digest in want.items():
        assert _sha256(CORPUS / name) == digest, f"{name} differs from FIXTURES.sha256"


def test_ground_truth_has_required_shape_and_is_authored_not_ocr():
    for name in _EXPECTED_PAGES:
        gt = json.loads((GT / f"{name}.json").read_text())
        assert set(gt) >= {"name", "category", "language", "text", "lines", "scored", "source"}
        assert gt["name"] == name
        assert "synthetic" in gt["source"] and "exact ground truth" in gt["source"]
        # authored text: no OCR-derived artefacts and NFC-normalised
        import unicodedata

        assert unicodedata.normalize("NFC", gt["text"]) == gt["text"]


def test_latin_coverage_is_unscored_and_primary_langs_are_scored():
    assert json.loads((GT / "latin_coverage_01.json").read_text())["scored"] is False
    for name in ("pt_diacritics_01", "en_text_01", "es_diacritics_01", "es_numeric_01"):
        assert json.loads((GT / f"{name}.json").read_text())["scored"] is True


def test_benchmark_run_does_not_regenerate_or_mutate_the_corpus():
    before = {p.name: _sha256(p) for p in sorted(CORPUS.glob("*.png"))}
    before_gt = {p.name: _sha256(p) for p in sorted(GT.glob("*.json"))}

    from benchmarks.ocr.run import run_benchmark

    run_benchmark()

    after = {p.name: _sha256(p) for p in sorted(CORPUS.glob("*.png"))}
    after_gt = {p.name: _sha256(p) for p in sorted(GT.glob("*.json"))}
    assert after == before, "benchmark run modified corpus PNGs"
    assert after_gt == before_gt, "benchmark run modified ground-truth JSONs"


def test_manifest_records_generation_environment():
    header = MANIFEST.read_text()
    assert "frozen" in header.lower()
    assert "Arial.ttf" in header
    assert "re-baselined" in header or "re-baseline" in header
