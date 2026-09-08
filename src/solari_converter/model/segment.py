"""Source-backed segments and their stable identity (T019).

A ``SourceBackedSegment`` is one contiguous piece of **verbatim** extracted text with its
provenance and this candidate's reading-order position. Its ``segment_id`` is stable across
the independent extraction paths and is the key used in reconciliation and in review items:

    segment_id = sha1(f"{page}:{round(bbox)}:{nfc_text_hash}")[:12]

(data-model.md — Layer 1). The bbox is rounded before hashing so sub-pixel jitter between
techniques does not fork the id; the text is NFC-normalised **for the hash only** — the
stored ``text`` is never normalised.

``StructuralHint`` lives here because a hint is attached to a segment; ``model/candidate.py``
(T020) re-exports it so the plan.md project structure ("candidate.py: … StructuralHint")
still holds without an import cycle.
"""

from __future__ import annotations

import hashlib
import unicodedata
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from solari_converter.model.provenance import BBox, SourceRef

__all__ = ["StructuralHint", "SourceBackedSegment", "segment_id"]

HintKind = Literal[
    "heading", "subheading", "list_item", "list_start", "list_end",
    "table", "table_row", "table_cell", "caption", "other",
]


class StructuralHint(BaseModel):
    """Advisory structural evidence (FR-060b / FR-061c). Carried into the CED unaltered;
    applied — or not — only by stage 3, which records the use (FR-064)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: HintKind
    level: int | None = Field(default=None, ge=1)
    source_technique: str = Field(min_length=1)
    payload: dict = Field(default_factory=dict)


def segment_id(*, page: int, bbox: BBox | list[float], text: str) -> str:
    """The stable 12-hex segment identity (data-model.md — Layer 1)."""
    nfc_text_hash = hashlib.sha1(
        unicodedata.normalize("NFC", text).encode()
    ).hexdigest()
    rounded = [round(v) for v in bbox]
    return hashlib.sha1(
        f"{page}:{rounded}:{nfc_text_hash}".encode()
    ).hexdigest()[:12]


class SourceBackedSegment(BaseModel):
    """One extraction path's view of a contiguous piece of source text."""

    model_config = ConfigDict(extra="forbid")

    segment_id: str = Field(min_length=1)
    text: str = Field(description="verbatim extracted text — never a normalised form")
    source: SourceRef
    reading_order_index: int = Field(ge=0)
    structural_hints: list[StructuralHint] = Field(default_factory=list)
