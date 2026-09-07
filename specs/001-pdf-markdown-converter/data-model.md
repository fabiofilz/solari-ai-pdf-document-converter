# Phase 1 Data Model: Local-First PDF Document Converter

> **Rewritten 2026-09-07** for the multi-path extraction → reconciliation → semantic
> transformation → final validation architecture. **The `SFIR` concept is retired.**
> Where the previous data model conflicts with this one, this one wins.

Three layers:

1. **Extraction layer** — one `ExtractionCandidate` per independent path (Docling,
   pdfplumber+pypdfium2, OCR). Persisted **as JSON only** for resume / audit /
   reproducibility — **no `.md` companion** (M1); the reconciliation log's `.md`
   rendering is the human-facing diagnostic for what each path produced. The
   **native-text reliability assessment** that routes OCR is *not* an extraction
   candidate — it reads the raw source PDF directly and never consumes a candidate
   (M2 / research §24).
2. **Reconciliation layer** — alignment, decisions, the `CanonicalExtractedDocument`
   (pre-normalization; **JSON only**, no `.md`), the human-review queue, and the
   durable resolution store.
3. **Delivery layer** — the `SemanticDocument` (ephemeral), the `original Markdown`,
   the DOCX, and the audit records.

All text is Unicode, serialized as UTF-8 (FR-012). **Every audit record** (FR-057)
carries the common envelope (below) and has a JSON source-of-truth **plus** a
generated Markdown rendering that MUST represent the same content. The **extraction
candidates and the Canonical Extracted Document** carry the envelope and are JSON
source-of-truth **without** a Markdown companion — no processing stage may consume a
Markdown rendering as source truth.

**Reproducibility (FR-053a + FR-053b)** — two levels:
- **Deterministic core** — the `original Markdown`, DOCX, and every record's
  deterministic content (incl. each validation report's `check_origin:
  "deterministic"` issues + `summary`) are byte-reproducible for identical effective
  inputs; `run_id` is a pure digest of those inputs.
- **LLM-assisted section** — a validation report's `check_origin: "semantic"` issues
  are byte-reproducible only when the backend honours `seed`; the report records
  `llm.reproducibility ∈ {deterministic, best_effort}`. On `best_effort`,
  `pipeline/validate` replays an already-persisted report for the identical
  applicability context rather than regenerating (research §4a pt 5).

---

## Common envelope (every persisted record)

| Field | Type | Notes |
|---|---|---|
| `record_type` | enum | `extraction_candidate` \| `canonical_extracted_document` \| `reconciliation_log` \| `human_review_queue` \| `human_review_resolution` \| `removal_log` \| `validation_report` \| `correction_log` \| `traceability_record` |
| `schema_version` | str | `"2.0"` (bumped: architecture change) |
| `run_id` | str | 16 hex chars, pure function of inputs — **no wall-clock time, no randomness** (research §14). `sha256(source_sha256 ⧺ normalized_selection ⧺ tool_version ⧺ canonical_json(output_affecting_config) ⧺ applicable_resolution_digest)[:16]`. |
| `tool_version` | str | human-readable; also an input to `run_id` |
| `source_pdf` | str | filename only |
| `source_sha256` | str | hex sha256 of the source PDF bytes |
| `page_selection` | str | canonical selector token, or `"all"` |

**`output_affecting_config`** (folded into `run_id`): `ocr_engine`, `ocr_languages_override`,
`ocr_confidence_threshold`, `reconcile_confidence_threshold`, `gross_divergence_threshold`
(validate/convert only), `llm_model`, `llm_decode` `{temperature, seed}`, `enabled_extraction_paths`.
Excluded: timeouts, retries, `base_url`, output dir, resolution-store path, `--json`.

The **resolution store** (`human_review_resolution` records) is the exception to "one record per
run": it is a durable append-only JSONL that spans runs; each line carries the envelope of the run
that created it.

---

## Layer 1 — Extraction

### `SourceRef` (provenance, on every segment / value)

| Field | Type | Notes |
|---|---|---|
| `physical_page` | int ≥ 1 | 1-based physical PDF page (FR-003) |
| `bbox` | `[x0,y0,x1,y1]` float \| null | PDF user-space box; null only for synthesized wrappers |
| `origin_kind` | enum `native_text` \| `ocr` | FR-025a |
| `extraction_technique` | enum `docling` \| `pdfplumber` \| `ocr:<engine>` | FR-060a |
| `ocr_languages` | list[str] | BCP-47-ish; empty for `native_text` |
| `ocr_confidence` | float 0–100 \| null | min per-word/token, **normalized 0–100** (research §9a); null for `native_text` |

### `SourceBackedSegment`

| Field | Type | Notes |
|---|---|---|
| `segment_id` | str | stable: `sha1(f"{page}:{round(bbox)}:{nfc_text_hash}")[:12]` — used across candidates and in review items |
| `text` | str | **verbatim** extracted text (never a normalized form) |
| `source` | `SourceRef` | |
| `reading_order_index` | int | this candidate's order position for the segment |
| `structural_hints` | list[`StructuralHint`] | may be empty |

### `StructuralHint`

`{ kind: enum(heading|subheading|list_item|list_start|list_end|table|table_row|table_cell|caption|other),
level: int|null, source_technique: str, payload: object }` — advisory evidence only (FR-060b /
FR-061c). Carried into the CED unaltered; applied (or not) only in stage 3, which records the use.

### `CandidateReadingOrder`

`{ technique: str, order: list[segment_id] }` — one per candidate (FR-015).

### `ExtractionCandidate`  (`extraction_candidate.schema.json`)

| Field | Type | Notes |
|---|---|---|
| envelope | — | |
| `technique` | enum `docling` \| `pdfplumber` \| `ocr:<engine>` | |
| `status` | enum `ok` \| `partial` \| `failed` | per FR-060 edge case |
| `status_detail` | str \| null | reason when not `ok` |
| `segments` | list[`SourceBackedSegment`] | |
| `reading_order` | `CandidateReadingOrder` | |
| `pages_covered` | list[int] | |
| `page_ocr` | list[`RegionOcrRecord`] | OCR candidate only |

### `RegionOcrRecord`

`{ physical_page: int, region_bbox: [..]|null, ran_ocr: bool, languages: list[str],
language_source: enum(auto|override), mean_confidence: float, confidence_threshold: float,
low_confidence_regions: int }` (FR-025 / FR-027 / FR-027a). `confidence_threshold` records the
effective normalized-0–100 per-run value (default 70).

### Page/region classification (FR-024b)

`PageClass` per page (and per region where subdivided): enum `native_text_sufficient` \|
`ocr_required` \| `hybrid_native_and_ocr`. Recorded on the OCR candidate and echoed in the CED.

---

## Layer 2 — Reconciliation

### `AlignedSegmentGroup` (internal; not persisted separately, embedded in the log)

`{ group_id, region_bbox, members: [{technique, segment_id, text, source}] }` — the cross-candidate
correspondence unit produced by `align.py` (research §21a). A group may have 1–3 members.

### `ReconciliationDecision`

| Field | Type | Notes |
|---|---|---|
| `decision_id` | str | |
| `conflict_type` | enum `literal_content` \| `reading_order` | |
| `scope` | object | `{page, bbox}` for literal; `{page, region_bboxes}` for reading-order |
| `candidates` | list[object] | literal: `[{technique, value}]`; reading-order: `[{technique, order:[segment_id]}]` (+ a synthesized `geometry` candidate where the geometric resolver produced one) |
| `method` | enum `deterministic_agreement` \| `llm_selected` \| `human_confirmed` | FR-057a |
| `selected` | object | literal: `{value, from_technique}`; reading-order: `{order:[segment_id], from: technique\|geometry\|human}` |
| `confidence` | float 0–1 \| null | present for `llm_selected` (and informational for others) |
| `llm_flip_check` | `{ calls: 2, agreed: bool }` \| null | research §4a |
| `resolution_ref` | str \| null | applicability key of the store record, for `human_confirmed` |
| `replayed` | bool \| null | `human_confirmed` only: replayed from the store vs created this run |

**Invariant (SC-020, tested)**: for `deterministic_agreement` and `llm_selected`, the `selected`
literal value is byte-identical to some `candidates[].value`, and the `selected` order equals some
`candidates[].order` (a real candidate or the `geometry` candidate).

### `ReconciliationLog`  (`reconciliation-log.schema.json`)

| Field | Type |
|---|---|
| envelope | — |
| `alignment_summary` | `{ groups: int, single_candidate_groups: int, iou_threshold: float, jaccard_threshold: float }` |
| `decisions` | list[`ReconciliationDecision`] |
| `unresolved` | list[`{ decision_id, conflict_type, reason: enum(below_threshold\|guard_rejected\|llm_flip\|no_llm), review_item_id }`] |
| `summary` | `{ literal_deterministic, literal_llm, literal_human, order_deterministic, order_llm, order_human, unresolved: int }` |

### `CanonicalExtractedDocument`  (`canonical-extracted-document.schema.json`)

| Field | Type | Notes |
|---|---|---|
| envelope | — | |
| `accepted_segments` | list[`AcceptedSegment`] | |
| `accepted_reading_order` | list[segment_id] | FR-061d; the source-ordering decision |
| `carried_structural_hints` | list[`StructuralHint`] | unapplied (FR-061c) |
| `page_classes` | list[`{page, region_bbox?, class}`] | FR-024b |
| `state` | const `pre_semantic_transformation` | FR-063 |

**`AcceptedSegment`**: `{ segment_id, text (verbatim), source: SourceRef,
contributing_techniques: list[str], decision: {method, decision_id} }`. Never mutated in place
(FR-063).

### `HUMAN_REVIEW_REQUIRED Item` + `HumanReviewQueue`  (`human-review-queue.schema.json`)

**Item** (`open` → `resolved`):

| Field | Req? | Type | Notes |
|---|---|---|---|
| `id` | ✓ | str | deterministic from the applicability key |
| `conflict_type` | ✓ | enum `literal_content` \| `reading_order` | |
| `status` | ✓ | enum `open` \| `resolved` | |
| `physical_page` | ✓ | int ≥ 1 | |
| `region_bboxes` | ✓ | list[`[..]`] | one for literal, ≥1 for reading-order |
| `contributing_sources` | ✓ | list[str] | techniques involved |
| `reason` | ✓ | str | why automatic reconciliation could not resolve it |
| `confidence` | ✓ | float 0–1 \| null | the score that fell below threshold (null if no LLM / guard reject) |
| `candidates` | ✓ | list | literal: `[{technique, value, ocr_confidence?}]` (FR-062a); reading-order: `[{technique, order:[segment_id]}]` + `segment_ids: [segment_id]` (FR-062d) |
| `markdown_line`/`markdown_column` | – | int | populated only when a partial Markdown context exists |

**Queue**: envelope + `items: list[Item]` + `summary: {open, resolved}`.

### `HumanReviewResolution` + store  (`human-review-resolution.schema.json`)

One JSONL line per resolution (append-only, FR-057b):

| Field | Type | Notes |
|---|---|---|
| envelope | — | envelope of the run that created it |
| `applicability_key` | str | `sha256(source_sha256 ⧺ conflict_type ⧺ canonical(page, region, aligned candidate-value set) ⧺ canonical_json(config_subset))` (research §22) |
| `review_item_id` | str | link back to the queue item |
| `conflict_type` | enum | |
| `physical_page` / `region_bboxes` | int / list | |
| `candidates_presented` | list | the evidence shown to the reviewer |
| `decision_method` | const `human_confirmed` | |
| `selected` | object | literal: `{mode: select\|entered, value, from_technique?, manually_verified: bool}`; reading-order: `{order: [segment_id]}` |
| `reviewer_note` | str \| null | optional free text |

Replay: `resolutions.py` reads the store, indexes by `applicability_key`, uses the **last** record
per key. `manually_verified` is `true` for `mode: entered` (FR-068).

---

## Layer 3 — Delivery

### `SemanticDocument` (ephemeral — not a persisted source of truth; research §23)

`Block` discriminated union on `kind`, built from the CED in accepted reading order:

| `kind` | Extra fields | → Markdown | Requirement |
|---|---|---|---|
| `heading` | `level` int ≥ 1, `text`, `numbering` str\|null, `applied_hint` ref\|null | `#`×level (1–6); emphasized lead-in + `[L{n}]` (>6) | FR-017/FR-017a |
| `paragraph` | `text` | reflowed paragraph | FR-013/FR-016 |
| `list` | `ordered` bool, `items` list[`ListItem`] | `-` / `1.`, nested | FR-018 |
| `clause` | `identifier`, `text`, `children` | identifier retained | FR-019 |
| `table` | `Table` | pipe, or HTML `<table>` if merged cells | FR-020–FR-022 |
| `code`/`quote` | `text` | fenced / `>` | FR-016 boundary fidelity |

Every block carries `provenance: [segment_id]` and `hint_decisions: [{hint_ref, applied: bool}]`
(FR-064 auditability). `Table` = `{rows: [[Cell]], has_merged_cells, header_row_count, spans_pages: [int]}`;
`Cell` = `{text, rowspan≥1, colspan≥1, is_header, provenance: [segment_id]}`.
Any re-ordering a table/list operation needs vs the accepted order is recorded as
`structural_reorder: [{scope, from_order, to_order, reason}]` — distinct from the source-ordering
decision (FR-064 / SC-023).

### `PageSelection`

`{ ranges: list[[start,end]] (1-based, start≤end, sorted, non-overlapping, merged-adjacent),
is_whole_document: bool }`. Validation (FR-004, produce no output): non-numeric → reject;
`start>end` → reject; page > page_count → reject; overlapping input ranges → reject naming the
overlap. Parsed from `--pages "2,5-7,10-12"`.

### `RemovalLog`  (`removal-log.schema.json`)  — FR-011

envelope + `entries[]`: `{ id, page, element_type: enum(running_header|running_footer|page_number|
watermark|background|auth_stamp|barcode|qr_code|vertical_auth_text|other), text_excerpt: str|null,
bbox: [..]|null, reason: enum(matched_repeated|matched_pattern|classifier),
kept_due_to_ambiguity: bool, note: str|null }`. Removal is a **stage-3** operation (FR-064);
SC-004: 100% of removed elements appear here.

### `ValidationReport`  (`validation-report.schema.json`)  — FR-032–038a, FR-065

`llm`: `{ required: true, available: bool, base_url, model: str|null,
decode: {temperature: 0, seed: int|null}, attempts: int,
reproducibility: "deterministic" | "best_effort" }` (FR-053b — set from a one-shot
seed-determinism probe at connect time: `deterministic` iff the backend returns
identical output for the probe prompt issued twice; `best_effort` otherwise, and the
report's Markdown rendering states the backend cannot guarantee deterministic
regeneration). `checks_run: {deterministic: true, semantic: bool}` (`semantic` false
on gross-divergence short-circuit).

**Semantic-section replay (FR-053b)**: `pipeline/validate` computes a
`semantic_context_key = sha256(markdown_sha256 ⧺ source_sha256 ⧺ normalized_selection
⧺ llm_model ⧺ canonical_json(llm_decode))`. On `best_effort`, if a persisted report
with a matching key exists and is schema-valid, its `check_origin: "semantic"`
issues are **reused verbatim** and the report is written with those; regeneration
happens only when no match exists. On `deterministic`, the semantic section is
regenerated and is byte-identical anyway. Either way a re-run for an unchanged
context reproduces the same bytes and is a satisfied no-op (no collision).

`compared_against`: `{ original_pdf: true, extraction_evidence: bool, reconciliation_provenance: bool }`
(FR-065 — validation checks the semantic doc against the PDF **and** the candidates **and** the
reconciliation log, not just the prior stage).

`issues[]` — six mandatory fields (SC-005) + defect class + optional block:

| Field | Req? | Type |
|---|---|---|
| `id` | ✓ | str |
| `severity` | ✓ | enum `error` \| `warning` \| `info` |
| `source_page` | ✓ | int ≥ 1 |
| `markdown_line` | ✓ | int ≥ 1 |
| `markdown_column` | ✓ | int ≥ 1 |
| `issue_type` | ✓ | enum `missing_content` \| `extra_content` \| `numeric_mismatch` \| `structure_mismatch` \| `heading_level` \| `table_shape` \| `duplicated_header` \| `reading_order` \| `unprovenanced_content` \| `ocr_low_confidence` \| `gross_divergence` \| `other` |
| `description` | ✓ | str |
| `defect_class` | ✓ | enum `extraction_error` \| `reconciliation_error` \| `disallowed_transformation` (FR-034a) |
| `check_origin` | ✓ | enum `deterministic` \| `semantic` |
| `source_location` / `expected` / `found` / `suggested_action` | – | str (FR-035) |
| `markdown_region` | – | `{start_line,start_col,end_line,end_col}` — the region `fix` may touch |
| `reconciliation_ref` | – | `decision_id` — set on `reconciliation_error` so `fix` can route it (FR-045a) |

`summary`: `{ error, warning, info, gross_divergence: bool, source_text_match_rate: float,
gross_divergence_threshold: float }` (all always populated).

### `CorrectionLog`  (`correction-log.schema.json`)  — FR-042

envelope + `original_markdown_file`, `original_markdown_sha256_before`,
`original_markdown_sha256_after` (MUST equal — SC-007), `corrected_markdown_file: str|null`
(null when every issue was routed), `input_report_file`, `input_report_sha256`,
`corrections[]`: `{ id, resolves_issue_id, markdown_region, before, after, rationale,
change_class: enum(restore_missing|remove_extra|fix_numeric|fix_structure|fix_heading_level|fix_table) }`,
`routed_to_review[]`: `{ issue_id, reconciliation_ref, review_item_id }` (FR-045a),
`unresolved[]`: `{ issue_id, reason: enum(region_not_found|ambiguous|out_of_scope) }`,
`revalidation: { report_path, report_sha256 } | null`.

Invariants: every `corrections[].markdown_region` ⊆ some report issue region (SC-006); original
hash unchanged (SC-007).

### `TraceabilityRecord`  (`traceability-record.schema.json`)  — FR-052, `convert` only

envelope + `operation: const "convert"` + `physical_page_ranges: [[start,end]]` +
`artifacts`: required `extraction_candidates[]`, `canonical_extracted_document`,
`reconciliation_log`, `original_markdown`, `removal_log`, `validation_report`; optional `docx`,
`human_review_queue`; each `{ path, sha256, deterministic_name }` +
`llm_used`: `{ base_url, model, operations: subset of ["reconcile","validate"], decode,
reproducibility: "deterministic" | "best_effort" } | null` (FR-053b) +
`network_egress: { occurred: false }` (SC-008) +
`resolutions_applied: [{ applicability_key, review_item_id }]` (the ones replayed this run).

A `convert` run that stopped at the human-review queue emits **no** traceability record (FR-051);
it emits the queue + intermediates.

### `RunIdentity` (internal, echoed into every envelope)

`{ run_id, source_sha256, normalized_selection, tool_version, output_affecting_config,
applicable_resolution_digest }` (research §14). `applicable_resolution_digest` =
`sha256(sorted( f"{key}={canonical(selected)}" for each replayed resolution ))`.

---

## Pipeline state flow

```
              ┌───────────── stage 1 (concurrent, isolated) ─────────────┐
source PDF ──▶│ Docling → cand A   pdfplumber+pypdfium2 → cand B   OCR? → cand C │
              └──────────────────────────┬──────────────────────────────┘
                                         ▼  (each persisted)
                          ┌──── stage 2: reconciliation ────┐
                          │ align → literal recon → reading- │
                          │ order recon → guard → decisions  │──▶ HUMAN_REVIEW_REQUIRED items? ──▶ queue + STOP (exit 6)
                          │ (replay store resolutions)       │        │  (review resolve → re-run)
                          └───────────────┬──────────────────┘        ▼
                                          ▼                     all resolved
                          CanonicalExtractedDocument (+ reconciliation log)
                                          ▼
                          stage 3: semantic transformation (deterministic) ──▶ SemanticDocument (+ removal log)
                                          ▼
                          stage 4: built-in deterministic final-fidelity self-check
                                          ▼
                          stage 5: render ──▶ original Markdown        (per validation policy)
                                          ▼
                          `validate` (standalone / in convert): full stage 4 (deterministic + LLM)
                                          ▼  ValidationReport (defect classes)
                          `fix`: disallowed_transformation → edit;  reconciliation_error → route to review
                          `export`: Markdown → DOCX
                          `convert`: extract → validate → [export] → TraceabilityRecord
```

---

## Validation-rule cross-reference

| Rule | Source | Enforced in |
|---|---|---|
| Extraction paths independent; one path's fault ≠ others' candidates | FR-060, SC-024 | `extract/` sibling modules; import-graph test; fault-injection test |
| Native-text reliability assessment reads the raw PDF, never a candidate | FR-024/FR-060, SC-024 (M2) | `extract/native_reliability.py` depends on `pdf/loader` only; import-graph test asserts it (and `ocr_path`) import neither `plumber_path` nor `docling_path`; fault-injection into a candidate does not change the OCR-trigger map |
| Docling structure is hint-only until stage 3 | FR-060b, SC-026 | `reconcile/canonical_build.py` carries hints unapplied; `transform/structure.py` records use; fixture test |
| Reading order is reconciled evidence, not literal correctness | FR-015, FR-061d, SC-022 | `reconcile/reading_order.py`; `align.py` keeps order separate from text |
| Automatic reconciliation never invents literal text / an order | FR-061a/b, SC-020 | `reconcile/guard.py` byte-equality check + `assert selected in candidates` |
| LLM used only to select; never authors | FR-029, FR-066b | one `llm_client`; `llm_select.py` returns an index/id; guard; import-graph (no LLM in `transform`/`render`/`export`) |
| Below-threshold conflict ⇒ HUMAN_REVIEW_REQUIRED, never a guess | FR-062, FR-067, SC-018/SC-021 | `reconcile/confidence.py` + `human_review.py` |
| Human resolution: select / enter (literal) or reorder (order); never rewrite | FR-068/FR-069 | `pipeline/review.py` validates the input shape |
| Human resolution persisted, append-only, replayable, LLM-free | FR-057b/FR-070/FR-071 | `reconcile/resolutions.py` (append-only JSONL); replay by applicability key |
| Unresolved review ⇒ no final Markdown | FR-072, SC-027 | `pipeline/extract.py` / `workflow/convert.py` early-return at the queue |
| Resolve-all ⇒ resume, no Markdown hand-edit | FR-072, SC-028 | resume path replays resolutions; regenerates from CED |
| Deterministic core byte-reproducible incl. applicable resolutions | FR-053a, SC-009(a) | `run_identity.py`; `langdetect` seed; LLM `temperature:0`+seed; `render/docx.py` fixed timestamps; run-twice test over Markdown/DOCX/deterministic records |
| LLM-assisted validation section: byte-identical under a `seed`-honouring backend, else `best_effort` + replay-persisted, never a false claim / collision | FR-053b, SC-009(b)(c) | `llm_client` seed-determinism probe → `llm.reproducibility`; `reports/report.py` semantic-context-key replay; two-run test with fake LLM `normal` vs `flip` |
| Identical re-run is a no-op; different-content collision surfaced | FR-054 | `artifacts_io.py` byte-compare |
| `fix` routes `reconciliation_error`, never patches it | FR-045a, SC-031 | `fix/apply.py` branch on `defect_class` |
| Final validation vs PDF + evidence + reconciliation provenance | FR-065, SC-025 | `validate/deterministic.py` + `validate/classify.py` |
| Six mandatory issue fields + defect class always populated | FR-034/FR-034a, SC-005 | `ValidationIssue` pydantic (required) + contract test |
| JSON ⇄ Markdown renderings equal | FR-057 | one model instance renders both; contract test |
| Clean failure, no partial artifact | FR-058, SC-016 | atomic `os.replace`; traceability + queue written last |
