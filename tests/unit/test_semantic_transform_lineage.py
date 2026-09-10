"""Final minimal semantic blocker remediation — adversarial coverage (checkpoint
``eaf5a77``).

BLOCKER 1 — the identical-evidence duplicate-collapse exception must be **cell-local
and provenance-authenticated**: usable only inside the exact retained ``TableCell``
that generated it, never in a paragraph / heading / clause / list item, never across
cells, never merely because ``table_identical_evidence_groups`` names a set.

BLOCKER 2 — a ``dehyphenate`` transform's ``segment_ids`` must be *exactly* the
owning carrier's ordered provenance prefix through the joined-right segment (the
frozen Stage-3 ``reflow._join`` contract). Unrelated prefix/suffix ids, cross-carrier
participants, wrong order, duplicate ids, and conflicting records are all rejected —
not accepted merely because the last two ids form a valid dehyphenation.

GREEN owner: this remediation pass (``transform/build_semantic.py``).
"""

from __future__ import annotations

import pytest

import solari_converter.transform.build_semantic as build_semantic
from solari_converter.model.semantic import (
    ClauseBlock,
    HeadingBlock,
    ListBlock,
    ListItemEntry,
    ParagraphBlock,
    SemanticDocument,
    TableBlock,
)
from solari_converter.transform.reflow import SegmentTransform
from solari_converter.transform.tables import LogicalTable, TableCell

from ._semantic_fixtures import Seg, ced

_violations = build_semantic.literal_accounting_violations


# --- builders --------------------------------------------------------------------


def _seg(sid, text, i=0):
    return Seg(sid, text, (72, 100 + 16 * i, 320, 112 + 16 * i))


def _deh(seg_ids, joined_with, *, permitted_by="FR-014", stage=3):
    return SegmentTransform(
        kind="dehyphenate", permitted_by=permitted_by, segment_ids=tuple(seg_ids),
        joined_with=joined_with, boundary="x", stage=stage,
    )


def _reflow_ws(seg_ids, joined_with):
    return SegmentTransform(
        kind="reflow_whitespace", permitted_by="FR-013", segment_ids=tuple(seg_ids),
        joined_with=joined_with, boundary="x",
    )


def _tc(sid, text, x0, top, *, page=1, w=80.0):
    return Seg(sid, text, (x0, top, x0 + w, top + 12), page=page,
              hints=[("table_cell", None, "pdfplumber")])


def _non_table_block(kind, text, prov):
    if kind == "paragraph":
        return ParagraphBlock(kind="paragraph", block_id="blk", text=text,
                              provenance=tuple(prov))
    if kind == "heading":
        return HeadingBlock(kind="heading", block_id="blk", text=text, level=1,
                            deep=False, numbering=None, provenance=tuple(prov))
    if kind == "clause":
        return ClauseBlock(kind="clause", block_id="blk", identifier="1", text=text,
                           depth=1, provenance=tuple(prov))
    if kind == "list":
        return ListBlock(
            kind="list", block_id="blk", ordered=False,
            items=(ListItemEntry(text=text, marker="-", family="bullet", depth=0,
                                 segment_ids=tuple(prov)),),
            provenance=tuple(prov),
        )
    raise AssertionError(kind)


def _cell_table(cells, table_id="tbl-x"):
    """``cells`` = list of (text, provenance-tuple). One row."""
    rows = [[
        TableCell(text=t, provenance=tuple(p), row=0, column=i)
        for i, (t, p) in enumerate(cells)
    ]]
    prov = tuple(s for _t, p in cells for s in p)
    table = LogicalTable(table_id=table_id, rows=rows, has_merged_cells=False,
                         header_row_count=1, spans_pages=[1])
    return TableBlock(kind="table", block_id="blk", table=table, provenance=prov,
                      hint_decisions=())


# --- BLOCKER 1: identical-evidence exception is cell-local + authenticated ---------


@pytest.mark.parametrize("kind", ["paragraph", "heading", "clause", "list"])
def test_non_table_carrier_cannot_use_an_injected_identical_group(kind):
    doc = ced([_seg("a", "abc", 0), _seg("b", "abc", 1)])
    sem = SemanticDocument(
        blocks=(_non_table_block(kind, "abc", ("a", "b")),),
        table_identical_evidence_groups=(frozenset({"a", "b"}),),
    )
    v = _violations(sem, doc)
    assert v  # the duplicate is NOT collapsible outside a table cell
    assert "b" in v or "a" in v


def test_group_with_an_id_from_another_cell_is_rejected():
    doc = ced([_tc("a", "dup", 72, 100), _tc("b", "dup", 72, 100),
               _tc("c", "dup", 200, 100)])
    sem = SemanticDocument(
        blocks=(_cell_table([("dup", ("a", "b")), ("dup", ("c",))]),),
        table_identical_evidence_groups=(frozenset({"a", "b", "c"}),),
    )
    assert _violations(sem, doc)  # cross-cell group never authenticates


def test_group_spanning_two_single_provenance_cells_is_rejected():
    doc = ced([_tc("a", "dup", 72, 100), _tc("c", "dup", 200, 100)])
    sem = SemanticDocument(
        blocks=(_cell_table([("dup", ("a",)), ("dup", ("c",))]),),
        table_identical_evidence_groups=(frozenset({"a", "c"}),),
    )
    assert _violations(sem, doc)


def test_group_with_unknown_id_is_rejected():
    doc = ced([_tc("a", "dup", 72, 100), _tc("b", "dup", 72, 100)])
    sem = SemanticDocument(
        blocks=(_cell_table([("dup", ("a", "b"))]),),
        table_identical_evidence_groups=(frozenset({"a", "b", "ghost"}),),
    )
    assert _violations(sem, doc)


def test_group_with_non_identical_literals_is_rejected():
    doc = ced([_tc("a", "dup", 72, 100), _tc("b", "DUP", 72, 100)])
    sem = SemanticDocument(
        blocks=(_cell_table([("dup", ("a", "b"))]),),
        table_identical_evidence_groups=(frozenset({"a", "b"}),),
    )
    assert _violations(sem, doc)


def test_rejected_table_fragment_group_is_rejected():
    doc = ced([_tc("a", "dup", 72, 100), _tc("b", "dup", 72, 100)])
    sem = SemanticDocument(
        blocks=(_cell_table([("dup", ("a", "b"))]),),
        table_identical_evidence_groups=(frozenset({"a", "b"}),),
        rejected_table_segment_ids=frozenset({"a"}),
    )
    assert _violations(sem, doc)


def test_malformed_singleton_group_is_rejected():
    doc = ced([_seg("a", "abc", 0)])
    sem = SemanticDocument(
        blocks=(ParagraphBlock(kind="paragraph", block_id="blk", text="abc",
                               provenance=("a",)),),
        table_identical_evidence_groups=(frozenset({"a"}),),
    )
    assert _violations(sem, doc)


def test_id_appearing_in_a_second_carrier_denies_the_group():
    doc = ced([_tc("a", "dup", 72, 100), _tc("b", "dup", 72, 100)])
    tbl = _cell_table([("dup", ("a", "b"))])
    other = ParagraphBlock(kind="paragraph", block_id="blk2", text="dup",
                           provenance=("a",))  # a also owned by prose → not cell-local
    sem = SemanticDocument(
        blocks=(tbl, other),
        table_identical_evidence_groups=(frozenset({"a", "b"}),),
    )
    assert _violations(sem, doc)


def test_real_t070_same_anchor_identical_evidence_in_one_cell_passes():
    doc = ced([
        _tc("h0", "H1", 72, 100), _tc("h1", "H2", 162, 100),
        _tc("a", "A", 72, 120), _tc("b", "B", 162, 120),
        _tc("a2", "A", 72, 120),  # byte-identical, same anchor as "a"
    ])
    sem = build_semantic.build_semantic(doc)
    assert any({"a", "a2"} <= g for g in sem.table_identical_evidence_groups)
    assert _violations(sem, doc) == []


def test_three_identical_duplicates_in_one_cell_pass():
    doc = ced([
        _tc("h0", "H1", 72, 100), _tc("h1", "H2", 162, 100),
        _tc("a", "A", 72, 120), _tc("b", "B", 162, 120),
        _tc("a2", "A", 72, 120), _tc("a3", "A", 72, 120),
    ])
    sem = build_semantic.build_semantic(doc)
    assert any({"a", "a2", "a3"} <= g for g in sem.table_identical_evidence_groups)
    assert _violations(sem, doc) == []


def test_identical_evidence_collapse_is_deterministic_across_runs():
    def _mk():
        return build_semantic.build_semantic(ced([
            _tc("h0", "H1", 72, 100), _tc("h1", "H2", 162, 100),
            _tc("a", "A", 72, 120), _tc("b", "B", 162, 120),
            _tc("a2", "A", 72, 120),
        ]))

    s1, s2 = _mk(), _mk()
    assert s1.table_identical_evidence_groups == s2.table_identical_evidence_groups
    assert [getattr(b, "text", None) for b in s1.blocks] == \
           [getattr(b, "text", None) for b in s2.blocks]


# --- BLOCKER 2: dehyphenation participants match the owning carrier lineage --------


def test_unrelated_prefix_id_in_dehyphenate_is_rejected():
    # the exact reproduced bug: segment_ids=("q","l","r") accepted for l/r even though
    # q belongs to another paragraph.
    doc = ced([_seg("q", "other-", 0), _seg("l", "inter-", 1), _seg("r", "national", 2)])
    sem = SemanticDocument(
        blocks=(
            ParagraphBlock(kind="paragraph", block_id="b1", text="other-",
                           provenance=("q",)),
            ParagraphBlock(kind="paragraph", block_id="b2", text="international",
                           provenance=("l", "r")),
        ),
        segment_transforms=(_deh(("q", "l", "r"), "r"),),
    )
    v = _violations(sem, doc)
    assert "q" in v or "l" in v or "r" in v


def test_dehyphenate_with_valid_pair_plus_unrelated_interior_id_is_rejected():
    doc = ced([_seg("l", "inter-", 0), _seg("x", "foo", 1), _seg("r", "national", 2)])
    sem = SemanticDocument(
        blocks=(ParagraphBlock(kind="paragraph", block_id="b", text="international",
                               provenance=("l", "r")),),
        segment_transforms=(_deh(("l", "x", "r"), "r"),),
    )
    assert _violations(sem, doc)


def test_dehyphenate_order_differing_from_carrier_order_is_rejected():
    doc = ced([_seg("a", "The", 0), _seg("b", "inter-", 1), _seg("c", "national.", 2)])
    sem = SemanticDocument(
        blocks=(ParagraphBlock(kind="paragraph", block_id="b",
                               text="The international.", provenance=("a", "b", "c")),),
        segment_transforms=(_deh(("b", "a", "c"), "c"),),
    )
    assert _violations(sem, doc)


def test_dehyphenate_with_duplicate_participant_ids_is_rejected():
    doc = ced([_seg("l", "inter-", 0), _seg("r", "national", 1)])
    sem = SemanticDocument(
        blocks=(ParagraphBlock(kind="paragraph", block_id="b", text="international",
                               provenance=("l", "r")),),
        segment_transforms=(_deh(("l", "l", "r"), "r"),),
    )
    assert _violations(sem, doc)


def test_two_dehyphenate_transforms_for_the_same_boundary_are_rejected():
    doc = ced([_seg("l", "inter-", 0), _seg("r", "national", 1)])
    sem = SemanticDocument(
        blocks=(ParagraphBlock(kind="paragraph", block_id="b", text="international",
                               provenance=("l", "r")),),
        segment_transforms=(_deh(("l", "r"), "r"), _deh(("l", "r"), "r")),
    )
    assert _violations(sem, doc)


def test_two_dehyphenate_transforms_claiming_the_same_joined_with_are_rejected():
    doc = ced([_seg("x", "foo-", 0), _seg("l", "inter-", 1), _seg("r", "national", 2)])
    sem = SemanticDocument(
        blocks=(
            ParagraphBlock(kind="paragraph", block_id="b1", text="foo-",
                           provenance=("x",)),
            ParagraphBlock(kind="paragraph", block_id="b2", text="international",
                           provenance=("l", "r")),
        ),
        segment_transforms=(_deh(("l", "r"), "r"), _deh(("x", "r"), "r")),
    )
    assert _violations(sem, doc)


def test_dehyphenate_participants_split_across_carriers_is_rejected():
    doc = ced([_seg("l", "inter-", 0), _seg("r", "national", 1)])
    sem = SemanticDocument(
        blocks=(
            ParagraphBlock(kind="paragraph", block_id="b1", text="inter-",
                           provenance=("l",)),
            ParagraphBlock(kind="paragraph", block_id="b2", text="national",
                           provenance=("r",)),
        ),
        segment_transforms=(_deh(("l", "r"), "r"),),
    )
    assert "l" in _violations(sem, doc)


def test_plain_inter_national_dehyphenation_passes():
    doc = ced([_seg("l", "inter-", 0), _seg("r", "national", 1)])
    sem = SemanticDocument(
        blocks=(ParagraphBlock(kind="paragraph", block_id="b", text="international",
                               provenance=("l", "r")),),
        segment_transforms=(_deh(("l", "r"), "r"),),
    )
    assert _violations(sem, doc) == []


def test_three_segment_carrier_with_one_legitimate_dehyphenation_passes():
    doc = ced([_seg("a", "The word", 0), _seg("b", "inter-", 1),
               _seg("c", "national.", 2)])
    sem = SemanticDocument(
        blocks=(ParagraphBlock(kind="paragraph", block_id="b",
                               text="The word international.",
                               provenance=("a", "b", "c")),),
        segment_transforms=(_reflow_ws(("a", "b"), "b"), _deh(("a", "b", "c"), "c")),
    )
    assert _violations(sem, doc) == []


def test_two_independent_valid_dehyphenations_in_one_carrier_pass():
    doc = ced([_seg("a", "foo-", 0), _seg("b", "bar", 1),
               _seg("c", "baz-", 2), _seg("d", "qux", 3)])
    sem = SemanticDocument(
        blocks=(ParagraphBlock(kind="paragraph", block_id="b", text="foobar bazqux",
                               provenance=("a", "b", "c", "d")),),
        segment_transforms=(
            _deh(("a", "b"), "b"),
            _reflow_ws(("a", "b", "c"), "c"),
            _deh(("a", "b", "c", "d"), "d"),
        ),
    )
    assert _violations(sem, doc) == []


def test_real_build_dehyphenate_segment_ids_are_the_carrier_prefix():
    doc = ced([
        Seg("w1", "inter-", (72, 100, 110, 112)),
        Seg("w2", "national trade", (72, 113, 200, 125)),
        Seg("att", "the international body", (72, 200, 300, 212)),
    ])
    sem = build_semantic.build_semantic(doc)
    deh = [t for t in sem.segment_transforms if t.kind == "dehyphenate"]
    assert deh
    carrier = next(b for b in sem.blocks if getattr(b, "text", "") == "international trade")
    for t in deh:
        ri = carrier.provenance.index(t.joined_with)
        assert tuple(t.segment_ids) == tuple(carrier.provenance[: ri + 1])
    assert _violations(sem, doc) == []
