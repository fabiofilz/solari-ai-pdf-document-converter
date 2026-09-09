"""Pre-semantic remediation — the CED-level consequence of the coverage defect.

Before the fix, when one native technique emitted a coarse segment and the other
emitted finer segments for the *same* source text, IoU grouping left both as independent
single-member groups and **both were accepted** — so the coarse literal and the
concatenation of the finer literals entered the Canonical Extracted Document, duplicating
the shared source characters.

After the fix (``reconcile/align.py`` coverage corroboration, §21a) the coarse segment is
represented **through** the finer groups: each covered source span appears once, at the
finer granularity, and both contributing native techniques are retained. The CED stays
pre-semantic and every accepted literal is still an exact extraction-candidate string.
"""

from __future__ import annotations

from solari_converter.model.candidate import CandidateReadingOrder, ExtractionCandidate
from solari_converter.model.provenance import SourceRef
from solari_converter.model.segment import SourceBackedSegment
from solari_converter.reconcile import engine

_ENV = dict(
    run_id="0" * 16, tool_version="0.1.0", source_pdf="coarse_fine.pdf",
    source_sha256="a" * 64, page_selection="all",
)
_CFG = {
    "ocr_engine": "tesseract",
    "ocr_languages_override": None,
    "ocr_confidence_threshold": 70,
    "enabled_extraction_paths": ["docling", "pdfplumber"],
}

# a tall coarse box; two finer boxes stack inside it (IoU vs coarse < 0.5 each), so
# the finer reading order is geometrically unambiguous (top clearly above bottom).
_COARSE = (100.0, 100.0, 400.0, 140.0)
_FINE_TOP = (105.0, 100.0, 395.0, 118.0)
_FINE_BOT = (105.0, 121.0, 395.0, 139.0)


def _seg(sid, bbox, text, idx, *, technique):
    return SourceBackedSegment(
        segment_id=sid, text=text, reading_order_index=idx,
        source=SourceRef(
            physical_page=1, bbox=bbox, origin_kind="native_text",
            extraction_technique=technique,
        ),
    )


def _cand(technique, segs):
    return ExtractionCandidate(
        **_ENV, technique=technique, status="ok", segments=list(segs),
        reading_order=CandidateReadingOrder(
            technique=technique, order=[s.segment_id for s in segs]
        ),
        pages_covered=[1],
    )


def _run(candidates, tmp_path):
    return engine.reconcile(
        candidates=candidates, envelope=_ENV, source_sha256="a" * 64,
        config_subset=_CFG, store=None, llm_client=None, llm_capable=False,
        output_dir=tmp_path, base="coarse_fine",
    )


def test_coarse_over_fine_native_segmentation_is_not_duplicated_in_the_ced(tmp_path):
    plumber = _cand("pdfplumber", [_seg("p1", _COARSE, "Cláusula 4ª — do objeto", 0,
                                        technique="pdfplumber")])
    docling = _cand("docling", [
        _seg("d1", _FINE_TOP, "Cláusula 4ª", 0, technique="docling"),
        _seg("d2", _FINE_BOT, "— do objeto", 1, technique="docling"),
    ])
    out = _run([plumber, docling], tmp_path)

    assert out.human_review_required is False
    ced = out.canonical
    assert ced is not None

    texts = sorted(s.text for s in ced.accepted_segments)
    assert texts == ["Cláusula 4ª", "— do objeto"]  # each span once, finer granularity

    # the coarse literal did not enter the CED as its own accepted segment
    assert "Cláusula 4ª — do objeto" not in {s.text for s in ced.accepted_segments}

    # both native techniques are retained as corroborating evidence on every span
    for s in ced.accepted_segments:
        assert sorted(s.contributing_techniques) == ["docling", "pdfplumber"]
        assert s.decision.method == "deterministic_agreement"

    # no unique source character was suppressed: the coarse text is exactly the finer
    # texts joined, so concatenating the accepted texts reproduces it
    joined = " ".join(s.text for s in sorted(ced.accepted_segments,
                                             key=lambda s: s.source.bbox[1]))
    assert joined == "Cláusula 4ª — do objeto"

    # CED stays pre-semantic; accepted values are exact candidate strings
    assert ced.state == "pre_semantic_transformation"
    all_candidate_texts = {"Cláusula 4ª — do objeto", "Cláusula 4ª", "— do objeto"}
    assert all(s.text in all_candidate_texts for s in ced.accepted_segments)

    # duplicated accepted characters attributable to the coarse/fine mismatch:
    # pre-fix the accepted set was {coarse, fine_l, fine_r} and the coarse literal's
    # characters were all repeated by the finer pair; post-fix that count is 0.
    accepted_concat = "".join(sorted(s.text for s in ced.accepted_segments))
    naive_pre_fix = "".join(sorted(["Cláusula 4ª — do objeto", "Cláusula 4ª", "— do objeto"]))
    assert len(accepted_concat) < len(naive_pre_fix)
    assert len(accepted_concat) == len("Cláusula 4ª") + len("— do objeto")
