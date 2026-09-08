"""Repo-root conftest — applies the shared test guards to **every** test tree.

`pyproject.toml` sets ``testpaths = ["tests", "benchmarks"]``; putting the
autouse guards here (rather than only in ``tests/conftest.py``) means the
no-egress / no-model-download protection also covers ``benchmarks/`` (M5). Tree-
specific helpers (`fake_llm_server`, `tmp_output_dir`, `run_twice`, …) stay in
``tests/conftest.py``.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:  # let `import conftest_guards` work from any test tree
    sys.path.insert(0, str(_ROOT))
_SRC = _ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from conftest_guards import install_model_download_guard, install_socket_guard  # noqa: E402


@pytest.fixture(autouse=True)
def _no_external_sockets(monkeypatch: pytest.MonkeyPatch) -> None:
    install_socket_guard(monkeypatch)


@pytest.fixture(autouse=True)
def _no_model_download(monkeypatch: pytest.MonkeyPatch) -> None:
    install_model_download_guard(monkeypatch)
