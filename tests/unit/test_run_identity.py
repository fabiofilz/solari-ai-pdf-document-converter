"""T014 — failing-first unit tests for ``solari_converter.run_identity``.

GREEN owner: **T025**. Research §14 is the AUTHORITATIVE definition of the effective-input
tuple and ``run_id``. FR-053a: the deterministic core is a pure function of the inputs —
no wall-clock, no randomness. The ``RunContext``-based recomputation is covered by T136
(Phase 4F), not here.
"""

from __future__ import annotations

import hashlib
import pathlib

from solari_converter import run_identity

_SRC = pathlib.Path(run_identity.__file__).read_text(encoding="utf-8")

_SHA = "a" * 64
_EMPTY_DIGEST = hashlib.sha256(b"").hexdigest()

_BASE = dict(
    source_sha256=_SHA,
    normalized_page_selection="all",
    tool_version="0.1.0",
    output_affecting_config={
        "ocr_engine": "tesseract",
        "ocr_languages_override": None,
        "ocr_confidence_threshold": 70,
        "reconcile_confidence_threshold": 0.75,
        "enabled_extraction_paths": ["docling", "pdfplumber", "ocr"],
    },
    applicable_resolution_digest=_EMPTY_DIGEST,
)


def _rid(**over) -> str:
    args = {**_BASE, **over}
    args["output_affecting_config"] = {**_BASE["output_affecting_config"],
                                      **over.get("output_affecting_config", {})}
    return run_identity.compute_run_id(**args)


def test_run_id_is_16_lowercase_hex() -> None:
    rid = _rid()
    assert len(rid) == 16
    assert rid == rid.lower()
    int(rid, 16)  # parses as hex


def test_identical_inputs_give_identical_id() -> None:
    assert _rid() == _rid()


def test_source_hash_change_changes_the_id() -> None:
    assert _rid(source_sha256="b" * 64) != _rid()


def test_normalized_selection_change_changes_the_id() -> None:
    assert _rid(normalized_page_selection="2_5-7") != _rid()


def test_tool_version_change_changes_the_id() -> None:
    assert _rid(tool_version="0.2.0") != _rid()


def test_each_output_affecting_config_field_changes_the_id() -> None:
    base = _rid()
    for field, new in [
        ("ocr_engine", "rapidocr"),
        ("ocr_confidence_threshold", 80),
        ("reconcile_confidence_threshold", 0.80),
        ("ocr_languages_override", ["pt", "en"]),
        ("enabled_extraction_paths", ["pdfplumber"]),
        ("gross_divergence_threshold", 0.6),  # present only for the validate-stage scope
        ("llm_model", "local-model"),
        ("llm_decode", {"temperature": 0, "seed": 7}),
    ]:
        assert _rid(output_affecting_config={field: new}) != base, field


def test_applicable_resolution_digest_change_changes_the_id() -> None:
    assert _rid(applicable_resolution_digest="c" * 64) != _rid()


def test_non_output_affecting_inputs_are_not_parameters() -> None:
    # base_url / timeouts / retries / output dir / --json / the review UI path
    # MUST NOT be able to influence run_id — compute_run_id has no such parameter.
    import inspect

    params = set(inspect.signature(run_identity.compute_run_id).parameters)
    forbidden = {"base_url", "timeout", "timeouts", "retries", "output_dir",
                 "json", "as_json", "resolution_store", "review_ui", "ui"}
    assert not (params & forbidden), params & forbidden


def test_no_wall_clock_or_randomness_in_the_module() -> None:
    for banned in ("import time", "import random", "import uuid",
                   "from datetime", "import datetime", "time.time", "os.urandom",
                   "secrets."):
        assert banned not in _SRC, banned


def test_run_id_matches_the_research_section_14_formula() -> None:
    cfg = _BASE["output_affecting_config"]
    canon = run_identity.canonical_json(cfg)
    manual = hashlib.sha256(
        (
            _SHA + "\n"
            + "all" + "\n"
            + "0.1.0" + "\n"
            + canon + "\n"
            + _EMPTY_DIGEST
        ).encode("utf-8")
    ).hexdigest()[:16]
    assert _rid() == manual


def test_canonical_json_is_sorted_and_compact() -> None:
    assert run_identity.canonical_json({"b": 1, "a": 2}) == '{"a":2,"b":1}'


def test_module_does_not_own_the_applicable_resolution_digest() -> None:
    # Digest ownership is the resolution store (reconcile.resolutions — T030); run_identity
    # only folds the string. Coverage of the digest itself lives in test_resolution_store.py.
    assert not hasattr(run_identity, "applicable_resolution_digest")
