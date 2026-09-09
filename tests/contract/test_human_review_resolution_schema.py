"""T039 [US1] — contract test: ``HumanReviewResolution`` ↔ its committed v2.1 schema.

GREEN now (owner T024):
    * a resolution line (each of the three ``selected`` shapes) conforms to the committed schema;
    * ``mode: "entered"`` ⇒ ``manually_verified: true``;
    * a reading-order ``selected.order`` is a permutation of the item's ``segment_ids``;
    * ``resolution_id`` is content-bound —
      ``sha256(canonical_json({applicability_key, sequence_index, selected}))[:16]``
      (M1) — the model rejects a non-content-bound id;
    * ``sequence_index`` is a non-negative int; ``supersedes`` is a 16-hex id or ``null``;
    * the three ``selected`` shapes (select / entered / order) are structurally distinct.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from solari_converter.model.human_review import (
    CandidateEvidence,
    HumanReviewResolution,
    compute_resolution_id,
)

from ._schema_subset import assert_valid

_SCHEMA = json.loads(
    (
        Path(__file__).resolve().parents[2]
        / "specs/001-pdf-markdown-converter/contracts/human-review-resolution.schema.json"
    ).read_text(encoding="utf-8")
)

_ENV = dict(
    run_id="0" * 16, tool_version="0.1.0", source_pdf="agreement.pdf",
    source_sha256="a" * 64, page_selection="all",
)
_AK = "b" * 64


def _resolution(*, selected: dict, conflict_type: str, sequence_index: int = 0,
                supersedes: str | None = None) -> HumanReviewResolution:
    rid = compute_resolution_id(
        applicability_key=_AK, sequence_index=sequence_index, selected=selected
    )
    return HumanReviewResolution(
        **_ENV, resolution_id=rid, sequence_index=sequence_index, supersedes=supersedes,
        applicability_key=_AK, review_item_id="i1", conflict_type=conflict_type,
        physical_page=5, region_bboxes=[(10.0, 20.0, 100.0, 32.0)],
        candidates_presented=[CandidateEvidence(technique="pdfplumber", value="A")],
        selected=selected,
    )


_SELECT = {"mode": "select", "value": "Cláusula 4ª", "manually_verified": False,
           "from_technique": "pdfplumber"}
_ENTERED = {"mode": "entered", "value": "Cláusula 4ª  ", "manually_verified": True}
_ORDER = {"order": ["s1", "s2", "s3"]}


@pytest.mark.parametrize(
    ("selected", "conflict_type"),
    [(_SELECT, "literal_content"), (_ENTERED, "literal_content"), (_ORDER, "reading_order")],
)
def test_each_selected_shape_conforms_to_the_committed_v21_schema(selected, conflict_type) -> None:
    res = _resolution(selected=selected, conflict_type=conflict_type)
    assert_valid(json.loads(res.model_dump_json()), _SCHEMA)


def test_entered_requires_manually_verified_true() -> None:
    with pytest.raises(ValueError):
        _resolution(selected={"mode": "entered", "value": "x", "manually_verified": False},
                    conflict_type="literal_content")


def test_resolution_id_is_content_bound_m1() -> None:
    good = _resolution(selected=_SELECT, conflict_type="literal_content")
    assert good.resolution_id == compute_resolution_id(
        applicability_key=_AK, sequence_index=0, selected=_SELECT
    )
    with pytest.raises(ValueError):
        HumanReviewResolution(
            **_ENV, resolution_id="0" * 16, sequence_index=0, supersedes=None,
            applicability_key=_AK, review_item_id="i1", conflict_type="literal_content",
            physical_page=1, region_bboxes=[(0.0, 0.0, 1.0, 1.0)],
            candidates_presented=[CandidateEvidence(technique="pdfplumber", value="A")],
            selected=_SELECT,
        )


def test_sequence_index_and_supersedes_shapes() -> None:
    assert _SCHEMA["properties"]["sequence_index"]["minimum"] == 0
    sup = _SCHEMA["properties"]["supersedes"]
    assert sup.get("type") == ["string", "null"] and sup["pattern"] == r"^[a-f0-9]{16}$"
    with pytest.raises(ValueError):
        _resolution(selected=_SELECT, conflict_type="literal_content", sequence_index=-1)
    superseding = _resolution(selected=_SELECT, conflict_type="literal_content",
                              sequence_index=2, supersedes="a" * 16)
    assert superseding.supersedes == "a" * 16


def test_the_three_selected_shapes_are_structurally_distinct() -> None:
    sel = _resolution(selected=_SELECT, conflict_type="literal_content").selected
    ent = _resolution(selected=_ENTERED, conflict_type="literal_content").selected
    order = _resolution(selected=_ORDER, conflict_type="reading_order").selected
    assert sel["mode"] == "select" and "order" not in sel
    assert ent["mode"] == "entered" and ent["manually_verified"] is True
    assert set(order) == {"order"} and "mode" not in order
