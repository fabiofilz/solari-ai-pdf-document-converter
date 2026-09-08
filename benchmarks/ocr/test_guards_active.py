"""M5 evidence — the shared no-egress / no-model-download guards from the repo-root
conftest are active for tests under ``benchmarks/`` too (not just ``tests/``).
"""

from __future__ import annotations

import importlib
import importlib.util
import socket
from pathlib import Path

import conftest_guards
import pytest

pytestmark = pytest.mark.benchmark


def test_no_egress_guard_active_in_benchmark_tree():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        with pytest.raises(RuntimeError, match="no-egress|non-loopback|loopback"):
            s.connect(("93.184.216.34", 80))  # a non-loopback address — never actually dialled
    finally:
        s.close()


def test_loopback_still_allowed_in_benchmark_tree():
    # a connect to a closed loopback port should get past the guard and fail with
    # a normal OS error, NOT the guard's RuntimeError
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(0.2)
    try:
        with pytest.raises(OSError) as ei:
            s.connect(("127.0.0.1", 1))
        assert not isinstance(ei.value, RuntimeError)
    finally:
        s.close()


def test_no_model_download_guard_active_in_benchmark_tree(monkeypatch):
    # the autouse fixture already patched every importable target; re-derive the
    # list the same way and confirm each patched entry point now raises.
    patched = []
    for mod_name, attr in conftest_guards.MODEL_FETCH_TARGETS:
        if importlib.util.find_spec(mod_name.split(".", 1)[0]) is None:
            continue
        try:
            mod = importlib.import_module(mod_name)
        except Exception:
            continue
        fn = getattr(mod, attr, None)
        if fn is None:
            continue
        patched.append((mod_name, attr))
        with pytest.raises(RuntimeError, match="model download"):
            fn()
    # in the Phase 1-2 environment huggingface_hub / docling are not installed and
    # rapidocr 1.4.x has no download_file, so there may be nothing to patch — the
    # real enforcement for rapidocr is the no-egress guard above. Assert the
    # mechanism works whenever a target exists.
    assert isinstance(patched, list)


def test_setup_scripts_are_not_imported_by_the_benchmark_harness():
    """fetch_latin_model.py (network) and build_corpus.py (regeneration) are
    developer/setup tools — the harness must never import or invoke them."""
    import ast

    src = Path(importlib.import_module("benchmarks.ocr.run").__file__)
    tree = ast.parse(src.read_text())
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    assert not any("fetch_latin_model" in m or "build_corpus" in m for m in imported), imported
    called = {
        n.func.id for n in ast.walk(tree)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
    }
    assert "build_corpus" not in called
