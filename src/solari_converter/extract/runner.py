"""Extraction runner/orchestration (T051).

Runs every enabled extraction path **concurrently**, via a real
``concurrent.futures.ProcessPoolExecutor`` by default, and collects the resulting
``list[ExtractionCandidate]`` — independent evidence only, **never** a reconciled
Canonical Extracted Document (that is reconciliation's job, out of this module's
scope entirely; this module imports nothing under ``reconcile/``, ``transform/``, or
``render/``).

**Why a process pool is the natural fit here, not just a performance choice**: a
``pdf/loader.PdfSource`` wraps ``pdfplumber`` and ``pypdfium2`` handles — C-extension
file objects that cannot be pickled and shared across a process boundary. Each worker
therefore opens its **own** ``PdfSource`` on the same source path (:func:`_run_one`),
independently — which is exactly FR-060's independence requirement ("each path reads
the original PDF directly"), enforced by the process boundary itself rather than by
convention alone. No path ever receives another path's result: a worker only ever
sees the source path and the shared envelope, never another path's candidate.

**Failure isolation** (FR-060 edge case): a failure *inside* one path's ``extract()``
is already converted to a ``status="failed"`` candidate by ``extract/base.py``'s
``run_path()``, called from inside the worker. A more catastrophic failure — the
worker process itself dying — is caught here, in the parent, and converted to the
same well-formed ``status="failed"`` shape via ``extract/base.py``'s
``failed_candidate()``. Either way, one path's failure never alters another path's
candidate, and the run never silently claims complete success.

**Persistence** (M1): each candidate is written via ``artifacts_io.write_record``
to ``intermediates/<base>.candidate.<technique>.json`` — JSON only, no ``.md``
companion (extraction candidates are not a human-review-facing record). The filename
suffix is the *technique family* (``docling`` / ``pdfplumber`` / ``ocr``), not the
specific OCR engine, matching ``contracts/cli.md``'s generic ``.candidate.ocr.json``
naming — engine identity is inside the JSON (``SourceRef.extraction_technique``),
not the filename.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import Executor, ProcessPoolExecutor
from pathlib import Path
from typing import Any

from solari_converter import artifacts_io
from solari_converter.extract.base import EnvelopeFields, ExtractionPath, failed_candidate
from solari_converter.model.candidate import ExtractionCandidate
from solari_converter.model.page_selection import PageSelection
from solari_converter.naming import base_name

__all__ = ["DEFAULT_PATH_FACTORIES", "run_extraction"]


def _build_docling_path(kwargs: dict[str, Any]) -> ExtractionPath:
    from solari_converter.extract.docling_path import DoclingExtractionPath

    return DoclingExtractionPath(**kwargs)


def _build_plumber_path(kwargs: dict[str, Any]) -> ExtractionPath:
    from solari_converter.extract.plumber_path import PlumberExtractionPath

    return PlumberExtractionPath(**kwargs)


def _build_ocr_path(kwargs: dict[str, Any]) -> ExtractionPath:
    from solari_converter.extract.ocr_path import OcrExtractionPath

    return OcrExtractionPath(**kwargs)


#: The three frozen extraction paths (T046/T047/T050). Module-level (picklable by
#: reference) so a real process-pool worker can look one up by name.
DEFAULT_PATH_FACTORIES: dict[str, Callable[[dict[str, Any]], ExtractionPath]] = {
    "docling": _build_docling_path,
    "pdfplumber": _build_plumber_path,
    "ocr": _build_ocr_path,
}


def _run_one(
    technique: str,
    factory: Callable[[dict[str, Any]], ExtractionPath],
    source_path: str,
    envelope: dict[str, Any],
    kwargs: dict[str, Any],
) -> ExtractionCandidate:
    """The process-pool worker body. Opens its **own** ``PdfSource`` on
    ``source_path`` — never a handle shared from the parent process (it couldn't be;
    ``PdfSource`` is not picklable). Runs through ``extract/base.py``'s ``run_path()``
    so an exception inside ``extract()`` is already a well-formed failed candidate by
    the time it leaves this function."""
    from solari_converter.extract.base import run_path
    from solari_converter.pdf.loader import load_pdf

    path = factory(kwargs)
    with load_pdf(source_path) as source:
        return run_path(path, source, envelope=envelope)


def _safe_failure_technique(registry_key: str) -> str:
    """A registry key (``enabled_paths`` entry) is a routing key, not necessarily a
    valid ``ExtractionCandidate.technique`` value on its own — the OCR family's own
    registry key is the generic ``"ocr"``, which does not by itself match the frozen
    ``docling|pdfplumber|ocr:<engine>`` pattern. This only matters for the rare
    catastrophic-crash path (the worker process itself dying, not an ordinary
    exception inside ``extract()`` — that case is already handled, with the real
    ``path.technique``, by ``run_path()`` *inside* the worker): the parent has no
    engine identity to report in that case, so it falls back to ``"ocr:unknown"``."""
    if registry_key == "ocr":
        return "ocr:unknown"
    return registry_key


def _technique_family(technique: str) -> str:
    """The candidate-filename suffix — the technique family, not the specific OCR
    engine (``"ocr:tesseract"`` -> ``"ocr"``), per ``contracts/cli.md``."""
    return technique.split(":", 1)[0]


def run_extraction(
    source_path: str | Path,
    *,
    envelope: EnvelopeFields,
    enabled_paths: Sequence[str],
    output_dir: str | Path,
    stem: str,
    selection: PageSelection | None,
    path_factories: Mapping[str, Callable[[dict[str, Any]], ExtractionPath]] | None = None,
    path_kwargs: Mapping[str, dict[str, Any]] | None = None,
    max_workers: int | None = None,
    executor_factory: Callable[..., Executor] = ProcessPoolExecutor,
) -> list[ExtractionCandidate]:
    """Run every technique in ``enabled_paths`` concurrently and persist each
    resulting candidate. Returns the ``list[ExtractionCandidate]`` — independent
    evidence, never reconciled here.

    ``path_factories`` defaults to :data:`DEFAULT_PATH_FACTORIES` (the three frozen
    real paths); tests may override it with fast, module-level fakes. ``selection``
    may be ``None`` (treated as the whole document, for callers that only need the
    ``page_selection`` envelope string and not the filename selector token).
    """
    factories = dict(DEFAULT_PATH_FACTORIES)
    if path_factories:
        factories.update(path_factories)
    kwargs_by_technique = dict(path_kwargs or {})
    env = dict(envelope)
    source_path_str = str(source_path)

    candidates: list[ExtractionCandidate] = []
    with executor_factory(max_workers=max_workers or max(1, len(enabled_paths))) as executor:
        futures = {
            executor.submit(
                _run_one,
                technique,
                factories[technique],
                source_path_str,
                env,
                kwargs_by_technique.get(technique, {}),
            ): technique
            for technique in enabled_paths
        }
        for future, technique in futures.items():
            try:
                candidates.append(future.result())
            except Exception as exc:  # noqa: BLE001 - a worker crash must not abort the run
                candidates.append(
                    failed_candidate(
                        _safe_failure_technique(technique), env, f"{type(exc).__name__}: {exc}"
                    )
                )

    _persist(candidates, output_dir=output_dir, stem=stem, selection=selection)
    return candidates


def _persist(
    candidates: list[ExtractionCandidate],
    *,
    output_dir: str | Path,
    stem: str,
    selection: PageSelection | None,
) -> None:
    base = base_name(stem, selection or PageSelection.whole_document())
    intermediates = artifacts_io.intermediates_dir(output_dir)
    for candidate in candidates:
        suffix = _technique_family(candidate.technique)
        stem_path = intermediates / f"{base}.candidate.{suffix}"
        artifacts_io.write_record(stem_path, candidate, emit_md=False)
