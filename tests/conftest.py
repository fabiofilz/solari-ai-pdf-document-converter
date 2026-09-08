"""Shared test fixtures for the Local-First PDF Document Converter (T004).

The no-egress / no-model-download **guards** live in the repo-root ``conftest.py``
+ ``conftest_guards.py`` so they cover both ``tests/`` and ``benchmarks/`` (M5).
This file keeps the ``tests/``-specific helpers:
  * ``tmp_output_dir`` / ``tmp_resolution_store``;
  * ``fake_llm_server`` — an OpenAI-compatible local HTTP server with selectable
    failure modes and a seed-determinism probe (FR-053b);
  * ``run_twice`` — run a command twice and compare artifacts byte-for-byte.
"""

from __future__ import annotations

import json
import subprocess
import sys
import threading
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

# --------------------------------------------------------------------------------------
# Temp-path fixtures
# --------------------------------------------------------------------------------------


@pytest.fixture
def tmp_output_dir(tmp_path: Path) -> Path:
    d = tmp_path / "out"
    d.mkdir()
    return d


@pytest.fixture
def tmp_resolution_store(tmp_path: Path) -> Path:
    return tmp_path / "resolutions.jsonl"


# --------------------------------------------------------------------------------------
# fake_llm_server — OpenAI-compatible, selectable modes, seed-determinism probe
# --------------------------------------------------------------------------------------

_MODES = {
    "normal",
    "always_500",
    "slow_timeout",
    "unparseable",
    "returns_non_candidate",
    "flip",
}

# A fixed tiny prompt the client issues twice to probe seed determinism (FR-053b).
SEED_PROBE_MARKER = "SOLARI_SEED_DETERMINISM_PROBE"


@dataclass
class FakeLLM:
    base_url: str
    mode: str
    requests: list[dict] = field(default_factory=list)
    _server: ThreadingHTTPServer | None = None
    _thread: threading.Thread | None = None
    _flip_state: dict[str, int] = field(default_factory=dict)

    def stop(self) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
        if self._thread is not None:
            self._thread.join(timeout=5)


def _make_handler(state: FakeLLM):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *_a):  # silence
            return

        def _send(self, code: int, payload: dict | str) -> None:
            body = (payload if isinstance(payload, str) else json.dumps(payload)).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:  # noqa: N802
            if self.path.rstrip("/").endswith("/v1/models"):
                models = [{"id": "fake-local", "object": "model"}]
                self._send(200, {"object": "list", "data": models})
            else:
                self._send(404, {"error": "not found"})

        def do_POST(self) -> None:  # noqa: N802
            length = int(self.headers.get("Content-Length", 0))
            raw = self.rfile.read(length) if length else b"{}"
            try:
                req = json.loads(raw or b"{}")
            except json.JSONDecodeError:
                req = {"_unparsed": raw.decode("utf-8", "replace")}
            state.requests.append(req)

            mode = state.mode
            if mode == "always_500":
                self._send(500, {"error": "injected server error"})
                return
            if mode == "slow_timeout":
                import time

                time.sleep(30)  # force a client read timeout
                return
            if mode == "unparseable":
                self._send(200, "this is not json { ")
                return

            prompt_text = json.dumps(req.get("messages", req))
            is_probe = SEED_PROBE_MARKER in prompt_text

            if is_probe:
                if mode == "flip":
                    n = state._flip_state.get("probe", 0)
                    state._flip_state["probe"] = n + 1
                    content = f"probe-answer-{n}"  # differs across the two probe calls
                else:
                    content = "probe-answer-stable"  # identical every call
            elif mode == "returns_non_candidate":
                content = json.dumps({"selected": "A VALUE THAT IS NOT AMONG THE CANDIDATES"})
            elif mode == "flip":
                n = state._flip_state.get("select", 0)
                state._flip_state["select"] = n + 1
                content = json.dumps({"selected_index": n % 2})  # 0, then 1, ...
            else:  # normal
                content = json.dumps({"selected_index": 0})

            self._send(
                200,
                {
                    "id": "chatcmpl-fake",
                    "object": "chat.completion",
                    "model": req.get("model", "fake-local"),
                    "choices": [
                        {
                            "index": 0,
                            "message": {"role": "assistant", "content": content},
                            "finish_reason": "stop",
                        }
                    ],
                },
            )

    return Handler


@pytest.fixture
def fake_llm_server():
    """Factory: ``srv = fake_llm_server(mode="normal")``; auto-stopped at teardown."""
    started: list[FakeLLM] = []

    def _factory(mode: str = "normal") -> FakeLLM:
        if mode not in _MODES:
            raise ValueError(f"unknown fake_llm_server mode {mode!r}; expected one of {_MODES}")
        handle = FakeLLM(base_url="", mode=mode)
        srv = ThreadingHTTPServer(("127.0.0.1", 0), _make_handler(handle))
        srv.daemon_threads = True
        host, port = srv.server_address[:2]
        handle.base_url = f"http://{host}:{port}/v1"
        handle._server = srv
        t = threading.Thread(
            target=srv.serve_forever, kwargs={"poll_interval": 0.05},
            name=f"fake-llm-{mode}", daemon=True,
        )
        t.start()
        handle._thread = t
        started.append(handle)
        return handle

    yield _factory
    for s in started:
        s.stop()


# --------------------------------------------------------------------------------------
# run_twice — determinism helper
# --------------------------------------------------------------------------------------


@dataclass
class TwoRuns:
    dir_a: Path
    dir_b: Path
    result_a: subprocess.CompletedProcess
    result_b: subprocess.CompletedProcess

    def assert_byte_identical(self, *, only: set[str] | None = None) -> None:
        files_a = {p.relative_to(self.dir_a): p for p in self.dir_a.rglob("*") if p.is_file()}
        files_b = {p.relative_to(self.dir_b): p for p in self.dir_b.rglob("*") if p.is_file()}
        names_a = {str(k) for k in files_a}
        names_b = {str(k) for k in files_b}
        if only is not None:
            names_a &= only
            names_b &= only
        assert names_a == names_b, f"artifact set differs: {names_a ^ names_b}"
        for name in sorted(names_a):
            rel = Path(name)
            a, b = files_a[rel].read_bytes(), files_b[rel].read_bytes()
            assert a == b, f"{name} differs between the two runs ({len(a)} vs {len(b)} bytes)"


@pytest.fixture
def run_twice(tmp_path: Path):
    def _run(cmd: list[str], *, out_flag: str = "--output-dir") -> TwoRuns:
        da, db = tmp_path / "run_a", tmp_path / "run_b"
        da.mkdir()
        db.mkdir()
        ra = subprocess.run([*cmd, out_flag, str(da)], capture_output=True, text=True)  # noqa: S603
        rb = subprocess.run([*cmd, out_flag, str(db)], capture_output=True, text=True)  # noqa: S603
        return TwoRuns(da, db, ra, rb)

    return _run


# Keep the src layout importable even before an editable install is guaranteed.
_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))
