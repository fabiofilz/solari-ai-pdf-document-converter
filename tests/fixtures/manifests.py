"""Machine-readable ground truth for the synthetic fixtures (T006).

Consumers:
  * T048  — `EXPECTED_PAGE_CLASS` / `EXPECTED_OCR_TRIGGER_REGIONS`
  * T124  — `expected_source_tokens()` (per selected page, each token -> true source page)
  * T133 / SC-019 — `DEFECT_GROUND_TRUTH` (seeded faults + `allowed` legitimate transforms)
  * heading / table / reading-order tests — `EXPECTED_HEADINGS`, `EXPECTED_TABLES`,
    `EXPECTED_READING_ORDER`

The token ground truth for the fixtures that *have* a native text layer is derived
from that layer (it is authoritative by construction — reportlab wrote exactly those
words). For the image-only / gapped fixtures the visible-content tokens are listed
explicitly, since no text layer exists to read them from.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

FIXTURES_DIR = Path(__file__).resolve().parent

# --------------------------------------------------------------------------------------
# Headings — (text, level), in document order
# --------------------------------------------------------------------------------------

EXPECTED_HEADINGS: dict[str, list[tuple[str, int]]] = {
    "native_text.pdf": [("Native Text Document", 1)],
    "agreement.pdf": [(f"Heading level {n}", n) for n in range(1, 9)]
    + [("Schedule A — Line Items (continued)", 2)],
    "clean_transform.pdf": [("Section Title", 1)],
    "monetary.pdf": [],
    "pt_diacritics.pdf": [],
    "two_column.pdf": [],
    "merged_cells.pdf": [("Table with merged / spanned cells", 1)],
    "multipage_table.pdf": [("Ledger extract", 1)],
    "hybrid.pdf": [("Hybrid page — native heading and body", 1)],
    "garbled_layer.pdf": [("Document with one garbled region", 1)],
    "missing_content_layer.pdf": [("CONTRATO DE PRESTAÇÃO DE SERVIÇOS", 1)],
    "scanned.pdf": [("ESCRITURA PÚBLICA", 1)],
    "degraded_scan.pdf": [("DECLARAÇÃO", 1)],
    "conflict_literal.pdf": [("Clause with a low-legibility number", 1)],
}


@dataclass
class TableGT:
    name: str
    cols: int
    body_rows: int
    header: list[str]
    header_repeats_on_pages: list[int]  # physical pages where the header row reappears
    spans_pages: list[int]
    has_merged_cells: bool = False


EXPECTED_TABLES: dict[str, list[TableGT]] = {
    "agreement.pdf": [
        TableGT(
            name="Schedule A — Line Items",
            cols=4,
            body_rows=33,
            header=["Item", "Qty", "Unit (USD)", "Line total (USD)"],
            header_repeats_on_pages=[2, 3, 4],
            spans_pages=[2, 3, 4],
        )
    ],
    "multipage_table.pdf": [
        TableGT(
            name="Ledger extract",
            cols=3,
            body_rows=40,
            header=["Date", "Description", "Amount (USD)"],
            header_repeats_on_pages=[1, 2, 3],
            spans_pages=[1, 2, 3],
        )
    ],
    "merged_cells.pdf": [
        TableGT(
            name="Region table",
            cols=3,
            body_rows=2,
            header=["Region (colspan=2)", "Total"],
            header_repeats_on_pages=[],
            spans_pages=[1],
            has_merged_cells=True,
        )
    ],
}

# One logical table across N pages must collapse the repeated header to ONE row.
EXPECTED_LOGICAL_ROW_COUNT = {
    "agreement.pdf": 1 + 33,          # header once + 33 body
    "multipage_table.pdf": 1 + 40,
}

# --------------------------------------------------------------------------------------
# Reading order — coarse, page-level expectations
# --------------------------------------------------------------------------------------

EXPECTED_READING_ORDER: dict[str, str] = {
    "two_column.pdf": (
        "page 1: left column top->bottom, then right column top->bottom "
        "(wide gutter -> geometry resolves it deterministically); "
        "page 2: ambiguous (narrow gutter + a full-width crossing line) -> HUMAN_REVIEW_REQUIRED"
    ),
    "agreement.pdf": "single column, strict top->bottom on every page",
    "clean_transform.pdf": "single column top->bottom",
}

GEOMETRY_RESOLVABLE_PAGES = {"two_column.pdf": [1]}
READING_ORDER_AMBIGUOUS_PAGES = {"two_column.pdf": [2]}

# --------------------------------------------------------------------------------------
# Page classification + OCR-trigger regions (T048 / FR-024b)
# --------------------------------------------------------------------------------------

# PageClass in {"native_text_sufficient", "ocr_required", "hybrid_native_and_ocr"}
EXPECTED_PAGE_CLASS: dict[str, list[str]] = {
    "native_text.pdf": ["native_text_sufficient"],
    "scanned.pdf": ["ocr_required"],
    "missing_content_layer.pdf": ["ocr_required"],  # text layer present but grossly incomplete
    "garbled_layer.pdf": ["hybrid_native_and_ocr"],  # clean para + one mojibake region
    "hybrid.pdf": ["hybrid_native_and_ocr"],
}

# Which fixtures must trigger OCR on 100% of the unambiguous cases (T048 assertion).
UNAMBIGUOUS_NO_OCR = ["native_text.pdf"]
UNAMBIGUOUS_OCR = ["scanned.pdf"]

# Regions (page, [x0,y0,x1,y1] in PDF points, origin bottom-left) that need OCR.
# Coarse boxes — the classifier is scored as an aggregate, not per-pixel.
EXPECTED_OCR_TRIGGER_REGIONS: dict[str, list[dict]] = {
    "native_text.pdf": [],
    "scanned.pdf": [{"page": 1, "bbox": None, "whole_page": True}],
    "missing_content_layer.pdf": [{"page": 1, "bbox": None, "whole_page": True}],
    "garbled_layer.pdf": [{"page": 1, "bbox": [72, 200, 540, 260], "whole_page": False}],
    "hybrid.pdf": [{"page": 1, "bbox": [72, 72, 540, 230], "whole_page": False}],
}

# --------------------------------------------------------------------------------------
# Source-token ground truth (SC-001 / T124)
# --------------------------------------------------------------------------------------

_TOKEN_RE = re.compile(r"[^\W_]+(?:[.,][^\W_]+)*|R\$|US\$|%", re.UNICODE)


def _tokens(text: str) -> list[str]:
    return _TOKEN_RE.findall(text)


# Visible-content tokens for the fixtures with NO / incomplete text layer — these
# cannot be read from the PDF and are the authoritative "must be recovered by OCR" set.
VISIBLE_ONLY_TOKENS: dict[str, dict[int, list[str]]] = {
    "scanned.pdf": {
        1: _tokens("ESCRITURA PÚBLICA Aos sete dias do mês de setembro compareceu a "
                   "parte outorgante para de livre e espontânea vontade declarar"),
    },
    "degraded_scan.pdf": {
        1: _tokens("DECLARAÇÃO Declaro para os devidos fins que o valor de R$ 8.750,00 "
                   "foi integralmente quitado em 03/2026 Assinatura"),
    },
    "missing_content_layer.pdf": {
        1: _tokens("CONTRATO DE PRESTAÇÃO DE SERVIÇOS Cláusula 1 Do objeto prestação de "
                   "serviços de consultoria Cláusula 2 Do preço R$ 12.500,00 mensais "
                   "Cláusula 3 Do prazo 12 doze meses renováveis Cláusula 4 Da rescisão "
                   "mediante aviso de 30 dias"),
    },
    "hybrid.pdf": {
        1: _tokens("REGISTRO CIVIL Selo de autenticidade nº 4471-A Valor R$ 27,50"),
    },
    "garbled_layer.pdf": {
        1: _tokens("Locação de imóvel residencial aluguel mensal de R$ 3.200,00"),
    },
    "conflict_literal.pdf": {
        1: _tokens("Cláusula 5 O aluguel mensal é de R$ 4.800,00 quatro mil e oitocentos "
                   "reais reajustado anualmente pelo IGP-M"),
    },
}


def expected_source_tokens(pdf_name: str, *, pages: list[int] | None = None) -> dict[int, list[str]]:
    """Per selected physical page -> the list of extractable source tokens with their
    true source page (the page number is the dict key). For fixtures with a reliable
    native text layer the tokens are read from that layer (authoritative); for the
    image-only / gapped fixtures the hand-authored visible tokens are used, plus any
    fragment that IS in the text layer.
    """
    import pdfplumber

    path = FIXTURES_DIR / pdf_name if not Path(pdf_name).is_absolute() else Path(pdf_name)
    basename = path.name
    out: dict[int, list[str]] = {}
    with pdfplumber.open(path) as doc:
        for i, page in enumerate(doc.pages, start=1):
            if pages is not None and i not in pages:
                continue
            layer = _tokens(page.extract_text() or "")
            visible = VISIBLE_ONLY_TOKENS.get(basename, {}).get(i, [])
            merged = list(dict.fromkeys(layer + visible))  # union, order-preserving
            out[i] = merged
    return out


# --------------------------------------------------------------------------------------
# Defect-classification ground truth (T133 / SC-019)
# --------------------------------------------------------------------------------------

@dataclass
class DefectCase:
    id: str
    markdown_fixture: str
    source_fixture: str
    where: str
    expected_defect_class: str  # extraction_error | reconciliation_error | disallowed_transformation
    note: str = ""


@dataclass
class AllowedCase:
    id: str
    source_fixture: str
    transform: str  # reflow | heading_inference | list_reconstruction | clause_reconstruction | table_stitch
    note: str = ""


DEFECT_GROUND_TRUTH: list[DefectCase] = [
    DefectCase(
        id="agr-dev-1",
        markdown_fixture="agreement.deviations.md",
        source_fixture="agreement.pdf",
        where="Schedule A row SKU-007, Line total column",
        expected_defect_class="extraction_error",
        note="numeric value altered; correct value is present in the PDF, absent from all candidates",
    ),
    DefectCase(
        id="agr-dev-2",
        markdown_fixture="agreement.deviations.md",
        source_fixture="agreement.pdf",
        where="Page 1, 'Heading level 8'",
        expected_defect_class="disallowed_transformation",
        note="a real heading was flattened to body text by the transformation stage",
    ),
    DefectCase(
        id="agr-dev-3",
        markdown_fixture="agreement.deviations.md",
        source_fixture="agreement.pdf",
        where="Clause 1.2 ('sixty (60)' vs source 'thirty (30)')",
        expected_defect_class="reconciliation_error",
        note="accepted value matches a candidate that the reconciliation log did NOT select; carries reconciliation_ref",
    ),
]

ALLOWED_TRANSFORMS: list[AllowedCase] = [
    AllowedCase("clean-1", "clean_transform.pdf", "reflow",
                "hard-wrapped lines joined into one paragraph; line-break hyphens repaired, "
                "compound hyphen kept"),
    AllowedCase("clean-2", "clean_transform.pdf", "heading_inference",
                "'Section Title' correctly promoted to a heading"),
    AllowedCase("clean-3", "clean_transform.pdf", "clause_reconstruction",
                "'1. Article 1 ...' numbered articles retained as a clause list"),
    AllowedCase("clean-4", "clean_transform.pdf", "table_stitch",
                "the Milestone/Due table rendered once, no duplicated header"),
    AllowedCase("agr-allowed-1", "agreement.pdf", "table_stitch",
                "Schedule A across 3 pages -> one logical table, repeated header collapsed"),
]

# --------------------------------------------------------------------------------------

ALL_FIXTURES: tuple[str, ...] = tuple(EXPECTED_HEADINGS)

_manifest_index: dict[str, object] = {
    "headings": EXPECTED_HEADINGS,
    "tables": EXPECTED_TABLES,
    "logical_row_count": EXPECTED_LOGICAL_ROW_COUNT,
    "reading_order": EXPECTED_READING_ORDER,
    "page_class": EXPECTED_PAGE_CLASS,
    "ocr_trigger_regions": EXPECTED_OCR_TRIGGER_REGIONS,
    "defect_ground_truth": DEFECT_GROUND_TRUTH,
    "allowed_transforms": ALLOWED_TRANSFORMS,
}
