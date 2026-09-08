"""T015 — committed-schema drift guard (contract test).

Constitution VI: written test-first. A **progressive drift guard** — like every other
schema in the repo, each per-schema assertion turns green when that schema's pydantic model
is built *and* ``scripts/export_schemas.py`` (T128) regenerates
``contracts/*.schema.json`` from the models. The Phase-3 deliverable is the correctly
written failing test, not a fully green run.

GREEN now
    * every ``contracts/*.schema.json`` is well-formed JSON and declares JSON Schema
      2020-12 with ``additionalProperties: false`` and a consistent ``schema_version``;
    * ``extraction_candidate`` / ``canonical_extracted_document`` carry the seven envelope
      fields but have **no** ``.md`` companion (M1).

INTENTIONAL future RED — ``test_schema_is_in_sync_with_its_model`` (one case per schema)
    Owner: **T128** (`scripts/export_schemas.py` regenerates the committed schema from the
    model) **plus** the per-record model task —
    extraction-candidate → T020 · canonical-extracted-document → T022 ·
    human-review-{queue,resolution} → T024 · reconciliation-log → T062 ·
    removal-log → T072 · validation-report → T098 · traceability-record → T107 ·
    correction-log → T115 · run-context → T137 · human-review-authorization → T139 ·
    human-review-verification → T141. FR-057 ``.json``/``.md`` parity is owned by the
    ``render_markdown()`` renderer tasks (T028+).
"""

from __future__ import annotations

import importlib
import json
from pathlib import Path

import pytest

CONTRACTS = (
    Path(__file__).resolve().parents[2] / "specs" / "001-pdf-markdown-converter" / "contracts"
)
SCHEMA_FILES = sorted(CONTRACTS.glob("*.schema.json"))
DRAFT_2020_12 = "https://json-schema.org/draft/2020-12/schema"

# schema stem -> (module, class attr) for the pydantic record model that must GENERATE it.
MODEL_FOR_SCHEMA: dict[str, tuple[str, str]] = {
    "extraction-candidate": ("solari_converter.model.candidate", "ExtractionCandidate"),
    "canonical-extracted-document": (
        "solari_converter.model.canonical", "CanonicalExtractedDocument"),
    "reconciliation-log": ("solari_converter.reports.reconciliation_log", "ReconciliationLog"),
    "run-context": ("solari_converter.run_identity", "RunContext"),
    "human-review-queue": ("solari_converter.model.human_review", "HumanReviewQueue"),
    "human-review-resolution": ("solari_converter.model.human_review", "HumanReviewResolution"),
    "human-review-authorization": (
        "solari_converter.reports.human_review_authorization", "HumanReviewAuthorization"),
    "human-review-verification": (
        "solari_converter.reports.human_review_verification", "HumanReviewVerification"),
    "removal-log": ("solari_converter.reports.removal_log", "RemovalLog"),
    "validation-report": ("solari_converter.reports.validation_report", "ValidationReport"),
    "correction-log": ("solari_converter.reports.correction_log", "CorrectionLog"),
    "traceability-record": ("solari_converter.reports.traceability", "TraceabilityRecord"),
}
NO_MD_COMPANION = {"extraction-candidate", "canonical-extracted-document"}


def _stem(path: Path) -> str:
    return path.name.removesuffix(".schema.json")


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


# --- GREEN now -------------------------------------------------------------------


def test_the_contract_directory_holds_exactly_twelve_schemas() -> None:
    assert [p.stem for p in SCHEMA_FILES] and len(SCHEMA_FILES) == 12


@pytest.mark.parametrize("path", SCHEMA_FILES, ids=_stem)
def test_schema_is_well_formed_and_declares_draft_2020_12(path: Path) -> None:
    doc = _load(path)  # raises on malformed JSON
    assert doc.get("$schema") == DRAFT_2020_12
    assert doc.get("type") == "object"
    assert doc.get("additionalProperties") is False


@pytest.mark.parametrize("path", SCHEMA_FILES, ids=_stem)
def test_schema_version_const_is_consistent_with_its_id(path: Path) -> None:
    doc = _load(path)
    sv = doc["properties"]["schema_version"]["const"]
    assert sv in {"2.0", "2.1"}
    assert doc["$id"].endswith(f"-{sv}.json")


@pytest.mark.parametrize("stem", sorted(NO_MD_COMPANION))
def test_candidate_and_ced_carry_the_envelope_but_have_no_md_companion(stem: str) -> None:
    doc = _load(CONTRACTS / f"{stem}.schema.json")
    for env_field in ("record_type", "schema_version", "run_id", "tool_version",
                      "source_pdf", "source_sha256", "page_selection"):
        assert env_field in doc["properties"], env_field
    assert "markdown" not in json.dumps(doc).lower()  # M1: JSON is the sole representation


# --- INTENTIONAL future RED (owner: T128 + the per-record model / renderer tasks) ---


@pytest.mark.parametrize("path", SCHEMA_FILES, ids=_stem)
def test_schema_is_in_sync_with_its_model(path: Path) -> None:
    """A committed schema is *in sync* when: its pydantic model exists, ``model_json_schema()``
    reproduces the committed schema (regenerated by T128), and — for an audit record — the
    model carries a ``render_markdown()`` hook for the FR-057 dual emit. RED until then."""
    module_name, attr = MODEL_FOR_SCHEMA[_stem(path)]
    module = importlib.import_module(module_name)  # RED until the model task lands
    model = getattr(module, attr)

    committed = _load(path)
    assert model.model_json_schema() == committed, (
        f"{_stem(path)}: committed schema drifted from {module_name}.{attr}.model_json_schema() "
        "(regenerate via scripts/export_schemas.py — T128)"
    )
    if _stem(path) not in NO_MD_COMPANION:
        assert hasattr(model, "render_markdown"), (
            f"{attr}: no render_markdown() — FR-057 .json/.md parity not yet implemented"
        )
