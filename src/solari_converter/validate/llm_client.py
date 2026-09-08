"""Local, OpenAI-compatible LLM client (T032).

The application is **local-first**: this client only ever talks to a loopback endpoint
(``127.0.0.1`` / ``::1`` / ``localhost``). It is used for two *analysis-only* jobs —
reconciliation candidate **selection** (``select`` / ``select_twice``) and read-only
validation **issue detection** (``detect_issues``). It never returns free-form model text
as authoritative source content: ``select`` resolves the model's answer to an index into
the caller-supplied candidate list, and the downstream programmatic guard
(``reconcile/guard.py`` — T033) remains the hard boundary.

Frozen behaviour (research §4a / §14, FR-053a / FR-053b):

* every request carries ``temperature: 0`` and the configured fixed ``seed``;
* transport / HTTP-5xx / timeout / unparseable failures are retried a **bounded** number
  of times — ``1 initial attempt + N retries`` (``N`` = ``config.llm_retries``, default 2)
  — then raise :class:`LLMUnavailable` (process exit 4);
* ``probe()`` issues one tiny fixed request **twice** (FR-053b seed-determinism probe):
  identical answers ⇒ ``deterministic``, differing answers ⇒ ``best_effort``. The
  classification is recorded in :meth:`provenance` and the report / traceability record —
  it is **not** an input to ``run_id`` (research §14).
"""

from __future__ import annotations

import ipaddress
import json
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

import httpx

from solari_converter.config import Config
from solari_converter.errors import LLMUnavailable

__all__ = [
    "LLMClient",
    "Selection",
    "FlipCheck",
    "ProbeResult",
    "SEED_PROBE_MARKER",
]

# The marker the fake test backend and any real probe share so the request is
# identifiable as the deterministic probe call.
SEED_PROBE_MARKER = "SOLARI_SEED_DETERMINISM_PROBE"
_SEED_PROBE_PROMPT = (
    f"{SEED_PROBE_MARKER}: respond with the single token OK and nothing else."
)

_DEFAULT_TIMEOUT = 30.0


def _is_local_host(host: str | None) -> bool:
    """True only for an unambiguously on-machine endpoint host.

    Accepts the literal DNS name ``localhost`` (with an optional trailing root dot) and
    any IP literal whose address is loopback (``127.0.0.0/8`` or ``::1``). Everything else
    — the wildcard/unspecified addresses ``0.0.0.0`` / ``::``, public IPs, and every other
    DNS name including ones that merely start with ``127.`` — is rejected. No DNS
    resolution is performed, so endpoint authorization stays deterministic and immune to
    DNS-rebinding / resolver surprises (research §8 / §12, constitution V)."""
    if not host:
        return False
    value = host.strip("[]").rstrip(".").lower()
    if value == "localhost":
        return True
    try:
        return ipaddress.ip_address(value).is_loopback
    except ValueError:
        return False


@dataclass(frozen=True)
class Selection:
    """The outcome of an LLM candidate selection — an index into the supplied candidate
    list (``None`` when the model's answer matched no candidate) plus the candidate value
    at that index. ``value`` is **always** copied from the candidate list, never from the
    model's own string (FR-061a)."""

    index: int | None
    value: str | None
    raw: Any = None


@dataclass(frozen=True)
class FlipCheck:
    """The result of the double-call flip check (research §4a) — the two selections and
    whether they agree. A disagreement is surfaced to the caller, which then applies the
    deterministic tie-break or routes the conflict to Human Review."""

    first: Selection
    second: Selection

    @property
    def agree(self) -> bool:
        return self.first.index is not None and self.first.index == self.second.index


@dataclass(frozen=True)
class ProbeResult:
    """``probe()`` outcome — reachability plus the FR-053b seed-determinism class."""

    reachable: bool
    reproducibility: str  # "deterministic" | "best_effort"
    model: str | None


class LLMClient:
    """A thin OpenAI-compatible chat client bound to a single loopback endpoint."""

    def __init__(
        self,
        *,
        base_url: str,
        model: str | None = None,
        seed: int | None = None,
        temperature: int | float = 0,
        retries: int = 2,
        timeout: float = _DEFAULT_TIMEOUT,
    ) -> None:
        parsed = urlparse(base_url)
        if not _is_local_host(parsed.hostname):
            raise LLMUnavailable(
                f"local-first: the LLM endpoint {base_url!r} is not a loopback address "
                "(only 'localhost', 127.0.0.0/8, and ::1 are permitted)"
            )
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._decode: dict[str, Any] = {"temperature": temperature, "seed": seed}
        self._retries = max(0, int(retries))
        self._timeout = float(timeout)
        self._attempts = 0
        self._reproducibility: str | None = None

    @classmethod
    def from_config(cls, cfg: Config, *, timeout: float = _DEFAULT_TIMEOUT) -> LLMClient:
        decode = dict(cfg.llm_decode or {})
        return cls(
            base_url=cfg.llm_base_url,
            model=cfg.llm_model,
            seed=decode.get("seed"),
            temperature=decode.get("temperature", 0),
            retries=cfg.llm_retries,
            timeout=timeout,
        )

    # --- provenance ----------------------------------------------------------------

    def provenance(self) -> dict[str, Any]:
        """The ``{model, decode, attempts, reproducibility}`` record folded into the
        validation report and the traceability record (research §14 / FR-053b)."""
        return {
            "model": self._model,
            "decode": dict(self._decode),
            "attempts": self._attempts,
            "reproducibility": self._reproducibility,
        }

    # --- probe --------------------------------------------------------------------

    def probe(self) -> ProbeResult:
        """Reachability + FR-053b seed-determinism probe: the same tiny fixed request is
        issued twice; identical answers ⇒ ``deterministic``, else ``best_effort``. An
        unreachable / failing endpoint raises :class:`LLMUnavailable`."""
        messages = [{"role": "user", "content": _SEED_PROBE_PROMPT}]
        first = self._chat(messages, tag="probe")
        second = self._chat(messages, tag="probe")
        self._reproducibility = "deterministic" if first == second else "best_effort"
        return ProbeResult(
            reachable=True, reproducibility=self._reproducibility, model=self._model
        )

    # --- selection (analysis only) ----------------------------------------------

    def select(self, prompt: str, candidates: list[str]) -> Selection:
        """Ask the backend to pick one of ``candidates`` by index. Returns a
        :class:`Selection`; a model answer that matches no candidate yields
        ``index=None`` (the conflict stays unresolved — it is never accepted as text)."""
        cands = list(candidates)
        messages = [
            {
                "role": "system",
                "content": (
                    "You choose exactly one candidate by its index. Reply as JSON "
                    '{"selected_index": <int>}. You never write, edit, or invent text.'
                ),
            },
            {"role": "user", "content": self._selection_prompt(prompt, cands)},
        ]
        content = self._chat(messages, tag="select")
        return self._parse_selection(content, cands)

    def select_twice(self, prompt: str, candidates: list[str]) -> FlipCheck:
        """The double-call flip check (research §4a) used by reconciliation."""
        cands = list(candidates)
        return FlipCheck(
            first=self.select(prompt, cands),
            second=self.select(prompt, cands),
        )

    def detect_issues(self, prompt: str) -> list[dict[str, Any]]:
        """One read-only validation pass. Returns a list of issue dicts; never an edit
        and never free text used as source (FR-037)."""
        messages = [
            {
                "role": "system",
                "content": (
                    "You perform a read-only fidelity review. Reply as JSON "
                    '{"issues": [...]}. You never propose edits, rewrites, or replacement text.'
                ),
            },
            {"role": "user", "content": prompt},
        ]
        content = self._chat(messages, tag="detect_issues")
        try:
            parsed = json.loads(content)
        except (json.JSONDecodeError, TypeError):
            return []
        issues = parsed.get("issues") if isinstance(parsed, dict) else None
        return [dict(i) for i in issues if isinstance(i, dict)] if isinstance(issues, list) else []

    # --- internals --------------------------------------------------------------

    @staticmethod
    def _selection_prompt(prompt: str, candidates: list[str]) -> str:
        lines = [prompt, "", "Candidates:"]
        lines += [f"[{i}] {c!r}" for i, c in enumerate(candidates)]
        return "\n".join(lines)

    def _parse_selection(self, content: str, candidates: list[str]) -> Selection:
        try:
            parsed = json.loads(content)
        except (json.JSONDecodeError, TypeError):
            parsed = None

        index: int | None = None
        if isinstance(parsed, dict):
            raw_idx = parsed.get("selected_index")
            if isinstance(raw_idx, bool):
                raw_idx = None
            if isinstance(raw_idx, int) and 0 <= raw_idx < len(candidates):
                index = raw_idx
            elif isinstance(parsed.get("selected"), str):
                # Match by *exact* candidate value only — the model's string itself is
                # never adopted as content.
                target = parsed["selected"]
                for i, cand in enumerate(candidates):
                    if cand == target:
                        index = i
                        break

        value = candidates[index] if index is not None else None
        return Selection(index=index, value=value, raw=content)

    def _chat(self, messages: list[dict[str, str]], *, tag: str) -> str:
        url = f"{self._base_url}/chat/completions"
        body: dict[str, Any] = {
            "model": self._model or "local-model",
            "messages": messages,
            "temperature": self._decode.get("temperature", 0),
        }
        seed = self._decode.get("seed")
        if seed is not None:
            body["seed"] = seed

        last_err: Exception | str | None = None
        for _ in range(self._retries + 1):
            self._attempts += 1
            try:
                # trust_env=False: ignore HTTP(S)_PROXY / ALL_PROXY / NO_PROXY so a
                # loopback request can never be rerouted off-machine (research §8 / §12).
                # follow_redirects=False: a 3xx from the endpoint is never chased to
                # another host — made explicit so it stays regression-proof.
                with httpx.Client(
                    timeout=self._timeout,
                    trust_env=False,
                    follow_redirects=False,
                ) as client:
                    resp = client.post(url, json=body)
            except httpx.TimeoutException as exc:
                last_err = f"timeout: {exc!r}"
                continue
            except httpx.TransportError as exc:
                last_err = f"transport error: {exc!r}"
                continue

            if resp.status_code >= 500:
                last_err = f"HTTP {resp.status_code}"
                continue
            if resp.status_code >= 400:
                raise LLMUnavailable(f"{tag}: local LLM returned HTTP {resp.status_code}")

            try:
                data = resp.json()
                content = data["choices"][0]["message"]["content"]
            except (json.JSONDecodeError, KeyError, IndexError, TypeError, ValueError) as exc:
                last_err = f"unparseable response: {exc!r}"
                continue
            if not isinstance(content, str):
                last_err = "unparseable response: non-string content"
                continue
            return content

        raise LLMUnavailable(
            f"{tag}: local LLM failed after {self._retries + 1} attempt(s) "
            f"({self._base_url}): {last_err}"
        )
