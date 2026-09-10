"""Narrow remediation regression for the T075–T078 post-implementation audit (R1–R8).

Covers, as focused adversarial cases and one combined interaction document:

* **R1** — context-aware Stage-5 Markdown escaping in ``render/markdown.py``: author
  text that looks like a heading / blockquote / emphasis / code span / raw HTML /
  ordered-or-bullet list marker renders **verbatim**, while the renderer's own
  structural syntax is never escaped;
* **R2** — ``validate/deterministic.py`` coverage is transformation-aware: a recorded
  ``dehyphenate`` join, a collapsed repeated header, and an identical-evidence table
  sibling are not counted as missing source content; genuinely dropped transformed
  content still is;
* **R3** — collapsed / merged-away source surfaces are excluded from the reading-order
  localisation so an identical retained twin does not trigger a false inversion;
* **R4** — numeric integrity keeps sign / ``%`` / separators / leading zeros, and a
  number the Markdown-or-HTML envelope generates (``rowspan``/``colspan``/``[L{n}]``)
  never satisfies an authored numeric expectation;
* **R5** — the rendered HTML ``<table>`` span geometry (row / column placement, ``th``
  vs ``td``, ``rowspan``, ``colspan``, cell count) is compared against the authoritative
  ``LogicalTable``;
* **R6** — a duplicated header is flagged only when the render repeats the header row
  more often than the reconstructed table does — an author data row equal to the header
  is accepted;
* **R7** — an explicit OCR ``confidence_threshold`` of ``0`` is honoured, not replaced
  by a truthiness fallback to the default;
* **R8** — a table ``ValidationIssue`` carries the source page derived from the
  reconstructed table's provenance, not a hard-coded ``1``.
"""

from __future__ import annotations

from solari_converter.model.semantic import (
    ClauseBlock,
    HeadingBlock,
    ListBlock,
    ListItemEntry,
    ParagraphBlock,
    SemanticDocument,
    block_id,
)
from solari_converter.render.markdown import render_markdown
from solari_converter.transform.build_semantic import build_semantic
from solari_converter.transform.tables import LogicalTable, TableBlock, TableCell
from solari_converter.validate.deterministic import run_deterministic_checks

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


def _plain_table(rows_text: list[list[str]], *, prov) -> TableBlock:
    rows = [
        [
            TableCell(text=v, provenance=(f"c{r}_{c}",), row=r, column=c,
                      is_header=(r == 0))
            for c, v in enumerate(row)
        ]
        for r, row in enumerate(rows_text)
    ]
    return TableBlock(
        kind="table", block_id=block_id("table", prov),
        table=LogicalTable(table_id="tbl-x", rows=rows, has_merged_cells=False,
                           header_row_count=1, spans_pages=[1]),
        provenance=tuple(prov), hint_decisions=(),
    )


# ======================================================================================
# R1 — context-aware Stage-5 Markdown escaping
# ======================================================================================


def test_r1_paragraph_leading_hash_is_not_a_heading():
    md = render_markdown(_doc(_para("# Important note")))
    assert md.strip() == r"\# Important note"


def test_r1_literal_blockquote_marker_is_neutralised():
    md = render_markdown(_doc(_para("> quoted author text here")))
    assert md.strip() == "&gt; quoted author text here"
    assert not md.lstrip().startswith(">")


def test_r1_emphasis_and_underscores_stay_literal():
    md = render_markdown(_doc(_para("see *value* and _snake_ now")))
    assert r"\*value\*" in md
    assert r"\_snake\_" in md


def test_r1_backticks_and_backslashes_stay_literal():
    md = render_markdown(_doc(_para(r"run `cmd` in C:\temp then done")))
    assert r"\`cmd\`" in md
    assert r"C:\\temp" in md


def test_r1_raw_html_looking_text_is_inert():
    md = render_markdown(_doc(_para("a <div> & <b>bold</b> tag")))
    assert "<div>" not in md
    assert "<b>" not in md
    assert "&amp;" in md
    assert "&lt;div&gt;" in md


def test_r1_embedded_newlines_do_not_split_or_reheading_the_block():
    md = render_markdown(_doc(_para("line one\n\n# line two"), _para("next")))
    assert md == "line one<br><br># line two\n\nnext\n"


def test_r1_heading_text_specials_do_not_break_heading_syntax():
    h = HeadingBlock(kind="heading", block_id=block_id("heading", ("h",)),
                     text="Rate * cost _ end", level=2, deep=False, numbering=None,
                     provenance=("h",))
    assert render_markdown(_doc(h)).strip() == r"## Rate \* cost \_ end"


def test_r1_deep_heading_envelope_survives_author_specials():
    h = HeadingBlock(kind="heading", block_id=block_id("heading", ("h",)),
                     text="a*b `c` <d>", level=8, deep=True, numbering=None,
                     provenance=("h",))
    assert render_markdown(_doc(h)).strip() == r"*a\*b \`c\` &lt;d&gt;* [L8]"


def test_r1_bullet_list_item_marker_kept_body_escaped():
    items = (ListItemEntry(text="- *urgent* item", marker="-", family="bullet",
                           depth=0, segment_ids=("l1",)),)
    lb = ListBlock(kind="list", block_id=block_id("list", ("l1",)), ordered=False,
                   items=items, provenance=("l1",))
    assert render_markdown(_doc(lb)).strip() == r"- \*urgent\* item"


def test_r1_ordered_list_item_number_marker_kept():
    items = (ListItemEntry(text="1. first > second", marker="1.", family="decimal",
                           depth=0, segment_ids=("l1",)),)
    lb = ListBlock(kind="list", block_id=block_id("list", ("l1",)), ordered=True,
                   items=items, provenance=("l1",))
    assert render_markdown(_doc(lb)).strip() == "1. first &gt; second"


def test_r1_clause_text_leading_marker_escaped():
    cb = ClauseBlock(kind="clause", block_id=block_id("clause", ("k",)),
                     identifier="-", text="- not a bullet, a dash lead", depth=0,
                     provenance=("k",))
    assert render_markdown(_doc(cb)).strip() == r"\- not a bullet, a dash lead"


def test_r1_pipe_cell_combines_several_specials_without_double_escaping():
    rows = [
        [TableCell(text="h1", provenance=("a",), row=0, column=0, is_header=True),
         TableCell(text="h2", provenance=("b",), row=0, column=1, is_header=True)],
        [TableCell(text=r"a|b *c* `d` \e", provenance=("x",), row=1, column=0),
         TableCell(text="ok", provenance=("y",), row=1, column=1)],
    ]
    tb = TableBlock(
        kind="table", block_id="blk-p",
        table=LogicalTable(table_id="tbl-p", rows=rows, has_merged_cells=False,
                           header_row_count=1, spans_pages=[1]),
        provenance=("a", "b", "x", "y"), hint_decisions=(),
    )
    md = render_markdown(_doc(tb))
    row = next(ln for ln in md.splitlines() if "ok" in ln and ln != "| h1 | h2 |")
    assert row == r"| a\|b \*c\* \`d\` \\e | ok |"


# ======================================================================================
# R2 — transformation-aware source coverage
# ======================================================================================


def _dehyphen_ced():
    return ced(
        [
            Seg("a", "The treaty is inter-", (72, 100, 240, 112)),
            Seg("b", "national in effect.", (72, 112, 240, 124)),
            Seg("c", "Every international clause applies.", (72, 160, 320, 172)),
        ],
        order=["a", "b", "c"],
    )


def test_r2_dehyphenation_is_not_false_missing_content():
    d = _dehyphen_ced()
    sem = build_semantic(d)
    assert any(t.kind == "dehyphenate" for t in sem.segment_transforms)
    md = render_markdown(sem)
    r = _run(markdown=md, semantic=sem, ced=d)
    assert r.source_text_match_rate == 1.0
    assert r.missing_tokens == ()
    assert "gross_divergence" not in _types(r)


def test_r2_genuinely_dropped_transformed_content_is_still_flagged():
    d = _dehyphen_ced()
    sem = build_semantic(d)
    md = render_markdown(sem).replace("international in effect", "in effect")
    r = _run(markdown=md, semantic=sem, ced=d)
    assert "international" in r.missing_tokens


def test_r2_collapsed_header_and_identical_evidence_excluded_from_coverage():
    d = ced(
        [
            Seg("h1", "Item", (72, 50, 120, 62), page=1),
            Seg("d1", "Widget", (72, 66, 140, 78), page=1),
            Seg("x1", "Total", (200, 66, 260, 78), page=1),
            Seg("x2", "Total", (200, 80, 260, 92), page=1),
            Seg("h2", "Item", (72, 400, 120, 412), page=2),
        ],
        order=["h1", "d1", "x1", "x2", "h2"],
    )
    tbl = _plain_table([["Item"], ["Widget"], ["Total"]], prov=("h1", "d1", "x1"))
    sem = SemanticDocument(
        blocks=(tbl,),
        collapsed_segment_ids=frozenset({"h2"}),
        table_identical_evidence_groups=(frozenset({"x1", "x2"}),),
    )
    md = render_markdown(sem)
    r = _run(markdown=md, semantic=sem, ced=d,
             source_page_text={1: "Item Widget Total Total", 2: "Item"})
    assert r.missing_tokens == ()
    assert r.source_text_match_rate == 1.0


def test_r2_removed_page_number_not_counted_missing():
    d = ced([
        Seg("pn1", "7", (280, 780, 300, 792), page=7),
        Seg("b1", "Body paragraph seven lives here.", (72, 100, 400, 114), page=7),
    ])
    sem = build_semantic(d)
    assert sem.removed_segment_ids
    md = render_markdown(sem)
    r = _run(markdown=md, semantic=sem, ced=d,
             source_page_text={7: "7 Body paragraph seven lives here."})
    assert r.source_text_match_rate == 1.0
    assert r.missing_tokens == ()


def test_r2_ordinary_untransformed_content_is_full_coverage():
    d = ced([Seg("s1", "plain sentence with ordinary words only", (72, 100, 400, 114))])
    sem = build_semantic(d)
    r = _run(markdown=render_markdown(sem), semantic=sem, ced=d)
    assert r.source_text_match_rate == 1.0


# ======================================================================================
# R3 — collapsed lineage must not cause reading-order false positives
# ======================================================================================


def test_r3_collapsed_header_is_not_localised_against_its_retained_twin():
    d = ced(
        [
            Seg("h1", "Name Value Column", (72, 50, 300, 62), page=1),
            Seg("body", "Some distinct paragraph body text here today.",
                (72, 70, 420, 82), page=1),
            Seg("h2", "Name Value Column", (72, 400, 300, 412), page=2),
        ],
        order=["h1", "body", "h2"],
    )
    sem = SemanticDocument(
        blocks=(_para("Name Value Column", ("h1",)),
                _para("Some distinct paragraph body text here today.", ("body",))),
        collapsed_segment_ids=frozenset({"h2"}),
    )
    md = render_markdown(sem)
    r = _run(markdown=md, semantic=sem, ced=d, source_page_text={
        1: "Name Value Column Some distinct paragraph body text here today.",
        2: "Name Value Column",
    })
    assert "reading_order" not in _types(r)


def test_r3_dehyphenated_left_surface_is_not_localised():
    d = _dehyphen_ced()
    sem = build_semantic(d)
    md = render_markdown(sem)
    r = _run(markdown=md, semantic=sem, ced=d)
    assert "reading_order" not in _types(r)


def test_r3_genuine_unlogged_inversion_still_flagged():
    d = ced(
        [
            Seg("a", "First distinct alpha sentence here.", (72, 100, 400, 114)),
            Seg("b", "Second distinct bravo sentence here.", (72, 130, 400, 144)),
        ],
        order=["a", "b"],
    )
    sem = SemanticDocument(
        blocks=(_para("Second distinct bravo sentence here.", ("b",)),
                _para("First distinct alpha sentence here.", ("a",))),
    )
    md = ("Second distinct bravo sentence here.\n\n"
          "First distinct alpha sentence here.\n")
    r = _run(markdown=md, semantic=sem, ced=d, source_page_text={
        1: "First distinct alpha sentence here. Second distinct bravo sentence here.",
    })
    assert "reading_order" in _types(r)


# ======================================================================================
# R4 — signed / percentage numeric fidelity + envelope isolation
# ======================================================================================


def test_r4_sign_and_percent_must_be_reproduced():
    d = ced([Seg("s1", "Delta was -25 and margin 25% last year", (72, 100, 400, 114))])
    sem = build_semantic(d)
    md = "Delta was 25 and margin 25 last year\n"
    r = _run(markdown=md, semantic=sem, ced=d,
             source_page_text={1: "Delta was -25 and margin 25% last year"})
    exp = {i.expected for i in r.issues if i.issue_type == "numeric_mismatch"}
    assert "-25" in exp
    assert "25%" in exp


def test_r4_leading_zeros_and_decimal_forms_stay_distinct():
    d = ced([Seg("s1", "codes 0004 and 1.00 units", (72, 100, 400, 114))])
    sem = build_semantic(d)
    r = _run(markdown="codes 4 and 1 units\n", semantic=sem, ced=d,
             source_page_text={1: "codes 0004 and 1.00 units"})
    exp = {i.expected for i in r.issues if i.issue_type == "numeric_mismatch"}
    assert exp == {"0004", "1.00"}


def test_r4_locale_forms_are_not_normalised_to_a_common_value():
    d = ced([Seg("s1", "price 1.599,80 today", (72, 100, 400, 114))])
    sem = build_semantic(d)
    r = _run(markdown="price 1,599.80 today\n", semantic=sem, ced=d,
             source_page_text={1: "price 1.599,80 today"})
    assert any(i.expected == "1.599,80" for i in r.issues
               if i.issue_type == "numeric_mismatch")


def test_r4_generated_span_and_level_numbers_do_not_satisfy_author_numbers():
    rows = [
        [TableCell(text="H", provenance=("a",), row=0, column=0, colspan=2,
                   is_header=True)],
        [TableCell(text="v", provenance=("b",), row=1, column=0, rowspan=3),
         TableCell(text="w", provenance=("c",), row=1, column=1)],
        [TableCell(text="x", provenance=("d",), row=2, column=1)],
        [TableCell(text="y", provenance=("e",), row=3, column=1)],
    ]
    tb = TableBlock(
        kind="table", block_id="blk-e",
        table=LogicalTable(table_id="tbl-e", rows=rows, has_merged_cells=True,
                           header_row_count=1, spans_pages=[1]),
        provenance=("a", "b", "c", "d", "e"), hint_decisions=(),
    )
    h = HeadingBlock(kind="heading", block_id=block_id("heading", ("z",)),
                     text="deep", level=7, deep=True, numbering=None, provenance=("z",))
    sem = SemanticDocument(blocks=(tb, h))
    d = ced(
        [
            Seg("a", "H", (72, 50, 120, 62)), Seg("b", "v", (72, 66, 90, 100)),
            Seg("c", "w", (100, 66, 120, 78)), Seg("d", "x", (100, 80, 120, 92)),
            Seg("e", "y", (100, 94, 120, 106)), Seg("z", "deep", (72, 120, 120, 132)),
        ],
        order=["a", "b", "c", "d", "e", "z"],
    )
    md = render_markdown(sem)
    assert 'rowspan="3"' in md and 'colspan="2"' in md and "[L7]" in md
    r = _run(markdown=md, semantic=sem, ced=d,
             source_page_text={1: "H v w x y deep 2 3 7"})
    miss = {i.expected for i in r.issues if i.issue_type == "numeric_mismatch"}
    assert miss == {"2", "3", "7"}


def test_r4_intact_signed_percentage_raises_no_issue():
    d = ced([Seg("s1", "movement of -3,5% recorded", (72, 100, 400, 114))])
    sem = build_semantic(d)
    r = _run(markdown="movement of -3,5% recorded\n", semantic=sem, ced=d,
             source_page_text={1: "movement of -3,5% recorded"})
    assert "numeric_mismatch" not in _types(r)


# ======================================================================================
# R5 — HTML table span geometry validation
# ======================================================================================


def _merged_block(rowspan_v: int = 2, colspan_v: int = 2) -> TableBlock:
    rows = [
        [TableCell(text="Head", provenance=("a",), row=0, column=0,
                   colspan=colspan_v, is_header=True)],
        [TableCell(text="L", provenance=("b",), row=1, column=0, rowspan=rowspan_v),
         TableCell(text="r1", provenance=("c",), row=1, column=1)],
        [TableCell(text="r2", provenance=("d",), row=2, column=1)],
    ]
    return TableBlock(
        kind="table", block_id="blk-m",
        table=LogicalTable(table_id="tbl-m", rows=rows, has_merged_cells=True,
                           header_row_count=1, spans_pages=[2]),
        provenance=("a", "b", "c", "d"), hint_decisions=(),
    )


def _merged_ced() -> object:
    return ced(
        [
            Seg("a", "Head", (72, 50, 220, 62), page=2),
            Seg("b", "L", (72, 66, 90, 92), page=2),
            Seg("c", "r1", (100, 66, 130, 78), page=2),
            Seg("d", "r2", (100, 80, 130, 92), page=2),
        ],
        order=["a", "b", "c", "d"],
    )


def test_r5_faithful_html_render_raises_no_table_shape():
    sem = SemanticDocument(blocks=(_merged_block(),))
    d = _merged_ced()
    r = _run(markdown=render_markdown(sem), semantic=sem, ced=d,
             source_page_text={2: "Head L r1 r2"})
    assert "table_shape" not in _types(r)


def test_r5_corrupted_rowspan_is_table_shape():
    sem = SemanticDocument(blocks=(_merged_block(rowspan_v=2),))
    d = _merged_ced()
    md = render_markdown(sem).replace('rowspan="2"', 'rowspan="9"')
    r = _run(markdown=md, semantic=sem, ced=d, source_page_text={2: "Head L r1 r2"})
    shape = [i for i in r.issues if i.issue_type == "table_shape"]
    assert shape
    assert any("rowspan" in i.description for i in shape)


def test_r5_wrong_colspan_is_table_shape():
    sem = SemanticDocument(blocks=(_merged_block(colspan_v=2),))
    d = _merged_ced()
    md = render_markdown(sem).replace('colspan="2"', 'colspan="5"')
    r = _run(markdown=md, semantic=sem, ced=d, source_page_text={2: "Head L r1 r2"})
    assert any("colspan" in i.description for i in r.issues
               if i.issue_type == "table_shape")


def test_r5_missing_cell_in_a_row_is_table_shape():
    sem = SemanticDocument(blocks=(_merged_block(),))
    d = _merged_ced()
    md = render_markdown(sem).replace("<td>r1</td>", "")
    r = _run(markdown=md, semantic=sem, ced=d, source_page_text={2: "Head L r1 r2"})
    assert "table_shape" in _types(r)


def test_r5_swapped_header_tag_is_table_shape():
    sem = SemanticDocument(blocks=(_merged_block(),))
    d = _merged_ced()
    md = render_markdown(sem).replace('<th colspan="2">Head</th>',
                                      '<td colspan="2">Head</td>')
    r = _run(markdown=md, semantic=sem, ced=d, source_page_text={2: "Head L r1 r2"})
    assert any("tag" in i.description for i in r.issues
               if i.issue_type == "table_shape")


# ======================================================================================
# R6 — duplicated-header check vs the expected semantic table
# ======================================================================================


def test_r6_author_data_row_equal_to_header_is_accepted():
    tb = _plain_table([["Name", "Value"], ["Name", "Value"], ["b", "2"]],
                      prov=("c0_0", "c0_1", "c1_0", "c1_1", "c2_0", "c2_1"))
    d = ced([Seg("x", "placeholder", (72, 100, 200, 114))])
    sem = SemanticDocument(blocks=(tb,))
    md = render_markdown(sem)
    r = _run(markdown=md, semantic=sem, ced=d,
             source_page_text={1: "Name Value Name Value b 2"})
    assert "duplicated_header" not in _types(r)


def test_r6_multiple_legitimate_header_equal_rows_no_false_positive():
    tb = _plain_table([["K", "V"], ["K", "V"], ["K", "V"]],
                      prov=("c0_0", "c0_1", "c1_0", "c1_1", "c2_0", "c2_1"))
    d = ced([Seg("x", "placeholder", (72, 100, 200, 114))])
    sem = SemanticDocument(blocks=(tb,))
    r = _run(markdown=render_markdown(sem), semantic=sem, ced=d,
             source_page_text={1: "K V K V K V"})
    assert "duplicated_header" not in _types(r)


def test_r6_injected_extra_header_row_is_flagged():
    tb = _plain_table([["Name", "Value"], ["a", "1"], ["b", "2"]],
                      prov=("c0_0", "c0_1", "c1_0", "c1_1", "c2_0", "c2_1"))
    d = ced([Seg("x", "placeholder", (72, 100, 200, 114))])
    sem = SemanticDocument(blocks=(tb,))
    lines = render_markdown(sem).split("\n")
    lines.insert(lines.index("| a | 1 |") + 1, "| Name | Value |")
    r = _run(markdown="\n".join(lines), semantic=sem, ced=d,
             source_page_text={1: "Name Value a 1 b 2"})
    assert "duplicated_header" in _types(r)


def test_r6_repeated_collapsed_physical_header_inserted_into_output_is_flagged():
    # the SemanticDocument carries the header once (the continuation copy collapsed),
    # but the delivered Markdown emits it twice
    tb = _plain_table([["Item", "Qty"], ["Widget", "3"]],
                      prov=("c0_0", "c0_1", "c1_0", "c1_1"))
    d = ced([Seg("x", "placeholder", (72, 100, 200, 114))])
    sem = SemanticDocument(blocks=(tb,), collapsed_segment_ids=frozenset())
    lines = render_markdown(sem).split("\n")
    lines.insert(lines.index("| Widget | 3 |") + 1, "| Item | Qty |")
    r = _run(markdown="\n".join(lines), semantic=sem, ced=d,
             source_page_text={1: "Item Qty Widget 3"})
    assert "duplicated_header" in _types(r)


# ======================================================================================
# R7 — OCR threshold must preserve an explicit zero
# ======================================================================================


def _ocr_candidate(threshold: float, mean: float, low_regions: int = 0):
    from solari_converter.model.candidate import (
        CandidateReadingOrder,
        ExtractionCandidate,
        RegionOcrRecord,
    )

    return ExtractionCandidate(
        run_id="a" * 16, tool_version="0.1.0", source_pdf="d.pdf",
        source_sha256="b" * 64, page_selection="all", technique="ocr:tesseract",
        segments=[],
        reading_order=CandidateReadingOrder(technique="ocr:tesseract", order=[]),
        page_ocr=[
            RegionOcrRecord(
                physical_page=1, ran_ocr=True, language_source="auto",
                mean_confidence=mean, confidence_threshold=threshold,
                low_confidence_regions=low_regions,
            )
        ],
    )


def test_r7_explicit_zero_threshold_with_zero_confidence_is_not_flagged():
    d = ced([Seg("s1", "some scanned body text", (72, 100, 400, 114))])
    sem = build_semantic(d)
    r = _run(markdown=render_markdown(sem), semantic=sem, ced=d,
             candidates=(_ocr_candidate(threshold=0.0, mean=0.0),),
             source_page_text={1: "some scanned body text"})
    assert "ocr_low_confidence" not in _types(r)


def test_r7_below_an_explicit_nonzero_threshold_is_flagged():
    d = ced([Seg("s1", "some scanned body text", (72, 100, 400, 114))])
    sem = build_semantic(d)
    r = _run(markdown=render_markdown(sem), semantic=sem, ced=d,
             candidates=(_ocr_candidate(threshold=70.0, mean=40.0),),
             source_page_text={1: "some scanned body text"})
    assert "ocr_low_confidence" in _types(r)


# ======================================================================================
# R8 — table ValidationIssue source page from provenance
# ======================================================================================


def test_r8_table_issue_source_page_is_derived_from_provenance():
    sem = SemanticDocument(blocks=(_merged_block(),))
    d = _merged_ced()  # every contributing segment is on physical page 2
    md = render_markdown(sem).replace('rowspan="2"', 'rowspan="9"')
    r = _run(markdown=md, semantic=sem, ced=d, source_page_text={2: "Head L r1 r2"})
    shape = [i for i in r.issues if i.issue_type == "table_shape"]
    assert shape
    assert all(i.source_page == 2 for i in shape)


def test_r8_table_source_page_uses_cell_recorded_page_when_present():
    rows = [
        [TableCell(text="A", provenance=(), row=0, column=0, is_header=True, page=10),
         TableCell(text="B", provenance=(), row=0, column=1, is_header=True, page=10)],
        [TableCell(text="1", provenance=(), row=1, column=0, page=10),
         TableCell(text="2", provenance=(), row=1, column=1, page=10)],
    ]
    tb = TableBlock(
        kind="table", block_id="blk-10",
        table=LogicalTable(table_id="tbl-10", rows=rows, has_merged_cells=False,
                           header_row_count=1, spans_pages=[10]),
        provenance=(), hint_decisions=(),
    )
    sem = SemanticDocument(blocks=(tb,))
    d = ced([Seg("x", "placeholder", (72, 100, 200, 114), page=10)])
    md = "| A |\n| --- |\n| 1 |\n"  # a column dropped
    r = _run(markdown=md, semantic=sem, ced=d, source_page_text={10: "A B 1 2"})
    shape = [i for i in r.issues if i.issue_type == "table_shape"]
    assert shape
    assert all(i.source_page == 10 for i in shape)


# ======================================================================================
# combined interaction — sanctioned transforms produce no false issues,
# then independent mutations are each detected
# ======================================================================================


def _combined_ced():
    return ced(
        [
            # dehyphenation pair + attesting occurrence
            Seg("p0", "The cross-border framework is inter-", (72, 60, 320, 72),
                page=1),
            Seg("p1", "national and binding on all parties.", (72, 74, 320, 86),
                page=1),
            Seg("p2", "Each international annexe is retained.", (72, 100, 340, 112),
                page=1),
            # markdown-special prose
            Seg("p3", "Fees rose by -3,5% and *terms* changed.", (72, 130, 360, 142),
                page=1),
            # a removed page number
            Seg("pn", "2", (300, 780, 312, 792), page=2),
            # table on page 2 with a merged header cell + an identical-evidence body
            Seg("t_h0", "Region", (72, 60, 130, 72), page=2,
                hints=[("table_cell", None, "pdfplumber")]),
            Seg("t_h1", "Region", (72, 60, 130, 72), page=2,
                hints=[("table_cell", None, "pdfplumber")]),
        ],
        order=["p0", "p1", "p2", "p3", "pn", "t_h0", "t_h1"],
    )


def _combined_semantic():
    # a hand-built SemanticDocument mirroring the sanctioned transforms
    para_join = _para("The cross-border framework is international and binding "
                      "on all parties.", ("p0", "p1"))
    para_intl = _para("Each international annexe is retained.", ("p2",))
    para_special = _para("Fees rose by -3,5% and *terms* changed.", ("p3",))
    rows = [
        [TableCell(text="Region", provenance=("t_h0", "t_h1"), row=0, column=0,
                   colspan=2, is_header=True)],
        [TableCell(text="North", provenance=("t_d0",), row=1, column=0),
         TableCell(text="South", provenance=("t_d1",), row=1, column=1)],
    ]
    tb = TableBlock(
        kind="table", block_id="blk-c",
        table=LogicalTable(table_id="tbl-c", rows=rows, has_merged_cells=True,
                           header_row_count=1, spans_pages=[2]),
        provenance=("t_h0", "t_h1", "t_d0", "t_d1"), hint_decisions=(),
    )
    from solari_converter.transform.reflow import SegmentTransform

    return SemanticDocument(
        blocks=(para_join, para_intl, para_special, tb),
        segment_transforms=(
            SegmentTransform(
                kind="dehyphenate", permitted_by="FR-014",
                segment_ids=("p0", "p1"), joined_with="p1",
                boundary="p0/p1", evidence="joined token 'international' in p2",
            ),
        ),
        removed_segment_ids=frozenset({"pn"}),
        table_identical_evidence_groups=(frozenset({"t_h0", "t_h1"}),),
    )


def _combined_ced_with_body():
    d = _combined_ced()
    # add the two data-cell segments the semantic table references
    return ced(
        [
            *[
                Seg(s.segment_id, s.text, s.source.bbox, page=s.source.physical_page)
                for s in d.accepted_segments
            ],
            Seg("t_d0", "North", (72, 74, 130, 86), page=2),
            Seg("t_d1", "South", (140, 74, 200, 86), page=2),
        ],
        order=[*d.accepted_reading_order, "t_d0", "t_d1"],
    )


def _combined_source_text():
    return {
        1: "The cross-border framework is inter- national and binding on all "
           "parties. Each international annexe is retained. Fees rose by -3,5% and "
           "*terms* changed.",
        2: "2 Region North South",
    }


def test_combined_sanctioned_transforms_emit_no_false_issues():
    sem = _combined_semantic()
    d = _combined_ced_with_body()
    md = render_markdown(sem)
    r = _run(markdown=md, semantic=sem, ced=d,
             source_page_text=_combined_source_text())
    assert r.issues == ()
    assert r.source_text_match_rate == 1.0
    assert r.gross_divergence is False


def test_combined_then_each_independent_mutation_is_caught():
    sem = _combined_semantic()
    d = _combined_ced_with_body()
    src = _combined_source_text()
    base = render_markdown(sem)

    # drop the trailing % (sign/percent fidelity)
    r1 = _run(markdown=base.replace("-3,5%", "-3,5"), semantic=sem, ced=d,
              source_page_text=src)
    assert "numeric_mismatch" in _types(r1)

    # corrupt the merged header colspan (span geometry)
    r2 = _run(markdown=base.replace('colspan="2"', 'colspan="4"'), semantic=sem,
              ced=d, source_page_text=src)
    assert "table_shape" in _types(r2)

    # inject a duplicate header row into the table (duplicated header)
    lines = base.split("\n")
    lines.insert(lines.index("<tr><td>North</td><td>South</td></tr>"),
                 '<tr><th colspan="2">Region</th></tr>')
    r3 = _run(markdown="\n".join(lines), semantic=sem, ced=d, source_page_text=src)
    assert "duplicated_header" in _types(r3)

    # drop transformed content entirely (transformation-aware coverage still flags)
    r4 = _run(markdown=base.replace("international and binding", "and binding"),
              semantic=sem, ced=d, source_page_text=src)
    assert "international" in r4.missing_tokens

    # activate Markdown syntax that escaping should have neutralised: a raw heading
    # line injected where author text sat renders as structure — the author '*terms*'
    # must still be inert in the faithful render
    assert r"\*terms\*" in base


def test_combined_render_is_byte_deterministic():
    sem = _combined_semantic()
    first = render_markdown(sem)
    for _ in range(5):
        assert render_markdown(sem) == first
