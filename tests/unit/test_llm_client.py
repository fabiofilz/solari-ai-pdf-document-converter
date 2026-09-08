"""T031 — failing-first tests for the local OpenAI-compatible LLM client (GREEN owner: **T032**).

Frozen behaviour (research §4a / §14, FR-053a / FR-053b, spec FR-037 / FR-061a):

* the client only talks to a **loopback / local** endpoint (local-first, no egress);
* ``probe()`` — an unreachable / failing endpoint maps to :class:`LLMUnavailable`
  (exit 4) via the frozen error architecture;
* mid-run HTTP 5xx / timeout / unparseable responses are retried a **bounded** number
  of times (``1 initial attempt + N retries``, default ``N = 2``) and then raise
  :class:`LLMUnavailable`;
* every applicable request carries ``temperature: 0`` **and** the configured fixed seed;
* the seed-determinism probe (FR-053b) issues the *same* tiny fixed request twice and
  classifies the backend ``deterministic`` (identical answers) or ``best_effort``
  (answers differ);
* the reproducibility classification is **not** an input to ``run_id`` (research §14);
* the client result / provenance captures ``{model, decode, attempts, reproducibility}``;
* the double-call flip helper reports a reconciliation-selection disagreement to the caller;
* free-form model output is **never** returned as authoritative literal source text —
  ``select`` resolves to a candidate index / value drawn from the supplied candidate list,
  never from the model's own string.
"""

from __future__ import annotations

import hashlib
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from solari_converter.config import Config
from solari_converter.errors import EXIT_LLM_UNAVAILABLE, LLMUnavailable, exit_code_for

# RFC 5737 / RFC 3849 documentation addresses — guaranteed never routable, used only to
# prove the client never *attempts* an off-machine destination.
_OFFBOX_IPV4 = "198.51.100.7"
_OFFBOX_IPV6 = "2001:db8::1"


def _client_mod():
    import solari_converter.validate.llm_client as llm_client  # GREEN owner: T032

    return llm_client


def _client(base_url: str, *, seed: int = 4242, retries: int = 2, timeout: float = 1.0):
    llm_client = _client_mod()
    cfg = Config.resolve(cli={"llm_base_url": base_url, "llm_seed": seed, "llm_retries": retries})
    return llm_client.LLMClient.from_config(cfg, timeout=timeout)


# --------------------------------------------------------------------------------------
# Network policy — loopback only
# --------------------------------------------------------------------------------------


def test_rejects_a_non_loopback_endpoint() -> None:
    llm_client = _client_mod()
    cfg = Config.resolve(cli={"llm_base_url": "http://example.com:8000/v1", "llm_seed": 1})
    with pytest.raises((ValueError, LLMUnavailable)):
        llm_client.LLMClient.from_config(cfg)


def test_accepts_loopback_endpoints(fake_llm_server) -> None:
    srv = fake_llm_server("normal")
    client = _client(srv.base_url)
    assert client is not None


# --------------------------------------------------------------------------------------
# Loopback endpoint enforcement — precise ipaddress-based policy (remediation)
# --------------------------------------------------------------------------------------


def _construct(base_url: str):
    return _client_mod().LLMClient(base_url=base_url, seed=1)


@pytest.mark.parametrize(
    "base_url",
    [
        "http://127.0.0.1:8000/v1",
        "http://127.1.2.3:8000/v1",          # anywhere in 127.0.0.0/8
        "http://127.255.255.254:8000/v1",
        "http://localhost:8000/v1",
        "http://localhost.:8000/v1",          # trailing root dot
        "http://[::1]:8000/v1",               # IPv6 loopback
    ],
)
def test_local_host_accepted(base_url: str) -> None:
    assert _construct(base_url) is not None


@pytest.mark.parametrize(
    "base_url",
    [
        f"http://{_OFFBOX_IPV4}:8000/v1",          # public IPv4 literal
        f"http://[{_OFFBOX_IPV6}]:8000/v1",        # non-loopback IPv6 literal
        "http://0.0.0.0:8000/v1",                  # IPv4 wildcard/unspecified — not loopback
        "http://[::]:8000/v1",                     # IPv6 wildcard/unspecified — not loopback
        "http://127.0.0.1.attacker.example/v1",    # DNS name that merely starts with 127.
        "http://127.evil.example/v1",
        "http://example.com:8000/v1",              # ordinary public hostname
        "http://llm.internal.corp:8000/v1",
    ],
)
def test_non_local_host_rejected(base_url: str) -> None:
    with pytest.raises(LLMUnavailable):
        _construct(base_url)


# --------------------------------------------------------------------------------------
# HTTP transport policy — env proxies ignored, redirects not followed (remediation)
# --------------------------------------------------------------------------------------


def test_environment_proxy_is_ignored(fake_llm_server, monkeypatch: pytest.MonkeyPatch) -> None:
    # If the client honoured the environment (trust_env=True), httpx would try to reach
    # this off-box proxy and the autouse socket guard would raise RuntimeError — not
    # LLMUnavailable — so a clean probe proves trust_env=False.
    for var in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
        monkeypatch.setenv(var, f"http://{_OFFBOX_IPV4}:3128")
    monkeypatch.delenv("NO_PROXY", raising=False)
    monkeypatch.delenv("no_proxy", raising=False)

    srv = fake_llm_server("normal")
    result = _client(srv.base_url).probe()
    assert result.reproducibility == "deterministic"
    assert srv.requests, "the request went directly to the loopback endpoint"


class _RedirectHandler(BaseHTTPRequestHandler):
    location = ""  # set per server

    def log_message(self, *_a):  # silence
        return

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length", 0))
        if length:
            self.rfile.read(length)
        type(self).hits += 1
        self.send_response(302)
        self.send_header("Location", type(self).location)
        self.send_header("Content-Length", "0")
        self.end_headers()

    do_GET = do_POST


def _redirecting_server(location: str):
    handler = type("H", (_RedirectHandler,), {"location": location, "hits": 0})
    srv = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True).start()
    host, port = srv.server_address[:2]
    return srv, handler, f"http://{host}:{port}/v1"


def test_redirect_is_not_followed(fake_llm_server) -> None:
    # The real backend records hits; the front server 302-redirects to it. A client that
    # followed redirects would land on `sink` and mint a request there.
    sink = fake_llm_server("normal")
    front_srv, front_handler, front_url = _redirecting_server(sink.base_url + "/chat/completions")
    try:
        client = _client(front_url, retries=1)
        with pytest.raises(LLMUnavailable):
            client.probe()
        assert front_handler.hits >= 1           # the front server was hit
        assert sink.requests == []               # the redirect target never was
    finally:
        front_srv.shutdown()
        front_srv.server_close()


def test_redirect_to_offbox_host_is_never_requested(fake_llm_server) -> None:
    # Location points off-box; following it would trip the socket guard (RuntimeError),
    # not LLMUnavailable. A clean LLMUnavailable proves the 302 was not chased.
    front_srv, _front_handler, front_url = _redirecting_server(
        f"http://{_OFFBOX_IPV4}:9/v1/chat/completions"
    )
    try:
        client = _client(front_url, retries=1)
        with pytest.raises(LLMUnavailable):
            client.probe()
    finally:
        front_srv.shutdown()
        front_srv.server_close()


# --------------------------------------------------------------------------------------
# probe() — reachability + seed determinism (FR-053b)
# --------------------------------------------------------------------------------------


def test_probe_unreachable_endpoint_maps_to_llm_unavailable() -> None:
    client = _client("http://127.0.0.1:1/v1", retries=1)
    with pytest.raises(LLMUnavailable) as exc:
        client.probe()
    assert exit_code_for(exc.value) == EXIT_LLM_UNAVAILABLE


def test_probe_server_error_maps_to_llm_unavailable(fake_llm_server) -> None:
    srv = fake_llm_server("always_500")
    client = _client(srv.base_url, retries=2)
    with pytest.raises(LLMUnavailable):
        client.probe()


def test_probe_normal_backend_is_deterministic(fake_llm_server) -> None:
    srv = fake_llm_server("normal")
    result = _client(srv.base_url).probe()
    assert result.reproducibility == "deterministic"


def test_probe_flip_backend_is_best_effort(fake_llm_server) -> None:
    srv = fake_llm_server("flip")
    result = _client(srv.base_url).probe()
    assert result.reproducibility == "best_effort"


def test_probe_issues_the_same_tiny_request_twice(fake_llm_server) -> None:
    srv = fake_llm_server("normal")
    _client(srv.base_url).probe()
    probe_reqs = [r for r in srv.requests if "SOLARI_SEED_DETERMINISM_PROBE" in str(r)]
    assert len(probe_reqs) == 2
    # byte-identical request payloads (the "same tiny deterministic request")
    assert probe_reqs[0] == probe_reqs[1]


def test_reproducibility_classification_does_not_alter_run_identity(fake_llm_server) -> None:
    from solari_converter.run_identity import compute_run_id

    det = _client(fake_llm_server("normal").base_url).probe()
    best = _client(fake_llm_server("flip").base_url).probe()
    assert det.reproducibility != best.reproducibility

    cfg = Config.resolve(cli={"llm_seed": 7})
    common = dict(
        source_sha256="a" * 64,
        normalized_page_selection="all",
        tool_version="0.1.0",
        output_affecting_config=cfg.output_affecting_config(stage="extract", llm_reachable=True),
        applicable_resolution_digest=hashlib.sha256(b"").hexdigest(),
    )
    # the extract-stage output-affecting subset never carries a reproducibility field
    assert "reproducibility" not in common["output_affecting_config"]
    assert compute_run_id(**common) == compute_run_id(**common)


# --------------------------------------------------------------------------------------
# decode parameters — temperature 0 + fixed seed on every request
# --------------------------------------------------------------------------------------


def test_every_request_carries_temperature_zero_and_the_configured_seed(fake_llm_server) -> None:
    srv = fake_llm_server("normal")
    client = _client(srv.base_url, seed=9182)
    client.probe()
    client.select("pick one", ["alpha", "beta"])
    assert srv.requests, "expected at least one request"
    for req in srv.requests:
        assert req.get("temperature") == 0
        assert req.get("seed") == 9182


# --------------------------------------------------------------------------------------
# bounded retry — mid-run failures ultimately raise LLMUnavailable
# --------------------------------------------------------------------------------------


def test_server_error_retries_are_bounded_then_llm_unavailable(fake_llm_server) -> None:
    srv = fake_llm_server("always_500")
    client = _client(srv.base_url, retries=2)
    with pytest.raises(LLMUnavailable):
        client.select("pick one", ["alpha", "beta"])
    assert len(srv.requests) == 3  # 1 initial + 2 retries


def test_timeout_retries_are_bounded_then_llm_unavailable(fake_llm_server) -> None:
    srv = fake_llm_server("slow_timeout")
    client = _client(srv.base_url, retries=1, timeout=0.4)
    with pytest.raises(LLMUnavailable):
        client.select("pick one", ["alpha", "beta"])
    assert len(srv.requests) == 2  # 1 initial + 1 retry


def test_unparseable_response_ultimately_maps_to_llm_unavailable(fake_llm_server) -> None:
    srv = fake_llm_server("unparseable")
    client = _client(srv.base_url, retries=2)
    with pytest.raises(LLMUnavailable):
        client.select("pick one", ["alpha", "beta"])
    assert len(srv.requests) == 3


# --------------------------------------------------------------------------------------
# selection — analysis only, never free-text source authority
# --------------------------------------------------------------------------------------


def test_select_returns_a_candidate_index_not_free_text(fake_llm_server) -> None:
    srv = fake_llm_server("normal")
    sel = _client(srv.base_url).select("pick one", ["alpha", "beta"])
    assert sel.index == 0
    assert sel.value == "alpha"  # drawn from the candidate list, not the model string
    assert not isinstance(sel, str)


def test_select_non_candidate_model_answer_does_not_become_source(fake_llm_server) -> None:
    srv = fake_llm_server("returns_non_candidate")
    sel = _client(srv.base_url).select("pick one", ["alpha", "beta"])
    # the model returned a value that is not among the candidates -> unresolved,
    # never surfaced as an accepted literal
    assert sel.index is None
    assert sel.value is None


def test_double_call_flip_disagreement_is_reported_to_the_caller(fake_llm_server) -> None:
    srv = fake_llm_server("flip")
    check = _client(srv.base_url).select_twice("pick one", ["alpha", "beta"])
    assert check.agree is False
    assert check.first.index != check.second.index


def test_double_call_stable_backend_agrees(fake_llm_server) -> None:
    srv = fake_llm_server("normal")
    check = _client(srv.base_url).select_twice("pick one", ["alpha", "beta"])
    assert check.agree is True


# --------------------------------------------------------------------------------------
# provenance / result record
# --------------------------------------------------------------------------------------


def test_provenance_captures_model_decode_attempts_and_reproducibility(fake_llm_server) -> None:
    srv = fake_llm_server("normal")
    client = _client(srv.base_url, seed=555)
    client.probe()
    client.select("pick one", ["alpha", "beta"])
    prov = client.provenance()
    assert set(prov) >= {"model", "decode", "attempts", "reproducibility"}
    assert prov["decode"] == {"temperature": 0, "seed": 555}
    assert prov["reproducibility"] == "deterministic"
    assert isinstance(prov["attempts"], int) and prov["attempts"] >= 1
