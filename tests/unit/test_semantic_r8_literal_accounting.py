"""R8 (post-semantic remediation audit of ``70aa0cf``) — the literal-level semantic
accounting invariant.

The set-level invariant ``retained ⊎ collapsed ⊎ removed == accepted`` is necessary but
(R1 proved) insufficient: a segment can be *set-accounted* while its literal silently
vanishes. ``literal_accounting_violations`` closes that: a nominally-retained segment
whose literal has no rendered representation and no permitted transform to explain the
delta is a violation.

Documented invariant — for every accepted segment ``s`` that appears in some block's
``provenance`` and is in neither ``collapsed_segment_ids`` nor ``removed_segment_ids``:
``norm(s.text)`` is a substring of ``norm(carrier.text)`` for some carrier unit
(paragraph / heading / clause / list item / table cell) naming ``s``, **or** ``s``
participates in a recorded ``dehyphenate`` ``SegmentTransform``. ``norm`` = the frozen
``comparison_key`` (NFC → smart-quote fold → whitespace-collapse) casefolded.
"""

from __future__ import annotations

import solari_converter.transform.build_semantic as build_semantic

from ._semantic_fixtures import Seg, ced

_violations = build_semantic.literal_accounting_violations


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


def test_case_and_whitespace_only_differences_are_not_violations():
    doc = ced([Seg("s", "TOTAL   DUE", (72, 100, 200, 112))])
    sem = build_semantic.build_semantic(doc)
    # the paragraph text is the segment's own literal — trivially holds; the point is
    # norm() folds the double space / case so an equivalent literal never trips it.
    assert _violations(sem, doc) == []
