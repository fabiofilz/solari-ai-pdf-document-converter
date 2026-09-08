"""Deterministic run identifier (T025).

**Research §14 is the single authoritative definition** of the effective-input tuple and
``run_id``. This module implements exactly that formula and nothing else — no wall-clock,
no randomness (FR-053a). ``spec.md`` FR-053a, ``data-model.md`` (common envelope) and
``contracts/cli.md`` reference §14; they do not restate a divergent list.

    run_id = sha256(
        source_sha256          + "\\n" +
        normalized_page_selection + "\\n" +     # "2_5-7_10-12" or "all"
        tool_version           + "\\n" +
        canonical_json(output_affecting_config) + "\\n" +
        applicable_resolution_digest
    ).hexdigest()[:16]

``output_affecting_config`` is supplied by the caller already reduced to the correct
research-§14 scope (extract-stage vs validate-stage) — see ``config.output_affecting_config``
(T017). This function is agnostic to *which* keys it contains; it only canonicalises and
folds. Timeouts, ``base_url``, output dir, ``--resolution-store``, ``--json`` and the
review-UI path are never passed here.

The ``RunContext``-based recomputation of the *current* ``run_id`` after the resolution
store changes is **T137 (Phase 4F)** — not this module.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from typing import Any

__all__ = ["canonical_json", "applicable_resolution_digest", "compute_run_id"]

_RUN_ID_LEN = 16


def canonical_json(obj: Any) -> str:
    """Deterministic JSON: keys sorted, compact separators, non-ASCII kept verbatim.

    The one canonical serialisation used for every digest input in the codebase
    (run_id, applicability key, resolution_id — research §14 / §22 / §22.2).
    """
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def applicable_resolution_digest(
    resolutions: Iterable[tuple[str, Mapping[str, Any]]],
) -> str:
    """``sha256`` over the sorted ``f"{applicability_key}={canonical_json(selected)}"``
    lines of the **currently-applicable** resolution set replayed for a run
    (data-model.md ``RunIdentity`` / research §14). Order-independent over the set; an
    empty set yields ``sha256(b"").hexdigest()``.
    """
    parts = sorted(
        f"{key}={canonical_json(selected)}" for key, selected in resolutions
    )
    return hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()


def compute_run_id(
    *,
    source_sha256: str,
    normalized_page_selection: str,
    tool_version: str,
    output_affecting_config: Mapping[str, Any],
    applicable_resolution_digest: str,
) -> str:
    """The 16-hex deterministic run identifier (research §14). Pure function of its
    arguments — no wall-clock, no randomness (FR-053a)."""
    payload = (
        f"{source_sha256}\n"
        f"{normalized_page_selection}\n"
        f"{tool_version}\n"
        f"{canonical_json(dict(output_affecting_config))}\n"
        f"{applicable_resolution_digest}"
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:_RUN_ID_LEN]
