"""Reconciliation decision model (T023).

Every reconciliation conflict — literal-content or reading-order — is resolved by exactly
one ``ReconciliationDecision`` recording the competing candidates, the method, and the
outcome (FR-057a). The **SC-020 invariant** is enforced here: for an *automatic* decision
(``deterministic_agreement`` / ``llm_selected``) the selected literal value is
byte-identical to some supplied candidate value, and the selected order equals some
candidate order (a real candidate or the synthesized ``geometry`` candidate). A
``human_confirmed`` decision is exempt — the reviewer's confirmed value is authoritative
even when no machine candidate matched (FR-068).

The full ``ReconciliationLog`` record (envelope + summary) is assembled by
``reports/reconciliation_log.py`` (T062).
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from solari_converter.run_identity import canonical_json

__all__ = ["DecisionCandidate", "ReconciliationDecision", "compute_decision_id"]

_AUTOMATIC = {"deterministic_agreement", "llm_selected"}


def compute_decision_id(
    *,
    conflict_type: Literal["literal_content", "reading_order"],
    physical_page: int,
    scope_ids: Sequence[str],
    candidate_reprs: Sequence[Any],
    selected: dict[str, Any] | None,
) -> str:
    """The deterministic 16-hex reconciliation-decision id (Block-2 pinned contract).

    ``payload = {conflict_type, physical_page, scope: sorted scope_ids,
    candidates: sorted candidate reprs, selected: repr | null}`` →
    ``sha256(canonical_json(payload)).hexdigest()[:16]``.

    * a literal candidate repr is ``[technique, exact_literal_value]``;
    * a reading-order candidate repr is ``[technique, [group_id, ...]]`` (geometry uses
      the stable technique id ``"geometry"``);
    * ``selected`` is ``{"value": exact_literal}`` (literal), ``{"order": [group_id, …]}``
      (reading order) or ``None`` (unresolved).

    It **excludes** method, confidence, ``run_id``, timestamps and any random value, so the
    id is stable for the same evidence + result; an unresolved decision (``selected`` null)
    never collides with a resolved one.
    """
    payload = {
        "conflict_type": conflict_type,
        "physical_page": int(physical_page),
        "scope": sorted(scope_ids),
        "candidates": sorted(
            ([r[0], r[1]] for r in candidate_reprs), key=canonical_json
        ),
        "selected": selected,
    }
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()[:16]


class DecisionCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    technique: str = Field(min_length=1)
    value: str | None = None
    order: list[str] | None = None
    ocr_confidence: float | None = None


class ReconciliationDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision_id: str = Field(min_length=1)
    conflict_type: Literal["literal_content", "reading_order"]
    scope: dict[str, Any]
    candidates: list[DecisionCandidate] = Field(min_length=1)
    method: Literal["deterministic_agreement", "llm_selected", "human_confirmed"]
    selected: dict[str, Any]
    confidence: float | None = Field(default=None, ge=0, le=1)
    llm_flip_check: dict[str, Any] | None = None
    resolution_ref: str | None = None
    replayed: bool | None = None

    @model_validator(mode="after")
    def _sc020_invariant(self) -> ReconciliationDecision:
        if self.method not in _AUTOMATIC:
            return self  # human_confirmed is exempt (FR-068)

        if self.conflict_type == "literal_content":
            selected_value = self.selected.get("value")
            candidate_values = [c.value for c in self.candidates if c.value is not None]
            if selected_value not in candidate_values:
                raise ValueError(
                    "SC-020: an automatic literal decision selected a value that is not "
                    f"byte-identical to any candidate ({selected_value!r} ∉ {candidate_values!r})"
                )
        else:  # reading_order
            selected_order = self.selected.get("order")
            candidate_orders = [c.order for c in self.candidates if c.order is not None]
            if list(selected_order or []) not in [list(o) for o in candidate_orders]:
                raise ValueError(
                    "SC-020: an automatic reading-order decision selected an order that is "
                    "not equal to any candidate or geometry-supported order"
                )
        return self
