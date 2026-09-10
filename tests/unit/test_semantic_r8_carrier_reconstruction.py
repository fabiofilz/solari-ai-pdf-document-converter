"""Third narrow semantic remediation pass — adversarial coverage.

B1: ``literal_accounting_violations`` verifies the **complete carrier** by exact
ordered reconstruction (source-segment ids → CED literals → permitted boundary
transforms), not by proving each source literal is *somewhere* inside a carrier.

B2: every frozen ``dehyphenate`` contract field is validated before the transform may
account for a boundary.

B3: ``accepted_partition_violations`` derives ``raw_retained`` from carrier ownership
(prose / heading / clause / list-item provenance + table **cell** provenance) and
checks the three terminal sets for overlap *without subtracting anything first*.

B4: a segment returned to ordinary processing because its table reconstruction was
rejected defaults to KEEP for generic artifact classification.

H1: generic repeated text + stable position is not deletion authority.

GREEN owner: this remediation pass (``transform/build_semantic.py`` /
``transform/tables.py`` / ``transform/artifacts.py``).
"""

from __future__ import annotations

import pytest

import solari_converter.transform.artifacts as artifacts
import solari_converter.transform.build_semantic as build_semantic
import solari_converter.transform.reflow as reflow_mod
from solari_converter.model.semantic import (
    ParagraphBlock,
    SemanticDocument,
    TableBlock,
)
from solari_converter.transform.reflow import SegmentTransform
from solari_converter.transform.tables import LogicalTable, TableCell

from ._semantic_fixtures import Seg, ced

_violations = build_semantic.literal_accounting_violations
_partition = build_semantic.accepted_partition_violations


def _p(text: str, prov, *, transforms=()):
    return SemanticDocument(
        blocks=(
            ParagraphBlock(
                kind="paragraph", block_id="blk-x", text=text, provenance=tuple(prov)
            ),
        ),
        segment_transforms=tuple(transforms),
    )


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


def _table_cell_doc(sem_cell_prov, cell_text, literals, *, groups=()):
    segs = [
        Seg(sid, lit, (72, 100 + 16 * i, 260, 112 + 16 * i))
        for i, (sid, lit) in enumerate(literals.items())
    ]
    doc = ced(segs)
    cell = TableCell(text=cell_text, provenance=tuple(sem_cell_prov), row=0, column=0)
    table = LogicalTable(
        table_id="tbl-x", rows=[[cell]], has_merged_cells=False,
        header_row_count=1, spans_pages=[1],
    )
    block = TableBlock(
        kind="table", block_id="blk-x", table=table,
        provenance=tuple(sem_cell_prov), hint_decisions=(),
    )
    sem = SemanticDocument(
        blocks=(block,), table_identical_evidence_groups=tuple(groups)
    )
    return sem, doc


# --- B1: full-carrier attribution ---------------------------------------------------


def test_carrier_wider_than_its_only_source_literal_fails():
    doc = ced([Seg("s", "abc", (72, 100, 200, 112))])
    assert _violations(_p("xabcx", ("s",)), doc) == ["s"]


def test_one_carrier_where_a_second_segment_supplied_the_first_segments_substring_fails():
    doc = ced([
        Seg("s1", "abc", (72, 100, 200, 112)),
        Seg("s2", "xabcx", (72, 116, 200, 128)),
    ])
    assert _violations(_p("xabcx", ("s1", "s2")), doc)


def test_duplicate_identical_source_literals_collapsed_to_one_occurrence_fail():
    doc = ced([
        Seg("s1", "abc", (72, 100, 200, 112)),
        Seg("s2", "abc", (72, 116, 200, 128)),
    ])
    assert _violations(_p("abc", ("s1", "s2")), doc)


def test_duplicate_identical_literals_pass_only_with_table_identical_evidence_lineage():
    ok_sem, doc = _table_cell_doc(
        ("s1", "s2"), "abc", {"s1": "abc", "s2": "abc"},
        groups=(frozenset({"s1", "s2"}),),
    )
    assert _violations(ok_sem, doc) == []

    no_lineage, doc2 = _table_cell_doc(("s1", "s2"), "abc", {"s1": "abc", "s2": "abc"})
    assert _violations(no_lineage, doc2)  # generic duplicate provenance is not enough


@pytest.mark.parametrize(
    "delivered",
    [
        "PREFIX total due",   # prefix insertion
        "total due SUFFIX",   # suffix insertion
        "total XXX due",      # interior insertion
        "total",              # truncation
        "TOTALLY DIFFERENT",  # replacement
    ],
)
def test_single_source_carrier_must_reconstruct_codepoint_exact(delivered):
    doc = ced([Seg("s", "total due", (72, 100, 200, 112))])
    assert _violations(_p(delivered, ("s",)), doc) == ["s"]


def test_correct_default_and_reflow_whitespace_joins_reconstruct_exactly():
    doc = ced([
        Seg("a", "first part", (72, 100, 160, 112)),
        Seg("b", "second part", (72, 113, 200, 125)),
    ])
    assert _violations(_p("first part second part", ("a", "b")), doc) == []
    assert _violations(
        _p("first part second part", ("a", "b"),
           transforms=(_reflow_ws(("a", "b"), "b"),)),
        doc,
    ) == []


def test_real_build_threads_table_identical_evidence_and_accepts_it():
    doc = ced([
        _tc("h0", "H1", 72, 100), _tc("h1", "H2", 162, 100),
        _tc("a", "A", 72, 120), _tc("b", "B", 162, 120),
        _tc("a2", "A", 72, 120),  # byte-identical, same anchor as "a"
    ])
    sem = build_semantic.build_semantic(doc)
    assert sem.table_identical_evidence_groups
    assert any({"a", "a2"} <= g for g in sem.table_identical_evidence_groups)
    assert _violations(sem, doc) == []
    assert _partition(sem, doc) == {}


# --- B2: dehyphenation contract ---------------------------------------------------


def test_dehyphenate_valid_exact_case():
    doc = ced([
        Seg("l", "inter-", (72, 100, 110, 112)),
        Seg("r", "national", (72, 113, 160, 125)),
    ])
    sem = _p("international", ("l", "r"), transforms=(_deh(("l", "r"), "r"),))
    assert _violations(sem, doc) == []


def test_dehyphenate_wrong_joined_with_fails():
    doc = ced([
        Seg("l", "inter-", (72, 100, 110, 112)),
        Seg("r", "national", (72, 113, 160, 125)),
    ])
    sem = _p("international", ("l", "r"), transforms=(_deh(("l", "r"), "zzz"),))
    assert _violations(sem, doc)


@pytest.mark.parametrize("kw", [{"permitted_by": "FR-999"}, {"stage": 5}])
def test_dehyphenate_wrong_rule_or_stage_fails(kw):
    doc = ced([
        Seg("l", "inter-", (72, 100, 110, 112)),
        Seg("r", "national", (72, 113, 160, 125)),
    ])
    sem = _p("international", ("l", "r"), transforms=(_deh(("l", "r"), "r", **kw),))
    assert _violations(sem, doc)


def test_dehyphenate_unrelated_segment_ids_do_not_influence_a_clean_carrier():
    doc = ced([
        Seg("l", "inter-", (72, 100, 110, 112)),
        Seg("r", "national", (72, 113, 160, 125)),
        Seg("q1", "x-", (72, 200, 90, 212)),
        Seg("q2", "y", (72, 213, 90, 225)),
    ])
    # the carrier keeps its hyphen (no dehyphenation applied to it) and reconstructs
    # exactly; a dehyphenate record naming q1/q2 must not implicate l or r.
    sem = _p("inter-national", ("l", "r"), transforms=(_deh(("q1", "q2"), "q2"),))
    v = _violations(sem, doc)
    assert "l" not in v and "r" not in v


def test_dehyphenate_left_without_trailing_hyphen_fails():
    doc = ced([
        Seg("l", "inter", (72, 100, 110, 112)),
        Seg("r", "national", (72, 113, 160, 125)),
    ])
    sem = _p("international", ("l", "r"), transforms=(_deh(("l", "r"), "r"),))
    assert "l" in _violations(sem, doc)


def test_dehyphenate_with_extra_deletion_fails():
    doc = ced([
        Seg("l", "inter-", (72, 100, 110, 112)),
        Seg("r", "national", (72, 113, 160, 125)),
    ])
    sem = _p("interational", ("l", "r"), transforms=(_deh(("l", "r"), "r"),))
    assert _violations(sem, doc)


def test_dehyphenate_participants_split_across_two_carriers_fails():
    doc = ced([
        Seg("l", "inter-", (72, 100, 110, 112)),
        Seg("r", "national", (72, 113, 160, 125)),
    ])
    sem = SemanticDocument(
        blocks=(
            ParagraphBlock(kind="paragraph", block_id="b1", text="inter-", provenance=("l",)),
            ParagraphBlock(kind="paragraph", block_id="b2", text="national", provenance=("r",)),
        ),
        segment_transforms=(_deh(("l", "r"), "r"),),
    )
    assert "l" in _violations(sem, doc)


def test_three_segment_carrier_with_exactly_one_valid_dehyphenation():
    doc = ced([
        Seg("a", "The word", (72, 100, 140, 112)),
        Seg("b", "inter-", (72, 113, 160, 125)),
        Seg("c", "national.", (72, 126, 200, 138)),
    ])
    sem = _p(
        "The word international.", ("a", "b", "c"),
        transforms=(_reflow_ws(("a", "b"), "b"), _deh(("a", "b", "c"), "c")),
    )
    assert _violations(sem, doc) == []


# --- B3: raw terminal-ownership partition ---------------------------------------------


def test_partition_flags_a_cell_owned_id_that_is_also_collapsed():
    doc = ced([Seg("h", "Date", (72, 60, 120, 72)), Seg("c", "Date", (72, 200, 120, 212))])
    cell = TableCell(text="Date", provenance=("h", "c"), row=0, column=0)
    table = LogicalTable(
        table_id="tbl-x", rows=[[cell]], has_merged_cells=False,
        header_row_count=1, spans_pages=[1, 2],
    )
    block = TableBlock(
        kind="table", block_id="blk-x", table=table,
        provenance=("h", "c"), hint_decisions=(),
    )
    sem = SemanticDocument(blocks=(block,), collapsed_segment_ids=frozenset({"c"}))
    assert _partition(sem, doc).get("retained_and_collapsed") == ["c"]


def test_partition_flags_a_carrier_owned_id_that_is_also_removed():
    doc = ced([
        Seg("a", "x", (72, 100, 120, 112)),
        Seg("b", "y", (72, 120, 120, 132)),
    ])
    sem = SemanticDocument(
        blocks=(ParagraphBlock(kind="paragraph", block_id="b", text="x y",
                               provenance=("a", "b")),),
        removed_segment_ids=frozenset({"b"}),
    )
    assert _partition(sem, doc).get("retained_and_removed") == ["b"]


def test_partition_flags_collapsed_and_removed_overlap():
    doc = ced([
        Seg("a", "x", (72, 100, 120, 112)),
        Seg("z", "z", (72, 120, 120, 132)),
    ])
    sem = SemanticDocument(
        blocks=(ParagraphBlock(kind="paragraph", block_id="b", text="x", provenance=("a",)),),
        collapsed_segment_ids=frozenset({"z"}),
        removed_segment_ids=frozenset({"z"}),
    )
    assert _partition(sem, doc).get("collapsed_and_removed") == ["z"]


def test_partition_flags_an_accepted_id_in_no_terminal_set():
    doc = ced([
        Seg("a", "x", (72, 100, 120, 112)),
        Seg("lost", "y", (72, 120, 120, 132)),
    ])
    sem = SemanticDocument(
        blocks=(ParagraphBlock(kind="paragraph", block_id="b", text="x", provenance=("a",)),),
    )
    assert _partition(sem, doc).get("absent") == ["lost"]


def test_partition_flags_a_terminal_id_not_in_accepted():
    doc = ced([Seg("a", "x", (72, 100, 120, 112))])
    sem = SemanticDocument(
        blocks=(ParagraphBlock(kind="paragraph", block_id="b", text="x", provenance=("a",)),),
        removed_segment_ids=frozenset({"ghost-removed"}),
    )
    assert _partition(sem, doc).get("not_accepted") == ["ghost-removed"]


def test_partition_holds_for_valid_stitched_table_cell_ownership():
    def grid(rows, page, top0):
        return [
            _tc(f"p{page}r{r}c{c}", v, 72 + 90 * c, top0 + 14 * r, page=page)
            for r, row in enumerate(rows) for c, v in enumerate(row)
        ]

    doc = ced(
        grid([["Date", "Amount"], ["2026-01-01", "100.00"]], 1, 60)
        + grid([["Date", "Amount"], ["2026-02-01", "200.00"]], 2, 60)
    )
    sem = build_semantic.build_semantic(doc)
    assert sem.collapsed_segment_ids  # header collapsed
    assert _partition(sem, doc) == {}
    raw = {sid for b in sem.blocks for _t, prov in build_semantic._carrier_units(b)
           for sid in prov}
    assert raw.isdisjoint(sem.collapsed_segment_ids)


# --- B4: rejected-table fallback ----------------------------------------------------


def _rejected_region(literal_a, literal_b, *, page):
    """Two same-anchor table_cell-hinted segments with distinct literals →
    ``same_anchor_literal_collision`` → the whole fragment is rejected and the region
    flows to ordinary prose. ``literal_a`` sits at the page's top extreme."""
    return ced([
        _tc("pa", literal_a, 72, 30, page=page),
        _tc("pb", literal_b, 72, 30, page=page),   # same anchor as pa
        _tc("h1", "Col", 200, 30, page=page),
        _tc("r0", "row data", 72, 60, page=page),
        _tc("r1", "more data", 200, 60, page=page),
    ])


@pytest.mark.parametrize(
    ("lit_a", "lit_b", "page"),
    [("1", "1.00", 1), ("2", "2.00", 2), ("Page 3", "Page 4", 3)],
)
def test_rejected_table_pageish_literal_survives_semantic_fallback(lit_a, lit_b, page):
    doc = _rejected_region(lit_a, lit_b, page=page)
    sem = build_semantic.build_semantic(doc)

    assert not any(b.kind == "table" for b in sem.blocks)
    assert sem.table_owned_segment_ids == frozenset()
    assert "pa" not in sem.removed_segment_ids
    assert "pb" not in sem.removed_segment_ids
    texts = {getattr(b, "text", None) for b in sem.blocks}
    assert lit_a in texts and lit_b in texts
    # the not-removed decision is recorded, never silent
    assert sem.removal_log is not None
    pa_kept = [
        e for e in sem.removal_log.entries
        if e.text_excerpt == lit_a and e.kept_due_to_ambiguity
    ]
    assert pa_kept
    assert _partition(sem, doc) == {}
    assert _violations(sem, doc) == []


def test_page_number_outside_a_rejected_region_is_still_removed():
    doc = ced([
        Seg("body", "Real content here.", (72, 100, 300, 112), page=1),
        Seg("pnum", "1", (280, 40, 300, 52), page=1),  # top margin, value == physical page
    ])
    sem = build_semantic.build_semantic(doc)
    assert "pnum" in sem.removed_segment_ids


def test_rejected_region_with_repeated_top_text_across_pages_is_kept():
    segs = []
    for page in (1, 2):
        segs += [
            _tc(f"pa{page}", "1", 72, 30, page=page),
            _tc(f"pb{page}", "1.00", 72, 30, page=page),
            _tc(f"h{page}", "Col", 200, 30, page=page),
            _tc(f"r0{page}", "row data", 72, 60, page=page),
            _tc(f"r1{page}", "more data", 200, 60, page=page),
        ]
    doc = ced(segs)
    sem = build_semantic.build_semantic(doc)
    kept = {sid for b in sem.blocks for sid in b.provenance}
    assert {"pa1", "pa2", "pb1", "pb2"} <= kept
    assert not sem.removed_segment_ids
    assert _violations(sem, doc) == []
    assert _partition(sem, doc) == {}


# --- H1: generic repeated furniture is never auto-removed ---------------------------


def _artifacts_run(segs, *, order=None):
    doc = ced(segs, order=order or [s.sid for s in segs])
    return artifacts.remove_artifacts(doc, reflow_mod.reflow(doc))


def _kept(result):
    return {s for u in result.kept_units for s in u.segment_ids}


@pytest.mark.parametrize("npages", [3, 4, 6])
def test_repeated_terms_and_conditions_banner_is_kept(npages):
    segs = []
    for p in range(1, npages + 1):
        segs.append(Seg(f"t{p}", "Terms and Conditions", (72, 30, 300, 42), page=p))
        segs.append(Seg(f"b{p}", f"Body {p}.", (72, 120, 300, 132), page=p))
    result = _artifacts_run(segs)
    assert {f"t{p}" for p in range(1, npages + 1)} <= _kept(result)
    hdr = [e for e in result.removal_log.entries if e.entry_type == "running_header"]
    assert hdr and all(e.ambiguous for e in hdr)
    assert all("H1" in (e.note or "") for e in hdr)


def test_repeated_section_title_is_kept():
    segs = []
    for p in (1, 2, 3):
        segs.append(Seg(f"s{p}", "SCHEDULE A", (72, 30, 300, 42), page=p,
                        hints=[("heading", 1, "docling")]))
        segs.append(Seg(f"b{p}", f"Body {p}.", (72, 120, 300, 132), page=p))
    result = _artifacts_run(segs)
    assert {"s1", "s2", "s3"} <= _kept(result)


def test_repeated_short_author_text_is_kept():
    segs = []
    for p in (1, 2, 3):
        segs.append(Seg(f"n{p}", "cont.", (72, 30, 110, 42), page=p))
        segs.append(Seg(f"b{p}", f"Body {p}.", (72, 120, 300, 132), page=p))
    result = _artifacts_run(segs)
    assert {"n1", "n2", "n3"} <= _kept(result)
    hdr = [e for e in result.removal_log.entries if e.entry_type == "running_header"]
    assert hdr and all(e.ambiguous for e in hdr)


def test_generic_furniture_keep_decisions_are_deterministic():
    segs = []
    for p in (1, 2, 3):
        segs.append(Seg(f"t{p}", "Terms and Conditions", (72, 30, 300, 42), page=p))
        segs.append(Seg(f"b{p}", f"Body {p}.", (72, 120, 300, 132), page=p))
    order = [s.sid for s in segs]
    a = _artifacts_run(segs, order=order)
    b = _artifacts_run(list(reversed(segs)), order=order)
    assert [e.id for e in a.removal_log.entries] == [e.id for e in b.removal_log.entries]
    assert [e.note for e in a.removal_log.entries] == [e.note for e in b.removal_log.entries]
    assert _kept(a) == _kept(b)


def test_evidenced_page_number_still_removed_alongside_kept_generic_header():
    segs = []
    for p in (1, 2, 3):
        segs.append(Seg(f"h{p}", "CONFIDENTIAL DRAFT", (72, 30, 300, 42), page=p))
        segs.append(Seg(f"b{p}", f"Body {p}.", (72, 120, 300, 132), page=p))
        segs.append(Seg(f"pg{p}", f"Page {p}", (250, 760, 320, 772), page=p))
    result = _artifacts_run(segs)
    assert {"h1", "h2", "h3"} <= _kept(result)
    assert {"pg1", "pg2", "pg3"}.isdisjoint(_kept(result))
