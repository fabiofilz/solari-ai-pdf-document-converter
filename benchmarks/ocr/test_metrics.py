"""Failing-first metric-function tests (T011).

These pin the contract of ``benchmarks/ocr/metrics.py`` (implemented by T012).
Until T012 lands, importing ``benchmarks.ocr.metrics`` raises ImportError -> RED.
"""

from __future__ import annotations

import math

import pytest

from benchmarks.ocr import metrics  # RED until T012 creates benchmarks/ocr/metrics.py

pytestmark = pytest.mark.benchmark


def test_cer_exact_and_errors():
    assert metrics.cer("hello world", "hello world") == 0.0
    # one substitution out of 11 chars
    assert math.isclose(metrics.cer("hello world", "hallo world"), 1 / 11, rel_tol=1e-6)
    assert metrics.cer("", "") == 0.0
    assert metrics.cer("abc", "") == 1.0


def test_numeric_token_exact_match():
    ref = "Total R$ 1.234,56 e 12x de R$ 99,90 (2%)"
    assert metrics.numeric_token_exact_match(ref, ref) == 1.0
    # one of the three monetary/number tokens wrong
    hyp = "Total R$ 1.234,56 e 12x de R$ 99.90 (2%)"
    v = metrics.numeric_token_exact_match(ref, hyp)
    assert 0.0 < v < 1.0
    assert metrics.numeric_token_exact_match("no numbers here", "still none") == 1.0


def test_diacritic_accuracy():
    ref = "AÇÃO informações José órfão"
    assert metrics.diacritic_accuracy(ref, ref) == 1.0
    stripped = "ACAO informacoes Jose orfao"
    assert metrics.diacritic_accuracy(ref, stripped) == 0.0
    assert 0.0 < metrics.diacritic_accuracy(ref, "AÇÃO informacoes Jose órfão") < 1.0
    # no diacritics in the reference -> defined as perfect
    assert metrics.diacritic_accuracy("plain ascii", "plain ascii") == 1.0


def test_table_cell_cer():
    ref = ["Bloco A", "12.500,00", "Total"]
    assert metrics.table_cell_cer(ref, ref) == 0.0
    hyp = ["Bloco A", "12.5OO,00", "Total"]  # two char errors in one 9-char cell
    v = metrics.table_cell_cer(ref, hyp)
    assert 0.0 < v < 0.2


def test_reading_order_kendall_tau():
    assert metrics.reading_order_kendall_tau([1, 2, 3, 4], [1, 2, 3, 4]) == 1.0
    assert metrics.reading_order_kendall_tau([1, 2, 3, 4], [4, 3, 2, 1]) == -1.0
    tau = metrics.reading_order_kendall_tau([1, 2, 3, 4], [2, 1, 3, 4])
    assert -1.0 < tau < 1.0


def test_insertion_deletion_rates():
    ins, dele = metrics.insertion_deletion_rates("the quick brown fox", "the quick brown fox")
    assert ins == 0.0 and dele == 0.0
    ins, dele = metrics.insertion_deletion_rates("the quick brown fox", "the quick red brown fox")
    assert ins > 0.0 and dele == 0.0
    ins, dele = metrics.insertion_deletion_rates("the quick brown fox", "the brown fox")
    assert dele > 0.0 and ins == 0.0


def test_language_detection_accuracy():
    assert metrics.language_detection_accuracy([("pt", "pt"), ("en", "en")]) == 1.0
    assert metrics.language_detection_accuracy([("pt", "pt"), ("en", "pt")]) == 0.5
    assert metrics.language_detection_accuracy([]) == 0.0


def test_weighted_total_is_bounded():
    per_metric = {
        "cer": 0.05,
        "numeric_token_exact_match": 0.9,
        "diacritic_accuracy": 1.0,
        "table_cell_cer": 0.02,
        "reading_order_kendall_tau": 0.8,
        "insertion_rate": 0.01,
        "deletion_rate": 0.03,
        "language_detection_accuracy": 1.0,
    }
    total = metrics.weighted_total(per_metric)
    assert 0.0 <= total <= 1.0
