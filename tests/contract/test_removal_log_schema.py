"""T040 [US1] — contract test: ``RemovalLog`` ↔ ``removal-log.schema.json``.

GREEN now:
    * the committed schema is well-formed, strict, envelope-bearing, ``schema_version`` 2.0;
    * the envelope has ``run_id`` and **no** ``generated_at`` (FR-053a);
    * every ``entries[]`` item carries ``id`` / ``page`` / ``element_type`` / ``reason`` /
      ``kept_due_to_ambiguity``.

INTENTIONAL future RED — ``test_removal_log_model_exists`` / ``test_a_built_log_conforms``
    Owner: **T072** (``src/solari_converter/reports/removal_log.py`` — the ``RemovalLog`` +
    ``RemovalEntry`` models + ``render_markdown()`` for the FR-057 ``.json``/``.md`` dual emit).
"""

from __future__ import annotations

import importlib
import json
from pathlib import Path

from ._schema_subset import assert_valid

_SCHEMA = json.loads(
    (
        Path(__file__).resolve().parents[2]
        / "specs/001-pdf-markdown-converter/contracts/removal-log.schema.json"
    ).read_text(encoding="utf-8")
)


def test_schema_is_strict_v2_with_run_id_and_no_generated_at() -> None:
    assert _SCHEMA["properties"]["record_type"]["const"] == "removal_log"
    assert _SCHEMA["properties"]["schema_version"]["const"] == "2.0"
    assert _SCHEMA["additionalProperties"] is False
    assert "run_id" in _SCHEMA["properties"] and "generated_at" not in _SCHEMA["properties"]


def test_entry_contract() -> None:
    item = _SCHEMA["properties"]["entries"]["items"]
    assert set(item["required"]) == {
        "id", "page", "element_type", "reason", "kept_due_to_ambiguity"
    }
    assert "auth_stamp" in item["properties"]["element_type"]["enum"]
    assert set(item["properties"]["reason"]["enum"]) == {
        "matched_repeated", "matched_pattern", "classifier"
    }


def _model():
    return importlib.import_module("solari_converter.reports.removal_log").RemovalLog


def test_removal_log_model_exists() -> None:
    """RED until T072 creates reports/removal_log.py."""
    assert hasattr(_model(), "render_markdown"), "FR-057 .json/.md dual emit"


def test_a_built_log_conforms_to_the_committed_schema() -> None:
    """RED until T072."""
    log = _model()(
        run_id="0" * 16, tool_version="0.1.0", source_pdf="a.pdf",
        source_sha256="a" * 64, page_selection="all", entries=[],
    )
    assert_valid(json.loads(log.model_dump_json()), _SCHEMA)
