# Implementation Plan: Local-First PDF Document Converter

**Branch**: `001-pdf-markdown-converter` | **Date**: 2026-09-07 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/001-pdf-markdown-converter/spec.md`

## Summary

A local CLI tool (`solari-convert`) that converts a single PDF into semantically structured,
UTF-8 Markdown — and optionally DOCX — while preserving textual, numeric, hierarchical, and
tabular content with verifiable fidelity. Five explicit operations: `extract` (deterministic,
no LLM), `validate` (deterministic checks + one read-only local-LLM semantic pass, produces a
report and never edits), `fix` (applies only report-flagged corrections, logs every change,
never overwrites the original, re-validates), `export` (Markdown → DOCX, no LLM), and `convert`
(runs `extract` → `validate` → optional `export`, stops at the report, never auto-fixes).

Technical approach: a shared in-memory **semantic Document model** carrying per-element source
provenance (physical page + bbox, OCR markers) is built by a deterministic PDF pipeline
(pdfplumber for text/layout/tables, pypdfium2 rasterization + Tesseract for pages with no text
layer). Renderers turn the model into Markdown / DOCX. Validation compares a Markdown against
its source PDF; the semantic pass calls an OpenAI-compatible local LLM endpoint and hard-stops
when none is reachable. All four audit records (removal log, validation report, correction log,
traceability record) are written as JSON source-of-truth **plus** a generated Markdown rendering.
Every processing step runs on the user's machine with zero network egress on the default path.

## Technical Context

**Language/Version**: Python — minimum 3.12, development and CI pinned to 3.13. (Python 3.14 is
present on the dev machine but wheel coverage for some dependencies still lags; the floor is
kept at 3.12 and revisited before release.)

**Primary Dependencies**:
- `pdfplumber` (MIT, on `pdfminer.six`) — text extraction with per-word coordinates, line/word
  layout, and table detection
- `pypdfium2` (BSD-3 / PDFium) — page rasterization for OCR input (no poppler/ImageMagick system
  dependency)
- `pytesseract` (Apache-2.0) → system `tesseract` v5.5.3 — local OCR with per-word confidence
- `langdetect` (Apache-2.0) — OCR language auto-detection from a first-pass text sample
- `python-docx` (MIT) — DOCX export with explicit Word style + merged-cell mapping
- `pydantic` v2 (MIT) — models and JSON (de)serialization for the four audit records; JSON Schema
  generation for the contracts
- `httpx` (BSD) — local LLM HTTP calls and availability probe with timeouts
- CLI: **stdlib `argparse`** — no dependency (constitution VII)
- Dev only: `pytest`, `reportlab` (BSD) for synthetic fixture PDFs

**Storage**: Filesystem only. Generated artifacts go to a user-specified output directory (never
the source PDF's directory by default). Intermediate/working files stay under a
project-controlled working directory.

**Testing**: `pytest`. Fixture PDFs are generated at test time with `reportlab` (no committed
binaries). An autouse fixture blocks outbound sockets to enforce the no-egress guarantee. A fake
local-LLM HTTP server fixture backs the semantic-validation and `fix` tests.

**Target Platform**: Local CLI on macOS and Linux; Windows best-effort.

**Project Type**: Single project — local CLI application.

**Performance Goals**: No fixed page-count or file-size limit (FR-058). Pages are processed in a
stream with bounded memory; OCR is the dominant cost and is parallelizable per page. Target:
a several-hundred-page text-layer PDF converts in minutes on a laptop; failure on resource
exhaustion is clean and never leaves a partial artifact presented as complete (SC-014).

**Constraints**: Zero outbound network connections on the default path (SC-008). All artifact
writes are atomic (write to a temp file, then rename). The source PDF and any intermediate
artifact are never overwritten (FR-054). Output filenames are deterministic from the source
filename + page selection (FR-053), so identical inputs produce identical names and content
(SC-009).

**Scale/Scope**: One source PDF per invocation (no batch). Five operations. Documents of any
size within available machine resources.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Verdict | Basis |
|---|---|---|
| I. Content Fidelity | PASS | Extraction is fully deterministic; an LLM is never the primary text extractor (FR-029). Every text unit in the Document model carries a `SourceSpan` (physical page + bbox) so it maps back to a verifiable source location (SC-001). |
| II. Semantic Structure Preservation | PASS | Structure is captured explicitly in the Document model and emitted as explicit Markdown headings / lists / tables — never flattened. Structural fidelity is checked by `validate` (deterministic + semantic), not assumed. |
| III. Validation Before Delivery | PASS | `validate` is a first-class operation; `convert` always runs it and stops at the report (FR-050/051). `extract` on its own emits the "original Markdown" explicitly labelled unvalidated — this is spec-intended, and downstream operations treat it as immutable input. |
| IV. Controlled, Auditable Correction (NON-NEGOTIABLE) | PASS | `fix` changes only regions the validation report explicitly flags (FR-040), writes a new file leaving the original byte-identical (FR-041, SC-007), logs every correction traceably (FR-042), re-validates (FR-043), and reports any region it cannot resolve instead of guessing (FR-045). No heuristic rewriting; corrections restore source content only (FR-044). |
| V. Local-First & Data Privacy | PASS | Every processing step runs on the user's machine, including the LLM (a local OpenAI-compatible endpoint). An autouse test asserts zero egress. Any future cloud/LLM-assisted path must be opt-in and disclosed before use (FR-056). |
| VI. Test-First (NON-NEGOTIABLE) | PASS | `/speckit-tasks` will order contract tests (the four JSON Schemas, the CLI contract) and per-user-story integration tests before implementation; Red-Green-Refactor for all extraction and validation code. |
| VII. Simplicity & Minimal Dependencies | PASS | Seven runtime dependencies, each mapped 1:1 to a distinct hard requirement (PDF parse / rasterize / OCR / language detect / DOCX / schema / HTTP); the CLI is stdlib. All licenses permissive (MIT/BSD/Apache-2.0) — PyMuPDF was rejected specifically because its AGPL license conflicts with this project's MIT license. No LLM SDK: a thin `httpx` client is enough. Each choice gets a Decision/Rationale/Alternatives block in `research.md`. |

**Result: no violations.** Complexity Tracking table below stays empty.

**Post-Design re-check (after Phase 1):** `data-model.md` and `contracts/` introduced no new
dependency, no new external interface, and no LLM path into `extract`/`export`. The four record
schemas make the audit trail (principles III, IV) machine-checkable, and the `network_egress`
field plus the no-egress test fixture make principle V a regression-guarded property. All seven
principles still PASS; Complexity Tracking remains empty.

## Project Structure

### Documentation (this feature)

```text
specs/001-pdf-markdown-converter/
├── plan.md              # This file (/speckit-plan)
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
├── contracts/           # Phase 1 output
│   ├── cli.md
│   ├── removal-log.schema.json
│   ├── validation-report.schema.json
│   ├── correction-log.schema.json
│   └── traceability-record.schema.json
├── checklists/
│   └── requirements.md  # already present
└── tasks.md             # /speckit-tasks output (not created here)
```

### Source Code (repository root)

```text
pyproject.toml                 # uv-managed; console script `solari-convert`; exact-pinned deps

src/solari_converter/
├── __init__.py
├── cli.py                     # argparse entrypoint: extract | validate | fix | export | convert
├── config.py                  # LLM base URL / model, output dir, working dir resolution
├── naming.py                  # deterministic output names from source stem + page-range token (FR-053)
├── artifacts_io.py            # atomic write (temp+rename); collision policy (FR-054);
│                              #   dual emit: JSON source of truth + Markdown rendering (FR-057)
├── model/
│   ├── document.py            # Document, Block, Heading, Paragraph, ListBlock, ListItem, Table, Cell
│   └── provenance.py          # SourceSpan (physical page, bbox), OCR-derived markers, confidence
├── pdf/
│   ├── loader.py              # open PDF; reject encrypted / corrupted with a clear message;
│   │                          #   physical 1-based page indexing; page count
│   ├── page_selection.py      # parse "2,5-7,10-12" → ordered physical page list;
│   │                          #   reject out-of-range / reversed / overlapping / non-numeric (FR-002..005)
│   ├── text_extract.py        # words/lines → blocks; reading order; rotated / mixed-orientation pages
│   ├── artifacts.py           # detect + strip repeated headers/footers, standalone page numbers,
│   │                          #   watermarks, auth stamps, barcodes, QR, vertical auth text;
│   │                          #   keep + record when ambiguous (FR-006..011) → RemovalLog
│   ├── reflow.py              # remove visual line wrapping; rejoin hyphenated line breaks while
│   │                          #   keeping legitimate compound hyphens (FR-013/014)
│   ├── structure.py           # heading-level inference (size/weight/numbering), lists + nesting,
│   │                          #   numbered articles/clauses keep identifiers (FR-017..019)
│   ├── tables.py              # per-page table detect; stitch multi-page tables into one logical
│   │                          #   table; drop repeated page-level header rows; merged cells →
│   │                          #   HTML <table> with rowspan/colspan, else pipe table (FR-020..022)
│   └── ocr.py                 # per-page needs-OCR check; rasterize (pypdfium2); language
│                              #   auto-detect + optional per-run override; tesseract; capture
│                              #   confidence; mark OCR-derived text; per-page OCR record (FR-024..027a)
├── render/
│   ├── markdown.py            # Document → UTF-8 Markdown; levels 1-6 = headings, deeper levels =
│   │                          #   emphasized lead-in paragraph + explicit level marker (FR-017a)
│   └── docx.py                # Document/Markdown → DOCX; heading levels, body, list styles,
│                              #   tables incl. merged cells from HTML <table> spans (FR-047)
├── validate/
│   ├── deterministic.py       # source-coverage, numeric integrity, table row/col counts, no
│   │                          #   duplicated header rows, heading presence/level, low-confidence
│   │                          #   OCR surfacing, gross Markdown/PDF divergence (FR-036)
│   ├── semantic.py            # single read-only local-LLM pass; emits issues only, never edits (FR-037)
│   ├── llm_client.py          # OpenAI-compatible /v1/chat/completions (httpx); availability probe;
│   │                          #   hard stop with a clear message when unreachable (FR-038/046, SC-012)
│   └── report.py              # ValidationReport + ValidationIssue models (six mandatory fields +
│                              #   optional source loc / expected / found / suggested action, FR-034/035)
├── fix/
│   └── apply.py               # region-scoped edits from the report; write new corrected Markdown;
│                              #   CorrectionLog; re-run validate; report unresolvable regions (FR-039..046)
└── workflow/
    └── convert.py             # extract → validate → optional export; never fix; TraceabilityRecord
                               #   linking source PDF, physical page ranges, and every artifact (FR-050..052)

tests/
├── conftest.py                # autouse no-egress socket guard; tmp output dirs; fake local-LLM server
├── fixtures/                  # reportlab-built synthetic PDFs; markdowns with seeded deviations
├── contract/                  # JSON-Schema conformance for each record; CLI command contract
├── integration/               # one module per user story US1..US5, covering the spec's acceptance scenarios
└── unit/                      # page_selection, reflow, naming, table stitch, structure inference, collision policy
```

**Structure Decision**: Single project, `src/` layout. One CLI package (`src/solari_converter/`)
with a deterministic PDF pipeline (`pdf/`), a shared `model/`, renderers (`render/`), and the
LLM-dependent operations isolated in `validate/` and `fix/` so `extract` and `export` have no
path to an LLM (FR-031). Tests mirror the package plus a per-user-story integration layer.

## Complexity Tracking

> No Constitution Check violations. Table intentionally empty.

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| — | — | — |
