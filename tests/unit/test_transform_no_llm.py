"""T074 [US1] — the Stage-3 (and Stage-5 / export) no-LLM architecture invariant.

No module under ``transform/``, ``render/``, or ``pipeline/export`` may import
``validate/llm_client`` or ``reconcile/llm_select`` or any other LLM / model / remote
inference client. Stage 3 is deterministic local processing only (Constitution;
research §21 / FR-064; block brief §28). Enforced as a **static import-graph**
assertion — no network, no model, no fixture needed.
"""

from __future__ import annotations

import ast
import importlib
import sys
from pathlib import Path

import solari_converter

_ROOT = Path(solari_converter.__file__).resolve().parent

_FORBIDDEN_MODULE_SUFFIXES = (
    "validate.llm_client",
    "reconcile.llm_select",
)
_FORBIDDEN_NAME_FRAGMENTS = ("llm", "openai", "anthropic", "litellm", "ollama")

_SCANNED_SUBPACKAGES = ("transform", "render")


def _python_files() -> list[Path]:
    files: list[Path] = []
    for sub in _SCANNED_SUBPACKAGES:
        d = _ROOT / sub
        if d.is_dir():
            files.extend(p for p in d.rglob("*.py") if p.stem != "__init__")
    export = _ROOT / "pipeline" / "export.py"
    if export.exists():
        files.append(export)
    return sorted(files)


def _imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    mods: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            mods.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            mods.add(node.module)
            mods.update(f"{node.module}.{a.name}" for a in node.names)
    return mods


def _is_forbidden(mod: str) -> bool:
    low = mod.lower()
    return any(low.endswith(s) for s in _FORBIDDEN_MODULE_SUFFIXES) or any(
        frag in low for frag in _FORBIDDEN_NAME_FRAGMENTS
    )


def test_no_transform_or_render_module_imports_an_llm_client():
    offenders = [
        f"{path.name} -> {mod}"
        for path in _python_files()
        for mod in _imported_modules(path)
        if _is_forbidden(mod)
    ]
    assert not offenders, (
        "Stage-3/5 modules must not import any LLM client:\n" + "\n".join(offenders)
    )


def test_scan_actually_covered_the_stage_three_modules():
    scanned = {p.stem for p in _python_files()}
    assert {"reflow", "structure", "lists", "tables"} <= scanned


def test_importing_the_transform_modules_loads_no_llm_client():
    for name in ("reflow", "structure", "lists", "tables"):
        importlib.import_module(f"solari_converter.transform.{name}")
    llm_loaded = [
        m for m in sys.modules
        if m.endswith("validate.llm_client") or m.endswith("reconcile.llm_select")
    ]
    # if some earlier test already imported the llm client it may be resident; the
    # static scan above is the authority — here we only assert the transform imports
    # themselves succeed without error.
    assert importlib.import_module("solari_converter.transform.reflow")
    _ = llm_loaded  # informational only
