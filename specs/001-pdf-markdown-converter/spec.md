# Feature Specification: Local-First PDF Document Converter

**Feature Branch**: `001-pdf-markdown-converter`

**Created**: 2026-09-05

**Status**: Draft

**Input**: User description: "Build a local-first PDF document converter that converts PDF files into semantically structured Markdown and optionally DOCX while preserving the original document's textual, numeric, hierarchical, and tabular content with high fidelity. [...] The entire default processing workflow must run locally on the user's machine without requiring paid APIs or cloud services."

## Clarifications

### Session 2026-09-08

- Q: (Refines the human-review workflow — FR-067–FR-074) How does a reviewer interact with HUMAN_REVIEW_REQUIRED items, how are decisions persisted and authorized, and how is the delivered Markdown verified against them? → A: The workflow is an **interactive terminal mode** of the command-line application — keyboard-driven (Up / Down / Enter to move through selectable options; no numeric-menu typing as the normal interaction), with **no** GUI, browser UI, local web server, OS-specific desktop application, or page-image / cropped-image previews. Each item shows enough context to locate and verify the disputed content against the original PDF (page, section, table / row / column, source context before and after, candidates, and a provenance label per candidate); a literal conflict offers the candidates plus **"Enter another value…"**, and an entered value is stored **exactly as typed** — never autocorrected, normalized, rewritten, or re-spaced. Every confirmed decision is persisted **immediately, before advancing**, and survives Ctrl+C / exit / terminal closure / process kill / machine restart; reopening resumes at the next unresolved applicable item and never re-asks resolved ones. A resolved item stays **reopenable and re-decidable**; changing an answer is append-only — the prior decision is retained in the audit history. Resolving the **last** item does **not** auto-resume processing: the workflow stops and offers **Review answers / Continue processing / Save and exit** (and, when reopened with everything already resolved but not authorized, **Review answers / Continue processing / Exit**); only "Continue processing" is explicit authorization. After authorization, human-confirmed resolutions flow through reconciliation → CED → deterministic semantic transformation → validation → render — **never** by patching the Markdown. When a delivery has one or more applicable human-review decisions, it also includes a **human-readable Markdown Human Review Report** (`<output-base>_review_report.md`) — a verification aid, not the authoritative audit log — whose per-item "Final Markdown" evidence is copied **literally** from the delivered artifact (no trim / strip / whitespace-collapse / Unicode- or punctuation-normalization / separator-rewrite / `<< >>` highlighting; report-only markers are allowed only on the *source-context* representation). Verification is **location-aware** — anchored to the reviewed source segment's processing lineage to its rendered Markdown span, not to any textual match elsewhere — and distinguishes an unauthorized literal alteration from a specification-permitted transformation. Each applicable decision gets an explicit **APPLIED AND VERIFIED** / **NOT APPLIED — VERIFICATION FAILED** status; a run with any failed verification is not a successful delivery (any Markdown produced exists only as a run-scoped non-deliverable intermediate, never at the delivered-Markdown name; the failure enters the validation/audit path classified by its originating stage — `reconciliation_error` or `disallowed_transformation`). This refines FR-067–FR-074 and adds FR-075–FR-084; it preserves the 0.75 reconciliation threshold, the candidate-selection restrictions, the LLM non-rewrite rules, `human_confirmed` semantics, deterministic replay/applicability, unresolved-review delivery blocking, and the `review` vs `fix` distinction.

### Session 2026-09-07

- Q: (Clarifies the v1 language scope) Which languages does v1 support, and what is out of scope? → A: v1 targets **Latin-script Western-language** documents. **Primary validated languages: Portuguese, English, Spanish** — these are the OCR-benchmark and release-acceptance-corpus dimensions. **French, Italian, German** must work through the same Latin-script OCR / pipeline path (character-coverage compatible; no Portuguese-specific hard-coding) but are **not** primary scored dimensions. **CJK and other non-Latin writing systems (Chinese, Japanese, Korean, …) are explicitly out of scope for v1.** OCR language identifiers stay generic BCP-47 / ISO-style strings (no enum in the schemas or data model), so a future writing system is an additive change — a new OCR model plus corpus — with no data-model or contract redesign. This **narrows** the earlier "language-agnostic … at least Latin-script" assumption; it changes no functional requirement.
- Q: How should `validate` decide that a Markdown and its source PDF have grossly diverged (e.g. the wrong Markdown was supplied)? → A: Measure the share of the selected pages' extractable source text that can be matched in the Markdown; when it falls below a configurable gross-divergence threshold (default 50%), set a `gross_divergence` indicator, lead the report with one summary issue stating the observed match rate, and suppress exhaustive line-level issues while still listing structural issues.
- Q: What should `validate`/`fix` do if the local LLM is reachable at probe time but then fails mid-run (timeout, HTTP error, unparseable response)? → A: Retry a bounded number of times (default 2); if it still fails, abort with the same clear message and exit status as an unavailable LLM, leaving no report or corrected file presented as complete.
- Q: Must the generated audit records be fully reproducible so an unchanged re-run is a byte-identical no-op rather than a collision error? → A: Yes. Record bodies carry no wall-clock timestamp or random run id; the deterministic run identifier is derived from the source hash, the normalized page selection, the tool version, and all output-affecting configuration, so every generated artifact is byte-identical across identical-input runs and a repeat run is a satisfied no-op.
- Q: Should standalone `validate` and `fix` accept the same OCR options as `extract` (language override, confidence threshold)? → A: Yes — both accept the optional OCR language override and the OCR confidence threshold with the same defaults and semantics as `extract`, since they re-derive text from the source PDF.
- Q: When `validate` detects gross divergence and will skip the semantic pass, does it still require a reachable local LLM? → A: No. The deterministic match-rate check runs first; when it detects gross divergence, `validate` skips the LLM probe and the semantic pass entirely and produces the gross-divergence report without a local LLM. A reachable LLM is still required for any run that does not short-circuit.
- Q: How is the processing pipeline structured with respect to source fidelity vs semantic transformation? → A: (SUPERSEDED by the independent-extraction refinement below — retained for history.) The earlier decision was a sequential model: one source-faithful extraction → fidelity validation of that single representation → semantic transformation → transformation validation → Markdown. This is replaced by the multi-path independent-extraction → reconciliation → transformation → final-validation model.
- Q: How does OCR behave on mixed/hybrid PDFs where native text quality varies within and across pages? → A: (Previously-decided OCR behavior; still applicable, now framed as one of the independent extraction paths.) OCR MUST be adaptive and region-aware, decided per page and per region — never document-wide by default. Native text is preferred wherever it is reliable; OCR is used only for pages/regions where native text is absent, incomplete, corrupted, or materially unreliable. Native and OCR-derived content may coexist on the same page, and a single region needing OCR MUST NOT cause OCR to replace reliable native text elsewhere. Every extracted region retains provenance: source page, source region/bbox where available, extraction technique, and OCR language/config where OCR was used. Pages/regions are conceptually classified as `native_text_sufficient`, `ocr_required`, or `hybrid_native_and_ocr`. OCR-derived text is subject to the same non-rewriting rule as all extracted text: no LLM may generate, improve, paraphrase, or substitute it.
- Q: (Refinement) How are extraction and reconciliation actually structured? → A: (Previously-decided architecture, recorded here — supersedes the sequential model above.) The original PDF is processed by **multiple independent extraction paths** — (A) a layout-aware structural extraction path, (B) a low-level geometry-aware PDF text extraction path, (C) conditional local OCR when needed — where no path may consume another path's output, so an error in one technique cannot propagate. Their outputs are then **reconciled** into a Canonical Extracted Document — via two sub-processes, literal-content reconciliation and reading-order reconciliation (see the reading-order refinement below): deterministic where the sources agree; where they materially disagree a local LLM MAY *select among the existing candidates only* (never generate, rewrite, paraphrase, correct, complete, normalize, combine, or substitute a value absent from the candidates), enforced programmatically, not by prompt text. The default reconciliation confidence threshold is 0.75 (configurable); below it the conflict becomes HUMAN_REVIEW_REQUIRED and is never silently guessed. Only after reconciliation does **semantic transformation** run (deterministic; the operations already specified; no LLM text rewriting). The transformed document then undergoes **final fidelity validation** against the original PDF and/or the independent extraction evidence — not merely the previous stage — detecting omissions, altered literals, incorrect reconciliation, invalid transformations, bad structural reconstruction, and unprovenanced content. The final Markdown is delivered only per the validation policy. Provenance, auditability, immutability, and the prohibition on presenting incomplete artifacts as complete all carry over.
- Q: (Resolves C-1) What is the layout-aware structural extraction path's structural interpretation authoritative for? → A: Nothing, during extraction/reconciliation. That path MAY do layout analysis, reading-order inference, and heading/table detection while extracting, but every such interpretation — from any extraction path — is **candidate evidence**. Its heading/list/table detection is a **structural hint** that reconciliation carries forward unaltered and unapplied (it MUST NOT accept, reject, merge, or act on a hint); only semantic transformation may accept/reject/apply hints, recording which it used. Its **reading-order inference** is handled differently — see the reading-order refinement below. The Canonical Extracted Document holds reconciled literal content, the accepted reading order, provenance, extraction evidence, and structural hints, but stays in a pre-semantic-transformation state. A structural inference from any extraction path is evidence, not an authoritative transformation.
- Q: (Resolves R-1/R-2) How is reading order handled across the independent extraction candidates? → A: Reading order is **independent extraction evidence**, not part of literal-text correctness. Each candidate keeps its own literal content, geometry/bboxes, candidate reading order, structural hints, and provenance separately. Extraction reconciliation therefore has two distinct sub-processes: **literal-content reconciliation** (which existing extracted content is accepted) and **reading-order reconciliation** (the accepted ordering of the existing source-backed segments). Reading-order reconciliation operates only on existing segments and candidate orders plus geometry/layout evidence — the LLM may never invent, rewrite, split, merge, or construct text, and may never produce an order unsupported by the evidence. It is deterministic where candidate orders agree or geometry resolves them; otherwise the LLM MAY select among existing candidate orders at confidence ≥ 0.75, and below 0.75 a reading-order HUMAN_REVIEW_REQUIRED item is raised (page, affected regions/bboxes, candidate segment ids, candidate orders, contributing sources, reason, confidence), resolved by a human inspecting the PDF and recorded as `human_confirmed`. Reading-order reconciliation completes before semantic transformation; semantic transformation may still do paragraph/list/heading/table-stitch operations but MUST keep any re-ordering it needs distinguishable from this source-ordering decision.
- Q: (Resolves H1 — reproducibility of LLM-assisted validation) Can FR-053a / SC-009 promise byte-identical audit records when a local LLM backend is non-deterministic? → A: No — split the guarantee into two levels. **FR-053a (deterministic core)**: the Markdown, DOCX, and every `check_origin: "deterministic"` record are byte-reproducible for identical effective inputs (source hash, normalized selection, enabled paths, OCR engine/model/config, reconcile threshold, tool version, applicable `human_confirmed` resolutions); `run_id` stays a pure function of those, with no wall-clock/random workaround. (v1 semantic transformation is deterministic and has no output-affecting configuration, so it adds nothing to the effective inputs; any future output-affecting semantic-transformation setting must then be added — see FR-053a.) **FR-053b (LLM-assisted results)**: byte-identical *only* when the backend provides `temperature: 0` + a reliable `seed`; then the report records `llm.reproducibility: "deterministic"`. When it cannot, the report records `"best_effort"`, states the backend cannot guarantee deterministic regeneration, and a re-run **replays** the persisted semantic section for an identical applicability context rather than regenerating it or raising a collision. Deterministic guards, candidate-selection invariants, and the no-source-modification rule stay mandatory. SC-009 is restated in these two levels so it is measurable and does not over-promise.
- Q: (Resolves the HUMAN_REVIEW_REQUIRED workflow) What is the full lifecycle of a human-review item? → A: HUMAN_REVIEW_REQUIRED is an explicit reconciliation state (not a validation warning), raised from any reconciliation decision below the confidence threshold. A reviewer resolves it against the original PDF: for a literal conflict, by selecting a candidate or — only when none is correct — entering a value verified against the PDF (recorded `human_confirmed` with manually-verified provenance; no automatic stage or LLM ever gets this permission); for a reading-order conflict, by ordering the existing segments without rewriting their content. Every resolution is persisted to a durable, append-only, cross-run **resolution store** (source hash, page/region, conflict type, candidate evidence, selected/entered value, accepted ordering, `decision_method = human_confirmed`, link to the review item). Resolutions are deterministic replay inputs: an unchanged applicable resolution is replayed (not re-asked) and yields the same result; when its output-affecting context changed it is not replayed and a fresh item is raised; the applicability key's exact shape is a planning decision but must carry enough source + configuration identity to prevent misapplication. Any unresolved item blocks the run's final Markdown (intermediate artifacts + the queue may still be written); once all are resolved, re-running resumes from the right reconciliation state with no hand-editing of Markdown. This is distinct from `fix`: human review resolves extraction-reconciliation uncertainty; `fix` addresses post-transformation defects; a `reconciliation_error` found by final validation is routed back to the human-review layer, never patched Markdown-only. The concrete CLI / UI / file format is a planning/contract decision.

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

Internally `extract` runs the pipeline (FR-059): the PDF is extracted by several
independent paths (a layout-aware structural extraction path; a low-level
geometry-aware PDF text extraction path; conditional local OCR where needed), their
outputs are reconciled into a Canonical Extracted Document, and only then are the
semantic transformations above applied and the Markdown rendered, subject to final
fidelity validation. Where the extraction paths disagree and the tool is not
confident enough to pick automatically, `extract` emits a human-review queue and
delivers no final Markdown for the run until every review item is resolved.

**Why this priority**: This is the core value proposition and the minimum
shippable product. Without trustworthy extraction, nothing else in the tool
matters. It is independently useful on its own.

**Independent Test**: Run `extract` against a representative PDF with and without
page selections; confirm the Markdown reproduces the source text, preserves
heading hierarchy and tables, removes artifacts, uses the expected deterministic
filename without overwriting anything, and that a page engineered to make the
extraction paths disagree below the confidence threshold produces a
HUMAN_REVIEW_REQUIRED item rather than a silently-guessed Markdown. Then run the
interactive `review` workflow: resolve the item with the keyboard, confirm the
decision is persisted before advancing and survives an interruption, confirm the
workflow stops for an explicit "Continue processing" authorization rather than
auto-resuming, and confirm the authorized run delivers the final Markdown **plus**
a Human Review Report whose per-item final-Markdown evidence matches the delivered
document exactly and whose verification status is APPLIED AND VERIFIED.

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
6a. **Given** a selected page with a reliable native text layer in most of the page
   and one image-only region, **When** the user runs `extract`, **Then** the native
   text is kept verbatim, only the image-only region is OCR'd and marked
   OCR-derived, the page is classified `hybrid_native_and_ocr`, and OCR does not
   replace the page's native text.
7. **Given** an output file with the deterministic name already exists, **When**
   the user runs `extract` again, **Then** the existing file is not overwritten and
   the user is told how the collision was handled.
8. **Given** a page where the independent extraction paths produce materially
   different text for a region and automatic reconciliation confidence is below
   0.75, **When** the user runs `extract`, **Then** a HUMAN_REVIEW_REQUIRED item is
   produced with the PDF page, region, each source's candidate value, the reason,
   and the confidence, and the run delivers no final Markdown until it is resolved
   (the human-review queue and intermediate artifacts are still written).
9. **Given** the same page where the extraction paths disagree but reconciliation
   confidence is at least 0.75, **When** the user runs `extract` with a local LLM
   available, **Then** the LLM selects one of the existing candidate values exactly
   as supplied, and the choice and confidence are recorded in the reconciliation
   log.
10. **Given** a multi-column page where the extraction paths agree on the literal
   text but disagree on reading order and the geometry does not resolve it, **When**
   the user runs `extract` below 0.75 confidence, **Then** a reading-order
   HUMAN_REVIEW_REQUIRED item is produced (page, affected regions, candidate
   segment ids, the candidate orders, contributing sources, reason, confidence),
   the literal text is not rewritten or re-segmented, and the run delivers no final
   Markdown until the ordering is confirmed.
11. **Given** a HUMAN_REVIEW_REQUIRED item whose literal candidates are all wrong,
   **When** the reviewer selects "Enter another value…" and types the correct value
   verified against the original PDF, **Then** the value is stored **exactly as
   typed** (no autocorrect, normalization, re-spacing, or separator rewrite),
   recorded as `human_confirmed` with manually-verified provenance, and a later
   identical run replays that resolution instead of asking again.
12. **Given** an open HUMAN_REVIEW_REQUIRED item presented in the interactive
   `review` workflow, **When** the reviewer moves through the candidates with the
   Up/Down arrows and presses Enter on one, **Then** the choice is confirmed
   without the reviewer typing a numeric menu index, and the item shows the PDF
   page, section / table / row / column where available, the source context before
   and after the disputed segment, and a provenance label for each candidate.
13. **Given** a `review` session in which the reviewer has confirmed some but not
   all items, **When** the process is interrupted (Ctrl+C, terminal closure, or a
   kill) and `review` is reopened, **Then** the already-confirmed decisions are
   still present, none of them is asked again, and the workflow resumes at the next
   unresolved applicable item.
14. **Given** a `review` session where the reviewer answers the final unresolved
   item, **When** that answer is confirmed, **Then** document processing does **not**
   resume automatically; the workflow stops and presents an interactive choice
   equivalent to "Review answers", "Continue processing", and "Save and exit", and
   only choosing "Continue processing" authorizes the pipeline to resume.
15. **Given** a run whose review items are all resolved but which was exited with
   "Save and exit" (processing never authorized), **When** `review` is reopened,
   **Then** it recognises that state and offers a choice equivalent to "Review
   answers", "Continue processing", and "Exit" — it never continues automatically
   just because every item is resolved.
16. **Given** a previously resolved review decision, **When** the reviewer opens
   "Review answers", selects that entry with the keyboard, and records a different
   value or order, **Then** the prior decision is retained in the audit history
   (previous decision, replacement decision, and which is currently applicable are
   all recoverable) and the new decision re-propagates through reconciliation, the
   Canonical Extracted Document, semantic transformation, and validation — never by
   editing the delivered Markdown.
17. **Given** an authorized run that had at least one applicable human-review
   decision, **When** the final Markdown is delivered, **Then** a Human Review
   Report `<output-base>_review_report.md` is delivered alongside it; for each
   applicable decision the report shows the source location and context, the
   candidates, the human-confirmed value/order, the corresponding final-Markdown
   excerpt copied **literally** from the delivered document, and an explicit
   APPLIED AND VERIFIED status; and the report summary shows PASS with the count of
   decisions applicable, resolved, and verified.
18. **Given** an authorized run where the final Markdown at a reviewed segment's
   rendered location differs from the human-confirmed literal only by spacing, a
   thousand separator, or a punctuation character, **When** final verification
   runs, **Then** that decision's status is NOT APPLIED — VERIFICATION FAILED, the
   run is not presented as a successful delivery, and the failed item (with its
   expected decision and the actual final-Markdown evidence) appears in the Human
   Review Report and enters the `reconciliation_error` validation workflow.

---

### User Story 2 - Validate a generated Markdown against its source PDF (Priority: P2)

A user who has an extracted Markdown wants to know exactly where and how it
deviates from the source before relying on it. They run the `validate` operation
with the Markdown and the source PDF (and page selection). They receive a
validation report — a separate artifact — that does not change the Markdown.
Every issue in the report states its severity, the source PDF page, the Markdown
line and column, the issue type, and a clear description of the problem; where
applicable it also gives the source location, the expected value or structure,
the found value or structure, and a suggested corrective action. Each issue is
also classed as an `extraction_error`, a `reconciliation_error`, or a
`disallowed_transformation`, so the user can tell which pipeline stage introduced
the fault (this operation is the final fidelity validation — FR-065). It compares
the Markdown against the original PDF and the independent extraction evidence,
combining deterministic checks with semantic checks performed by a single local
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
   structure, classed as a `disallowed_transformation`.
3a. **Given** a Markdown where a table cell's text was mis-read during extraction,
   **When** the user runs `validate`, **Then** the issue is classed as an
   `extraction_error`, distinct from a normalization fault.
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
the wording. `fix` handles only post-transformation defects; an issue that
final fidelity validation attributes to a wrong reconciliation decision
(`reconciliation_error`) is routed back to the human-review layer instead of being
patched in the Markdown (FR-045a/FR-073).

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
7. **Given** a validation report whose issue is classed `reconciliation_error`
   (a wrong literal selection or wrong accepted reading order), **When** the user
   runs `fix`, **Then** `fix` does not edit the Markdown for that issue and instead
   routes it back to the human-review layer, so the corrected source decision is
   re-applied through semantic transformation and re-validated.

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
6. **Given** a `convert` run whose `extract` stage raises HUMAN_REVIEW_REQUIRED
   items, **When** the run reaches the review queue, **Then** `convert` stops
   before `validate`, delivers no final Markdown or traceability record, and
   resumes only after the items are resolved through the interactive `review`
   workflow **and** the reviewer explicitly authorizes downstream processing; the
   completed run then also delivers the Human Review Report and links it in the
   traceability record.

---

### Edge Cases

- **No text layer on a page**: local OCR is applied to the whole page and its text
  is marked as OCR-derived, with per-region provenance.
- **Low-confidence OCR regions**: surfaced as validation issues rather than
  silently accepted.
- **Page that is partly a text layer and partly an image**: OCR supplies candidates
  for the image regions; reconciliation keeps native text for the reliable regions
  and OCR for the rest; the OCR-derived regions are marked and the page keeps its
  reliable native text (FR-026/FR-026a).
- **Page with an incomplete, corrupted, or materially unreliable native text
  layer**: OCR provides a candidate for the unreliable regions; reconciliation
  chooses per region, keeping reliable native regions; the page is classified
  `hybrid_native_and_ocr` and each candidate is retained with provenance
  (FR-024/FR-025b/FR-063).
- **Extraction paths materially disagree on a region and confidence ≥ 0.75**: the
  local LLM selects one of the existing candidates exactly as supplied; the choice
  and confidence are recorded in the reconciliation log (FR-061/FR-062).
- **Extraction paths materially disagree and confidence < 0.75** (or no LLM is
  available): a HUMAN_REVIEW_REQUIRED item is produced with page/line/column, each
  candidate, the reason, and the confidence; the run delivers no final Markdown
  until every required review item is resolved (FR-062/FR-067/FR-072/FR-066b).
- **The reconciliation LLM returns a value that is not one of the supplied
  candidates**: the response is rejected programmatically and the conflict is
  treated as unresolved → HUMAN_REVIEW_REQUIRED (FR-061b).
- **Extraction candidates agree on literal text but produce different reading
  orders** (e.g. a two-column page, a sidebar, a footnote block): literal-content
  reconciliation succeeds; reading-order reconciliation resolves the order from
  geometry where unambiguous, else via the LLM (≥ 0.75, selecting an existing
  candidate order) or a reading-order HUMAN_REVIEW_REQUIRED item (< 0.75) — it is
  never resolved by rewriting or re-segmenting the text (FR-061d/FR-062d).
- **An extractor's inferred reading order conflicts with the geometric layout
  evidence**: the inference is one candidate among others and geometry is
  deterministic evidence; neither is automatically canonical — reading-order
  reconciliation weighs them per FR-061d.
- **The reconciliation LLM proposes a reading order not present in any candidate
  and not supported by geometry**: rejected programmatically → reading-order
  HUMAN_REVIEW_REQUIRED (FR-061b/FR-061d).
- **None of the extraction candidates is correct for a literal-content conflict**:
  the reviewer selects "Enter another value…" and types the correct value after
  verifying it against the original PDF; it is stored **exactly as typed** (no
  autocorrect / normalization / re-spacing / separator rewrite) and recorded as
  `human_confirmed` with manually-verified provenance (FR-068). No automatic stage
  may do this.
- **A recorded human resolution's context has changed on a later run** (e.g. a
  different OCR confidence threshold, a different extraction engine, a page
  selection that shifts the affected region): the resolution is **not** replayed
  or silently reused; a fresh HUMAN_REVIEW_REQUIRED item is raised (FR-071 /
  FR-079).
- **A `review` session is interrupted after some answers are confirmed** (Ctrl+C,
  terminal closure, process kill, machine restart): every confirmed decision was
  persisted before the workflow advanced, so on reopening none of them is asked
  again and the workflow resumes at the next unresolved applicable item (FR-070).
- **The reviewer answers the last unresolved item**: processing does **not** resume
  automatically; the workflow stops and offers "Review answers" / "Continue
  processing" / "Save and exit", and only "Continue processing" authorizes the
  pipeline to resume (FR-077).
- **`review` is reopened when every item is already resolved but processing was
  never authorized**: the workflow recognises the "all resolved, not authorized"
  state and offers "Review answers" / "Continue processing" / "Exit" — it never
  continues automatically merely because the queue is empty (FR-077).
- **The reviewer reopens an earlier resolved item and records a different answer**:
  the prior decision is retained in the append-only audit history (previous,
  replacement, and currently-applicable decision all recoverable) and the new
  decision re-propagates through reconciliation → CED → semantic transformation →
  validation → render, never by editing the Markdown (FR-076 / FR-079).
- **After authorization, the pipeline resumes**: applicable human-confirmed
  resolutions flow through reconciliation and the Canonical Extracted Document into
  deterministic semantic transformation and final validation; the user never edits
  the generated Markdown by hand to finish the run (FR-072 / FR-079).
- **The human-confirmed value also appears verbatim elsewhere in the final
  Markdown**: final verification is location-aware — it confirms the decision at the
  reviewed source segment's rendered Markdown span via its processing lineage, not
  at the first textual match (FR-083).
- **The final Markdown at the reviewed span differs from the human-confirmed
  literal only by spacing, a thousand/decimal separator, a punctuation character,
  or a Unicode variant**: verification does **not** treat it as equivalent; the
  decision is marked NOT APPLIED — VERIFICATION FAILED and successful delivery is
  blocked (FR-083 / FR-084).
- **An allowed structural transformation occurs around a reviewed segment** (e.g. a
  pipe table becomes an HTML `<table>`, a paragraph is reflowed) while the reviewed
  literal is preserved intact: verification passes, and the Human Review Report
  shows the **actual delivered excerpt** (HTML / reflowed) around the unchanged
  literal (FR-082 / FR-083).
- **Final verification fails for one applicable human-review decision while others
  pass**: the Markdown may be written as a non-successful / intermediate output,
  successful delivery is blocked, the failed item plus its human-confirmed expected
  decision and the actual final-Markdown evidence are recorded in the Human Review
  Report, and the failure enters the final-fidelity-validation / audit workflow
  classified by its originating stage — `reconciliation_error` or
  `disallowed_transformation` (FR-084) — rather than being ignored (FR-034a /
  FR-073).
- **A reading-order HUMAN_REVIEW_REQUIRED item**: the reviewer chooses / reorders
  the existing source-backed segments in the interactive workflow and MUST NOT
  rewrite any segment's literal content as part of an order-only resolution; all
  cross-cutting human-review rules — immediate persistence, resumability, answer
  browsing, append-only history, explicit authorization, downstream replay,
  location-aware final verification, and Human Review Report inclusion — apply to
  the order decision as well (FR-069).
- **Final fidelity validation finds an earlier reconciliation decision was wrong**
  (wrong literal selection or wrong accepted reading order): the issue is routed
  back to the human-review layer, not patched by `fix`; the corrected decision
  re-propagates through semantic transformation and final validation
  (FR-045a/FR-073).
- **Local LLM not installed / not configured** when `validate`, `fix`, or
  `convert` is run: the operation stops with a clear message; no partial result
  is presented as complete. Exception: a `validate` run that short-circuits on
  gross divergence (FR-036a) needs no local LLM and completes normally.
- **Local LLM reachable at probe time but fails mid-run** (timeout, transport or
  HTTP error, or a response that cannot be parsed): the operation retries a
  bounded number of times (default 2) and, if still failing, stops with the same
  clear message and exit status as an unavailable LLM; no partial validation
  report or corrected file is presented as complete.
- **Local LLM backend cannot honour the decode seed** (non-deterministic
  regeneration): the deterministic artifacts (Markdown, DOCX, deterministic
  records) stay byte-identical across runs (FR-053a); the validation report records
  `llm.reproducibility: "best_effort"` and states the backend cannot guarantee
  deterministic regeneration; a re-run for an identical applicability context
  **replays** the persisted semantic issues rather than regenerating them, and does
  **not** raise a collision (FR-053b).
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
  the line break. **v1 policy (research §27, authoritative): keep the trailing
  hyphen by default; remove it only when the joined token — the two fragments with
  the boundary hyphen deleted — occurs elsewhere in the same document as a complete
  token, and the structural guards hold. No dictionary, no LLM. Ambiguous ⇒ keep
  the hyphen; validation may flag it later.**
- **Document with no detectable headings**: produced as a flat structure; not
  fabricated hierarchy.
- **Table that starts mid-page after other content, or spans more than two
  pages**: still reconstructed as one logical table.
- **Vertical text that is meaningful content** (a rotated table, a sidebar note)
  vs. vertical authentication text: meaningful vertical text is preserved.
- **Markdown and PDF fundamentally diverge** (wrong Markdown passed to
  `validate`): when less than a configurable share (default 50%) of the selected
  pages' extractable source text can be matched in the Markdown, the report sets
  the `gross_divergence` indicator, leads with a single summary issue stating the
  observed match rate, and suppresses exhaustive line-level issues; structural
  issues are still listed. It never fails silently.
- **Validation report references a Markdown region that no longer exists** when
  `fix` runs: that issue is reported as unresolvable rather than applied to the
  wrong location.
- **Deterministic filename collision with different content**: the existing file
  is preserved and the collision is surfaced to the user.
- **Very large PDF**: no fixed page or size limit is imposed; the document is
  processed within available machine resources. If resources are exhausted
  mid-run, the operation fails cleanly and never presents a partially written
  artifact as complete.
- **Rotated or mixed-orientation pages**: each extraction candidate contributes its
  reading order for the page; reading-order reconciliation (FR-061d) establishes
  the accepted order, from geometry where unambiguous.
- **Final fidelity validation fails** (omitted content, altered literal, incorrect
  reconciliation, invalid transformation, bad structural reconstruction, or
  unprovenanced content): the final Markdown is delivered only as the validation
  policy allows; a failing outcome under the policy MUST NOT yield a delivered
  Markdown presented as complete (FR-065).
- **An issue is ambiguous between an extraction error, a reconciliation error, and
  an intentional transformation**: final fidelity validation reports it, defaulting
  to the more serious class and noting the ambiguity, rather than silently treating
  it as an allowed transformation.
- **One extraction path fails entirely** (e.g. the layout-aware structural
  extraction path errors on a page): the
  remaining independent paths still run; reconciliation proceeds with the
  candidates it has, and the missing path is noted in the reconciliation log — one
  path's failure never blocks the others (FR-060).

## Requirements *(mandatory)*

### Functional Requirements

#### Processing pipeline: independent extraction → reconciliation → transformation → final validation

This subsection is foundational and **supersedes the earlier sequential
single-extraction model** (a single source-faithful extraction feeding fidelity
validation, then transformation). The operations named in every other subsection
run within this pipeline; the transformations listed elsewhere (FR-006–FR-022) are
all **stage-3 semantic transformations** and MUST NOT occur before reconciliation
(stage 2) completes. No requirement in this spec may describe both architectures.

- **FR-059**: The document processing pipeline MUST run as ordered stages:
  (1) independent multi-path extraction; (2) extraction reconciliation — comprising
  **literal-content reconciliation** and **reading-order reconciliation** — into a
  Canonical Extracted Document; (3) semantic transformation; (4) final fidelity
  validation; (5) final Markdown delivery. Stage 3 MUST NOT begin before stage 2
  has produced a Canonical Extracted Document (with an accepted reading order) for
  the requested pages. This model replaces the earlier sequential model entirely.
- **FR-060**: The original PDF MUST be processed **independently** by multiple
  extraction techniques. For v1 the primary paths are: (A) a **layout-aware
  structural extraction path**, processing
  the original PDF directly and producing its own extraction candidate (literal
  content plus structural hints — see FR-060b); (B) a **low-level geometry-aware
  PDF text extraction path**,
  processing the original PDF independently of path A and producing a second
  extraction / evidence candidate; (C) **conditional local OCR**, used when necessary — not
  mandatory for every
  page, MUST support mixed PDFs where some pages have usable native text and others
  are image-only or otherwise require OCR (per FR-024–FR-027b), producing an
  additional independent extraction candidate. **No extraction path may consume or
  depend on the output of another extraction path.** The purpose of this
  independence is to prevent an extraction error in one technique from propagating
  into the others.
- **FR-060a**: Each extraction candidate is a set of **source-backed segments**.
  Every segment MUST retain, separately and where available: the literal extracted
  content; the source geometry / bounding box; that candidate's **reading-order
  position** for the segment; any structural hints attached to it; and provenance
  (source PDF page, extraction technique, and for OCR the language(s) /
  configuration). Reading order is kept as its own field, not folded into
  literal-text correctness.
- **FR-060b**: An extractor (the layout-aware structural extraction path in
  particular) MAY perform layout analysis,
  reading-order inference, and heading / table / structure detection while
  extracting. Its **reading-order inference** is candidate evidence for
  reading-order reconciliation (FR-061d) and MUST NOT automatically become the
  canonical reading order. Its **other structural interpretation** (heading, list,
  table detection) is a **structural hint** — evidence only, neither reconciled nor
  applied before semantic transformation (FR-061c / FR-064). Neither may directly
  modify or define the Canonical Extracted Document's semantic structure during
  extraction or reconciliation. Such a structural inference is evidence, not an
  authoritative transformation.
- **FR-061**: After the independent extraction paths complete, extraction
  reconciliation assembles the **Canonical Extracted Document** through two distinct
  sub-processes — **literal-content reconciliation** (this requirement) and
  **reading-order reconciliation** (FR-061d) — while preserving provenance and
  carrying every extractor's structural hints forward unaltered and unapplied
  (FR-061c). Reconciliation applies **no** semantic normalization or structural
  transformation. **Literal-content reconciliation** determines which existing
  extracted literal content is accepted: where the candidates' literal content
  agrees, deterministic reconciliation MUST be preferred and no LLM decision is
  required; where it **materially disagrees**, a local LLM MAY analyze the
  conflicting alternatives, its role **strictly limited to selecting among the
  existing extracted candidates**. Reading order is not part of this comparison —
  two candidates MAY have identical literal content but different candidate reading
  orders.
- **FR-061a**: In either reconciliation sub-process the LLM MUST NEVER: generate
  new source text; rewrite source text; paraphrase source text; correct spelling or
  grammar; complete missing text; normalize source text; split, merge, or combine
  fragments into a new textual alternative; substitute any extracted value with a
  value not present in the supplied candidates; or construct a reading order not
  supported by the extraction evidence. A valid automatic LLM decision MUST select
  something that already exists in the candidates — an extracted value **exactly as
  supplied** (literal-content reconciliation) or an existing candidate / geometry-
  supported ordering (reading-order reconciliation).
- **FR-061b**: The application MUST enforce FR-061a **programmatically** — it MUST
  NOT rely only on prompt instructions. If the LLM returns a value or an ordering
  that does not correspond exactly to an allowed existing candidate (or, for
  ordering, to a deterministic geometry-supported ordering), the response MUST be
  rejected and the conflict treated as unresolved (FR-062).
- **FR-061c**: Neither reconciliation sub-process may accept, reject, merge, or act
  on a **structural hint** (heading / list / table detection). Hints are carried
  forward into the Canonical Extracted Document as attributed evidence; deciding
  what to do with them belongs to semantic transformation (FR-064). This is
  distinct from reading order, which *is* reconciled (FR-061d) before semantic
  transformation.
- **FR-061d**: **Reading-order reconciliation** determines the accepted ordering of
  the existing source-backed segments. It MUST operate only on those segments and
  the candidates' reading orders, with supporting geometry / layout evidence; it
  never changes segment content, and it never splits or merges segments to force an
  order.
  - Where the candidate reading orders agree, or deterministic geometric / layout
    evidence resolves the ordering unambiguously, deterministic reconciliation
    SHOULD be used and no LLM decision is required.
  - Where the candidate reading orders **materially disagree** and deterministic
    evidence is insufficient, the local reconciliation LLM MAY analyze the existing
    candidate orders and the supporting geometry / layout evidence (subject to
    FR-061a / FR-061b). A valid automatic decision selects an existing candidate
    ordering, or a deterministic geometry-supported ordering, exactly — never an
    arbitrary new order unsupported by the evidence.
  - The FR-062 confidence threshold applies: at confidence **≥ 0.75** an existing
    supported candidate ordering MAY be selected automatically; at confidence
    **< 0.75** the conflict becomes a HUMAN_REVIEW_REQUIRED item (FR-062d).
  Reading-order reconciliation completes **before** semantic transformation; the
  accepted order is recorded in the Canonical Extracted Document with provenance
  (FR-063).
- **FR-062**: The default automatic reconciliation confidence threshold MUST be
  **0.75** and MUST be configurable. It and the never-silently-guess rule apply to
  **both** reconciliation sub-processes — literal-content conflicts (FR-061) and
  reading-order conflicts (FR-061d). When candidates disagree: at confidence
  **≥ 0.75** the LLM MAY select an existing candidate (value, or ordering); at
  confidence **< 0.75** automatic reconciliation MUST stop for that conflict and
  produce a **HUMAN_REVIEW_REQUIRED** item. The system MUST NEVER silently guess
  when confidence is below the configured threshold.
- **FR-062a**: A HUMAN_REVIEW_REQUIRED item for a **literal-content** conflict MUST
  provide enough information for a person to inspect the original PDF, including at
  minimum where applicable: PDF page; line; column; source region / bounding box
  when available; the candidate value produced by each extraction source; the
  reason the conflict could not be resolved automatically; and the LLM confidence.
- **FR-062b**: A HUMAN_REVIEW_REQUIRED item is resolved by a human against the
  original PDF and persisted as an auditable `human_confirmed` reconciliation
  decision. The resolution lifecycle — how it is resolved, what is persisted, how
  it is replayed, and how it unblocks the run — is specified in *Human review
  workflow* (FR-067–FR-084).
- **FR-062c**: Any unresolved HUMAN_REVIEW_REQUIRED item blocks delivery of the
  final Markdown for the run (FR-072); intermediate artifacts and the human-review
  queue MAY still be written for diagnosis.
- **FR-062d**: A HUMAN_REVIEW_REQUIRED item for a **reading-order** conflict MUST
  include, where applicable: the PDF page; the affected regions / bounding boxes;
  the candidate segment identifiers; the candidate reading orders; the contributing
  extraction sources; the reason for the uncertainty; and the confidence.
- **FR-063**: The result of reconciliation is the **Canonical Extracted Document**.
  It contains: the reconciled literal content of the source-backed segments; the
  **accepted reading order** over those segments (FR-061d); source provenance and
  extraction evidence; and the extractors' structural hints. It MUST still
  represent a **pre-semantic-transformation state** — literal-content and
  reading-order differences among the candidates are resolved, but no structural
  hint has been accepted or applied and **no semantic normalization has occurred**;
  the accepted reading order is a source-ordering decision, not a structural
  transformation. It MUST preserve provenance sufficient to trace every value and
  the accepted order back to: the original PDF page / region; the contributing
  extraction source(s); the reconciliation decision; and whether it was
  deterministic, LLM-selected, or human-confirmed. The Canonical Extracted Document
  and the individual extraction candidates are internal intermediates; if persisted
  they are never mutated in place, and they are persisted as **JSON only** — the
  machine-readable source of truth, with no Markdown companion. Only the audit
  records of FR-057 receive a generated Markdown rendering, and no processing stage
  may consume a Markdown rendering as source truth.
- **FR-064**: Semantic transformations MAY occur only **after** extraction
  reconciliation. This stage — and only this stage — MAY **accept, reject, or
  apply** the structural hints carried in the Canonical Extracted Document, and it
  performs the operations specified elsewhere: joining artificial visual line wraps
  (FR-013), repairing end-of-line hyphenation (FR-014), reconstructing logical
  paragraphs, assigning headings and hierarchy (FR-017/FR-017a), reconstructing
  lists (FR-018/FR-019), merging multi-page table fragments into logical tables
  (FR-020–FR-022), removing repeated non-semantic headers/footers, page numbers,
  and authentication / decorative artifacts (FR-006–FR-011), and other allowed
  structural normalization. It consumes the reading order fixed by reading-order
  reconciliation (FR-061d) and MUST NOT silently re-order source segments; if a
  structural operation would require a different segment order, that is a distinct,
  recorded decision, not part of the earlier source-ordering decision. A structural
  hint (from any extraction path) is advisory: this stage decides whether to
  use it, and MUST record that decision so it is auditable and distinguishable from
  the reading-order decision. Semantic transformation MUST NOT use an LLM to
  rewrite, improve, correct, paraphrase, or replace source text. Any textual result
  MUST remain deterministically derived from the reconciled content, subject only
  to the explicitly permitted structural transformations.
- **FR-065**: After semantic transformation, the resulting semantic document MUST
  undergo **final fidelity validation** that compares it against the original PDF,
  the independent extraction evidence, and the reconciliation provenance — each
  where available — not merely against the immediately preceding pipeline stage.
  It MUST be able to detect: omitted source content; altered literal values;
  incorrect literal-content reconciliation; a wrong or lost reading order relative
  to the source; invalid semantic
  transformations; incorrect structural reconstruction; and content introduced
  without source provenance. The final Markdown is produced / delivered only
  according to the validation policy; a validation outcome the policy treats as
  failing MUST NOT yield a delivered Markdown presented as complete.
- **FR-066**: Every unit of content in the final Markdown MUST be traceable back
  through the semantic document and the Canonical Extracted Document to its
  originating PDF page / region, the contributing extraction source(s), and the
  reconciliation decision. This provenance chain backs SC-001 and the source
  locations reported by `validate`.
- **FR-066a**: The externally invocable **document-processing** operations remain
  `extract`, `validate`, `fix`, `export`, and `convert`. In addition, the
  human-review workflow (FR-067–FR-084) is driven through its own dedicated
  operation — the `review` command at the CLI layer — which is an **interactive,
  keyboard-driven terminal mode** (FR-074); the specific terminal-interaction
  library and file formats are planning / contract decisions. The tool's full
  invocable surface is therefore these five document-processing operations **plus**
  the separate human-review operation. `extract` performs stages 1–3 plus a
  built-in final fidelity self-check. When reconciliation raises HUMAN_REVIEW_REQUIRED
  items, `extract` emits the human-review queue and the intermediate artifacts and
  delivers **no** "original Markdown" for that run (FR-072); otherwise it emits the
  "original Markdown" subject to the validation policy. The `validate` operation
  performs the full final fidelity validation (FR-065), including its local-LLM
  semantic pass, against a produced Markdown and its source PDF. `convert` composes
  `extract` then `validate`.
- **FR-066b**: LLM use in the whole pipeline is confined to two analysis-only
  roles: (1) extraction-reconciliation candidate-selection — both literal-content
  and reading-order (FR-061/FR-061a/FR-061b/FR-061d); (2) semantic-validation issue
  detection (FR-037). In neither role may an LLM emit, complete, or alter source
  text, nor construct an unsupported reading order. `extract` MUST still run
  without a local LLM: both reconciliation sub-processes then use deterministic
  agreement / geometry only, and every material disagreement they cannot resolve
  deterministically becomes a HUMAN_REVIEW_REQUIRED item rather than being
  auto-resolved.

#### Human review workflow

*HUMAN_REVIEW_REQUIRED is a first-class part of extraction reconciliation, not a
validation warning. This subsection defines its lifecycle and its interaction
model (an interactive terminal workflow — FR-074); the specific terminal-interaction
library, file formats, and lineage / Markdown-span data structures remain
planning / research / data-model / contract decisions.*

- **FR-067**: HUMAN_REVIEW_REQUIRED is an explicit **reconciliation state**. It is
  raised whenever an automatic reconciliation decision cannot be made at or above
  the configured confidence threshold (FR-062) — today from unresolved
  literal-content reconciliation (FR-061) or unresolved reading-order
  reconciliation (FR-061d), and from any future reconciliation decision that
  adopts this same mechanism. When the threshold is not met the system MUST create
  a HUMAN_REVIEW_REQUIRED item and MUST NOT guess.
- **FR-068** (resolving a literal-content conflict): A reviewer resolves the item
  by inspecting the original PDF and either (a) selecting one of the extraction
  candidates presented, or (b) choosing **"Enter another value…"** and typing the
  correct literal text / value directly — **only** when none of the candidates is
  correct, and only after verifying it against the original PDF. A human-entered
  literal value is permitted **only** through this explicit human-review workflow;
  it MUST be captured **exactly as the reviewer types it** and recorded as
  `human_confirmed` source truth whose provenance states it was manually verified
  against the original PDF. The system MUST NOT autocorrect, normalize, rewrite,
  suggest a replacement for, or alter the punctuation, spacing, Unicode, or
  decimal / thousand separators of an entered value — an entered value represents
  an explicitly human-verified source literal. This human exception grants no
  automatic stage, and no LLM, any permission to invent, correct, rewrite,
  normalize, complete, merge, split, or substitute source text — FR-029, FR-037,
  FR-044, and FR-061a remain fully in force.
- **FR-069** (resolving a reading-order conflict): A reviewer resolves the item by
  choosing / reordering the **existing** source-backed segments after inspecting
  the original PDF. An order-only resolution MUST NOT permit literal rewriting of
  any segment — a literal-content error noticed during a reading-order review MUST
  be raised as its own literal-content review item (FR-068), not fixed inline. All
  cross-cutting human-review rules — immediate persistence and resumability
  (FR-070), reopen-and-change with append-only history (FR-076), explicit
  processing authorization (FR-077), review-answer browsing (FR-078), downstream
  replay through reconciliation and the Canonical Extracted Document (FR-079), and
  location-aware final verification plus Human Review Report inclusion (FR-080–
  FR-084) — apply equally to reading-order decisions.
- **FR-070** (persisted resolution — immediate and resumable): Every human
  resolution MUST be persisted as an auditable reconciliation decision identifying
  at least: the source document identity / hash; the relevant page / region; the
  conflict type; the candidate evidence originally presented; the selected
  candidate or the human-entered literal value, where applicable; the accepted
  segment ordering, for a reading-order conflict; the decision method
  `human_confirmed`; and provenance sufficient to trace the decision to the
  originating review item. Each confirmed decision MUST be persisted
  **immediately, before the workflow advances to the next item**. The persisted set
  of confirmed decisions MUST survive Ctrl+C, a voluntary exit, terminal closure,
  process termination, and a machine restart; a reviewer reopening the workflow
  MUST NOT be asked to resolve an already-resolved applicable item again, and the
  normal resume behaviour continues from the next unresolved applicable item. Once
  persisted, the item MUST NOT be treated as unresolved (it MAY still be reopened
  and re-decided — FR-076).
- **FR-071** (replay and reproducibility): A recorded `human_confirmed` resolution
  is an explicit **deterministic input** to later processing — never hidden
  nondeterministic state. When a later run reaches the same conflict and the
  resolution's applicability context is identical, the system SHOULD replay the
  recorded resolution instead of asking again, and replaying an unchanged
  `human_confirmed` decision MUST produce the same reconciliation result. The
  system MUST NOT replay — and MUST NOT silently reuse — a resolution when
  output-affecting context relevant to that decision has changed; it raises a fresh
  HUMAN_REVIEW_REQUIRED item instead. The exact deterministic applicability key is
  a planning decision, but it MUST carry enough source and configuration identity
  to prevent applying a resolution to the wrong document or an incompatible
  extraction context.
- **FR-072** (blocking and the delivery gate): Any unresolved HUMAN_REVIEW_REQUIRED
  item MUST block **successful delivery** of the final Markdown for the run. A
  partially resolved document MUST NOT be produced or presented as a complete final
  artifact. Intermediate extraction / reconciliation artifacts and the human-review
  queue MAY still be written for diagnosis and review. Resolving every item is
  necessary but **not sufficient**: even when the queue is empty, downstream
  processing and delivery remain paused until the reviewer gives **explicit
  authorization to continue** (FR-077), and successful delivery additionally
  requires that every applicable human-review decision passes location-aware final
  verification in the delivered Markdown (FR-083 / FR-084). Once authorization is
  given, processing MUST resume from the appropriate reconciliation state
  **without** the user hand-editing the generated Markdown (FR-079).
- **FR-073** (relationship to `fix`): Human review and `fix` have distinct
  responsibilities. Human review resolves **uncertainty during extraction
  reconciliation**; `fix` addresses **defects that final fidelity validation
  (FR-065) identifies** on a document that has already passed reconciliation and
  semantic transformation. `fix` MUST NOT be the normal mechanism for resolving
  unresolved extraction candidates or an unresolved source reading order. If final
  fidelity validation finds that an earlier reconciliation decision was wrong — a
  wrong literal selection or a wrong accepted reading order — the issue MUST be
  routed back to the reconciliation / human-review decision layer, not silently
  patched as a Markdown-only `fix`; the corrected source decision then
  re-propagates through semantic transformation and final validation, preserving
  the provenance chain. `validate` itself only *flags* such an issue (with defect
  class `reconciliation_error`, FR-034a) and never modifies anything (FR-033); the
  routing happens when that issue is acted on — `fix` performs it (FR-045a), and a
  user reading a standalone `validate` report is directed to the human-review
  workflow rather than to a manual Markdown edit.
- **FR-074** (interaction model — interactive terminal): The system MUST provide an
  explicit, supported human-review workflow implementing the lifecycle above (raise
  → present evidence → human resolves against the source → persist as
  `human_confirmed` → authorize → replay / re-propagate → verify → unblock). This
  workflow MUST be an **interactive terminal mode** of the command-line application
  (the `review` operation — FR-066a). It MUST be keyboard-driven: the reviewer
  navigates selectable options with the **Up Arrow**, **Down Arrow**, and **Enter**
  keys, and MUST NOT be required to type numeric menu choices (`1`, `2`, `3`, …) as
  the normal interaction. It MUST NOT require a graphical desktop application, a
  browser-based UI, a local web server, a desktop-application framework, an
  OS-specific native application, or the generation of page images or cropped image
  previews for the review workflow. The specification does not select a
  terminal-interaction library; the library, the resolution-store and queue file
  formats, the review-item and lineage schemas, and the Markdown-span
  representation are planning / research / data-model / contract decisions.
- **FR-075** (review-item presentation): For each open HUMAN_REVIEW_REQUIRED item
  the workflow MUST present enough human-facing information for the reviewer to
  locate and verify the disputed content against the original PDF, including where
  available: the physical PDF page; the section or structural context; the table
  identifier; the row; the column; the surrounding source text immediately before
  and after the disputed segment; the candidate values (literal-content) or
  candidate orders (reading-order); and an extraction-source / provenance label for
  each candidate. Source geometry / bounding boxes MUST remain available internally
  where required for traceability, but the workflow is **not** required to display
  graphical geometry or generate image crops. For a literal-content conflict the
  selectable options conceptually are: candidate A; candidate B; any further
  candidates; and **"Enter another value…"** (FR-068).
- **FR-076** (reopen and change; append-only decision history): A previously
  resolved human-review item MUST remain reviewable, and the reviewer MUST be able
  to reopen it and record a different decision. A changed answer MUST NOT
  destructively erase the prior decision from the authoritative audit history. The
  system MUST preserve an append-only / auditable sequence sufficient to determine,
  per item: the previous decision; the replacement decision; which decision is
  currently applicable; and the provenance / context under which each decision was
  made. The resolution store's append-only nature (FR-057b) and the applicability /
  replay rules (FR-071) remain authoritative — a changed answer is a new record,
  the superseded record is retained.
- **FR-077** (review completion is not authorization to continue): Resolving the
  last unresolved human-review divergence MUST NOT automatically resume document
  processing. The workflow MUST distinguish at least three states: (1) unresolved
  review items remain; (2) all review items are resolved but downstream processing
  is not yet authorized; (3) downstream processing has been explicitly authorized.
  After the final unresolved item is answered the workflow MUST stop and present an
  interactive choice conceptually equivalent to **Review answers**, **Continue
  processing**, and **Save and exit** — where "Continue processing" constitutes the
  reviewer's **explicit authorization** to resume downstream document processing,
  "Review answers" opens the review-answer browser (FR-078), and "Save and exit"
  persists the complete review state and does not continue processing. When the
  workflow is opened again and all items are already resolved but processing has
  not been authorized or completed, it MUST recognise that state and present a
  choice conceptually equivalent to **Review answers**, **Continue processing**,
  and **Exit**. No automatic continuation is permitted merely because every review
  item is resolved.
- **FR-078** (review-answer browsing): The "Review answers" experience MUST also be
  interactive and keyboard-navigable — the reviewer moves through the previously
  resolved decisions with the Up / Down arrows and Enter. Each summary entry MUST
  carry enough identifying information to distinguish it — such as page, section /
  table location, the reviewed field or context, and the currently confirmed value
  or order. Selecting an entry MUST reopen that decision's review details, from
  which it may be changed (FR-076).
- **FR-079** (decisions flow through the pipeline; never patched into Markdown):
  Confirmed human-review resolutions MUST NOT be applied by directly editing or
  patching the final Markdown artifact. After explicit authorization to continue
  (FR-077), each **applicable** human-confirmed resolution MUST flow through the
  authoritative processing pipeline: human-confirmed resolution → extraction
  reconciliation → Canonical Extracted Document → deterministic semantic
  transformation → final fidelity validation → final Markdown rendering / delivery.
  A resolution that is no longer applicable because an output-affecting context
  changed MUST NOT be silently reused (FR-071). A `reconciliation_error` discovered
  later still routes back to reconciliation / human review (FR-045a / FR-073),
  never a silent Markdown edit.
- **FR-080** (Human Review Report — existence, identity, purpose): When a run
  contains one or more **applicable** human-review decisions and downstream
  processing has been authorized, the delivered result MUST include a
  human-readable **Human Review Report** in Markdown, in addition to the final
  Markdown document. Its conceptual name is `<output-base>_review_report.md`. The
  report is **not** the authoritative technical audit log — that remains the
  reconciliation log and the human-review resolution store (FR-057 / FR-057a /
  FR-057b) — and it is not one of the machine-readable stores those requirements
  govern. Its purpose is to let a human inspecting the delivered final document
  confirm that every requested human-review decision was actually reflected in it.
  The report MUST include a summary stating at least: the source document identity;
  the final Markdown output identity; the number of human-review decisions
  applicable to this delivery; the number resolved; the number successfully
  verified in the final Markdown; the number that failed final-application
  verification; and an overall **PASS / FAIL** review-verification status.
- **FR-081** (Human Review Report — per-item content): For every applicable
  human-review decision the report MUST provide enough human-readable evidence to
  answer: where in the original PDF the divergence was; what surrounding source
  context identifies it; what candidate values or orders were available; what the
  human confirmed; what corresponding content was actually rendered in the final
  Markdown; and whether that decision was successfully applied and verified. Where
  applicable it MUST include: PDF page; section; table; row; column;
  extraction-source labels; the source context before and after the disputed
  segment; the human-confirmed value or order; the corresponding final Markdown
  excerpt; and an explicit verification result (FR-084).
- **FR-082** (source-context markers vs literal final-Markdown evidence): The
  report MAY add **report-only** markers to the **source-context** representation
  to indicate the disputed location — for example `Apartamento 42 | << R$ 1.599,80
  >>`. Such markers are presentation aids only, are not part of any source literal,
  and MUST NOT be confused with delivered content. In contrast, the **Final
  Markdown evidence** shown for each item MUST be copied from the **actual
  delivered Markdown artifact** — specifically from the text obtained by decoding
  that artifact's exact bytes as UTF-8, which is also the text the location-aware
  verification of FR-083 indexes into — and MUST reproduce the relevant excerpt
  **literally as delivered** — preserving exact characters, exact punctuation,
  decimal
  separators, thousand separators, the spaces before / inside / after the reviewed
  value, Unicode characters, Markdown syntax, and the line structure relevant to
  the excerpt. The system MUST NOT alter the Final Markdown evidence for
  readability; specifically it MUST NOT add `<< >>` highlighting, trim the excerpt,
  apply an equivalent of `.strip()`, collapse whitespace, normalize Unicode,
  normalize punctuation, rewrite decimal / thousand separators, insert or remove
  spaces, or canonicalize equivalent-looking characters. If the delivered Markdown
  literally contains `Apartamento 42 | R$ 1.599,80`, the report MUST show exactly
  `Apartamento 42 | R$ 1.599,80` and MUST NOT transform it into `Apartamento 42 |
  << R$ 1.599,80 >>`. The report MAY add headings or explanatory text **around**
  the excerpt, but the captured excerpt itself MUST remain literal.
- **FR-083** (location-aware verification): A human-review decision MUST NOT be
  considered successfully applied merely because the human-confirmed string can be
  found **somewhere** in the final Markdown — this matters especially where an
  identical value occurs more than once. Verification MUST be tied to the reviewed
  source segment and its authoritative processing lineage to the corresponding
  rendered output location — conceptually: review item → source-backed segment →
  human-confirmed resolution → reconciled / Canonical-Extracted-Document
  representation → semantic / render lineage → the corresponding final-Markdown
  span. Verification MUST distinguish an **unauthorized literal alteration** from a
  **transformation explicitly permitted by this specification**: it MUST NOT
  silently treat punctuation, spacing, Unicode, numeric-formatting, or other
  literal differences as equivalent because they look similar, and any allowed
  transformation that affects how the reviewed content appears in the final
  Markdown MUST remain traceable and valid under the existing transformation rules
  (FR-006–FR-022 / FR-064). The report MUST show what the delivered document
  **actually** contains, even when an allowed structural transformation has occurred
  around the reviewed content. The detailed lineage and Markdown-span data
  structures belong to future data-model / contract work; this location-aware
  verification **behaviour** is a product requirement.
- **FR-084** (verification outcome and delivery gating): Each applicable
  human-review decision MUST receive an explicit human-readable final-verification
  status with semantics equivalent to **APPLIED AND VERIFIED** or **NOT APPLIED /
  VERIFICATION FAILED** (exact wording may be refined during planning / contracts).
  A run MUST NOT be considered **successfully delivered** if any applicable
  human-review decision cannot be traced to and verified at its corresponding
  location in the final Markdown. When verification fails: any Markdown produced
  for that run MUST exist **only** as a run-scoped, non-deliverable intermediate
  output and MUST NOT be written to — or left at — the name reserved for the
  successfully delivered Markdown (`<output-base>.md`); successful delivery is
  blocked; the failed human-review item is identified; the human-confirmed expected
  decision is recorded in the Human Review Report; the actual corresponding
  final-Markdown evidence is shown when available; and the failure enters the
  existing final fidelity validation / audit workflow rather than being ignored,
  **classified by the stage that introduced it** (FR-034a / FR-045a / FR-073):
  `reconciliation_error` when the human-confirmed decision was not carried into the
  reconciled / Canonical-Extracted-Document representation (routed back to the
  human-review layer), or `disallowed_transformation` when that representation is
  correct but a later deterministic transformation or rendering step altered or
  dropped the reviewed content (routed to a code fix and re-verification, or to
  `fix` followed by mandatory re-verification) — the verification step MUST NOT
  collapse both causes into a single class. Publishing the successfully delivered
  Markdown to `<output-base>.md` happens **only after** every delivery gate passes
  (all items resolved, explicit authorization for the current run, built-in
  fidelity self-check passed, and every applicable human-review decision
  **APPLIED AND VERIFIED**). If a prior run already delivered `<output-base>.md`
  and a later run changes a human-review decision, the later run MUST NOT overwrite
  that delivered artifact: it is treated as an FR-054 name collision (the existing
  file is preserved and the user is directed to a fresh output location).
  Combined with FR-072 and FR-077, the delivery gate progresses conceptually as:
  *unresolved review* →
  blocked; *all resolved, not authorized* → awaiting explicit user authorization;
  *authorized, processing underway* → processing; *rendered but review verification
  failed* → delivery blocked; *every applicable review decision verified* →
  eligible for successful delivery. These behavioural states need not use these
  exact internal names if the system expresses run state differently.

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

*Artifact removal is a stage-3 semantic transformation (FR-064); the Canonical
Extracted Document still contains these elements with their provenance.*

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

*FR-013, FR-014, and FR-016 are stage-3 semantic transformations (FR-064),
performed on the Canonical Extracted Document — never during extraction or
reconciliation. FR-015 governs reading order, which is reconciled evidence
(FR-061d), not a facet of literal-text correctness.*

- **FR-012**: Markdown output MUST be valid Unicode encoded as UTF-8.
- **FR-013**: The system MUST remove visual line wrapping so that logical
  paragraphs are contiguous.
- **FR-014**: The system MUST repair hyphenation introduced by line breaks by
  rejoining split words, without removing hyphens that are part of the word. The
  repair is **conservative and deterministic (research §27, authoritative)**: the
  trailing hyphen is kept by default and removed only on **positive
  document-internal evidence** — the un-hyphenated joined token occurs elsewhere in
  the same Canonical Extracted Document as a complete token — together with the
  §27 structural guards. No external dictionary, no language model. When the
  evidence is insufficient or ambiguous the hyphen is retained (a later validation
  check may flag it); Stage 3 never guesses. Every removal is recorded as a
  `dehyphenate` transform in the RenderMap.
- **FR-015**: Reading order MUST be treated as **independent extraction evidence**,
  not as part of literal-text correctness. Each extraction technique produces its
  own **candidate reading order** over its source-backed segments; two techniques
  MAY yield identical literal text but different candidate orders, and no single
  extractor's order is adopted implicitly — not even that of the layout-aware
  structural extraction path. The **accepted
  reading order** is fixed by reading-order reconciliation (FR-061d) and recorded
  in the Canonical Extracted Document; once fixed, it MUST be preserved unchanged
  through semantic transformation and into the final Markdown (semantic
  transformation MUST NOT silently re-order source segments — FR-064).
- **FR-016**: The system MUST preserve semantic paragraph, heading, list,
  article, clause, and table boundaries.

#### Semantic structure

*All of FR-017–FR-022 are stage-3 semantic transformations (FR-064): heading
inference, list reconstruction, and multi-page table stitching operate on the
Canonical Extracted Document — which already carries the **accepted reading order**
(FR-061d) and each value's originating page and contributing extraction source(s)
(FR-063/FR-066). This stage MAY use the structural hints carried in that document
(from any extraction path) as advisory input, recording which it applied; the hints are
never authoritative on their own (FR-060b/FR-064). Any re-ordering a structural
operation needs is a distinct recorded decision, kept separate from the source
reading-order decision.*

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

#### Scanned pages / OCR (adaptive, region-aware)

*OCR is extraction path C (FR-060): a stage-1 technique that recovers text
physically present on pages or regions lacking reliable native text. Its output is
one independent extraction candidate; native-vs-OCR differences are settled in
reconciliation (stage 2), not by OCR overriding native text directly. OCR markers,
per-region provenance, and the OCR records survive reconciliation into the
Canonical Extracted Document, the semantic document, and the final Markdown.*

- **FR-024**: The system MUST support mixed / hybrid PDFs in which pages differ:
  some have a reliable native text layer, some are image-only, some contain both
  native text and image-only regions, and some have a native text layer that is
  incomplete, corrupted, or materially unreliable. For any selected page or page
  region where native text is absent or insufficient, the system MUST apply local
  OCR to that page or region and include the resulting text. Native text MUST be
  preferred wherever it is reliable.
- **FR-024a**: OCR MUST be applied **adaptively and region-aware** — the decision
  to OCR is made per page and, where a page subdivides, per region — and MUST NOT
  be document-wide by default. A single region requiring OCR MUST NOT cause OCR to
  replace reliable native text elsewhere on that page or in the document (see
  FR-026a).
- **FR-024b**: The system MUST conceptually classify each page — and each region
  where it subdivides a page — into at least: `native_text_sufficient`,
  `ocr_required`, or `hybrid_native_and_ocr`. This classification MUST be recorded.
- **FR-025**: OCR-derived text MUST be identifiable as OCR-derived, and OCR use
  MUST be recorded (per page, and per region where OCR was applied region-wise).
- **FR-025a**: Every extracted region MUST retain provenance sufficient to
  identify: the source PDF page; the source region / bounding box where the source
  provides one; the origin kind (`native_text` or `ocr`); the specific extraction
  technique (FR-060a); and, where OCR was used, the OCR language(s) and
  configuration for that region.
- **FR-025b**: The independent extraction candidates (FR-060) MUST each preserve
  their own native-text and/or OCR-derived evidence with provenance; the Canonical
  Extracted Document (FR-063) MUST record, per value, which candidate(s) it came
  from. Native and OCR evidence for the same region are never merged into a single
  unattributed value before reconciliation.
- **FR-026**: A page MAY carry native text and OCR-derived content simultaneously.
  Where reconciliation selects native text for some regions of a page and OCR for
  others, it MUST mark the OCR-derived portions and MUST NOT discard the page's
  reliable native text.
- **FR-026a**: Reconciliation MUST NOT silently replace reliable native text for a
  whole page merely because one region of that page required OCR.
- **FR-026b**: The OCR path (C) MAY be run for a region even where a native text
  layer exists, so that reconciliation has a second independent candidate for that
  region, subject to the OCR-triggering policy. Any such OCR evidence is recorded
  with its provenance and enters reconciliation as a candidate — it never
  overwrites native text outside the reconciliation decision.
- **FR-026c**: OCR-derived text is subject to the same non-rewriting rule as all
  extracted content (FR-029, FR-044, Constitution I & IV): no LLM may generate,
  improve, paraphrase, or substitute OCR text. OCR output is the OCR engine's
  verbatim result; stage-3 normalization applies to it exactly as it does to
  native text, and no more.
- **FR-027**: OCR regions whose minimum per-word (or per-token) confidence is below
  the configurable low-confidence threshold MUST be surfaced during validation
  rather than accepted silently. The confidence MUST be expressed on a normalized
  0–100 scale regardless of which OCR engine produced it; the threshold MUST
  default to 70 and MUST be configurable per run. (Low OCR confidence is distinct
  from an unreliable *native* text layer under FR-024 — the two are assessed
  separately.)
- **FR-027a**: The system MUST auto-detect the language(s) of a page or region
  before running OCR on it and MUST accept an optional user override to force one
  or more OCR languages for the run. The detected or overridden language(s) MUST be
  recorded alongside the OCR provenance for that page/region (FR-025a).
- **FR-027b**: Because `validate` and `fix` re-derive text from the source PDF,
  they MUST accept the same OCR options as `extract` — the optional OCR language
  override (FR-027a) and the OCR confidence threshold (FR-027, default 70) — with
  identical defaults and semantics.

#### Operation separation

- **FR-028**: The system MUST expose `extract`, `validate`, `fix`, and `export` as
  explicit, independently invocable operations. Internally, `extract` runs the
  pipeline of FR-059 (stages 1–3 plus the built-in final fidelity self-check).
- **FR-029**: No extraction path, the reconciliation step, or semantic
  transformation may use an LLM to produce or alter source text. Verbatim text
  always originates from a PDF text layer or local OCR; the only LLM roles are
  candidate-selection during reconciliation (FR-061a) and issue detection during
  validation (FR-037) — see FR-066b.
- **FR-030**: `extract` MUST produce the "original Markdown" (the stage-5 render of
  the semantic document, itself built from the Canonical Extracted Document), which
  is treated as immutable by later operations. The extraction candidates and the
  Canonical Extracted Document are internal intermediates; if persisted they are
  never mutated in place (FR-063).
- **FR-031**: `extract` and `export` MUST be able to run without a local LLM. With
  no LLM, `extract`'s reconciliation is deterministic-only and unresolved material
  disagreements become HUMAN_REVIEW_REQUIRED items (FR-066b); its built-in final
  fidelity self-check runs its deterministic checks only.

#### Validation

*The `validate` operation is the full final fidelity validation of FR-059 stage 4
(FR-065). The lighter self-check inside `extract` is not this operation.*

- **FR-032**: `validate` MUST compare a generated Markdown against its source PDF
  and, where available, the independent extraction evidence, and produce a
  validation report as a separate persisted artifact. `validate` MUST classify
  each issue by defect class (FR-034a) — an extraction error, a reconciliation
  error, or a disallowed transformation — per FR-065.
- **FR-033**: `validate` MUST NOT modify the Markdown under any circumstance.
- **FR-034**: Every issue in the report MUST include severity, source PDF page,
  Markdown line, Markdown column, issue type, and a clear problem description.
- **FR-034a**: Every issue MUST also carry a defect class — one of
  `extraction_error` (a stage-1 extraction defect), `reconciliation_error` (a
  stage-2 defect: wrong literal candidate, wrong accepted reading order, or a
  missed conflict), or `disallowed_transformation` (a stage-3 normalization or
  silent re-ordering defect) — so a consumer can tell which stage introduced the
  fault (FR-065). This is in addition to the FR-034 fields.
- **FR-035**: Where applicable, an issue MUST also include the source location,
  the expected value or structure, the found value or structure, and a suggested
  corrective action.
- **FR-036**: `validate` MUST include deterministic checks.
- **FR-036a**: `validate` MUST compute the fraction of the selected pages'
  extractable source text that can be matched in the generated Markdown. This
  deterministic check MUST run before the local-LLM probe. When that fraction is
  below the gross-divergence threshold (default 50% — a 0-to-1 fraction,
  configurable per run), the report MUST set a `gross_divergence` indicator, lead
  with a single summary issue stating the observed match rate, suppress exhaustive
  line-level issues while still listing structural issues, and skip both the
  local-LLM probe and the semantic pass. Above the threshold, `validate` proceeds
  to the LLM probe and produces the full issue list as normal.
- **FR-037**: `validate` MUST use at most one local LLM for semantic validation,
  and that LLM MUST NOT alter the document.
- **FR-038**: `validate` MUST require a local LLM and MUST stop with a clear
  message when none is available, rather than presenting a deterministic-only
  report as complete. Exception: when the deterministic pass detects gross
  divergence (FR-036a), `validate` skips the LLM probe and the semantic pass and
  produces the gross-divergence report without requiring a local LLM — that report
  is a complete answer for its purpose, not a truncated validation.
- **FR-038a**: If the local LLM is reachable when probed but then fails during the
  semantic pass (timeout, transport or HTTP error, or a response that cannot be
  parsed), `validate` MUST retry a bounded number of times (default 2) and, if the
  failure persists, MUST stop with the same clear message and exit status as an
  unavailable LLM, leaving no validation report that would be treated as complete.

#### Fix

*`fix` operates only on post-transformation defects flagged by final fidelity
validation. It is not the mechanism for unresolved extraction candidates or an
unresolved source reading order — those go through the human-review workflow
(FR-067–FR-084). See FR-073 and FR-045a.*

- **FR-039**: `fix` MUST take the original Markdown, the validation report, and
  source context as inputs.
- **FR-040**: `fix` MUST change only the regions the validation report explicitly
  identified as non-conformant.
- **FR-041**: When `fix` applies at least one correction it MUST write a new
  corrected Markdown file and MUST NOT overwrite the original. If every flagged
  issue is routed back to the human-review layer (FR-045a) and no correction is
  applied, `fix` produces no corrected Markdown and reports that outcome.
- **FR-042**: `fix` MUST log every applied correction with enough detail to trace
  it to the report issue it resolves.
- **FR-043**: When `fix` produced a corrected Markdown, it MUST re-run validation
  against that corrected output and produce its report.
- **FR-044**: `fix` MUST NOT paraphrase, summarize, rewrite, or improve wording;
  corrections MUST restore source content only.
- **FR-045**: `fix` MUST report any flagged region it cannot resolve (for example,
  a region that no longer exists in the Markdown) rather than applying a change to
  the wrong location.
- **FR-045a**: When a validation issue's defect class is `reconciliation_error`
  (a wrong literal selection or a wrong accepted reading order — FR-034a), `fix`
  MUST NOT patch it as a Markdown-only edit. It MUST route the issue back to the
  reconciliation / human-review decision layer (raising the appropriate
  HUMAN_REVIEW_REQUIRED item) so the corrected source decision re-propagates
  through semantic transformation and final validation (FR-073).
- **FR-046**: `fix` MUST require a local LLM and MUST stop with a clear message
  when none is available.
- **FR-046a**: A local LLM that fails mid-run during `fix` (as described in
  FR-038a) MUST be handled the same way: bounded retry (default 2), then stop with
  the unavailable-LLM message and exit status, leaving no corrected Markdown or
  correction log presented as complete.

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
  `fix` automatically. If its `extract` stage raises HUMAN_REVIEW_REQUIRED items,
  `convert` MUST stop at the human-review queue (before `validate`) and deliver no
  final Markdown or traceability record for that run; it resumes only after the
  items are resolved **and** downstream processing is explicitly authorized
  through the `review` workflow (FR-072 / FR-077).
- **FR-052**: The `convert` standard workflow MUST emit a traceability record that
  links the source PDF, selected physical page ranges, generated Markdown, removal
  log, reconciliation log, any human-review queue, the Human Review Report when one
  is produced (FR-080), validation report, and DOCX output when requested.
  Standalone `extract`, `validate`, `fix`, and `export` operations MUST NOT emit a
  traceability record.
- **FR-053**: Generated files MUST use deterministic names derived from the
  original filename and the selected page ranges, so identical inputs yield
  identical names.
- **FR-053a** (deterministic core): The **deterministic core** of every run MUST be
  byte-reproducible for **identical effective inputs**. Effective inputs are:
  source identity (hash); normalized page selection; enabled extraction paths; the
  selected OCR engine + model + config; the OCR language override; the OCR
  confidence threshold; the reconciliation confidence threshold; the tool version;
  and the set of applicable `human_confirmed` resolutions replayed for the run
  (FR-071). For identical effective inputs the **original Markdown**, the **DOCX** (under the normalized
  metadata / ZIP rules), and the **deterministic records** — the removal log, the
  reconciliation log's `deterministic_agreement` and `human_confirmed` decisions,
  the traceability record, and every `check_origin: "deterministic"` portion of a
  validation report — MUST be byte-identical across runs. Records MUST NOT embed
  wall-clock timestamps or randomly generated identifiers in their persisted body;
  the `run_id` MUST be a pure function of the effective inputs above (and MUST NOT
  introduce wall-clock time, randomness, or a random identifier to work around
  nondeterminism). Semantic transformation in v1 is deterministic and exposes **no
  user-configurable or otherwise output-affecting settings**, so it contributes
  nothing to the effective inputs or the `run_id`. If a future version introduces
  any output-affecting semantic-transformation configuration, that setting MUST
  then be added to the effective inputs above and folded into run identity. The
  precise canonical form of this effective-input tuple and of `run_id` is
  maintained authoritatively in the technical design (research §14); this list and
  every other artifact reference it rather than restating it. The Human Review
  Report and its machine model (FR-080–FR-084) are part of the deterministic core;
  the post-review processing authorization (FR-077) is a recorded human action,
  never feeds `run_id`, and is **not** part of the run-twice deterministic-core
  artifact set.
- **FR-053b** (LLM-assisted audit results): The validation report's
  `check_origin: "semantic"` issues — and any future LLM-produced audit content —
  are reproducible **only to the extent the local LLM backend provides the
  deterministic controls the reproducibility contract requires**: the configured
  deterministic decoding parameters (`temperature: 0`) **plus** a supported and
  reliable `seed` (or an equivalent deterministic mechanism).
  - **Backend is deterministic**: identical effective inputs MUST produce identical
    persisted LLM-assisted results, and the run / audit metadata MUST record the
    reproducibility level as `deterministic`.
  - **Backend is not deterministic**: the system MUST NOT claim byte-level
    reproducibility for **newly generated** LLM-assisted results; the run / audit
    metadata MUST record the reproducibility level as `best_effort` and MUST state
    that the backend cannot guarantee deterministic regeneration; and where a valid
    LLM-assisted result for the identical applicability context has already been
    persisted, the system SHOULD **replay** that persisted result rather than
    regenerate it (and MUST NOT raise a name-collision error for a re-run whose
    only difference would be a regeneration of an already-persisted `best_effort`
    semantic section — it replays instead).
  - In every case the deterministic guards (FR-061b), the reconciliation
    candidate-selection invariants (FR-061a), the prohibition on the LLM modifying
    source content (FR-029 / FR-037), and the deterministic core (FR-053a) remain
    mandatory and unaffected.
  This distinguishes: (1) reproducibility of deterministic artifacts — always;
  (2) reproducibility of *newly generated* LLM-assisted audit decisions — only
  under backend determinism; (3) deterministic **replay** of a *previously
  persisted* LLM-assisted decision — always preferred over regeneration when the
  backend is `best_effort`.
- **FR-054**: The system MUST NOT overwrite the original source or any
  intermediate artifact by default. A name collision whose existing file has
  byte-identical content is a satisfied no-op; a collision whose existing file
  differs MUST preserve the existing file and be surfaced to the user.
- **FR-055**: The entire default processing workflow MUST run locally on the
  user's machine without requiring paid APIs or cloud services.
- **FR-056**: Any optional network- or cloud-assisted behavior MUST be opt-in and
  disclosed before use.
- **FR-057**: The validation report, removal log, correction log, traceability
  record, reconciliation log, human-review queue, human-review resolution store,
  the persisted run-context, the append-only human-review authorization event log,
  and the human-review verification record MUST each be written as a structured
  machine-readable file that is the authoritative source of truth (consumed
  programmatically by `fix`, by human-review resolution and replay, and by tests),
  and the system MUST also generate a human-readable Markdown rendering of each
  (for the verification record, that rendering is the Human Review Report). The two
  MUST always represent the same content. The **Human Review Report** (FR-080) is a
  human-readable Markdown delivery artifact rendered from the verification record —
  a verification aid, not itself one of the authoritative machine-readable stores —
  and does not replace them.
- **FR-057a**: The reconciliation log MUST record, per resolved conflict, whether
  it was a **literal-content** or a **reading-order** conflict, the competing
  candidates (values, or segment orderings) with their sources, the resolution
  method (`deterministic_agreement`, `llm_selected`, or `human_confirmed`), the
  selected value or ordering, and — for `llm_selected` — the confidence; a
  `human_confirmed` entry also references the resolution store record it came from
  (FR-070) and whether that record was freshly created this run or replayed
  (FR-071). It is the audit trail for how the Canonical Extracted Document (content
  and order) was assembled.
- **FR-057b**: The **human-review resolution store** is the durable, cross-run
  record of every `human_confirmed` resolution (FR-070), keyed by its deterministic
  applicability key (FR-071). It is an append-only audit trail: a superseded
  resolution is retained, not deleted, and a new resolution is a new record. It is
  never modified by any automatic stage or by an LLM.
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
- **Source-backed segment**: a contiguous run of extracted text with its own
  geometry / bounding box and provenance — the unit that reading-order
  reconciliation orders (FR-060a/FR-061d). Its content comes from literal-content
  reconciliation; its position comes from reading-order reconciliation.
- **Extraction candidate**: one extraction path's independent output — the
  layout-aware structural representation, the geometry-aware PDF text
  representation, or an OCR
  representation — as a set of source-backed segments. Per segment: verbatim text,
  geometry, that candidate's **reading-order position**, provenance (technique,
  page, bbox, OCR language/config), and any **structural hints**. Never derived
  from another path's output (FR-060).
- **Candidate reading order**: one extractor's inferred ordering of its segments.
  Evidence for reading-order reconciliation (FR-061d); never adopted implicitly as
  canonical, not even that of the layout-aware structural extraction path.
- **Structural hint**: a heading / list / table interpretation produced by an
  extractor. Advisory evidence only — attributed to its source, carried through
  reconciliation unaltered, and accepted / rejected / applied solely by semantic
  transformation, which records the decision (FR-060b/FR-061c/FR-064). (Reading
  order is *not* a structural hint — it is reconciled before semantic
  transformation.)
- **Canonical Extracted Document**: the reconciliation output (stage 2). Holds the
  reconciled *literal* content of the source-backed segments, the **accepted
  reading order** over them, source provenance, extraction evidence, and the
  extractors' structural hints — but no hint has been accepted or applied and no
  semantic normalization has occurred; it is a pre-semantic-transformation state.
  Per value and for the accepted order it records the originating PDF page/region,
  the contributing extraction source(s), and whether the decision was
  deterministic, LLM-selected, or human-confirmed (FR-063). Input to semantic
  transformation. An internal intermediate, never mutated in place.
- **Reconciliation decision / reconciliation log**: per resolved conflict —
  literal-content *or* reading-order — the competing candidates and their sources,
  the resolution method (`deterministic_agreement` / `llm_selected` /
  `human_confirmed`), the selected value or ordering, and the LLM confidence when
  applicable (FR-057a).
- **HUMAN_REVIEW_REQUIRED item / human-review queue**: an explicit reconciliation
  state (FR-067) — a conflict whose automatic confidence is below the threshold.
  Item lifecycle: `open` → `resolved`, and a `resolved` item remains reopenable and
  re-decidable (FR-076). A literal-content item carries the FR-062a fields
  (page/line/column, bbox, each source's candidate value, reason, confidence); a
  reading-order item carries the FR-062d fields (page, affected regions/bboxes,
  candidate segment identifiers, candidate reading orders, contributing sources,
  reason, confidence). It is presented to the reviewer with the FR-075 locating
  context (section, table/row/column, source context before/after, per-candidate
  provenance label). The workflow also tracks a **run-level** state (FR-077):
  *items unresolved* / *all resolved but processing not authorized* / *processing
  authorized*. While any item is `open` the run's **successful delivery** is blocked
  (FR-072); an empty queue alone does not unblock it.
- **Human-review resolution**: the persisted outcome of resolving one review item
  (FR-070) — source hash, page/region, conflict type, the candidate evidence
  presented, the selected candidate or human-entered literal value, the accepted
  segment ordering (reading-order), `decision_method = human_confirmed`, and a link
  to the originating review item. For a literal-content conflict where none of the
  candidates was correct, it records a human-entered value captured **exactly as
  typed** and flagged as manually verified against the original PDF (FR-068). It is
  persisted immediately, before the workflow advances (FR-070). Lives in the
  **human-review resolution store** (FR-057b): durable across runs, append-only,
  keyed by a deterministic applicability key (FR-071), never touched by an automatic
  stage or an LLM. A changed answer (FR-076) is a **new record**; the superseded
  record is retained, and the store makes previous / replacement / currently-
  applicable decisions and each decision's context recoverable.
- **Human Review Report**: a human-readable Markdown delivery artifact
  (`<output-base>_review_report.md`, FR-080–FR-084) delivered alongside the final
  Markdown when a run has one or more applicable human-review decisions and
  downstream processing was authorized. A verification aid, **not** an authoritative
  audit store (that is the reconciliation log / resolution store, FR-057). Carries a
  summary (source and final-Markdown identity; counts of decisions applicable,
  resolved, verified, and failed; overall PASS/FAIL) and, per applicable decision,
  the source location and context, the candidates, the human-confirmed value/order,
  the corresponding final-Markdown excerpt **copied literally from the delivered
  artifact**, and an explicit **APPLIED AND VERIFIED** / **NOT APPLIED —
  VERIFICATION FAILED** status. Report-only `<< >>`-style markers MAY appear on the
  *source-context* representation but never on the literal final-Markdown evidence.
- **Region OCR record**: per page (and per region where OCR is applied region-wise)
  — whether OCR ran, the detected or overridden language(s), the effective
  confidence threshold, and low-confidence region count.
- **Semantic document**: the stage-3 output; the normalized structure (reflowed
  paragraphs, inferred headings/hierarchy, reconstructed lists and multi-page
  tables, artifacts removed) built from the Canonical Extracted Document. The final
  Markdown is rendered from this (stage 5).
- **Original Markdown**: the immutable output of `extract` — the stage-5 render of
  the semantic document; the canonical representation of the converted document.
  Produced from the validated semantic document, never directly from any single
  extraction path.
- **Removal log**: the record of every non-semantic element removed during
  stage-3 semantic transformation, with source page references.
- **Validation report**: the output of `validate`; a list of validation issues;
  never modifies the Markdown. Records the **LLM reproducibility level**
  (`deterministic` | `best_effort`, FR-053b) alongside the decode parameters used.
- **Validation issue**: one entry in a report — severity, source PDF page,
  Markdown line, Markdown column, issue type, description, and optionally source
  location, expected value/structure, found value/structure, suggested action.
- **Correction log**: the output of `fix` describing each applied correction and
  the issue it resolves.
- **Corrected Markdown**: a new file produced by `fix`; the original is retained
  unchanged.
- **DOCX export**: an optional Word-format rendering of a Markdown file.
- **Traceability record**: linkage emitted by a `convert` run between the source
  PDF, page ranges, and all artifacts generated by that workflow; its persisted
  body is reproducible (no wall-clock timestamp or random identifier).

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: On the acceptance test corpus, every unit of extractable source text
  in the selected pages maps to a verifiable source page location, with zero
  silent omissions.
- **SC-002**: At least 95% of headings present in the source appear at the correct
  hierarchical level in the Markdown across the test corpus.
- **SC-003**: Every multi-page table in the test corpus is reconstructed with zero
  lost rows, zero lost columns, and zero duplicated header rows.
- **SC-004**: 100% of elements removed during stage-3 semantic transformation are
  recorded in the removal log.
- **SC-005**: 100% of validation issues carry all six mandatory FR-034 fields
  populated, plus the FR-034a defect class.
- **SC-006**: For any `fix` run, a diff between original and corrected Markdown
  shows changes only within regions named in the validation report — zero edits
  elsewhere.
- **SC-007**: After any `fix` run, the original Markdown file is byte-identical to
  its pre-run state, in 100% of runs.
- **SC-008**: A default `convert` run completes with zero outbound network
  connections.
- **SC-009**: For identical effective inputs (FR-053a), running `convert` (or
  `extract` / `export`) twice:
  (a) produces byte-identical **deterministic artifacts** — original Markdown,
      DOCX, and all deterministic records — with identical filenames, and the
      second run completes as a satisfied no-op with no collision error — 100% of
      runs;
  (b) when the local LLM backend provides the required deterministic controls
      (FR-053b), the validation report's semantic section is also byte-identical
      across the two runs and the report records `llm.reproducibility:
      "deterministic"` — 100% of runs;
  (c) when it does not, the report records `llm.reproducibility: "best_effort"`,
      (a) still holds, and the second run **replays** the persisted semantic
      section rather than regenerating it or raising a collision — 100% of runs.
- **SC-010**: A user can trace any artifact generated by a `convert` run back to
  its source PDF and exact physical page ranges using that run's traceability
  record, with no ambiguity.
- **SC-011**: 100% of Markdown headings map to the corresponding Word heading style
  on DOCX export.
- **SC-012**: When a local LLM is required but unavailable — or reachable at probe
  time but failing on every attempt during the run — `validate`, `fix`, and
  `convert` stop with an explanatory message in 100% of cases and never present a
  partial result as complete.
- **SC-013**: Pages and regions with no reliable native text are converted via OCR
  and marked as OCR-derived, with per-region provenance, in 100% of cases in the
  test corpus.
- **SC-014**: On a hybrid page (reliable native text in some regions, OCR needed
  in others), the reliable native text is retained verbatim — OCR never replaces it
  — and the page is classified `hybrid_native_and_ocr`, in 100% of such cases in
  the test corpus.
- **SC-015**: Every value in the Canonical Extracted Document carries an origin
  kind (`native_text` or `ocr`), the contributing extraction source(s), and — for
  OCR values — the OCR language/config; 100% of values.
- **SC-016**: When any operation fails mid-run (including resource exhaustion on a
  very large document), no partially written output is left in a state that a
  consumer or the traceability record would treat as a complete artifact — 100% of
  failure cases.
- **SC-017**: When a Markdown that does not correspond to the source PDF is
  validated (below the gross-divergence threshold), the report sets
  `gross_divergence` and emits the single summary issue plus structural issues
  only — never an exhaustive line-level issue list — and completes without a local
  LLM, in 100% of such cases.
- **SC-018**: In 100% of `extract` runs, semantic transformation does not begin
  until extraction reconciliation has produced a Canonical Extracted Document for
  the requested pages; any conflict below the confidence threshold becomes a
  HUMAN_REVIEW_REQUIRED item and is never silently guessed.
- **SC-019**: Every issue in a `validate` report carries a defect class
  (`extraction_error`, `reconciliation_error`, or `disallowed_transformation`);
  across a seeded test set mixing genuine extraction faults, wrong reconciliation
  choices, and legitimate normalizations, the classes are assigned correctly in
  ≥ 95% of cases and legitimate normalizations are never reported as errors without
  the ambiguity being flagged.
- **SC-020**: In 100% of automatic reconciliation decisions, the outcome already
  exists in the evidence — a selected literal value byte-identical to a supplied
  candidate value, or a selected reading order equal to a candidate order or a
  deterministic geometry-supported order; the programmatic guard rejects 100% of
  LLM responses that are not.
- **SC-021**: Every reconciliation conflict — literal-content or reading-order —
  resolved at confidence below the configured threshold (or with no LLM available)
  produces a HUMAN_REVIEW_REQUIRED item carrying all applicable fields (FR-062a for
  literal-content, FR-062d for reading-order) — 100% of such conflicts, zero silent
  guesses.
- **SC-022**: Reading order is reconciled as its own decision: for a fixture where
  the extraction candidates agree on literal text but disagree on order, the
  outcome is either a deterministic/LLM-selected existing candidate order or a
  reading-order HUMAN_REVIEW_REQUIRED item — never a re-written or re-segmented
  text — in 100% of such cases, and the reconciliation log records it as a
  reading-order decision distinct from any literal-content decision.
- **SC-023**: The accepted reading order in the Canonical Extracted Document is
  preserved unchanged into the final Markdown; any re-ordering introduced by a
  stage-3 structural operation is recorded separately and is distinguishable from
  the source-ordering decision — 100% of runs.
- **SC-024**: No extraction path consumes another extraction path's output —
  verified by construction and by a test that a fault injected into one path does
  not alter the others' candidates.
- **SC-025**: Final fidelity validation compares against the original PDF, the
  independent extraction evidence, and the reconciliation provenance — each where
  available — not merely the prior stage: a seeded reconciliation error and a
  seeded transformation error are each detected in 100% of runs on the test corpus.
- **SC-026**: The Canonical Extracted Document applies zero structural hints — for
  a fixture where the layout-aware structural extraction path infers a heading that
  the other extraction paths do not, the
  Canonical Extracted Document still holds that text as literal content plus the
  hint as attributed evidence, and only the semantic transformation stage's
  recorded decision determines whether it becomes a heading — 100% of such cases.
- **SC-027**: A run with at least one unresolved HUMAN_REVIEW_REQUIRED item is never
  presented as a successfully delivered final Markdown — 100% of such runs; the
  human-review queue and intermediate artifacts MAY still be written.
- **SC-028**: Once every required review item for a run is resolved **and** the
  reviewer explicitly authorizes downstream processing (chooses "Continue
  processing"), processing resumes and completes to a final Markdown that
  incorporates each resolution, with no hand-editing of generated Markdown — 100% of
  such cases. Answering the last review item alone never auto-resumes processing —
  100% of cases the workflow instead presents the authorization choice (FR-077).
- **SC-029**: A human-entered literal value (used only when no candidate was
  correct) is stored exactly as typed (no normalization / re-spacing / separator
  rewrite), recorded as `human_confirmed` with manually-verified provenance, and
  appears only via the human-review workflow — an automatic run of the same
  document without that resolution still raises the review item rather than
  inventing the value — 100% of such cases.
- **SC-030**: Replaying an unchanged applicable `human_confirmed` resolution yields
  the identical reconciliation result and identical final Markdown; when the
  resolution's output-affecting context has changed, it is not replayed and a fresh
  HUMAN_REVIEW_REQUIRED item is raised — 100% of both cases in the test set.
- **SC-031**: When final fidelity validation flags a `reconciliation_error`, `fix`
  routes it back to the human-review layer and never patches it as a Markdown-only
  edit — 100% of such cases.
- **SC-032**: Every confirmed human-review decision is persisted before the
  workflow advances to the next item; after an interruption (Ctrl+C, voluntary
  exit, terminal closure, process kill, machine restart) no already-resolved
  applicable item is asked again and the workflow resumes at the next unresolved
  applicable item — 100% of interruption cases in the test set (FR-070).
- **SC-033**: When a reviewer reopens an earlier decision and records a different
  answer, the prior decision remains recoverable from the audit history (previous,
  replacement, and currently-applicable decision, plus each decision's context) and
  the new decision re-propagates through reconciliation → CED → semantic
  transformation → validation → render — never by editing the delivered Markdown —
  100% of such cases (FR-076 / FR-079).
- **SC-034**: When a run has at least one applicable human-review decision and
  downstream processing is authorized, the delivery includes the Human Review
  Report, and each per-item "Final Markdown" excerpt in the report is byte-for-byte
  identical to the corresponding span of the delivered Markdown (no trim, `.strip()`,
  whitespace collapse, Unicode/punctuation/separator normalization, or `<< >>`
  highlighting) — 100% of such deliveries (FR-080 / FR-082).
- **SC-035**: Human-review final verification is location-aware: for a fixture where
  the human-confirmed value also occurs elsewhere in the Markdown, verification is
  anchored to the reviewed segment's rendered span via its processing lineage, and a
  spacing / punctuation / decimal- or thousand-separator / Unicode-only difference
  at that span is reported as VERIFICATION FAILED rather than silently accepted —
  100% of such fixtures (FR-083).
- **SC-036**: A run in which any applicable human-review decision fails
  location-aware verification is never presented as a successful delivery; no
  Markdown for that run is written to the delivered-Markdown name; the failed item,
  its human-confirmed expected decision, and the actual final-Markdown evidence
  appear in the Human Review Report; and the failure enters the final fidelity
  validation / audit workflow classified by its originating stage —
  `reconciliation_error` (decision not carried into reconciliation / the CED) or
  `disallowed_transformation` (CED correct, a later transform/render step broke it)
  — 100% of such runs (FR-084).

## Assumptions

- The primary interface is a command-line application. It exposes the five
  document-processing operations `extract`, `validate`, `fix`, `export`, and
  `convert`, plus a separate `review` operation for the human-review workflow
  (FR-066a). The `review` workflow is an **interactive, keyboard-driven terminal
  mode** (FR-074). The specification does **not** require — and the design MUST NOT
  introduce — a graphical desktop application, a browser-based UI, a local web
  server, a desktop-application framework, an OS-specific native application, PDF
  image previews or PNG crop generation for the review workflow, direct manual
  editing of review-state files as the normal workflow, direct patching or
  hand-editing of the final Markdown, automatic continuation immediately after the
  final review answer, or LLM-generated correction of disputed literals. Any
  graphical interface is out of scope for the first version.
- The concrete terminal-interaction library, the human-review queue / resolution
  store file formats, the review-item schema, the review-to-Markdown lineage
  representation, and the Markdown-span representation used for location-aware
  verification (FR-083) are planning / research / data-model / contract decisions.
  This specification fixes the **behaviour** (interactive terminal, immediate
  persistence, explicit authorization, literal Markdown evidence, location-aware
  verification, Human Review Report), not the mechanism.
- The Human Review Report (FR-080) is a **delivery artifact and verification aid**,
  not an authoritative audit store; the authoritative records remain the
  reconciliation log and the human-review resolution store (FR-057 / FR-057a /
  FR-057b). Its exact section layout and file naming beyond `<output-base>_review_report.md`
  are a planning / contract decision.
- One source PDF is processed per invocation; batch processing of multiple PDFs is
  out of scope for the first version.
- Physical PDF pages are indexed from 1.
- **Language scope (v1).** The tool targets **Latin-script Western-language**
  documents. The **primary validated languages are Portuguese, English, and
  Spanish** (the benchmark and acceptance-corpus dimensions). **French, Italian,
  and German** are architecturally supported through the same Latin-script
  OCR / pipeline path — character-coverage compatible, no Portuguese-specific
  hard-coding — but are not primary scored dimensions. **CJK and other non-Latin
  writing systems (Chinese, Japanese, Korean, …) are explicitly out of scope for
  v1.** Language identifiers remain generic / open BCP-47 / ISO-style strings (no
  enum in the schemas or data model), so an additional writing system is an
  additive change — a new OCR model plus corpus — with no schema or data-model
  redesign.
- A "local LLM" means a language model that runs entirely on the user's machine;
  its selection and setup are the user's responsibility. `validate` / `fix` depend
  on it (except a `validate` run that short-circuits on gross divergence). `extract`
  does not require it: without an LLM, reconciliation is deterministic-only and
  unresolved disagreements become HUMAN_REVIEW_REQUIRED items.
- The independent extraction paths for v1 are a layout-aware structural extraction
  path, a low-level geometry-aware PDF text extraction path, and conditional local
  OCR. The architectural requirement is multi-path independence (no path
  consumes another's output) plus at least two independent non-OCR extraction paths
  and conditional local OCR; the
  specific tools are a planning / research decision. Under Constitution VII (v2.0.0,
  "Simplicity & Justified Dependencies") a heavier component — for example one that
  performs machine-learning-based layout analysis — is
  acceptable when its fidelity / validation / diagnosability benefit is documented
  and justified and it stays compatible with Principle V (local-first) — its
  runtime weight or model download is not by itself disqualifying.
- The "validation policy" for final fidelity validation — which validation
  outcomes block or gate delivery of the final Markdown versus are recorded and
  allowed through — is defined during planning.
- Any unresolved HUMAN_REVIEW_REQUIRED item blocks the run's **final Markdown**
  delivery (FR-072). Whether the pipeline still processes wholly unaffected pages
  to completion internally (while the run stays "incomplete" overall) is a planning
  optimisation, not a change to the delivery rule.
- The exact deterministic **applicability key** for replaying a `human_confirmed`
  resolution (FR-071) is a planning decision. It MUST at least bind the source
  document hash, the specific conflict's identity (page/region and conflict type),
  and the output-affecting configuration in effect for that decision, so a
  resolution can never be applied to the wrong document or an incompatible
  extraction context; how granular it is beyond that (e.g. tolerating unrelated
  config changes) is for planning.
- How a `human_confirmed` resolution folds into the deterministic `run_id` /
  reproducibility contract (FR-053a) — whether via a digest of the applicable
  resolution set or otherwise — is a planning decision; the requirement is that the
  same source + configuration + applicable resolutions yields byte-identical
  output.
- How "material disagreement" is measured — separately for **literal content** and
  for **candidate reading orders** — and how the reconciliation confidence score is
  computed for each, are planning decisions; the requirement is the 0.75 default
  threshold, its configurability, and the never-silently-guess rule. Structural
  hints (headings/lists/tables) are not reconciled and do not enter either
  comparison.
- What counts as "deterministic geometric / layout evidence" sufficient to resolve
  a reading-order conflict without the LLM (column detection, block bounding boxes,
  baseline order, etc.), and how a "segment" is delimited so candidates' orders can
  be compared, are planning decisions; the requirement is that reading-order
  reconciliation only ever selects an existing candidate order or a
  geometry-supported order and never fabricates one.
- How the semantic transformation stage weighs competing structural hints (e.g.
  the layout-aware path says "heading" while geometric evidence suggests "body")
  and records its
  decision is a planning decision; the requirement is only that hints are advisory
  and the decision is auditable and kept distinct from the reading-order decision.
- Local OCR runs entirely on the user's machine; it is adaptive and region-aware
  (per page / per region), not document-wide; OCR language is auto-detected per
  page/region with an optional per-run user override.
- How the system decides a native text layer is "materially unreliable" (versus
  merely low-quality but usable) is a detection heuristic defined during planning;
  the requirement here is only that such regions trigger OCR and that both
  evidences are retained with provenance. The native-text reliability assessment
  reads low-level native-text evidence **directly from the source PDF / page
  representation** and MUST NOT consume any extraction path's `ExtractionCandidate`
  — it is an extraction-routing / evidence component that runs before the OCR path
  (path C), not a fourth extraction path and not a consumer of any extraction
  path's candidate output. (Preserves FR-060 / SC-024 path
  independence.)
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
  and scanned pages; fixtures with seeded extraction faults, seeded wrong
  reconciliation choices, and seeded transformation faults for SC-019 / SC-025; at
  least one hybrid page and one corrupted-native-layer page for SC-014 / SC-015;
  at least one page engineered so the extraction paths materially disagree on
  literal content — one resolvable at ≥ 0.75 confidence and one that must fall to
  HUMAN_REVIEW_REQUIRED — for SC-020 / SC-021; and at least one page (e.g.
  multi-column or with a sidebar/footnote block) where the candidates agree on
  literal text but produce different reading orders — one resolvable by geometry
  and one that must fall to a reading-order HUMAN_REVIEW_REQUIRED — for SC-022 /
  SC-023.
