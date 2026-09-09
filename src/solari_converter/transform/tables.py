"""Stage-3 deterministic table reconstruction (T070).

The table pass. It consumes the **Canonical Extracted Document only** — the accepted
verbatim segments in ``accepted_reading_order`` plus their frozen ``SourceRef`` geometry
and the carried (never-applied) ``table`` / ``table_row`` / ``table_cell`` structural
hints — and reconstructs logical tables: a per-page grid from the cell geometry, a
conservative multi-page stitch of continuation fragments, a single collapse of a repeated
continuation header, and geometry-only merged-cell spans (FR-020 / FR-021 / FR-022).

Hard guarantees
---------------

* **deterministic** — a pure function of the CED alone; no LLM, no network, no
  dictionary, no randomness, no third-party table library, no PDF reopening. The
  :class:`~solari_converter.transform.reflow.ReflowResult` is **not** table input: table
  ownership is determined *before* non-table reflow (``build_tables(ced)`` first, then
  ``reflow(ced, excluded_segment_ids=result.consumed_segment_ids)``) so a hint-less cell
  absorbed by geometry can never be half-owned by a prose unit;
* **literal-faithful** — a cell's text is a source segment's own character sequence,
  verbatim. The *only* permitted composition is the audited multi-segment wrapped-line
  boundary join (``WRAPPED_LINE_JOIN`` between two segment literals, recorded as a
  ``reflow_whitespace`` :class:`SegmentTransform`). No numeric / separator / currency /
  date normalisation, ever. A CED segment is **atomic** — never split to invent columns;
* **conservative detection** — a segment enters a table only via a ``table*`` hint, or
  (hint-less) only when it lies inside an already-hinted fragment's bbox within
  ``CELL_BBOX_TOLERANCE`` and aligns with that fragment's columns. No hint-free
  geometric table discovery. A false negative beats a false-positive table;
* **lineage-complete** — every cell keeps *all* contributing segment ids; every consumed
  CED table segment is traceable to exactly one retained logical cell **or** a recorded
  :class:`CollapsedHeader`. Nothing consumed disappears;
* **order-transparent** — any re-ordering the row-major grid needs versus the accepted
  order is a recorded :class:`StructuralReorder` (``permitted_by`` ``FR-020`` / ``FR-021``);
  the accepted reading order itself is never mutated (FR-064 / SC-023).

Thresholds are **named module constants** — not ``Config`` fields, not CLI options, not
folded into run identity.
"""

from __future__ import annotations

import difflib
import hashlib
import re
from dataclasses import dataclass, field
from typing import Literal

from solari_converter.model.canonical import AcceptedSegment, CanonicalExtractedDocument
from solari_converter.reconcile.confidence import comparison_key
from solari_converter.transform.reflow import (
    WRAPPED_LINE_JOIN,
    HintDecision,
    ReflowResult,
    SegmentTransform,
)

__all__ = [
    "TABLE_HINT_KINDS",
    "CELL_BBOX_TOLERANCE",
    "TABLE_ROW_GAP_MAX_RATIO",
    "ROW_BAND_TOP_RATIO",
    "ROW_OVERLAP_MIN_RATIO",
    "COLUMN_OVERLAP_MIN_RATIO",
    "SPAN_OVERLAP_MIN_RATIO",
    "SPAN_UNCERTAIN_MIN_RATIO",
    "SIGNATURE_ROUNDING",
    "COLUMN_X0_TOLERANCE",
    "CELL_WRAP_GAP_RATIO",
    "CELL_WRAP_UNCERTAIN_GAP_RATIO",
    "HEADER_RESEMBLANCE_RATIO",
    "FURNITURE_REPEAT_MIN_PAGES",
    "FURNITURE_TOP_TOLERANCE",
    "MIN_GRID_ROWS",
    "MIN_GRID_COLS",
    "MIN_POPULATED_ROWS",
    "MIN_FILLED_POSITIONS",
    "PAGE_NUMBER_RE",
    "PAGE_NUMBER_BARE_RE",
    "TableCell",
    "TableFragment",
    "LogicalTable",
    "StitchRecord",
    "CollapsedHeader",
    "StructuralReorder",
    "TableAmbiguity",
    "TableBlock",
    "TablesResult",
    "build_tables",
]

# --- frozen thresholds (module constants; NOT Config; run identity unchanged) --------

#: Hint kinds that let a segment enter table reconstruction (the authoritative
#: table forms present in ``model/segment.py``).
TABLE_HINT_KINDS: frozenset[str] = frozenset({"table", "table_row", "table_cell"})

#: A hint-less segment may join a hinted fragment only if its bbox lies inside that
#: fragment's bbox within this many PDF units on every edge (and it column-aligns).
CELL_BBOX_TOLERANCE: float = 2.0

#: A vertical gap between a fragment's current bottom and the next candidate row larger
#: than this fraction of the local row height ends the fragment. Prefer *not* grouping.
TABLE_ROW_GAP_MAX_RATIO: float = 1.5

#: Row bands are anchored on segment *top* coordinates: a segment joins a band whose
#: anchor top is within this fraction of ``min(segment height, band height)``. Segments
#: sharing a visual row have near-identical tops; the next row is a full row pitch away.
ROW_BAND_TOP_RATIO: float = 0.5

#: A cell's vertical extent must overlap an additional row band by at least this fraction
#: of the band height for the band to count toward a ``rowspan``.
ROW_OVERLAP_MIN_RATIO: float = 0.5

#: The analogous horizontal-overlap floor for a segment joining a column cluster.
COLUMN_OVERLAP_MIN_RATIO: float = 0.5

#: A cell's bbox must overlap each *additional* row band / column cluster by at least
#: this fraction for a ``rowspan`` / ``colspan`` > 1 to be inferred (geometry only).
SPAN_OVERLAP_MIN_RATIO: float = 0.5

#: Overlap strictly between this floor and ``SPAN_OVERLAP_MIN_RATIO`` with a neighbouring
#: band/cluster is *ambiguous* — span stays 1 and a ``span_uncertain`` ambiguity is
#: recorded. At or below this it is a clean span 1.
SPAN_UNCERTAIN_MIN_RATIO: float = 0.15

#: Column-interval geometry is rounded to this many points before it becomes a stable
#: column signature (used for multi-page stitch compatibility).
SIGNATURE_ROUNDING: float = 1.0

#: Two fragments' corresponding column left edges must be within this many points for
#: their signatures to be "compatible" for a stitch.
COLUMN_X0_TOLERANCE: float = 6.0

#: A lone segment whose band starts within this fraction of the fragment's dominant row
#: pitch below the cell directly above it (same single column, no competing segment) is a
#: wrapped continuation line of that cell — aggregated with ``WRAPPED_LINE_JOIN`` (a
#: ``reflow_whitespace`` transform). Nothing inside either literal changes. A normal next
#: row sits a full pitch away and is never merged.
CELL_WRAP_GAP_RATIO: float = 0.75

#: Between ``CELL_WRAP_GAP_RATIO`` and this fraction of the row pitch the wrap is
#: *uncertain*: do not merge, record a ``wrapped_cell_uncertain`` ambiguity, keep the row.
CELL_WRAP_UNCERTAIN_GAP_RATIO: float = 0.97

#: A continuation-fragment first row that is not a key-exact repeat of the logical header
#: but whose per-cell text is at least this similar (mean ``difflib`` ratio) is recorded
#: as a rejected header repeat rather than silently kept — but still **not** collapsed.
HEADER_RESEMBLANCE_RATIO: float = 0.6

#: A hint-less segment between two page fragments is "stitch-transparent" only if it is
#: a page number with *positive* evidence (``PAGE_NUMBER_RE`` explicit prefix, or a bare
#: ``PAGE_NUMBER_BARE_RE`` integer that equals its physical page or sits in an
#: adjacent-page ``n`` / ``n+1`` sequence) **or** its comparison key repeats on at least
#: this many distinct physical pages at a *position-consistent* top coordinate.
FURNITURE_REPEAT_MIN_PAGES: int = 2

#: Repeated furniture must recur with its bbox top within this many PDF units of the
#: candidate's top on every counted page. Larger than the 1-unit bbox rounding jitter
#: that ``segment_id`` tolerates between techniques, and well under one text line
#: (≈12 units), so two different lines can never alias as the same furniture.
FURNITURE_TOP_TOLERANCE: float = 4.0

#: Minimum corroborated grid: at least this many row bands …
MIN_GRID_ROWS: int = 2
#: … at least this many column clusters …
MIN_GRID_COLS: int = 2
#: … at least this many non-empty row bands …
MIN_POPULATED_ROWS: int = 2
#: … and at least this many filled logical positions overall.
MIN_FILLED_POSITIONS: int = 3

#: An *explicitly prefixed* page number (``Page 12`` / ``Pág. 3`` / ``fls. 7`` /
#: ``página iv``) — positive evidence on its own. Stitch transparency only; never used
#: to remove anything (artifact removal is T071/T072).
PAGE_NUMBER_RE = re.compile(
    r"^\s*(?:[-–—]\s*)?(?:p\.|p[aá]g\.?|page|p[aá]gina|fls?\.|folha)\s*"
    r"(?:[0-9]{1,6}|[ivxlc]{1,6})\s*(?:/\s*[0-9]{1,6})?\s*(?:[-–—]\s*)?$",
    re.IGNORECASE,
)

#: A *bare* decimal page-number candidate (``53`` / ``- 53 -`` / ``53/120``). On its
#: own this is **not** evidence — a year, a price, a clause number look the same. It
#: becomes transparent only when the integer equals the segment's physical page or a
#: bare number on the adjacent physical page continues the sequence. Roman letters are
#: deliberately excluded (``I`` / ``V`` / ``X`` / ``L`` / ``C`` are ordinary tokens).
PAGE_NUMBER_BARE_RE = re.compile(
    r"^\s*(?:[-–—]\s*)?([0-9]{1,6})\s*(?:/\s*[0-9]{1,6})?\s*(?:[-–—]\s*)?$"
)


# --- value types -------------------------------------------------------------------


@dataclass(frozen=True)
class TableCell:
    """One logical grid cell. ``text`` is a verbatim source literal (or the audited
    multi-segment wrapped join); ``provenance`` keeps *every* contributing segment id."""

    text: str
    provenance: tuple[str, ...]
    row: int
    column: int
    rowspan: int = 1
    colspan: int = 1
    is_header: bool = False
    page: int | None = None

    @property
    def source_segment_ids(self) -> tuple[str, ...]:
        return self.provenance

    @property
    def is_empty(self) -> bool:
        return self.text == "" and not self.provenance


@dataclass(frozen=True)
class TableFragment:
    """One reconstructed per-page grid, before any multi-page stitch."""

    fragment_id: str
    page: int
    segment_ids: tuple[str, ...]          # accepted-source order
    row_major_segment_ids: tuple[str, ...]
    rows: tuple[tuple[TableCell, ...], ...]
    column_signature: tuple[tuple[float, float], ...]


@dataclass(frozen=True)
class StitchRecord:
    """One accepted continuation join between two adjacent-page fragments."""

    from_fragment_id: str
    to_fragment_id: str
    from_page: int
    to_page: int
    signal: str                          # repeated_header | direct_continuation | repeated_caption
    transparent_segment_ids: tuple[str, ...]


@dataclass(frozen=True)
class CollapsedHeader:
    """A repeated continuation-header row folded into the retained logical header
    (FR-022). Its physical segment ids survive here, never in a rendered cell."""

    table_id: str
    page: int
    segment_ids: tuple[str, ...]                     # the physical continuation header
    kept_header_segment_ids: tuple[str, ...]         # the retained logical header row
    per_cell: tuple[tuple[int, tuple[str, ...]], ...]  # (column, collapsed segment ids)
    rule: str = "FR-022"


@dataclass(frozen=True)
class StructuralReorder:
    """A table-scoped reorder the row-major grid needs versus the accepted order
    (SC-023). ``permitted_by`` is ``FR-020`` (grid order) or ``FR-021`` (stitch placement)."""

    scope: str
    affected_segment_ids: tuple[str, ...]
    from_order: tuple[str, ...]
    to_order: tuple[str, ...]
    reason: str
    permitted_by: str


@dataclass(frozen=True)
class TableAmbiguity:
    """A place the pass took the conservative interpretation. No review queue in T070."""

    kind: str
    scope: str
    segment_ids: tuple[str, ...]
    detail: str


@dataclass(frozen=True)
class LogicalTable:
    """A single logical table — one or more stitched fragments, header collapsed once."""

    table_id: str
    rows: list[list[TableCell]]
    has_merged_cells: bool
    header_row_count: int
    spans_pages: list[int]


@dataclass(frozen=True)
class TableBlock:
    kind: Literal["table"]
    block_id: str
    table: LogicalTable
    provenance: tuple[str, ...]
    hint_decisions: tuple[HintDecision, ...]


@dataclass(frozen=True)
class TablesResult:
    blocks: tuple[TableBlock, ...] = ()
    structural_reorder: tuple[StructuralReorder, ...] = ()
    stitch_records: tuple[StitchRecord, ...] = ()
    collapsed_headers: tuple[CollapsedHeader, ...] = ()
    ambiguities: tuple[TableAmbiguity, ...] = ()
    hint_decisions: tuple[HintDecision, ...] = ()
    transforms: tuple[SegmentTransform, ...] = ()
    consumed_segment_ids: frozenset[str] = field(default_factory=frozenset)


# --- geometry helpers (pure) ------------------------------------------------------


def _interval_overlap(a0: float, a1: float, b0: float, b1: float) -> float:
    return max(0.0, min(a1, b1) - max(a0, b0))


def _bbox(seg: AcceptedSegment) -> tuple[float, float, float, float] | None:
    return seg.source.bbox


def _height(box: tuple[float, float, float, float]) -> float:
    h = box[3] - box[1]
    return h if h > 0.0 else 12.0


def _width(box: tuple[float, float, float, float]) -> float:
    w = box[2] - box[0]
    return w if w > 0.0 else 1.0


def _hint_ref(h) -> str:
    return f"{h.segment_id}:{h.kind}:{h.source_technique}:{h.level}"


def _digest(prefix: str, payload: str) -> str:
    return prefix + hashlib.sha1(payload.encode("utf-8")).hexdigest()[:12]


def _key(text: str) -> str:
    return comparison_key(text).casefold()


# --- row / column clustering (deterministic) -------------------------------------


@dataclass
class _Band:
    top: float                       # anchor: the min top of the band's seeding segments
    rep_height: float                # representative row height (min member height)
    seg_ids: list[str] = field(default_factory=list)

    @property
    def height(self) -> float:
        return self.rep_height if self.rep_height > 0.0 else 12.0

    @property
    def bottom(self) -> float:
        return self.top + self.height


@dataclass
class _Cluster:
    x0: float
    x1: float
    seg_ids: list[str] = field(default_factory=list)

    @property
    def width(self) -> float:
        w = self.x1 - self.x0
        return w if w > 0.0 else 1.0


def _row_bands(segs: list[AcceptedSegment]) -> list[_Band]:
    """Cluster segments into row bands by *top-coordinate* proximity. Deterministic:
    segments are processed in ``(top, x0, segment_id)`` order; bands are anchored on the
    top of their first (shortest) member so a tall row-spanning cell does not swallow the
    band; bands are returned top-to-bottom."""
    ordered = sorted(
        segs, key=lambda s: (_bbox(s)[1], _bbox(s)[0], s.segment_id)  # type: ignore[index]
    )
    bands: list[_Band] = []
    for s in ordered:
        box = _bbox(s)
        assert box is not None
        top = box[1]
        sh = _height(box)
        hit = next(
            (
                b for b in bands
                if abs(top - b.top) <= ROW_BAND_TOP_RATIO * min(sh, b.height)
            ),
            None,
        )
        if hit is None:
            bands.append(_Band(top, sh, [s.segment_id]))
        else:
            hit.seg_ids.append(s.segment_id)
            hit.top = min(hit.top, top)
            hit.rep_height = min(hit.rep_height, sh)
    return sorted(bands, key=lambda b: (b.top, b.rep_height))


def _col_clusters(segs: list[AcceptedSegment]) -> list[_Cluster]:
    """Cluster segments into column intervals by horizontal overlap. Deterministic:
    narrowest segments first (a wide spanning cell must not define a column), then
    ``(x0, segment_id)``; clusters are returned left-to-right."""
    ordered = sorted(
        segs,
        key=lambda s: (_width(_bbox(s)), _bbox(s)[0], s.segment_id),  # type: ignore[index]
    )
    clusters: list[_Cluster] = []
    for s in ordered:
        box = _bbox(s)
        assert box is not None
        x0, x1 = box[0], box[2]
        sw = _width(box)
        strong = [
            c for c in clusters
            if _interval_overlap(x0, x1, c.x0, c.x1)
            >= COLUMN_OVERLAP_MIN_RATIO * min(sw, c.width)
        ]
        if len(strong) == 1:
            c = strong[0]
            c.seg_ids.append(s.segment_id)
            c.x0 = min(c.x0, x0)
            c.x1 = max(c.x1, x1)
        elif not strong:
            clusters.append(_Cluster(x0, x1, [s.segment_id]))
        # len(strong) > 1: a spanning candidate — it defines no column of its own.
    return sorted(clusters, key=lambda c: (c.x0, c.x1))


def _signature(clusters: list[_Cluster]) -> tuple[tuple[float, float], ...]:
    r = SIGNATURE_ROUNDING
    return tuple((round(c.x0 / r) * r, round(c.x1 / r) * r) for c in clusters)


# --- fragment grouping ----------------------------------------------------------


def _group_fragments(page_segs: list[AcceptedSegment]) -> list[list[AcceptedSegment]]:
    """Split one page's table-candidate segments into vertically-contiguous fragments."""
    ordered = sorted(
        page_segs, key=lambda s: (_bbox(s)[1], _bbox(s)[0], s.segment_id)  # type: ignore[index]
    )
    groups: list[list[AcceptedSegment]] = []
    cur: list[AcceptedSegment] = []
    cur_bottom = 0.0
    cur_h = 12.0
    for s in ordered:
        box = _bbox(s)
        assert box is not None
        if not cur:
            cur = [s]
            cur_bottom, cur_h = box[3], _height(box)
            continue
        gap = box[1] - cur_bottom
        if gap > TABLE_ROW_GAP_MAX_RATIO * max(cur_h, _height(box)):
            groups.append(cur)
            cur = [s]
            cur_bottom, cur_h = box[3], _height(box)
        else:
            cur.append(s)
            cur_bottom = max(cur_bottom, box[3])
            cur_h = max(cur_h, _height(box))
    if cur:
        groups.append(cur)
    return groups


# --- the pass -------------------------------------------------------------------


def build_tables(
    ced: CanonicalExtractedDocument, reflow_result: ReflowResult | None = None
) -> TablesResult:
    """Reconstruct logical tables from ``ced``'s accepted segments. Deterministic.

    The CED is the **only** input. Every stitch-adjacency / intervening-content decision
    is taken on ``accepted_reading_order`` directly. ``reflow_result`` is accepted for
    backward compatibility and ignored: table ownership must be known *before* the
    non-table reflow runs (call ``build_tables(ced)`` first, then
    ``reflow(ced, excluded_segment_ids=result.consumed_segment_ids)``).
    """
    return _Builder(ced).run()


class _Builder:
    def __init__(self, ced: CanonicalExtractedDocument) -> None:
        self.ced = ced
        self.by_id: dict[str, AcceptedSegment] = {
            s.segment_id: s for s in ced.accepted_segments
        }
        self.order: list[str] = [
            sid for sid in ced.accepted_reading_order if sid in self.by_id
        ]
        self.accepted_index: dict[str, int] = {
            sid: i for i, sid in enumerate(self.order)
        }
        self.pages_in_ced: frozenset[int] = frozenset(
            s.source.physical_page for s in ced.accepted_segments
        )
        self.hints_by_seg: dict[str, list] = {}
        for h in ced.carried_structural_hints:
            self.hints_by_seg.setdefault(h.segment_id, []).append(h)

        # accumulators
        self.hint_decisions: list[HintDecision] = []
        self.ambiguities: list[TableAmbiguity] = []
        self.transforms: list[SegmentTransform] = []
        self.stitch_records: list[StitchRecord] = []
        self.collapsed_headers: list[CollapsedHeader] = []
        self.structural_reorder: list[StructuralReorder] = []
        self.consumed: set[str] = set()

    # -- helpers ------------------------------------------------------------

    def _table_hints(self, seg_id: str) -> list:
        return [h for h in self.hints_by_seg.get(seg_id, []) if h.kind in TABLE_HINT_KINDS]

    def _has_table_hint(self, seg_id: str) -> bool:
        return bool(self._table_hints(seg_id))

    def _record_hint_decisions(self, seg_ids: set[str], applied: bool, reason: str) -> None:
        for sid in sorted(seg_ids):
            for h in self._table_hints(sid):
                self.hint_decisions.append(
                    HintDecision(
                        hint_ref=_hint_ref(h), kind=h.kind, applied=applied, reason=reason
                    )
                )

    def _ambiguity(self, kind: str, scope: str, seg_ids, detail: str) -> None:
        self.ambiguities.append(
            TableAmbiguity(kind, scope, tuple(sorted(set(seg_ids))), detail)
        )

    # -- run --------------------------------------------------------------

    def run(self) -> TablesResult:
        fragments = self._build_all_fragments()
        logical = self._stitch(fragments)
        blocks = self._finalise(logical)

        return TablesResult(
            blocks=tuple(blocks),
            structural_reorder=tuple(self.structural_reorder),
            stitch_records=tuple(self.stitch_records),
            collapsed_headers=tuple(self.collapsed_headers),
            ambiguities=tuple(
                sorted(self.ambiguities, key=lambda a: (a.scope, a.kind, a.segment_ids))
            ),
            hint_decisions=tuple(
                sorted(
                    self.hint_decisions,
                    key=lambda d: (d.hint_ref, d.applied, d.reason),
                )
            ),
            transforms=tuple(self.transforms),
            consumed_segment_ids=frozenset(self.consumed),
        )

    # -- fragment construction ------------------------------------------

    def _candidate_segments_by_page(self) -> dict[int, list[AcceptedSegment]]:
        by_page: dict[int, list[AcceptedSegment]] = {}
        for sid in self.order:
            seg = self.by_id[sid]
            if _bbox(seg) is None:
                continue
            if self._has_table_hint(sid):
                by_page.setdefault(seg.source.physical_page, []).append(seg)
        return by_page

    def _build_all_fragments(self) -> list[TableFragment]:
        fragments: list[TableFragment] = []
        by_page = self._candidate_segments_by_page()
        for page in sorted(by_page):
            for group in _group_fragments(by_page[page]):
                group = self._absorb_hintless(page, group)
                frag = self._build_fragment(page, group)
                if frag is not None:
                    fragments.append(frag)
        # global order: by first accepted index of any of the fragment's segments
        fragments.sort(
            key=lambda f: (
                min(self.accepted_index[s] for s in f.segment_ids),
                f.page,
                f.fragment_id,
            )
        )
        return fragments

    def _absorb_hintless(
        self, page: int, group: list[AcceptedSegment]
    ) -> list[AcceptedSegment]:
        """Pull in hint-less segments fully inside the fragment bbox (within tolerance)
        and column-aligned. Conservative — no general hint-free discovery."""
        boxes = [_bbox(s) for s in group]
        gx0 = min(b[0] for b in boxes)  # type: ignore[index]
        gtop = min(b[1] for b in boxes)  # type: ignore[index]
        gx1 = max(b[2] for b in boxes)  # type: ignore[index]
        gbot = max(b[3] for b in boxes)  # type: ignore[index]
        clusters = _col_clusters(group)
        present = {s.segment_id for s in group}
        extra: list[AcceptedSegment] = []
        for sid in self.order:
            if sid in present:
                continue
            seg = self.by_id[sid]
            if seg.source.physical_page != page or self._has_table_hint(sid):
                continue
            box = _bbox(seg)
            if box is None:
                continue
            t = CELL_BBOX_TOLERANCE
            inside = (
                box[0] >= gx0 - t and box[1] >= gtop - t
                and box[2] <= gx1 + t and box[3] <= gbot + t
            )
            if not inside:
                continue
            aligned = any(
                _interval_overlap(box[0], box[2], c.x0, c.x1)
                >= COLUMN_OVERLAP_MIN_RATIO * min(_width(box), c.width)
                for c in clusters
            )
            if aligned:
                extra.append(seg)
        if not extra:
            return group
        merged = sorted(
            group + extra, key=lambda s: (_bbox(s)[1], _bbox(s)[0], s.segment_id)  # type: ignore[index]
        )
        return merged

    def _build_fragment(
        self, page: int, group: list[AcceptedSegment]
    ) -> TableFragment | None:
        seg_ids_accepted = tuple(
            sorted((s.segment_id for s in group), key=lambda x: self.accepted_index[x])
        )
        scope = f"page-{page}:{seg_ids_accepted[0]}"

        bands = _row_bands(group)
        clusters = _col_clusters(group)

        if len(clusters) < MIN_GRID_COLS:
            self._record_hint_decisions(
                set(s.segment_id for s in group), applied=False,
                reason="no column evidence — hinted region has no recoverable per-column grid",
            )
            self._ambiguity(
                "single_column_region_skipped", scope,
                (s.segment_id for s in group),
                f"{len(bands)} row band(s) but {len(clusters)} column interval(s); "
                "left as ordinary content (no grid invented)",
            )
            return None

        grid, span_amb = self._assign_cells(group, bands, clusters, page, scope)
        grid = self._merge_wrapped_cells(grid, bands, clusters, page, scope)

        non_empty_rows = sum(1 for r in grid if any(not c.is_empty for c in r))
        filled = sum(
            c.rowspan * c.colspan for r in grid for c in r if not c.is_empty
        )
        max_positions = max(
            (sum(c.colspan for c in r if not c.is_empty) for r in grid), default=0
        )
        corroborated = (
            len(bands) >= MIN_GRID_ROWS
            and len(clusters) >= MIN_GRID_COLS
            and non_empty_rows >= MIN_POPULATED_ROWS
            and filled >= MIN_FILLED_POSITIONS
            and max_positions >= MIN_GRID_COLS
        )
        if not corroborated:
            self._record_hint_decisions(
                set(s.segment_id for s in group), applied=False,
                reason="insufficient corroborated grid "
                f"(bands={len(bands)}, cols={len(clusters)}, populated_rows={non_empty_rows})",
            )
            self._ambiguity(
                "column_boundary_uncertain", scope,
                (s.segment_id for s in group),
                "hint present but geometry does not corroborate a >=2x2 grid",
            )
            return None

        for amb in span_amb:
            self.ambiguities.append(amb)

        row_major: list[str] = []
        for r in grid:
            for c in r:
                if not c.is_empty:
                    row_major.extend(c.provenance)
        # de-dup preserving order (a span cell contributes once)
        seen: set[str] = set()
        row_major_ids = tuple(x for x in row_major if not (x in seen or seen.add(x)))

        frag_id = _digest("tf-", f"{page}:{list(row_major_ids)}")
        return TableFragment(
            fragment_id=frag_id,
            page=page,
            segment_ids=seg_ids_accepted,
            row_major_segment_ids=row_major_ids,
            rows=tuple(tuple(r) for r in grid),
            column_signature=_signature(clusters),
        )

    def _assign_cells(
        self,
        group: list[AcceptedSegment],
        bands: list[_Band],
        clusters: list[_Cluster],
        page: int,
        scope: str,
    ) -> tuple[list[list[TableCell]], list[TableAmbiguity]]:
        nrows, ncols = len(bands), len(clusters)
        anchors: dict[tuple[int, int], TableCell] = {}
        covered: set[tuple[int, int]] = set()
        span_amb: list[TableAmbiguity] = []

        placed: list[tuple[int, int, int, int, AcceptedSegment]] = []
        for s in sorted(
            group, key=lambda s: (_bbox(s)[1], _bbox(s)[0], s.segment_id)  # type: ignore[index]
        ):
            box = _bbox(s)
            assert box is not None
            r0, rspan, r_amb = _span(
                box[1], box[3], [(b.top, b.bottom) for b in bands], scope, s.segment_id
            )
            c0, cspan, c_amb = _span(
                box[0], box[2], [(c.x0, c.x1) for c in clusters], scope, s.segment_id
            )
            span_amb.extend(r_amb)
            span_amb.extend(c_amb)
            placed.append((r0, c0, rspan, cspan, s))

        # A real source segment always wins over an inferred span: an anchor that lies
        # inside another cell's would-be coverage cancels the disputed span dimension.
        anchor_positions = {(r0, c0) for r0, c0, _, _, _ in placed}
        for r0, c0, rspan, cspan, s in placed:
            rspan = max(1, min(rspan, nrows - r0))
            cspan = max(1, min(cspan, ncols - c0))
            if rspan > 1 or cspan > 1:
                rspan, cspan, hit = _resolve_span_conflict(
                    r0, c0, rspan, cspan, anchor_positions
                )
                if hit is not None:
                    span_amb.append(
                        TableAmbiguity(
                            "span_uncertain", scope, (s.segment_id,),
                            "inferred span would cover a real source segment at "
                            f"row {hit[0]}, column {hit[1]} — disputed span kept at 1",
                        )
                    )
            key = (r0, c0)
            if key in anchors:
                # a second segment landed on the same anchor position: keep the
                # source-order-first literal, record every id, flag the collision.
                prev = anchors[key]
                anchors[key] = TableCell(
                    text=prev.text,
                    provenance=prev.provenance + (s.segment_id,),
                    row=r0, column=c0, rowspan=prev.rowspan, colspan=prev.colspan,
                    is_header=prev.is_header, page=page,
                )
                span_amb.append(
                    TableAmbiguity(
                        "hint_conflict", scope,
                        tuple(sorted(anchors[key].provenance)),
                        "two segments resolve to the same grid position; "
                        "kept the source-order-first literal",
                    )
                )
                continue
            anchors[key] = TableCell(
                text=s.text,
                provenance=(s.segment_id,),
                row=r0, column=c0, rowspan=rspan, colspan=cspan,
                is_header=False, page=page,
            )
            for dr in range(rspan):
                for dc in range(cspan):
                    if (dr, dc) != (0, 0):
                        covered.add((r0 + dr, c0 + dc))

        grid: list[list[TableCell]] = []
        for r in range(nrows):
            row: list[TableCell] = []
            c = 0
            while c < ncols:
                if (r, c) in covered:
                    c += 1
                    continue
                cell = anchors.get((r, c))
                if cell is None:
                    row.append(
                        TableCell(text="", provenance=(), row=r, column=c, page=page)
                    )
                    c += 1
                else:
                    row.append(cell)
                    c += cell.colspan
            grid.append(row)
        return grid, span_amb

    def _merge_wrapped_cells(
        self,
        grid: list[list[TableCell]],
        bands: list[_Band],
        clusters: list[_Cluster],
        page: int,
        scope: str,
    ) -> list[list[TableCell]]:
        """Fold a single-segment band that is a wrapped continuation line of the cell
        directly above it (same column, small vertical gap) into that cell."""
        if len(grid) < 2 or len(bands) < 2:
            return grid
        gaps = [bands[i + 1].top - bands[i].top for i in range(len(bands) - 1)]
        pitch = max(gaps) if gaps else bands[0].height
        drop_rows: set[int] = set()
        for r in range(1, len(grid)):
            filled = [c for c in grid[r] if not c.is_empty]
            if len(filled) != 1:
                continue
            cont = filled[0]
            if cont.colspan != 1 or cont.rowspan != 1 or len(cont.provenance) != 1:
                continue
            above = self._anchor_at(grid, r - 1, cont.column, drop_rows)
            if above is not None and above.row == cont.row:
                above = None  # the only candidate is the continuation row itself
            if above is None or above.is_empty or above.colspan != 1:
                continue
            offset = bands[r].top - bands[r - 1].top
            if offset <= CELL_WRAP_GAP_RATIO * pitch:
                new_text = above.text + WRAPPED_LINE_JOIN + cont.text
                merged = TableCell(
                    text=new_text,
                    provenance=above.provenance + cont.provenance,
                    row=above.row, column=above.column,
                    rowspan=above.rowspan, colspan=above.colspan,
                    is_header=above.is_header, page=page,
                )
                self._replace_cell(grid, above, merged)
                self.transforms.append(
                    SegmentTransform(
                        kind="reflow_whitespace",
                        permitted_by="FR-013",
                        segment_ids=above.provenance + cont.provenance,
                        joined_with=cont.provenance[0],
                        boundary=(
                            f"wrapped continuation line collapsed to a single space "
                            f"inside one table cell ({above.provenance[-1]} + "
                            f"{cont.provenance[0]})"
                        ),
                    )
                )
                drop_rows.add(r)
            elif offset <= CELL_WRAP_UNCERTAIN_GAP_RATIO * pitch:
                self._ambiguity(
                    "wrapped_cell_uncertain", scope,
                    above.provenance + cont.provenance,
                    "a lone segment sits below a cell in the same column but the "
                    "vertical gap is not conclusively a wrapped line — kept separate",
                )
        if not drop_rows:
            return grid
        return [row for i, row in enumerate(grid) if i not in drop_rows]

    @staticmethod
    def _anchor_at(
        grid: list[list[TableCell]], r: int, column: int, drop_rows: set[int]
    ) -> TableCell | None:
        """The cell anchored at ``column`` on the nearest logical row at or above
        ``r`` that has **not** already been folded away. A continuation line of an
        already-merged cell therefore resolves to the retained (merged) cell, so an
        arbitrary ``line1 → line2 → line3 → …`` chain accumulates in source order."""
        for rr in range(r, -1, -1):
            if rr in drop_rows:
                continue
            for c in grid[rr]:
                if c.column == column:
                    return c
            return None
        return None

    @staticmethod
    def _replace_cell(
        grid: list[list[TableCell]], old: TableCell, new: TableCell
    ) -> None:
        for row in grid:
            for i, c in enumerate(row):
                if c is old:
                    row[i] = new
                    return

    # -- stitching -------------------------------------------------------

    def _stitch(self, fragments: list[TableFragment]) -> list[list[TableFragment]]:
        groups: list[list[TableFragment]] = []
        for frag in fragments:
            if groups:
                tail = groups[-1][-1]
                header = groups[-1][0].rows[0]
                ok, signal, transparent = self._can_stitch(tail, frag, header)
                if ok:
                    self.stitch_records.append(
                        StitchRecord(
                            from_fragment_id=tail.fragment_id,
                            to_fragment_id=frag.fragment_id,
                            from_page=tail.page,
                            to_page=frag.page,
                            signal=signal,
                            transparent_segment_ids=transparent,
                        )
                    )
                    groups[-1].append(frag)
                    continue
            groups.append([frag])
        return groups

    def _intervening_ids(self, a: TableFragment, b: TableFragment) -> list[str]:
        lo = max(self.accepted_index[s] for s in a.segment_ids)
        hi = min(self.accepted_index[s] for s in b.segment_ids)
        return [self.order[i] for i in range(lo + 1, hi)]

    def _is_transparent(self, seg_id: str, stitch_pages: set[int]) -> bool:
        """May this hint-less intervening segment be ignored for *continuity
        detection only*? It stays in the document either way — transparency is never
        removal authority (that is T071 / T072)."""
        seg = self.by_id[seg_id]
        if self._has_table_hint(seg_id):
            return False
        if seg.source.physical_page not in stitch_pages:
            return False
        return self._is_page_number(seg) or self._is_repeated_furniture(seg)

    def _bare_page_number(self, seg: AcceptedSegment) -> int | None:
        """The integer of a standalone bare-number segment (hint-less), else ``None``."""
        if self._has_table_hint(seg.segment_id):
            return None
        m = PAGE_NUMBER_BARE_RE.match(seg.text)
        return int(m.group(1)) if m else None

    def _is_page_number(self, seg: AcceptedSegment) -> bool:
        if PAGE_NUMBER_RE.match(seg.text):
            return True  # explicit prefix — positive evidence on its own
        value = self._bare_page_number(seg)
        if value is None:
            return False
        page = seg.source.physical_page
        if value == page:
            return True  # printed number equals the physical page
        # adjacent-page sequence: n on page p and n±1 on page p±1
        for delta in (-1, 1):
            for other in self.by_id.values():
                if other.source.physical_page != page + delta:
                    continue
                if self._bare_page_number(other) == value + delta:
                    return True
        return False

    def _is_repeated_furniture(self, seg: AcceptedSegment) -> bool:
        """Key-exact repetition on ≥ ``FURNITURE_REPEAT_MIN_PAGES`` distinct pages at a
        position-consistent top (within ``FURNITURE_TOP_TOLERANCE``). Repeated prose at
        materially different vertical positions is content, not furniture."""
        box = _bbox(seg)
        if box is None:
            return False
        k = _key(seg.text)
        pages: set[int] = set()
        for other in self.by_id.values():
            obox = _bbox(other)
            if obox is None or _key(other.text) != k:
                continue
            if abs(obox[1] - box[1]) <= FURNITURE_TOP_TOLERANCE:
                pages.add(other.source.physical_page)
        return len(pages) >= FURNITURE_REPEAT_MIN_PAGES

    def _can_stitch(
        self, a: TableFragment, b: TableFragment, logical_header: tuple[TableCell, ...]
    ) -> tuple[bool, str, tuple[str, ...]]:
        scope = a.fragment_id
        if b.page != a.page + 1:
            return (False, "continuation_rejected", ())
        if a.page not in self.pages_in_ced or b.page not in self.pages_in_ced:
            return (False, "continuation_rejected", ())
        if len(a.column_signature) != len(b.column_signature):
            self._ambiguity(
                "continuation_rejected", scope, a.segment_ids + b.segment_ids,
                "different column counts across the page break",
            )
            return (False, "continuation_rejected", ())
        for (ax0, ax1), (bx0, bx1) in zip(
            a.column_signature, b.column_signature, strict=True
        ):
            if abs(ax0 - bx0) > COLUMN_X0_TOLERANCE:
                self._ambiguity(
                    "continuation_rejected", scope, a.segment_ids + b.segment_ids,
                    f"column left edge {ax0} vs {bx0} exceeds tolerance",
                )
                return (False, "continuation_rejected", ())
            if _interval_overlap(ax0, ax1, bx0, bx1) <= 0.0:
                self._ambiguity(
                    "continuation_rejected", scope, a.segment_ids + b.segment_ids,
                    "corresponding column intervals do not overlap",
                )
                return (False, "continuation_rejected", ())

        stitch_pages = {a.page, b.page}
        intervening = self._intervening_ids(a, b)
        transparent: list[str] = []
        for sid in intervening:
            if self._is_transparent(sid, stitch_pages):
                transparent.append(sid)
            else:
                self._ambiguity(
                    "continuation_rejected", scope, (sid,),
                    "disallowed semantic content between the page fragments "
                    f"({sid!r}) blocks the stitch",
                )
                return (False, "continuation_rejected", ())

        b_first = b.rows[0]
        header_match = _row_keys(b_first) == _row_keys(logical_header) and len(
            b_first
        ) == len(logical_header)
        if header_match:
            return (True, "repeated_header", tuple(transparent))
        if not intervening:
            return (True, "direct_continuation", tuple(transparent))
        # transparent-only gap but no positive continuation signal
        self._ambiguity(
            "continuation_rejected", scope, a.segment_ids + b.segment_ids,
            "no repeated header and not a direct continuation",
        )
        return (False, "continuation_rejected", ())

    # -- finalisation ---------------------------------------------------

    def _finalise(self, groups: list[list[TableFragment]]) -> list[TableBlock]:
        blocks: list[TableBlock] = []
        for group in groups:
            first, last = group[0], group[-1]
            pre_collapse_ids: list[str] = []
            for frag in group:
                pre_collapse_ids.extend(frag.row_major_segment_ids)
            table_id = _digest(
                "tbl-", f"{first.page}:{last.page}:{pre_collapse_ids}"
            )

            rows: list[list[TableCell]] = [list(r) for r in first.rows]
            logical_header = first.rows[0]
            for frag in group[1:]:
                frag_rows = [list(r) for r in frag.rows]
                frag_rows = self._maybe_collapse_header(
                    table_id, frag, frag_rows, logical_header
                )
                rows.extend(frag_rows)

            rows = self._reindex_and_flag_header(rows)
            has_merged = any(
                c.rowspan > 1 or c.colspan > 1 for r in rows for c in r
            )
            spans_pages = sorted({frag.page for frag in group})

            all_ids: list[str] = []
            for r in rows:
                for c in r:
                    all_ids.extend(c.provenance)
            for ch in self.collapsed_headers:
                if ch.table_id == table_id:
                    all_ids.extend(ch.segment_ids)
            self.consumed.update(all_ids)

            self._emit_grid_reorder(table_id, group, rows)

            self._record_hint_decisions(
                set(all_ids), applied=True,
                reason="segment reconstructed into a logical table cell",
            )

            table = LogicalTable(
                table_id=table_id,
                rows=rows,
                has_merged_cells=has_merged,
                header_row_count=1 if rows else 0,
                spans_pages=spans_pages,
            )
            provenance = tuple(
                x for x in _dedup(all_ids)
            )
            block = TableBlock(
                kind="table",
                block_id=_digest("blk-", table_id),
                table=table,
                provenance=provenance,
                hint_decisions=tuple(
                    d for d in self.hint_decisions
                    if d.hint_ref.split(":", 1)[0] in set(all_ids)
                ),
            )
            blocks.append(block)
        blocks.sort(key=lambda b: b.table.table_id)
        return blocks

    def _maybe_collapse_header(
        self,
        table_id: str,
        frag: TableFragment,
        frag_rows: list[list[TableCell]],
        logical_header: tuple[TableCell, ...],
    ) -> list[list[TableCell]]:
        if not frag_rows:
            return frag_rows
        candidate = frag_rows[0]
        same_shape = len(candidate) == len(logical_header) and [
            c.colspan for c in candidate
        ] == [c.colspan for c in logical_header]
        keys_match = _row_keys(candidate) == _row_keys(logical_header)
        if same_shape and keys_match:
            per_cell = tuple(
                (c.column, tuple(c.provenance)) for c in candidate if c.provenance
            )
            self.collapsed_headers.append(
                CollapsedHeader(
                    table_id=table_id,
                    page=frag.page,
                    segment_ids=tuple(
                        s for c in candidate for s in c.provenance
                    ),
                    kept_header_segment_ids=tuple(
                        s for c in logical_header for s in c.provenance
                    ),
                    per_cell=per_cell,
                )
            )
            return frag_rows[1:]
        if same_shape and _mean_ratio(candidate, logical_header) >= HEADER_RESEMBLANCE_RATIO:
            self._ambiguity(
                "header_repeat_rejected", table_id,
                (s for c in candidate for s in c.provenance),
                "continuation row resembles the header but differs materially "
                "(OCR variance / edited text) — kept as a data row, not collapsed",
            )
        return frag_rows

    @staticmethod
    def _reindex_and_flag_header(rows: list[list[TableCell]]) -> list[list[TableCell]]:
        out: list[list[TableCell]] = []
        for r, row in enumerate(rows):
            new_row: list[TableCell] = []
            for c in row:
                new_row.append(
                    TableCell(
                        text=c.text,
                        provenance=c.provenance,
                        row=r,
                        column=c.column,
                        rowspan=c.rowspan,
                        colspan=c.colspan,
                        is_header=(r == 0),
                        page=c.page,
                    )
                )
            out.append(new_row)
        return out

    def _emit_grid_reorder(
        self, table_id: str, group: list[TableFragment], rows: list[list[TableCell]]
    ) -> None:
        """Record a table-scoped reorder **only** over the retained logical cells. A
        collapsed continuation header has no logical position — its lineage is the
        :class:`CollapsedHeader`, never an artificial slot in ``to_order``."""
        row_major: list[str] = []
        for r in rows:
            for c in r:
                row_major.extend(c.provenance)
        row_major = _dedup(row_major)
        affected = set(row_major)
        accepted = [s for s in self.order if s in affected]
        if accepted != row_major and len(row_major) == len(accepted):
            self.structural_reorder.append(
                StructuralReorder(
                    scope=table_id,
                    affected_segment_ids=tuple(sorted(affected)),
                    from_order=tuple(accepted),
                    to_order=tuple(row_major),
                    reason=(
                        "accepted source segment order differs from the deterministic "
                        "row-major table cell order"
                    ),
                    permitted_by="FR-020",
                )
            )


# --- span inference (pure) -----------------------------------------------------


def _span(
    lo: float,
    hi: float,
    intervals: list[tuple[float, float]],
    scope: str,
    seg_id: str,
) -> tuple[int, int, list[TableAmbiguity]]:
    """Which interval index the ``[lo, hi]`` extent anchors to, and how many contiguous
    intervals it spans. Ambiguous partial overlap → span 1 + a ``span_uncertain``
    ambiguity. Non-contiguous overlap → span 1 + a ``span_uncertain`` ambiguity."""
    extent = max(hi - lo, 1.0)
    ratios = [
        _interval_overlap(lo, hi, a, b) / min(extent, max(b - a, 1.0))
        for (a, b) in intervals
    ]
    strong = [i for i, r in enumerate(ratios) if r >= SPAN_OVERLAP_MIN_RATIO]
    partial = [
        i for i, r in enumerate(ratios)
        if SPAN_UNCERTAIN_MIN_RATIO < r < SPAN_OVERLAP_MIN_RATIO
    ]
    amb: list[TableAmbiguity] = []
    if not strong:
        # anchor to the best-overlapping interval, span 1
        best = max(range(len(ratios)), key=lambda i: ratios[i]) if ratios else 0
        if partial:
            amb.append(
                TableAmbiguity(
                    "span_uncertain", scope, (seg_id,),
                    "partial overlap with a cell boundary — span kept at 1",
                )
            )
        return (best, 1, amb)
    first, last = strong[0], strong[-1]
    contiguous = strong == list(range(first, last + 1))
    if not contiguous:
        amb.append(
            TableAmbiguity(
                "span_uncertain", scope, (seg_id,),
                "overlaps non-contiguous cell intervals — span kept at 1",
            )
        )
        return (first, 1, amb)
    if partial and last + 1 in partial:
        amb.append(
            TableAmbiguity(
                "span_uncertain", scope, (seg_id,),
                "a further neighbouring cell is partially overlapped — span kept "
                "at the corroborated extent",
            )
        )
    span = last - first + 1
    if partial and any(p < first or p > last for p in partial) and span == 1:
        amb.append(
            TableAmbiguity(
                "span_uncertain", scope, (seg_id,),
                "adjacent partial overlap — span kept at 1",
            )
        )
    return (first, span, amb)


def _resolve_span_conflict(
    r0: int,
    c0: int,
    rspan: int,
    cspan: int,
    anchor_positions: set[tuple[int, int]],
) -> tuple[int, int, tuple[int, int] | None]:
    """Reduce an inferred span so it never covers another real anchor. The disputed
    dimension collapses to 1 (a conflict on the same column → ``rowspan``; on the same
    row → ``colspan``; diagonal → both). Returns the resolved spans and the first
    conflicting position in ``(row, column)`` order, or ``None`` when undisputed."""
    conflicts = sorted(
        (r0 + dr, c0 + dc)
        for dr in range(rspan)
        for dc in range(cspan)
        if (dr, dc) != (0, 0) and (r0 + dr, c0 + dc) in anchor_positions
    )
    if not conflicts:
        return rspan, cspan, None
    for (rr, cc) in conflicts:
        if rr > r0 and cc == c0:
            rspan = 1
        elif rr == r0 and cc > c0:
            cspan = 1
        else:
            rspan, cspan = 1, 1
    return rspan, cspan, conflicts[0]


def _row_keys(row) -> tuple[str, ...]:
    return tuple(_key(c.text) for c in row)


def _mean_ratio(a_row, b_row) -> float:
    """Mean per-cell ``difflib`` similarity of two equal-length rows (deterministic)."""
    if not a_row:
        return 0.0
    ratios = [
        difflib.SequenceMatcher(None, _key(a.text), _key(b.text)).ratio()
        for a, b in zip(a_row, b_row, strict=True)
    ]
    return sum(ratios) / len(ratios)


def _dedup(ids: list[str]) -> list[str]:
    seen: set[str] = set()
    return [x for x in ids if not (x in seen or seen.add(x))]
