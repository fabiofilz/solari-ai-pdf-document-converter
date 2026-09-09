"""Canonical Extracted Document construction (T063).

Builds the :class:`~solari_converter.model.canonical.CanonicalExtractedDocument` from the
**resolved** literal decisions + the accepted reading order + the carried (never applied)
structural hints + per-page classification, and persists it as **JSON only** (M1). The CED
is ``state = "pre_semantic_transformation"`` and is never mutated in place (FR-063) — stage
3 builds a fresh ``SemanticDocument`` from it.

**No semantic transformation** here: accepted literal values are copied **verbatim** from
the reconciliation decision; no dehyphenation, reflow, heading/list/table inference,
artifact removal, or escaping. Every ``AcceptedSegment`` keeps the representative
``SourceRef`` + segment id (M3: representative = ``docling > pdfplumber > OCR`` member,
independent of the selected value), the sorted union of contributing techniques, and the
deterministic ``{method, decision_id}`` link. It is built **only** when reconciliation left
no unresolved Human Review item (the engine enforces this — a partial CED is never
persisted).
"""

from __future__ import annotations

import os
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

from solari_converter import artifacts_io
from solari_converter.model.candidate import ExtractionCandidate, PageClass
from solari_converter.model.canonical import (
    AcceptedDecision,
    AcceptedSegment,
    CanonicalExtractedDocument,
    CarriedStructuralHint,
    PageClassEntry,
)
from solari_converter.model.reconciliation import ReconciliationDecision
from solari_converter.model.segment import StructuralHint
from solari_converter.reconcile.align import AlignedSegmentGroup
from solari_converter.reconcile.confidence import preferred_technique
from solari_converter.run_identity import canonical_json

__all__ = ["representative_member", "build_canonical", "persist_canonical"]


def representative_member(group: AlignedSegmentGroup) -> Any:
    """The group member chosen by the narrowed technique precedence
    (``docling > pdfplumber > OCR``) — the source-evidence identity for the CED. This is
    **independent of the reconciled value** (M3)."""
    winner = preferred_technique(m.technique for m in group.members)
    return next(m for m in group.members if m.technique == winner)


def _hints_by_segment(
    candidates: Iterable[ExtractionCandidate],
) -> dict[str, list[StructuralHint]]:
    out: dict[str, list[StructuralHint]] = {}
    for cand in candidates:
        for seg in cand.segments:
            if seg.structural_hints:
                out.setdefault(seg.segment_id, []).extend(seg.structural_hints)
    return out


def _page_class(origins: set[str]) -> PageClass:
    if origins == {"native_text"}:
        return PageClass.NATIVE_TEXT_SUFFICIENT
    if origins == {"ocr"}:
        return PageClass.OCR_REQUIRED
    return PageClass.HYBRID_NATIVE_AND_OCR


def build_canonical(
    *,
    envelope: Mapping[str, Any],
    groups: Sequence[AlignedSegmentGroup],
    decisions_by_group: Mapping[str, ReconciliationDecision],
    accepted_reading_order: Sequence[str],
    candidates: Iterable[ExtractionCandidate] = (),
) -> CanonicalExtractedDocument:
    """Assemble the CED. ``decisions_by_group`` maps ``group_id`` → the resolved
    literal :class:`ReconciliationDecision`; ``accepted_reading_order`` is the accepted
    order as **representative segment ids** (it must cover exactly the accepted segments).
    """
    reps = {g.group_id: representative_member(g) for g in groups}
    hints_by_seg = _hints_by_segment(candidates)

    accepted: list[AcceptedSegment] = []
    for g in groups:
        d = decisions_by_group[g.group_id]
        rep = reps[g.group_id]
        accepted.append(
            AcceptedSegment(
                segment_id=rep.segment_id,
                text=d.selected["value"],  # verbatim; SC-020 for automatic decisions
                source=rep.source,
                contributing_techniques=sorted(
                    {m.technique for m in g.members}
                    | {c.technique for c in g.corroborations}  # §21a coverage evidence
                ),
                decision=AcceptedDecision(method=d.method, decision_id=d.decision_id),
            )
        )

    carried: list[CarriedStructuralHint] = []
    for g in groups:
        rep_id = reps[g.group_id].segment_id
        seen: set[tuple[Any, ...]] = set()
        hint_segment_ids = [m.segment_id for m in g.members] + [
            c.segment_id for c in g.corroborations  # §21a: coarse member's hints kept
        ]
        for sid in hint_segment_ids:
            for h in hints_by_seg.get(sid, []):
                sig = (h.kind, h.level, h.source_technique, canonical_json(h.payload))
                if sig in seen:
                    continue
                seen.add(sig)
                carried.append(
                    CarriedStructuralHint(
                        kind=h.kind, level=h.level, source_technique=h.source_technique,
                        payload=dict(h.payload), segment_id=rep_id,
                    )
                )

    order = list(accepted_reading_order)
    accepted_ids = {s.segment_id for s in accepted}
    if set(order) != accepted_ids or len(order) != len(accepted_ids):
        raise ValueError(
            "accepted_reading_order must cover exactly the accepted segments "
            f"({sorted(order)} vs {sorted(accepted_ids)})"
        )

    by_page: dict[int, set[str]] = {}
    for s in accepted:
        by_page.setdefault(s.source.physical_page, set()).add(s.source.origin_kind)
    page_classes = [
        PageClassEntry(page=p, class_=_page_class(o)) for p, o in sorted(by_page.items())
    ]

    return CanonicalExtractedDocument(
        **dict(envelope),
        accepted_segments=accepted,
        accepted_reading_order=order,
        carried_structural_hints=carried,
        page_classes=page_classes,
    )


def persist_canonical(
    ced: CanonicalExtractedDocument, output_dir: str | os.PathLike[str], base: str
) -> Path:
    """Write ``<output-dir>/<base>.canonical-extracted-document.json`` (JSON only — M1)."""
    stem = Path(output_dir) / f"{base}.canonical-extracted-document"
    return artifacts_io.write_record(stem, ced, emit_md=False)[0]
