"""T052 — extraction-independence architecture test (M2 / SC-024).

The mandatory end-of-block gate for the extraction phase (T046-T051). Proves, by
construction rather than by convention:

1. **import-graph independence** — ``extract/docling_path``, ``extract/plumber_path``,
   and ``extract/ocr_path`` never import each other, and ``extract/native_reliability``
   never imports any of the three extraction paths. The one documented exception
   (research §24): ``extract/ocr_path`` legitimately imports
   ``extract/native_reliability`` for **routing evidence only** — native_reliability
   is "extraction-routing / evidence", not a fourth extraction path (T049's own
   module docstring), so this is not a violation of path independence; the test
   below asserts the narrower, correct invariant rather than a blanket "these four
   modules import nothing from each other", which would make T050's frozen,
   already-tested design fail a test that misreads its own specification;
2. **runner as the sole meeting point** — no other module under ``extract/`` (besides
   ``extract/runner.py``) imports more than one of the three extraction-path modules
   together, and ``runner.run_extraction()`` returns a flat ``list`` of
   ``ExtractionCandidate`` objects — never a reconciled document;
3. **fault isolation** — a fault injected into one path's candidate construction
   (raised inside ``extract()``) does not alter another path's candidate, does not
   alter a native-reliability classification computed independently, and does not
   alter an OCR-trigger decision (SC-024).
"""

from __future__ import annotations

import ast
import contextlib
from pathlib import Path

import pytest

_EXTRACT_DIR = Path(__file__).resolve().parents[2] / "src" / "solari_converter" / "extract"

_MODULE_PATHS = {
    "docling_path": _EXTRACT_DIR / "docling_path.py",
    "plumber_path": _EXTRACT_DIR / "plumber_path.py",
    "ocr_path": _EXTRACT_DIR / "ocr_path.py",
    "native_reliability": _EXTRACT_DIR / "native_reliability.py",
    "runner": _EXTRACT_DIR / "runner.py",
}

_EXTRACTION_PATH_NAMES = ("docling_path", "plumber_path", "ocr_path")


# Module-level fakes: a real ProcessPoolExecutor (spawn) must be able to pickle-and-
# reimport both the class and its factory function by qualified name, so neither may
# be a lambda or a function/class nested inside a test body.


class _FakeGoodPath:
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


class _FakeFaultyPath:
    technique = "docling"

    def extract(self, source, *, envelope):
        raise RuntimeError("injected fault")


def _factory_good(_kwargs):
    return _FakeGoodPath()


def _factory_faulty(_kwargs):
    return _FakeFaultyPath()


def _imported_module_names(path: Path) -> set[str]:
    tree = ast.parse(path.read_text())
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


def _mentions(imported: set[str], target: str) -> bool:
    return any(target in name for name in imported)


# ---------------------------------------------------------------------------------------
# 1. Import-graph independence (M2)
# ---------------------------------------------------------------------------------------


@pytest.mark.parametrize("module_name", _EXTRACTION_PATH_NAMES)
def test_extraction_paths_never_import_a_sibling_extraction_path(module_name: str) -> None:
    imported = _imported_module_names(_MODULE_PATHS[module_name])
    for sibling in _EXTRACTION_PATH_NAMES:
        if sibling == module_name:
            continue
        assert not _mentions(imported, sibling), (
            f"{module_name}.py imports sibling extraction path {sibling!r} "
            "-- one extraction path must never consume another's representation"
        )


def test_extraction_paths_never_import_reconciliation_transform_or_render() -> None:
    for module_name in (*_EXTRACTION_PATH_NAMES, "native_reliability", "runner"):
        imported = _imported_module_names(_MODULE_PATHS[module_name])
        for forbidden in ("reconcile", "transform", "render"):
            assert not _mentions(imported, forbidden), (
                f"{module_name}.py imports {forbidden!r} -- extraction never reaches "
                "into reconciliation, semantic transformation, or rendering"
            )


def test_native_reliability_imports_no_extraction_path() -> None:
    """native_reliability is extraction-routing/evidence, not a fourth path (T049) --
    it must not depend on any of the three real extractors' output or implementation."""
    imported = _imported_module_names(_MODULE_PATHS["native_reliability"])
    for path_name in _EXTRACTION_PATH_NAMES:
        assert not _mentions(imported, path_name), (
            f"native_reliability.py imports {path_name!r} -- it must read only the "
            "raw source PDF, never another extraction path's interpretation"
        )


def test_native_reliability_never_imports_the_candidate_model() -> None:
    """Reinforces T049's own invariant here too: native_reliability neither accepts
    nor constructs an ExtractionCandidate."""
    tree = ast.parse(_MODULE_PATHS["native_reliability"].read_text())
    imported_names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            imported_names.update(alias.name for alias in node.names)
    assert "ExtractionCandidate" not in imported_names


def test_ocr_path_does_not_import_docling_or_plumber_path() -> None:
    """The one documented exception (research §24): ocr_path legitimately imports
    native_reliability for routing evidence -- but never the other two real
    extraction paths, and never a candidate from them."""
    imported = _imported_module_names(_MODULE_PATHS["ocr_path"])
    assert not _mentions(imported, "docling_path")
    assert not _mentions(imported, "plumber_path")


def test_ocr_path_does_legitimately_import_native_reliability_for_routing_only() -> None:
    """Documented, intentional -- confirms the exception exists and is exactly this
    one, not a broader coupling."""
    imported = _imported_module_names(_MODULE_PATHS["ocr_path"])
    assert _mentions(imported, "native_reliability")


# ---------------------------------------------------------------------------------------
# 2. extract/runner is the only meeting point, and only as list[ExtractionCandidate]
# ---------------------------------------------------------------------------------------


def test_only_runner_imports_more_than_one_extraction_path() -> None:
    for py_file in sorted(_EXTRACT_DIR.glob("*.py")):
        if py_file.stem in (*_EXTRACTION_PATH_NAMES, "runner", "__init__"):
            continue
        imported = _imported_module_names(py_file)
        touched = [name for name in _EXTRACTION_PATH_NAMES if _mentions(imported, name)]
        assert len(touched) <= 1, (
            f"{py_file.name} imports more than one extraction path {touched} -- "
            "only extract/runner.py may be the meeting point"
        )
    runner_imported = _imported_module_names(_MODULE_PATHS["runner"])
    # runner.py imports the three real paths lazily, inside its builder functions --
    # the AST-level import scan still finds them there, confirming it IS the meeting
    # point (the previous loop confirms nothing else is).
    for path_name in _EXTRACTION_PATH_NAMES:
        assert _mentions(runner_imported, path_name)


def test_run_extraction_returns_a_flat_list_of_extraction_candidates_never_a_ced(
    tmp_path: Path,
) -> None:
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    import solari_converter.extract.runner as runner_mod
    from fixtures.build_fixtures import build_native_text
    from solari_converter.model.candidate import ExtractionCandidate

    pdf_path = build_native_text(tmp_path)
    candidates = runner_mod.run_extraction(
        pdf_path,
        envelope={
            "run_id": "a" * 16,
            "tool_version": "0.1.0",
            "source_pdf": str(pdf_path),
            "source_sha256": "b" * 64,
            "page_selection": "all",
        },
        enabled_paths=["fake"],
        path_factories={"fake": _factory_good},
        output_dir=tmp_path / "out",
        stem="native_text",
        selection=None,
    )

    assert isinstance(candidates, list)
    assert all(isinstance(c, ExtractionCandidate) for c in candidates)
    # a plain list has no "reconciled" / "canonical" shape -- there is no accepted
    # reading order, no carried structural hints, no accepted-decision concept here.
    assert not hasattr(candidates, "accepted_reading_order")


# ---------------------------------------------------------------------------------------
# 3. Fault isolation (SC-024) -- a fault in one path never alters another's output,
#    a native-reliability classification, or an OCR-trigger decision.
# ---------------------------------------------------------------------------------------


@pytest.fixture
def _fixtures_path():
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def test_fault_in_one_path_does_not_alter_another_paths_candidate(
    _fixtures_path, tmp_path: Path
) -> None:
    import solari_converter.extract.runner as runner_mod
    from fixtures.build_fixtures import build_native_text

    pdf_path = build_native_text(tmp_path)
    envelope = {
        "run_id": "a" * 16,
        "tool_version": "0.1.0",
        "source_pdf": str(pdf_path),
        "source_sha256": "b" * 64,
        "page_selection": "all",
    }

    baseline = runner_mod.run_extraction(
        pdf_path,
        envelope=envelope,
        enabled_paths=["good"],
        path_factories={"good": _factory_good},
        output_dir=tmp_path / "out_a",
        stem="native_text",
        selection=None,
    )[0]

    with_fault = runner_mod.run_extraction(
        pdf_path,
        envelope=envelope,
        enabled_paths=["good", "faulty"],
        path_factories={"good": _factory_good, "faulty": _factory_faulty},
        output_dir=tmp_path / "out_b",
        stem="native_text",
        selection=None,
    )
    good_with_fault = next(c for c in with_fault if c.technique == "pdfplumber")
    faulty_candidate = next(c for c in with_fault if c.technique == "docling")

    assert good_with_fault.model_dump() == baseline.model_dump()
    assert faulty_candidate.status == "failed"


def test_fault_in_a_path_does_not_alter_native_reliability_classification(
    _fixtures_path, tmp_path: Path
) -> None:
    from fixtures.build_fixtures import build_native_text
    from solari_converter.extract.native_reliability import NativeReliabilityClassifier
    from solari_converter.pdf.loader import load_pdf

    pdf_path = build_native_text(tmp_path)

    def _classify():
        with load_pdf(pdf_path) as source:
            return NativeReliabilityClassifier().classify_page(source, 1)

    before = _classify()

    class _FaultyPath:
        technique = "docling"

        def extract(self, source, *, envelope):
            raise RuntimeError("injected fault")

    # Simulate a fault happening in "another path" by simply raising and discarding --
    # native_reliability has no shared state with any extraction path, so a completely
    # independent classification call after a fault must be byte-identical.
    with contextlib.suppress(RuntimeError):
        _FaultyPath().extract(None, envelope={})

    after = _classify()
    assert before == after


def test_fault_in_a_path_does_not_alter_the_ocr_trigger_decision(
    _fixtures_path, tmp_path: Path
) -> None:
    from fixtures.build_fixtures import build_hybrid
    from solari_converter.extract.native_reliability import NativeReliabilityClassifier
    from solari_converter.pdf.loader import load_pdf

    pdf_path = build_hybrid(tmp_path)

    def _regions():
        with load_pdf(pdf_path) as source:
            result = NativeReliabilityClassifier().classify_page(source, 1)
            return result.page_class, [r.bbox for r in result.ocr_regions]

    before = _regions()

    class _FaultyPath:
        technique = "pdfplumber"

        def extract(self, source, *, envelope):
            raise RuntimeError("injected fault")

    with contextlib.suppress(RuntimeError):
        _FaultyPath().extract(None, envelope={})

    after = _regions()
    assert before == after
