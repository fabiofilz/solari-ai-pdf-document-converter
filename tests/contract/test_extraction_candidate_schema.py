"""T035 [US1] — contract test: ``ExtractionCandidate`` ↔ ``extraction-candidate.schema.json``.

GREEN now (owner T020 model + committed schema agree at instance level):
    * a model-built candidate serialises to a document that conforms to the committed schema;
    * ``technique`` matches ``docling | pdfplumber | ocr:<engine>``;
    * every segment carries ``segment_id`` + a ``SourceRef`` + ``reading_order_index``;
    * **M1** — the contract has no ``.md`` companion: JSON is the sole representation and
      neither the schema nor the model mentions a markdown rendering.

The ``model_json_schema() == committed`` drift guard stays owned by T015 / T128.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from solari_converter.model.candidate import CandidateReadingOrder, ExtractionCandidate
from solari_converter.model.provenance import SourceRef
from solari_converter.model.segment import SourceBackedSegment

from ._schema_subset import assert_valid

_SCHEMA = json.loads(
    (
        Path(__file__).resolve().parents[2]
        / "specs/001-pdf-markdown-converter/contracts/extraction-candidate.schema.json"
    ).read_text(encoding="utf-8")
)

_ENV = dict(
    run_id="0" * 16, tool_version="0.1.0", source_pdf="agreement.pdf",
    source_sha256="a" * 64, page_selection="all",
)


def _candidate(*, technique: str = "pdfplumber") -> ExtractionCandidate:
    seg = SourceBackedSegment(
        segment_id="seg000000001",
        text="Cláusula 4ª",
        source=SourceRef(
            physical_page=1, bbox=(10.0, 20.0, 100.0, 32.0),
            origin_kind="native_text", extraction_technique=technique,
        ),
        reading_order_index=0,
    )
    return ExtractionCandidate(
        **_ENV, technique=technique, status="ok", segments=[seg],
        reading_order=CandidateReadingOrder(technique="geometry", order=["seg000000001"]),
        pages_covered=[1],
    )


def test_a_built_candidate_conforms_to_the_committed_schema() -> None:
    assert_valid(json.loads(_candidate().model_dump_json()), _SCHEMA)


@pytest.mark.parametrize("technique", ["docling", "pdfplumber", "ocr:tesseract", "ocr:rapidocr"])
def test_valid_technique_tokens_are_accepted(technique: str) -> None:
    assert _candidate(technique=technique).technique == technique


@pytest.mark.parametrize("technique", ["ocr:", "OCR:tesseract", "camelot", "ocr tesseract", ""])
def test_invalid_technique_tokens_are_rejected(technique: str) -> None:
    with pytest.raises(ValueError):
        _candidate(technique=technique)


def test_every_segment_carries_id_sourceref_and_reading_order_index() -> None:
    seg = _candidate().segments[0]
    assert seg.segment_id and isinstance(seg.source, SourceRef)
    assert seg.source.extraction_technique and seg.reading_order_index == 0


def test_contract_has_no_markdown_companion_m1() -> None:
    # neither the schema nor the model represents a candidate as/with markdown
    assert "markdown" not in json.dumps(_SCHEMA).lower()
    assert "markdown" not in json.dumps(ExtractionCandidate.model_json_schema()).lower()


def test_schema_is_json_only_and_strict() -> None:
    assert _SCHEMA["properties"]["record_type"]["const"] == "extraction_candidate"
    assert _SCHEMA["properties"]["schema_version"]["const"] == "2.0"
    assert _SCHEMA["additionalProperties"] is False
