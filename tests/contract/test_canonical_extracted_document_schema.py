"""T036 [US1] — contract test: ``CanonicalExtractedDocument`` ↔ its committed schema.

GREEN now (owner T022):
    * ``state`` is frozen at ``pre_semantic_transformation`` — no other value is accepted;
    * an ``AcceptedSegment`` carries ≥1 ``contributing_techniques``, a ``SourceRef``, and a
      ``decision`` — its ``text`` is verbatim (SC-020) and there is **no "applied" flag** on a
      carried structural hint (hints are carried, not applied — FR-061c);
    * ``accepted_reading_order`` is a plain segment-id list that covers exactly the accepted
      segments;
    * **M1** — CED is JSON only; neither schema nor model mentions a markdown rendering.

INTENTIONAL future RED — ``test_a_built_ced_conforms_to_the_committed_schema``
    Owner: **T128** (``scripts/export_schemas.py`` regenerates the committed schema from the
    model). The committed schema's inline ``accepted_segments[].source`` object is a stale
    subset (no ``extraction_technique``) of the model's ``SourceRef``; regeneration closes it.
    Same root cause as ``test_schemas_committed.py::…[canonical-extracted-document]``.
    (The ``page_classes[].class`` alias is **not** a cause any more — ``artifacts_io``
    persists ``by_alias=True`` and this test serialises the same way; see
    ``test_artifacts_io_record.py`` for the focused alias regression.)
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from solari_converter.model.canonical import (
    AcceptedDecision,
    AcceptedSegment,
    CanonicalExtractedDocument,
    CarriedStructuralHint,
    PageClassEntry,
)
from solari_converter.model.provenance import SourceRef

from ._schema_subset import assert_valid

_SCHEMA = json.loads(
    (
        Path(__file__).resolve().parents[2]
        / "specs/001-pdf-markdown-converter/contracts/canonical-extracted-document.schema.json"
    ).read_text(encoding="utf-8")
)

_ENV = dict(
    run_id="0" * 16, tool_version="0.1.0", source_pdf="agreement.pdf",
    source_sha256="a" * 64, page_selection="all",
)


_SRC = SourceRef(physical_page=1, origin_kind="native_text", extraction_technique="pdfplumber")


def _ced() -> CanonicalExtractedDocument:
    seg = AcceptedSegment(
        segment_id="seg1", text="Cláusula 4ª", source=_SRC,
        contributing_techniques=["pdfplumber", "docling"],
        decision=AcceptedDecision(method="deterministic_agreement", decision_id="d1"),
    )
    hint = CarriedStructuralHint(
        kind="heading", level=1, source_technique="docling", segment_id="seg1"
    )
    return CanonicalExtractedDocument(
        **_ENV, accepted_segments=[seg], accepted_reading_order=["seg1"],
        carried_structural_hints=[hint],
        page_classes=[PageClassEntry(page=1, **{"class": "native_text_sufficient"})],
    )


def test_state_is_frozen_at_pre_semantic_transformation() -> None:
    assert _ced().state == "pre_semantic_transformation"
    with pytest.raises(ValueError):
        CanonicalExtractedDocument(**_ENV, state="post_transform")  # type: ignore[arg-type]


def test_accepted_segment_shape_sc020() -> None:
    seg = _ced().accepted_segments[0]
    assert seg.contributing_techniques and seg.text == "Cláusula 4ª"
    assert seg.decision.method in {"deterministic_agreement", "llm_selected", "human_confirmed"}
    with pytest.raises(ValueError):
        AcceptedSegment(
            segment_id="x", text="y", source=_SRC,
            contributing_techniques=[],  # min_length 1
            decision=AcceptedDecision(method="human_confirmed", decision_id="d"),
        )


def test_carried_hints_have_no_applied_flag_fr061c() -> None:
    hint = _ced().carried_structural_hints[0]
    assert hint.segment_id == "seg1"
    assert "applied" not in hint.model_dump()


def test_accepted_reading_order_covers_exactly_the_accepted_segments() -> None:
    ced = _ced()
    assert set(ced.accepted_reading_order) == {s.segment_id for s in ced.accepted_segments}


def test_contract_is_json_only_m1() -> None:
    assert "markdown" not in json.dumps(_SCHEMA).lower()
    assert "markdown" not in json.dumps(CanonicalExtractedDocument.model_json_schema()).lower()
    assert _SCHEMA["properties"]["state"]["const"] == "pre_semantic_transformation"


def test_a_built_ced_conforms_to_the_committed_schema() -> None:
    """INTENTIONAL RED — owner T128 (committed CED `source` subset is stale vs the model).

    Serialised the way ``artifacts_io.write_record`` persists it (``by_alias=True``), so
    ``page_classes[].class`` is already correct; the only remaining nonconformance is the
    stale inline ``source`` subset that T128's schema regeneration closes.
    """
    assert_valid(json.loads(_ced().model_dump_json(by_alias=True)), _SCHEMA)
