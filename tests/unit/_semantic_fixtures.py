"""Shared builders for the Stage-3 (semantic transform) unit tests — T066.

Stage 3 consumes the **Canonical Extracted Document only** (research §21 / FR-064), so
these helpers assemble a ``CanonicalExtractedDocument`` directly from lightweight segment
specs. No PDF, no extraction, no reconciliation.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from solari_converter.model.canonical import (
    AcceptedDecision,
    AcceptedSegment,
    CanonicalExtractedDocument,
    CarriedStructuralHint,
    PageClassEntry,
)
from solari_converter.model.provenance import SourceRef

_ENV = dict(
    run_id="0" * 16, tool_version="0.1.0", source_pdf="doc.pdf",
    source_sha256="a" * 64, page_selection="all",
)


@dataclass
class Seg:
    """One accepted-segment spec. ``bbox`` is ``(x0, top, x1, bottom)`` — top-based."""

    sid: str
    text: str
    bbox: tuple[float, float, float, float]
    page: int = 1
    origin: str = "native_text"
    technique: str = "pdfplumber"
    ocr_conf: float | None = None
    hints: list[tuple] = field(default_factory=list)  # (kind, level|None, source_technique)


def ced(segs: list[Seg], *, order: list[str] | None = None) -> CanonicalExtractedDocument:
    accepted = [
        AcceptedSegment(
            segment_id=s.sid,
            text=s.text,
            source=SourceRef(
                physical_page=s.page, bbox=s.bbox, origin_kind=s.origin,
                extraction_technique=s.technique, ocr_confidence=s.ocr_conf,
            ),
            contributing_techniques=[s.technique],
            decision=AcceptedDecision(method="deterministic_agreement", decision_id=f"d-{s.sid}"),
        )
        for s in segs
    ]
    hints = [
        CarriedStructuralHint(
            kind=k, level=lvl, source_technique=tech, segment_id=s.sid,
        )
        for s in segs
        for (k, lvl, tech) in s.hints
    ]
    by_page: dict[int, str] = {}
    for s in segs:
        by_page.setdefault(s.page, "native_text_sufficient")
    return CanonicalExtractedDocument(
        **_ENV,
        accepted_segments=accepted,
        accepted_reading_order=order or [s.sid for s in segs],
        carried_structural_hints=hints,
        page_classes=[
            PageClassEntry(page=p, **{"class": c}) for p, c in sorted(by_page.items())
        ],
    )
