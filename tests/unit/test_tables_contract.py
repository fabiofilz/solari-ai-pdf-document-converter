"""T070 [US1] — the closed table-reconstruction contract (``transform/tables.py``).

Failing-first companion to the four scenario tests in ``test_tables.py``. Covers the
audited T070 policy: conservative hint-gated detection, deterministic row/column
clustering, atomic (never-split) segments, verbatim numeric fidelity, geometry-only
merged spans, the conservative multi-page stitch predicate, single repeated-header
collapse with lineage, table-scoped structural reorder, and deterministic identities.

GREEN owner: **T070**. These must be RED (module absent) before ``tables.py`` lands.
"""

from __future__ import annotations

import pytest

from ._semantic_fixtures import Seg, ced


def _tables():
    import solari_converter.transform.tables as tables

    return tables


def _reflow(doc):
    import solari_converter.transform.reflow as reflow

    return reflow.reflow(doc)


# --- fixture builders --------------------------------------------------------------

_COLW = 90.0
_CELLW = 80.0
_X0 = 72.0
_H = 12.0
_DY = 20.0  # row pitch: comfortably wider than a wrapped-line step (~cell height)


def tcell(sid, text, col, top, *, page=1, w=_CELLW, x0=None):
    x = _X0 + _COLW * col if x0 is None else x0
    return Seg(sid, text, (x, top, x + w, top + _H), page=page,
               hints=[("table_cell", None, "pdfplumber")])


def tgrid(rows, *, page=1, top0=100.0, dy=_DY):
    segs = []
    for r, cells in enumerate(rows):
        for c, val in enumerate(cells):
            if val is None:
                continue
            segs.append(tcell(f"p{page}r{r}c{c}", val, c, top0 + dy * r, page=page))
    return segs


def build(segs, *, order=None):
    doc = ced(segs, order=order)
    return _tables().build_tables(doc, _reflow(doc)), doc


def only_table(result):
    tables = [b for b in result.blocks if b.kind == "table"]
    assert len(tables) == 1, f"expected exactly one table, got {len(tables)}"
    return tables[0].table


# --- detection policy ------------------------------------------------------------


def test_basic_table_reconstruction():
    result, _ = build(tgrid([["H1", "H2"], ["a", "b"], ["c", "d"]]))
    t = only_table(result)
    assert [ [c.text for c in row] for row in t.rows ] == [
        ["H1", "H2"], ["a", "b"], ["c", "d"]
    ]
    assert t.header_row_count == 1
    assert t.spans_pages == [1]
    assert not t.has_merged_cells


def test_deterministic_rows_and_columns():
    result, _ = build(tgrid([["A", "B", "C"], ["1", "2", "3"], ["4", "5", "6"]]))
    t = only_table(result)
    assert len(t.rows) == 3
    assert all(len(r) == 3 for r in t.rows)
    assert [c.column for c in t.rows[0]] == [0, 1, 2]


def test_hintless_grid_remains_prose():
    # visually regular 2-col / 3-row block, no table hints anywhere
    segs = []
    for r in range(3):
        for c in range(2):
            x = _X0 + _COLW * c
            segs.append(Seg(f"n{r}{c}", f"v{r}{c}", (x, 100 + 14 * r, x + 60, 112 + 14 * r)))
    result, _ = build(segs)
    assert not any(b.kind == "table" for b in result.blocks)
    assert result.consumed_segment_ids == frozenset()


def test_hinted_region_without_column_evidence_stays_prose():
    # one coarse whole-row literal per line: a table hint but no per-column grid
    segs = [
        Seg("r0", "Region Total", (72, 100, 452, 112), hints=[("table_row", None, "pdfplumber")]),
        Seg("r1", "North 10", (72, 116, 452, 128), hints=[("table_row", None, "pdfplumber")]),
        Seg("r2", "South 20", (72, 132, 452, 144), hints=[("table_row", None, "pdfplumber")]),
    ]
    result, _ = build(segs)
    assert not any(b.kind == "table" for b in result.blocks)
    assert result.consumed_segment_ids == frozenset()
    assert any(not d.applied for d in result.hint_decisions)
    assert any("column" in d.reason for d in result.hint_decisions if not d.applied)
    assert any(a.kind == "single_column_region_skipped" for a in result.ambiguities)
    # no literal was split
    assert not any(
        c.text in {"Region", "Total"} for b in result.blocks if b.kind == "table"
        for row in b.table.rows for c in row
    )


def test_geometry_included_hintless_cell_is_absorbed():
    # hinted grid H1/H2 then a hinted "a" at c0 — the c1 value on that row is hint-less
    # but lands squarely inside the hinted fragment bbox and column-aligns.
    segs = [
        tcell("h0", "H1", 0, 100), tcell("h1", "H2", 1, 100),
        tcell("a", "a", 0, 120),
        Seg("bfill", "b", (_X0 + _COLW, 120, _X0 + _COLW + _CELLW, 132)),
    ]
    result, _ = build(segs)
    t = only_table(result)
    assert t.rows[1][1].text == "b"
    assert "bfill" in result.consumed_segment_ids


# --- grid: empty / wrapped cells -------------------------------------------------


def test_empty_cell_is_an_empty_table_cell_with_no_provenance():
    result, _ = build(tgrid([["A", "B"], ["1", None], ["2", "3"]]))
    t = only_table(result)
    empty = t.rows[1][1]
    assert empty.text == ""
    assert empty.provenance == ()
    assert empty.source_segment_ids == ()


def test_multiple_segment_wrapped_cell_is_joined_verbatim():
    segs = tgrid([["Desc", "Amt"], ["line one", "9.99"]])  # rows at top 100, 120
    # a lone continuation line ~one text line below the c0 data cell (offset 12 << pitch 20)
    segs.append(Seg("wrap", "line two", (_X0, 132, _X0 + _CELLW, 144),
                    hints=[("table_cell", None, "pdfplumber")]))
    result, _ = build(segs)
    t = only_table(result)
    assert [c.text for c in t.rows[1]] == ["line one line two", "9.99"]
    assert set(t.rows[1][0].provenance) == {"p1r1c0", "wrap"}
    joins = [tr for tr in result.transforms if tr.kind == "reflow_whitespace"]
    assert joins and "wrap" in joins[0].segment_ids


def test_wrapped_cell_uncertain_is_not_merged():
    segs = tgrid([["Desc", "Amt"], ["line one", "9.99"]])  # rows at top 100, 120
    # same column, but ~0.8 of a row pitch below: ambiguous — keep separate, record it
    segs.append(Seg("maybe", "later text", (_X0, 136, _X0 + _CELLW, 148),
                    hints=[("table_cell", None, "pdfplumber")]))
    result, _ = build(segs)
    t = only_table(result)
    assert len(t.rows) == 3
    assert any(a.kind == "wrapped_cell_uncertain" for a in result.ambiguities)
    assert not any(
        tr.kind == "reflow_whitespace" and "maybe" in tr.segment_ids
        for tr in result.transforms
    )


# --- fidelity ------------------------------------------------------------------


@pytest.mark.parametrize(
    "value",
    [
        "1.234,56", "R$ 1.000,00", "007", "12,5%", "31/12/2025",
        "Lei nº 8.245/91", "-3,2", "(1.000)", "1.5e-3", "5 000", "$ 5.00",
    ],
)
def test_numeric_and_literal_fidelity_is_byte_exact(value):
    result, _ = build(tgrid([["Label", "Value"], ["row", value]]))
    t = only_table(result)
    assert t.rows[1][1].text == value


def test_table_literal_fidelity_across_a_whole_grid():
    rows = [["Nº", "Base"], ["1", "R$ 1.234,56"], ["2", "0,00%"]]
    result, doc = build(tgrid(rows))
    t = only_table(result)
    got = [[c.text for c in row] for row in t.rows]
    assert got == rows
    # every stored literal equals some accepted segment's verbatim text
    literals = {s.text for s in doc.accepted_segments}
    assert all(
        c.text in literals for row in t.rows for c in row if c.text
    )


# --- merged cells ------------------------------------------------------------


def test_colspan_is_inferred_only_from_supporting_geometry():
    segs = [
        Seg("h", "spans both", (72, 100, 252, 112), page=1,
            hints=[("table_cell", None, "pdfplumber")]),
        tcell("a", "left", 0, 116),
        tcell("b", "right", 1, 116),
    ]
    result, _ = build(segs)
    t = only_table(result)
    assert t.has_merged_cells
    anchor = t.rows[0][0]
    assert anchor.colspan == 2 and anchor.rowspan == 1
    assert len(t.rows[0]) == 1  # covered position not duplicated


def test_rowspan_is_inferred_where_row_geometry_supports_it():
    segs = [
        Seg("cat", "category", (72, 100, 152, 128), page=1,
            hints=[("table_cell", None, "pdfplumber")]),
        tcell("x1", "one", 1, 100),
        tcell("x2", "two", 1, 114),
    ]
    result, _ = build(segs)
    t = only_table(result)
    assert t.has_merged_cells
    assert t.rows[0][0].rowspan == 2
    assert set(t.rows[0][0].provenance) == {"cat"}
    # the covered position on row 1 is not a duplicated copy of the literal
    assert all(c.text != "category" for c in t.rows[1])


def test_uncertain_span_falls_back_to_one_and_records_ambiguity():
    segs = [
        # overlaps c0 fully, c1 only slightly (~0.3) -> ambiguous, span 1
        Seg("w", "wide-ish", (72, 100, 200, 112), page=1,
            hints=[("table_cell", None, "pdfplumber")]),
        tcell("a", "A", 0, 116),
        tcell("bb", "B", 1, 116),
        tcell("c2", "C", 0, 130),
        tcell("d2", "D", 1, 130),
    ]
    result, _ = build(segs)
    t = only_table(result)
    assert all(c.colspan == 1 for row in t.rows for c in row)
    assert any(a.kind == "span_uncertain" for a in result.ambiguities)


# --- stitching -------------------------------------------------------------


def _page_grid(page, header, datarow, *, top0=60.0):
    return tgrid([header, datarow], page=page, top0=top0)


def test_three_page_stitch_becomes_one_logical_table():
    segs = (
        _page_grid(1, ["K", "V"], ["a1", "n1"])
        + _page_grid(2, ["K", "V"], ["a2", "n2"])
        + _page_grid(3, ["K", "V"], ["a3", "n3"])
    )
    result, _ = build(segs)
    t = only_table(result)
    assert t.spans_pages == [1, 2, 3]
    assert t.header_row_count == 1
    assert sum(1 for row in t.rows if row[0].text == "K") == 1
    assert [[c.text for c in row] for row in t.rows] == [
        ["K", "V"], ["a1", "n1"], ["a2", "n2"], ["a3", "n3"]
    ]
    assert len(result.stitch_records) == 2
    assert len(result.collapsed_headers) == 2
    # stable id across an equivalent rebuild
    result2, _ = build(list(reversed(segs)), order=[s.sid for s in segs])
    assert only_table(result2).table_id == t.table_id


def test_direct_continuation_without_repeated_header_still_stitches():
    segs = (
        tgrid([["H", "J"], ["a", "b"]], page=1, top0=60.0)
        + tgrid([["c", "d"], ["e", "f"]], page=2, top0=60.0)
    )
    result, _ = build(segs)
    t = only_table(result)
    assert t.spans_pages == [1, 2]
    assert len(result.stitch_records) == 1
    assert result.stitch_records[0].signal == "direct_continuation"


def test_incompatible_column_signatures_stay_separate_tables():
    segs = (
        tgrid([["A", "B"], ["1", "2"]], page=1, top0=60.0)
        + tgrid([["A", "B", "C"], ["1", "2", "3"]], page=2, top0=60.0)
    )
    result, _ = build(segs)
    assert sum(1 for b in result.blocks if b.kind == "table") == 2
    assert not result.stitch_records
    assert any(a.kind == "continuation_rejected" for a in result.ambiguities)


def test_intervening_prose_blocks_the_stitch():
    segs = (
        tgrid([["Date", "Amt"], ["2026-01-01", "1"]], page=1, top0=60.0)
        + [Seg("note", "This paragraph interrupts the table.", (72, 300, 452, 314), page=1)]
        + tgrid([["Date", "Amt"], ["2026-02-01", "2"]], page=2, top0=60.0)
    )
    result, _ = build(segs)
    assert sum(1 for b in result.blocks if b.kind == "table") == 2
    assert not result.stitch_records
    assert "note" not in result.consumed_segment_ids


def test_page_number_between_fragments_is_transparent_and_preserved():
    segs = (
        tgrid([["Date", "Amt"], ["2026-01-01", "1"]], page=1, top0=60.0)
        + [Seg("pg", "53", (280, 760, 300, 772), page=1)]
        + tgrid([["Date", "Amt"], ["2026-02-01", "2"]], page=2, top0=60.0)
    )
    result, _ = build(segs)
    t = only_table(result)
    assert t.spans_pages == [1, 2]
    assert len(result.stitch_records) == 1
    assert result.stitch_records[0].transparent_segment_ids == ("pg",)
    assert "pg" not in result.consumed_segment_ids  # transparent != removed/consumed


# --- repeated header collapse -------------------------------------------------


def test_repeated_header_collapsed_once_with_lineage():
    segs = (
        tgrid([["Date", "Amount"], ["2026-01-01", "100,00"]], page=1, top0=60.0)
        + tgrid([["Date", "Amount"], ["2026-02-01", "200,00"]], page=2, top0=60.0)
    )
    result, _ = build(segs)
    t = only_table(result)
    assert sum(1 for row in t.rows if row[0].text == "Date") == 1
    assert len(result.collapsed_headers) == 1
    ch = result.collapsed_headers[0]
    assert ch.rule == "FR-022"
    assert ch.page == 2
    assert set(ch.segment_ids) == {"p2r0c0", "p2r0c1"}
    assert set(ch.kept_header_segment_ids) == {"p1r0c0", "p1r0c1"}
    # collapsed header segments are consumed (folded), not lost
    assert {"p2r0c0", "p2r0c1"} <= set(result.consumed_segment_ids)


def test_identical_data_row_later_in_table_is_not_collapsed():
    segs = (
        tgrid([["K", "V"], ["x", "1"]], page=1, top0=60.0)
        + tgrid([["K", "V"], ["x", "1"]], page=2, top0=60.0)
    )
    result, _ = build(segs)
    t = only_table(result)
    # header collapsed once; the identical *data* row ["x","1"] stays twice
    assert sum(1 for row in t.rows if [c.text for c in row] == ["K", "V"]) == 1
    assert sum(1 for row in t.rows if [c.text for c in row] == ["x", "1"]) == 2


def test_ocr_variant_header_is_not_collapsed():
    segs = (
        tgrid([["Date", "Amount"], ["2026-01-01", "1"]], page=1, top0=60.0)
        + tgrid([["Dote", "Arnount"], ["2026-02-01", "2"]], page=2, top0=60.0)
    )
    result, _ = build(segs)
    t = only_table(result)
    assert not result.collapsed_headers
    assert any(a.kind == "header_repeat_rejected" for a in result.ambiguities)
    assert any(r for r in t.rows if [c.text for c in r] == ["Dote", "Arnount"])


# --- structural reorder ----------------------------------------------------


def _colmajor_2x2():
    # accepted order walks columns: (r0c0, r1c0, r0c1, r1c1)
    return [
        tcell("s0", "A", 0, 100),
        tcell("s1", "C", 0, 114),
        tcell("s2", "B", 1, 100),
        tcell("s3", "D", 1, 114),
    ]


def test_column_major_accepted_input_yields_row_major_table_and_a_reorder():
    segs = _colmajor_2x2()
    result, _ = build(segs, order=["s0", "s1", "s2", "s3"])
    t = only_table(result)
    assert [[c.text for c in row] for row in t.rows] == [["A", "B"], ["C", "D"]]
    assert len(result.structural_reorder) == 1
    entry = result.structural_reorder[0]
    assert entry.from_order == ("s0", "s1", "s2", "s3")
    assert entry.to_order == ("s0", "s2", "s1", "s3")
    assert set(entry.affected_segment_ids) == {"s0", "s1", "s2", "s3"}
    assert entry.permitted_by == "FR-020"
    assert entry.reason


def test_row_major_accepted_input_emits_no_reorder():
    segs = _colmajor_2x2()
    result, _ = build(segs, order=["s0", "s2", "s1", "s3"])
    t = only_table(result)
    assert [[c.text for c in row] for row in t.rows] == [["A", "B"], ["C", "D"]]
    assert result.structural_reorder == ()


def test_reorder_and_no_reorder_share_the_same_logical_table_id():
    segs = _colmajor_2x2()
    a, _ = build(segs, order=["s0", "s1", "s2", "s3"])
    b, _ = build(segs, order=["s0", "s2", "s1", "s3"])
    assert only_table(a).table_id == only_table(b).table_id


# --- lineage / consumed ids ---------------------------------------------------


def test_every_consumed_segment_is_traceable_to_a_cell_or_a_collapsed_header():
    segs = (
        tgrid([["Date", "Amount"], ["2026-01-01", "1"]], page=1, top0=60.0)
        + tgrid([["Date", "Amount"], ["2026-02-01", "2"]], page=2, top0=60.0)
    )
    result, _ = build(segs)
    cell_ids: set[str] = set()
    for b in result.blocks:
        if b.kind != "table":
            continue
        for row in b.table.rows:
            for c in row:
                cell_ids.update(c.provenance)
    header_ids: set[str] = set()
    for ch in result.collapsed_headers:
        header_ids.update(ch.segment_ids)
    assert set(result.consumed_segment_ids) == cell_ids | header_ids
    assert cell_ids and header_ids


def test_consumed_ids_exclude_skipped_regions_and_furniture():
    segs = (
        tgrid([["Date", "Amt"], ["2026-01-01", "1"]], page=1, top0=60.0)
        + [Seg("pg", "2", (280, 760, 300, 772), page=1)]
        + tgrid([["Date", "Amt"], ["2026-02-01", "2"]], page=2, top0=60.0)
        # a separate hinted-but-uncorroborated region on page 3
        + [
            Seg("coarse0", "Grand Total", (72, 100, 452, 112), page=3,
                hints=[("table_row", None, "pdfplumber")]),
            Seg("coarse1", "sum 30", (72, 116, 452, 128), page=3,
                hints=[("table_row", None, "pdfplumber")]),
        ]
    )
    result, _ = build(segs)
    assert "pg" not in result.consumed_segment_ids
    assert "coarse0" not in result.consumed_segment_ids
    assert "coarse1" not in result.consumed_segment_ids


# --- determinism ---------------------------------------------------------------


def test_results_are_stable_under_accepted_segments_container_permutation():
    segs = tgrid([["A", "B", "C"], ["1", "2", "3"], ["4", "5", "6"]])
    fixed_order = [s.sid for s in segs]
    r1, _ = build(segs, order=fixed_order)
    r2, _ = build(list(reversed(segs)), order=fixed_order)
    t1, t2 = only_table(r1), only_table(r2)
    assert t1.table_id == t2.table_id
    assert [[c.text for c in row] for row in t1.rows] == [
        [c.text for c in row] for row in t2.rows
    ]


def test_fragment_ids_and_ambiguity_ordering_are_deterministic():
    segs = [
        Seg("r0", "Region Total", (72, 100, 452, 112), page=1,
            hints=[("table_row", None, "pdfplumber")]),
        Seg("r1", "North 10", (72, 116, 452, 128), page=1,
            hints=[("table_row", None, "pdfplumber")]),
    ]
    r1, _ = build(segs, order=["r0", "r1"])
    r2, _ = build(list(reversed(segs)), order=["r0", "r1"])
    assert [a.kind for a in r1.ambiguities] == [a.kind for a in r2.ambiguities]
    assert [d.hint_ref for d in r1.hint_decisions] == [d.hint_ref for d in r2.hint_decisions]


def test_build_tables_takes_the_ced_and_reflow_result_and_exposes_consumed_ids():
    result, _ = build(tgrid([["A", "B"], ["1", "2"]]))
    assert hasattr(result, "consumed_segment_ids")
    assert isinstance(result.consumed_segment_ids, frozenset)
