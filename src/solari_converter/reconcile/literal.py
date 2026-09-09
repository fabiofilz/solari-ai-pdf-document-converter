"""Per-group literal-content decision dispatch (T060).

For one :class:`~solari_converter.reconcile.align.AlignedSegmentGroup` this decides how the
competing verbatim candidate values are reconciled and emits a
:class:`~solari_converter.model.reconciliation.ReconciliationDecision` (research §21b / §21d,
SC-020, block brief §8):

1. a **replayed** stored human decision (the engine passes it when the applicability key
   matched) → ``human_confirmed`` (``replayed: true``);
2. a **single-member** group, or a group whose only differences are **non-material** under
   the frozen group policy (:func:`confidence.classify_group_diff` — whitespace, or a
   native/OCR case difference where the native evidence agrees) → ``deterministic_agreement``
   on a **verbatim** candidate value chosen by the *narrowed* technique precedence;
3. a **material** disagreement → deterministic confidence
   (:func:`confidence.literal_confidence`, formula unchanged):
   * ``< reconcile_confidence_threshold`` → HUMAN_REVIEW_REQUIRED (``below_threshold``);
   * ``>= threshold`` and the run established **no usable LLM** → HUMAN_REVIEW_REQUIRED
     (``no_llm``) — never a guess;
   * ``>= threshold`` and LLM-capable → :func:`llm_select.select_literal` (two calls +
     exact guard) → an accepted **existing** candidate value (``llm_selected``), or
     HUMAN_REVIEW_REQUIRED (``llm_flip`` / ``guard_rejected``).

The technique precedence never resolves a material disagreement by itself; it only picks
the representative member among already-non-material or LLM-selected-equal evidence
(block brief §4 / §8). A mid-run ``LLMUnavailable`` propagates unchanged (M4).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from solari_converter.model.reconciliation import (
    DecisionCandidate,
    ReconciliationDecision,
    compute_decision_id,
)
from solari_converter.reconcile.align import AlignedSegmentGroup
from solari_converter.reconcile.confidence import (
    group_material_disagreement,
    literal_confidence,
    pick_verbatim,
    preferred_technique,
)
from solari_converter.reconcile.llm_select import (
    HUMAN_REVIEW_REQUIRED,
    RESOLVED,
    DecisionResult,
    select_literal,
)
from solari_converter.reconcile.resolutions import compute_applicability_key

__all__ = [
    "reconcile_literal",
    "literal_applicability_key",
    "HUMAN_REVIEW_REQUIRED",
    "RESOLVED",
    "DecisionResult",
]

BBox = tuple[float, float, float, float]


def literal_applicability_key(
    group: AlignedSegmentGroup,
    *,
    source_sha256: str = "0" * 64,
    config_subset: Mapping[str, Any] | None = None,
) -> str:
    """The literal applicability key for ``group`` (FR-071) — the aligned candidate-value
    set is the members' verbatim texts. Same computation :func:`reconcile_literal` uses."""
    return compute_applicability_key(
        source_sha256=source_sha256,
        conflict_type="literal_content",
        physical_page=group.physical_page,
        region_bboxes=[tuple(float(c) for c in group.region_bbox)],
        candidate_values=[m.text for m in group.members],
        config_subset=config_subset or {},
    )


def reconcile_literal(
    group: AlignedSegmentGroup,
    *,
    confidence_threshold: float = 0.75,
    llm_client: Any | None = None,
    llm_capable: bool = False,
    source_sha256: str = "0" * 64,
    config_subset: Mapping[str, Any] | None = None,
    replay: Mapping[str, Any] | None = None,
) -> DecisionResult:
    """Reconcile the literal content of ``group``. See the module docstring for the
    routing. ``replay`` is ``{"applicability_key": <64hex>, "selected": {...}}`` — the
    currently-applicable stored resolution when its key matched this group."""
    members = list(group.members)
    page = group.physical_page
    region_bboxes: list[BBox] = [tuple(float(c) for c in group.region_bbox)]
    cand_values = [m.text for m in members]
    contributing = sorted({m.technique for m in members})
    cand_reprs: list[list[Any]] = [[m.technique, m.text] for m in members]
    cand_evidence = [
        {"technique": m.technique, "value": m.text, "ocr_confidence": m.source.ocr_confidence}
        for m in members
    ]

    key = compute_applicability_key(
        source_sha256=source_sha256,
        conflict_type="literal_content",
        physical_page=page,
        region_bboxes=region_bboxes,
        candidate_values=cand_values,
        config_subset=config_subset or {},
    )

    def _resolved(
        method: str,
        selected: dict[str, Any],
        *,
        confidence: float | None = None,
        flip: dict[str, Any] | None = None,
        replayed: bool | None = None,
        resolution_ref: str | None = None,
    ) -> DecisionResult:
        did = compute_decision_id(
            conflict_type="literal_content", physical_page=page,
            scope_ids=[group.group_id], candidate_reprs=cand_reprs,
            selected={"value": selected["value"]},
        )
        decision = ReconciliationDecision(
            decision_id=did,
            conflict_type="literal_content",
            scope={"page": page, "bbox": list(region_bboxes[0])},
            candidates=[
                DecisionCandidate(
                    technique=m.technique, value=m.text,
                    ocr_confidence=m.source.ocr_confidence,
                )
                for m in members
            ],
            method=method,
            selected=selected,
            confidence=confidence,
            llm_flip_check=flip,
            resolution_ref=resolution_ref,
            replayed=replayed,
        )
        return DecisionResult(
            outcome=RESOLVED, conflict_type="literal_content", decision_id=did,
            physical_page=page, region_bboxes=region_bboxes,
            candidates_evidence=cand_evidence, contributing_sources=contributing,
            applicability_key=key, decision=decision, confidence=confidence,
            replayed=bool(replayed),
        )

    def _review(reason: str, confidence: float | None = None) -> DecisionResult:
        did = compute_decision_id(
            conflict_type="literal_content", physical_page=page,
            scope_ids=[group.group_id], candidate_reprs=cand_reprs, selected=None,
        )
        return DecisionResult(
            outcome=HUMAN_REVIEW_REQUIRED, conflict_type="literal_content", decision_id=did,
            physical_page=page, region_bboxes=region_bboxes,
            candidates_evidence=cand_evidence, contributing_sources=contributing,
            applicability_key=key, review_reason=reason, confidence=confidence,
        )

    def _representative_technique(value: str) -> str:
        carriers = [m.technique for m in members if m.text == value]
        return preferred_technique(carriers) if carriers else members[0].technique

    # 0) replay a stored human decision
    if replay is not None:
        return _resolved(
            "human_confirmed", {"value": replay["selected"]["value"], "from": "human"},
            replayed=True, resolution_ref=replay["applicability_key"],
        )

    # 1) trivial / non-material -> deterministic agreement on a verbatim candidate
    if len(members) == 1:
        return _resolved(
            "deterministic_agreement",
            {"value": members[0].text, "from": members[0].technique},
        )
    if not group_material_disagreement(group):
        picked = pick_verbatim(group)
        return _resolved(
            "deterministic_agreement",
            {"value": picked, "from": _representative_technique(picked)},
        )

    # 2) material disagreement -> deterministic confidence -> LLM tier / HUMAN_REVIEW
    conf = literal_confidence(group)
    if conf < confidence_threshold:
        return _review("below_threshold", conf)
    if not llm_capable or llm_client is None:
        return _review("no_llm", conf)

    sel = select_literal(
        candidate_values=cand_values, llm_client=llm_client, physical_page=page,
    )
    if sel.reason == "llm_flip":
        return _review("llm_flip", conf)
    if not sel.accepted:
        return _review("guard_rejected", conf)
    return _resolved(
        "llm_selected", {"value": sel.value, "from": _representative_technique(sel.value)},
        confidence=conf, flip={"calls": 2, "agreed": True},
    )
