"""Stage-4 deterministic final-fidelity checks — T077 (M3, Constitution VI).

``validate/deterministic.py`` is the **non-LLM** validation subset (also the ``extract``
self-check): source-text coverage (SC-001), numeric integrity, table shape, duplicated
table headers, reading-order fidelity, OCR low-confidence, and the gross-divergence
match-rate — every issue ``check_origin == "deterministic"``, the whole pass
byte-reproducible for a fixed input, and **no LLM** anywhere.
"""

from __future__ import annotations

import importlib
import inspect

from solari_converter.model.semantic import (
    ParagraphBlock,
    SemanticDocument,
    block_id,
)
from solari_converter.transform.build_semantic import build_semantic
from solari_converter.transform.tables import LogicalTable, TableBlock, TableCell
from solari_converter.validate.deterministic import (
    ValidationIssue,
    run_deterministic_checks,
)
from tests.unit._semantic_fixtures import Seg, ced

# --------------------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------------------


def _para_doc(*texts_and_prov) -> SemanticDocument:
    blocks = tuple(
        ParagraphBlock(kind="paragraph", block_id=block_id("paragraph", (pid,)),
                       text=t, provenance=(pid,))
        for t, pid in texts_and_prov
    )
    return SemanticDocument(blocks=blocks)


def _run(**kw):
    base = dict(candidates=(), ocr_confidence_threshold=70.0,
               gross_divergence_threshold=0.5)
    base.update(kw)
    return run_deterministic_checks(**base)


def _types(result) -> list[str]:
    return sorted({i.issue_type for i in result.issues})


# --------------------------------------------------------------------------------------
# source-text coverage (SC-001)
# --------------------------------------------------------------------------------------


def test_full_coverage_yields_rate_one_and_no_missing_tokens():
    d = ced([Seg("s1", "The quick brown fox jumps", (72, 100, 400, 114))])
    sem = build_semantic(d)
    md = "The quick brown fox jumps\n"
    r = _run(markdown=md, semantic=sem, ced=d,
             source_page_text={1: "The quick brown fox jumps"})
    assert r.source_text_match_rate == 1.0
    assert r.missing_tokens == ()
    assert r.gross_divergence is False


def test_partial_coverage_reports_the_fraction_and_lists_missing_tokens():
    d = ced([Seg("s1", "alpha beta gamma delta", (72, 100, 400, 114))])
    sem = build_semantic(d)
    md = "alpha beta\n"
    r = _run(markdown=md, semantic=sem, ced=d,
             source_page_text={1: "alpha beta gamma delta"})
    assert r.source_text_match_rate == 0.5
    assert set(r.missing_tokens) == {"gamma", "delta"}


def test_logged_artifact_removal_is_not_counted_as_missing_coverage():
    # a page number removed + logged by stage 3 is deliberately absent from the Markdown
    d = ced([
        Seg("pn1", "3", (280, 780, 300, 792), page=3),
        Seg("pn2", "4", (280, 780, 300, 792), page=4),
        Seg("b1", "Body paragraph one here today.", (72, 100, 400, 114), page=3),
        Seg("b2", "Body paragraph two here today.", (72, 100, 400, 114), page=4),
    ])
    sem = build_semantic(d)
    assert sem.removed_segment_ids  # the page numbers were removed + logged
    md = "Body paragraph one here today.\n\nBody paragraph two here today.\n"
    r = _run(markdown=md, semantic=sem, ced=d, source_page_text={
        3: "3 Body paragraph one here today.",
        4: "4 Body paragraph two here today.",
    })
    assert r.source_text_match_rate == 1.0
    assert r.missing_tokens == ()


# --------------------------------------------------------------------------------------
# numeric integrity
# --------------------------------------------------------------------------------------


def test_a_seeded_numeric_change_is_a_numeric_mismatch_issue():
    d = ced([Seg("s1", "Total due 1234.56 today", (72, 100, 400, 114))])
    sem = build_semantic(d)
    md = "Total due 9999.56 today\n"
    r = _run(markdown=md, semantic=sem, ced=d,
             source_page_text={1: "Total due 1234.56 today"})
    numeric = [i for i in r.issues if i.issue_type == "numeric_mismatch"]
    assert numeric
    assert any(i.expected == "1234.56" for i in numeric)
    assert all(i.check_origin == "deterministic" for i in numeric)


def test_a_monetary_value_rendered_intact_raises_no_numeric_issue():
    d = ced([Seg("s1", "Rent R 1.599,80 per month", (72, 100, 400, 114))])
    sem = build_semantic(d)
    md = "Rent R 1.599,80 per month\n"
    r = _run(markdown=md, semantic=sem, ced=d,
             source_page_text={1: "Rent R 1.599,80 per month"})
    assert not [i for i in r.issues if i.issue_type == "numeric_mismatch"]


# --------------------------------------------------------------------------------------
# table shape + duplicated header
# --------------------------------------------------------------------------------------


def _table_doc(rows_text: list[list[str]]) -> SemanticDocument:
    rows = [
        [TableCell(text=v, provenance=(f"c{r}_{c}",), row=r, column=c,
                   is_header=(r == 0)) for c, v in enumerate(row)]
        for r, row in enumerate(rows_text)
    ]
    tbl = TableBlock(
        kind="table", block_id="blk-t",
        table=LogicalTable(table_id="tbl-t", rows=rows, has_merged_cells=False,
                           header_row_count=1, spans_pages=[1]),
        provenance=tuple(f"c{r}_{c}" for r in range(len(rows_text))
                         for c in range(len(rows_text[r]))),
        hint_decisions=(),
    )
    return SemanticDocument(blocks=(tbl,))


def test_a_broken_table_shape_is_a_table_shape_issue():
    sem = _table_doc([["A", "B", "C"], ["1", "2", "3"]])
    d = ced([Seg("x", "placeholder", (72, 100, 200, 114))])
    # the delivered Markdown lost a column
    md = "| A | B |\n| --- | --- |\n| 1 | 2 |\n"
    r = _run(markdown=md, semantic=sem, ced=d, source_page_text={1: "A B C 1 2 3"})
    assert "table_shape" in _types(r)


def test_a_matching_table_shape_raises_no_table_issue():
    sem = _table_doc([["A", "B"], ["1", "2"]])
    d = ced([Seg("x", "placeholder", (72, 100, 200, 114))])
    md = "| A | B |\n| --- | --- |\n| 1 | 2 |\n"
    r = _run(markdown=md, semantic=sem, ced=d, source_page_text={1: "A B 1 2"})
    assert "table_shape" not in _types(r)


def test_a_duplicated_header_row_is_a_duplicated_header_issue():
    sem = _table_doc([["Name", "Value"], ["a", "1"], ["b", "2"]])
    d = ced([Seg("x", "placeholder", (72, 100, 200, 114))])
    md = (
        "| Name | Value |\n| --- | --- |\n"
        "| a | 1 |\n| Name | Value |\n| b | 2 |\n"
    )
    r = _run(markdown=md, semantic=sem, ced=d,
             source_page_text={1: "Name Value a 1 b 2"})
    assert "duplicated_header" in _types(r)


# --------------------------------------------------------------------------------------
# reading order
# --------------------------------------------------------------------------------------


def test_a_reordered_segment_versus_the_accepted_order_is_a_reading_order_issue():
    d = ced(
        [
            Seg("a", "First distinct alpha sentence.", (72, 100, 400, 114)),
            Seg("b", "Second distinct bravo sentence.", (72, 130, 400, 144)),
            Seg("c", "Third distinct charlie sentence.", (72, 160, 400, 174)),
        ],
        order=["a", "b", "c"],
    )
    sem = _para_doc(
        ("First distinct alpha sentence.", "a"),
        ("Second distinct bravo sentence.", "b"),
        ("Third distinct charlie sentence.", "c"),
    )
    # delivered Markdown puts charlie before alpha — an unlogged inversion
    md = (
        "Third distinct charlie sentence.\n\n"
        "First distinct alpha sentence.\n\n"
        "Second distinct bravo sentence.\n"
    )
    r = _run(markdown=md, semantic=sem, ced=d,
             source_page_text={1: "First distinct alpha sentence. "
                                  "Second distinct bravo sentence. "
                                  "Third distinct charlie sentence."})
    assert "reading_order" in _types(r)


def test_markdown_in_accepted_order_raises_no_reading_order_issue():
    d = ced(
        [
            Seg("a", "First distinct alpha sentence.", (72, 100, 400, 114)),
            Seg("b", "Second distinct bravo sentence.", (72, 130, 400, 144)),
        ],
        order=["a", "b"],
    )
    sem = _para_doc(
        ("First distinct alpha sentence.", "a"),
        ("Second distinct bravo sentence.", "b"),
    )
    md = "First distinct alpha sentence.\n\nSecond distinct bravo sentence.\n"
    r = _run(markdown=md, semantic=sem, ced=d,
             source_page_text={1: "First distinct alpha sentence. "
                                  "Second distinct bravo sentence."})
    assert "reading_order" not in _types(r)


# --------------------------------------------------------------------------------------
# OCR low confidence
# --------------------------------------------------------------------------------------


def test_an_ocr_span_below_the_threshold_is_an_ocr_low_confidence_issue():
    d = ced([
        Seg("o1", "blurry scanned line", (72, 100, 400, 114),
            origin="ocr", technique="ocr:tesseract", ocr_conf=41.0),
        Seg("n1", "crisp native line", (72, 130, 400, 144)),
    ])
    sem = build_semantic(d)
    md = "blurry scanned line\n\ncrisp native line\n"
    r = _run(markdown=md, semantic=sem, ced=d, ocr_confidence_threshold=70.0,
             source_page_text={1: "blurry scanned line crisp native line"})
    ocr = [i for i in r.issues if i.issue_type == "ocr_low_confidence"]
    assert len(ocr) == 1
    assert ocr[0].source_page == 1
    assert ocr[0].check_origin == "deterministic"


def test_an_ocr_span_at_or_above_the_threshold_raises_no_issue():
    d = ced([Seg("o1", "clean scan", (72, 100, 400, 114),
                 origin="ocr", technique="ocr:tesseract", ocr_conf=95.0)])
    sem = build_semantic(d)
    r = _run(markdown="clean scan\n", semantic=sem, ced=d,
             ocr_confidence_threshold=70.0, source_page_text={1: "clean scan"})
    assert "ocr_low_confidence" not in _types(r)


# --------------------------------------------------------------------------------------
# gross divergence
# --------------------------------------------------------------------------------------


def test_an_unrelated_markdown_trips_gross_divergence_below_threshold():
    d = ced([Seg("s1", "lease agreement between the landlord and the tenant "
                       "concerning apartment forty two", (72, 100, 400, 200))])
    sem = build_semantic(d)
    unrelated = "quarterly revenue rose while operating margins compressed sharply\n"
    r = _run(markdown=unrelated, semantic=sem, ced=d, gross_divergence_threshold=0.5,
             source_page_text={1: "lease agreement between the landlord and the "
                                  "tenant concerning apartment forty two"})
    assert r.gross_divergence is True
    assert r.source_text_match_rate < 0.5
    gd = [i for i in r.issues if i.issue_type == "gross_divergence"]
    assert len(gd) == 1
    assert "%" in gd[0].description or "rate" in gd[0].description.lower()
    # per-token missing_content noise is suppressed on gross divergence
    assert "missing_content" not in _types(r)


def test_gross_divergence_still_lists_structural_issues():
    sem = _table_doc([["A", "B", "C"], ["1", "2", "3"]])
    d = ced([Seg("s1", "entirely unrelated contractual boilerplate text here",
                 (72, 100, 400, 200))])
    md = "| A | B |\n| --- | --- |\n| 1 | 2 |\n"
    r = _run(markdown=md, semantic=sem, ced=d, gross_divergence_threshold=0.5,
             source_page_text={1: "entirely unrelated contractual boilerplate text here"})
    assert r.gross_divergence is True
    assert "table_shape" in _types(r)


# --------------------------------------------------------------------------------------
# invariants: check_origin, determinism, no-LLM
# --------------------------------------------------------------------------------------


def test_every_emitted_issue_is_check_origin_deterministic():
    d = ced([Seg("s1", "alpha 1234.56 beta", (72, 100, 400, 114))])
    sem = build_semantic(d)
    md = "gamma 9999.99 delta\n"
    r = _run(markdown=md, semantic=sem, ced=d,
             source_page_text={1: "alpha 1234.56 beta"})
    assert r.issues
    assert all(i.check_origin == "deterministic" for i in r.issues)
    assert all(isinstance(i, ValidationIssue) for i in r.issues)
    assert all(i.markdown_line >= 1 and i.markdown_column >= 1 for i in r.issues)
    assert all(i.source_page >= 1 for i in r.issues)


def test_the_whole_pass_is_byte_reproducible_for_a_fixed_input():
    d = ced([
        Seg("a", "Distinct alpha 100.00 sentence.", (72, 100, 400, 114)),
        Seg("b", "Distinct bravo sentence follows.", (72, 130, 400, 144)),
        Seg("o", "scanned tail", (72, 160, 400, 174), origin="ocr",
            technique="ocr:tesseract", ocr_conf=33.0),
    ], order=["a", "b", "o"])
    sem = _para_doc(
        ("Distinct bravo sentence follows.", "b"),
        ("Distinct alpha 100.00 sentence.", "a"),
        ("scanned tail", "o"),
    )
    kw = dict(markdown="Distinct bravo sentence follows.\n\nDistinct alpha 999.00 "
                        "sentence.\n\nscanned tail\n",
              semantic=sem, ced=d,
              source_page_text={1: "Distinct alpha 100.00 sentence. "
                                   "Distinct bravo sentence follows. scanned tail"})
    first = _run(**kw)
    snap = [
        (i.id, i.severity, i.source_page, i.markdown_line, i.markdown_column,
         i.issue_type, i.description, i.check_origin, i.expected, i.found)
        for i in first.issues
    ]
    for _ in range(4):
        again = _run(**kw)
        assert [
            (i.id, i.severity, i.source_page, i.markdown_line, i.markdown_column,
             i.issue_type, i.description, i.check_origin, i.expected, i.found)
            for i in again.issues
        ] == snap
        assert again.source_text_match_rate == first.source_text_match_rate
        assert again.missing_tokens == first.missing_tokens


def test_module_imports_no_llm_client_or_llm_symbol():
    mod = importlib.import_module("solari_converter.validate.deterministic")
    src = inspect.getsource(mod)
    assert "llm_client" not in src
    assert "llm_select" not in src
    for bad in ("import openai", "import anthropic", "litellm", "ollama"):
        assert bad not in src
