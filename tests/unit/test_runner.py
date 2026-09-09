"""T051 — failing-first tests for the extraction runner/orchestration
(GREEN owner: **T051**, ``src/solari_converter/extract/runner.py``).

Frozen behaviour under test (FR-060; M1):

* every enabled path runs **concurrently** (a real process pool by default — each
  worker opens its **own** ``pdf/loader`` handle on the source path; a ``PdfSource``
  wraps unpicklable file handles and is never shared across the process boundary,
  which is exactly what makes independent, isolated reads the natural implementation
  here, not merely a performance choice);
* the runner collects a ``list[ExtractionCandidate]`` — independent evidence, never a
  reconciled Canonical Extracted Document;
* no path receives another path's result — a fault in one path (an exception inside
  ``extract()``, or a whole worker process failing) never alters another path's
  candidate, and never silently claims full-document success;
* each candidate is persisted via ``artifacts_io`` to ``intermediates/`` as **JSON
  only** (M1 — no ``.md`` companion for a candidate).

Most tests inject lightweight, fast fake ``ExtractionPath`` implementations (module-
level, so they survive being pickled to a subprocess under a real
``ProcessPoolExecutor``) rather than exercising the real, heavy Docling/OCR paths on
every test.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

MODULE_PATH = (
    Path(__file__).resolve().parents[2] / "src" / "solari_converter" / "extract" / "runner.py"
)


def _mod():
    import solari_converter.extract.runner as runner  # GREEN owner: T051

    return runner


def _envelope(**overrides) -> dict:
    base = {
        "run_id": "a" * 16,
        "tool_version": "0.1.0",
        "source_pdf": "doc.pdf",
        "source_sha256": "b" * 64,
        "page_selection": "all",
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------------------
# Module-level fake extraction paths -- must be importable by name for a real
# ProcessPoolExecutor (spawn) worker to reconstruct them.
# ---------------------------------------------------------------------------------------


class _FakeOkPath:
    """A fake path whose reported `technique` must still satisfy the frozen
    `ExtractionCandidate.technique` pattern (`docling|pdfplumber|ocr:<engine>`) --
    only the *registry key* used for routing/lookup is free-form."""

    technique = "pdfplumber"

    def extract(self, source, *, envelope):
        from solari_converter.model.candidate import CandidateReadingOrder, ExtractionCandidate

        env = {
            k: envelope[k]
            for k in ("run_id", "tool_version", "source_pdf", "source_sha256", "page_selection")
        }
        return ExtractionCandidate(
            **env,
            technique=self.technique,
            status="ok",
            segments=[],
            reading_order=CandidateReadingOrder(technique=self.technique, order=[]),
            pages_covered=[source.page_count],
        )


class _FakeOkPathDocling(_FakeOkPath):
    """A second, distinct fake for the "two concurrent paths" test -- a different
    valid technique family so the two candidates don't collide on their persisted
    filename (each technique family maps to its own `.candidate.<family>.json`)."""

    technique = "docling"


class _FakeRaisingPath:
    technique = "ocr:fake_boom"

    def extract(self, source, *, envelope):
        raise RuntimeError("synthetic failure inside extract()")


def _factory_ok(_kwargs):
    return _FakeOkPath()


def _factory_ok_docling(_kwargs):
    return _FakeOkPathDocling()


def _factory_boom(_kwargs):
    return _FakeRaisingPath()


def _factory_ocr_tesseract_like(_kwargs):
    return _FakeOcrLikePath()


class _FakeOcrLikePath:
    technique = "ocr:tesseract"

    def extract(self, source, *, envelope):
        from solari_converter.model.candidate import CandidateReadingOrder, ExtractionCandidate

        env = {
            k: envelope[k]
            for k in ("run_id", "tool_version", "source_pdf", "source_sha256", "page_selection")
        }
        return ExtractionCandidate(
            **env,
            technique="ocr:tesseract",
            status="ok",
            segments=[],
            reading_order=CandidateReadingOrder(technique="ocr:tesseract", order=[]),
            pages_covered=[1],
        )


# ---------------------------------------------------------------------------------------
# Independence — no reconciliation, no semantic transform, no render module
# ---------------------------------------------------------------------------------------


def test_module_imports_no_reconciliation_transform_or_render() -> None:
    tree = ast.parse(MODULE_PATH.read_text())
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    forbidden = ("reconcile", "transform", "render")
    for name in imported:
        for bad in forbidden:
            assert bad not in name, f"runner.py must not import {name!r} ({bad!r})"


# ---------------------------------------------------------------------------------------
# Real fixture + real loader, fake fast paths run through a real process pool
# ---------------------------------------------------------------------------------------


@pytest.fixture
def native_text_pdf(tmp_path: Path) -> Path:
    import sys as _sys

    _sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from fixtures.build_fixtures import build_native_text

    return build_native_text(tmp_path)


def test_runner_collects_one_candidate_per_enabled_path(
    native_text_pdf: Path, tmp_path: Path
) -> None:
    m = _mod()
    candidates = m.run_extraction(
        native_text_pdf,
        envelope=_envelope(source_pdf=str(native_text_pdf)),
        enabled_paths=["fake_ok"],
        path_factories={"fake_ok": _factory_ok},
        output_dir=tmp_path / "out",
        stem="native_text",
        selection=None,
    )
    assert len(candidates) == 1
    assert candidates[0].technique == "pdfplumber"
    assert candidates[0].status == "ok"


def test_runner_runs_multiple_paths_concurrently_and_preserves_all_candidates(
    native_text_pdf: Path, tmp_path: Path
) -> None:
    m = _mod()
    candidates = m.run_extraction(
        native_text_pdf,
        envelope=_envelope(source_pdf=str(native_text_pdf)),
        enabled_paths=["fake_ok", "fake_ok2"],
        path_factories={"fake_ok": _factory_ok, "fake_ok2": _factory_ok_docling},
        output_dir=tmp_path / "out",
        stem="native_text",
        selection=None,
    )
    assert len(candidates) == 2
    assert {c.technique for c in candidates} == {"pdfplumber", "docling"}


def test_a_failing_path_yields_a_failed_candidate_not_a_crash(
    native_text_pdf: Path, tmp_path: Path
) -> None:
    m = _mod()
    candidates = m.run_extraction(
        native_text_pdf,
        envelope=_envelope(source_pdf=str(native_text_pdf)),
        enabled_paths=["fake_ok", "fake_boom"],
        path_factories={"fake_ok": _factory_ok, "fake_boom": _factory_boom},
        output_dir=tmp_path / "out",
        stem="native_text",
        selection=None,
    )
    by_technique = {c.technique: c for c in candidates}
    assert by_technique["pdfplumber"].status == "ok"
    assert by_technique["ocr:fake_boom"].status == "failed"
    assert "RuntimeError" in (by_technique["ocr:fake_boom"].status_detail or "")
    # the failing path never altered the other path's candidate
    assert by_technique["pdfplumber"].segments == []


def test_one_path_never_receives_another_paths_result(
    native_text_pdf: Path, tmp_path: Path
) -> None:
    """Each worker opens its own PdfSource; nothing about one path's output is
    reachable from another path's process."""
    m = _mod()
    candidates = m.run_extraction(
        native_text_pdf,
        envelope=_envelope(source_pdf=str(native_text_pdf)),
        enabled_paths=["fake_ok", "fake_ok2"],
        path_factories={"fake_ok": _factory_ok, "fake_ok2": _factory_ok_docling},
        output_dir=tmp_path / "out",
        stem="native_text",
        selection=None,
    )
    # both fake paths independently read the same source and report the same page
    # count -- neither one received a candidate object as input.
    assert {c.pages_covered[0] for c in candidates} == {1}


def test_runner_returns_a_list_of_candidates_never_a_ced(
    native_text_pdf: Path, tmp_path: Path
) -> None:
    m = _mod()
    candidates = m.run_extraction(
        native_text_pdf,
        envelope=_envelope(source_pdf=str(native_text_pdf)),
        enabled_paths=["fake_ok"],
        path_factories={"fake_ok": _factory_ok},
        output_dir=tmp_path / "out",
        stem="native_text",
        selection=None,
    )
    assert isinstance(candidates, list)
    from solari_converter.model.candidate import ExtractionCandidate

    assert all(isinstance(c, ExtractionCandidate) for c in candidates)


# ---------------------------------------------------------------------------------------
# Persistence — JSON only, to intermediates/ (M1)
# ---------------------------------------------------------------------------------------


def test_each_candidate_is_persisted_as_json_only_in_intermediates(
    native_text_pdf: Path, tmp_path: Path
) -> None:
    m = _mod()
    out_dir = tmp_path / "out"
    m.run_extraction(
        native_text_pdf,
        envelope=_envelope(source_pdf=str(native_text_pdf)),
        enabled_paths=["fake_ok"],
        path_factories={"fake_ok": _factory_ok},
        output_dir=out_dir,
        stem="native_text",
        selection=None,
    )
    intermediates = out_dir / "intermediates"
    files = sorted(p.name for p in intermediates.iterdir())
    assert files == ["native_text.candidate.pdfplumber.json"]
    payload = json.loads((intermediates / files[0]).read_text())
    assert payload["record_type"] == "extraction_candidate"
    assert payload["technique"] == "pdfplumber"


def test_candidate_filename_uses_selector_token_when_partial_selection(
    native_text_pdf: Path, tmp_path: Path
) -> None:
    from solari_converter.model.page_selection import PageSelection

    m = _mod()
    out_dir = tmp_path / "out"
    m.run_extraction(
        native_text_pdf,
        envelope=_envelope(source_pdf=str(native_text_pdf), page_selection="1"),
        enabled_paths=["fake_ok"],
        path_factories={"fake_ok": _factory_ok},
        output_dir=out_dir,
        stem="native_text",
        selection=PageSelection.parse("1"),
    )
    intermediates = out_dir / "intermediates"
    files = sorted(p.name for p in intermediates.iterdir())
    assert files == ["native_text__p1.candidate.pdfplumber.json"]


def test_ocr_technique_filename_drops_the_engine_suffix(
    native_text_pdf: Path, tmp_path: Path
) -> None:
    """`ocr:tesseract` -> `.candidate.ocr.json`, per contracts/cli.md's generic
    `.candidate.ocr.json` naming (engine identity lives inside the JSON, not the
    filename)."""
    m = _mod()
    out_dir = tmp_path / "out"
    m.run_extraction(
        native_text_pdf,
        envelope=_envelope(source_pdf=str(native_text_pdf)),
        enabled_paths=["ocr"],
        path_factories={"ocr": _factory_ocr_tesseract_like},
        output_dir=out_dir,
        stem="native_text",
        selection=None,
    )
    files = sorted(p.name for p in (out_dir / "intermediates").iterdir())
    assert files == ["native_text.candidate.ocr.json"]


# ---------------------------------------------------------------------------------------
# Real end-to-end: the three actual frozen paths (T046/T047/T050), lightly
# ---------------------------------------------------------------------------------------


def test_real_paths_registry_has_exactly_docling_pdfplumber_ocr() -> None:
    m = _mod()
    assert set(m.DEFAULT_PATH_FACTORIES) == {"docling", "pdfplumber", "ocr"}
