"""R8 — the exact literal-level + accepted-ID partition semantic accounting invariants.

The set-level invariant ``retained ⊎ collapsed ⊎ removed == accepted`` is necessary but
(R1 proved) insufficient: a segment can be *set-accounted* while its literal silently
vanishes or is quietly mutated.

Second-pass contract (checkpoint ``73fb7d9``):

* ``accepted_partition_violations`` — every accepted id in exactly one terminal state
  (retained / collapsed / removed); the three sets pairwise disjoint; union == accepted.
* ``literal_accounting_violations`` — for every nominally-retained ``s`` (id in some
  block ``provenance``; not collapsed; not removed), ``s.text`` MUST appear **verbatim**
  (codepoint-exact — NO ``comparison_key`` / casefold / smart-quote / whitespace /
  punctuation / numeric-format folding) as a substring of some carrier unit naming
  ``s``. The one exception is the *left* side of a recorded ``dehyphenate`` transform:
  the single permitted mutation is the trailing-``U+002D`` drop, i.e.
  ``s.text[:-1] + right.text`` must appear verbatim. Appearing in a ``dehyphenate``
  record exempts nothing else.

Both are enforced at runtime by ``build_semantic`` (``AcceptedPartitionError`` /
``LiteralAccountingError``).
"""

from __future__ import annotations

import pytest

import solari_converter.transform.build_semantic as build_semantic
from solari_converter.model.semantic import ParagraphBlock, SemanticDocument
from solari_converter.transform.reflow import SegmentTransform

from ._semantic_fixtures import Seg, ced

_violations = build_semantic.literal_accounting_violations
_partition = build_semantic.accepted_partition_violations


def _tcell(sid, text, x0, top, *, page=1, w=80.0):
    return Seg(sid, text, (x0, top, x0 + w, top + 12), page=page,
              hints=[("table_cell", None, "pdfplumber")])


def test_holds_for_a_plain_multi_block_document():
    doc = ced([
        Seg("t", "Overview", (72, 60, 200, 74), hints=[("heading", 1, "docling")]),
        Seg("p1", "A paragraph that then", (72, 90, 452, 102)),
        Seg("p2", "wraps onto a second visual line.", (72, 104, 452, 116)),
        Seg("li1", "- first point", (72, 140, 452, 152)),
        Seg("li2", "- second point", (72, 156, 452, 168)),
    ])
    sem = build_semantic.build_semantic(doc)
    assert _violations(sem, doc) == []


def test_holds_across_a_wrapped_table_cell_join():
    doc = ced([
        _tcell("h0", "Desc", 72, 100), _tcell("h1", "Amt", 162, 100),
        _tcell("a0", "line one", 72, 120), _tcell("a1", "9.99", 162, 120),
        _tcell("wrap", "line two", 72, 132),
    ])
    sem = build_semantic.build_semantic(doc)
    assert _violations(sem, doc) == []
    tb = next(b for b in sem.blocks if b.kind == "table")
    assert {"a0", "wrap"} <= set(tb.table.rows[1][0].provenance)


def test_holds_when_a_hyphen_is_repaired_by_a_dehyphenate_transform():
    # "inter-" + "national" with "international" attested elsewhere in the document →
    # a recorded ``dehyphenate`` transform legitimately drops the boundary hyphen.
    doc = ced([
        Seg("w1", "inter-", (72, 100, 110, 112)),
        Seg("w2", "national trade", (72, 113, 200, 125)),
        Seg("att", "the international body", (72, 200, 300, 212)),
    ])
    sem = build_semantic.build_semantic(doc)
    kinds = {t.kind for t in sem.segment_transforms}
    assert "dehyphenate" in kinds
    assert _violations(sem, doc) == []


def test_a_segments_own_literal_is_delivered_verbatim_including_internal_spacing():
    doc = ced([Seg("s", "TOTAL   DUE", (72, 100, 200, 112))])
    sem = build_semantic.build_semantic(doc)
    para = next(b for b in sem.blocks if b.kind == "paragraph")
    assert para.text == "TOTAL   DUE"  # double space preserved, not collapsed
    assert _violations(sem, doc) == []


# --- R8 (second pass) adversarial: comparison-equivalence is NOT fidelity ------------


def _para(sid, text, *, prov=None):
    return ParagraphBlock(
        kind="paragraph", block_id=f"blk-{sid}", text=text,
        provenance=tuple(prov or (sid,)),
    )


def _doc_one(sid, literal):
    return ced([Seg(sid, literal, (72, 100, 300, 112))])


@pytest.mark.parametrize(
    ("literal", "delivered"),
    [
        ("Total Due", "total due"),          # case mutation
        ('He said "yes"', "He said “yes”"),  # smart/straight quote mutation
        ("Section 3.", "Section 3:"),          # punctuation mutation
        ("1,234.50", "1234.5"),                # numeric-format mutation (in place)
        ("abcdef", "TOTAL REPLACEMENT"),       # arbitrary replacement
    ],
)
def test_non_verbatim_delivery_of_a_retained_literal_is_a_violation(literal, delivered):
    doc = _doc_one("s", literal)
    sem = SemanticDocument(blocks=(_para("s", delivered),))
    assert _violations(sem, doc) == ["s"]


def test_arbitrary_replacement_under_a_fake_dehyphenate_record_still_fails():
    doc = ced([
        Seg("l", "abcdef", (72, 100, 110, 112)),
        Seg("r", "ghi", (72, 113, 140, 125)),
    ])
    # "l" carries a trailing hyphen? no — and the delivered text is a total
    # replacement. A dehyphenate lineage record must not exempt it.
    sem = SemanticDocument(
        blocks=(_para("p", "TOTAL REPLACEMENT", prov=("l", "r")),),
        segment_transforms=(
            SegmentTransform(
                kind="dehyphenate", permitted_by="FR-014",
                segment_ids=("l", "r"), joined_with="r",
                boundary="fabricated",
            ),
        ),
    )
    assert "l" in _violations(sem, doc)


def test_arbitrary_replacement_under_a_real_looking_dehyphenate_record_fails():
    # "l" genuinely ends with a hyphen, but the delivered carrier is not
    # l.text[:-1] + r.text — the exact boundary mutation is not what happened.
    doc = ced([
        Seg("l", "inter-", (72, 100, 110, 112)),
        Seg("r", "national", (72, 113, 160, 125)),
    ])
    sem = SemanticDocument(
        blocks=(_para("p", "something else entirely", prov=("l", "r")),),
        segment_transforms=(
            SegmentTransform(
                kind="dehyphenate", permitted_by="FR-014",
                segment_ids=("l", "r"), joined_with="r", boundary="x",
            ),
        ),
    )
    assert "l" in _violations(sem, doc)


def test_exact_boundary_dehyphenation_is_accepted():
    doc = ced([
        Seg("l", "inter-", (72, 100, 110, 112)),
        Seg("r", "national trade", (72, 113, 200, 125)),
    ])
    sem = SemanticDocument(
        blocks=(_para("p", "international trade", prov=("l", "r")),),
        segment_transforms=(
            SegmentTransform(
                kind="dehyphenate", permitted_by="FR-014",
                segment_ids=("l", "r"), joined_with="r", boundary="x",
            ),
        ),
    )
    assert _violations(sem, doc) == []


def test_correct_reflow_whitespace_join_is_accepted():
    doc = ced([
        Seg("a", "first part", (72, 100, 160, 112)),
        Seg("b", "second part", (72, 113, 200, 125)),
    ])
    sem = SemanticDocument(blocks=(_para("p", "first part second part", prov=("a", "b")),))
    assert _violations(sem, doc) == []


def test_accepted_id_absent_from_every_terminal_set_is_a_partition_violation():
    doc = ced([
        Seg("kept", "delivered text", (72, 100, 200, 112)),
        Seg("lost", "never placed anywhere", (72, 120, 200, 132)),
    ])
    sem = SemanticDocument(blocks=(_para("kept", "delivered text"),))
    v = _partition(sem, doc)
    assert v.get("absent") == ["lost"]


def test_id_in_provenance_but_literal_missing_is_a_literal_violation_not_partition():
    doc = ced([
        Seg("kept", "REAL VALUE", (72, 100, 200, 112)),
        Seg("ghost", "LOST VALUE", (72, 120, 200, 132)),
    ])
    sem = SemanticDocument(blocks=(_para("p", "REAL VALUE", prov=("kept", "ghost")),))
    assert _partition(sem, doc) == {}          # ghost IS in a provenance → retained
    assert _violations(sem, doc) == ["ghost"]  # …but its literal never arrived


def test_valid_collapsed_header_segment_is_exempt_from_literal_check():
    from solari_converter.model.semantic import TableBlock
    from solari_converter.transform.tables import CollapsedHeader, LogicalTable, TableCell

    doc = ced([
        Seg("h", "Date", (72, 60, 120, 72)),
        Seg("c", "Date", (72, 200, 120, 212)),  # repeated continuation header
    ])
    cell = TableCell(text="Date", provenance=("h",), row=0, column=0, is_header=True)
    table = LogicalTable(
        table_id="tbl-x", rows=[[cell]], has_merged_cells=False,
        header_row_count=1, spans_pages=[1, 2],
    )
    block = TableBlock(
        kind="table", block_id="blk-x", table=table,
        provenance=("h", "c"), hint_decisions=(),
    )
    ch = CollapsedHeader(
        table_id="tbl-x", page=2, segment_ids=("c",),
        kept_header_segment_ids=("h",), per_cell=((0, ("c",)),),
        collapsed_into=(("c", "h"),),
    )
    sem = SemanticDocument(
        blocks=(block,), collapsed_segment_ids=frozenset({"c"}),
        collapsed_headers=(ch,),
    )
    assert _violations(sem, doc) == []
    assert _partition(sem, doc) == {}


def test_valid_artifact_removed_segment_is_exempt_from_literal_check():
    doc = ced([
        Seg("body", "Ordinary paragraph text.", (72, 100, 300, 112)),
        Seg("furn", "ACME CONFIDENTIAL", (72, 30, 300, 42)),
    ])
    sem = SemanticDocument(
        blocks=(_para("body", "Ordinary paragraph text."),),
        removed_segment_ids=frozenset({"furn"}),
    )
    assert _violations(sem, doc) == []
    assert _partition(sem, doc) == {}
