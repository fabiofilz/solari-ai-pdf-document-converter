"""T065 [US1] — the non-rewrite reconciliation invariant (planning requirement 5, core).

Even with an **adversarial / incorrect** local LLM, the selector-only reconciliation tier
can never cause source text that is not in an exact extraction candidate (or a replayed
``human_confirmed`` resolution) to enter the Canonical Extracted Document. Exercised
end-to-end through :func:`solari_converter.reconcile.engine.reconcile` with the loopback
``fake_llm_server`` (no egress — the repo-root autouse guard blocks non-loopback sockets).

* (a) ``returns_non_candidate`` on a literal conflict → guard-rejected → HUMAN_REVIEW,
  **no CED**, the invented value is in no written artifact;
* (b) ``returns_non_candidate`` on a reading-order conflict → guard-rejected → a
  reading-order review item;
* (c) forced confidence ``< 0.75`` → HUMAN_REVIEW with **no LLM call** — never a guess;
* (d) property: every automatically-reconciled value in the CED is byte-identical to one
  of that group's candidate values (SC-020).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from solari_converter.model.candidate import CandidateReadingOrder, ExtractionCandidate
from solari_converter.model.provenance import SourceRef
from solari_converter.model.segment import SourceBackedSegment
from solari_converter.reconcile import engine
from solari_converter.validate.llm_client import LLMClient

_ENV = dict(
    run_id="0" * 16, tool_version="0.1.0", source_pdf="synthetic.pdf",
    source_sha256="a" * 64, page_selection="all",
)
_SRC_SHA = "a" * 64
_CFG = {
    "ocr_engine": "tesseract",
    "ocr_languages_override": None,
    "ocr_confidence_threshold": 70,
    "enabled_extraction_paths": ["docling", "pdfplumber", "ocr"],
}


def _seg(sid, bbox, text, idx, *, page=1, origin="native_text",
         technique="pdfplumber", ocr_conf=None):
    return SourceBackedSegment(
        segment_id=sid, text=text, reading_order_index=idx,
        source=SourceRef(
            physical_page=page, bbox=bbox, origin_kind=origin,
            extraction_technique=technique, ocr_confidence=ocr_conf,
        ),
    )


def _cand(technique, segs):
    return ExtractionCandidate(
        **_ENV, technique=technique, status="ok", segments=list(segs),
        reading_order=CandidateReadingOrder(
            technique=technique, order=[s.segment_id for s in segs]
        ),
        pages_covered=sorted({s.source.physical_page for s in segs}),
    )


def _client(srv):
    return LLMClient(base_url=srv.base_url, model="fake", seed=0, retries=0)


def _run(candidates, tmp_path, *, srv=None, llm_capable=False, threshold=0.75):
    return engine.reconcile(
        candidates=candidates, envelope=_ENV, source_sha256=_SRC_SHA,
        config_subset=_CFG, reconcile_confidence_threshold=threshold,
        store=None, llm_client=_client(srv) if srv else None,
        llm_capable=llm_capable, output_dir=tmp_path, base="synthetic",
    )


# --------------------------------------------------------------------------------------


_NON_CANDIDATE = "A VALUE THAT IS NOT AMONG THE CANDIDATES"


def _bbox(y0):
    return (100.0, float(y0), 300.0, float(y0 + 20))


def test_a_non_candidate_literal_is_rejected_no_ced(fake_llm_server, tmp_path):
    srv = fake_llm_server("returns_non_candidate")
    b = _bbox(100)
    cands = [
        _cand("docling", [_seg("d1", b, "art. 12", 0, technique="docling")]),
        _cand("pdfplumber", [_seg("p1", b, "art. 12", 0, technique="pdfplumber")]),
        _cand("ocr:tesseract", [
            _seg("o1", b, "art 12", 0, origin="ocr",
                 technique="ocr:tesseract", ocr_conf=95.0)
        ]),
    ]
    out = _run(cands, tmp_path, srv=srv, llm_capable=True)

    assert out.human_review_required is True
    assert out.canonical is None
    assert any(it.conflict_type == "literal_content" for it in out.queue.items)
    reasons = {u.reason for u in out.log.unresolved}
    assert "guard_rejected" in reasons
    blob = b"".join(p.read_bytes() for p in Path(tmp_path).rglob("*") if p.is_file())
    assert _NON_CANDIDATE.encode() not in blob  # invented value never persisted


def test_a_non_candidate_reading_order_is_rejected_to_a_review_item(fake_llm_server, tmp_path):
    srv = fake_llm_server("returns_non_candidate")
    # 4 regions; A/B and C/D overlap vertically -> geometry ambiguous; two full-perm
    # candidate orders differ by one adjacent swap -> disagreement confidence >= 0.75
    regions = {
        "A": (100.0, 100.0, 300.0, 160.0), "B": (100.0, 140.0, 300.0, 200.0),
        "C": (100.0, 300.0, 300.0, 360.0), "D": (100.0, 340.0, 300.0, 400.0),
    }
    doc = {"A": 0, "B": 1, "C": 2, "D": 3}
    ocr = {"A": 0, "B": 1, "C": 3, "D": 2}
    dsegs = [_seg(f"d-{k}", v, "same text", doc[k], technique="docling")
             for k, v in regions.items()]
    osegs = [_seg(f"o-{k}", v, "same text", ocr[k], origin="ocr",
                  technique="ocr:tesseract", ocr_conf=90.0)
             for k, v in regions.items()]
    out = _run([_cand("docling", dsegs), _cand("ocr:tesseract", osegs)],
              tmp_path, srv=srv, llm_capable=True)

    assert out.human_review_required is True
    assert out.canonical is None
    assert any(it.conflict_type == "reading_order" for it in out.queue.items)
    ro = next(it for it in out.queue.items if it.conflict_type == "reading_order")
    assert ro.segment_ids and len(ro.segment_ids) == 4


def test_forced_below_threshold_is_human_review_with_no_llm_call(fake_llm_server, tmp_path):
    srv = fake_llm_server("normal")
    b = _bbox(100)
    cands = [
        _cand("ocr:rapidocr", [
            _seg("o1", b, "R$ 100", 0, origin="ocr", technique="ocr:rapidocr", ocr_conf=30.0)
        ]),
        _cand("ocr:tesseract", [
            _seg("o2", b, "R$ 188", 0, origin="ocr", technique="ocr:tesseract", ocr_conf=30.0)
        ]),
    ]
    out = _run(cands, tmp_path, srv=srv, llm_capable=True)

    assert out.human_review_required is True
    assert out.canonical is None
    assert {u.reason for u in out.log.unresolved} == {"below_threshold"}
    assert srv.requests == []  # the < 0.75 gate is checked before any LLM call


def test_no_llm_mode_at_or_above_threshold_never_guesses(tmp_path):
    b = _bbox(100)
    cands = [
        _cand("docling", [_seg("d1", b, "art. 12", 0, technique="docling")]),
        _cand("pdfplumber", [_seg("p1", b, "art. 12", 0, technique="pdfplumber")]),
        _cand("ocr:tesseract", [
            _seg("o1", b, "art 12", 0, origin="ocr", technique="ocr:tesseract", ocr_conf=95.0)
        ]),
    ]
    out = _run(cands, tmp_path, srv=None, llm_capable=False)
    assert out.human_review_required is True
    assert out.canonical is None
    assert {u.reason for u in out.log.unresolved} == {"no_llm"}


def test_property_automatic_ced_values_are_always_candidate_values(fake_llm_server, tmp_path):
    srv = fake_llm_server("normal")  # LLM always picks candidate index 0
    g1 = _bbox(100)
    g2 = _bbox(200)
    cands = [
        _cand("docling", [
            _seg("d1", g1, "hello world", 0, technique="docling"),
            _seg("d2", g2, "art. 12", 1, technique="docling"),
        ]),
        _cand("pdfplumber", [
            _seg("p1", g1, "hello world", 0, technique="pdfplumber"),
            _seg("p2", g2, "art. 12", 1, technique="pdfplumber"),
        ]),
        _cand("ocr:tesseract", [
            _seg("o1", g1, "hello world", 0, origin="ocr",
                 technique="ocr:tesseract", ocr_conf=90.0),
            _seg("o2", g2, "art 12", 1, origin="ocr",
                 technique="ocr:tesseract", ocr_conf=95.0),
        ]),
    ]
    out = _run(cands, tmp_path, srv=srv, llm_capable=True)

    assert out.human_review_required is False
    ced = out.canonical
    assert ced is not None
    # every accepted value is byte-identical to a candidate value for that region
    by_region = {"hello world", "art. 12", "art 12"}
    for seg in ced.accepted_segments:
        assert seg.text in by_region
    # the CED reading order covers exactly the accepted segments
    assert set(ced.accepted_reading_order) == {s.segment_id for s in ced.accepted_segments}
    for d in out.log.decisions:
        if d.method in ("deterministic_agreement", "llm_selected"):
            sel = d.selected.get("value") or d.selected.get("order")
            assert sel is not None


@pytest.mark.parametrize("mode", ["always_500", "unparseable"])
def test_mid_run_llm_failure_propagates_and_writes_nothing(fake_llm_server, tmp_path, mode):
    srv = fake_llm_server(mode)
    b = _bbox(100)
    cands = [
        _cand("docling", [_seg("d1", b, "art. 12", 0, technique="docling")]),
        _cand("pdfplumber", [_seg("p1", b, "art. 12", 0, technique="pdfplumber")]),
        _cand("ocr:tesseract", [
            _seg("o1", b, "art 12", 0, origin="ocr", technique="ocr:tesseract", ocr_conf=95.0)
        ]),
    ]
    from solari_converter.errors import LLMUnavailable

    with pytest.raises(LLMUnavailable):
        _run(cands, tmp_path, srv=srv, llm_capable=True)
    assert list(Path(tmp_path).rglob("*.json")) == []  # atomic: nothing persisted
