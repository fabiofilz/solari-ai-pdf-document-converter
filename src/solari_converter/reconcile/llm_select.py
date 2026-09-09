"""Restricted LLM reconciliation selector + reading-order dispatch (T059).

The **selection-only** LLM tier of reconciliation (research §21d / §4a, FR-061a/b, SC-020).
The local LLM is asked exactly one thing — *which of these fixed options* — and its answer
is resolved to an index into a caller-supplied list **in code**. It never generates,
corrects, normalises, paraphrases, rewrites, combines, splits, merges, or invents source
text or a reading order; a response that is not an exact supported option is rejected.

Contents
--------

* :func:`select_literal` / :func:`select_order` — the raw selection-only helpers: build a
  selection prompt, call ``llm_client.select`` **twice** (the §4a flip check), then pass
  the chosen option through the deterministic :mod:`solari_converter.reconcile.guard`.
  Returns an exact existing candidate value / order, or a rejection reason
  (``llm_flip`` when the two calls disagree, ``guard_rejected`` when the choice is invalid
  / unmappable / not an exact supported option).
* :func:`reconcile_order` — the full **reading-order decision dispatch** (the test file's
  "T059 owns … < 0.75 → HUMAN_REVIEW_REQUIRED" contract): deterministic geometric
  resolution → conflict → deterministic confidence → ``< threshold`` HUMAN_REVIEW,
  ``>= threshold`` + no usable LLM → HUMAN_REVIEW (``no_llm``), ``>= threshold`` +
  LLM-capable → :func:`select_order` → exact guard → flip guard → an accepted **existing**
  order or HUMAN_REVIEW.

No persistence, no network beyond the injected loopback ``llm_client``, no CED, no
semantic transformation. A mid-run ``LLMUnavailable`` from the client propagates unchanged
(M4 — the caller fails closed; it is never downgraded to ``no_llm`` or a guess).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from solari_converter.model.reconciliation import (
    DecisionCandidate,
    ReconciliationDecision,
    compute_decision_id,
)
from solari_converter.reconcile.confidence import reading_order_confidence
from solari_converter.reconcile.guard import GuardReject, guard_literal, guard_order
from solari_converter.reconcile.reading_order import (
    ReadingOrderResolution,
    build_candidate_orders,
    geometric_order,
    resolve_reading_order,
)
from solari_converter.reconcile.resolutions import compute_applicability_key
from solari_converter.run_identity import canonical_json

__all__ = [
    "HUMAN_REVIEW_REQUIRED",
    "RESOLVED",
    "SelectionResult",
    "DecisionResult",
    "select_literal",
    "select_order",
    "reconcile_order",
    "reading_order_applicability_key",
]

HUMAN_REVIEW_REQUIRED = "HUMAN_REVIEW_REQUIRED"
RESOLVED = "RESOLVED"

BBox = tuple[float, float, float, float]

# review reasons — the frozen enum shared with reconciliation-log `unresolved[].reason`
_REASON_FLIP = "llm_flip"
_REASON_GUARD = "guard_rejected"
_REASON_BELOW = "below_threshold"
_REASON_NO_LLM = "no_llm"


# --- selection-only helpers ------------------------------------------------------


@dataclass(frozen=True)
class SelectionResult:
    """Outcome of one selection-only LLM interaction (both calls + guard)."""

    accepted: bool
    value: str | None = None
    order: list[str] | None = None
    reason: str | None = None  # "llm_flip" | "guard_rejected" when not accepted


def _selection_context(kind: str, page: int | None) -> str:
    where = f" on physical page {page}" if page else ""
    return (
        f"Two independent extractions disagree on {kind}{where}. Choose exactly one of "
        "the listed options by index. Do not write, edit, merge, split, reorder, or "
        "invent anything — only select."
    )


def select_literal(
    *,
    candidate_values: Sequence[str],
    llm_client: Any,
    physical_page: int | None = None,
) -> SelectionResult:
    """Ask the backend to pick one of ``candidate_values`` by index (issued twice), then
    require the choice to be byte-identical to an existing candidate value."""
    options = [str(v) for v in candidate_values]
    flip = llm_client.select_twice(_selection_context("a literal value", physical_page), options)
    bad = _flip_reason(flip)
    if bad is not None:
        return SelectionResult(accepted=False, reason=bad)
    chosen = options[flip.first.index]
    verdict = guard_literal(selected_value=chosen, candidate_values=options)
    if isinstance(verdict, GuardReject):
        return SelectionResult(accepted=False, reason=_REASON_GUARD)
    return SelectionResult(accepted=True, value=verdict.value)


def select_order(
    *,
    candidate_orders: Sequence[Sequence[str]],
    geometry_order: Sequence[str] | None,
    llm_client: Any,
    physical_page: int | None = None,
) -> SelectionResult:
    """Ask the backend to pick one **supported** reading order by index (issued twice).

    Every candidate order and the geometry-supported order (when present) is a distinct
    canonical selectable option; the model may never construct a new permutation."""
    opts: list[list[str]] = []
    seen: set[tuple[str, ...]] = set()
    supported = list(candidate_orders) + ([geometry_order] if geometry_order else [])
    for order in supported:
        key = tuple(order)
        if key not in seen:
            seen.add(key)
            opts.append(list(order))
    labels = [canonical_json(o) for o in opts]
    flip = llm_client.select_twice(_selection_context("the reading order", physical_page), labels)
    bad = _flip_reason(flip)
    if bad is not None:
        return SelectionResult(accepted=False, reason=bad)
    chosen = opts[flip.first.index]
    verdict = guard_order(
        selected_order=chosen,
        candidate_orders=candidate_orders,
        geometry_order=geometry_order,
    )
    if isinstance(verdict, GuardReject):
        return SelectionResult(accepted=False, reason=_REASON_GUARD)
    return SelectionResult(accepted=True, order=list(verdict.order))


def _flip_reason(flip: Any) -> str | None:
    """``None`` when the two calls agree on a mappable index; else the review reason.

    An unmappable / invalid selection on either call → ``guard_rejected`` (block brief §5);
    two mappable but different selections → ``llm_flip``."""
    if flip.first.index is None or flip.second.index is None:
        return _REASON_GUARD
    if flip.first.index != flip.second.index:
        return _REASON_FLIP
    return None


# --- reading-order decision dispatch --------------------------------------------


@dataclass(frozen=True)
class DecisionResult:
    """A per-scope reconciliation outcome (reading-order here; the literal analogue is
    :func:`solari_converter.reconcile.literal.reconcile_literal`)."""

    outcome: str  # RESOLVED | HUMAN_REVIEW_REQUIRED
    conflict_type: str
    decision_id: str
    physical_page: int
    region_bboxes: list[BBox]
    candidates_evidence: list[dict[str, Any]]
    contributing_sources: list[str]
    applicability_key: str
    decision: ReconciliationDecision | None = None
    review_reason: str | None = None
    confidence: float | None = None
    segment_ids: list[str] | None = None
    replayed: bool = False
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def method(self) -> str | None:
        return self.decision.method if self.decision is not None else None

    @property
    def selected(self) -> dict[str, Any] | None:
        return self.decision.selected if self.decision is not None else None


def _order_shape(groups: Sequence[Any], idmap: Mapping[str, str]) -> dict[str, Any]:
    """The translated reading-order candidate reprs + scope + region for a page's groups."""
    scope_gids = sorted(g.group_id for g in groups)
    region_bboxes: list[BBox] = [tuple(float(c) for c in g.region_bbox) for g in groups]
    full_perms = {
        t: o for t, o in build_candidate_orders(groups).items() if sorted(o) == scope_gids
    }
    geo = geometric_order(groups)
    cand_reprs: list[list[Any]] = [
        [t, [idmap[x] for x in o]] for t, o in sorted(full_perms.items())
    ]
    if geo is not None:
        cand_reprs.append(["geometry", [idmap[x] for x in geo]])
    return {
        "scope_gids": scope_gids,
        "scope_ids": [idmap[x] for x in scope_gids],
        "region_bboxes": region_bboxes,
        "cand_reprs": cand_reprs,
    }


def reading_order_applicability_key(
    groups: Sequence[Any],
    *,
    id_map: Mapping[str, str] | None = None,
    source_sha256: str = "0" * 64,
    config_subset: Mapping[str, Any] | None = None,
) -> str:
    """The reading-order applicability key for a page's groups (FR-071). Uses exactly the
    same translated canonical order reprs :func:`reconcile_order` uses, so the engine can
    look up a stored resolution before deciding."""
    groups = list(groups)
    page = groups[0].physical_page if groups else 1
    idmap = dict(id_map) if id_map else {g.group_id: g.group_id for g in groups}
    shape = _order_shape(groups, idmap)
    return compute_applicability_key(
        source_sha256=source_sha256,
        conflict_type="reading_order",
        physical_page=page,
        region_bboxes=shape["region_bboxes"],
        candidate_values=[canonical_json(r[1]) for r in shape["cand_reprs"]],
        config_subset=config_subset or {},
    )


def reconcile_order(
    groups: Sequence[Any],
    *,
    id_map: Mapping[str, str] | None = None,
    confidence_threshold: float = 0.75,
    llm_client: Any | None = None,
    llm_capable: bool = False,
    source_sha256: str = "0" * 64,
    config_subset: Mapping[str, Any] | None = None,
    replay: Mapping[str, Any] | None = None,
) -> DecisionResult:
    """Reconcile the reading order over one physical page's aligned groups.

    Internally the order is over ``group_id``s; ``id_map`` (``group_id -> segment_id``)
    translates every emitted order / scope id for the engine. Never returns a partial or
    invented order (Block-1 guarantees are preserved)."""
    groups = list(groups)
    page = groups[0].physical_page if groups else 1
    idmap = dict(id_map) if id_map else {g.group_id: g.group_id for g in groups}

    def tr(seq: Sequence[str]) -> list[str]:
        return [idmap[x] for x in seq]

    contributing = sorted({m.technique for g in groups for m in g.members})
    shape = _order_shape(groups, idmap)
    scope_ids = shape["scope_ids"]
    region_bboxes = shape["region_bboxes"]
    cand_reprs = shape["cand_reprs"]
    cand_evidence = [{"technique": r[0], "order": list(r[1])} for r in cand_reprs]

    key = compute_applicability_key(
        source_sha256=source_sha256,
        conflict_type="reading_order",
        physical_page=page,
        region_bboxes=region_bboxes,
        candidate_values=[canonical_json(r[1]) for r in cand_reprs],
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
            conflict_type="reading_order", physical_page=page,
            scope_ids=scope_ids, candidate_reprs=cand_reprs,
            selected={"order": list(selected["order"])},
        )
        decision = ReconciliationDecision(
            decision_id=did,
            conflict_type="reading_order",
            scope={"page": page, "region_bboxes": [list(b) for b in region_bboxes]},
            candidates=[
                DecisionCandidate(technique=r[0], order=list(r[1])) for r in cand_reprs
            ] or [DecisionCandidate(technique="geometry", order=list(selected["order"]))],
            method=method,
            selected=selected,
            confidence=confidence,
            llm_flip_check=flip,
            resolution_ref=resolution_ref,
            replayed=replayed,
        )
        return DecisionResult(
            outcome=RESOLVED, conflict_type="reading_order", decision_id=did,
            physical_page=page, region_bboxes=region_bboxes,
            candidates_evidence=cand_evidence, contributing_sources=contributing,
            applicability_key=key, decision=decision, confidence=confidence,
            segment_ids=scope_ids, replayed=bool(replayed),
        )

    def _review(reason: str, confidence: float | None = None) -> DecisionResult:
        did = compute_decision_id(
            conflict_type="reading_order", physical_page=page,
            scope_ids=scope_ids, candidate_reprs=cand_reprs, selected=None,
        )
        return DecisionResult(
            outcome=HUMAN_REVIEW_REQUIRED, conflict_type="reading_order", decision_id=did,
            physical_page=page, region_bboxes=region_bboxes,
            candidates_evidence=cand_evidence, contributing_sources=contributing,
            applicability_key=key, review_reason=reason, confidence=confidence,
            segment_ids=scope_ids,
        )

    # 0) replay a stored human decision (the engine passes it when the key matched)
    if replay is not None:
        return _resolved(
            "human_confirmed", {"order": list(replay["selected"]["order"]), "from": "human"},
            replayed=True, resolution_ref=replay["applicability_key"],
        )

    # 1) Block-1 deterministic resolver
    res = resolve_reading_order(groups)
    if isinstance(res, ReadingOrderResolution):
        return _resolved(
            "deterministic_agreement",
            {"order": tr(list(res.order)), "from": res.source},
        )

    # 2) conflict -> deterministic confidence -> LLM tier / HUMAN_REVIEW
    conf = reading_order_confidence(
        candidate_orders=[list(o) for o in res.candidate_orders],
        max_pairwise_kendall_tau_distance=res.max_pairwise_kendall_tau_distance,
        geometry_unambiguous=res.geometry_order is not None,
    )
    if conf < confidence_threshold:
        return _review(_REASON_BELOW, conf)
    if not llm_capable or llm_client is None:
        return _review(_REASON_NO_LLM, conf)

    sel = select_order(
        candidate_orders=[list(o) for o in res.candidate_orders],
        geometry_order=list(res.geometry_order) if res.geometry_order else None,
        llm_client=llm_client,
        physical_page=page,
    )
    if sel.reason == _REASON_FLIP:
        return _review(_REASON_FLIP, conf)
    if not sel.accepted:
        return _review(_REASON_GUARD, conf)
    return _resolved(
        "llm_selected", {"order": tr(list(sel.order)), "from": "llm"},
        confidence=conf, flip={"calls": 2, "agreed": True},
    )
