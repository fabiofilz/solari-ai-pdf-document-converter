"""Remediation RED tests for the corrected Latin-script OCR Benchmark Gate (T011).

The original ``test_metrics.py`` RED->GREEN history for the 8 metric functions is
unchanged and still stands. These are the *additional* failing-first tests the
2026-09-07 reopening requires. They target behaviour implemented by the amended
T012:

* ``metrics.per_language_aggregate``   — PT/EN/ES per-language aggregation
* ``metrics.evaluate_language_floor``  — deterministic PASS/FAIL against the
  AUTHORITATIVE per-language acceptance floor (``research.md`` §4.1). The
  thresholds and applicability rules live in §4.1 and in
  ``metrics.LANGUAGE_ACCEPTANCE_FLOOR`` — they are **not** restated here.
* ``metrics.language_regression_flags`` — "materially worse for a supported
  primary language" == fails one or more *applicable* §4.1 criteria for that
  language (absolute; never relative to the other engine).

Until T012 adds those, importing the names raises AttributeError -> RED.
"""

from __future__ import annotations

import pytest

from benchmarks.ocr import metrics

pytestmark = pytest.mark.benchmark


# --------------------------------------------------------------------------------------
# per-language aggregation
# --------------------------------------------------------------------------------------

def _page(lang, scored, **m):
    base = {
        "cer": 0.0,
        "diacritic_accuracy": 1.0,
        "numeric_token_exact_match": 1.0,
        "reading_order_kendall_tau": 1.0,
        "insertion_rate": 0.0,
        "deletion_rate": 0.0,
    }
    base.update(m)
    return {"language": lang, "scored": scored, "metrics": base}


def test_per_language_aggregate_buckets_pt_en_es_only():
    pages = [
        _page("pt", True, cer=0.10),
        _page("pt", True, cer=0.20),
        _page("en", True, cer=0.04),
        _page("es", True, cer=0.06),
        _page("mul", False, cer=0.90),   # latin_coverage — excluded
        _page("de", True, cer=0.50),     # not a primary language — excluded
    ]
    agg = metrics.per_language_aggregate(pages)
    assert set(agg) == {"pt", "en", "es"}
    assert agg["pt"]["cer"] == pytest.approx(0.15)          # mean(0.10, 0.20)
    assert "weighted_total" in agg["pt"]
    assert 0.0 <= agg["pt"]["weighted_total"] <= 1.0


def test_per_language_aggregate_ignores_unscored_pages():
    pages = [_page("es", True, cer=0.05), _page("es", False, cer=0.95)]
    agg = metrics.per_language_aggregate(pages)
    assert agg["es"]["cer"] == pytest.approx(0.05)


# --------------------------------------------------------------------------------------
# §4.1 acceptance-floor — deterministic boundary behaviour
# --------------------------------------------------------------------------------------

def _floor():
    f = metrics.LANGUAGE_ACCEPTANCE_FLOOR
    return (
        f["weighted_total_min"],
        f["cer_max"],
        f["diacritic_accuracy_min"],
        f["numeric_token_exact_match_min"],
    )


def _agg(wt, cer, dia, num):
    return {
        "weighted_total": wt,
        "cer": cer,
        "diacritic_accuracy": dia,
        "numeric_token_exact_match": num,
    }


def test_floor_passes_exactly_on_the_boundary():
    wt, cer, dia, num = _floor()
    ev = metrics.evaluate_language_floor(
        _agg(wt, cer, dia, num), diacritic_applicable=True, numeric_applicable=True
    )
    assert ev["pass"] is True
    assert all(c["pass"] for c in ev["criteria"].values() if c["applicable"])


@pytest.mark.parametrize("bump", [1e-9, 1e-6, 1e-3])
def test_floor_fails_just_below_each_boundary(bump):
    wt, cer, dia, num = _floor()
    for agg in (
        _agg(wt - bump, cer, dia, num),
        _agg(wt, cer + bump, dia, num),
        _agg(wt, cer, dia - bump, num),
        _agg(wt, cer, dia, num - bump),
    ):
        ev = metrics.evaluate_language_floor(
            agg, diacritic_applicable=True, numeric_applicable=True
        )
        assert ev["pass"] is False


def test_floor_diacritic_not_applicable_for_english_slice():
    wt, cer, dia, num = _floor()
    # diacritic accuracy is terrible but the slice carries no diacritic ground truth
    ev = metrics.evaluate_language_floor(
        _agg(wt, cer, 0.0, num), diacritic_applicable=False, numeric_applicable=True
    )
    assert ev["criteria"]["diacritic_accuracy"]["applicable"] is False
    assert ev["criteria"]["diacritic_accuracy"]["pass"] is None
    assert ev["pass"] is True


def test_floor_numeric_not_applicable_when_no_numeric_ground_truth():
    wt, cer, dia, num = _floor()
    ev = metrics.evaluate_language_floor(
        _agg(wt, cer, dia, 0.0), diacritic_applicable=True, numeric_applicable=False
    )
    assert ev["criteria"]["numeric_token_exact_match"]["applicable"] is False
    assert ev["pass"] is True


# --------------------------------------------------------------------------------------
# "materially worse" — absolute, per §4.1, never relative to the other engine
# --------------------------------------------------------------------------------------

def test_regression_flag_is_absolute_failure_of_an_applicable_criterion():
    wt, cer, dia, num = _floor()
    good = metrics.evaluate_language_floor(
        _agg(wt, cer, dia, num), diacritic_applicable=True, numeric_applicable=True
    )
    bad = metrics.evaluate_language_floor(
        _agg(wt, cer, dia - 0.05, num), diacritic_applicable=True, numeric_applicable=True
    )
    flags = metrics.language_regression_flags({"pt": bad, "en": good, "es": good})
    assert flags == {"pt": True, "en": False, "es": False}


def test_regression_flag_not_relative_both_bad_still_both_flagged():
    wt, cer, dia, num = _floor()
    worse = metrics.evaluate_language_floor(
        _agg(0.50, cer, dia, num), diacritic_applicable=True, numeric_applicable=True
    )
    also_bad = metrics.evaluate_language_floor(
        _agg(0.60, cer, dia, num), diacritic_applicable=True, numeric_applicable=True
    )
    # the "less bad" engine does NOT become acceptable just because the other is worse
    flags = metrics.language_regression_flags({"pt": worse, "es": also_bad})
    assert flags == {"pt": True, "es": True}
