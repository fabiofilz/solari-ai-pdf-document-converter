# Phase 1 Data Model: Local-First PDF Document Converter

> **Rewritten 2026-09-07** for the multi-path extraction → reconciliation → semantic
> transformation → final validation architecture. **The `SFIR` concept is retired.**
> Where the previous data model conflicts with this one, this one wins.
>
> **Updated 2026-09-08** for the interactive Human Review workflow and Human Review
> Report (FR-074–FR-084 / SC-032–SC-036, research §22 / §25 / §26), then **hardened
> 2026-09-08 (audit remediation)**: `resolution_id` is content-bound and
> `sequence_index` is the sole "current" authority (I1–I6, loader fails closed);
> `HumanReviewAuthorization` becomes an append-only **audit event** (validity =
> `run_id` match only; no `queue_sha256`; **not** in the run-twice deterministic
> core); new **`RunContext`** so `review` can recompute `run_id`; `RenderMap` gains
> the closed-enum ordered **`segment_transforms`** and **`collapsed_into`**;
> `HumanReviewVerification` items gain **`defect_class`** (originating stage) and
> **null spans/excerpt for `not_located`**; Markdown serialization is pinned
> (binary UTF-8 / no BOM / LF / no normalization); `<base>.md` is published only
> after all delivery gates pass; run-state derivation has an explicit precedence.
> **research §14 is the authoritative effective-input definition** — all other
> artifacts reference it.

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

**Markdown artifact serialization (research §25.1).** The final `<base>.md` and every
run-scoped staging Markdown are written as `text.encode("utf-8")` in **binary mode**
(never Python text mode), **no BOM**, **LF only**, **no Unicode normalization**.
`delivered_markdown_text := <bytes>.decode("utf-8")`; span offsets are Unicode
code-point positions into that string. This is what makes span offsets and byte
identity deterministic cross-platform (strengthens FR-053a).

**Reproducibility (FR-053a + FR-053b)** — the authoritative effective-input tuple and
`run_id` definition is **research §14** (all other artifacts reference it, none
restate a divergent list):
- **Deterministic core** — the `original Markdown`, DOCX, and every record's
  deterministic content (incl. each validation report's `check_origin:
  "deterministic"` issues + `summary`, **and the Human Review Report + its
  `human_review_verification` machine model**) are byte-reproducible for identical
  effective inputs; `run_id` is a pure digest of those inputs. The
  **currently-applicable** resolution set (the valid record with the greatest
  `sequence_index` per applicability key, research §22.2) folds into
  `applicable_resolution_digest` — changing an answer changes `run_id`.
- **NOT in the deterministic-core artifact-equality set** — the **review authorization
  event log** (`<base>.review-authorizations.jsonl`): it records a human action, is
  append-only audit, and a run-twice test never regenerates it (research §22.4 / M4).
  Its body is still deterministic (no wall-clock) so a re-authorization of an
  unchanged decision set is an idempotent no-op append.
- **LLM-assisted section** — a validation report's `check_origin: "semantic"` issues
  are byte-reproducible only when the backend honours `seed`; the report records
  `llm.reproducibility ∈ {deterministic, best_effort}`. On `best_effort`,
  `pipeline/validate` replays an already-persisted report for the identical
  applicability context rather than regenerating (research §4a pt 5).

---

## Common envelope (every persisted record)

| Field | Type | Notes |
|---|---|---|
| `record_type` | enum | `run_context` \| `extraction_candidate` \| `canonical_extracted_document` \| `reconciliation_log` \| `human_review_queue` \| `human_review_resolution` \| `human_review_authorization` \| `human_review_verification` \| `removal_log` \| `validation_report` \| `correction_log` \| `traceability_record` |
| `schema_version` | str | see each schema — bumped to `"2.1"` where a required field was added 2026-09-08 (resolution, queue, verification, authorization, traceability); `"2.0"` elsewhere |
| `run_id` | str | 16 hex, pure function of inputs — **no wall-clock, no randomness**. **Definition: research §14 (authoritative).** `sha256(source_sha256 ⧺ normalized_selection ⧺ tool_version ⧺ canonical_json(output_affecting_config) ⧺ applicable_resolution_digest)[:16]`. |
| `tool_version` | str | human-readable; also an input to `run_id` |
| `source_pdf` | str | filename only |
| `source_sha256` | str | hex sha256 of the source PDF bytes |
| `page_selection` | str | canonical selector token, or `"all"` |

**`output_affecting_config`** — **defined authoritatively in research §14** (two scopes:
extract-stage vs validate-stage). Do not restate a divergent list here. Excluded: timeouts,
retries, `base_url`, output dir, resolution-store path, `--json`, the review UI path, **and every
Human-Review *workflow event*** (the authorization event, report generation, verification results
are outputs). The applicable **resolution *decisions*** are folded in via
`applicable_resolution_digest` (the currently-applicable set — §22.2).

The **resolution store** (`human_review_resolution` records) is the exception to "one record per
run": it is a durable append-only JSONL that spans runs; each line carries the envelope of the run
that created it, a store-monotonic `sequence_index`, a `resolution_id`, and an optional
`supersedes` link (research §22.2) — records are **only ever appended**, never edited or removed.
The **`review-authorization`** and **`human-review-verification`** records are per-delivery (one
per authorized `run_id`), written under the output dir like other audit records.

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

**Item** (`open` → `resolved`; a `resolved` item stays **reopenable and re-decidable** — FR-076):

| Field | Req? | Type | Notes |
|---|---|---|---|
| `id` | ✓ | str | deterministic from the applicability key |
| `conflict_type` | ✓ | enum `literal_content` \| `reading_order` | |
| `status` | ✓ | enum `open` \| `resolved` | derived from the store on every load (research §22.2) |
| `physical_page` | ✓ | int ≥ 1 | |
| `region_bboxes` | ✓ | list[`[..]`] | one for literal, ≥1 for reading-order — **internal traceability** (FR-075); the terminal workflow does not draw them |
| `contributing_sources` | ✓ | list[str] | techniques involved |
| `reason` | ✓ | str | why automatic reconciliation could not resolve it |
| `confidence` | ✓ | float 0–1 \| null | the score that fell below threshold (null if no LLM / guard reject) |
| `candidates` | ✓ | list | literal: `[{technique, value, ocr_confidence?, provenance_label}]` (FR-062a/FR-075); reading-order: `[{technique, order:[segment_id], provenance_label}]` + `segment_ids: [segment_id]` (FR-062d) |
| `structural_context` | – | `{section_path: [str]\|null, table_id: str\|null, row: int\|null, column: int\|null}` | FR-075 — populated where the extraction evidence knows it |
| `source_context_before` / `source_context_after` | – | str \| null | short **verbatim** windows of surrounding source text (FR-075) |
| `segment_refs` | – | list[segment_id] | internal source-segment references the reviewed content maps to (FR-075) |
| `markdown_line`/`markdown_column` | – | int | populated only when a partial Markdown context exists |

**Queue**: envelope + `items: list[Item]` + `summary: {open, resolved}` + `run_state` (derived —
see *Run state* below). No image / crop fields (FR-018 / FR-074). The queue is rewritten (atomic)
when `status`/`run_state` change; its **content is never an authorization gate** (M2) — the
`RunContext` record, not the queue, carries the effective-input tuple `review` needs.

### `RunContext`  (`run-context.schema.json`)  — H3, research §14 / §22.2

Written by `extract`/`convert` to `<base>.run-context.json` + `.md` so the `review` workflow can
recompute the **current** `run_id` after resolutions change, without re-prompting for flags.

| Field | Type | Notes |
|---|---|---|
| envelope | — | its `run_id` is the run's `run_id` **at write time** (may be recomputed higher by `review`) |
| `extract_output_affecting_config` | object | the **extract-stage** subset of research §14: `{ocr_engine, ocr_languages_override, ocr_confidence_threshold, reconcile_confidence_threshold, enabled_extraction_paths, llm_model?, llm_decode?}` — `canonical_json` of these + the envelope `source_sha256` / `page_selection` / `tool_version` + the current **scoped** `applicable_resolution_digest(source_sha256=…, config_subset=this object)` (H1 — never the no-argument whole-store digest) ⇒ `run_id` (research §14). |

Deterministic; no wall-clock. `review` never mutates it.

### `HumanReviewResolution` + store  (`human-review-resolution.schema.json`, **v2.1**)

One JSONL line per confirmed decision — **append-only** (FR-057b / FR-076 / SC-032). A changed
answer is a **new line**; nothing is edited or deleted. Every append is an **atomic whole-file
publish** (read + append line + `<store>.tmp` + `flush`+`fsync` + `os.replace`) so a crash leaves
the old file or the new complete file, never a torn line (M3).

| Field | Type | Notes |
|---|---|---|
| envelope | — | envelope of the run that created it (incl. its `run_id`) |
| `resolution_id` | str (16 hex) | **content-bound (M1)**: `sha256(canonical_json({applicability_key, sequence_index, selected}))[:16]`. A local-store traceability id, **not** a cryptographic integrity digest. |
| `sequence_index` | int ≥ 0 | **the authority for ordering / "current" (H6)** — unique and strictly increasing store-wide; assigned = `max(existing) + 1` |
| `supersedes` | str (16 hex) \| null | **audit linkage only** — the `resolution_id` of the *currently-applicable* prior record for the same `applicability_key`; `null` iff no prior record. Invariants I1–I6 (research §22.2). |
| `applicability_key` | str | `sha256(source_sha256 ⧺ conflict_type ⧺ canonical(page, region, aligned candidate-value set) ⧺ canonical_json(config_subset))` (research §22) |
| `review_item_id` | str | link back to the queue item |
| `conflict_type` | enum | |
| `physical_page` / `region_bboxes` | int / list | |
| `candidates_presented` | list[`CandidateEvidence`] | the evidence shown to the reviewer (shared `$def`) |
| `decision_method` | const `human_confirmed` | |
| `selected` | object | literal: `{mode: select\|entered, value, from_technique?, manually_verified: bool}` — for `mode: entered` the `value` is the confirmed input **verbatim**, no normalization (FR-068 / FR-082); reading-order: `{order: [segment_id]}` (a permutation of exactly the item's `segment_ids`) |
| `reviewer_note` | str \| null | optional free text |

**Currently-applicable decision** for an `applicability_key` = **the valid record with the greatest
`sequence_index`** for that key. The store loader enforces I1–I6 (research §22.2) and **fails
closed** for a key whose chain is invalid (raises it fresh; never guesses). `replay` and
`applicable_resolution_digest` use exactly the currently-applicable set; for **run identity**
the digest call is always **scoped** to the run's `source_sha256` + config subset (H1) — a
currently-applicable record for another source or an incompatible config folds in nothing. The full previous →
replacement → currently-applicable chain (each with its run context) is recoverable by walking
`sequence_index` / `supersedes` — the append-only audit history FR-076 requires.

### `HumanReviewAuthorization`  (`human-review-authorization.schema.json`, **v2.1**)  — M2, M4

An **append-only audit event**, one line per authorized `run_id`, appended to
`<base>.review-authorizations.jsonl` (+ `.md`) with the same atomic whole-file publish as the
resolution store. **Not** in the FR-053a run-twice deterministic-core artifact-equality set — it
records a human action.

| Field | Type | Notes |
|---|---|---|
| envelope | — | its `run_id` == `authorized_run_id` |
| `authorized_run_id` | str | the 16-hex `run_id` this authorization is bound to. **Authorization validity is exactly `authorized_run_id == current run_id`** — nothing else. |
| `applicable_resolution_digest` | str | the decision-set digest folded into `run_id` (audit evidence + cross-check) |
| `resolved_item_ids` | list[str] | the queue-item ids resolved at authorization time (audit evidence only — **not** a validity gate; the derived `run_state` precedence already handles a newly raised item) |
| `authorized_via` | enum `interactive_continue` \| `cli_authorize` | how the reviewer authorized |

No wall-clock, no random id ⇒ re-authorizing an unchanged decision set is an **idempotent no-op
append**. Changing any decision ⇒ new `run_id` ⇒ no event matches ⇒ `resolved_unauthorized` again
(research §22.4). There is **no `queue_sha256`** (M2 — it would self-invalidate).

### `RenderMap`  (stage-5 output; embedded in `human_review_verification.items[].lineage`)

| Field | Type | Notes |
|---|---|---|
| `blocks` | `[{ block_id, span }]` | codepoint `[start,end)` per `SemanticDocument` block |
| `segment_spans` | `[{ segment_id, spans: [span, …] }]` | where each accepted source segment's own text landed — **may be multiple spans** (merged HTML cell, a segment split across syntax) (M11) |
| `collapsed_segments` | `[{ segment_id, collapsed_into: segment_id, rule }]` | a segment with **no standalone span** because a permitted stage-3 op folded it into a canonical twin — repeated table-header collapse (FR-021), duplicate structural material (M7). `rule` names the permitting FR. |
| `segment_transforms` | `[{ segment_id, transforms: [ {kind, stage, permitted_by, detail?} … ] }]` | **ordered** deterministic ops that changed a segment's **own characters** between CED literal and rendered bytes (H1, research §25.2). `kind ∈ {dehyphenate, reflow_whitespace, markdown_escape, html_escape, cell_newline_br, ocr_marker}` — **a closed enum**, each with a permitting FR. Not an open normalizer. |
| `markdown_sha256` | str | sha256 of the delivered Markdown bytes the offsets index into |

`render/markdown.py` produces it as it lays text down; `transform/reflow.py` contributes the
stage-3 `segment_transforms`. The old `segment_edits` (`dehyphenate` only) is **replaced** by
`segment_transforms`.

### `ReviewRenderLineage` + `HumanReviewVerification`  (`human-review-verification.schema.json`, **v2.1**)

One record per **authorized** delivery attempt that had ≥ 1 applicable human-review decision
(research §25) — written whether verification passes or fails (FR-084). The **authoritative machine
model** the Human Review Report renders from.

| Field | Type | Notes |
|---|---|---|
| envelope | — | deterministic; joins the FR-053a core |
| `delivered_markdown` | `{ path, markdown_sha256, run_id }` | the file verified against — `path` = `intermediates/<base>.<run_id>.unverified.md` until step 5 of §25.7 publishes `<base>.md`; `run_id` MUST equal the record `run_id` AND a matching authorization event's `authorized_run_id` |
| `items` | list[`VerificationItem`] | one per applicable decision |
| `summary` | `{ decisions_applicable, resolved, verified, failed, status: "PASS"\|"FAIL" }` | `PASS` iff `failed == 0 && verified == decisions_applicable` — computed here, **printed verbatim** by the Report |

**`VerificationItem`**:

| Field | Type | present when |
|---|---|---|
| `review_item_id` / `applicability_key` / `conflict_type` / `resolution_id` | str/str/enum/str | always |
| `lineage` | `{ accepted_segment_ids, reconciliation_decision_id: str\|null, ced_accepted, semantic_block_ids: [str], render_span: span\|null, per_segment_spans: [{segment_id, spans:[span]}]\|null, segment_transforms: [...]\|null, incomplete: bool }` | always (fields inside may be `null` — see below) |
| `expected` | literal: `{ value }` (verbatim human-confirmed); order: `{ order: [segment_id] }` | always |
| `render_span` / `per_segment_spans` / `final_markdown_span_lc` / `final_markdown_excerpt` | span / spans / `{start_line,start_col,end_line,end_col}` / str | **non-null iff the reviewed location resolved** (H4) — i.e. `failure_reason != not_located`. `null` for `not_located`. |
| `status` | enum `applied_and_verified` \| `verification_failed` | always |
| `failure_reason` | enum `not_located` \| `literal_altered` \| `order_not_reflected` \| null | only on failure (research §25.5) |
| `defect_class` | enum `reconciliation_error` \| `disallowed_transformation` \| `extraction_error` \| null | **only on failure** — the originating stage (research §25.6 / H5): `reconciliation_error` iff `lineage.ced_accepted` ≠ the human-confirmed decision (or `reconciliation_decision_id` is null); `disallowed_transformation` iff the CED is correct but a stage-3/5 transform altered it or an unrecorded removal dropped it; `extraction_error` if the confirmed value itself was a source-evidence fault |
| `structural_context` / `source_context_before` / `source_context_after` / `candidates_presented` | shared `$def`s (M2/L3) | copied from the queue item for the Report (FR-081); the source-context copy MAY carry report-only markers, the excerpt MUST NOT (FR-082) |

**Application-level invariants** (JSON Schema can't fully express — validated in code + tests):
`not_located` ⇒ all span/excerpt fields `null` and `lineage.incomplete == true`;
`applied_and_verified` ⇒ `render_span` + `final_markdown_excerpt` + `final_markdown_span_lc`
present; `literal_altered` / `order_not_reflected` ⇒ span/excerpt present (location resolved,
content/order wrong); `defect_class` present iff `status == verification_failed`.

**Determinism**: a pure function of `(delivered_markdown_text, RenderMap incl. segment_transforms,
CED decisions, currently-applicable resolutions, RunContext)` — all pinned by `run_id`. A
`verification_failed` item is also emitted as a validation issue with `review_item_id` +
`defect_class` (research §25.6) and blocks successful delivery (FR-084).

### `HumanReviewReport` (rendered artifact — `<base>_review_report.md`; NOT a store)

The human-readable Markdown rendering of `human_review_verification` (FR-080–FR-082, research §26).
Same "one model renders both" rule as every FR-057 pair — the `.json` is
`human-review-verification.schema.json`, the `.md` is the Report. It holds **no** state not
derivable from that record + the delivered Markdown; it **prints `summary.status` verbatim** (it
does not re-decide PASS/FAIL). Per applicable decision it presents **three distinct things** (M6):
1. the human-confirmed **source literal / order** (verbatim);
2. the **applied permitted transformations** — the ordered `segment_transforms` chain with each
   kind's permitting FR (shown only when non-empty);
3. the **actual final-Markdown evidence** — the literal excerpt, or "not located" for
   `not_located`;
plus PDF page, structural context, source context, candidates offered, and the
`APPLIED AND VERIFIED` / `NOT APPLIED — VERIFICATION FAILED` status + `failure_reason` +
`defect_class`.

### Run state (derived — not a stored flag; FR-077 / research §22.4)

**Evaluated in this precedence order — first match wins (M11):**

| # | State | Condition |
|---|---|---|
| 1 | `unresolved` | ∃ queue item `open` (after applying the store I1–I6). **A newly raised item always wins here**, regardless of a prior authorization for an earlier `run_id`. |
| 2 | `delivery_blocked_verification_failed` | no `open` items **and** a `human_review_verification` record for the current `run_id` with `summary.status == "FAIL"` |
| 3 | `delivered` | no `open` items **and** `<base>.md` on disk matches what this run renders **and** (if ≥1 applicable decision) a `human_review_verification` for the current `run_id` with `status == "PASS"` **and** (for `convert`) a traceability record for the current `run_id` |
| 4 | `authorized` | no `open` items **and** a `review-authorizations.jsonl` line with `authorized_run_id == current run_id`. Rendering/verification may be in progress or not started — **still not `delivered`**; a restart re-runs render + verification deterministically. |
| 5 | `resolved_unauthorized` | no `open` items and none of the above |

`extract`/`convert` exit **6** for `unresolved`, `resolved_unauthorized`, and
`delivery_blocked_verification_failed`; `run_state` is in the message and in `--json`. There is
**no persisted "in-progress" state** — "authorized, rendered, no complete verification record yet"
derives as `authorized` and a restart is safe.

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

Every block carries `block_id` (stable), `provenance: [segment_id]` and
`hint_decisions: [{hint_ref, applied: bool}]` (FR-064 auditability). `Table` =
`{rows: [[Cell]], has_merged_cells, header_row_count, spans_pages: [int]}`;
`Cell` = `{text, rowspan≥1, colspan≥1, is_header, provenance: [segment_id]}`.
Any re-ordering a table/list operation needs vs the accepted order is recorded as
`structural_reorder: [{scope, affected_segment_ids: [segment_id], from_order, to_order, reason}]` —
distinct from the source-ordering decision (FR-064 / SC-023). `affected_segment_ids` +
`from_order` + `to_order` are what the reading-order verification invariant (research §25.5 / M8)
checks against.

**RenderMap + `segment_transforms` (research §25.2, FR-083, H1).** `render/markdown.py` emits a
`RenderMap` (codepoint `[start,end)` spans per block and per `segment_id` — **possibly multiple
spans per segment**; `collapsed_segments` for a segment folded into a canonical twin;
`segment_transforms` — an **ordered, closed-enum** list of the deterministic ops that changed each
segment's **own characters**: `dehyphenate` / `reflow_whitespace` (stage 3), `markdown_escape` /
`html_escape` / `cell_newline_br` / `ocr_marker` (stage 5), each with its permitting FR). This
**replaces** the old `segment_edits` (which modelled only de-hyphenation). It feeds the
review→Markdown lineage and location-aware verification (`HumanReviewVerification`, above).

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
| `issue_type` | ✓ | enum `missing_content` \| `extra_content` \| `numeric_mismatch` \| `literal_mismatch` \| `structure_mismatch` \| `heading_level` \| `table_shape` \| `duplicated_header` \| `reading_order` \| `unprovenanced_content` \| `ocr_low_confidence` \| `gross_divergence` \| `other` |
| `description` | ✓ | str |
| `defect_class` | ✓ | enum `extraction_error` \| `reconciliation_error` \| `disallowed_transformation` (FR-034a) |
| `check_origin` | ✓ | enum `deterministic` \| `semantic` |
| `source_location` / `expected` / `found` / `suggested_action` | – | str (FR-035) |
| `markdown_region` | – | `{start_line,start_col,end_line,end_col}` — the region `fix` may touch |
| `reconciliation_ref` | – | `decision_id` — set on `reconciliation_error` so `fix` can route it (FR-045a) |
| `review_item_id` | – | set when the issue is a **human-review verification failure** (FR-084 / research §25.6): `issue_type ∈ {literal_mismatch, reading_order, missing_content}`, `check_origin = deterministic`, `defect_class` = the originating stage (`reconciliation_error` when the CED does not carry the human-confirmed decision → routes to `review`; `disallowed_transformation` when the CED is correct but a stage-3/5 transform altered it → code-fix or `fix` + §25 re-verification; `extraction_error` if the confirmed value itself was a source-evidence fault) |

`literal_mismatch` = source-backed **non-numeric** literal text that is present in both the
source / extraction evidence and the produced output but whose value was **altered** (the
"modified literal" fault of SC-025 / T094). It is kept distinct from `missing_content` (present
in source, absent from output), `extra_content` (present in output, unsupported by source),
`numeric_mismatch` (an altered numeric or monetary value — that type still applies), and
`reading_order` / `structure_mismatch` (ordering and structural-transformation errors, not
literal-value alteration). Its `defect_class` is assigned exactly as for any other issue
(`extraction_error` / `reconciliation_error` / `disallowed_transformation`, FR-034a) — this new
value changes only the `issue_type` vocabulary, not the defect-class model or any detection rule.

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
`run_context`, `human_review_queue`, **`review_authorizations`** (the append-only event log),
**`human_review_report`** (the `.md`), **`human_review_verification`** (the machine model); each
`{ path, sha256, deterministic_name }` +
`llm_used`: `{ base_url, model, operations: subset of ["reconcile","validate"], decode,
reproducibility: "deterministic" | "best_effort" } | null` (FR-053b) +
`network_egress: { occurred: false }` (SC-008) +
`resolutions_applied: [{ applicability_key, review_item_id, resolution_id }]` (the currently-
applicable decisions replayed this run) +
`human_review_verification_summary: { applicable, verified, failed, status: "PASS"\|"FAIL" } | null`
(FR-084; `null` when the run had no applicable human-review decision; full detail is the linked
`artifacts.human_review_verification` record).

A `convert` run that stopped at the human-review queue (`unresolved` / `resolved_unauthorized`)
**or** ended `delivery_blocked_verification_failed` emits **no** traceability record (FR-051 /
FR-084); it emits the queue, the report (if authorized), and the intermediates. A traceability
record is written only for a **`delivered`** run.

### `RunIdentity` (internal, echoed into every envelope)

`{ run_id, source_sha256, normalized_selection, tool_version, output_affecting_config,
applicable_resolution_digest }` — **defined authoritatively in research §14**.
`applicable_resolution_digest = sha256(sorted( f"{applicability_key}={canonical_json(selected)}"
for each *currently-applicable* resolution replayed ))`. The persisted **`RunContext`** record is
the same tuple minus the digest, so `review` can recompute `run_id` after the store changes
(research §14 / §22.2).

---

## Pipeline state flow

```
              ┌───────────── stage 1 (concurrent, isolated) ─────────────┐
source PDF ──▶│ Docling → cand A   pdfplumber+pypdfium2 → cand B   OCR? → cand C │
              └──────────────────────────┬──────────────────────────────┘
                                         ▼  (each persisted)
                          ┌──── stage 2: reconciliation ────┐
                          │ align → literal recon → reading- │
                          │ order recon → guard → decisions  │──▶ open items? ──▶ queue + STOP (exit 6, run_state=unresolved)
                          │ (replay CURRENTLY-APPLICABLE      │        │
                          │  store resolutions §22.2)         │        ▼   interactive `review`: keyboard resolve (immediate save),
                          └───────────────┬──────────────────┘            browse/reopen/change (append-only), then:
                                          ▼                               [Review answers | Continue processing | Save and exit]
                                  all items resolved                              │ "Continue processing" ⇒ write review-authorization(run_id)
                                          ▼                                        │ "Save and exit" ⇒ run_state=resolved_unauthorized, exit 6
                          run_state == authorized?  ──no──▶ STOP (exit 6, run_state=resolved_unauthorized)
                                          │ yes
                                          ▼
                          CanonicalExtractedDocument (+ reconciliation log)   (+ RunContext persisted)
                                          ▼
                          stage 3: semantic transformation (deterministic) ──▶ SemanticDocument (+ removal log)
                                          ▼
                          stage 4: built-in deterministic final-fidelity self-check
                                          ▼
                          stage 5: render ──▶ intermediates/<base>.<run_id>.unverified.md  (+ RenderMap incl. segment_transforms)
                                          ▼
                          §25 location-aware Human-Review verification  (only if ≥1 applicable decision)
                                          │   ──▶ intermediates/<base>.human-review-verification.json  +  <base>_review_report.md
                                          ▼
                          DELIVERY GATE — ALL must hold: no open items;
                            authorization event with authorized_run_id == run_id;
                            stage-4 passed;  (if applicable) verification summary.status == PASS
                                          │
                          ┌───── gate fails ─────┐        └──── gate passes ────┐
                          ▼                       ▼                              ▼
              delivery_blocked_          resolved_unauthorized       ATOMIC PUBLISH: os.replace →  <base>.md
              verification_failed        (exit 6)                    then (convert) TraceabilityRecord (last)
              (exit 6; keep the                                      run_state = delivered
               .unverified.md for audit,
               <base>.md NOT written;
               reconciliation_error /
               disallowed_transformation
               issue → fix/validate route)
                          ▼
              `validate` (standalone / in convert): full stage 4 (deterministic + LLM) ──▶ ValidationReport
              `fix`: disallowed_transformation → edit + RE-VERIFY §25;  reconciliation_error → route to review
              `export`: Markdown → DOCX
              `convert`: extract → validate → [export] → TraceabilityRecord   (only when run_state == delivered)
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
| Human resolution: select / enter (literal) or reorder (order); never rewrite | FR-068/FR-069 | `reconcile/resolutions.py` validates the input shape; entered value stored verbatim |
| `review` is an interactive keyboard-driven terminal mode (Up/Down/Enter, "Enter another value…", browse, reopen) | FR-074/FR-075/FR-078 | `review/tui.py` (`questionary`); `pipeline/review.py` core; non-interactive `review list/show/resolve/authorize/status` for automation |
| Ctrl+C / `None` from a prompt ⇒ cancellation, never a persisted value | FR-070, research §22.8 | `review/tui.py` treats `ask()==None` as cancel; failing-first test with scripted `KeyboardInterrupt` |
| `--value-file` is normative for whitespace/newline-sensitive exact literals | FR-068, research §22.5 | `cli.py` reads bytes, requires UTF-8, no strip/normalize/BOM-strip; `--value` is single-line only |
| Each confirmed answer persisted (atomic whole-file publish + fsync) before advancing; survives interruption; torn write ignored; resume at next unresolved | FR-070, SC-032 | `reconcile/resolutions.py` atomic `tmp`+`fsync`+`os.replace` **before** queue-item update; loader ignores a non-`\n`-terminated / unparseable final line; status re-derived from store on load |
| Reopen & change ⇒ append-only supersede; `sequence_index` authoritative for "current"; I1–I6 enforced, loader fails closed | FR-076, SC-033 | `resolution_id` content-bound; `sequence_index` unique+increasing; `supersedes` = current prior; `resolutions.py` "greatest `sequence_index` per key"; invalid chain ⇒ raise fresh |
| Human resolution persisted, append-only, replayable, LLM-free | FR-057b/FR-070/FR-071 | `reconcile/resolutions.py` (append-only JSONL); replay by applicability key |
| Resolving the last item ⇒ NOT authorization; explicit "Continue processing" required | FR-077, SC-028 | derived `run_state`; `review-authorizations.jsonl` event keyed to `run_id`; `pipeline/extract.py` / `workflow/convert.py` check it |
| Authorization validity = `authorized_run_id == current run_id` **only** (no queue hash) | FR-077, M2 | `review/session.py`; derived `run_state` precedence handles "new item appeared" |
| Authorization is an audit event, NOT a run-twice deterministic-core artifact | FR-053a, M4 | `<base>.review-authorizations.jsonl` excluded from the run-twice equality set; body still deterministic (idempotent no-op append) |
| Changing an answer after authorization ⇒ new `run_id` ⇒ prior authorization void, re-authorize | FR-077, FR-079 | `run_identity.py` folds `applicable_resolution_digest`; `review` recomputes `run_id` from `RunContext` + current store |
| `review` recomputes the current `run_id` without re-prompting for flags | FR-077, H3 | `RunContext` (`run-context.schema.json`) persists the extract-stage §14 tuple; `review/session.py` folds in the current applicable digest |
| Decisions flow through reconciliation → CED → transform → validate → render; never patch Markdown | FR-079 | resume path regenerates from CED; no Markdown-editing code path in `review/` or `pipeline/review.py` |
| Unresolved review ⇒ no **successful** delivery | FR-072, SC-027 | `pipeline/extract.py` / `workflow/convert.py` early-return at the queue (exit 6) |
| Markdown serialized binary UTF-8, no BOM, LF, no normalization; span offsets are code-points into the decoded string | FR-082/FR-083, M5 | `render/markdown.py` binary write; `review/verify.py` slices `bytes.decode('utf-8')`; cross-platform run-twice byte test |
| `<base>.md` never holds an unverified render; publish only after ALL delivery gates pass | FR-084, H2 | `pipeline/extract.py` renders to `intermediates/<base>.<run_id>.unverified.md`; atomic `os.replace` to `<base>.md` only at the gate; prior delivered artifact ⇒ FR-054 collision (exit 5) |
| Review→Markdown lineage is location-aware; verified at the rendered span, not by global search | FR-083, SC-035 | `review/verify.py` uses `RenderMap` per-segment spans + CED decision ids + `segment_transforms` chain; code-point offsets |
| Expected rendered form = confirmed literal ∘ recorded `segment_transforms` chain; any unrecorded literal change fails | FR-083, H1 | `review/verify.py` re-applies the closed-enum ordered transform list; `render/markdown.py` records every intra-segment edit with its permitting FR |
| Legitimate segment collapse (repeated header, dedup) followed via `collapsed_into`; unrecorded disappearance ⇒ fault | FR-021/SC-003, M7 | `transform/tables.py` records `collapsed_segments`; `review/verify.py` follows the edge; else `not_located` / `disallowed_transformation` |
| Reading-order verified by first-span monotonicity (+ logged `structural_reorder` gate) | FR-083, SC-035, M8 | `review/verify.py`: first-span starts strictly increasing in confirmed order, or logged reorder with `from_order`/`to_order`/`affected_segment_ids` consistent |
| Final-Markdown evidence is the literal delivered excerpt (no strip/normalize/highlight); `null` for `not_located` | FR-082, SC-034, H4 | `final_markdown_excerpt = delivered_markdown_text[start:end]` or `null`; contract `oneOf` on `not_located`; run-twice byte test |
| Each applicable decision gets APPLIED_AND_VERIFIED / VERIFICATION_FAILED + `defect_class` on failure | FR-084 | `HumanReviewVerification.items[].{status, defect_class}`; deterministic |
| Verification failure ⇒ no successful delivery; classed by originating stage; enters validation/audit; `fix` routes/re-verifies | FR-084, FR-034a, SC-036, H5 | `run_state=delivery_blocked_verification_failed`; issue with `review_item_id` + `defect_class` (`reconciliation_error` ⇒ review; `disallowed_transformation` ⇒ code-fix or `fix`+re-verify) |
| Human Review Report delivered when applicable + authorized; derived, not a store; prints `summary.status` verbatim | FR-080/FR-081 | `review/report.py` renders `human-review-verification.json` → `_review_report.md`; no state of its own; shows source-literal / transforms / final-evidence as 3 distinct things |
| Deterministic core byte-reproducible incl. applicable resolutions | FR-053a, SC-009(a) | `run_identity.py`; `langdetect` seed; LLM `temperature:0`+seed; `render/docx.py` fixed timestamps; run-twice test over Markdown/DOCX/deterministic records |
| LLM-assisted validation section: byte-identical under a `seed`-honouring backend, else `best_effort` + replay-persisted, never a false claim / collision | FR-053b, SC-009(b)(c) | `llm_client` seed-determinism probe → `llm.reproducibility`; `reports/report.py` semantic-context-key replay; two-run test with fake LLM `normal` vs `flip` |
| Identical re-run is a no-op; different-content collision surfaced | FR-054 | `artifacts_io.py` byte-compare |
| `fix` routes `reconciliation_error`, never patches it | FR-045a, SC-031 | `fix/apply.py` branch on `defect_class` |
| Final validation vs PDF + evidence + reconciliation provenance | FR-065, SC-025 | `validate/deterministic.py` + `validate/classify.py` |
| Six mandatory issue fields + defect class always populated | FR-034/FR-034a, SC-005 | `ValidationIssue` pydantic (required) + contract test |
| JSON ⇄ Markdown renderings equal | FR-057 | one model instance renders both; contract test |
| Clean failure, no partial artifact | FR-058, SC-016 | atomic `os.replace`; traceability + queue written last |
