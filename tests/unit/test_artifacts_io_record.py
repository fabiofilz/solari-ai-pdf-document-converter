"""Focused regression: ``artifacts_io.write_record`` serialises pydantic **field
aliases** under their contract name (pre-semantic remediation, audit finding 2).

The only aliased field in the RecordEnvelope-backed model tree is the CED
``page_classes[].class`` (Python identifier ``class_``). Before the fix the persisted
JSON carried ``class_``, diverging from ``contracts/canonical-extracted-document.schema.json``
(and every generated consumer). ``write_record`` now dumps ``by_alias=True``:

* the CED page-class field serialises as ``class`` and round-trips;
* deterministic canonical bytes are preserved (``by_alias`` does not reorder keys);
* a model with no aliased fields is byte-identical to the pre-fix output.
"""

from __future__ import annotations

import json

from solari_converter import artifacts_io
from solari_converter.model.canonical import (
    AcceptedDecision,
    AcceptedSegment,
    CanonicalExtractedDocument,
    PageClassEntry,
)
from solari_converter.model.provenance import SourceRef

_ENV = dict(
    run_id="0" * 16, tool_version="0.1.0", source_pdf="agreement.pdf",
    source_sha256="a" * 64, page_selection="all",
)
_SRC = SourceRef(physical_page=1, origin_kind="native_text", extraction_technique="pdfplumber")


_STEM = "d.canonical-extracted-document"


def _ced() -> CanonicalExtractedDocument:
    seg = AcceptedSegment(
        segment_id="seg1", text="Cláusula 4ª", source=_SRC,
        contributing_techniques=["pdfplumber", "docling"],
        decision=AcceptedDecision(method="deterministic_agreement", decision_id="d1"),
    )
    return CanonicalExtractedDocument(
        **_ENV, accepted_segments=[seg], accepted_reading_order=["seg1"],
        page_classes=[
            PageClassEntry(page=1, **{"class": "native_text_sufficient"}),
            PageClassEntry(page=2, **{"class": "hybrid_native_and_ocr"}),
        ],
    )


def _write(tmp_path) -> str:
    written = artifacts_io.write_record(tmp_path / _STEM, _ced(), emit_md=False)
    return written[0].read_text(encoding="utf-8")


def test_ced_page_class_field_persists_under_the_contract_alias(tmp_path) -> None:
    data = json.loads(_write(tmp_path))
    assert [e["class"] for e in data["page_classes"]] == [
        "native_text_sufficient", "hybrid_native_and_ocr"
    ]
    for entry in data["page_classes"]:
        assert "class_" not in entry  # the Python identifier must never leak to disk


def test_persisted_ced_round_trips_back_into_the_model(tmp_path) -> None:
    reloaded = CanonicalExtractedDocument.model_validate_json(_write(tmp_path))
    assert [e.class_ for e in reloaded.page_classes] == [
        "native_text_sufficient", "hybrid_native_and_ocr"
    ]


def test_alias_serialisation_is_deterministic_and_key_order_stable(tmp_path) -> None:
    a = _write(tmp_path)
    b_dir = tmp_path / "b"
    b_dir.mkdir()
    b = _write(b_dir)
    assert a == b
    # the alias only renames the key in place — surrounding order is unchanged
    order = list(CanonicalExtractedDocument.model_fields)
    keys = list(json.loads(a))
    assert keys == sorted(keys, key=order.index)
