"""Reading-order reconciliation evidence + deterministic geometric resolution (T058).

Reading order is reconciled **separately** from literal content (FR-015 / FR-061d /
SC-022): nothing here reads, rewrites, or re-segments a segment's text — it works only
with group ids and bbox geometry.

Pipeline (research §21c):

* :func:`build_candidate_orders` — project each extraction technique's own
  reading-order opinion onto the aligned groups (evidence only, FR-060b);
* :func:`geometric_order` — the **deterministic, band-aware geometric resolver**
  (block brief §5). Full-width regions (a heading, a footer, a mid-page subheading —
  width ≥ :data:`SPANNING_REGION_MIN_WIDTH_FRACTION` of the page x-span) are
  *spanning* regions; they divide the page into vertical **bands**. Column detection
  runs **per band**, over that band's non-spanning regions only, so a full-width
  heading can never collapse the page into one interleaved column. Within a band:
  columns left-to-right, members top-to-bottom (``SourceRef.bbox`` is top-left origin
  — smaller ``y`` is higher). Spanning regions are ordered by their vertical position
  relative to the bands. Returns a **full permutation** of the scope ids, or ``None``
  when geometry cannot support one — two regions in the same band/column that overlap
  vertically with neither clearly above the other yield ``None`` (never a left-to-right
  guess just because their x differs, block brief §6);
* :func:`resolve_reading_order` — returns either a :class:`ReadingOrderResolution`
  (``deterministic_agreement`` — **≥ 2** distinct techniques supply agreeing complete
  permutations, or the geometric resolver is unambiguous) or an explicit
  :class:`ReadingOrderConflict`. A **lone** technique's complete permutation is not
  vacuous agreement (block brief §7): it is accepted automatically only when an
  unambiguous geometric order also supports it. It raises
  :class:`MixedPhysicalPageError` for a scope spanning more than one physical PDF
  page — cross-page geometric ordering is never attempted here (block brief §8).

**No silent fallback.** When geometry is ambiguous and the candidate orders disagree
this module returns a conflict — never candidate-iteration order, a ``segment_id`` sort,
an alphabetical technique order, or any stable sort unrelated to geometry. The LLM
selection tier and the ``< 0.75`` → HUMAN_REVIEW routing are **T059**, not here; Block 1
does not import the LLM, build a CED, or persist anything.

Unpinned thresholds are named module constants with keyword injection (finding M1 —
not ``Config`` fields; run identity unchanged).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from solari_converter.reconcile.align import AlignedSegmentGroup

__all__ = [
    "KENDALL_TAU_DISAGREEMENT_THRESHOLD",
    "SPANNING_REGION_MIN_WIDTH_FRACTION",
    "MixedPhysicalPageError",
    "ReadingOrderResolution",
    "ReadingOrderConflict",
    "build_candidate_orders",
    "geometric_order",
    "kendall_tau_distance",
    "resolve_reading_order",
]

#: Normalised Kendall-τ distance (discordant pairs / total pairs, in ``[0, 1]``) above
#: which two candidate orders are treated as *materially* disagreeing. Kept as
#: disagreement evidence for the T059 confidence tier — final reading-order arbitration
#: is **T059**, never a gate in this module (block brief §9). Unpinned by the
#: architecture (research §14) → an implementation constant, keyword-injectable.
KENDALL_TAU_DISAGREEMENT_THRESHOLD: float = 0.25

#: A region whose width is at least this fraction of the page x-span is a *spanning*
#: region (full-width heading / footer / subheading). Spanning regions partition the
#: page into vertical bands; column detection runs per band over non-spanning regions
#: only, so a full-width heading cannot collapse the page into one column
#: (block brief §5). Unpinned by the architecture → an implementation constant.
SPANNING_REGION_MIN_WIDTH_FRACTION: float = 0.60

#: Two group x-intervals separated by a gap at least this fraction of the band x-span
#: are in different columns.
_COLUMN_X_GAP_FRACTION: float = 0.04

#: Vertical slack (PDF units) for "A is strictly above B" within a column / band.
_Y_ABOVE_EPSILON: float = 1.0


class MixedPhysicalPageError(ValueError):
    """:func:`resolve_reading_order` was given regions from more than one physical PDF
    page. Reading order is reconciled per physical page; cross-page geometric ordering
    is never attempted here (block brief §8). The later engine reconciles reading order
    per physical page — this is a defensive invariant."""


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


def _full_permutation_orders_by_tech(
    orders: dict[str, list[str]], scope: Sequence[str]
) -> dict[str, list[str]]:
    """The subset of ``orders`` (technique → order) that are **complete** permutations
    of ``scope`` — a technique that only saw some of the groups is not counted as
    supplying a candidate order (block brief §7)."""
    target = sorted(scope)
    return {t: o for t, o in orders.items() if sorted(o) == target}


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


def _page_x_span(groups: Sequence[AlignedSegmentGroup]) -> float:
    """Page horizontal span from the regions in scope (block brief §5)."""
    x0 = min(g.region_bbox[0] for g in groups)
    x1 = max(g.region_bbox[2] for g in groups)
    return x1 - x0


def _is_spanning(group: AlignedSegmentGroup, page_x_span: float) -> bool:
    """Is ``group`` a full-width spanning region (heading / footer / subheading)?"""
    if page_x_span <= 0.0:
        return False
    width = group.region_bbox[2] - group.region_bbox[0]
    return width >= SPANNING_REGION_MIN_WIDTH_FRACTION * page_x_span


def _vertical_precedes(a: Sequence[float], b: Sequence[float]) -> bool | None:
    """Is box ``a`` strictly above box ``b``? ``True`` / ``False`` when one is clearly
    above the other; ``None`` when they overlap vertically with neither clearly above
    (an ambiguity the resolver must not paper over — block brief §6)."""
    ay0, ay1 = a[1], a[3]
    by0, by1 = b[1], b[3]
    if ay1 <= by0 + _Y_ABOVE_EPSILON:
        return True
    if by1 <= ay0 + _Y_ABOVE_EPSILON:
        return False
    return None


def _band_index(bbox: Sequence[float], spanning: Sequence[AlignedSegmentGroup]) -> int | None:
    """Which vertical band (0..len(spanning)) a non-spanning region sits in, or ``None``
    when it overlaps a spanning divider (ambiguous — block brief §6). ``spanning`` is
    sorted top-to-bottom."""
    ry0, ry1 = bbox[1], bbox[3]
    idx = 0
    for k, s in enumerate(spanning):
        sy0, sy1 = s.region_bbox[1], s.region_bbox[3]
        if ry0 >= sy1 - _Y_ABOVE_EPSILON:      # fully below this spanning region
            idx = k + 1
        elif ry1 <= sy0 + _Y_ABOVE_EPSILON:    # fully above it (and every later one)
            return idx
        else:
            return None                         # straddles a spanning divider
    return idx


def _order_within_band(band: Sequence[AlignedSegmentGroup]) -> list[str] | None:
    """Left-to-right columns, top-to-bottom within each column, over one band's
    non-spanning regions. ``None`` when two regions in the same column overlap
    vertically with neither clearly above the other (block brief §6)."""
    band = list(band)
    if len(band) <= 1:
        return [g.group_id for g in band]
    boundaries = _columns(band)
    cols: dict[int, list[AlignedSegmentGroup]] = {}
    for g in band:
        cols.setdefault(_column_of(g.region_bbox, boundaries), []).append(g)
    ordered: list[str] = []
    for col_idx in sorted(cols):
        col = cols[col_idx]
        for i in range(len(col)):
            for j in range(i + 1, len(col)):
                if _vertical_precedes(col[i].region_bbox, col[j].region_bbox) is None:
                    return None
        col_sorted = sorted(
            col, key=lambda g: (g.region_bbox[1], g.region_bbox[3], g.group_id)
        )
        ordered.extend(g.group_id for g in col_sorted)
    return ordered


def geometric_order(groups: Sequence[AlignedSegmentGroup]) -> list[str] | None:
    """A full permutation of the scope group ids from **band-aware** geometry (block
    brief §5): full-width spanning regions split the page into vertical bands, columns
    are detected per band over non-spanning regions only, and spanning regions are
    ordered by their vertical position between the bands. ``None`` when geometry cannot
    support one — a region straddling a spanning divider, spanning regions that cannot
    be vertically ordered, or two same-column regions overlapping vertically with
    neither clearly above the other. The resolver never invents an order."""
    groups = list(groups)
    if not groups:
        return []
    if len({g.physical_page for g in groups}) > 1:
        return None  # cross-page geometry is undefined (see resolve_reading_order)
    scope = _scope_ids(groups)
    if len(scope) != len(set(scope)):
        return None

    x_span = _page_x_span(groups)
    spanning = sorted(
        (g for g in groups if _is_spanning(g, x_span)),
        key=lambda g: (g.region_bbox[1], g.region_bbox[3], g.group_id),
    )
    non_spanning = [g for g in groups if not _is_spanning(g, x_span)]

    # spanning regions must be mutually vertically orderable, top-to-bottom
    for a, b in zip(spanning, spanning[1:], strict=False):
        if _vertical_precedes(a.region_bbox, b.region_bbox) is not True:
            return None

    bands: list[list[AlignedSegmentGroup]] = [[] for _ in range(len(spanning) + 1)]
    for g in non_spanning:
        idx = _band_index(g.region_bbox, spanning)
        if idx is None:
            return None
        bands[idx].append(g)

    result: list[str] = []
    for k, band in enumerate(bands):
        band_order = _order_within_band(band)
        if band_order is None:
            return None
        result.extend(band_order)
        if k < len(spanning):
            result.append(spanning[k].group_id)

    if sorted(result) != scope or len(result) != len(set(result)):
        return None
    return result


# --- resolution ---------------------------------------------------------------


def resolve_reading_order(
    groups: Sequence[AlignedSegmentGroup],
    *,
    kendall_threshold: float = KENDALL_TAU_DISAGREEMENT_THRESHOLD,
) -> ReadingOrderResolution | ReadingOrderConflict:
    """Deterministically accept a reading order over ``groups`` or return an explicit
    conflict descriptor (research §21c). Never falls back to a non-geometric order.

    Raises :class:`MixedPhysicalPageError` when ``groups`` span more than one physical
    PDF page (block brief §8)."""
    groups = list(groups)
    pages = {g.physical_page for g in groups}
    if len(pages) > 1:
        raise MixedPhysicalPageError(
            f"reading-order scope spans multiple physical pages: {sorted(pages)}"
        )
    scope = _scope_ids(groups)
    cand_orders = build_candidate_orders(groups)
    full_perms_by_tech = _full_permutation_orders_by_tech(cand_orders, scope)
    full_perms = list(full_perms_by_tech.values())
    distinct_perms = {tuple(o) for o in full_perms}
    geo = geometric_order(groups)
    geo_tuple = tuple(geo) if geo is not None else None
    max_tau = _max_pairwise_tau(full_perms)

    # 1) candidate agreement is authoritative only when >= 2 distinct techniques each
    #    supply a COMPLETE permutation and those permutations agree (block brief §7 — a
    #    lone technique's full order is not vacuous "agreement").
    if len(full_perms_by_tech) >= 2 and len(distinct_perms) == 1:
        order = next(iter(distinct_perms))
        _assert_permutation(order, scope)
        return ReadingOrderResolution(order=order, source="candidate_agreement")

    # 2) an unambiguous band-aware geometric order resolves the scope — it confirms a
    #    lone candidate order (block brief §7: one full candidate + matching geometry =>
    #    supported resolution) and overrides candidate disagreement (research §21c).
    if geo is not None:
        _assert_permutation(geo_tuple, scope)
        return ReadingOrderResolution(order=geo_tuple, source="geometry")

    # 3) no supported automatic order: a lone/absent candidate order with ambiguous
    #    geometry, or disagreeing candidates with ambiguous geometry (block brief §7).
    reason = "geometry_ambiguous" if len(scope) >= 2 else "no_supported_order"
    _ = kendall_threshold  # disagreement evidence for the T059 confidence tier; final
    #                        reading-order arbitration is T059, never a gate here (§9)
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
