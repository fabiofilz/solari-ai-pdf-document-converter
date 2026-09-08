"""T031 — failing-first tests for the reconciliation non-rewrite guard (GREEN owner: **T033**).

The guard (research §21d, FR-061a / FR-061b, SC-020) is a **hard programmatic safety
boundary**, independent of whether the LLM response looks reasonable:

* an LLM-selected literal is accepted **only** when it is byte-identical to one of the
  source-backed candidate values;
* an LLM-selected reading order is accepted **only** when it exactly equals a candidate
  reading order or the explicitly permitted geometry-derived order;
* the guard never trims, case-folds, normalises Unicode, collapses whitespace, normalises
  punctuation, repairs spelling / OCR, combines, splits, or paraphrases — a near-miss is
  rejected, not "fixed";
* a rejection leaves the conflict **unresolved** and routes it to Human Review
  (``HUMAN_REVIEW_REQUIRED`` — FR-061b); the guard does not implement that workflow.
"""

from __future__ import annotations


def _guard():
    import solari_converter.reconcile.guard as guard  # GREEN owner: T033

    return guard


# --------------------------------------------------------------------------------------
# literal guard
# --------------------------------------------------------------------------------------


def test_exact_literal_candidate_is_accepted() -> None:
    g = _guard()
    res = g.guard_literal(
        selected_value="Cláusula 4ª",
        candidate_values=["Cláusula 4ª", "Clausula 4a"],
    )
    assert isinstance(res, g.GuardAccept)
    assert res.value == "Cláusula 4ª"  # byte-identical to the supplied candidate


def test_byte_different_literal_is_rejected() -> None:
    g = _guard()
    res = g.guard_literal(selected_value="Clausula 4a", candidate_values=["Cláusula 4ª"])
    assert isinstance(res, g.GuardReject)


def test_whitespace_different_literal_is_rejected() -> None:
    g = _guard()
    for bad in ["foo  bar", "foo\tbar", "foo bar ", " foo bar", "foo\nbar"]:
        res = g.guard_literal(selected_value=bad, candidate_values=["foo bar"])
        assert isinstance(res, g.GuardReject), bad


def test_punctuation_different_literal_is_rejected() -> None:
    g = _guard()
    res = g.guard_literal(
        selected_value="Total: R$ 1.234,56", candidate_values=["Total R$ 1.234,56"]
    )
    assert isinstance(res, g.GuardReject)
    res2 = g.guard_literal(selected_value="art 12", candidate_values=["art. 12"])
    assert isinstance(res2, g.GuardReject)


def test_unicode_normalisation_difference_is_rejected() -> None:
    g = _guard()
    composed = "café"          # café — e-acute as one codepoint
    decomposed = "café"       # café — e + combining acute; same glyph, different bytes
    assert composed != decomposed
    res = g.guard_literal(selected_value=decomposed, candidate_values=[composed])
    assert isinstance(res, g.GuardReject)


def test_invented_non_candidate_literal_is_rejected() -> None:
    g = _guard()
    res = g.guard_literal(
        selected_value="A PLAUSIBLE BUT INVENTED VALUE",
        candidate_values=["value one", "value two"],
    )
    assert isinstance(res, g.GuardReject)


# --------------------------------------------------------------------------------------
# reading-order guard
# --------------------------------------------------------------------------------------


def test_exact_candidate_reading_order_is_accepted() -> None:
    g = _guard()
    res = g.guard_order(
        selected_order=["s1", "s2", "s3"],
        candidate_orders=[["s1", "s2", "s3"], ["s2", "s1", "s3"]],
    )
    assert isinstance(res, g.GuardAccept)
    assert res.order == ["s1", "s2", "s3"]


def test_geometry_derived_reading_order_is_accepted() -> None:
    g = _guard()
    res = g.guard_order(
        selected_order=["s3", "s1", "s2"],
        candidate_orders=[["s1", "s2", "s3"]],
        geometry_order=["s3", "s1", "s2"],
    )
    assert isinstance(res, g.GuardAccept)


def test_unsupported_reading_order_is_rejected() -> None:
    g = _guard()
    res = g.guard_order(
        selected_order=["s2", "s3", "s1"],
        candidate_orders=[["s1", "s2", "s3"], ["s2", "s1", "s3"]],
        geometry_order=["s1", "s2", "s3"],
    )
    assert isinstance(res, g.GuardReject)


def test_guard_does_not_sort_to_fix_an_unsupported_order() -> None:
    g = _guard()
    res = g.guard_order(
        selected_order=["s1", "s3", "s2"],
        candidate_orders=[["s1", "s2", "s3"]],
    )
    assert isinstance(res, g.GuardReject)


# --------------------------------------------------------------------------------------
# rejection -> unresolved -> HUMAN_REVIEW_REQUIRED
# --------------------------------------------------------------------------------------


def test_literal_rejection_signals_human_review_required() -> None:
    g = _guard()
    res = g.guard_literal(selected_value="nope", candidate_values=["yes"])
    assert isinstance(res, g.GuardReject)
    assert res.outcome == g.HUMAN_REVIEW_REQUIRED
    assert res.resolved is False


def test_order_rejection_signals_human_review_required() -> None:
    g = _guard()
    res = g.guard_order(selected_order=["b", "a"], candidate_orders=[["a", "b"]])
    assert isinstance(res, g.GuardReject)
    assert res.outcome == g.HUMAN_REVIEW_REQUIRED
    assert res.resolved is False
