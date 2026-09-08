"""T014 — failing-first unit tests for ``solari_converter.config``.

GREEN owner: **T017**. Option precedence CLI > env > default; numeric bounds enforced;
``output_affecting_config()`` returns exactly the research §14 extract-stage subset and
MUST NOT include UI / navigation / authorization metadata.
"""

from __future__ import annotations

import pytest

from solari_converter.config import Config
from solari_converter.errors import InvalidSelection


def test_defaults() -> None:
    cfg = Config.resolve(cli={}, env={})
    assert cfg.ocr_confidence_threshold == 70
    assert cfg.reconcile_confidence_threshold == 0.75
    assert cfg.gross_divergence_threshold == 0.5
    assert cfg.llm_retries == 2
    assert cfg.llm_decode == {"temperature": 0, "seed": None}
    assert cfg.output_dir.name == "out"


def test_cli_beats_env_beats_default() -> None:
    cfg = Config.resolve(
        cli={"ocr_confidence_threshold": 85},
        env={"SOLARI_OCR_CONFIDENCE_THRESHOLD": "60"},
    )
    assert cfg.ocr_confidence_threshold == 85

    cfg2 = Config.resolve(cli={}, env={"SOLARI_OCR_CONFIDENCE_THRESHOLD": "60"})
    assert cfg2.ocr_confidence_threshold == 60


def test_numeric_bounds_are_enforced() -> None:
    with pytest.raises((InvalidSelection, ValueError)):
        Config.resolve(cli={"ocr_confidence_threshold": 101}, env={})
    with pytest.raises((InvalidSelection, ValueError)):
        Config.resolve(cli={"ocr_confidence_threshold": -1}, env={})
    with pytest.raises((InvalidSelection, ValueError)):
        Config.resolve(cli={"reconcile_confidence_threshold": 1.5}, env={})
    with pytest.raises((InvalidSelection, ValueError)):
        Config.resolve(cli={"gross_divergence_threshold": -0.1}, env={})


def test_resolution_store_and_authorization_log_and_intermediates_paths_resolve() -> None:
    cfg = Config.resolve(cli={"output_dir": "/tmp/o"}, env={})
    assert str(cfg.intermediates_dir).startswith(str(cfg.output_dir))
    assert cfg.resolution_store_path is not None
    # <base>.review-authorizations.jsonl (research §22.4)
    assert str(cfg.authorization_log_path("agreement")).endswith(
        "agreement.review-authorizations.jsonl"
    )


def test_output_affecting_config_is_exactly_the_extract_stage_subset() -> None:
    cfg = Config.resolve(cli={"ocr_engine": "tesseract"}, env={})
    oac = cfg.output_affecting_config(stage="extract")
    assert set(oac) == {
        "ocr_engine",
        "ocr_languages_override",
        "ocr_confidence_threshold",
        "reconcile_confidence_threshold",
        "enabled_extraction_paths",
    }


def test_validate_stage_adds_gross_divergence_and_llm() -> None:
    cfg = Config.resolve(cli={"llm_model": "local-x"}, env={})
    oac = cfg.output_affecting_config(stage="validate", llm_reachable=True)
    assert "gross_divergence_threshold" in oac
    assert oac["llm_model"] == "local-x"
    assert oac["llm_decode"] == {"temperature": 0, "seed": None}


def test_output_affecting_config_excludes_non_content_and_ui_metadata() -> None:
    cfg = Config.resolve(
        cli={
            "llm_base_url": "http://127.0.0.1:9/v1",
            "llm_retries": 9,
            "output_dir": "/tmp/somewhere",
            "as_json": True,
            "resolution_store": "/tmp/store.jsonl",
        },
        env={},
    )
    for stage in ("extract", "validate"):
        oac = cfg.output_affecting_config(stage=stage)
        for forbidden in (
            "llm_base_url", "base_url", "llm_retries", "retries", "output_dir",
            "as_json", "json", "resolution_store", "review_ui", "authorization",
            "authorized_run_id", "run_state",
        ):
            assert forbidden not in oac, forbidden


def test_output_affecting_config_is_json_serialisable_and_run_id_stable_under_ui_changes() -> None:
    from solari_converter import run_identity

    a = Config.resolve(cli={"llm_base_url": "http://127.0.0.1:1/v1"}, env={})
    b = Config.resolve(cli={"llm_base_url": "http://127.0.0.1:2/v1", "llm_retries": 5}, env={})
    common = dict(
        source_sha256="a" * 64,
        normalized_page_selection="all",
        tool_version="0.1.0",
        applicable_resolution_digest="0" * 64,
    )
    rid_a = run_identity.compute_run_id(
        output_affecting_config=a.output_affecting_config(stage="extract"), **common
    )
    rid_b = run_identity.compute_run_id(
        output_affecting_config=b.output_affecting_config(stage="extract"), **common
    )
    assert rid_a == rid_b  # base_url / retries do not move run_id
