"""Human-review models (T024).

Three record shapes for the HUMAN_REVIEW_REQUIRED workflow (FR-062a / FR-062d / FR-068 /
FR-070 / FR-075 / FR-076):

* ``HumanReviewItem`` + ``HumanReviewQueue`` — the per-run queue
  (``human-review-queue.schema.json`` v2.1). ``run_state`` is a **derived** field: this
  model only carries the slot; the trivial ``"unresolved"`` value is written by
  ``reconcile/human_review`` (T061) and the full 5-state precedence is derived by
  ``review/session`` (T143).
* ``CandidateEvidence`` — the shared candidate shape reused by the queue, the resolution
  store, and (T141) the verification models (L3 / L4).
* ``HumanReviewResolution`` — one append-only resolution-store line
  (``human-review-resolution.schema.json`` v2.1). **This model defines and validates the
  content-bound ``resolution_id`` formula and the three ``selected`` shapes.** The store
  (``reconcile/resolutions.py`` — T030) is the *only* component that assigns
  ``sequence_index`` and computes/persists ``resolution_id`` from the canonical payload —
  no duplicated algorithm.
"""

from __future__ import annotations

import hashlib
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from solari_converter.run_identity import canonical_json

__all__ = [
    "CandidateEvidence",
    "StructuralContext",
    "HumanReviewItem",
    "HumanReviewQueue",
    "HumanReviewResolution",
    "compute_resolution_id",
    "RUN_STATES",
]

BBox = tuple[float, float, float, float]

# Precedence order (M11 / research §22.4); index 0 wins first.
RUN_STATES: tuple[str, ...] = (
    "unresolved",
    "delivery_blocked_verification_failed",
    "delivered",
    "authorized",
    "resolved_unauthorized",
)


class CandidateEvidence(BaseModel):
    """One candidate shown to the reviewer (FR-062a / FR-062d / FR-075). Shared shape."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    technique: str = Field(min_length=1)
    value: str | None = None
    order: list[str] | None = None
    ocr_confidence: float | None = None
    provenance_label: str | None = Field(
        default=None,
        description="FR-075 human-readable source label, e.g. 'layout path (docling), p.5'",
    )


class StructuralContext(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    section_path: list[str] | None = None
    table_id: str | None = None
    row: int | None = Field(default=None, ge=1)
    column: int | None = Field(default=None, ge=1)


class HumanReviewItem(BaseModel):
    """An explicit reconciliation state — a conflict whose automatic confidence fell below
    threshold, or whose LLM selection was guard-rejected (FR-067 / FR-061b)."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, description="deterministic from the applicability key")
    conflict_type: Literal["literal_content", "reading_order"]
    status: Literal["open", "resolved"] = "open"
    physical_page: int = Field(ge=1)
    region_bboxes: list[BBox] = Field(min_length=1)
    contributing_sources: list[str] = Field(min_length=1)
    reason: str = Field(min_length=1)
    confidence: float | None = Field(default=None, ge=0, le=1)
    candidates: list[CandidateEvidence] = Field(min_length=1)
    # --- optional FR-075 presentation fields ---
    markdown_line: int | None = Field(default=None, ge=1)
    markdown_column: int | None = Field(default=None, ge=1)
    segment_ids: list[str] | None = None
    segment_refs: list[str] | None = None
    structural_context: StructuralContext | None = None
    source_context_before: str | None = None
    source_context_after: str | None = None

    @model_validator(mode="after")
    def _reading_order_needs_segment_ids(self) -> HumanReviewItem:
        if self.conflict_type == "reading_order" and not self.segment_ids:
            raise ValueError("reading_order item requires `segment_ids` (FR-062d)")
        return self


class HumanReviewQueue(BaseModel):
    model_config = ConfigDict(extra="forbid")

    record_type: Literal["human_review_queue"] = "human_review_queue"
    schema_version: Literal["2.1"] = "2.1"
    run_id: str = Field(pattern=r"^[a-f0-9]{16}$")
    tool_version: str = Field(min_length=1)
    source_pdf: str = Field(min_length=1)
    source_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    page_selection: str = Field(min_length=1)
    items: list[HumanReviewItem] = Field(default_factory=list)
    run_state: Literal[
        "unresolved", "delivery_blocked_verification_failed", "delivered",
        "authorized", "resolved_unauthorized",
    ]
    summary: dict[str, int]

    @model_validator(mode="after")
    def _summary_matches_items(self) -> HumanReviewQueue:
        want = {
            "open": sum(1 for it in self.items if it.status == "open"),
            "resolved": sum(1 for it in self.items if it.status == "resolved"),
        }
        if self.summary != want:
            raise ValueError(f"summary {self.summary} does not match item counts {want}")
        return self


# --- resolution ------------------------------------------------------------------


def _canonical_selected(selected: dict[str, Any]) -> dict[str, Any]:
    """The normalised decision payload the ``resolution_id`` digest is taken over
    (research §22.2): ``{mode, value}`` for a literal decision, ``{order}`` for a
    reading-order decision. Provenance fields (``from_technique`` / ``manually_verified``)
    are NOT part of the decision *content*."""
    if "order" in selected:
        return {"order": list(selected["order"])}
    return {"mode": selected["mode"], "value": selected["value"]}


def compute_resolution_id(
    *, applicability_key: str, sequence_index: int, selected: dict[str, Any]
) -> str:
    """``sha256(canonical_json({applicability_key, sequence_index, selected}))[:16]``
    (M1 / research §22.2). A local-store traceability id, not an integrity digest."""
    payload = {
        "applicability_key": applicability_key,
        "sequence_index": sequence_index,
        "selected": _canonical_selected(selected),
    }
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()[:16]


class HumanReviewResolution(BaseModel):
    """One append-only resolution-store line. Content-bound ``resolution_id`` (M1);
    ``sequence_index`` is the sole authority for "currently-applicable" (H6)."""

    model_config = ConfigDict(extra="forbid")

    record_type: Literal["human_review_resolution"] = "human_review_resolution"
    schema_version: Literal["2.1"] = "2.1"
    run_id: str = Field(pattern=r"^[a-f0-9]{16}$")
    tool_version: str = Field(min_length=1)
    source_pdf: str = Field(min_length=1)
    source_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    page_selection: str = Field(min_length=1)

    resolution_id: str = Field(pattern=r"^[a-f0-9]{16}$")
    sequence_index: int = Field(ge=0)
    supersedes: str | None = Field(default=None, pattern=r"^[a-f0-9]{16}$")
    applicability_key: str = Field(pattern=r"^[a-f0-9]{64}$")
    review_item_id: str = Field(min_length=1)
    conflict_type: Literal["literal_content", "reading_order"]
    physical_page: int = Field(ge=1)
    region_bboxes: list[BBox] = Field(min_length=1)
    candidates_presented: list[CandidateEvidence] = Field(min_length=1)
    decision_method: Literal["human_confirmed"] = "human_confirmed"
    selected: dict[str, Any]
    reviewer_note: str | None = None

    @model_validator(mode="after")
    def _selected_shape_and_content_bound_id(self) -> HumanReviewResolution:
        sel = self.selected
        if self.conflict_type == "reading_order":
            order = sel.get("order")
            if set(sel) != {"order"} or not isinstance(order, list) or not order:
                raise ValueError(
                    "reading-order `selected` must be exactly {'order': [segment_id, ...]}"
                )
        else:  # literal_content
            if sel.get("mode") not in {"select", "entered"} or "value" not in sel:
                raise ValueError("literal `selected` must carry mode ∈ {select, entered} and value")
            if "manually_verified" not in sel:
                raise ValueError("literal `selected` must carry `manually_verified`")
            if sel["mode"] == "entered" and sel["manually_verified"] is not True:
                raise ValueError("mode='entered' requires manually_verified=true (FR-068)")
            extra = set(sel) - {"mode", "value", "manually_verified", "from_technique"}
            if extra:
                raise ValueError(f"unexpected keys in literal `selected`: {sorted(extra)}")

        expected = compute_resolution_id(
            applicability_key=self.applicability_key,
            sequence_index=self.sequence_index,
            selected=sel,
        )
        if self.resolution_id != expected:
            raise ValueError(
                f"resolution_id {self.resolution_id!r} is not content-bound "
                f"(expected {expected!r} for this applicability_key / sequence_index / selected)"
            )
        return self
