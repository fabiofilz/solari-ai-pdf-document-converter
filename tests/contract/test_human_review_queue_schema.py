"""T038 [US1] — contract test: ``HumanReviewQueue`` ↔ ``human-review-queue.schema.json`` (v2.1).

GREEN now (owner T024):
    * a built queue (literal + reading-order items) conforms to the committed v2.1 schema;
    * literal items carry the FR-062a fields; reading-order items carry ``segment_ids`` (FR-062d);
    * the FR-075 presentation fields (``structural_context``, ``source_context_before/after``,
      per-candidate ``provenance_label``, ``segment_refs``) are modelled;
    * ``candidates`` uses the shared ``candidateEvidence`` shape (L3);
    * ``run_state`` is a **required** field whose enum is exactly the precedence order
      ``unresolved → delivery_blocked_verification_failed → delivered → authorized →
      resolved_unauthorized``;
    * a queue's ``summary`` must match its item counts (a queue with an ``open`` item ⇒ the run
      wrote no ``<base>.md`` — enforced downstream by the delivery gate).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from solari_converter.model.human_review import (
    CandidateEvidence,
    HumanReviewItem,
    HumanReviewQueue,
    StructuralContext,
)

from ._schema_subset import assert_valid

_SCHEMA = json.loads(
    (
        Path(__file__).resolve().parents[2]
        / "specs/001-pdf-markdown-converter/contracts/human-review-queue.schema.json"
    ).read_text(encoding="utf-8")
)

_ENV = dict(
    run_id="0" * 16, tool_version="0.1.0", source_pdf="agreement.pdf",
    source_sha256="a" * 64, page_selection="all",
)

_PRECEDENCE = [
    "unresolved", "delivery_blocked_verification_failed", "delivered",
    "authorized", "resolved_unauthorized",
]


def _literal_item() -> HumanReviewItem:
    return HumanReviewItem(
        id="i-lit", conflict_type="literal_content", physical_page=5,
        region_bboxes=[(10.0, 20.0, 100.0, 32.0)],
        contributing_sources=["pdfplumber", "ocr:tesseract"],
        reason="material disagreement below 0.75", confidence=0.61,
        candidates=[
            CandidateEvidence(technique="pdfplumber", value="Cláusula 4ª",
                              provenance_label="layout path (pdfplumber), p.5"),
            CandidateEvidence(technique="ocr:tesseract", value="Clausula 4a", ocr_confidence=71.0,
                              provenance_label="OCR (tesseract; pt; conf 71)"),
        ],
        segment_refs=["seg1"],
        structural_context=StructuralContext(section_path=["I", "4"], table_id=None),
        source_context_before="… as partes acordam ", source_context_after=" do presente contrato.",
    )


def _order_item() -> HumanReviewItem:
    return HumanReviewItem(
        id="i-ord", conflict_type="reading_order", physical_page=6,
        region_bboxes=[(0.0, 0.0, 200.0, 400.0)],
        contributing_sources=["pdfplumber", "docling"],
        reason="two-column ambiguity", confidence=0.5,
        candidates=[
            CandidateEvidence(technique="pdfplumber", order=["s1", "s2", "s3"]),
            CandidateEvidence(technique="docling", order=["s1", "s3", "s2"]),
        ],
        segment_ids=["s1", "s2", "s3"],
    )


def _queue(*items: HumanReviewItem, run_state: str = "unresolved") -> HumanReviewQueue:
    return HumanReviewQueue(
        **_ENV, items=list(items), run_state=run_state,
        summary={
            "open": sum(1 for it in items if it.status == "open"),
            "resolved": sum(1 for it in items if it.status == "resolved"),
        },
    )


def test_a_built_queue_conforms_to_the_committed_v21_schema() -> None:
    assert_valid(json.loads(_queue(_literal_item(), _order_item()).model_dump_json()), _SCHEMA)


def test_reading_order_item_requires_segment_ids_fr062d() -> None:
    with pytest.raises(ValueError):
        HumanReviewItem(
            id="x", conflict_type="reading_order", physical_page=1,
            region_bboxes=[(0.0, 0.0, 1.0, 1.0)], contributing_sources=["a", "b"],
            reason="r", candidates=[CandidateEvidence(technique="a", order=["s1"])],
        )


def test_candidates_use_the_shared_candidate_evidence_shape_l3() -> None:
    defs = _SCHEMA["$defs"]["candidateEvidence"]
    assert defs["required"] == ["technique"]
    assert set(defs["properties"]) >= {
        "technique", "value", "order", "ocr_confidence", "provenance_label"
    }
    item_cands = _SCHEMA["properties"]["items"]["items"]["properties"]["candidates"]
    assert item_cands["items"] == {"$ref": "#/$defs/candidateEvidence"}


def test_run_state_is_required_and_in_precedence_order() -> None:
    assert "run_state" in _SCHEMA["required"]
    assert _SCHEMA["properties"]["run_state"]["enum"] == _PRECEDENCE
    with pytest.raises(ValueError):
        HumanReviewQueue(
            **_ENV, items=[], run_state="in_progress",  # type: ignore[arg-type]
            summary={"open": 0, "resolved": 0},
        )


def test_summary_must_match_item_counts() -> None:
    with pytest.raises(ValueError):
        HumanReviewQueue(**_ENV, items=[_literal_item()], run_state="unresolved",
                         summary={"open": 0, "resolved": 0})
