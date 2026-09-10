"""Independent-gate remediation for the T075–T078 Codex final gate (three HIGHs).

Each HIGH is closed with test-first adversarial coverage:

* **HIGH 1 / R1** — a Markdown **pipe-table** cell neutralises authored ``<`` / ``>`` /
  ``&`` (as HTML entities) on top of the existing backslash / pipe / backtick / ``*`` /
  ``_`` / multiline escaping, so authored raw HTML can never become active
  Markdown/HTML syntax, and the renderer's own generated escapes are never
  double-escaped (``render/markdown.py``);
* **HIGH 2 / R2+R3** — the Stage-4 deterministic validator only lets a ``dehyphenate``
  transform account for a joined line-boundary surface when the record satisfies the
  **frozen** T066–T074 semantic lineage contract against the real carriers / CED
  literals (``transform.build_semantic.authenticated_dehyphenations``). A forged record
  (wrong ``stage`` / ``permitted_by``, unknown / unrelated / reordered / duplicated
  participant ids, a forged ``joined_with``, cross-carrier lineage, a conflicting twin)
  can no longer suppress a missing-content coverage defect or a reading-order defect;
* **HIGH 3 / R5** — deterministic HTML-/pipe-table validation verifies each rendered
  cell's **text** at its **logical row / column** against the authoritative
  ``LogicalTable`` (accounting only for the renderer's own escaping / whitespace-trim
  contract): a swapped, moved, edited, missing, or extra cell — and any wrong
  ``rowspan`` / ``colspan`` — now fails.
"""

from __future__ import annotations

from dataclasses import replace

from solari_converter.model.semantic import (
    ParagraphBlock,
    SemanticDocument,
    block_id,
)
from solari_converter.render.markdown import _pipe_cell, render_markdown
from solari_converter.transform.build_semantic import (
    authenticated_dehyphenations,
    build_semantic,
)
from solari_converter.transform.reflow import SegmentTransform
from solari_converter.transform.tables import LogicalTable, TableBlock, TableCell
from solari_converter.validate.deterministic import (
    _pipe_cell_unescape,
    run_deterministic_checks,
)

from ._semantic_fixtures import Seg, ced

# --------------------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------------------


def _para(text: str, prov=("p1",)) -> ParagraphBlock:
    return ParagraphBlock(
        kind="paragraph", block_id=block_id("paragraph", prov), text=text,
        provenance=tuple(prov),
    )


def _doc(*blocks) -> SemanticDocument:
    return SemanticDocument(blocks=tuple(blocks))


def _run(**kw):
    base = dict(candidates=(), ocr_confidence_threshold=70.0,
               gross_divergence_threshold=0.5)
    base.update(kw)
    return run_deterministic_checks(**base)


def _types(result) -> set[str]:
    return {i.issue_type for i in result.issues}


def _table(rows_text, *, prov, merged=False, spans=None) -> TableBlock:
    """A table block whose cell provenance ids are ``prov[r][c]`` — one accepted
    segment id per authored cell (``spans`` optionally overrides (rowspan, colspan) as
    ``{(r, c): (rs, cs)}``)."""
    spans = spans or {}
    rows = []
    for r, row in enumerate(rows_text):
        cells = []
        for c, v in enumerate(row):
            rs, cs = spans.get((r, c), (1, 1))
            cells.append(
                TableCell(text=v, provenance=(prov[r][c],), row=r, column=c,
                          rowspan=rs, colspan=cs, is_header=(r == 0))
            )
        rows.append(cells)
    flat = tuple(pid for row in prov for pid in row)
    return TableBlock(
        kind="table", block_id=block_id("table", flat),
        table=LogicalTable(table_id="tbl", rows=rows, has_merged_cells=merged,
                           header_row_count=1, spans_pages=[1]),
        provenance=flat, hint_decisions=(),
    )


def _cells_ced(rows_text, prov, page=1):
    segs = []
    for r, row in enumerate(rows_text):
        for c, v in enumerate(row):
            segs.append(Seg(prov[r][c], v, (72 + c * 40, 60 + r * 14,
                                            100 + c * 40, 72 + r * 14), page=page))
    return segs


# ======================================================================================
# HIGH 1 / R1 — pipe-table cell HTML-character neutralisation
# ======================================================================================


def _one_cell_pipe_md(text: str) -> str:
    """Render a 2×2 pipe table whose single data cell (row 1, column 0) is ``text``;
    return the data-row line."""
    tb = _table([["h0", "h1"], [text, "ok"]],
                prov=[["a", "b"], ["x", "y"]])
    md = render_markdown(_doc(tb))
    return next(ln for ln in md.splitlines()
               if ln.startswith("| ") and "ok" in ln and "h1" not in ln)


def test_r1_pipe_cell_html_tag_and_ampersand_are_inert():
    row = _one_cell_pipe_md("<b>x</b> & y")
    assert row == "| &lt;b&gt;x&lt;/b&gt; &amp; y | ok |"
    assert "<b>" not in row and "</b>" not in row


def test_r1_pipe_cell_bare_lt_gt_amp():
    assert _one_cell_pipe_md("<") == "| &lt; | ok |"
    assert _one_cell_pipe_md(">") == "| &gt; | ok |"
    assert _one_cell_pipe_md("&") == "| &amp; | ok |"


def test_r1_pipe_cell_mixed_html_significant_run():
    assert _one_cell_pipe_md("A & B < C > D") == "| A &amp; B &lt; C &gt; D | ok |"


def test_r1_pipe_cell_html_chars_combined_with_markdown_specials():
    row = _one_cell_pipe_md(r"<i>|x| *b* `c` \d & _e_ >")
    assert row == r"| &lt;i&gt;\|x\| \*b\* \`c\` \\d &amp; \_e\_ &gt; | ok |"
    for tag in ("<i>", "*b*", "`c`", "_e_"):
        assert tag not in row


def test_r1_pipe_cell_multiline_content_with_html_chars():
    row = _one_cell_pipe_md("first <x>\nsecond & third > end")
    assert row == "| first &lt;x&gt;<br>second &amp; third &gt; end | ok |"
    assert "\n" not in row.strip("|").strip()


def test_r1_pipe_cell_does_not_double_escape_generated_escapes():
    # an already-entity-looking author literal is preserved, not collapsed
    assert _pipe_cell("&amp;") == "&amp;amp;"
    assert _pipe_cell("&lt;") == "&amp;lt;"
    # a single '&' followed by a real pipe: entity first, then the structural escape
    assert _pipe_cell("&|") == r"&amp;\|"


def test_r1_pipe_cell_escaping_is_an_exact_invertible_contract():
    for authored in (
        "<b>x</b> & y", "A & B < C > D", r"<i>|x| *b* `c` \d & _e_ >",
        "first <x>\nsecond & third > end", "plain text", "&amp; &lt; &gt;",
        r"weird \\ & << >> || ``",
    ):
        assert _pipe_cell_unescape(_pipe_cell(authored)) == authored


def test_r1_pipe_cell_html_render_cannot_activate_authored_markup():
    md = render_markdown(_doc(_table(
        [["Col"], ["<script>alert(1)</script> & <b>bold</b>"]],
        prov=[["h"], ["d"]],
    )))
    assert "<script>" not in md
    assert "<b>" not in md
    assert "&lt;script&gt;alert(1)&lt;/script&gt; &amp; &lt;b&gt;bold&lt;/b&gt;" in md


# ======================================================================================
# HIGH 2 / R2+R3 — forged dehyphenation transforms cannot suppress defects
# ======================================================================================


def _join_ced():
    return ced(
        [
            Seg("a", "The zone remains trans-", (72, 100, 300, 112)),
            Seg("b", "national under active review.", (72, 112, 300, 124)),
            Seg("c", "A separate closing statement follows here.", (72, 150, 420, 162)),
        ],
        order=["a", "b", "c"],
    )


def _joined_semantic(*transforms) -> SemanticDocument:
    """The render joined ``a`` + ``b`` into one paragraph; ``c`` is a second paragraph.
    ``transforms`` are the (possibly forged) ``dehyphenate`` records under test."""
    return SemanticDocument(
        blocks=(
            _para("The zone remains transnational under active review.", ("a", "b")),
            _para("A separate closing statement follows here.", ("c",)),
        ),
        segment_transforms=tuple(transforms),
    )


_VALID_JOIN = SegmentTransform(
    kind="dehyphenate", permitted_by="FR-014", segment_ids=("a", "b"),
    joined_with="b", boundary="a/b", stage=3,
)

# every forged variant still names participant ``a`` — under the pre-remediation code
# each one removed ``a`` (and its neighbour) from the checks and so suppressed a defect.
_FORGERIES = {
    "wrong_stage": replace(_VALID_JOIN, stage=99),
    "wrong_permitted_by": replace(_VALID_JOIN, permitted_by="FR-999"),
    "unknown_participant": replace(_VALID_JOIN, segment_ids=("a", "ghost"),
                                  joined_with="ghost"),
    "unrelated_extra_participant": replace(_VALID_JOIN, segment_ids=("a", "c", "b")),
    "reordered_participants": replace(_VALID_JOIN, segment_ids=("b", "a"),
                                     joined_with="a"),
    "duplicate_participant_id": replace(_VALID_JOIN, segment_ids=("a", "a", "b")),
    "wrong_joined_with": replace(_VALID_JOIN, joined_with="a"),
    "cross_carrier_lineage": replace(_VALID_JOIN, segment_ids=("a", "c"),
                                     joined_with="c"),
}


def test_h2_valid_producer_compatible_join_authenticates_and_passes_coverage():
    d = _join_ced()
    sem = _joined_semantic(_VALID_JOIN)
    assert authenticated_dehyphenations(sem, d) == (_VALID_JOIN,)
    md = render_markdown(sem)
    r = _run(markdown=md, semantic=sem, ced=d)
    assert r.source_text_match_rate == 1.0
    assert r.missing_tokens == ()
    assert "missing_content" not in _types(r)


def test_h2_real_build_semantic_join_authenticates():
    d = ced(
        [
            Seg("a", "The treaty is inter-", (72, 100, 240, 112)),
            Seg("b", "national in effect.", (72, 112, 240, 124)),
            Seg("c", "Every international clause applies.", (72, 160, 320, 172)),
        ],
        order=["a", "b", "c"],
    )
    sem = build_semantic(d)
    got = authenticated_dehyphenations(sem, d)
    assert [t.kind for t in got] == ["dehyphenate"]
    assert got[0].segment_ids[-1] == got[0].joined_with


def _forgery_names():
    return sorted(_FORGERIES)


def test_h2_each_forged_join_is_rejected_by_the_authenticator():
    d = _join_ced()
    for name in _forgery_names():
        sem = _joined_semantic(_FORGERIES[name])
        assert authenticated_dehyphenations(sem, d) == (), name


def test_h2_conflicting_duplicate_valid_records_are_both_rejected():
    d = _join_ced()
    sem = _joined_semantic(_VALID_JOIN, replace(_VALID_JOIN, boundary="dup"))
    assert authenticated_dehyphenations(sem, d) == ()


def test_h2_forged_join_cannot_suppress_missing_content_coverage_defect():
    d = _join_ced()
    base = _joined_semantic()  # no transform at all → the join is unrecorded
    md = render_markdown(base)  # renders "...transnational under active review."
    # baseline: with no accounting record the two joined source surfaces are missing
    baseline = _run(markdown=md, semantic=base, ced=d)
    assert {"trans", "national"} <= set(baseline.missing_tokens)

    for name in _forgery_names():
        sem = _joined_semantic(_FORGERIES[name])
        r = _run(markdown=md, semantic=sem, ced=d)
        assert {"trans", "national"} <= set(r.missing_tokens), name
        assert "missing_content" in _types(r), name

    # and a conflicting-duplicate pair likewise cannot suppress it
    sem = _joined_semantic(_VALID_JOIN, replace(_VALID_JOIN, boundary="dup"))
    r = _run(markdown=md, semantic=sem, ced=d)
    assert {"trans", "national"} <= set(r.missing_tokens)


def _ro_ced():
    return ced(
        [
            Seg("a", "First distinct alpha sentence sits here.", (72, 100, 400, 114)),
            Seg("b", "Second distinct bravo sentence sits here.", (72, 130, 400, 144)),
            Seg("c", "Third distinct charlie sentence sits here.", (72, 160, 400, 174)),
        ],
        order=["a", "b", "c"],
    )


def _ro_semantic(*transforms) -> SemanticDocument:
    # the render inverts a and b (b before a) — an unlogged reading-order violation
    return SemanticDocument(
        blocks=(
            _para("Second distinct bravo sentence sits here.", ("b",)),
            _para("First distinct alpha sentence sits here.", ("a",)),
            _para("Third distinct charlie sentence sits here.", ("c",)),
        ),
        segment_transforms=tuple(transforms),
    )


def _ro_source():
    return {1: "First distinct alpha sentence sits here. "
               "Second distinct bravo sentence sits here. "
               "Third distinct charlie sentence sits here."}


def test_h2_unlogged_inversion_is_a_reading_order_defect_without_any_transform():
    d = _ro_ced()
    sem = _ro_semantic()
    r = _run(markdown=render_markdown(sem), semantic=sem, ced=d,
             source_page_text=_ro_source())
    assert "reading_order" in _types(r)


def test_h2_forged_join_cannot_suppress_reading_order_defect():
    d = _ro_ced()
    for name in _forgery_names():
        sem = _ro_semantic(_FORGERIES[name])
        r = _run(markdown=render_markdown(sem), semantic=sem, ced=d,
                 source_page_text=_ro_source())
        assert "reading_order" in _types(r), name

    sem = _ro_semantic(_VALID_JOIN, replace(_VALID_JOIN, boundary="dup"))
    r = _run(markdown=render_markdown(sem), semantic=sem, ced=d,
             source_page_text=_ro_source())
    assert "reading_order" in _types(r)


def test_h2_authentic_join_still_suppresses_a_false_reading_order_inversion():
    # a legitimately joined pair must NOT be independently localised (R3) — no false
    # positive when the two source surfaces no longer appear on their own
    d = _join_ced()
    sem = _joined_semantic(_VALID_JOIN)
    r = _run(markdown=render_markdown(sem), semantic=sem, ced=d)
    assert "reading_order" not in _types(r)


# ======================================================================================
# HIGH 3 / R5 — rendered table cell text + logical position vs the LogicalTable
# ======================================================================================


def _pipe_pair():
    rows = [["A", "B"], ["C", "D"]]
    prov = [["h0", "h1"], ["d0", "d1"]]
    sem = _doc(_table(rows, prov=prov))
    d = ced(_cells_ced(rows, prov))
    return sem, d, render_markdown(sem)


def test_r5_faithful_pipe_table_raises_no_cell_issue():
    sem, d, md = _pipe_pair()
    r = _run(markdown=md, semantic=sem, ced=d,
             source_page_text={1: "A B C D"})
    assert "literal_mismatch" not in _types(r)
    assert "table_shape" not in _types(r)


def test_r5_swapped_cells_fail_even_with_identical_geometry():
    sem, d, md = _pipe_pair()
    mutated = md.replace("| C | D |", "| D | C |")
    r = _run(markdown=mutated, semantic=sem, ced=d,
             source_page_text={1: "A B C D"})
    assert "literal_mismatch" in _types(r)
    assert "table_shape" not in _types(r)  # counts / tags / spans unchanged
    lm = [i for i in r.issues if i.issue_type == "literal_mismatch"]
    assert {i.expected for i in lm} == {"C", "D"}


def test_r5_modified_cell_text_fails():
    sem, d, md = _pipe_pair()
    r = _run(markdown=md.replace("| C | D |", "| C-EDITED | D |"), semantic=sem,
             ced=d, source_page_text={1: "A B C D"})
    lm = [i for i in r.issues if i.issue_type == "literal_mismatch"]
    assert any(i.expected == "C" and i.found == "C-EDITED" for i in lm)


def test_r5_cell_moved_to_a_different_logical_column_fails():
    rows = [["A", "B", "C"], ["1", "2", "3"]]
    prov = [["h0", "h1", "h2"], ["d0", "d1", "d2"]]
    sem = _doc(_table(rows, prov=prov))
    d = ced(_cells_ced(rows, prov))
    md = render_markdown(sem)
    # move "2" from column 1 to column 2 and "3" to column 1 (spans untouched)
    r = _run(markdown=md.replace("| 1 | 2 | 3 |", "| 1 | 3 | 2 |"), semantic=sem,
             ced=d, source_page_text={1: "A B C 1 2 3"})
    lm = {i.expected for i in r.issues if i.issue_type == "literal_mismatch"}
    assert {"2", "3"} <= lm


def test_r5_missing_cell_fails():
    sem, d, md = _pipe_pair()
    r = _run(markdown=md.replace("| C | D |", "| C |"), semantic=sem, ced=d,
             source_page_text={1: "A B C D"})
    assert "table_shape" in _types(r)


def test_r5_extra_cell_fails():
    sem, d, md = _pipe_pair()
    r = _run(markdown=md.replace("| C | D |", "| C | D | E |"), semantic=sem, ced=d,
             source_page_text={1: "A B C D E"})
    assert "table_shape" in _types(r)


def _span_table():
    tb = TableBlock(
        kind="table", block_id="blk-span",
        table=LogicalTable(
            table_id="tbl-span",
            rows=[
                [TableCell(text="Region", provenance=("s_h",), row=0, column=0,
                           colspan=2, is_header=True)],
                [TableCell(text="North", provenance=("s_l",), row=1, column=0),
                 TableCell(text="South", provenance=("s_r",), row=1, column=1)],
            ],
            has_merged_cells=True, header_row_count=1, spans_pages=[2],
        ),
        provenance=("s_h", "s_l", "s_r"), hint_decisions=(),
    )
    d = ced(
        [
            Seg("s_h", "Region", (72, 60, 200, 72), page=2),
            Seg("s_l", "North", (72, 74, 130, 86), page=2),
            Seg("s_r", "South", (140, 74, 200, 86), page=2),
        ],
        order=["s_h", "s_l", "s_r"],
    )
    return _doc(tb), d, render_markdown(_doc(tb))


def test_r5_faithful_html_span_table_raises_no_issue():
    sem, d, md = _span_table()
    r = _run(markdown=md, semantic=sem, ced=d, source_page_text={2: "Region North South"})
    assert "literal_mismatch" not in _types(r)
    assert "table_shape" not in _types(r)


def test_r5_html_span_table_swapped_body_cells_fail():
    sem, d, md = _span_table()
    mutated = md.replace("<td>North</td><td>South</td>",
                         "<td>South</td><td>North</td>")
    r = _run(markdown=mutated, semantic=sem, ced=d,
             source_page_text={2: "Region North South"})
    lm = {i.expected for i in r.issues if i.issue_type == "literal_mismatch"}
    assert {"North", "South"} <= lm


def test_r5_html_span_table_wrong_colspan_fails():
    sem, d, md = _span_table()
    r = _run(markdown=md.replace('colspan="2"', 'colspan="5"'), semantic=sem, ced=d,
             source_page_text={2: "Region North South"})
    assert any("colspan" in i.description for i in r.issues
               if i.issue_type == "table_shape")


def test_r5_html_span_table_wrong_rowspan_fails():
    rows = [
        [TableCell(text="H", provenance=("a",), row=0, column=0, colspan=2,
                   is_header=True)],
        [TableCell(text="L", provenance=("b",), row=1, column=0, rowspan=2),
         TableCell(text="r1", provenance=("c",), row=1, column=1)],
        [TableCell(text="r2", provenance=("d",), row=2, column=1)],
    ]
    tb = TableBlock(
        kind="table", block_id="blk-rs",
        table=LogicalTable(table_id="tbl-rs", rows=rows, has_merged_cells=True,
                           header_row_count=1, spans_pages=[1]),
        provenance=("a", "b", "c", "d"), hint_decisions=(),
    )
    sem = _doc(tb)
    d = ced(
        [
            Seg("a", "H", (72, 50, 120, 62)), Seg("b", "L", (72, 66, 90, 100)),
            Seg("c", "r1", (100, 66, 130, 78)), Seg("d", "r2", (100, 80, 130, 92)),
        ],
        order=["a", "b", "c", "d"],
    )
    md = render_markdown(sem).replace('rowspan="2"', 'rowspan="7"')
    r = _run(markdown=md, semantic=sem, ced=d, source_page_text={1: "H L r1 r2"})
    assert any("rowspan" in i.description for i in r.issues
               if i.issue_type == "table_shape")


def test_r5_html_span_table_escaped_cell_contents_roundtrip_and_mutation_fails():
    rows = [
        [TableCell(text="a<b>&c", provenance=("h",), row=0, column=0, colspan=2,
                   is_header=True)],
        [TableCell(text="x & y", provenance=("l",), row=1, column=0),
         TableCell(text="p < q > r", provenance=("rr",), row=1, column=1)],
    ]
    tb = TableBlock(
        kind="table", block_id="blk-esc",
        table=LogicalTable(table_id="tbl-esc", rows=rows, has_merged_cells=True,
                           header_row_count=1, spans_pages=[1]),
        provenance=("h", "l", "rr"), hint_decisions=(),
    )
    sem = _doc(tb)
    d = ced(
        [
            Seg("h", "a<b>&c", (72, 50, 200, 62)),
            Seg("l", "x & y", (72, 66, 120, 78)),
            Seg("rr", "p < q > r", (130, 66, 200, 78)),
        ],
        order=["h", "l", "rr"],
    )
    md = render_markdown(sem)
    assert "a&lt;b&gt;&amp;c" in md and "<b>" not in md
    ok = _run(markdown=md, semantic=sem, ced=d,
              source_page_text={1: "a<b>&c x & y p < q > r"})
    assert "literal_mismatch" not in _types(ok)
    # flip one escaped char in the rendered output → the authored cell no longer matches
    bad = md.replace("x &amp; y", "x &amp; z")
    r = _run(markdown=bad, semantic=sem, ced=d,
             source_page_text={1: "a<b>&c x & y p < q > r"})
    assert any(i.expected == "x & y" and i.found == "x & z" for i in r.issues
               if i.issue_type == "literal_mismatch")


def test_r5_html_span_table_multiline_cell_roundtrips_then_mutation_fails():
    rows = [
        [TableCell(text="Head", provenance=("h",), row=0, column=0, colspan=2,
                   is_header=True)],
        [TableCell(text="line one\nline two", provenance=("l",), row=1, column=0),
         TableCell(text="solo", provenance=("rr",), row=1, column=1)],
    ]
    tb = TableBlock(
        kind="table", block_id="blk-ml",
        table=LogicalTable(table_id="tbl-ml", rows=rows, has_merged_cells=True,
                           header_row_count=1, spans_pages=[1]),
        provenance=("h", "l", "rr"), hint_decisions=(),
    )
    sem = _doc(tb)
    d = ced(
        [
            Seg("h", "Head", (72, 50, 200, 62)),
            Seg("l", "line one line two", (72, 66, 160, 90)),
            Seg("rr", "solo", (170, 66, 200, 78)),
        ],
        order=["h", "l", "rr"],
    )
    md = render_markdown(sem)
    assert "line one<br>line two" in md
    ok = _run(markdown=md, semantic=sem, ced=d,
              source_page_text={1: "Head line one line two solo"})
    assert "literal_mismatch" not in _types(ok)
    bad = md.replace("line one<br>line two", "line one<br>line three")
    r = _run(markdown=bad, semantic=sem, ced=d,
             source_page_text={1: "Head line one line two solo"})
    assert any(i.issue_type == "literal_mismatch" for i in r.issues)


# ======================================================================================
# combined interaction regression — valid output is clean, each mutation is caught
# ======================================================================================


def _combined_ced():
    return ced(
        [
            Seg("d0", "The consolidated figure is inter-", (72, 60, 320, 72), page=1),
            Seg("d1", "national and fully audited.", (72, 74, 320, 86), page=1),
            Seg("d2", "Each international total stands at 1.599,80 today.",
                (72, 100, 420, 112), page=1),
            Seg("p_h0", "Tag", (72, 60, 120, 72), page=2),
            Seg("p_h1", "Note", (140, 60, 200, 72), page=2),
            Seg("p_d0", "<b>x</b>", (72, 74, 120, 86), page=2),
            Seg("p_d1", "a & b", (140, 74, 220, 86), page=2),
            Seg("s_h", "Region", (72, 60, 200, 72), page=3),
            Seg("s_l", "North", (72, 74, 130, 86), page=3),
            Seg("s_r", "South", (140, 74, 200, 86), page=3),
        ],
        order=["d0", "d1", "d2", "p_h0", "p_h1", "p_d0", "p_d1", "s_h", "s_l", "s_r"],
    )


def _combined_semantic() -> SemanticDocument:
    para_join = _para(
        "The consolidated figure is international and fully audited.", ("d0", "d1")
    )
    para_num = _para("Each international total stands at 1.599,80 today.", ("d2",))
    pipe_tbl = _table([["Tag", "Note"], ["<b>x</b>", "a & b"]],
                      prov=[["p_h0", "p_h1"], ["p_d0", "p_d1"]])
    span_tbl = TableBlock(
        kind="table", block_id="blk-cs",
        table=LogicalTable(
            table_id="tbl-cs",
            rows=[
                [TableCell(text="Region", provenance=("s_h",), row=0, column=0,
                           colspan=2, is_header=True)],
                [TableCell(text="North", provenance=("s_l",), row=1, column=0),
                 TableCell(text="South", provenance=("s_r",), row=1, column=1)],
            ],
            has_merged_cells=True, header_row_count=1, spans_pages=[3],
        ),
        provenance=("s_h", "s_l", "s_r"), hint_decisions=(),
    )
    return SemanticDocument(
        blocks=(para_join, para_num, pipe_tbl, span_tbl),
        segment_transforms=(
            SegmentTransform(
                kind="dehyphenate", permitted_by="FR-014", segment_ids=("d0", "d1"),
                joined_with="d1", boundary="d0/d1", stage=3,
            ),
        ),
    )


def _combined_source():
    return {
        1: "The consolidated figure is inter- national and fully audited. "
           "Each international total stands at 1.599,80 today.",
        2: "Tag Note <b>x</b> a & b",
        3: "Region North South",
    }


def test_combined_valid_output_is_clean():
    sem = _combined_semantic()
    d = _combined_ced()
    assert len(authenticated_dehyphenations(sem, d)) == 1
    md = render_markdown(sem)
    assert "&lt;b&gt;x&lt;/b&gt;" in md and "<b>" not in md
    r = _run(markdown=md, semantic=sem, ced=d, source_page_text=_combined_source())
    assert r.issues == ()
    assert r.source_text_match_rate == 1.0
    assert r.gross_divergence is False


def test_combined_each_single_defect_mutation_is_caught_without_masking():
    sem = _combined_semantic()
    d = _combined_ced()
    src = _combined_source()
    base = render_markdown(sem)

    # HIGH 1 surface: flip an escaped pipe-cell HTML char in the render
    m1 = base.replace("&lt;b&gt;x&lt;/b&gt;", "&lt;b&gt;z&lt;/b&gt;")
    r1 = _run(markdown=m1, semantic=sem, ced=d, source_page_text=src)
    assert any(i.expected == "<b>x</b>" and i.found == "<b>z</b>" for i in r1.issues
               if i.issue_type == "literal_mismatch")

    # HIGH 2 surface: forge the dehyphenation record → the dropped join surfaces show
    forged_sem = replace(
        sem,
        segment_transforms=(replace(sem.segment_transforms[0], permitted_by="FR-999"),),
    )
    r2 = _run(markdown=base, semantic=forged_sem, ced=d, source_page_text=src)
    assert {"inter", "national"} <= set(r2.missing_tokens)
    assert "missing_content" in _types(r2)

    # HIGH 3 surface: swap the HTML span-table body cells
    m3 = base.replace("<td>North</td><td>South</td>", "<td>South</td><td>North</td>")
    r3 = _run(markdown=m3, semantic=sem, ced=d, source_page_text=src)
    assert {"North", "South"} <= {i.expected for i in r3.issues
                                  if i.issue_type == "literal_mismatch"}

    # HIGH 3 surface: corrupt the merged-header colspan
    m4 = base.replace('colspan="2"', 'colspan="4"')
    r4 = _run(markdown=m4, semantic=sem, ced=d, source_page_text=src)
    assert "table_shape" in _types(r4)

    # numeric literal integrity still independently enforced
    m5 = base.replace("1.599,80", "1599.80")
    r5 = _run(markdown=m5, semantic=sem, ced=d, source_page_text=src)
    assert any(i.expected == "1.599,80" for i in r5.issues
               if i.issue_type == "numeric_mismatch")

    # duplicated header injected into the span table
    lines = base.split("\n")
    lines.insert(lines.index("<tr><td>North</td><td>South</td></tr>"),
                 '<tr><th colspan="2">Region</th></tr>')
    r6 = _run(markdown="\n".join(lines), semantic=sem, ced=d, source_page_text=src)
    assert "duplicated_header" in _types(r6)


def test_combined_render_and_checks_are_byte_stable():
    sem = _combined_semantic()
    d = _combined_ced()
    src = _combined_source()
    md = render_markdown(sem)
    first = _run(markdown=md, semantic=sem, ced=d, source_page_text=src)
    for _ in range(4):
        assert render_markdown(sem) == md
        again = _run(markdown=md, semantic=sem, ced=d, source_page_text=src)
        assert again.issues == first.issues
        assert again.source_text_match_rate == first.source_text_match_rate
