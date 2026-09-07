# Phase 1 Data Model: Local-First PDF Document Converter

Two layers:

1. **Semantic Document model** — the in-memory intermediate representation produced by `extract`
   and consumed by the renderers and by `validate`. Not persisted directly; the persisted form
   is the Markdown file.
2. **Audit records** — four persisted artifacts, each written as authoritative JSON **and** a
   generated Markdown rendering of the same content (FR-057). JSON Schemas live in
   [`contracts/`](./contracts/).

All text is Unicode, serialized as UTF-8 (FR-012).

---

## Layer 1 — Semantic Document model

### `SourceSpan` (provenance, attached to every content element)

| Field | Type | Notes |
|---|---|---|
| `physical_page` | int ≥ 1 | 1-based physical PDF page (FR-003). For a stitched multi-page table, the row carries its own page. |
| `bbox` | `[x0, y0, x1, y1]` floats \| null | PDF user-space box; null for synthesized nodes (e.g. a list wrapper). |
| `origin` | enum: `text_layer` \| `ocr` \| `mixed` | `ocr` / `mixed` mark OCR-derived content (FR-025/026). |
| `ocr_confidence` | float 0–100 \| null | Min per-word confidence in the span when `origin` ≠ `text_layer`; drives FR-027 low-confidence surfacing. |
| `ocr_languages` | list[str] | BCP-47-ish codes actually used by OCR for this span (FR-027a); empty for `text_layer`. |

### `Document`

| Field | Type | Notes |
|---|---|---|
| `source_pdf` | str | Original filename (not full path). |
| `source_sha256` | str | Hash of the source PDF bytes; goes into the traceability record. |
| `page_selection` | `PageSelection` | See below; empty ⇒ whole document. |
| `blocks` | list[`Block`] | Document order = reading order (FR-015). |
| `page_ocr` | list[`PageOcrRecord`] | One per page where OCR ran (FR-025). |

### `Block` (discriminated union on `kind`)

| `kind` | Extra fields | Maps to Markdown | Requirement |
|---|---|---|---|
| `heading` | `level` int ≥ 1, `text` str, `numbering` str\|null | `#`×level for 1–6; emphasized lead-in + `[L{n}]` marker for >6 | FR-017, FR-017a |
| `paragraph` | `text` str | plain paragraph, reflowed | FR-013, FR-016 |
| `list` | `ordered` bool, `items` list[`ListItem`] | `-` / `1.` list, nested | FR-018 |
| `clause` | `identifier` str, `text` str, `children` list[`Block`] | identifier retained inline; nested blocks indented | FR-019 |
| `table` | `Table` (below) | pipe table, or HTML `<table>` if any merged cell | FR-020–022 |
| `code`/`quote` | `text` str | fenced / `>` | FR-016 fidelity of block boundaries |

`ListItem`: `{ text: str, children: list[Block], span: SourceSpan }`.

### `Table`

| Field | Type | Notes |
|---|---|---|
| `rows` | list[list[`Cell`]] | Logical grid after multi-page stitching (FR-021). |
| `has_merged_cells` | bool | If true → rendered as HTML `<table>` with `rowspan`/`colspan` (FR-020). |
| `header_row_count` | int ≥ 0 | Repeated page-level headers collapsed to one (FR-022). |
| `spans_pages` | list[int] | Physical pages the logical table covers. |

`Cell`: `{ text: str, rowspan: int ≥ 1, colspan: int ≥ 1, is_header: bool, span: SourceSpan }`.

### `PageSelection`

| Field | Type | Notes |
|---|---|---|
| `ranges` | list[`[start, end]`] int pairs, `start ≤ end`, 1-based | Normalized: sorted, non-overlapping, merged-adjacent. |
| `is_whole_document` | bool | True ⇔ `ranges` empty. |

**Validation (FR-004, rejects produce no output):** non-numeric → reject; `start > end` (e.g.
`10-5`) → reject; any page > page count → reject; overlapping input ranges → reject with the
overlap named. Selection string parsed from `--pages "2,5-7,10-12"`.

### `PageOcrRecord`

`{ physical_page: int, ran_ocr: bool, languages: list[str], language_source: "auto"|"override",
mean_confidence: float, low_confidence_regions: int }` (FR-025, FR-027a).

### State flow

```
extract ──▶ Document ──render──▶ original Markdown  (immutable hereafter, FR-030)
                     └──────────▶ RemovalLog (json+md)

validate(original|corrected Markdown, source PDF, page selection)
        ──▶ ValidationReport (json+md)          [never mutates Markdown, FR-033]

fix(original Markdown, ValidationReport, source context)
        ──▶ corrected Markdown (new file, FR-041)
        ──▶ CorrectionLog (json+md)
        ──▶ re-run validate ──▶ ValidationReport for corrected output (FR-043)

convert = extract → validate → [export] ; never fix (FR-051)
        ──▶ TraceabilityRecord (json+md)
```

---

## Layer 2 — Audit records (persisted; schemas in `contracts/`)

### Common envelope (every record)

| Field | Type | Notes |
|---|---|---|
| `record_type` | enum | `removal_log` \| `validation_report` \| `correction_log` \| `traceability_record` |
| `schema_version` | str | `"1.0"` |
| `generated_at` | str (ISO-8601) | |
| `tool_version` | str | `solari_converter` version |
| `source_pdf` | str | filename |
| `source_sha256` | str | |
| `page_selection` | str | canonical selector token, or `"all"` |

### RemovalLog (FR-011)

`entries[]`: `{ id, page: int, element_type: enum(running_header|running_footer|page_number|
watermark|background|auth_stamp|barcode|qr_code|vertical_auth_text|other), text_excerpt: str|null,
bbox: [..]|null, reason: enum(matched_repeated|matched_pattern|classifier), kept_due_to_ambiguity:
bool, note: str|null }`.

Rule: when ambiguous, `kept_due_to_ambiguity = true` and the element is **not** removed from the
Markdown but is still logged (FR-010). SC-004: 100% of removed elements appear here.

### ValidationReport (FR-032–037)

`llm`: `{ required: true, available: bool, base_url: str, model: str|null }`. If
`available == false` the operation has already hard-stopped (FR-038) — a report file is written
only when the run completed.

`checks_run`: `{ deterministic: true, semantic: bool }`.

`issues[]` — six mandatory fields (SC-005) + optional block:

| Field | Req? | Type | Requirement |
|---|---|---|---|
| `id` | ✓ | str | |
| `severity` | ✓ | enum: `error` \| `warning` \| `info` | FR-034 |
| `source_page` | ✓ | int ≥ 1 | FR-034 |
| `markdown_line` | ✓ | int ≥ 1 | FR-034 |
| `markdown_column` | ✓ | int ≥ 1 | FR-034 |
| `issue_type` | ✓ | enum: `missing_content` \| `extra_content` \| `numeric_mismatch` \| `structure_mismatch` \| `heading_level` \| `table_shape` \| `duplicated_header` \| `ocr_low_confidence` \| `reading_order` \| `gross_divergence` \| `other` | FR-034 |
| `description` | ✓ | str | FR-034 |
| `check_origin` | ✓ | enum: `deterministic` \| `semantic` | traceability of who raised it |
| `source_location` | – | str | FR-035 |
| `expected` | – | str | FR-035 |
| `found` | – | str | FR-035 |
| `suggested_action` | – | str | FR-035; consumed by `fix` |
| `markdown_region` | – | `{ start_line, start_col, end_line, end_col }` | the region `fix` is allowed to touch (FR-040) |

`summary`: `{ error: int, warning: int, info: int, gross_divergence: bool }` — the
gross-divergence flag covers the "wrong Markdown passed to validate" edge case.

### CorrectionLog (FR-042)

`corrections[]`: `{ id, resolves_issue_id: str, markdown_region: {start_line,start_col,end_line,
end_col}, before: str, after: str, rationale: str, change_class: enum(restore_missing|
remove_extra|fix_numeric|fix_structure|fix_heading_level|fix_table) }`.

`unresolved[]`: `{ issue_id: str, reason: enum(region_not_found|ambiguous|out_of_scope), note:
str }` (FR-045).

`revalidation`: `{ report_path: str, report_sha256: str }` (FR-043).

Invariants: every `markdown_region` here ⊆ some `issues[].markdown_region` in the input report
(SC-006); original file hash unchanged pre/post (SC-007).

### TraceabilityRecord (FR-052)

| Field | Type |
|---|---|
| `run_id` | str (uuid) |
| `operation` | enum: `convert` (also written by standalone ops for their own outputs) |
| `physical_page_ranges` | list[`[start,end]`] |
| `artifacts` | object: `original_markdown`, `removal_log`, `validation_report`, `corrected_markdown`?, `correction_log`?, `docx`? — each `{ path: str, sha256: str, deterministic_name: str }` |
| `llm_used` | `{ base_url, model, operations: ["validate", ...] }` \| null |
| `network_egress` | `{ occurred: false }` — asserted, recorded (SC-008) |

SC-010: any artifact → source PDF + exact physical page ranges, unambiguously, from this record.

---

## Validation-rule cross-reference

| Rule | Source | Enforced in |
|---|---|---|
| Page selection 1-based physical; reject reversed/oob/overlap/non-numeric | FR-003, FR-004 | `PageSelection` validators, `pdf/page_selection.py` |
| Original Markdown immutable after `extract` | FR-030 | `fix`/`validate` open source read-only; hash check |
| Six mandatory issue fields always populated | FR-034, SC-005 | `ValidationIssue` model (required) + contract test |
| `fix` edits ⊆ reported regions | FR-040, SC-006 | `CorrectionLog` invariant check + integration test (diff) |
| Original byte-identical after `fix` | FR-041, SC-007 | pre/post sha256 assertion |
| Deterministic names | FR-053, SC-009 | `naming.py` pure function + unit test |
| No overwrite; collision surfaced | FR-054 | `artifacts_io.py` collision policy |
| JSON ⇄ Markdown renderings represent the same content | FR-057 | single model instance renders both; contract test compares |
| Clean failure, no partial artifact | FR-058, SC-014 | atomic write (`os.replace`), traceability written last |
