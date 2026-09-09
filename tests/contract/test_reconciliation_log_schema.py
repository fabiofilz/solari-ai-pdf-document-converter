"""T037 [US1] — contract test: ``ReconciliationLog`` ↔ ``reconciliation-log.schema.json``.

GREEN now:
    * the committed schema is well-formed, strict, envelope-bearing, ``schema_version`` 2.0;
    * every ``decisions[]`` item carries the SC-020-relevant fields (``candidates`` ≥ 1,
      ``method`` enum, ``selected``) and every ``unresolved[]`` item references a
      ``review_item_id``; the ``summary`` counts every decision class.

INTENTIONAL future RED — ``test_reconciliation_log_model_exists`` /
``test_a_built_log_conforms`` / ``test_non_human_decisions_satisfy_sc020``
    Owner: **T062** (``src/solari_converter/reports/reconciliation_log.py`` — the
    ``ReconciliationLog`` model + ``render_markdown()`` for the FR-057 ``.json``/``.md``
    dual emit). The reconciliation log **is** an audit record, so it gets the dual emit.
"""

from __future__ import annotations

import importlib
import json
from pathlib import Path

from ._schema_subset import assert_valid

_SCHEMA = json.loads(
    (
        Path(__file__).resolve().parents[2]
        / "specs/001-pdf-markdown-converter/contracts/reconciliation-log.schema.json"
    ).read_text(encoding="utf-8")
)


# --- GREEN now: committed-schema structure ----------------------------------------


def test_schema_is_strict_envelope_bearing_v2() -> None:
    assert _SCHEMA["properties"]["record_type"]["const"] == "reconciliation_log"
    assert _SCHEMA["properties"]["schema_version"]["const"] == "2.0"
    assert _SCHEMA["additionalProperties"] is False
    for env in ("run_id", "tool_version", "source_pdf", "source_sha256", "page_selection"):
        assert env in _SCHEMA["properties"]


def test_decision_and_unresolved_item_contracts() -> None:
    dec = _SCHEMA["properties"]["decisions"]["items"]
    assert set(dec["required"]) >= {
        "decision_id", "conflict_type", "candidates", "method", "selected"
    }
    assert dec["properties"]["candidates"]["minItems"] == 1
    methods = {"deterministic_agreement", "llm_selected", "human_confirmed"}
    assert set(dec["properties"]["method"]["enum"]) == methods
    unr = _SCHEMA["properties"]["unresolved"]["items"]
    assert "review_item_id" in unr["required"]
    summ = _SCHEMA["properties"]["summary"]["required"]
    assert {"literal_deterministic", "literal_llm", "literal_human", "unresolved"} <= set(summ)


# --- INTENTIONAL future RED: the model (owner T062) -------------------------------


def _model():
    return importlib.import_module("solari_converter.reports.reconciliation_log").ReconciliationLog


def test_reconciliation_log_model_exists() -> None:
    """RED until T062 creates reports/reconciliation_log.py."""
    model = _model()
    assert hasattr(model, "render_markdown"), "FR-057 .json/.md dual emit (audit record)"


def test_a_built_log_conforms_to_the_committed_schema() -> None:
    """RED until T062."""
    model = _model()
    log = model(
        run_id="0" * 16, tool_version="0.1.0", source_pdf="a.pdf",
        source_sha256="a" * 64, page_selection="all",
        alignment_summary={"groups": 1, "single_candidate_groups": 0,
                           "iou_threshold": 0.5, "jaccard_threshold": 0.5},
        decisions=[], unresolved=[],
        summary={"literal_deterministic": 0, "literal_llm": 0, "literal_human": 0,
                 "order_deterministic": 0, "order_llm": 0, "order_human": 0, "unresolved": 0},
    )
    assert_valid(json.loads(log.model_dump_json()), _SCHEMA)
