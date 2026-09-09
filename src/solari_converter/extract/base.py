"""Extraction-path protocol + per-path error capture (T043).

Each independent extraction path (A = Docling, B = pdfplumber+pypdfium2, C = OCR) is an
:class:`ExtractionPath` that turns the **source PDF** into one :class:`ExtractionCandidate`
— verbatim segments, its own reading-order opinion (evidence only, FR-060b), and structural
hints. The paths never see each other's output (M2); ``extract/runner`` (T051) is the only
meeting point, and only as a ``list[ExtractionCandidate]``.

:func:`run_path` is the boundary that keeps one path's failure from aborting the run
(FR-060 edge case): a path that raises — or returns nothing usable — is recorded as a
``status="failed"`` (or ``"partial"``) candidate with a ``status_detail`` string, never an
exception that propagates. Reconciliation then works from whatever candidates succeeded.

This module holds **no** extraction logic and imports **no** concrete path.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Protocol, runtime_checkable

from solari_converter.model.candidate import CandidateReadingOrder, ExtractionCandidate

__all__ = ["ExtractionPath", "EnvelopeFields", "run_path", "failed_candidate"]

# The seven common-envelope fields the runner passes to every path so a failed path can
# still emit a well-formed candidate.
EnvelopeFields = Mapping[str, Any]
_ENVELOPE_KEYS = (
    "run_id", "tool_version", "source_pdf", "source_sha256", "page_selection",
)


@runtime_checkable
class ExtractionPath(Protocol):
    """One independent extraction technique. Implementations live in ``extract/*_path.py``
    (T046 / T047 / T050) and import none of each other."""

    #: ``"docling"`` | ``"pdfplumber"`` | ``"ocr:<engine>"`` (FR-060a).
    technique: str

    def extract(self, source: Any, *, envelope: EnvelopeFields) -> ExtractionCandidate:
        """Read ``source`` (a ``pdf/loader`` handle) and return this path's candidate.
        May raise — :func:`run_path` converts a raise into a ``failed`` candidate."""
        ...


def failed_candidate(
    technique: str,
    envelope: EnvelopeFields,
    detail: str,
    *,
    status: str = "failed",
) -> ExtractionCandidate:
    """A well-formed placeholder candidate for a path that could not produce output."""
    env = {k: envelope[k] for k in _ENVELOPE_KEYS}
    return ExtractionCandidate(
        **env,
        technique=technique,
        status=status,  # "failed" | "partial"
        status_detail=detail,
        segments=[],
        reading_order=CandidateReadingOrder(technique=technique, order=[]),
        pages_covered=[],
    )


def run_path(path: ExtractionPath, source: Any, *, envelope: EnvelopeFields) -> ExtractionCandidate:
    """Run one path, capturing any failure as a ``failed`` candidate (FR-060 edge case)."""
    try:
        candidate = path.extract(source, envelope=envelope)
    except Exception as exc:  # noqa: BLE001 — a path failure must not abort the run
        return failed_candidate(path.technique, envelope, f"{type(exc).__name__}: {exc}")
    if candidate is None:  # a path that returned nothing usable
        return failed_candidate(path.technique, envelope, "path returned no candidate")
    return candidate
