"""R6 + R7 (post-semantic remediation audit of ``70aa0cf``).

R6: ``TableBlock.hint_decisions`` must be carried in the same canonical order already
used for ``TablesResult.hint_decisions`` — equivalent effective inputs that differ
only in carried-hint container order must produce equal semantic values and equal
serialization.

R7: ``SemanticDocument`` carries T070's ``CollapsedHeader`` records verbatim so the
per-collapse continuation-header → retained-header mapping the downstream RenderMap
``collapsed_into`` edge needs is not lost to the flat ``collapsed_segment_ids`` set.
"""

from __future__ import annotations

import solari_converter.transform.build_semantic as build_semantic
import solari_converter.transform.tables as tables

from ._semantic_fixtures import Seg, ced

_H = 12.0


def _tcell(sid, text, x0, top, *, page=1, w=80.0, hints=None):
    return Seg(sid, text, (x0, top, x0 + w, top + _H), page=page,
              hints=hints if hints is not None
              else [("table_cell", None, "pdfplumber")])


_TWO_HINTS = [("table_cell", None, "pdfplumber"), ("table_cell", None, "docling")]


def _grid_with_double_hints(hint_orders):
    segs = []
    for r, cells in enumerate([["H1", "H2"], ["a", "b"], ["c", "d"]]):
        for c, val in enumerate(cells):
            segs.append(_tcell(f"r{r}c{c}", val, 72 + 90 * c, 100 + 20 * r,
                               hints=list(hint_orders)))
    return segs


# --- R6 -----------------------------------------------------------------------------


def test_table_block_hint_decisions_are_canonically_ordered():
    result = tables.build_tables(ced(_grid_with_double_hints(_TWO_HINTS)))
    tb = next(b for b in result.blocks if b.kind == "table")
    keys = [(d.hint_ref, d.applied, d.reason) for d in tb.hint_decisions]
    assert keys == sorted(keys)


def test_hint_container_order_does_not_change_table_block_hint_decisions():
    a = tables.build_tables(ced(_grid_with_double_hints(_TWO_HINTS)))
    b = tables.build_tables(ced(_grid_with_double_hints(list(reversed(_TWO_HINTS)))))
    ta = next(x for x in a.blocks if x.kind == "table")
    tb = next(x for x in b.blocks if x.kind == "table")

    def to_key(blk):
        return [(d.hint_ref, d.applied, d.reason) for d in blk.hint_decisions]

    assert to_key(ta) == to_key(tb)
    # and equal to the top-level canonical ordering restricted to this block's ids
    block_ids = set(ta.provenance)
    top = [
        (d.hint_ref, d.applied, d.reason) for d in a.hint_decisions
        if d.hint_ref.split(":", 1)[0] in block_ids
    ]
    assert to_key(ta) == sorted(top)


def test_repeated_serialization_of_hint_decisions_is_stable():
    doc_args = _grid_with_double_hints(_TWO_HINTS)
    order = [s.sid for s in doc_args]
    r1 = tables.build_tables(ced(doc_args, order=order))
    r2 = tables.build_tables(ced(list(reversed(doc_args)), order=order))
    t1 = next(x for x in r1.blocks if x.kind == "table")
    t2 = next(x for x in r2.blocks if x.kind == "table")
    assert t1.hint_decisions == t2.hint_decisions


# --- R7: CollapsedHeader carried forward -------------------------------------------


def _stitched_doc():
    def grid(rows, page, top0):
        return [
            _tcell(f"p{page}r{r}c{c}", v, 72 + 90 * c, top0 + 14 * r, page=page)
            for r, row in enumerate(rows) for c, v in enumerate(row)
        ]

    return ced(
        grid([["Date", "Amount"], ["2026-01-01", "100.00"]], 1, 60)
        + grid([["Date", "Amount"], ["2026-02-01", "200.00"]], 2, 60)
    )


def test_semantic_document_carries_collapsed_header_records_verbatim():
    doc = _stitched_doc()
    tr = tables.build_tables(doc)
    sem = build_semantic.build_semantic(doc)

    assert sem.collapsed_headers == tr.collapsed_headers
    assert sem.collapsed_headers  # a repeated continuation header did collapse

    ch = sem.collapsed_headers[0]
    # the mapping the flat set discards: continuation-header ids + the retained
    # logical-header ids + the per-column pairing
    assert set(ch.segment_ids) == {"p2r0c0", "p2r0c1"}
    assert set(ch.kept_header_segment_ids) == {"p1r0c0", "p1r0c1"}
    assert {col for col, _ids in ch.per_cell} == {0, 1}

    # the flat set is still exactly the union of the collapsed ids (unchanged contract)
    assert sem.collapsed_segment_ids == {
        sid for c in sem.collapsed_headers for sid in c.segment_ids
    }


def test_no_collapsed_headers_leaves_the_tuple_empty():
    doc = ced([
        _tcell("h0", "H1", 72, 100), _tcell("h1", "H2", 162, 100),
        _tcell("a", "x", 72, 120), _tcell("b", "y", 162, 120),
    ])
    sem = build_semantic.build_semantic(doc)
    assert sem.collapsed_headers == ()
