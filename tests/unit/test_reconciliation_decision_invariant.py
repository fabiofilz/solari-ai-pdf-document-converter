"""T014 — failing-first unit tests for the SC-020 invariant on
``solari_converter.model.reconciliation.ReconciliationDecision``.

GREEN owner: **T023**. SC-020: for ``deterministic_agreement`` and ``llm_selected`` the
selected literal value is **byte-identical** to some ``candidates[].value``, and the
selected order equals some ``candidates[].order`` (a real candidate or the synthesized
``geometry`` candidate). A decision that violates this MUST raise a validation error.
``human_confirmed`` decisions are exempt (the reviewer's confirmed value is authoritative).
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from solari_converter.model.reconciliation import ReconciliationDecision


def _literal(method: str, selected_value: str, candidate_values: list[str]):
    return ReconciliationDecision(
        decision_id="d1",
        conflict_type="literal_content",
        scope={"page": 3, "bbox": [1.0, 2.0, 3.0, 4.0]},
        candidates=[{"technique": f"t{i}", "value": v} for i, v in enumerate(candidate_values)],
        method=method,
        selected={"value": selected_value, "from_technique": "t0"},
    )


def _order(method: str, selected_order: list[str], candidate_orders: list[list[str]]):
    return ReconciliationDecision(
        decision_id="d2",
        conflict_type="reading_order",
        scope={"page": 3, "region_bboxes": [[1.0, 2.0, 3.0, 4.0]]},
        candidates=[
            {"technique": t, "order": o}
            for t, o in zip(["geometry", "docling", "pdfplumber"], candidate_orders, strict=True)
        ],
        method=method,
        selected={"order": selected_order, "from": "geometry"},
    )


def test_deterministic_agreement_with_a_matching_candidate_value_is_valid() -> None:
    d = _literal("deterministic_agreement", "R$ 1.599,80", ["R$ 1.599,80", "R$ 1.599,80"])
    assert d.selected["value"] == "R$ 1.599,80"


def test_llm_selected_with_a_matching_candidate_value_is_valid() -> None:
    _literal("llm_selected", "Option B", ["Option A", "Option B"])


@pytest.mark.parametrize("method", ["deterministic_agreement", "llm_selected"])
def test_automatic_literal_value_not_among_candidates_is_rejected(method: str) -> None:
    with pytest.raises(ValidationError):
        _literal(method, "R$ 1.599.80", ["R$ 1.599,80", "R$ 1,599.80"])


def test_whitespace_difference_is_still_a_violation_for_automatic_decisions() -> None:
    with pytest.raises(ValidationError):
        _literal("deterministic_agreement", "value ", ["value"])  # trailing space added


def test_automatic_order_not_among_candidate_or_geometry_orders_is_rejected() -> None:
    with pytest.raises(ValidationError):
        _order(
            "llm_selected",
            selected_order=["s3", "s1", "s2"],
            candidate_orders=[["s1", "s2", "s3"], ["s1", "s2", "s3"], ["s2", "s1", "s3"]],
        )


def test_automatic_order_equal_to_the_geometry_candidate_is_valid() -> None:
    _order(
        "deterministic_agreement",
        selected_order=["s1", "s2", "s3"],
        candidate_orders=[["s1", "s2", "s3"], ["s2", "s1", "s3"], ["s1", "s2", "s3"]],
    )


def test_human_confirmed_is_exempt_from_the_candidate_membership_check() -> None:
    # The reviewer may enter a value that is not among the machine candidates (FR-068).
    d = ReconciliationDecision(
        decision_id="d3",
        conflict_type="literal_content",
        scope={"page": 1, "bbox": [0.0, 0.0, 1.0, 1.0]},
        candidates=[{"technique": "docling", "value": "wrong-A"},
                    {"technique": "pdfplumber", "value": "wrong-B"}],
        method="human_confirmed",
        selected={"value": "the true value from the PDF", "from_technique": None},
        resolution_ref="a" * 64,
        replayed=False,
    )
    assert d.selected["value"] == "the true value from the PDF"
