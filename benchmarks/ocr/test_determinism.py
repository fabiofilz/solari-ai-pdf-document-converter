"""M1 — the benchmark determinism self-check re-executes OCR on the second pass
(it does not simply reuse cached recognition outputs).
"""

from __future__ import annotations

import pytest

from benchmarks.ocr import run

pytestmark = pytest.mark.benchmark


def test_determinism_selfcheck_reexecutes_ocr_independently(monkeypatch):
    real = run._recognize
    exec_count = {"n": 0}

    def counting(engine, page_stem, language):
        cache_hit = (engine.name, page_stem) in run._OCR_CACHE
        result = real(engine, page_stem, language)
        if not cache_hit:
            exec_count["n"] += 1  # a genuine engine.recognize() call
        return result

    monkeypatch.setattr(run, "_recognize", counting)
    run._OCR_CACHE.clear()

    assert run.determinism_selfcheck() is True

    engines = run.load_engines()
    n_pages = len(list(run.CORPUS_DIR.glob("*.png")))
    # two independent passes, cache cleared before each => every (engine, page)
    # recognised at least twice
    one_pass = len(engines) * n_pages
    assert exec_count["n"] >= 2 * one_pass, (
        f"only {exec_count['n']} real recognitions for "
        f"{len(engines)} engines x {n_pages} pages x 2 passes — cache was reused "
        f"(a cache-backed self-check would show ~{one_pass})"
    )
