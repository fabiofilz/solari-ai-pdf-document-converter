"""Stage-5 deterministic Markdown rendering — T075 (M3).

``render/markdown.py`` is a **deterministic projection** of a frozen
``SemanticDocument`` (T073): headings → ``#``×level (1–6) / emphasized lead-in +
``[L{n}]`` (>6); a table with no merged cells → a Markdown pipe table; a table with
merged cells → an HTML ``<table>`` with exact ``rowspan`` / ``colspan``; an OCR-derived
block carries the OCR marker. The bytes are UTF-8, binary-written, **no BOM, LF only,
no NFC/NFD**, and byte-identical for a fixed ``SemanticDocument``.

RenderMap emission is **not** in scope here (T145).
"""

from __future__ import annotations

import unicodedata

from solari_converter.model.semantic import (
    ClauseBlock,
    HeadingBlock,
    ListBlock,
    ListItemEntry,
    ParagraphBlock,
    SemanticDocument,
    block_id,
)
from solari_converter.render.markdown import (
    OCR_BLOCK_MARKER,
    render_markdown,
    render_markdown_bytes,
)
from solari_converter.transform.tables import LogicalTable, TableBlock, TableCell

# --------------------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------------------


def _heading(text: str, level: int, *, prov=("s1",)) -> HeadingBlock:
    return HeadingBlock(
        kind="heading",
        block_id=block_id("heading", prov),
        text=text,
        level=level,
        deep=level > 6,
        numbering=None,
        provenance=tuple(prov),
    )


def _para(text: str, *, prov=("p1",)) -> ParagraphBlock:
    return ParagraphBlock(
        kind="paragraph", block_id=block_id("paragraph", prov), text=text,
        provenance=tuple(prov),
    )


def _doc(*blocks) -> SemanticDocument:
    return SemanticDocument(blocks=tuple(blocks))


def _plain_table_block(rows_text: list[list[str]], *, prov=("t1",)) -> TableBlock:
    rows: list[list[TableCell]] = []
    for r, row in enumerate(rows_text):
        rows.append([
            TableCell(text=cell, provenance=(f"c{r}_{c}",), row=r, column=c,
                      is_header=(r == 0))
            for c, cell in enumerate(row)
        ])
    table = LogicalTable(
        table_id="tbl-plain", rows=rows, has_merged_cells=False,
        header_row_count=1, spans_pages=[1],
    )
    return TableBlock(kind="table", block_id=block_id("table", prov), table=table,
                      provenance=tuple(prov), hint_decisions=())


# --------------------------------------------------------------------------------------
# headings
# --------------------------------------------------------------------------------------


def test_heading_levels_1_to_6_use_hash_syntax():
    doc = _doc(*[_heading(f"H{n}", n, prov=(f"s{n}",)) for n in range(1, 7)])
    md = render_markdown(doc)
    lines = [ln for ln in md.splitlines() if ln.strip()]
    assert lines == [
        "# H1", "## H2", "### H3", "#### H4", "##### H5", "###### H6",
    ]


def test_deep_heading_beyond_6_is_emphasized_lead_in_with_level_marker():
    doc = _doc(_heading("Deep clause title", 8, prov=("d1",)))
    md = render_markdown(doc)
    body = md.strip()
    # no run of 7+ '#'  → not a Markdown heading
    assert not body.startswith("#######")
    assert "[L8]" in body
    assert "Deep clause title" in body
    # emphasized lead-in: the text is wrapped in a Markdown emphasis run
    assert body == "*Deep clause title* [L8]"


def test_deep_heading_level_marker_tracks_the_exact_level():
    for lvl in (7, 9, 12):
        doc = _doc(_heading("x", lvl, prov=(f"s{lvl}",)))
        assert f"[L{lvl}]" in render_markdown(doc)


# --------------------------------------------------------------------------------------
# paragraphs / lists / clauses
# --------------------------------------------------------------------------------------


def test_paragraph_text_is_emitted_verbatim():
    doc = _doc(_para("A reflowed logical paragraph with no wrapping."))
    assert render_markdown(doc).strip() == "A reflowed logical paragraph with no wrapping."


def test_blocks_are_separated_by_one_blank_line_and_a_single_trailing_newline():
    doc = _doc(_heading("Title", 1), _para("Body."))
    md = render_markdown(doc)
    assert md == "# Title\n\nBody.\n"


def test_list_items_keep_their_literal_and_nest_by_depth():
    items = (
        ListItemEntry(text="- top", marker="-", family="bullet", depth=0,
                      segment_ids=("l1",)),
        ListItemEntry(text="- nested", marker="-", family="bullet", depth=1,
                      segment_ids=("l2",)),
    )
    doc = _doc(ListBlock(kind="list", block_id=block_id("list", ("l1", "l2")),
                         ordered=False, items=items, provenance=("l1", "l2")))
    assert render_markdown(doc).strip() == "- top\n  - nested"


def test_numbered_clause_identifier_is_retained():
    doc = _doc(ClauseBlock(kind="clause", block_id=block_id("clause", ("k1",)),
                           identifier="Article 1", text="Article 1. Definitions.",
                           depth=0, provenance=("k1",)))
    assert render_markdown(doc).strip() == "Article 1. Definitions."


# --------------------------------------------------------------------------------------
# tables
# --------------------------------------------------------------------------------------


def test_table_without_merged_cells_is_a_pipe_table():
    doc = _doc(_plain_table_block([["Item", "Qty"], ["Widget", "12"], ["Bolt", "1.599,80"]]))
    md = render_markdown(doc).strip()
    assert md.splitlines() == [
        "| Item | Qty |",
        "| --- | --- |",
        "| Widget | 12 |",
        "| Bolt | 1.599,80 |",
    ]


def test_pipe_table_cell_escapes_the_pipe_character():
    doc = _doc(_plain_table_block([["A", "B"], ["x|y", "z"]]))
    md = render_markdown(doc)
    assert r"x\|y" in md
    # exactly the escaped form, never a raw structural pipe in the value
    row = next(ln for ln in md.splitlines() if "x" in ln)
    assert row == r"| x\|y | z |"


def test_table_with_merged_cells_is_html_with_exact_rowspan_and_colspan():
    rows = [
        [TableCell(text="H", provenance=("a",), row=0, column=0, colspan=2,
                   is_header=True)],
        [
            TableCell(text="left", provenance=("b",), row=1, column=0, rowspan=2),
            TableCell(text="r1", provenance=("c",), row=1, column=1),
        ],
        [TableCell(text="r2", provenance=("d",), row=2, column=1)],
    ]
    table = LogicalTable(table_id="tbl-m", rows=rows, has_merged_cells=True,
                         header_row_count=1, spans_pages=[1])
    doc = _doc(TableBlock(kind="table", block_id="blk-m", table=table,
                          provenance=("a", "b", "c", "d"), hint_decisions=()))
    md = render_markdown(doc).strip()
    assert md.splitlines() == [
        "<table>",
        '<tr><th colspan="2">H</th></tr>',
        '<tr><td rowspan="2">left</td><td>r1</td></tr>',
        "<tr><td>r2</td></tr>",
        "</table>",
    ]


def test_html_table_cell_escapes_markup_characters():
    rows = [
        [TableCell(text="a<b>&c", provenance=("a",), row=0, column=0, colspan=1,
                   rowspan=1, is_header=True),
         TableCell(text="d", provenance=("z",), row=0, column=1, rowspan=2)],
        [TableCell(text="e", provenance=("b",), row=1, column=0)],
    ]
    table = LogicalTable(table_id="tbl-e", rows=rows, has_merged_cells=True,
                         header_row_count=1, spans_pages=[1])
    doc = _doc(TableBlock(kind="table", block_id="blk-e", table=table,
                          provenance=("a", "z", "b"), hint_decisions=()))
    md = render_markdown(doc)
    assert "a&lt;b&gt;&amp;c" in md
    assert "<b>" not in md


def test_numeric_values_survive_rendering_exactly():
    doc = _doc(_plain_table_block([["v"], ["1.599,80"], ["1,599.80"], ["0004"]]))
    md = render_markdown(doc)
    for v in ("1.599,80", "1,599.80", "0004"):
        assert v in md


# --------------------------------------------------------------------------------------
# OCR marker
# --------------------------------------------------------------------------------------


def test_ocr_derived_block_carries_the_ocr_marker():
    doc = _doc(_para("Recovered from a scanned region.", prov=("o1",)),
               _para("Native text.", prov=("n1",)))
    md = render_markdown(doc, ocr_segment_ids={"o1"})
    lines = md.splitlines()
    i = lines.index("Recovered from a scanned region.")
    assert lines[i - 1] == OCR_BLOCK_MARKER
    # the native block is not marked
    assert lines.count(OCR_BLOCK_MARKER) == 1


def test_a_partially_ocr_block_is_not_marked_at_block_level():
    doc = _doc(_para("half native half ocr", prov=("a", "b")))
    md = render_markdown(doc, ocr_segment_ids={"a"})
    assert OCR_BLOCK_MARKER not in md


# --------------------------------------------------------------------------------------
# serialization + determinism
# --------------------------------------------------------------------------------------


def test_output_is_utf8_binary_no_bom_lf_only():
    doc = _doc(_heading("Café — dénouement", 1), _para(" Senhor, ação, ‑ e 𝔘𝔫𝔦𝔠𝔬𝔡𝔢."))
    data = render_markdown_bytes(doc)
    assert isinstance(data, bytes)
    assert not data.startswith(b"\xef\xbb\xbf")       # no BOM
    assert b"\r" not in data                          # LF only
    assert data.decode("utf-8") == render_markdown(doc)


def test_no_unicode_normalization_is_applied():
    # a decomposed (NFD) sequence must be written exactly as authored
    nfd = unicodedata.normalize("NFD", "é")
    assert nfd != "é"
    doc = _doc(_para(f"value {nfd} end"))
    md = render_markdown(doc)
    assert nfd in md
    assert unicodedata.normalize("NFC", nfd) not in md.replace(nfd, "")


def test_render_is_byte_identical_across_repeated_calls():
    rows = [
        [TableCell(text="H1", provenance=("a",), row=0, column=0, colspan=2,
                   is_header=True)],
        [TableCell(text="x", provenance=("b",), row=1, column=0),
         TableCell(text="y", provenance=("c",), row=1, column=1)],
    ]
    table = LogicalTable(table_id="tbl-d", rows=rows, has_merged_cells=True,
                         header_row_count=1, spans_pages=[1])
    doc = _doc(
        _heading("Doc", 1),
        _para("Para one."),
        TableBlock(kind="table", block_id="blk-d", table=table,
                   provenance=("a", "b", "c"), hint_decisions=()),
        _heading("Very deep", 9, prov=("z1",)),
    )
    first = render_markdown_bytes(doc, ocr_segment_ids={"b", "c"})
    for _ in range(5):
        assert render_markdown_bytes(doc, ocr_segment_ids={"b", "c"}) == first
    # a set vs a frozenset vs a list of the same ids ⇒ identical bytes
    assert render_markdown_bytes(doc, ocr_segment_ids=["c", "b"]) == first


def test_block_order_is_the_semantic_document_order_never_re_sorted():
    doc = _doc(_para("zeta", prov=("z",)), _para("alpha", prov=("a",)),
               _heading("mid", 2, prov=("m",)))
    md = render_markdown(doc)
    assert md == "zeta\n\nalpha\n\n## mid\n"
