"""Deterministic cross-candidate segment alignment (T056).

The first step of stage-2 reconciliation (research §21a, data-model.md
"AlignedSegmentGroup"). Given the list of **independent** ``ExtractionCandidate``s
produced by ``extract/runner`` (T051), :func:`align` groups the segments that describe
the *same physical region* so literal- and reading-order reconciliation can compare
like with like.

Frozen grouping rules
---------------------

* **physical page identity is required** — two segments on different physical pages are
  never in one group, whatever their geometry;
* **bbox IoU is the primary signal** — two segments link when their boxes overlap by at
  least :data:`IOU_THRESHOLD`;
* **token Jaccard is only a tie-break / evidence signal** — when a segment could join
  more than one group it joins the one with the greatest member IoU, and Jaccard breaks
  a near-tie in IoU (it is never an independent gate);
* at most one member per technique per group; a second segment from the same technique
  that also overlaps starts its own group (no provenance is dropped);
* the result is **deterministic** and **stable under input-candidate ordering** and
  under segment ordering within a candidate — every decision is driven by a total sort
  on ``(page, rounded bbox, technique, segment_id)``, never on input position.

What alignment must **not** do (it only groups): dehyphenate, strip, normalise or
rewrite any candidate value; reconstruct paragraphs; infer headings; apply structural
hints; make any reconciliation decision. ``segment_id`` — which is text-derived and
intentionally different when paths disagree — is **never** used as the join key.

Thresholds are named module constants with keyword injection (finding M1 — they are
deliberately *not* ``Config`` fields and do not touch run identity).
"""

from __future__ import annotations

import hashlib
import unicodedata
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from solari_converter.model.candidate import ExtractionCandidate
from solari_converter.model.provenance import BBox, SourceRef

__all__ = [
    "IOU_THRESHOLD",
    "JACCARD_TIEBREAK_THRESHOLD",
    "AlignedMember",
    "AlignedSegmentGroup",
    "iou",
    "token_jaccard",
    "align",
]

# --- frozen thresholds (module constants; keyword-injectable; NOT Config — M1) --------

#: Minimum bbox intersection-over-union for two segments to be considered the same
#: region. Unpinned by the architecture (research §14) → an implementation constant.
IOU_THRESHOLD: float = 0.5

#: A candidate group is preferred over another near-equal-IoU group only when its best
#: member token-Jaccard reaches this value; below it the deterministic sort order breaks
#: the tie instead. Jaccard is never a standalone grouping gate.
JACCARD_TIEBREAK_THRESHOLD: float = 0.3

#: Two IoU values within this absolute distance are a "tie" for the Jaccard tie-break.
_IOU_TIE_EPSILON: float = 1e-6

#: bbox rounding for the deterministic sort key (sub-pixel jitter must not reorder).
_BBOX_SORT_NDIGITS: int = 3


# --- public value types -------------------------------------------------------------


@dataclass(frozen=True)
class AlignedMember:
    """One candidate's evidence within a group — the segment carried verbatim."""

    technique: str
    segment_id: str
    text: str
    source: SourceRef
    reading_order_index: int


@dataclass(frozen=True)
class AlignedSegmentGroup:
    """The cross-candidate correspondence unit (data-model.md Layer 2). 1–3 members.

    Internal — embedded in the reconciliation log, never persisted on its own.
    """

    group_id: str
    physical_page: int
    region_bbox: BBox
    members: tuple[AlignedMember, ...]


# --- geometry / text helpers (pure) -------------------------------------------------


def iou(a: Sequence[float], b: Sequence[float]) -> float:
    """Intersection-over-union of two ``(x0, y0, x1, y1)`` boxes. Orientation-agnostic.

    Returns ``0.0`` for a degenerate box or no overlap, ``1.0`` for identical boxes.
    """
    ax0, ay0, ax1, ay1 = _norm_box(a)
    bx0, by0, bx1, by1 = _norm_box(b)
    ix0, iy0 = max(ax0, bx0), max(ay0, by0)
    ix1, iy1 = min(ax1, bx1), min(ay1, by1)
    iw, ih = ix1 - ix0, iy1 - iy0
    if iw <= 0.0 or ih <= 0.0:
        return 0.0
    inter = iw * ih
    area_a = (ax1 - ax0) * (ay1 - ay0)
    area_b = (bx1 - bx0) * (by1 - by0)
    union = area_a + area_b - inter
    if union <= 0.0:
        return 0.0
    return inter / union


def token_jaccard(a: str, b: str) -> float:
    """Jaccard similarity of the whitespace-split token *sets* of two strings.

    The inputs are NFC- and case-folded **for this comparison only** — no stored value
    is touched. Two empty token sets are treated as fully similar (``1.0``).
    """
    ta = _token_set(a)
    tb = _token_set(b)
    if not ta and not tb:
        return 1.0
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def _token_set(text: str) -> frozenset[str]:
    return frozenset(unicodedata.normalize("NFC", text).casefold().split())


def _norm_box(box: Sequence[float]) -> tuple[float, float, float, float]:
    x0, y0, x1, y1 = (float(v) for v in box)
    return (min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1))


# --- alignment ---------------------------------------------------------------------


@dataclass(frozen=True)
class _Item:
    technique: str
    segment_id: str
    text: str
    source: SourceRef
    reading_order_index: int
    page: int
    bbox: tuple[float, float, float, float]

    @property
    def sort_key(self) -> tuple:
        r = tuple(round(v, _BBOX_SORT_NDIGITS) for v in self.bbox)
        return (self.page, *r, self.technique, self.segment_id)


def _items(candidates: Iterable[ExtractionCandidate]) -> list[_Item]:
    out: list[_Item] = []
    for cand in candidates:
        for seg in cand.segments:
            src = seg.source
            # a synthesized wrapper without geometry cannot be geometrically aligned —
            # it becomes its own single-member group (IoU 0 against everything).
            bbox = (0.0, 0.0, 0.0, 0.0) if src.bbox is None else _norm_box(src.bbox)
            out.append(
                _Item(
                    technique=cand.technique,
                    segment_id=seg.segment_id,
                    text=seg.text,
                    source=src,
                    reading_order_index=seg.reading_order_index,
                    page=src.physical_page,
                    bbox=bbox,
                )
            )
    return out


def align(
    candidates: Iterable[ExtractionCandidate],
    *,
    iou_threshold: float = IOU_THRESHOLD,
    jaccard_tiebreak_threshold: float = JACCARD_TIEBREAK_THRESHOLD,
) -> list[AlignedSegmentGroup]:
    """Group the independent candidates' segments by physical region (research §21a).

    Deterministic and stable under any reordering of ``candidates`` or of the segments
    within a candidate.
    """
    items = sorted(_items(candidates), key=lambda it: it.sort_key)

    clusters: list[list[_Item]] = []
    for item in items:
        best_idx: int | None = None
        best_iou = -1.0
        best_jac = -1.0
        for idx, cluster in enumerate(clusters):
            if cluster[0].page != item.page:
                continue
            if any(m.technique == item.technique for m in cluster):
                continue
            cand_iou = max(iou(item.bbox, m.bbox) for m in cluster)
            if cand_iou < iou_threshold:
                continue
            cand_jac = max(token_jaccard(item.text, m.text) for m in cluster)
            if _prefers(cand_iou, cand_jac, best_iou, best_jac, jaccard_tiebreak_threshold):
                best_idx, best_iou, best_jac = idx, cand_iou, cand_jac
        if best_idx is None:
            clusters.append([item])
        else:
            clusters[best_idx].append(item)

    groups = [_finalise(cluster) for cluster in clusters]
    groups.sort(key=lambda g: (g.physical_page, g.region_bbox, g.group_id))
    return groups


def _prefers(
    cand_iou: float,
    cand_jac: float,
    best_iou: float,
    best_jac: float,
    jaccard_tiebreak_threshold: float,
) -> bool:
    """Is ``(cand_iou, cand_jac)`` a better group match than the current best?

    IoU is primary. Token Jaccard only decides a near-tie in IoU, and only when it is
    informative enough (``>= jaccard_tiebreak_threshold``).
    """
    if best_iou < 0.0:
        return True
    if abs(cand_iou - best_iou) > _IOU_TIE_EPSILON:
        return cand_iou > best_iou
    if max(cand_jac, best_jac) < jaccard_tiebreak_threshold:
        return False  # keep the earlier (deterministically-sorted) match
    return cand_jac > best_jac


def _finalise(cluster: list[_Item]) -> AlignedSegmentGroup:
    members = tuple(
        AlignedMember(
            technique=it.technique,
            segment_id=it.segment_id,
            text=it.text,
            source=it.source,
            reading_order_index=it.reading_order_index,
        )
        for it in sorted(cluster, key=lambda it: (it.technique, it.segment_id))
    )
    page = cluster[0].page
    x0 = min(it.bbox[0] for it in cluster)
    y0 = min(it.bbox[1] for it in cluster)
    x1 = max(it.bbox[2] for it in cluster)
    y1 = max(it.bbox[3] for it in cluster)
    region_bbox = (x0, y0, x1, y1)
    digest = hashlib.sha1(
        f"{page}:{sorted(m.segment_id for m in members)}".encode()
    ).hexdigest()[:12]
    return AlignedSegmentGroup(
        group_id=digest,
        physical_page=page,
        region_bbox=region_bbox,
        members=members,
    )
