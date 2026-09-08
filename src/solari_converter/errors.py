"""Exception types and the process exit-code map (phased — T008 / T016).

* **T008 (Phase 2)** defined only the OCR exception types (``OcrError`` / ``OcrUnavailable``)
  — the permanent definitions the OCR engine adapters raise. Their class hierarchy is
  frozen and unchanged here.
* **T016 (Phase 3)** extends this module with the remaining exception classes and the
  **complete** exit-code constants + exception→exit mapping (0, 2, 3, 4, 5, 6, 7, 8).

Exit codes (cli.md):

===  ==========================================================================
0    success
2    invalid arguments / invalid page selection / invalid ``review resolve`` input
3    source PDF unreadable — missing, encrypted, corrupted
4    local LLM required but unavailable / failing every attempt
5    output-name collision with different content (FR-054)
6    human review required — run incomplete (unresolved / resolved_unauthorized /
     delivery_blocked_verification_failed)
7    resource exhaustion / interrupted — no partial artifact left as complete
8    configured OCR engine unavailable/unusable
===  ==========================================================================
"""

from __future__ import annotations

# --- OCR exception types (frozen — defined in T008, hierarchy unchanged) -------------


class OcrError(Exception):
    """Base class for OCR-engine failures."""


class OcrUnavailable(OcrError):
    """A configured OCR engine cannot be used — missing binary, language data, or model
    files. Mapped to process exit code 8 by T016 / the CLI (T081)."""


# --- the remaining exception hierarchy (T016) ---------------------------------------


class SolariError(Exception):
    """Base class for the recoverable, exit-code-mapped Solari errors added in T016."""


class InvalidSelection(SolariError):
    """Invalid CLI arguments — a bad ``--pages`` selection (out of range, reversed,
    non-numeric, overlapping — FR-004), an out-of-bounds numeric option, or invalid
    ``review resolve`` input. Exit code 2; the run produces no output."""


class SourceUnreadable(SolariError):
    """The source PDF is missing, encrypted, or corrupted (FR-004 edge / FR-058).
    Exit code 3."""


class LLMUnavailable(SolariError):
    """A required local LLM endpoint could not be reached, or failed every attempt after
    bounded retry (``validate`` / ``fix`` / the ``convert`` validate step). Exit code 4."""


class OutputCollision(SolariError):
    """An output name already exists with **different** content (FR-054 / SC-016). The
    existing file is preserved; the run does not overwrite it. Exit code 5."""


class HumanReviewRequired(SolariError):
    """The run cannot be delivered: an open HUMAN_REVIEW_REQUIRED item, a
    resolved-but-unauthorized run, or a delivery blocked by a verification failure
    (FR-072 / FR-077 / FR-084). Carries the derived ``run_state``. Exit code 6."""

    def __init__(self, message: str = "", *, run_state: str | None = None) -> None:
        super().__init__(message or (run_state or "human review required"))
        self.run_state = run_state


class ResourceExhausted(SolariError):
    """The process ran out of a bounded resource, or was interrupted, before completing
    — no partial artifact is left in a state that looks complete (FR-058 / SC-016).
    Exit code 7."""


# --- exit codes --------------------------------------------------------------------


EXIT_OK = 0
EXIT_INVALID_ARGS = 2
EXIT_SOURCE_UNREADABLE = 3
EXIT_LLM_UNAVAILABLE = 4
EXIT_OUTPUT_COLLISION = 5
EXIT_HUMAN_REVIEW_REQUIRED = 6
EXIT_RESOURCE_EXHAUSTED = 7
EXIT_OCR_UNAVAILABLE = 8

# Most-specific first (``OcrUnavailable`` before ``OcrError``).
_EXIT_BY_TYPE: tuple[tuple[type[BaseException], int], ...] = (
    (InvalidSelection, EXIT_INVALID_ARGS),
    (SourceUnreadable, EXIT_SOURCE_UNREADABLE),
    (LLMUnavailable, EXIT_LLM_UNAVAILABLE),
    (OutputCollision, EXIT_OUTPUT_COLLISION),
    (HumanReviewRequired, EXIT_HUMAN_REVIEW_REQUIRED),
    (ResourceExhausted, EXIT_RESOURCE_EXHAUSTED),
    (OcrUnavailable, EXIT_OCR_UNAVAILABLE),
    (OcrError, EXIT_OCR_UNAVAILABLE),
)


def exit_code_for(exc: BaseException) -> int:
    """Map an exception instance to its process exit code. An unmapped error → 1
    (unexpected failure), which the CLI (T081) reports distinctly from the mapped codes."""
    for exc_type, code in _EXIT_BY_TYPE:
        if isinstance(exc, exc_type):
            return code
    return 1
