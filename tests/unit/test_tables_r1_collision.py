"""R1 (post-semantic remediation audit of ``70aa0cf``) — same-anchor table literal
collision.

BLOCKER: two distinct accepted segments could resolve to one grid anchor while the
implementation retained only the first literal and merely appended the second segment
id to the cell provenance. A source segment must never be treated as semantically
retained just because its id appears in provenance while its literal has no
representation.

GREEN owner: this remediation pass (``transform/tables.py`` ``_Builder._assign_cells``
+ ``transform/build_semantic.py`` R8 invariant).
"""

from __future__ import annotations

import pytest

import solari_converter.transform.build_semantic as build_semantic
import solari_converter.transform.tables as tables

from ._semantic_fixtures import Seg, ced

_H = 12.0


def _tcell(sid, text, x0, top, *, page=1, w=80.0):
    return Seg(sid, text, (x0, top, x0 + w, top + _H), page=page,
              hints=[("table_cell", None, "pdfplumber")])


def _two_by_two(a1_text="A", extra=None):
    segs = [
        _tcell("h0", "H1", 72, 100), _tcell("h1", "H2", 162, 100),
        _tcell("a", a1_text, 72, 120), _tcell("b", "B", 162, 120),
    ]
    if extra is not None:
        segs.append(extra)
    return segs


# --- 1. FIRST + SECOND at one anchor cannot leave only FIRST renderable ---------------


def test_distinct_literals_at_one_anchor_abandon_the_table_fragment():
    # "A" and "A2" are two distinct source segments that land in the same grid cell.
    collide = _tcell("a2", "A2", 72, 120)  # exact same band + column as "a"
    doc = ced(_two_by_two(extra=collide))
    result = tables.build_tables(doc)

    assert not any(b.kind == "table" for b in result.blocks)
    assert any(
        amb.kind == "same_anchor_literal_collision" for amb in result.ambiguities
    )
    # every carried hint for the region is recorded NOT applied
    region = {"h0", "h1", "a", "a2", "b"}
    region_decisions = [
        d for d in result.hint_decisions if d.hint_ref.split(":", 1)[0] in region
    ]
    assert region_decisions and all(not d.applied for d in region_decisions)


def test_neither_colliding_literal_is_consumed_and_both_survive_as_prose():
    collide = _tcell("a2", "A2", 72, 120)
    doc = ced(_two_by_two(extra=collide))
    result = tables.build_tables(doc)

    # 2. both source literals remain source-accounted — nothing consumed by a table
    assert result.consumed_segment_ids == frozenset()

    # 3. the fragment falls back conservatively: the region is available for ordinary
    #    non-table semantic processing, and BOTH literals are rendered there.
    semantic = build_semantic.build_semantic(doc)
    assert not any(b.kind == "table" for b in semantic.blocks)
    rendered = " ".join(
        t
        for b in semantic.blocks
        for t, _prov in build_semantic._carrier_units(b)
    )
    assert "A" in rendered and "A2" in rendered
    assert build_semantic.literal_accounting_violations(semantic, doc) == []


def test_collision_fallback_is_deterministic_under_permutation():
    collide = _tcell("a2", "A2", 72, 120)
    segs = _two_by_two(extra=collide)
    order = [s.sid for s in segs]
    r1 = tables.build_tables(ced(segs, order=order))
    r2 = tables.build_tables(ced(list(reversed(segs)), order=order))
    assert [a.kind for a in r1.ambiguities] == [a.kind for a in r2.ambiguities]
    assert r1.consumed_segment_ids == r2.consumed_segment_ids == frozenset()


# --- ONLY codepoint-identical literals may collapse ---------------------------------


def test_byte_identical_literals_at_one_anchor_collapse_without_literal_loss():
    collide = _tcell("a2", "A", 72, 120)  # exactly "A" — same as segment "a"
    doc = ced(_two_by_two(extra=collide))
    result = tables.build_tables(doc)

    tbl = next(b for b in result.blocks if b.kind == "table")
    cell = tbl.table.rows[1][0]
    assert cell.text == "A"
    assert {"a", "a2"} <= set(cell.provenance)
    assert {"a", "a2"} <= set(result.consumed_segment_ids)
    assert any(
        amb.kind == "identical_cell_evidence_collapsed" for amb in result.ambiguities
    )


@pytest.mark.parametrize(
    ("first", "second"),
    [
        ("A", "a"),                 # case
        ('"hi"', "“hi”"),  # straight vs smart quotes
        ("total", "total "),        # trailing whitespace
        ("total due", "total  due"),  # internal whitespace
        ("1", "1.00"),              # numeric formatting
        ("nao", "não"),        # different Unicode representation
        ("A,", "A;"),               # punctuation
    ],
)
def test_non_identical_literals_at_one_anchor_reject_the_fragment(first, second):
    segs = [
        _tcell("h0", "H1", 72, 100), _tcell("h1", "H2", 162, 100),
        _tcell("a", first, 72, 120), _tcell("b", "B", 162, 120),
        _tcell("a2", second, 72, 120),
    ]
    result = tables.build_tables(ced(segs))
    assert not any(b.kind == "table" for b in result.blocks)
    assert any(
        amb.kind == "same_anchor_literal_collision" for amb in result.ambiguities
    )
    assert result.consumed_segment_ids == frozenset()  # no distinct literal disappears


def test_three_or_more_identical_collisions_stay_safe():
    segs = [
        _tcell("h0", "H1", 72, 100), _tcell("h1", "H2", 162, 100),
        _tcell("a", "A", 72, 120), _tcell("b", "B", 162, 120),
        _tcell("a2", "A", 72, 120), _tcell("a3", "A", 72, 120),
    ]
    result = tables.build_tables(ced(segs))
    tbl = next(b for b in result.blocks if b.kind == "table")
    cell = tbl.table.rows[1][0]
    assert cell.text == "A"
    assert {"a", "a2", "a3"} <= set(cell.provenance)
    assert {"a", "a2", "a3"} <= set(result.consumed_segment_ids)


# --- 4. wrapped-cell + merged-span behaviour is untouched ----------------------------


def test_wrapped_cell_continuation_still_joins_after_the_collision_guard():
    segs = [
        _tcell("h0", "Desc", 72, 100), _tcell("h1", "Amt", 162, 100),
        _tcell("a0", "line one", 72, 120), _tcell("a1", "9.99", 162, 120),
        _tcell("wrap", "line two", 72, 132),  # ~one text line below a0 → wrapped
    ]
    result = tables.build_tables(ced(segs))
    tbl = next(b for b in result.blocks if b.kind == "table")
    assert tbl.table.rows[1][0].text == "line one line two"
    assert set(tbl.table.rows[1][0].provenance) == {"a0", "wrap"}


def test_merged_span_behaviour_still_holds():
    segs = [
        Seg("cat", "category", (72, 100, 152, 128), page=1,
            hints=[("table_cell", None, "pdfplumber")]),
        _tcell("x1", "one", 162, 100), _tcell("x2", "two", 162, 114),
    ]
    result = tables.build_tables(ced(segs))
    tbl = next(b for b in result.blocks if b.kind == "table")
    assert tbl.table.has_merged_cells
    assert tbl.table.rows[0][0].rowspan == 2


# --- R8 direct: retained provenance alone is NOT sufficient --------------------------


def test_literal_accounting_flags_a_provenance_only_retained_segment():
    from solari_converter.model.semantic import SemanticDocument, TableBlock
    from solari_converter.transform.tables import LogicalTable, TableCell

    doc = ced([
        Seg("keep", "REAL VALUE", (72, 100, 200, 112), page=1),
        Seg("ghost", "LOST VALUE", (72, 116, 200, 128), page=1),
    ])
    # a hand-built pathological document: "ghost" is in the cell provenance but its
    # literal never made it into any rendered text — exactly the R1 defect shape.
    cell = TableCell(text="REAL VALUE", provenance=("keep", "ghost"), row=0, column=0)
    table = LogicalTable(
        table_id="tbl-x", rows=[[cell]], has_merged_cells=False,
        header_row_count=1, spans_pages=[1],
    )
    block = TableBlock(
        kind="table", block_id="blk-x", table=table,
        provenance=("keep", "ghost"), hint_decisions=(),
    )
    bad = SemanticDocument(blocks=(block,))
    assert build_semantic.literal_accounting_violations(bad, doc) == ["ghost"]


def test_build_semantic_raises_on_a_literal_accounting_violation(monkeypatch):
    # force the invariant to see a violation and assert build_semantic refuses to
    # return silently (the R1 class must never pass unnoticed).
    doc = ced([
        _tcell("h0", "H1", 72, 100), _tcell("h1", "H2", 162, 100),
        _tcell("a", "A", 72, 120), _tcell("b", "B", 162, 120),
    ])
    monkeypatch.setattr(
        build_semantic, "literal_accounting_violations", lambda *_: ["a"]
    )
    with pytest.raises(build_semantic.LiteralAccountingError):
        build_semantic.build_semantic(doc)
