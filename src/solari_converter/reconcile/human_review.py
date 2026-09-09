"""Reconciliation → Human Review queue boundary (T061).

The **headless** boundary only: when deterministic reconciliation + the restricted LLM
selector cannot resolve a conflict, this module turns the unresolved
:class:`~solari_converter.reconcile.llm_select.DecisionResult` into a
:class:`~solari_converter.model.human_review.HumanReviewItem` and assembles the per-run
:class:`~solari_converter.model.human_review.HumanReviewQueue` with the trivial derived
``run_state: "unresolved"`` (open items exist). The full 5-state precedence derivation is
``review/session`` (T143); the interactive Phase-9 UI is not here.

* the item ``id`` is **deterministic from the applicability key** (FR-062 / §22) so a
  re-run raises the *same* id for the *same* conflict;
* the item keeps enough evidence for later review (FR-075): physical page, conflict type,
  candidate values / orders, region bboxes, contributing techniques, representative
  segment refs, applicability key (as the id), structural / source context;
* **no semantic transformation, no LLM, no Markdown, no persistence** — the engine (T064)
  writes the queue file.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from solari_converter.model.human_review import (
    CandidateEvidence,
    HumanReviewItem,
    HumanReviewQueue,
    StructuralContext,
)

__all__ = [
    "hr_item_id",
    "provenance_label",
    "raise_literal_item",
    "raise_reading_order_item",
    "assemble_queue",
]

BBox = tuple[float, float, float, float]


def hr_item_id(applicability_key: str) -> str:
    """The deterministic queue-item id — the first 16 hex of the applicability key
    (which already binds source hash + conflict identity + config subset, §22)."""
    return applicability_key[:16]


def provenance_label(technique: str, physical_page: int, ocr_confidence: float | None) -> str:
    """FR-075 human-readable source label, e.g. ``"layout path (docling), p.5"`` /
    ``"OCR (tesseract; conf 82), p.5"``."""
    if technique.startswith("ocr:"):
        engine = technique.split(":", 1)[1]
        conf = f"; conf {ocr_confidence:g}" if ocr_confidence is not None else ""
        return f"OCR ({engine}{conf}), p.{physical_page}"
    friendly = {"docling": "layout path (docling)", "pdfplumber": "geometry path (pdfplumber)"}
    return f"{friendly.get(technique, technique)}, p.{physical_page}"


def _candidate_evidence(
    raw: Sequence[Mapping[str, Any]], physical_page: int
) -> list[CandidateEvidence]:
    out: list[CandidateEvidence] = []
    for c in raw:
        out.append(
            CandidateEvidence(
                technique=c["technique"],
                value=c.get("value"),
                order=list(c["order"]) if c.get("order") is not None else None,
                ocr_confidence=c.get("ocr_confidence"),
                provenance_label=provenance_label(
                    c["technique"], physical_page, c.get("ocr_confidence")
                ),
            )
        )
    return out


def _bboxes(region_bboxes: Sequence[Sequence[float]]) -> list[BBox]:
    return [tuple(float(v) for v in b) for b in region_bboxes]


def raise_literal_item(
    *,
    applicability_key: str,
    physical_page: int,
    region_bboxes: Sequence[Sequence[float]],
    candidates_evidence: Sequence[Mapping[str, Any]],
    contributing_sources: Sequence[str],
    reason: str,
    confidence: float | None,
    segment_refs: Sequence[str] | None = None,
    structural_context: Mapping[str, Any] | None = None,
    source_context_before: str | None = None,
    source_context_after: str | None = None,
) -> HumanReviewItem:
    """Build the ``literal_content`` queue item for an unresolved literal conflict."""
    return HumanReviewItem(
        id=hr_item_id(applicability_key),
        conflict_type="literal_content",
        status="open",
        physical_page=physical_page,
        region_bboxes=_bboxes(region_bboxes),
        contributing_sources=list(contributing_sources),
        reason=reason,
        confidence=confidence,
        candidates=_candidate_evidence(candidates_evidence, physical_page),
        segment_refs=list(segment_refs) if segment_refs else None,
        structural_context=(
            StructuralContext(**dict(structural_context)) if structural_context else None
        ),
        source_context_before=source_context_before,
        source_context_after=source_context_after,
    )


def raise_reading_order_item(
    *,
    applicability_key: str,
    physical_page: int,
    region_bboxes: Sequence[Sequence[float]],
    candidates_evidence: Sequence[Mapping[str, Any]],
    segment_ids: Sequence[str],
    contributing_sources: Sequence[str],
    reason: str,
    confidence: float | None,
    segment_refs: Sequence[str] | None = None,
    structural_context: Mapping[str, Any] | None = None,
) -> HumanReviewItem:
    """Build the ``reading_order`` queue item for an unresolved ordering conflict. The
    ``segment_ids`` are the exact set an ``--order`` resolution must permute (FR-062d)."""
    return HumanReviewItem(
        id=hr_item_id(applicability_key),
        conflict_type="reading_order",
        status="open",
        physical_page=physical_page,
        region_bboxes=_bboxes(region_bboxes),
        contributing_sources=list(contributing_sources),
        reason=reason,
        confidence=confidence,
        candidates=_candidate_evidence(candidates_evidence, physical_page),
        segment_ids=list(segment_ids),
        segment_refs=list(segment_refs) if segment_refs else None,
        structural_context=(
            StructuralContext(**dict(structural_context)) if structural_context else None
        ),
    )


def assemble_queue(
    items: Sequence[HumanReviewItem], *, envelope: Mapping[str, Any]
) -> HumanReviewQueue:
    """Assemble the per-run queue. ``run_state`` is written **directly** as
    ``"unresolved"`` — the trivial case (open items exist). The general precedence
    derivation belongs to ``review/session`` (T143), not here."""
    items = list(items)
    return HumanReviewQueue(
        **dict(envelope),
        items=items,
        run_state="unresolved",
        summary={
            "open": sum(1 for it in items if it.status == "open"),
            "resolved": sum(1 for it in items if it.status == "resolved"),
        },
    )
