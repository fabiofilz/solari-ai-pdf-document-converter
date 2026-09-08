"""Provenance value types (T018).

``SourceRef`` rides on every segment and every accepted value — it is the fidelity
audit trail (FR-025a / FR-060a / FR-066): which physical page, where on it, whether the
text came from a PDF text layer or local OCR, by which technique, in which language(s),
and — for OCR — the minimum per-token confidence normalised to 0–100 (research §9a).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

OriginKind = Literal["native_text", "ocr"]
BBox = tuple[float, float, float, float]


class SourceRef(BaseModel):
    """Where a piece of text came from (data-model.md — Layer 1)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    physical_page: int = Field(ge=1, description="1-based physical PDF page (FR-003)")
    bbox: BBox | None = Field(
        default=None,
        description="PDF user-space box [x0,y0,x1,y1]; null only for synthesized wrappers",
    )
    origin_kind: OriginKind
    extraction_technique: str = Field(
        min_length=1, description="docling | pdfplumber | ocr:<engine> (FR-060a)"
    )
    ocr_languages: list[str] = Field(
        default_factory=list, description="BCP-47-ish; empty for native_text"
    )
    ocr_confidence: float | None = Field(
        default=None, ge=0, le=100,
        description="min per-word/token, normalised 0–100 (research §9a); null for native_text",
    )
