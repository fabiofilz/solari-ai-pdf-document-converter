"""Reconciliation orchestrator — stage 2 (T064).

The frozen sequence (research §21, block brief §15):

1. receive the independent :class:`ExtractionCandidate`s (stage 1 output);
2. :func:`align` them into :class:`AlignedSegmentGroup`s;
3. for every group / physical page, look up an applicable stored Human Review resolution
   (``ResolutionStore.replay_for`` — an exact applicability-key match, inherently scoped to
   the current source + config, H1) and **replay** it as ``human_confirmed`` where found;
4. literal reconciliation per group (:func:`reconcile_literal`);
5. reading-order reconciliation **per physical page** (:func:`reconcile_order`) — the T058
   mixed-page guard is respected, cross-page ordering is never attempted;
6. accumulate every decision / unresolved item **in memory**;
7. if any conflict is unresolved → assemble the reconciliation log, build the Human Review
   queue (``run_state: unresolved``), persist **both**, and stop — **no CED**;
8. else → assemble + persist the reconciliation log, build + persist the CED.

Logical reconciliation artifacts are written **only after** the whole computation has
completed (a success, or an intentional unresolved outcome). A mid-run ``LLMUnavailable``
propagates out of this function **before any write** — the log / queue / CED from that
failed attempt are never persisted, and the mode is never silently downgraded (M4).
``RunContext`` persistence is **not** done here — the orchestrating ``pipeline/extract``
(T079) owns it.
"""

from __future__ import annotations

import os
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from solari_converter import artifacts_io
from solari_converter.model.candidate import ExtractionCandidate
from solari_converter.model.canonical import CanonicalExtractedDocument
from solari_converter.reconcile.align import AlignedSegmentGroup, align
from solari_converter.reconcile.canonical_build import (
    build_canonical,
    persist_canonical,
    representative_member,
)
from solari_converter.reconcile.human_review import (
    assemble_queue,
    raise_literal_item,
    raise_reading_order_item,
)
from solari_converter.reconcile.literal import literal_applicability_key, reconcile_literal
from solari_converter.reconcile.llm_select import (
    HUMAN_REVIEW_REQUIRED,
    RESOLVED,
    DecisionResult,
    reading_order_applicability_key,
    reconcile_order,
)
from solari_converter.reconcile.log import assemble_log
from solari_converter.reports.reconciliation_log import ReconciliationLog

__all__ = ["ReconcileOutcome", "reconcile", "REPLAY_APPLICABILITY_CONFIG_KEYS"]

#: The FR-071 / §22.2 applicability-key config subset — exactly these four settings.
REPLAY_APPLICABILITY_CONFIG_KEYS = (
    "ocr_engine",
    "ocr_languages_override",
    "ocr_confidence_threshold",
    "enabled_extraction_paths",
)

_REASON_PHRASE = {
    "below_threshold": "material disagreement below the reconcile confidence threshold",
    "guard_rejected": "the LLM selection was not an exact source-backed candidate",
    "llm_flip": "the two LLM selection calls disagreed (flip check)",
    "no_llm": "material disagreement and no local LLM was available this run",
}


@dataclass(frozen=True)
class ReconcileOutcome:
    human_review_required: bool
    log: ReconciliationLog
    canonical: CanonicalExtractedDocument | None
    queue: Any | None
    decisions: list[DecisionResult]
    written: list[Path] = field(default_factory=list)
    run_state: str | None = None


def applicability_config_subset(config_subset: Mapping[str, Any]) -> dict[str, Any]:
    """Reduce a config mapping to the four FR-071 applicability-key keys."""
    return {k: config_subset.get(k) for k in REPLAY_APPLICABILITY_CONFIG_KEYS}


def reconcile(
    *,
    candidates: Iterable[ExtractionCandidate],
    envelope: Mapping[str, Any],
    source_sha256: str,
    config_subset: Mapping[str, Any],
    reconcile_confidence_threshold: float = 0.75,
    store: Any | None = None,
    llm_client: Any | None = None,
    llm_capable: bool = False,
    output_dir: str | os.PathLike[str],
    base: str,
) -> ReconcileOutcome:
    """Run stage-2 reconciliation over ``candidates`` and persist its artifacts under
    ``output_dir`` as ``<base>.reconciliation-log`` / ``<base>.human-review-queue`` /
    ``<base>.canonical-extracted-document``. ``config_subset`` is the extract-stage
    output-affecting config (only its four FR-071 keys feed applicability)."""
    candidates = list(candidates)
    app_cfg = applicability_config_subset(config_subset)
    groups = align(candidates)
    id_map = {g.group_id: representative_member(g).segment_id for g in groups}

    # --- literal reconciliation (all in memory) ---------------------------------
    literal_results: dict[str, DecisionResult] = {}
    for g in groups:
        key = literal_applicability_key(
            g, source_sha256=source_sha256, config_subset=app_cfg
        )
        replay = _replay(store, key)
        literal_results[g.group_id] = reconcile_literal(
            g,
            confidence_threshold=reconcile_confidence_threshold,
            llm_client=llm_client,
            llm_capable=llm_capable,
            source_sha256=source_sha256,
            config_subset=app_cfg,
            replay=replay,
        )

    # --- reading-order reconciliation, per physical page -----------------------
    order_results: list[DecisionResult] = []
    page_orders: dict[int, list[str]] = {}
    for page in sorted({g.physical_page for g in groups}):
        page_groups = [g for g in groups if g.physical_page == page]
        okey = reading_order_applicability_key(
            page_groups, id_map=id_map, source_sha256=source_sha256, config_subset=app_cfg
        )
        oreplay = _replay(store, okey)
        r = reconcile_order(
            page_groups,
            id_map=id_map,
            confidence_threshold=reconcile_confidence_threshold,
            llm_client=llm_client,
            llm_capable=llm_capable,
            source_sha256=source_sha256,
            config_subset=app_cfg,
            replay=oreplay,
        )
        order_results.append(r)
        if r.outcome == RESOLVED and r.decision is not None:
            page_orders[page] = list(r.decision.selected["order"])

    all_results = list(literal_results.values()) + order_results
    unresolved = [r for r in all_results if r.outcome == HUMAN_REVIEW_REQUIRED]

    _assert_replays_in_scope(store, source_sha256, app_cfg, all_results)

    out_dir = Path(output_dir)
    if unresolved:
        return _stop_for_review(
            all_results, unresolved, groups, envelope, out_dir, base
        )
    return _build_delivery(
        all_results, literal_results, groups, page_orders, candidates,
        envelope, out_dir, base,
    )


# --- helpers -----------------------------------------------------------------


def _replay(store: Any | None, applicability_key: str) -> dict[str, Any] | None:
    if store is None:
        return None
    rec = store.replay_for(applicability_key)
    if rec is None:
        return None
    return {"applicability_key": rec.applicability_key, "selected": dict(rec.selected)}


def _assert_replays_in_scope(
    store: Any | None,
    source_sha256: str,
    app_cfg: Mapping[str, Any],
    results: Sequence[DecisionResult],
) -> None:
    """Every replayed resolution must belong to the scoped applicable set used for this
    source + config identity (H1 / block brief §15). ``replay_for`` already matches on the
    exact current-context key, so this is a defensive cross-check."""
    replayed = {r.applicability_key for r in results if r.replayed}
    if not replayed or store is None:
        return
    scoped = set(
        store.applicable_index(source_sha256=source_sha256, config_subset=dict(app_cfg))
    )
    stale = replayed - scoped
    if stale:
        raise AssertionError(
            f"replayed resolution(s) not in the scoped applicable set: {sorted(stale)}"
        )


def _raise_item(r: DecisionResult) -> Any:
    reason = _REASON_PHRASE.get(r.review_reason or "", r.review_reason or "unresolved")
    if r.conflict_type == "reading_order":
        return raise_reading_order_item(
            applicability_key=r.applicability_key,
            physical_page=r.physical_page,
            region_bboxes=r.region_bboxes,
            candidates_evidence=r.candidates_evidence,
            segment_ids=r.segment_ids or [],
            contributing_sources=r.contributing_sources,
            reason=reason,
            confidence=r.confidence,
            segment_refs=r.segment_ids,
        )
    return raise_literal_item(
        applicability_key=r.applicability_key,
        physical_page=r.physical_page,
        region_bboxes=r.region_bboxes,
        candidates_evidence=r.candidates_evidence,
        contributing_sources=r.contributing_sources,
        reason=reason,
        confidence=r.confidence,
    )


def _stop_for_review(
    all_results: Sequence[DecisionResult],
    unresolved: Sequence[DecisionResult],
    groups: Sequence[AlignedSegmentGroup],
    envelope: Mapping[str, Any],
    out_dir: Path,
    base: str,
) -> ReconcileOutcome:
    items = []
    review_item_ids: dict[str, str] = {}
    for r in unresolved:
        item = _raise_item(r)
        items.append(item)
        review_item_ids[r.decision_id] = item.id

    log = assemble_log(
        envelope=envelope, groups=groups, results=all_results,
        review_item_ids=review_item_ids,
    )
    queue = assemble_queue(items, envelope=envelope)

    written: list[Path] = []
    written += artifacts_io.write_record(out_dir / f"{base}.reconciliation-log", log, emit_md=True)
    written += artifacts_io.write_record(
        out_dir / f"{base}.human-review-queue", queue, emit_md=True
    )
    return ReconcileOutcome(
        human_review_required=True, log=log, canonical=None, queue=queue,
        decisions=list(all_results), written=written, run_state="unresolved",
    )


def _build_delivery(
    all_results: Sequence[DecisionResult],
    literal_results: Mapping[str, DecisionResult],
    groups: Sequence[AlignedSegmentGroup],
    page_orders: Mapping[int, list[str]],
    candidates: Sequence[ExtractionCandidate],
    envelope: Mapping[str, Any],
    out_dir: Path,
    base: str,
) -> ReconcileOutcome:
    log = assemble_log(
        envelope=envelope, groups=groups, results=all_results, review_item_ids={},
    )
    reading_order: list[str] = []
    for page in sorted(page_orders):
        reading_order += page_orders[page]

    ced = build_canonical(
        envelope=envelope,
        groups=groups,
        decisions_by_group={
            gid: r.decision for gid, r in literal_results.items() if r.decision is not None
        },
        accepted_reading_order=reading_order,
        candidates=candidates,
    )

    written: list[Path] = []
    written += artifacts_io.write_record(out_dir / f"{base}.reconciliation-log", log, emit_md=True)
    written.append(persist_canonical(ced, out_dir, base))
    return ReconcileOutcome(
        human_review_required=False, log=log, canonical=ced, queue=None,
        decisions=list(all_results), written=written, run_state=None,
    )
