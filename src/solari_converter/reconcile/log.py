"""Pure assembly of the reconciliation log (T062 / M5).

No I/O. Given the per-scope :class:`~solari_converter.reconcile.llm_select.DecisionResult`
list, the aligned groups and the alignment thresholds, :func:`assemble_log` builds the
:class:`~solari_converter.reports.reconciliation_log.ReconciliationLog` model
(``human_confirmed`` entries carry the store ``resolution_ref`` + ``replayed`` flag —
FR-057a). Persisting it (the ``.json`` + ``.md`` dual emit) is ``reconcile/engine.py``.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from solari_converter.reconcile.align import (
    IOU_THRESHOLD,
    JACCARD_TIEBREAK_THRESHOLD,
    AlignedSegmentGroup,
)
from solari_converter.reconcile.llm_select import RESOLVED, DecisionResult
from solari_converter.reports.reconciliation_log import (
    AlignmentSummary,
    LogCandidate,
    LogDecision,
    LogFlipCheck,
    LogRegion,
    LogSummary,
    LogUnresolved,
    ReconciliationLog,
)

__all__ = ["assemble_log", "SUMMARY_KEYS"]

SUMMARY_KEYS: tuple[str, ...] = (
    "literal_deterministic", "literal_llm", "literal_human",
    "order_deterministic", "order_llm", "order_human", "unresolved",
)

_BUCKET = {
    "deterministic_agreement": "deterministic",
    "llm_selected": "llm",
    "human_confirmed": "human",
}


def assemble_log(
    *,
    envelope: Mapping[str, Any],
    groups: Sequence[AlignedSegmentGroup],
    results: Sequence[DecisionResult],
    review_item_ids: Mapping[str, str],
    iou_threshold: float = IOU_THRESHOLD,
    jaccard_threshold: float = JACCARD_TIEBREAK_THRESHOLD,
) -> ReconciliationLog:
    """Build the ``ReconciliationLog`` from reconciliation output. ``review_item_ids`` maps
    an unresolved ``decision_id`` to the raised queue-item id."""
    decisions: list[LogDecision] = []
    unresolved: list[LogUnresolved] = []
    for r in results:
        if r.outcome == RESOLVED and r.decision is not None:
            decisions.append(_log_decision(r))
        else:
            unresolved.append(
                LogUnresolved(
                    decision_id=r.decision_id,
                    conflict_type=r.conflict_type,
                    reason=r.review_reason or "below_threshold",
                    review_item_id=review_item_ids[r.decision_id],
                )
            )

    return ReconciliationLog(
        **dict(envelope),
        alignment_summary=AlignmentSummary(
            groups=len(groups),
            single_candidate_groups=sum(1 for g in groups if len(g.members) == 1),
            iou_threshold=iou_threshold,
            jaccard_threshold=jaccard_threshold,
        ),
        decisions=decisions,
        unresolved=unresolved,
        summary=_summary(decisions, unresolved),
    )


def _log_decision(r: DecisionResult) -> LogDecision:
    d = r.decision
    assert d is not None
    return LogDecision(
        decision_id=d.decision_id,
        conflict_type=d.conflict_type,
        scope=LogRegion(**dict(d.scope)),
        candidates=[
            LogCandidate(
                technique=c.technique, value=c.value, order=c.order,
                ocr_confidence=c.ocr_confidence,
            )
            for c in d.candidates
        ],
        method=d.method,
        selected=dict(d.selected),
        confidence=d.confidence,
        llm_flip_check=LogFlipCheck(**d.llm_flip_check) if d.llm_flip_check else None,
        resolution_ref=d.resolution_ref,
        replayed=d.replayed,
    )


def _summary(
    decisions: Sequence[LogDecision], unresolved: Sequence[LogUnresolved]
) -> LogSummary:
    counts = dict.fromkeys(SUMMARY_KEYS, 0)
    for d in decisions:
        kind = "literal" if d.conflict_type == "literal_content" else "order"
        counts[f"{kind}_{_BUCKET[d.method]}"] += 1
    counts["unresolved"] = len(unresolved)
    return LogSummary(**counts)
