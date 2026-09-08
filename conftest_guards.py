"""Shared test guards — one implementation for both ``tests/`` and ``benchmarks/``.

The repo-root ``conftest.py`` turns these into autouse fixtures so the same
no-egress / no-model-download protection applies to every test tree (M5). Kept as
plain functions (no pytest import) so a guard test can also call / inspect them.
"""

from __future__ import annotations

import importlib
import importlib.util

LOOPBACK_HOSTS = {"127.0.0.1", "::1", "localhost", "0.0.0.0", "::"}

# Model-fetch entry points that DO reach the network. rapidocr-onnxruntime 1.4.x
# ships its PP-OCR ONNX models in the wheel and has no download entry point, so
# the no-egress guard is the real enforcement for it; the setup-time
# ``benchmarks/ocr/models/fetch_latin_model.py`` is deliberately never imported by
# tests. Each target is patched only when its base package is importable
# (``docling`` / ``huggingface_hub`` are installed from T046, not T002).
MODEL_FETCH_TARGETS: tuple[tuple[str, str], ...] = (
    ("huggingface_hub", "snapshot_download"),
    ("huggingface_hub", "hf_hub_download"),
    ("docling.utils.model_downloader", "download_models"),
    ("rapidocr_onnxruntime.utils", "download_file"),  # absent in 1.4.x; harmless if so
)


def is_loopback(address: object) -> bool:
    # AF_UNIX / socketpair — address is a str path or bytes; always local.
    if isinstance(address, (str, bytes)):
        return True
    if isinstance(address, tuple) and address:
        host = address[0]
        if isinstance(host, bytes):
            host = host.decode("ascii", "ignore")
        return host in LOOPBACK_HOSTS or str(host).startswith("127.")
    return False


def install_socket_guard(monkeypatch) -> None:
    """Block every non-loopback ``socket.connect`` / ``connect_ex`` for the test."""
    import socket

    real_connect = socket.socket.connect
    real_connect_ex = socket.socket.connect_ex

    def guard_connect(self, address, *a, **kw):  # noqa: ANN001
        if not is_loopback(address):
            raise RuntimeError(
                f"blocked non-loopback socket.connect to {address!r} during a test "
                "(local-first / no-egress guard)"
            )
        return real_connect(self, address, *a, **kw)

    def guard_connect_ex(self, address, *a, **kw):  # noqa: ANN001
        if not is_loopback(address):
            raise RuntimeError(
                f"blocked non-loopback socket.connect_ex to {address!r} during a test"
            )
        return real_connect_ex(self, address, *a, **kw)

    monkeypatch.setattr(socket.socket, "connect", guard_connect)
    monkeypatch.setattr(socket.socket, "connect_ex", guard_connect_ex)


def install_model_download_guard(monkeypatch) -> list[tuple[str, str]]:
    """Patch every importable model-fetch entry point to raise. Returns the list
    of ``(module, attr)`` targets that were actually patched (for guard tests)."""

    def boom(*_a, **_kw):  # noqa: ANN002, ANN003
        raise RuntimeError("model download attempted during a test (models must be pre-fetched)")

    patched: list[tuple[str, str]] = []
    for mod_name, attr in MODEL_FETCH_TARGETS:
        if importlib.util.find_spec(mod_name.split(".", 1)[0]) is None:
            continue
        try:
            mod = importlib.import_module(mod_name)
        except Exception:
            continue
        if hasattr(mod, attr):
            monkeypatch.setattr(mod, attr, boom, raising=False)
            patched.append((mod_name, attr))
    return patched
