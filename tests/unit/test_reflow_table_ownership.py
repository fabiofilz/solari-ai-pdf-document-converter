"""S2 remediation (R5) — table-before-reflow ownership boundary.

GREEN owner: **S2 remediation** (``transform/reflow.py`` ``excluded_segment_ids`` +
``transform/tables.py`` additive ``build_tables(ced)``).

Pins the frozen Stage-3 orchestration order (post-T070 audit, Part B): table
ownership is determined **before** non-table reflow —

    tables = build_tables(ced)
    non_table = reflow(ced, excluded_segment_ids=tables.consumed_segment_ids)

so a hint-less segment absorbed into a table by geometry (T070) can never also be
half-owned by a reflowed prose unit (the "partial ReflowUnit" hazard). This module
does **not** implement T073 — it only proves the two additive APIs compose safely.
"""

from __future__ import annotations

import solari_converter.transform.reflow as reflow
import solari_converter.transform.tables as tables

from ._semantic_fixtures import Seg, ced


def _cell(sid, text, x0, top, *, page=1, w=80.0, h=12.0, hint=True):
    return Seg(
        sid, text, (x0, top, x0 + w, top + h), page=page,
        hints=[("table_cell", None, "pdfplumber")] if hint else [],
    )


# --------------------------------------------------------------------------------------
# build_tables can run standalone, before reflow
# --------------------------------------------------------------------------------------


def test_build_tables_runs_without_a_reflow_result():
    doc = ced([
        _cell("h0", "Item", 72, 100), _cell("h1", "Qty", 162, 100),
        _cell("a0", "Widget", 72, 114), _cell("a1", "3", 162, 114),
    ])
    result = tables.build_tables(doc)  # no reflow_result argument at all
    assert {b.kind for b in result.blocks} == {"table"}
    assert result.consumed_segment_ids == {"h0", "h1", "a0", "a1"}


def test_build_tables_still_accepts_a_reflow_result_for_backward_compatibility():
    doc = ced([
        _cell("h0", "Item", 72, 100), _cell("h1", "Qty", 162, 100),
        _cell("a0", "Widget", 72, 114), _cell("a1", "3", 162, 114),
    ])
    a = tables.build_tables(doc)
    b = tables.build_tables(doc, reflow.reflow(doc))
    assert a.consumed_segment_ids == b.consumed_segment_ids
    assert [t.table.table_id for blk in (a, b) for t in [blk.blocks[0]]][0] == \
        [t.table.table_id for blk in (a, b) for t in [blk.blocks[0]]][1]


# --------------------------------------------------------------------------------------
# reflow() default behaviour is unchanged
# --------------------------------------------------------------------------------------


def test_reflow_with_no_exclusions_matches_the_prior_signature_exactly():
    doc = ced([
        Seg("a", "This is a single logical paragraph that has been hard", (72, 100, 452, 112)),
        Seg("b", "wrapped across several visual lines of the same block.", (72, 114, 452, 126)),
    ])
    default = reflow.reflow(doc)
    explicit_empty = reflow.reflow(doc, excluded_segment_ids=frozenset())
    assert default.units == explicit_empty.units
    assert default.transforms == explicit_empty.transforms


# --------------------------------------------------------------------------------------
# excluded segments never appear, and are a hard boundary — not a splice point
# --------------------------------------------------------------------------------------


def test_excluded_segment_never_appears_in_any_unit_or_transform():
    doc = ced([
        Seg("a", "First line of a paragraph that keeps", (72, 100, 452, 112)),
        Seg("b", "going for a couple more visual lines", (72, 114, 452, 126)),
        Seg("c", "before it finally wraps to a close.", (72, 128, 452, 140)),
    ])
    result = reflow.reflow(doc, excluded_segment_ids=frozenset({"b"}))
    all_ids = {sid for u in result.units for sid in u.segment_ids}
    assert "b" not in all_ids
    assert all("b" not in tr.segment_ids for tr in result.transforms)


def test_excluded_segment_is_a_hard_boundary_not_a_splice_point():
    # Without "b", "a" and "c" sit at the same indent with a gap comfortably inside
    # PARAGRAPH_BREAK_GAP_RATIO — they would wrap-join if adjacent. "b" must not be
    # silently spliced out to let them merge across it.
    doc = ced([
        Seg("a", "First line of a paragraph that keeps", (72, 100, 452, 112)),
        Seg("b", "a table-owned line sitting between them", (72, 114, 452, 126)),
        Seg("c", "continuing at the same left margin below.", (72, 128, 452, 140)),
    ])
    baseline = reflow.reflow(doc)  # sanity: a+c WOULD join if b were simply absent
    assert len(baseline.units) == 1

    result = reflow.reflow(doc, excluded_segment_ids=frozenset({"b"}))
    unit_ids = [u.segment_ids for u in result.units]
    assert ("a", "c") not in unit_ids
    assert not any(set(ids) == {"a", "c"} for ids in unit_ids)
    assert ("a",) in unit_ids
    assert ("c",) in unit_ids


def test_source_order_equals_accepted_order_minus_excluded_ids():
    doc = ced([
        Seg("a", "Alpha paragraph.", (72, 100, 300, 112)),
        Seg("b", "Bravo paragraph.", (72, 130, 300, 142)),
        Seg("c", "Charlie paragraph.", (72, 160, 300, 172)),
    ])
    result = reflow.reflow(doc, excluded_segment_ids=frozenset({"b"}))
    assert result.source_order() == ["a", "c"]

    unfiltered = reflow.reflow(doc)
    assert unfiltered.source_order() == list(doc.accepted_reading_order)


def test_ced_wide_dehyphenation_evidence_is_unaffected_by_exclusion():
    # The §27 positive-evidence token index stays CED-wide: the attesting segment may
    # itself be excluded from reflow units without invalidating the evidence it offers.
    doc = ced([
        Seg("attest", "The company operates internationally across many regions.",
            (72, 400, 452, 412)),
        Seg("l", "The firm operates inter-", (72, 100, 452, 112)),
        Seg("r", "nationally across many regions.", (72, 114, 452, 126)),
    ])
    unfiltered = reflow.reflow(doc)
    dehyph = [t for t in unfiltered.transforms if t.kind == "dehyphenate"]
    assert dehyph  # positive evidence found via "attest"

    excluding_attester = reflow.reflow(doc, excluded_segment_ids=frozenset({"attest"}))
    dehyph2 = [t for t in excluding_attester.transforms if t.kind == "dehyphenate"]
    assert dehyph2  # "attest" need not be IN a unit to attest the joined token


# --------------------------------------------------------------------------------------
# cross-boundary: table ownership determined before, and consumed by, reflow
# --------------------------------------------------------------------------------------


def _partial_unit_fixture():
    return ced([
        Seg("p", "Prose line above the table", (72, 84, 300, 96)),
        _cell("h0", "Item", 72, 100, hint=False),  # hint-less: absorbed by geometry
        _cell("h1", "Qty", 162, 100),
        _cell("c0", "Widget", 72, 114), _cell("c1", "3", 162, 114),
        _cell("d0", "Gadget", 72, 128), _cell("d1", "1", 162, 128),
        Seg("q", "Prose line below", (72, 146, 300, 158)),
    ])


def test_partial_reflow_unit_ownership_hazard_is_reproduced_unfiltered():
    doc = _partial_unit_fixture()
    unfiltered = reflow.reflow(doc)
    assert ("p", "h0") in [u.segment_ids for u in unfiltered.units]


def test_table_ownership_before_reflow_closes_the_partial_unit_hazard():
    doc = _partial_unit_fixture()

    result = tables.build_tables(doc)
    assert {"h0", "h1", "c0", "c1", "d0", "d1"} <= result.consumed_segment_ids

    non_table = reflow.reflow(doc, excluded_segment_ids=result.consumed_segment_ids)
    unit_ids = [u.segment_ids for u in non_table.units]

    # the table-owned hint-less cell never leaks into a reflow unit
    assert not any("h0" in ids for ids in unit_ids)
    assert not any(set(ids) & result.consumed_segment_ids for ids in unit_ids)
    # p and q are preserved and are NOT joined across the excluded table content
    assert ("p",) in unit_ids
    assert ("q",) in unit_ids
    assert not any(set(ids) == {"p", "q"} for ids in unit_ids)


def test_table_and_non_table_ownership_partition_the_accepted_segments():
    doc = _partial_unit_fixture()
    result = tables.build_tables(doc)
    non_table = reflow.reflow(doc, excluded_segment_ids=result.consumed_segment_ids)

    table_ids = result.consumed_segment_ids
    non_table_ids = set(non_table.source_order())

    assert table_ids & non_table_ids == set()
    assert table_ids | non_table_ids == set(doc.accepted_reading_order)


def test_ownership_partition_holds_for_a_stitched_table_with_collapsed_header():
    def grid(rows, page, top0):
        return [
            _cell(f"p{page}r{r}c{c}", v, 72 + 90 * c, top0 + 14 * r, page=page)
            for r, row in enumerate(rows) for c, v in enumerate(row)
        ]

    doc = ced(
        [Seg("intro", "Statement follows.", (72, 60, 300, 72), page=1)]
        + grid([["Date", "Amount"], ["2026-01-01", "100.00"]], 1, 100)
        + grid([["Date", "Amount"], ["2026-02-01", "200.00"]], 2, 60)
        + [Seg("outro", "End of statement.", (72, 100, 300, 112), page=2)]
    )
    result = tables.build_tables(doc)
    non_table = reflow.reflow(doc, excluded_segment_ids=result.consumed_segment_ids)

    table_ids = result.consumed_segment_ids
    non_table_ids = set(non_table.source_order())

    # the collapsed continuation header stays inside table ownership (CollapsedHeader
    # lineage), never resurfacing as a non-table reflow unit
    assert result.collapsed_headers
    collapsed_ids = {s for ch in result.collapsed_headers for s in ch.segment_ids}
    assert collapsed_ids <= table_ids
    assert collapsed_ids.isdisjoint(non_table_ids)

    assert table_ids & non_table_ids == set()
    assert table_ids | non_table_ids == set(doc.accepted_reading_order)
    assert "intro" in non_table_ids and "outro" in non_table_ids
