"""Extraction-candidate model (T020).

One ``ExtractionCandidate`` is one independent extraction path's output (FR-060): its
verbatim segments, its own reading-order opinion (evidence only — FR-060b), the structural
hints it noticed, and — for the OCR path — a per-region OCR record. The three paths never
see each other's candidates (M2); ``reconcile/runner`` (T051) is the only meeting point.

Matches ``contracts/extraction-candidate.schema.json`` (record_type ``extraction_candidate``,
schema_version ``2.0``). The shared envelope base is refactored into ``reports/base.py`` by
T028; until then each record model declares the seven envelope fields directly.
"""

from __future__ import annotations

import enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from solari_converter.model.segment import SourceBackedSegment, StructuralHint

__all__ = [
    "PageClass",
    "CandidateReadingOrder",
    "RegionOcrRecord",
    "ExtractionCandidate",
    "StructuralHint",  # re-exported (defined in model/segment.py to avoid an import cycle)
]

_TECHNIQUE = r"^(docling|pdfplumber|ocr:[a-z0-9_-]+)$"


class PageClass(enum.StrEnum):
    """Per page (and per region where subdivided) — FR-024b."""

    NATIVE_TEXT_SUFFICIENT = "native_text_sufficient"
    OCR_REQUIRED = "ocr_required"
    HYBRID_NATIVE_AND_OCR = "hybrid_native_and_ocr"


class CandidateReadingOrder(BaseModel):
    """One candidate's ordered segment list (FR-015). Evidence only — never authoritative
    until reconciliation accepts it."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    technique: str = Field(min_length=1)
    order: list[str] = Field(default_factory=list)


class RegionOcrRecord(BaseModel):
    """Per-page/region OCR provenance on the OCR candidate (FR-025 / FR-027 / FR-027a)."""

    model_config = ConfigDict(extra="forbid")

    physical_page: int = Field(ge=1)
    region_bbox: tuple[float, float, float, float] | None = None
    ran_ocr: bool
    languages: list[str] = Field(default_factory=list)
    language_source: Literal["auto", "override"]
    mean_confidence: float = Field(ge=0, le=100)
    confidence_threshold: float = Field(
        ge=0, le=100, description="effective normalised-0–100 per-run value (default 70)"
    )
    low_confidence_regions: int = Field(ge=0)


class ExtractionCandidate(BaseModel):
    """One independent extraction path's persisted output."""

    model_config = ConfigDict(extra="forbid")

    # --- envelope (data-model.md — Common envelope) ---
    record_type: Literal["extraction_candidate"] = "extraction_candidate"
    schema_version: Literal["2.0"] = "2.0"
    run_id: str = Field(pattern=r"^[a-f0-9]{16}$")
    tool_version: str = Field(min_length=1)
    source_pdf: str = Field(min_length=1)
    source_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    page_selection: str = Field(min_length=1)
    # --- body ---
    technique: str = Field(pattern=_TECHNIQUE)
    status: Literal["ok", "partial", "failed"] = "ok"
    status_detail: str | None = None
    segments: list[SourceBackedSegment] = Field(default_factory=list)
    reading_order: CandidateReadingOrder
    pages_covered: list[int] = Field(default_factory=list)
    page_ocr: list[RegionOcrRecord] = Field(default_factory=list)
