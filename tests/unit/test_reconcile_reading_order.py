"""T055 — failing-first tests for reading-order reconciliation.

Split ownership:

* **T058** (``src/solari_converter/reconcile/reading_order.py``) owns candidate-order
  construction, the deterministic geometric resolver (column detection + baseline
  order), Kendall-τ disagreement detection, and the explicit conflict descriptor —
  these tests turn **GREEN** in Block 1.
* **T059** (``src/solari_converter/reconcile/llm_select.py``) owns the ≥ 0.75 → LLM
  order-selection path, the post-LLM guard, and < 0.75 → reading-order
  HUMAN_REVIEW_REQUIRED. Those live in ``class TestFutureOwnerT059`` and stay **RED**.

Frozen references: research §21a / §21c / §21d, data-model.md (reading-order decision
+ geometry candidate), SC-022, the block brief §8.
"""

from __future__ import annotations

import pytest


def _ro():
    import solari_converter.reconcile.reading_order as reading_order  # GREEN owner: T058

    return reading_order


def _align():
    import solari_converter.reconcile.align as align  # GREEN owner: T056

    return align


# --------------------------------------------------------------------------------------
# builders — aligned groups with explicit geometry + per-technique order
# --------------------------------------------------------------------------------------


def _member(align, technique, sid, idx):
    from solari_converter.model.provenance import SourceRef

    return align.AlignedMember(
        technique=technique,
        segment_id=sid,
        text=f"text-{sid}",
        source=SourceRef(
            physical_page=1,
            bbox=(0.0, 0.0, 1.0, 1.0),
            origin_kind="native_text" if not technique.startswith("ocr") else "ocr",
            extraction_technique=technique,
            ocr_confidence=None if not technique.startswith("ocr") else 80.0,
        ),
        reading_order_index=idx,
    )


def _grp(align, gid, bbox, members):
    return align.AlignedSegmentGroup(
        group_id=gid, physical_page=1, region_bbox=bbox, members=tuple(members)
    )


def _linear_page(align, orders):
    """One column, three stacked regions g1/g2/g3 (top-left origin: smaller y = higher).

    ``orders`` maps technique -> the reading_order_index it assigns to (g1, g2, g3).
    """
    boxes = {
        "g1": (100.0, 100.0, 400.0, 130.0),
        "g2": (100.0, 200.0, 400.0, 230.0),
        "g3": (100.0, 300.0, 400.0, 330.0),
    }
    groups = []
    for gid in ("g1", "g2", "g3"):
        members = [
            _member(align, tech, f"{tech}-{gid}", idxs[("g1", "g2", "g3").index(gid)])
            for tech, idxs in orders.items()
        ]
        groups.append(_grp(align, gid, boxes[gid], members))
    return groups


def _two_column_page(align):
    """Left column L1/L2 (x≈100), right column R1/R2 (x≈400); wide inter-column gap.

    Correct reading order: L1, L2, R1, R2. Each region carries a member of a different
    technique, so no single technique produces a full-permutation candidate order and
    the geometric resolver is the only signal.
    """
    boxes = {
        "L1": (100.0, 100.0, 250.0, 130.0),
        "L2": (100.0, 200.0, 250.0, 230.0),
        "R1": (400.0, 100.0, 550.0, 130.0),
        "R2": (400.0, 200.0, 550.0, 230.0),
    }
    techs = ["docling", "pdfplumber", "ocr:tesseract"]
    groups = []
    for i, gid in enumerate(boxes):
        groups.append(_grp(align, gid, boxes[gid],
                           [_member(align, techs[i % len(techs)], f"m-{gid}", 0)]))
    return groups


# --------------------------------------------------------------------------------------
# candidate-order construction
# --------------------------------------------------------------------------------------


def test_build_candidate_orders_projects_each_technique_onto_the_group_ids():
    ro, align = _ro(), _align()
    groups = _linear_page(align, {
        "docling": (0, 1, 2),
        "pdfplumber": (0, 1, 2),
        "ocr:tesseract": (2, 0, 1),
    })
    orders = ro.build_candidate_orders(groups)
    assert orders["docling"] == ["g1", "g2", "g3"]
    # ocr assigns index 2->g1, 0->g2, 1->g3  =>  sorted by index: g2, g3, g1
    assert orders["ocr:tesseract"] == ["g2", "g3", "g1"]


# --------------------------------------------------------------------------------------
# deterministic agreement paths
# --------------------------------------------------------------------------------------


def test_candidate_orders_agree_yields_deterministic_agreement():
    ro, align = _ro(), _align()
    groups = _linear_page(align, {
        "docling": (0, 1, 2),
        "pdfplumber": (0, 1, 2),
        "ocr:tesseract": (0, 1, 2),
    })
    res = ro.resolve_reading_order(groups)
    assert isinstance(res, ro.ReadingOrderResolution)
    assert res.method == "deterministic_agreement"
    assert res.source == "candidate_agreement"
    assert list(res.order) == ["g1", "g2", "g3"]


def test_geometry_resolves_a_two_column_page_unambiguously():
    ro, align = _ro(), _align()
    groups = _two_column_page(align)
    geo = ro.geometric_order(groups)
    assert geo == ["L1", "L2", "R1", "R2"]
    res = ro.resolve_reading_order(groups)
    assert isinstance(res, ro.ReadingOrderResolution)
    assert res.method == "deterministic_agreement"
    assert res.source == "geometry"
    assert list(res.order) == ["L1", "L2", "R1", "R2"]


def test_geometry_breaks_a_pure_candidate_disagreement_when_unambiguous():
    ro, align = _ro(), _align()
    # single column, geometry unambiguous; two candidates flatly disagree
    groups = _linear_page(align, {
        "docling": (0, 1, 2),
        "ocr:tesseract": (2, 1, 0),
    })
    res = ro.resolve_reading_order(groups)
    assert isinstance(res, ro.ReadingOrderResolution)
    assert res.source == "geometry"
    assert list(res.order) == ["g1", "g2", "g3"]


# --------------------------------------------------------------------------------------
# permutation invariant
# --------------------------------------------------------------------------------------


def test_resolution_order_is_a_full_permutation_of_the_scope_ids():
    ro, align = _ro(), _align()
    groups = _linear_page(align, {"docling": (0, 1, 2), "pdfplumber": (0, 1, 2)})
    res = ro.resolve_reading_order(groups)
    order = list(res.order)
    assert sorted(order) == ["g1", "g2", "g3"]
    assert len(order) == len(set(order)) == 3


def test_geometric_order_is_a_full_permutation_or_none_never_partial():
    ro, align = _ro(), _align()
    groups = _two_column_page(align)
    geo = ro.geometric_order(groups)
    assert geo is None or sorted(geo) == sorted(g.group_id for g in groups)


# --------------------------------------------------------------------------------------
# Kendall-τ
# --------------------------------------------------------------------------------------


def test_kendall_tau_distance_bounds():
    ro = _ro()
    assert ro.kendall_tau_distance(["a", "b", "c"], ["a", "b", "c"]) == 0.0
    assert ro.kendall_tau_distance(["a", "b", "c"], ["c", "b", "a"]) == pytest.approx(1.0)
    assert ro.kendall_tau_distance(["a", "b", "c"], ["b", "a", "c"]) == pytest.approx(1 / 3)


def test_kendall_threshold_is_a_module_constant_and_keyword_injectable():
    ro, align = _ro(), _align()
    assert isinstance(ro.KENDALL_TAU_DISAGREEMENT_THRESHOLD, float)
    groups = _ambiguous_disagreeing_page(ro, align)
    # a threshold of 1.1 can never be exceeded -> no "material" disagreement is declared,
    # but ambiguous geometry still can't produce an order -> still a conflict, deterministically
    res = ro.resolve_reading_order(groups, kendall_threshold=1.1)
    assert isinstance(res, ro.ReadingOrderConflict)


# --------------------------------------------------------------------------------------
# ambiguity -> explicit conflict, never an invented order
# --------------------------------------------------------------------------------------


def _ambiguous_disagreeing_page(ro, align):
    """Two regions sharing the same bbox (geometry cannot order them) with two
    full-permutation candidate orders that disagree."""
    bbox = (100.0, 100.0, 400.0, 140.0)
    g_a = _grp(align, "a", bbox, [
        _member(align, "docling", "d-a", 0), _member(align, "ocr:tesseract", "o-a", 1)
    ])
    g_b = _grp(align, "b", bbox, [
        _member(align, "docling", "d-b", 1), _member(align, "ocr:tesseract", "o-b", 0)
    ])
    return [g_a, g_b]


def test_ambiguous_geometry_plus_disagreement_returns_a_conflict_descriptor():
    ro, align = _ro(), _align()
    res = ro.resolve_reading_order(_ambiguous_disagreeing_page(ro, align))
    assert isinstance(res, ro.ReadingOrderConflict)
    assert res.geometry_order is None
    assert set(res.scope_ids) == {"a", "b"}
    assert res.max_pairwise_kendall_tau_distance == pytest.approx(1.0)


def test_conflict_is_returned_not_a_silent_fallback_ordering():
    ro, align = _ro(), _align()
    res = ro.resolve_reading_order(_ambiguous_disagreeing_page(ro, align))
    # must NOT be a list / order — no candidate-iteration, segment_id-sort, or
    # alphabetical fallback
    assert not isinstance(res, (list, tuple))
    assert isinstance(res, ro.ReadingOrderConflict)


def test_geometric_order_returns_none_for_geometrically_identical_regions():
    ro, align = _ro(), _align()
    bbox = (10.0, 10.0, 90.0, 40.0)
    groups = [
        _grp(align, "x", bbox, [_member(align, "docling", "d-x", 0)]),
        _grp(align, "y", bbox, [_member(align, "docling", "d-y", 1)]),
    ]
    assert ro.geometric_order(groups) is None


# --------------------------------------------------------------------------------------
# determinism / SC-022 (literal text untouched)
# --------------------------------------------------------------------------------------


def test_resolution_is_deterministic_across_calls_and_input_order():
    ro, align = _ro(), _align()
    groups = _two_column_page(align)
    a = ro.resolve_reading_order(groups)
    b = ro.resolve_reading_order(list(reversed(groups)))
    assert list(a.order) == list(b.order)


def test_reading_order_never_rewrites_or_resegments_literal_text():
    ro, align = _ro(), _align()
    groups = _linear_page(align, {"docling": (0, 1, 2), "pdfplumber": (0, 1, 2)})
    before = [[m.text for m in g.members] for g in groups]
    res = ro.resolve_reading_order(groups)
    after = [[m.text for m in g.members] for g in groups]
    assert before == after
    # the resolution carries ids only — no literal text
    assert all(isinstance(x, str) for x in res.order)
    assert all(x.startswith("g") for x in res.order)


# --------------------------------------------------------------------------------------
# T059 — LLM order selection + guard + below-threshold review. RED until Block >= 2.
# --------------------------------------------------------------------------------------


class TestFutureOwnerT059:
    """GREEN owner: **T059** — ``reconcile/llm_select.py`` (NOT in Block 1).

    Block 1 deliberately does not create ``reconcile/llm_select.py``; every test here
    fails at import until T059 lands. They pin: ≥ 0.75 → the LLM selects an **existing**
    candidate/geometry order; the guard rejects an order that is neither; < 0.75 →
    reading-order HUMAN_REVIEW_REQUIRED carrying ``segment_ids`` (research §21c/§21d).
    """

    def _llm_select(self):
        import solari_converter.reconcile.llm_select as llm_select  # GREEN owner: T059

        return llm_select

    def test_at_or_above_threshold_llm_selects_an_existing_order(self):
        self._llm_select()
        raise AssertionError("T059: selection-only order path not built yet")

    def test_guard_rejects_an_order_that_is_neither_candidate_nor_geometry(self):
        self._llm_select()
        raise AssertionError("T059: post-LLM order guard not built yet")

    def test_below_threshold_reading_order_conflict_requires_human_review(self):
        self._llm_select()
        raise AssertionError("T059: < 0.75 reading-order HUMAN_REVIEW_REQUIRED not built yet")
