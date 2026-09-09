"""T053 — failing-first tests for deterministic cross-candidate segment alignment.

GREEN owner: **T056** (``src/solari_converter/reconcile/align.py``).

Frozen behaviour under test (research §21a, data-model.md "AlignedSegmentGroup",
plan.md ``reconcile/align.py``):

* alignment groups the *independent* extraction candidates' segments that describe the
  same physical region, using **physical page identity + bbox IoU** as the primary
  signal and **token Jaccard only as a tie-break / evidence** signal;
* ``segment_id`` (text-derived identity — deliberately different when paths disagree)
  is **never** the join key;
* the result is deterministic and **stable under input-candidate ordering**;
* a group holds 1–3 members (one per available path); a region only one path saw is
  still a group;
* alignment performs **no** literal mutation / normalisation / structural inference —
  it only groups.
"""

from __future__ import annotations


def _align_mod():
    import solari_converter.reconcile.align as align  # GREEN owner: T056

    return align


# --------------------------------------------------------------------------------------
# builders
# --------------------------------------------------------------------------------------


def _seg(sid, page, bbox, text, idx, *, origin="native_text", technique="pdfplumber",
         ocr_conf=None):
    from solari_converter.model.provenance import SourceRef
    from solari_converter.model.segment import SourceBackedSegment

    return SourceBackedSegment(
        segment_id=sid,
        text=text,
        reading_order_index=idx,
        source=SourceRef(
            physical_page=page,
            bbox=bbox,
            origin_kind=origin,
            extraction_technique=technique,
            ocr_confidence=ocr_conf,
        ),
    )


def _cand(technique, segments, *, order=None):
    from solari_converter.model.candidate import CandidateReadingOrder, ExtractionCandidate

    return ExtractionCandidate(
        run_id="a" * 16,
        tool_version="0.1.0",
        source_pdf="d.pdf",
        source_sha256="b" * 64,
        page_selection="all",
        technique=technique,
        segments=segments,
        reading_order=CandidateReadingOrder(
            technique=technique, order=order or [s.segment_id for s in segments]
        ),
    )


def _member_set(groups):
    """A comparable, order-independent view of an alignment result."""
    return {
        frozenset((m.technique, m.segment_id) for m in g.members)
        for g in groups
    }


# a region three paths all saw, with sub-pixel jitter between techniques
_A_DOCLING = (100.0, 100.0, 300.0, 120.0)
_A_PLUMBER = (101.0, 99.0, 299.0, 121.0)
_A_OCR = (100.5, 100.5, 300.5, 119.5)
# a disjoint region, far down the same page
_B_DOCLING = (100.0, 400.0, 300.0, 420.0)
_B_PLUMBER = (100.0, 401.0, 300.0, 419.0)


# --------------------------------------------------------------------------------------
# grouping rules
# --------------------------------------------------------------------------------------


def test_overlapping_bboxes_equal_text_form_one_three_member_group():
    align = _align_mod()
    cands = [
        _cand("docling", [_seg("d1", 1, _A_DOCLING, "Cláusula 4ª", 0, technique="docling")]),
        _cand("pdfplumber", [_seg("p1", 1, _A_PLUMBER, "Cláusula 4ª", 0)]),
        _cand("ocr:tesseract",
              [_seg("o1", 1, _A_OCR, "Cláusula 4ª", 0, origin="ocr",
                    technique="ocr:tesseract", ocr_conf=88.0)]),
    ]
    groups = align.align(cands)
    assert len(groups) == 1
    assert len(groups[0].members) == 3
    assert {m.technique for m in groups[0].members} == {
        "docling", "pdfplumber", "ocr:tesseract"
    }


def test_disjoint_regions_form_separate_groups():
    align = _align_mod()
    cands = [
        _cand("docling", [
            _seg("d1", 1, _A_DOCLING, "top", 0, technique="docling"),
            _seg("d2", 1, _B_DOCLING, "bottom", 1, technique="docling"),
        ]),
        _cand("pdfplumber", [
            _seg("p1", 1, _A_PLUMBER, "top", 0),
            _seg("p2", 1, _B_PLUMBER, "bottom", 1),
        ]),
    ]
    groups = align.align(cands)
    assert _member_set(groups) == {
        frozenset({("docling", "d1"), ("pdfplumber", "p1")}),
        frozenset({("docling", "d2"), ("pdfplumber", "p2")}),
    }


def test_region_only_one_path_saw_is_a_one_member_group():
    align = _align_mod()
    cands = [
        _cand("docling", [
            _seg("d1", 1, _A_DOCLING, "shared", 0, technique="docling"),
            _seg("d2", 1, _B_DOCLING, "docling only", 1, technique="docling"),
        ]),
        _cand("pdfplumber", [_seg("p1", 1, _A_PLUMBER, "shared", 0)]),
    ]
    groups = align.align(cands)
    solo = [g for g in groups if len(g.members) == 1]
    assert len(solo) == 1
    assert solo[0].members[0].segment_id == "d2"


def test_same_physical_page_is_required():
    align = _align_mod()
    # identical bbox + text, different physical pages -> never one group
    cands = [
        _cand("docling", [_seg("d1", 1, _A_DOCLING, "header", 0, technique="docling")]),
        _cand("pdfplumber", [_seg("p1", 2, _A_DOCLING, "header", 0)]),
    ]
    groups = align.align(cands)
    assert len(groups) == 2
    assert all(len(g.members) == 1 for g in groups)


def test_segment_id_is_not_the_join_key():
    align = _align_mod()
    # same region, *materially different* text -> different segment_ids; a segment_id
    # join would never pair them. Geometry must still group them (alignment != reconcile).
    cands = [
        _cand("docling", [_seg("docling-xyz", 1, _A_DOCLING, "Total: R$ 100", 0,
                               technique="docling")]),
        _cand("pdfplumber", [_seg("plumber-abc", 1, _A_PLUMBER, "Total: R$ 108", 0)]),
    ]
    groups = align.align(cands)
    assert len(groups) == 1
    assert len(groups[0].members) == 2
    assert {m.segment_id for m in groups[0].members} == {"docling-xyz", "plumber-abc"}


# --------------------------------------------------------------------------------------
# determinism / stability
# --------------------------------------------------------------------------------------


def _three_region_candidates():
    return [
        _cand("docling", [
            _seg("d1", 1, _A_DOCLING, "one", 0, technique="docling"),
            _seg("d2", 1, _B_DOCLING, "two", 1, technique="docling"),
        ]),
        _cand("pdfplumber", [
            _seg("p1", 1, _A_PLUMBER, "one", 0),
            _seg("p2", 1, _B_PLUMBER, "two", 1),
        ]),
        _cand("ocr:tesseract", [
            _seg("o1", 1, _A_OCR, "one", 0, origin="ocr", technique="ocr:tesseract",
                 ocr_conf=90.0),
        ]),
    ]


def test_alignment_is_stable_under_candidate_reordering():
    align = _align_mod()
    a, b, c = _three_region_candidates()
    assert _member_set(align.align([a, b, c])) == _member_set(align.align([c, a, b]))
    assert _member_set(align.align([a, b, c])) == _member_set(align.align([b, c, a]))


def test_alignment_is_deterministic_across_repeated_calls():
    align = _align_mod()
    cands = _three_region_candidates()
    first = align.align(cands)
    second = align.align(cands)
    assert [g.group_id for g in first] == [g.group_id for g in second]
    assert _member_set(first) == _member_set(second)


def test_alignment_is_stable_under_segment_reordering_within_a_candidate():
    align = _align_mod()
    s_top = _seg("d1", 1, _A_DOCLING, "one", 0, technique="docling")
    s_bot = _seg("d2", 1, _B_DOCLING, "two", 1, technique="docling")
    p_top = _seg("p1", 1, _A_PLUMBER, "one", 0)
    p_bot = _seg("p2", 1, _B_PLUMBER, "two", 1)
    forward = align.align([_cand("docling", [s_top, s_bot]),
                           _cand("pdfplumber", [p_top, p_bot])])
    reversed_ = align.align([_cand("docling", [s_bot, s_top]),
                             _cand("pdfplumber", [p_bot, p_top])])
    assert _member_set(forward) == _member_set(reversed_)


# --------------------------------------------------------------------------------------
# thresholds are deterministic module constants, keyword-injectable (M1)
# --------------------------------------------------------------------------------------


def test_iou_and_jaccard_thresholds_are_module_constants():
    align = _align_mod()
    assert isinstance(align.IOU_THRESHOLD, float)
    assert isinstance(align.JACCARD_TIEBREAK_THRESHOLD, float)


def test_iou_threshold_is_keyword_injectable():
    align = _align_mod()
    cands = [
        _cand("docling", [_seg("d1", 1, _A_DOCLING, "x", 0, technique="docling")]),
        _cand("pdfplumber", [_seg("p1", 1, _A_PLUMBER, "x", 0)]),
    ]
    # jittered boxes group at the default threshold ...
    assert len(align.align(cands)) == 1
    # ... and separate under a near-1.0 requirement
    strict = align.align(cands, iou_threshold=0.999)
    assert len(strict) == 2


# --------------------------------------------------------------------------------------
# no mutation / no transformation
# --------------------------------------------------------------------------------------


def test_alignment_never_mutates_or_normalises_candidate_text():
    align = _align_mod()
    raw = "ﬁrst  line­\nsecond “quote”"  # ligature, soft hyphen, smart quotes
    cands = [
        _cand("docling", [_seg("d1", 1, _A_DOCLING, raw, 0, technique="docling")]),
        _cand("pdfplumber", [_seg("p1", 1, _A_PLUMBER, raw, 0)]),
    ]
    groups = align.align(cands)
    for m in groups[0].members:
        assert m.text == raw  # byte/codepoint identical — no NFC, no collapse, no strip


def test_iou_helper_and_token_jaccard_helper_are_pure():
    align = _align_mod()
    assert align.iou(_A_DOCLING, _A_DOCLING) == 1.0
    assert align.iou(_A_DOCLING, _B_DOCLING) == 0.0
    assert align.token_jaccard("foo bar baz", "foo bar baz") == 1.0
    assert align.token_jaccard("foo bar", "baz qux") == 0.0


# --------------------------------------------------------------------------------------
# cross-technique coverage corroboration (§21a) — the coarse/fine duplication defect
# --------------------------------------------------------------------------------------
#
# One technique emits a coarse segment covering a region; another emits finer segments
# for the same content. IoU (coarse vs each fine) is below the threshold, so without a
# coverage rule all of them survive as single-member groups and the same source text is
# accepted twice. A coarse group is folded into the finer run ONLY when their comparison
# keys concatenate (single space, re-normalised) to the coarse comparison key.

# coarse region: one wide box; two finer boxes tile most of it, left then right.
# (each fine box's IoU against the coarse box stays < 0.5 so ordinary grouping leaves
# them as independent single-member groups — the exact defect shape.)
_COARSE = (100.0, 100.0, 400.0, 118.0)
_FINE_L = (105.0, 100.0, 240.0, 118.0)
_FINE_R = (250.0, 100.0, 395.0, 118.0)
_FINE_TEXT_L = "Cláusula 4ª"
_FINE_TEXT_R = "— do objeto"
_COARSE_TEXT = "Cláusula 4ª — do objeto"


def _coarse_fine_candidates(*, coarse_tech="pdfplumber", fine_tech="docling",
                            coarse_text=_COARSE_TEXT, fine_l=_FINE_TEXT_L,
                            fine_r=_FINE_TEXT_R):
    coarse = _cand(coarse_tech, [
        _seg("c1", 1, _COARSE, coarse_text, 0, technique=coarse_tech),
    ])
    fine = _cand(fine_tech, [
        _seg("f1", 1, _FINE_L, fine_l, 0, technique=fine_tech),
        _seg("f2", 1, _FINE_R, fine_r, 1, technique=fine_tech),
    ])
    return coarse, fine


def _accepted_texts(groups):
    """Every literal that would enter the CED once at fine granularity: one per group,
    corroborations contribute a technique, not a second accepted segment."""
    out = []
    for g in groups:
        out.append(g.members[0].text if len(g.members) == 1 else
                   tuple(m.text for m in g.members))
    return out


def test_coarse_segment_covered_by_finer_run_is_not_an_independent_group():
    align = _align_mod()
    groups = align.align(list(_coarse_fine_candidates()))
    # the coarse pdfplumber segment is gone as its own group; the two docling segments
    # remain, each carrying the coarse member as coverage evidence.
    assert _member_set(groups) == {
        frozenset({("docling", "f1")}),
        frozenset({("docling", "f2")}),
    }
    for g in groups:
        assert len(g.corroborations) == 1
        c = g.corroborations[0]
        assert c.technique == "pdfplumber" and c.segment_id == "c1"
        assert c.text == _COARSE_TEXT
        assert set(c.covers_group_ids) == {gg.group_id for gg in groups}
    # source text is represented exactly once, verbatim, at the finer granularity
    assert sorted(_accepted_texts(groups)) == sorted([_FINE_TEXT_L, _FINE_TEXT_R])


def test_coverage_requires_exact_comparison_key_concatenation():
    align = _align_mod()
    joined = f"{_FINE_TEXT_L} {_FINE_TEXT_R}"
    # coarse comparison key == finer keys joined by a single space -> covered
    covered = align.align(list(_coarse_fine_candidates(coarse_text=joined)))
    assert all(g.corroborations for g in covered) and len(covered) == 2
    # extra whitespace in the coarse literal is comparison-only noise -> still covered
    spaced = f"  {_FINE_TEXT_L}   {_FINE_TEXT_R}  "
    noisy = align.align(list(_coarse_fine_candidates(coarse_text=spaced)))
    assert all(g.corroborations for g in noisy) and len(noisy) == 2


def test_coverage_works_in_the_reverse_technique_arrangement():
    align = _align_mod()
    groups = align.align(list(
        _coarse_fine_candidates(coarse_tech="docling", fine_tech="pdfplumber")
    ))
    assert _member_set(groups) == {
        frozenset({("pdfplumber", "f1")}),
        frozenset({("pdfplumber", "f2")}),
    }
    assert {g.corroborations[0].technique for g in groups} == {"docling"}


def test_geometric_containment_without_text_match_stays_separate():
    align = _align_mod()
    groups = align.align(list(
        _coarse_fine_candidates(coarse_text="a completely unrelated heading string")
    ))
    # coarse survives as its own group; no corroboration is recorded anywhere
    assert _member_set(groups) == {
        frozenset({("pdfplumber", "c1")}),
        frozenset({("docling", "f1")}),
        frozenset({("docling", "f2")}),
    }
    assert all(not g.corroborations for g in groups)


def test_partial_textual_overlap_stays_separate():
    align = _align_mod()
    groups = align.align(list(
        _coarse_fine_candidates(coarse_text=f"{_COARSE_TEXT} e das obrigações")
    ))
    assert len(groups) == 3
    assert all(not g.corroborations for g in groups)


def test_coverage_never_removes_content_the_finer_run_does_not_reproduce():
    align = _align_mod()
    # the finer run is missing a trailing token that only the coarse segment carries
    groups = align.align(list(_coarse_fine_candidates(
        coarse_text=f"{_COARSE_TEXT} e das obrigações", fine_r=_FINE_TEXT_R,
    )))
    all_text = " ".join(sorted(str(t) for t in _accepted_texts(groups)))
    assert "e das obrigações" in all_text  # unique coarse content is still present
    assert any(g.members[0].text == f"{_COARSE_TEXT} e das obrigações"
               for g in groups if len(g.members) == 1)


def test_non_contiguous_finer_segments_are_not_treated_as_coverage():
    align = _align_mod()
    # a docling segment sits (in reading order) between the two covered ones but lies
    # OUTSIDE the coarse box -> the contained indices are not contiguous
    coarse, _ = _coarse_fine_candidates()
    fine = _cand("docling", [
        _seg("f1", 1, _FINE_L, _FINE_TEXT_L, 0, technique="docling"),
        _seg("mid", 1, (100.0, 400.0, 400.0, 418.0), "far below", 1, technique="docling"),
        _seg("f2", 1, _FINE_R, _FINE_TEXT_R, 2, technique="docling"),
    ])
    groups = align.align([coarse, fine])
    assert any(len(g.members) == 1 and g.members[0].segment_id == "c1" for g in groups)
    assert all(not g.corroborations for g in groups)


def test_coverage_is_deterministic_under_candidate_and_segment_reordering():
    align = _align_mod()
    coarse, fine = _coarse_fine_candidates()
    fine_rev = _cand("docling", [
        _seg("f2", 1, _FINE_R, _FINE_TEXT_R, 1, technique="docling"),
        _seg("f1", 1, _FINE_L, _FINE_TEXT_L, 0, technique="docling"),
    ])
    a = align.align([coarse, fine])
    b = align.align([fine, coarse])
    c = align.align([fine_rev, coarse])
    assert _member_set(a) == _member_set(b) == _member_set(c)
    assert [g.group_id for g in a] == [g.group_id for g in b] == [g.group_id for g in c]
    for g in a:
        assert g.corroborations and g.corroborations[0].segment_id == "c1"


def test_a_one_to_one_same_region_pair_is_left_to_ordinary_iou_grouping():
    align = _align_mod()
    # a single finer segment equal to the coarse one is NOT a coverage relationship
    coarse = _cand("pdfplumber", [_seg("c1", 1, _COARSE, _COARSE_TEXT, 0)])
    fine = _cand("docling", [_seg("f1", 1, _COARSE, _COARSE_TEXT, 0, technique="docling")])
    groups = align.align([coarse, fine])
    # identical bbox + text -> ordinary IoU makes one two-member group, no corroboration
    assert len(groups) == 1
    assert {m.technique for m in groups[0].members} == {"pdfplumber", "docling"}
    assert not groups[0].corroborations
