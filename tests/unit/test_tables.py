"""T066 [US1] — failing-first tests for Stage-3 table reconstruction.

GREEN owner: **T070** (``src/solari_converter/transform/tables.py``) — **NOT** part of
Semantic Block S1. These stay **RED** until T070 lands; S1 (T067–T069) must not make
them green by implementing tables early (block brief §24).

Frozen references: spec FR-020 / FR-021 / FR-022, SC-023, data-model.md ``Table`` /
``Cell`` / ``structural_reorder``.
"""

from __future__ import annotations

from ._semantic_fixtures import Seg, ced


def _tables():
    import solari_converter.transform.tables as tables  # GREEN owner: T070 (post-S1)

    return tables


def _reflow(doc):
    import solari_converter.transform.reflow as reflow

    return reflow.reflow(doc)


def _cell(sid, text, x0, top, *, page=1):
    return Seg(sid, text, (x0, top, x0 + 80.0, top + 12.0), page=page,
               hints=[("table_cell", None, "pdfplumber")])


def _grid(rows, *, page=1, top0=100.0):
    segs = []
    for r, cells in enumerate(rows):
        for c, val in enumerate(cells):
            segs.append(_cell(f"p{page}r{r}c{c}", val, 72.0 + 90.0 * c, top0 + 14.0 * r,
                              page=page))
    return segs


def test_table_starting_mid_page_is_built_with_exact_rows_and_columns():
    t = _tables()
    doc = ced(
        [Seg("intro", "Some text before the table.", (72, 60, 452, 74))]
        + _grid([["Item", "Qty", "Price"], ["Widget", "3", "9.99"], ["Gadget", "1", "4.50"]])
    )
    result = t.build_tables(doc, _reflow(doc))
    tbl = next(b for b in result.blocks if b.kind == "table")
    assert len(tbl.table.rows) == 3
    assert all(len(row) == 3 for row in tbl.table.rows)
    assert tbl.table.rows[1][2].text == "9.99"  # numeric preserved verbatim


def test_multi_page_table_is_stitched_with_the_repeated_header_collapsed_once():
    t = _tables()
    doc = ced(
        _grid([["Date", "Amount"], ["2026-01-01", "100.00"]], page=1)
        + _grid([["Date", "Amount"], ["2026-02-01", "200.00"]], page=2, top0=60.0)
    )
    result = t.build_tables(doc, _reflow(doc))
    tbl = next(b for b in result.blocks if b.kind == "table")
    assert tbl.table.header_row_count == 1
    assert tbl.table.spans_pages == [1, 2]
    assert sum(1 for row in tbl.table.rows if row[0].text == "Date") == 1
    assert [c.text for c in tbl.table.rows[-1]] == ["2026-02-01", "200.00"]


def test_merged_cells_are_detected_and_flagged():
    t = _tables()
    doc = ced([
        Seg("h", "Header spanning two columns", (72, 100, 252, 112), page=1,
            hints=[("table_cell", None, "pdfplumber")]),
        Seg("a", "left", (72, 116, 162, 128), page=1, hints=[("table_cell", None, "pdfplumber")]),
        Seg("b", "right", (162, 116, 252, 128), page=1, hints=[("table_cell", None, "pdfplumber")]),
    ])
    result = t.build_tables(doc, _reflow(doc))
    tbl = next(b for b in result.blocks if b.kind == "table")
    assert tbl.table.has_merged_cells
    assert any(c.colspan == 2 for row in tbl.table.rows for c in row)


def test_any_row_reordering_is_recorded_as_a_structural_reorder_entry():
    t = _tables()
    doc = ced(_grid([["A", "B"], ["2", "y"], ["1", "x"]]))
    result = t.build_tables(doc, _reflow(doc))
    if result.structural_reorder:
        entry = result.structural_reorder[0]
        assert set(entry.affected_segment_ids)
        assert entry.from_order != entry.to_order
        assert entry.reason
