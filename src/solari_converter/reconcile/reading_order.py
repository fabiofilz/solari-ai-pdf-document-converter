"""Reading-order reconciliation evidence + deterministic geometric resolution (T058).

Reading order is reconciled **separately** from literal content (FR-015 / FR-061d /
SC-022): nothing here reads, rewrites, or re-segments a segment's text — it works only
with group ids and bbox geometry.

Pipeline (research §21c):

* :func:`build_candidate_orders` — project each extraction technique's own
  reading-order opinion onto the aligned groups (evidence only, FR-060b);
* :func:`geometric_order` — the **deterministic geometric resolver**: detect columns by
  x-projection gaps, then order top-to-bottom within a column (``SourceRef.bbox`` is
  top-left origin — smaller ``y`` is higher on the page, per ``extract/plumber_path`` /
  ``extract/docling_path``), columns left-to-right. Returns a **full permutation** of
  the scope ids, or ``None`` when geometry cannot support one (two regions with no
  geometric precedence between them);
* :func:`resolve_reading_order` — returns either a :class:`ReadingOrderResolution`
  (``deterministic_agreement`` — every candidate order agrees, or the geometric
  resolver is unambiguous) or an explicit :class:`ReadingOrderConflict` descriptor.

**No silent fallback.** When geometry is ambiguous and the candidate orders disagree
this module returns a conflict — never candidate-iteration order, a ``segment_id`` sort,
an alphabetical technique order, or any stable sort unrelated to geometry. The LLM
selection tier and the ``< 0.75`` → HUMAN_REVIEW routing are **T059**, not here; Block 1
does not import the LLM, build a CED, or persist anything.

Unpinned thresholds are named module constants with keyword injection (finding M1 —
not ``Config`` fields; run identity unchanged).
"""

from __future__ import annotations

import functools
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from solari_converter.reconcile.align import AlignedSegmentGroup

__all__ = [
    "KENDALL_TAU_DISAGREEMENT_THRESHOLD",
    "ReadingOrderResolution",
    "ReadingOrderConflict",
    "build_candidate_orders",
    "geometric_order",
    "kendall_tau_distance",
    "resolve_reading_order",
]

#: Normalised Kendall-τ distance (discordant pairs / total pairs, in ``[0, 1]``) above
#: which two candidate orders are treated as *materially* disagreeing. Unpinned by the
#: architecture (research §14) → an implementation constant, keyword-injectable.
KENDALL_TAU_DISAGREEMENT_THRESHOLD: float = 0.25

#: Two group x-intervals separated by a gap at least this fraction of the page x-span
#: are in different columns.
_COLUMN_X_GAP_FRACTION: float = 0.04

#: Vertical slack (PDF units) for "A is above B" within a column.
_Y_ABOVE_EPSILON: float = 1.0

#: Horizontal slack (PDF units) for "A is left of B" when the boxes share a row.
_X_LEFT_EPSILON: float = 1.0


# --- value types ----------------------------------------------------------------


@dataclass(frozen=True)
class ReadingOrderResolution:
    """A deterministic accepted order over the aligned groups."""

    order: tuple[str, ...]
    source: Literal["candidate_agreement", "geometry"]
    method: Literal["deterministic_agreement"] = "deterministic_agreement"


@dataclass(frozen=True)
class ReadingOrderConflict:
    """No deterministic order — geometry is ambiguous and the candidates disagree
    (or there is no supported order). The LLM/HUMAN_REVIEW tiers (T059) consume this."""

    scope_ids: tuple[str, ...]
    candidate_orders: tuple[tuple[str, ...], ...]
    geometry_order: tuple[str, ...] | None
    max_pairwise_kendall_tau_distance: float
    reason: Literal["geometry_ambiguous", "no_supported_order"]


# --- candidate orders -----------------------------------------------------------


def _scope_ids(groups: Sequence[AlignedSegmentGroup]) -> list[str]:
    return sorted(g.group_id for g in groups)


def build_candidate_orders(
    groups: Sequence[AlignedSegmentGroup],
) -> dict[str, list[str]]:
    """Map each technique to its order over the groups it has a member in, sorted by
    that member's ``reading_order_index`` (evidence only — FR-060b)."""
    techniques: set[str] = {m.technique for g in groups for m in g.members}
    orders: dict[str, list[str]] = {}
    for tech in sorted(techniques):
        seen: list[tuple[int, str]] = []
        for g in groups:
            for m in g.members:
                if m.technique == tech:
                    seen.append((m.reading_order_index, g.group_id))
                    break
        orders[tech] = [gid for _, gid in sorted(seen, key=lambda t: (t[0], t[1]))]
    return orders


def _full_permutation_orders(
    orders: dict[str, list[str]], scope: Sequence[str]
) -> list[list[str]]:
    target = sorted(scope)
    return [o for o in orders.values() if sorted(o) == target]


# --- Kendall-τ -----------------------------------------------------------------


def kendall_tau_distance(a: Sequence[str], b: Sequence[str]) -> float:
    """Normalised Kendall-τ distance in ``[0, 1]``: the fraction of item pairs ordered
    oppositely by ``a`` and ``b``. ``0.0`` = identical order, ``1.0`` = exact reverse.
    ``a`` and ``b`` must be permutations of the same set."""
    common = [x for x in a if x in set(b)]
    rank_b = {x: i for i, x in enumerate(b)}
    n = len(common)
    if n < 2:
        return 0.0
    discordant = 0
    total = 0
    for i in range(n):
        for j in range(i + 1, n):
            total += 1
            if (rank_b[common[i]] - rank_b[common[j]]) > 0:
                discordant += 1
    return discordant / total if total else 0.0


def _max_pairwise_tau(orders: Sequence[Sequence[str]]) -> float:
    worst = 0.0
    for i in range(len(orders)):
        for j in range(i + 1, len(orders)):
            worst = max(worst, kendall_tau_distance(orders[i], orders[j]))
    return worst


# --- geometric resolver -------------------------------------------------------


def _columns(groups: Sequence[AlignedSegmentGroup]) -> list[float]:
    """Column-boundary x positions from gaps in the merged x-projection of the boxes."""
    spans = sorted((g.region_bbox[0], g.region_bbox[2]) for g in groups)
    if not spans:
        return []
    x_span = max(s[1] for s in spans) - min(s[0] for s in spans)
    if x_span <= 0.0:
        return []
    merged: list[list[float]] = [list(spans[0])]
    for x0, x1 in spans[1:]:
        if x0 <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], x1)
        else:
            merged.append([x0, x1])
    boundaries: list[float] = []
    for (_, a_x1), (b_x0, _) in zip(merged, merged[1:], strict=False):
        if (b_x0 - a_x1) >= _COLUMN_X_GAP_FRACTION * x_span:
            boundaries.append((a_x1 + b_x0) / 2.0)
    return boundaries


def _column_of(bbox: Sequence[float], boundaries: Sequence[float]) -> int:
    center = (bbox[0] + bbox[2]) / 2.0
    return sum(1 for b in boundaries if center > b)


def _precedes(
    a: AlignedSegmentGroup,
    b: AlignedSegmentGroup,
    boundaries: Sequence[float],
) -> bool | None:
    """Does ``a`` strictly come before ``b`` by geometry? ``None`` ⇒ incomparable."""
    ca, cb = _column_of(a.region_bbox, boundaries), _column_of(b.region_bbox, boundaries)
    if ca != cb:
        return ca < cb
    ay0, ay1 = a.region_bbox[1], a.region_bbox[3]
    by0, by1 = b.region_bbox[1], b.region_bbox[3]
    if ay1 <= by0 + _Y_ABOVE_EPSILON:
        return True
    if by1 <= ay0 + _Y_ABOVE_EPSILON:
        return False
    # boxes share a row -> left to right
    ax0, ax1 = a.region_bbox[0], a.region_bbox[2]
    bx0, bx1 = b.region_bbox[0], b.region_bbox[2]
    if ax1 <= bx0 + _X_LEFT_EPSILON:
        return True
    if bx1 <= ax0 + _X_LEFT_EPSILON:
        return False
    return None


def geometric_order(groups: Sequence[AlignedSegmentGroup]) -> list[str] | None:
    """A full permutation of the scope group ids from column detection + baseline
    order, or ``None`` when any pair of regions has no geometric precedence between
    them (the resolver never invents an order)."""
    groups = list(groups)
    if not groups:
        return []
    scope = _scope_ids(groups)
    if len(scope) != len(set(scope)):
        return None
    boundaries = _columns(groups)

    for i in range(len(groups)):
        for j in range(i + 1, len(groups)):
            if _precedes(groups[i], groups[j], boundaries) is None:
                return None

    def cmp(a: AlignedSegmentGroup, b: AlignedSegmentGroup) -> int:
        rel = _precedes(a, b, boundaries)
        return -1 if rel else 1

    ordered = sorted(groups, key=functools.cmp_to_key(cmp))
    # verify the produced order is consistent with every adjacent precedence
    for a, b in zip(ordered, ordered[1:], strict=False):
        if _precedes(a, b, boundaries) is not True:
            return None
    result = [g.group_id for g in ordered]
    if sorted(result) != scope:
        return None
    return result


# --- resolution ---------------------------------------------------------------


def resolve_reading_order(
    groups: Sequence[AlignedSegmentGroup],
    *,
    kendall_threshold: float = KENDALL_TAU_DISAGREEMENT_THRESHOLD,
) -> ReadingOrderResolution | ReadingOrderConflict:
    """Deterministically accept a reading order over ``groups`` or return an explicit
    conflict descriptor (research §21c). Never falls back to a non-geometric order."""
    groups = list(groups)
    scope = _scope_ids(groups)
    cand_orders = build_candidate_orders(groups)
    full_perms = _full_permutation_orders(cand_orders, scope)
    distinct_perms = {tuple(o) for o in full_perms}
    geo = geometric_order(groups)
    geo_tuple = tuple(geo) if geo is not None else None
    max_tau = _max_pairwise_tau(full_perms)

    # 1) every full-permutation candidate order agrees -> deterministic agreement
    if len(distinct_perms) == 1:
        order = next(iter(distinct_perms))
        _assert_permutation(order, scope)
        return ReadingOrderResolution(order=order, source="candidate_agreement")

    # 2) geometry is unambiguous -> it resolves the order (even against disagreeing
    #    candidates, research §21c)
    if geo is not None:
        _assert_permutation(geo_tuple, scope)
        return ReadingOrderResolution(order=geo_tuple, source="geometry")

    # 3) no supported automatic order
    reason = "geometry_ambiguous" if len(scope) >= 2 else "no_supported_order"
    _ = kendall_threshold  # evidence for the T059 confidence tier; not a gate here
    return ReadingOrderConflict(
        scope_ids=tuple(scope),
        candidate_orders=tuple(tuple(o) for o in full_perms),
        geometry_order=geo_tuple,
        max_pairwise_kendall_tau_distance=max_tau,
        reason=reason,
    )


def _assert_permutation(order: Sequence[str], scope: Sequence[str]) -> None:
    if sorted(order) != sorted(scope) or len(order) != len(set(order)):
        raise AssertionError(
            f"reading-order resolver produced a non-permutation: {order!r} vs {scope!r}"
        )
