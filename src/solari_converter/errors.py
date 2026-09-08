"""Exception types (phased — T008 / T016).

T008 (Phase 2) defines ONLY the OCR exception types below — the permanent
definitions the OCR engine adapters raise. T016 (Phase 3) extends this module
with the remaining exception classes (``InvalidSelection``, ``SourceUnreadable``,
``LLMUnavailable``, ``OutputCollision``, ``HumanReviewRequired``,
``ResourceExhausted``) and the complete exit-code constant mapping.

This module MUST NOT gain exit-code constants or any exception->exit mapping here.
"""

from __future__ import annotations


class OcrError(Exception):
    """Base class for OCR-engine failures."""


class OcrUnavailable(OcrError):
    """A configured OCR engine cannot be used — missing binary, language data, or
    model files. Mapped to process exit code 8 by T016 / the CLI (T081)."""
