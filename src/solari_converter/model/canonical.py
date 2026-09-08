"""Canonical Extracted Document (T022).

The stage-2 reconciliation output (FR-063): accepted verbatim segments, the accepted
source reading order (FR-061d), the structural hints **carried but not applied** (FR-061c),
and per-page classification. ``state`` is frozen at ``pre_semantic_transformation`` — the
CED is never mutated in place; stage 3 builds a new ``SemanticDocument`` from it.

Matches ``contracts/canonical-extracted-document.schema.json`` (record_type
``canonical_extracted_document``, schema_version ``2.0``).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from solari_converter.model.candidate import PageClass
from solari_converter.model.provenance import SourceRef
from solari_converter.model.segment import StructuralHint

__all__ = ["AcceptedSegment", "CarriedStructuralHint", "PageClassEntry",
           "CanonicalExtractedDocument"]


class AcceptedDecision(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    method: Literal["deterministic_agreement", "llm_selected", "human_confirmed"]
    decision_id: str = Field(min_length=1)


class AcceptedSegment(BaseModel):
    """A segment reconciliation accepted into the CED. Never mutated in place (FR-063)."""

    model_config = ConfigDict(extra="forbid")

    segment_id: str = Field(min_length=1)
    text: str = Field(description="verbatim; equals some contributing candidate's text (SC-020)")
    source: SourceRef
    contributing_techniques: list[str] = Field(min_length=1)
    decision: AcceptedDecision


class CarriedStructuralHint(StructuralHint):
    """A ``StructuralHint`` carried into the CED, tagged with the segment it belongs to.
    Unapplied here — stage 3 decides (FR-061c / FR-064)."""

    segment_id: str = Field(min_length=1)


class PageClassEntry(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    page: int = Field(ge=1)
    region_bbox: tuple[float, float, float, float] | None = None
    class_: PageClass = Field(alias="class")


class CanonicalExtractedDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # --- envelope ---
    record_type: Literal["canonical_extracted_document"] = "canonical_extracted_document"
    schema_version: Literal["2.0"] = "2.0"
    run_id: str = Field(pattern=r"^[a-f0-9]{16}$")
    tool_version: str = Field(min_length=1)
    source_pdf: str = Field(min_length=1)
    source_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    page_selection: str = Field(min_length=1)
    # --- body ---
    state: Literal["pre_semantic_transformation"] = "pre_semantic_transformation"
    accepted_segments: list[AcceptedSegment] = Field(default_factory=list)
    accepted_reading_order: list[str] = Field(default_factory=list)
    carried_structural_hints: list[CarriedStructuralHint] = Field(default_factory=list)
    page_classes: list[PageClassEntry] = Field(default_factory=list)
