# Feature Specification: Local-First PDF Document Converter

**Feature Branch**: `001-pdf-markdown-converter`

**Created**: 2026-09-05

**Status**: Draft

**Input**: User description: "Build a local-first PDF document converter that converts PDF files into semantically structured Markdown and optionally DOCX while preserving the original document's textual, numeric, hierarchical, and tabular content with high fidelity. [...] The entire default processing workflow must run locally on the user's machine without requiring paid APIs or cloud services."

## Clarifications

### Session 2026-09-05

- Q: Should the converter handle scanned / image-only pages (OCR) in this first version? → A: In scope for v1 — run local OCR on selected pages that have no extractable text layer.
- Q: Should `validate` and `fix` depend on a local LLM, or work without one? → A: Required for `validate` and `fix`; `extract` and `export` run without an LLM.
- Q: What should the convenience `convert` workflow do after it produces the validation report? → A: Stop at the report; `convert` never auto-runs `fix`.
- Q: How should merged/spanned table cells be represented in the Markdown? → A: Emit an HTML `<table>` with `rowspan`/`colspan` for tables that contain merged cells; use plain pipe tables for all other tables.
- Q: In what format should the validation report, removal log, correction log, and traceability record be written? → A: A structured machine-readable file (e.g. JSON) is the source of truth, plus a generated human-readable Markdown rendering of each.
- Q: How should hierarchy deeper than 6 levels be represented, given Markdown's 6 heading levels? → A: Use Markdown headings for levels 1–6; represent deeper levels as emphasized lead-in paragraphs carrying an explicit level marker, mapped to Word's deeper heading/list styles on export.
- Q: What document size must a single conversion handle before the tool may refuse it as too large? → A: No fixed document limit; the tool processes documents of any size within available machine resources and fails cleanly (never a partial artifact presented as complete) if resources are exhausted.
- Q: How should the converter decide which language(s) to use for OCR? → A: Auto-detect the page language(s) and OCR accordingly, with an optional user override to force one or more languages.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Extract a faithful, structured Markdown from selected pages (Priority: P1)

A user has a PDF (a contract, a collective agreement, a regulation, a report) and
wants a clean Markdown version of the whole document or of specific physical
pages. They run the `extract` operation, pointing at the PDF and optionally a
page selection (a single page, a contiguous range, or several discontinuous
ranges). They receive a Markdown file whose text matches the source, with visual
line wrapping removed, hyphenated line breaks repaired, non-semantic artifacts
(repeated headers/footers, page numbers, decorative backgrounds, authentication
stamps, barcodes, QR codes, vertical authentication text) stripped out, and the
document's hierarchy (headings, subheadings, lists, numbered articles/clauses,
tables) explicitly represented. Multi-page tables appear as one logical table.
The output file has a deterministic name derived from the source filename and the
selected page ranges, and no existing file is overwritten.

**Why this priority**: This is the core value proposition and the minimum
shippable product. Without trustworthy extraction, nothing else in the tool
matters. It is independently useful on its own.

**Independent Test**: Run `extract` against a representative PDF with and without
page selections; confirm the Markdown reproduces the source text, preserves
heading hierarchy and tables, removes artifacts, and uses the expected
deterministic filename without overwriting anything.

**Acceptance Scenarios**:

1. **Given** a text-layer PDF and no page selection, **When** the user runs
   `extract`, **Then** a Markdown file covering the entire document is produced
   with headings as Markdown heading levels, lists as Markdown lists, and tables
   as Markdown tables, and the source text is reproduced without paraphrase or
   omission.
2. **Given** a PDF and a selection of "pages 2, 5-7, and 10-12", **When** the user
   runs `extract`, **Then** only those physical pages are converted, in document
   order, and the output filename encodes that page selection.
3. **Given** a PDF whose every page repeats a company header, a footer, and a page
   number, **When** the user runs `extract`, **Then** those repeated elements do
   not appear in the Markdown body and each removed element is recorded in a
   removal log.
4. **Given** a paragraph split across a line break with a hyphenated word
   ("compre-\nhensive"), **When** the user runs `extract`, **Then** the Markdown
   contains the joined word ("comprehensive") and the surrounding text is a single
   reflowed paragraph.
5. **Given** a table that continues across three pages with a repeated column
   header on each page, **When** the user runs `extract`, **Then** the Markdown
   contains one table with all data rows, no lost or reordered columns, merged-cell
   meaning preserved, numeric values intact, and the repeated header appearing only
   once.
6. **Given** a selected page that has no extractable text layer, **When** the user
   runs `extract`, **Then** local OCR is applied to that page, the resulting text
   is included in the Markdown and marked as OCR-derived, and the OCR use is
   recorded for that page.
7. **Given** an output file with the deterministic name already exists, **When**
   the user runs `extract` again, **Then** the existing file is not overwritten and
   the user is told how the collision was handled.

---

### User Story 2 - Validate a generated Markdown against its source PDF (Priority: P2)

A user who has an extracted Markdown wants to know exactly where and how it
deviates from the source before relying on it. They run the `validate` operation
with the Markdown and the source PDF (and page selection). They receive a
validation report — a separate artifact — that does not change the Markdown.
Every issue in the report states its severity, the source PDF page, the Markdown
line and column, the issue type, and a clear description of the problem; where
applicable it also gives the source location, the expected value or structure,
the found value or structure, and a suggested corrective action. The report
combines deterministic checks with semantic checks performed by a single local
LLM. The LLM never alters the Markdown.

**Why this priority**: Fidelity claims are only credible if they are checked.
Validation turns the extracted Markdown from "probably fine" into "known issues
listed", which is what makes the tool trustworthy for real documents.

**Independent Test**: Run `validate` against a Markdown that has known, seeded
deviations from its source PDF; confirm the report identifies each deviation with
all mandatory fields populated and that the Markdown file is byte-identical before
and after.

**Acceptance Scenarios**:

1. **Given** an extracted Markdown and its source PDF, **When** the user runs
   `validate`, **Then** a validation report artifact is produced and the Markdown
   file is unchanged.
2. **Given** a Markdown where one numeric value in a table differs from the
   source, **When** the user runs `validate`, **Then** the report contains an
   issue with severity, source PDF page, Markdown line, Markdown column, issue
   type, description, the expected value, the found value, and a suggested
   correction.
3. **Given** a Markdown where a source heading was flattened into a normal
   paragraph, **When** the user runs `validate`, **Then** the report flags a
   structural issue identifying the expected heading level and the found
   structure.
4. **Given** no local LLM is available or configured, **When** the user runs
   `validate`, **Then** the operation stops with a clear message stating that a
   local LLM is required and no partial report is presented as complete.
5. **Given** a validation run, **When** the semantic checks execute, **Then** no
   edit is made to the Markdown as a result of the LLM's analysis.

---

### User Story 3 - Apply controlled, auditable corrections (Priority: P3)

A user has a validation report listing non-conformant regions and wants them
corrected without losing the original or the audit trail. They run the `fix`
operation with the original Markdown, the validation report, and the source
context. The tool changes only the regions the report explicitly flagged,
writes a new corrected Markdown file (the original is untouched), logs every
applied correction, and re-runs validation on the corrected output. Corrections
restore source content; they never paraphrase, summarize, rewrite, or "improve"
the wording.

**Why this priority**: Correction is where uncontrolled automation would do the
most damage. It depends on US2 existing and is valuable once validation is
trustworthy, but the tool is already useful without it (a user can correct
manually from the report).

**Independent Test**: Run `fix` with a report that flags three specific regions;
confirm exactly those regions changed (diff shows no other edits), the original
file is byte-identical, a correction log lists all three changes, and a
re-validation report is produced.

**Acceptance Scenarios**:

1. **Given** an original Markdown, a validation report, and source context,
   **When** the user runs `fix`, **Then** a new corrected Markdown file is created
   and the original file is not overwritten.
2. **Given** a report that flags two regions as non-conformant, **When** the user
   runs `fix`, **Then** only those two regions differ between the original and the
   corrected Markdown, verified by diff.
3. **Given** a `fix` run, **When** corrections are applied, **Then** a correction
   log records each change with enough detail to trace it back to the report issue
   it resolves.
4. **Given** a corrected Markdown, **When** `fix` completes, **Then** validation is
   re-run against the corrected output and its report is produced.
5. **Given** a flagged region containing awkward but source-accurate wording,
   **When** the user runs `fix`, **Then** the wording is not paraphrased or
   rewritten; only genuine conversion errors are corrected.
6. **Given** no local LLM is available or configured, **When** the user runs
   `fix`, **Then** the operation stops with a clear message stating that a local
   LLM is required.

---

### User Story 4 - Export a Markdown to DOCX (Priority: P3)

A user needs to hand a Word document to someone who does not work in Markdown.
They run the `export` operation on a Markdown file (original or corrected) and
receive a DOCX file in which Markdown heading levels map to the equivalent Word
heading styles, paragraphs map to the body style, lists map to Word list styles,
and tables map to Word tables. Markdown remains the canonical representation;
DOCX is an optional output.

**Why this priority**: A distribution convenience, not a fidelity concern. It
depends only on a valid Markdown existing and does not need the LLM.

**Independent Test**: Run `export` on a Markdown containing headings at several
levels, nested lists, and a table; open the DOCX and confirm each element carries
the corresponding Word style and the content matches the Markdown.

**Acceptance Scenarios**:

1. **Given** a Markdown with headings at levels 1 through 4, **When** the user runs
   `export`, **Then** the DOCX applies the matching Word heading style to each.
2. **Given** a Markdown with bulleted and numbered lists, **When** the user runs
   `export`, **Then** the DOCX uses Word list styles that preserve list type and
   nesting.
3. **Given** a Markdown table, **When** the user runs `export`, **Then** the DOCX
   contains a Word table with the same rows, columns, and cell values.
4. **Given** an `export` run, **When** it completes, **Then** the source Markdown
   file is unchanged and no LLM is invoked.

---

### User Story 5 - Run the convert workflow with full traceability (Priority: P2)

A user wants a single operation that takes them from source PDF to a validated
Markdown (and optionally a DOCX) in one step, while keeping every intermediate
artifact linked. They run the `convert` operation with the PDF and an optional
page selection. It runs `extract`, then `validate`, and — if the user asked for
it — `export`. It stops at the validation report; it never runs `fix`
automatically. A traceability record links the source PDF, the selected physical
page ranges, the generated Markdown, the validation report, and the DOCX (when
produced). All generated files use deterministic names, no source or intermediate
artifact is overwritten by default, and the whole run happens locally with no
paid APIs or cloud services.

**Why this priority**: This is the "standard workflow" the user described and the
common path, but it is a composition of US1 and US2, so those must exist first.

**Independent Test**: Run `convert` on a PDF with a page selection; confirm a
Markdown and a validation report are produced with deterministic names, a
traceability record links them to the source and page ranges, `fix` was not run,
and no network egress occurred.

**Acceptance Scenarios**:

1. **Given** a PDF and a page selection, **When** the user runs `convert`, **Then**
   an extracted Markdown and a validation report are produced and the workflow
   stops without applying corrections.
2. **Given** a `convert` run with export requested, **When** it completes, **Then**
   a DOCX is also produced and linked in the traceability record.
3. **Given** a completed `convert` run, **When** the user inspects the traceability
   record, **Then** they can identify the source PDF, the exact physical page
   ranges, the Markdown, the validation report, and the DOCX without ambiguity.
4. **Given** a `convert` run, **When** it executes end to end, **Then** no outbound
   network connection is made and no paid service is required.
5. **Given** the same PDF and the same page selection, **When** the user runs
   `convert` twice, **Then** both runs produce the same output filenames and the
   same Markdown content.

---

### Edge Cases

- **No text layer on a page**: local OCR is applied and the page's text is marked
  as OCR-derived.
- **Low-confidence OCR regions**: surfaced as validation issues rather than
  silently accepted.
- **Page that is partly a text layer and partly an image**: both sources are
  combined for that page and the OCR-derived portion is marked.
- **Local LLM not installed / not configured** when `validate`, `fix`, or
  `convert` is run: the operation stops with a clear message; no partial result
  is presented as complete.
- **Encrypted or password-protected PDF**: the user is told the document cannot be
  opened rather than producing an empty or partial Markdown.
- **Corrupted or malformed PDF**: reported as unprocessable with a clear message.
- **Page selection out of range, reversed (e.g. "10-5"), or overlapping ranges**:
  rejected with a message explaining the problem; nothing is produced.
- **Printed page labels differ from physical page order** (front matter numbered
  i, ii, iii): selections always refer to physical pages, and this is stated to
  the user.
- **A header/footer string that is also legitimate body content** (a defined term,
  a party name): removal is conservative; when ambiguous the element is kept and
  the decision is recorded.
- **Legitimate hyphen at a line end** (a compound term): not removed when joining
  the line break.
- **Document with no detectable headings**: produced as a flat structure; not
  fabricated hierarchy.
- **Table that starts mid-page after other content, or spans more than two
  pages**: still reconstructed as one logical table.
- **Vertical text that is meaningful content** (a rotated table, a sidebar note)
  vs. vertical authentication text: meaningful vertical text is preserved.
- **Markdown and PDF fundamentally diverge** (wrong Markdown passed to
  `validate`): the report reflects the scale of the mismatch rather than failing
  silently.
- **Validation report references a Markdown region that no longer exists** when
  `fix` runs: that issue is reported as unresolvable rather than applied to the
  wrong location.
- **Deterministic filename collision with different content**: the existing file
  is preserved and the collision is surfaced to the user.
- **Very large PDF**: no fixed page or size limit is imposed; the document is
  processed within available machine resources. If resources are exhausted
  mid-run, the operation fails cleanly and never presents a partially written
  artifact as complete.
- **Rotated or mixed-orientation pages**: text is extracted in correct reading
  order.

## Requirements *(mandatory)*

### Functional Requirements

#### Page selection

- **FR-001**: The system MUST support converting the entire document when no page
  selection is given.
- **FR-002**: The system MUST support a page selection consisting of single pages,
  contiguous ranges, and multiple discontinuous ranges in one request.
- **FR-003**: Page selections MUST refer to 1-based physical PDF page positions,
  not printed page labels, and the system MUST make this explicit to the user.
- **FR-004**: The system MUST reject invalid selections (out of range, reversed
  ranges, non-numeric, overlapping) with a clear message and produce no output.
- **FR-005**: When a page selection is used, output covers only those pages, in
  document order.

#### Artifact removal

- **FR-006**: The system MUST detect and remove repeated running headers and
  footers when they are not part of the document's meaningful content.
- **FR-007**: The system MUST remove standalone page numbers.
- **FR-008**: The system MUST remove decorative backgrounds and watermarks.
- **FR-009**: The system MUST remove authentication stamps, barcodes, QR codes,
  and vertical authentication text when they are not part of the document's
  meaningful content.
- **FR-010**: When it is ambiguous whether an element is a non-semantic artifact
  or meaningful content, the system MUST keep the element and record the decision.
- **FR-011**: The system MUST record every removed element in a removal log that
  identifies what was removed and from which source page.

#### Text normalization

- **FR-012**: Markdown output MUST be valid Unicode encoded as UTF-8.
- **FR-013**: The system MUST remove visual line wrapping so that logical
  paragraphs are contiguous.
- **FR-014**: The system MUST repair hyphenation introduced by line breaks by
  rejoining split words, without removing hyphens that are part of the word.
- **FR-015**: The system MUST preserve reading order.
- **FR-016**: The system MUST preserve semantic paragraph, heading, list,
  article, clause, and table boundaries.

#### Semantic structure

- **FR-017**: Headings and subheadings detected in the PDF MUST be emitted as
  explicit Markdown heading levels that reflect the document's hierarchy.
- **FR-017a**: Hierarchy levels 1 through 6 MUST use Markdown heading syntax.
  Levels deeper than 6 MUST be emitted as emphasized lead-in paragraphs that carry
  an explicit level marker, so every level remains machine-distinguishable; on
  DOCX export these MUST map to Word's deeper heading or styled-list paragraph
  styles.
- **FR-018**: Lists detected in the PDF MUST be emitted as Markdown lists,
  preserving list type and nesting.
- **FR-019**: Numbered articles and clauses MUST retain their identifiers.
- **FR-020**: Tables MUST be emitted with their rows, columns, numeric values, and
  merged-cell meaning preserved. Tables without merged cells MUST be emitted as
  Markdown pipe tables; tables that contain merged (spanned) cells MUST be emitted
  as HTML `<table>` markup using `rowspan`/`colspan` to express the spans exactly.
- **FR-021**: A table that continues across pages MUST be reconstructed as a
  single logical table with no lost rows or columns.
- **FR-022**: Repeated page-level table headers MUST NOT be emitted as duplicated
  data rows.
- **FR-023**: The Markdown heading structure MUST be sufficient to map to
  equivalent Word heading styles during DOCX export.

#### Scanned pages / OCR

- **FR-024**: For a selected page with no extractable text layer, the system MUST
  apply local OCR and include the resulting text in the Markdown.
- **FR-025**: OCR-derived text MUST be identifiable as OCR-derived, and OCR use
  MUST be recorded per page.
- **FR-026**: For a page that combines a text layer and image content, the system
  MUST include both and mark the OCR-derived portion.
- **FR-027**: Low-confidence OCR regions MUST be surfaced during validation rather
  than accepted silently.
- **FR-027a**: The system MUST auto-detect the language(s) of a page before
  running OCR on it and MUST accept an optional user override to force one or more
  OCR languages for the run. The detected or overridden language(s) MUST be
  recorded alongside the per-page OCR record.

#### Operation separation

- **FR-028**: The system MUST expose `extract`, `validate`, `fix`, and `export` as
  explicit, independently invocable operations.
- **FR-029**: Extraction MUST NOT use an LLM as the primary text extractor.
- **FR-030**: Extraction MUST produce the "original Markdown", which is treated as
  immutable by later operations.
- **FR-031**: `extract` and `export` MUST be able to run without a local LLM.

#### Validation

- **FR-032**: `validate` MUST compare a generated Markdown against its source PDF
  and produce a validation report as a separate persisted artifact.
- **FR-033**: `validate` MUST NOT modify the Markdown under any circumstance.
- **FR-034**: Every issue in the report MUST include severity, source PDF page,
  Markdown line, Markdown column, issue type, and a clear problem description.
- **FR-035**: Where applicable, an issue MUST also include the source location,
  the expected value or structure, the found value or structure, and a suggested
  corrective action.
- **FR-036**: `validate` MUST include deterministic checks.
- **FR-037**: `validate` MUST use at most one local LLM for semantic validation,
  and that LLM MUST NOT alter the document.
- **FR-038**: `validate` MUST require a local LLM and MUST stop with a clear
  message when none is available, rather than presenting a deterministic-only
  report as complete.

#### Fix

- **FR-039**: `fix` MUST take the original Markdown, the validation report, and
  source context as inputs.
- **FR-040**: `fix` MUST change only the regions the validation report explicitly
  identified as non-conformant.
- **FR-041**: `fix` MUST write a new corrected Markdown file and MUST NOT
  overwrite the original.
- **FR-042**: `fix` MUST log every applied correction with enough detail to trace
  it to the report issue it resolves.
- **FR-043**: `fix` MUST re-run validation against the corrected output and
  produce its report.
- **FR-044**: `fix` MUST NOT paraphrase, summarize, rewrite, or improve wording;
  corrections MUST restore source content only.
- **FR-045**: `fix` MUST report any flagged region it cannot resolve (for example,
  a region that no longer exists in the Markdown) rather than applying a change to
  the wrong location.
- **FR-046**: `fix` MUST require a local LLM and MUST stop with a clear message
  when none is available.

#### Export

- **FR-047**: `export` MUST convert a Markdown file to DOCX, mapping heading
  levels, paragraphs, lists, and tables to equivalent Word styles; both Markdown
  pipe tables and HTML `<table>` tables (including their `rowspan`/`colspan`
  spans) MUST map to Word tables with equivalent merged cells.
- **FR-048**: Markdown MUST remain the canonical representation; DOCX is an
  optional output format.
- **FR-049**: `export` MUST NOT modify the source Markdown.

#### Workflow and traceability

- **FR-050**: The system MUST provide a `convert` convenience operation that runs
  `extract`, then `validate`, and — when requested — `export`.
- **FR-051**: `convert` MUST stop at the validation report and MUST NOT invoke
  `fix` automatically.
- **FR-052**: The standard workflow MUST preserve traceability between the source
  PDF, the selected physical page ranges, the generated Markdown, the validation
  report, the corrected Markdown (when produced), and the DOCX output.
- **FR-053**: Generated files MUST use deterministic names derived from the
  original filename and the selected page ranges, so identical inputs yield
  identical names.
- **FR-054**: The system MUST NOT overwrite the original source or any
  intermediate artifact by default; a name collision MUST preserve the existing
  file and be surfaced to the user.
- **FR-055**: The entire default processing workflow MUST run locally on the
  user's machine without requiring paid APIs or cloud services.
- **FR-056**: Any optional network- or cloud-assisted behavior MUST be opt-in and
  disclosed before use.
- **FR-057**: The validation report, removal log, correction log, and traceability
  record MUST each be written as a structured machine-readable file that is the
  authoritative source of truth (consumed programmatically by `fix` and by tests),
  and the system MUST also generate a human-readable Markdown rendering of each.
  The two MUST always represent the same content.
- **FR-058**: The system MUST NOT impose a fixed page-count or file-size limit on
  a conversion. It MUST process documents of any size within the machine's
  available resources; if resources are exhausted during a run, the operation MUST
  fail with a clear message and MUST NOT leave a partially written artifact
  presented as complete.

### Key Entities *(include if feature involves data)*

- **Source PDF**: the input document; identified by filename; has a fixed number
  of physical pages.
- **Page selection**: the set of physical pages to process, expressed as single
  pages and ranges; may be empty (whole document).
- **Original Markdown**: the immutable output of `extract`; the canonical
  representation of the converted document.
- **Removal log**: the record of every non-semantic element removed during
  extraction, with source page references.
- **Validation report**: the output of `validate`; a list of validation issues;
  never modifies the Markdown.
- **Validation issue**: one entry in a report — severity, source PDF page,
  Markdown line, Markdown column, issue type, description, and optionally source
  location, expected value/structure, found value/structure, suggested action.
- **Correction log**: the output of `fix` describing each applied correction and
  the issue it resolves.
- **Corrected Markdown**: a new file produced by `fix`; the original is retained
  unchanged.
- **DOCX export**: an optional Word-format rendering of a Markdown file.
- **Traceability record**: per-run linkage between the source PDF, page ranges,
  and all generated artifacts.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: On the acceptance test corpus, every unit of extractable source text
  in the selected pages maps to a verifiable source page location, with zero
  silent omissions.
- **SC-002**: At least 95% of headings present in the source appear at the correct
  hierarchical level in the Markdown across the test corpus.
- **SC-003**: Every multi-page table in the test corpus is reconstructed with zero
  lost rows, zero lost columns, and zero duplicated header rows.
- **SC-004**: 100% of elements removed during extraction are recorded in the
  removal log.
- **SC-005**: 100% of validation issues carry all six mandatory fields populated.
- **SC-006**: For any `fix` run, a diff between original and corrected Markdown
  shows changes only within regions named in the validation report — zero edits
  elsewhere.
- **SC-007**: After any `fix` run, the original Markdown file is byte-identical to
  its pre-run state, in 100% of runs.
- **SC-008**: A default `convert` run completes with zero outbound network
  connections.
- **SC-009**: Running `convert` twice on the same PDF and the same page selection
  produces identical output filenames and identical Markdown content.
- **SC-010**: A user can trace any generated artifact back to its source PDF and
  exact physical page ranges using the traceability record, with no ambiguity.
- **SC-011**: 100% of Markdown headings map to the corresponding Word heading style
  on DOCX export.
- **SC-012**: When a local LLM is required but unavailable, `validate`, `fix`, and
  `convert` stop with an explanatory message in 100% of cases and never present a
  partial result as complete.
- **SC-013**: Pages with no text layer are converted via OCR and marked as
  OCR-derived in 100% of cases in the test corpus.
- **SC-014**: When any operation fails mid-run (including resource exhaustion on a
  very large document), no partially written output is left in a state that a
  consumer or the traceability record would treat as a complete artifact — 100% of
  failure cases.

## Assumptions

- The primary interface is a command-line application exposing the operations
  `extract`, `validate`, `fix`, `export`, and `convert`; a graphical interface is
  out of scope for the first version.
- One source PDF is processed per invocation; batch processing of multiple PDFs is
  out of scope for the first version.
- Physical PDF pages are indexed from 1.
- The tool is language-agnostic for text content and must handle at least
  Latin-script languages, including Portuguese.
- A "local LLM" means a language model that runs entirely on the user's machine;
  its selection and setup are the user's responsibility, and `validate` / `fix` /
  `convert` depend on it being present.
- Local OCR runs entirely on the user's machine; OCR language is auto-detected per
  page with an optional per-run user override.
- DOCX export uses standard built-in Word styles (heading levels, body/normal,
  bulleted and numbered list styles, table style) unless the user supplies a
  template.
- Generated artifacts are written to a user-controlled output location, never back
  to the source PDF's path.
- "Deterministic name" means the same source filename plus the same page selection
  always yields the same output filename; the naming scheme itself is defined
  during planning.
- The acceptance test corpus includes at least one long document with multi-page
  tables, running headers/footers, authentication stamps, and a mix of text-layer
  and scanned pages.
