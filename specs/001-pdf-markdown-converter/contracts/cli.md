# CLI Contract: `solari-convert`

> **Rewritten 2026-09-07** for the multi-path + reconciliation + human-review architecture.
> Console script `solari-convert` (module `solari_converter.cli`). One source PDF per invocation.
> All operations are local. `validate` and `fix` require a reachable local LLM (except a
> gross-divergence `validate`). `extract` / `convert` use the LLM **if available** for
> reconciliation but never require it.

## Operations

`extract` · `validate` · `fix` · `export` · `convert` · `review`

## Global conventions

- **Page selection** `--pages SPEC`: comma-separated single pages and `a-b` ranges, 1-based
  physical pages (e.g. `2,5-7,10-12`). Omitted ⇒ whole document. Invalid (non-numeric,
  `start>end`, out of range, overlapping) ⇒ exit **2**, nothing written (FR-004). Help and
  messages state these are physical positions, not printed labels (FR-003).
- **Output** `--output-dir DIR` (default `./out`): per-run artifacts here with deterministic
  names (FR-053). Intermediates (extraction candidates, canonical extracted document) go in
  `DIR/intermediates/`. Never the source PDF's directory unless pointed there explicitly.
- **Intermediate persistence is always on.** `extract` and `convert` always write the extraction
  candidates, the Canonical Extracted Document, and the reconciliation / human-review / audit
  intermediates — they are required for provenance, diagnostics, deterministic replay, human
  review, failure analysis, and reproducibility. **v1 provides no `--no-intermediates` (or
  equivalent) flag** to suppress them; this is a deliberate design decision (research §23), and
  disk usage is an accepted v1 trade-off. Any future retention/cleanup policy is a separate,
  additive concern that must not weaken auditability or reproducibility.
- **Resolution store** `--resolution-store PATH` (default `DIR/../resolutions.jsonl`): the
  durable, append-only, cross-run store of `human_confirmed` resolutions (FR-057b). Shareable
  across documents (keyed by content, research §22).
- **Reconciliation** `--reconcile-confidence-threshold R` (default **0.75**, range 0–1, FR-062):
  below `R` a conflict becomes HUMAN_REVIEW_REQUIRED. Accepted by `extract` / `convert`.
- **OCR** `--ocr-engine NAME` (`tesseract` | `rapidocr`; default is **benchmark-decided**, set in
  `config.py` after the OCR benchmark — until then the CLI requires it explicitly or errors),
  `--ocr-lang LANG[,LANG...]` (force; omitted ⇒ auto-detect per page/region, FR-027a),
  `--ocr-confidence-threshold N` (normalized 0–100, default **70**, FR-027). Accepted by
  `extract` / `validate` / `fix` / `convert` (FR-027b).
- **LLM** `--llm-base-url URL` (default `http://localhost:11434/v1`), `--llm-model NAME`,
  `--llm-retries N` (default 2, FR-038a — not output-affecting). Used by `validate` / `fix`
  always; by `extract` / `convert` only if reachable.
- **Gross-divergence** `--gross-divergence-threshold R` (default **0.5**, range 0–1, FR-036a).
  `validate` / `convert`.
- `--json`: machine-readable run summary to stdout instead of prose.
- **Reproducibility — two levels** (FR-053a + FR-053b):
  - **Deterministic core**: `original Markdown`, DOCX, and the **deterministic** content of every
    record (incl. each validation report's `check_origin: "deterministic"` issues + `summary`)
    are byte-identical for identical `(source hash, page selection, enabled paths, OCR
    engine+model+config, reconcile threshold, tool version, applicable human resolutions)`.
    (v1 semantic transformation is deterministic and has no output-affecting configuration, so it
    is not part of this tuple; a future output-affecting semantic-transform setting would join it
    — FR-053a.) Records carry no wall-clock timestamp / random id — a content-derived `run_id`.
  - **LLM-assisted**: a validation report's `check_origin: "semantic"` section is byte-identical
    only when the backend honours `seed` (`llm.reproducibility: "deterministic"`); otherwise
    `"best_effort"` and the section is reproduced by **replay** of a persisted report, not
    regeneration (see `validate`).
  An identical re-run is a satisfied no-op (exit **0**); a deterministic-name collision with
  **different** content ⇒ exit **5**, existing file preserved (this never fires merely because a
  `best_effort` semantic section would be regenerated — it is replayed instead).

### Exit codes

| Code | Meaning |
|---|---|
| 0 | Success (incl. idempotent no-op; incl. `review` actions) |
| 2 | Invalid arguments / invalid page selection / invalid `review resolve` input |
| 3 | Source PDF unreadable — missing, encrypted, corrupted |
| 4 | Local LLM required but unavailable, or reachable then failing every attempt after bounded retry (`validate` / `fix` / `convert` validate-step) (FR-038/038a/046/046a, SC-012) |
| 5 | Output-name collision with different content (FR-054) |
| **6** | **Human review required — run incomplete** (`extract` / `convert` stopped at the queue) (FR-072) |
| 7 | Resource exhaustion / interrupted — no partial artifact left as complete (FR-058, SC-016) |
| 8 | Configured OCR engine unavailable/unusable (missing binary / model) |

---

## `extract`

```
solari-convert extract SOURCE.pdf [--pages SPEC] [--output-dir DIR] [--resolution-store PATH]
                       [--ocr-engine NAME] [--ocr-lang L] [--ocr-confidence-threshold N]
                       [--reconcile-confidence-threshold R]
                       [--llm-base-url URL] [--llm-model NAME] [--json]
```

Runs stages 1→2→3, a built-in **deterministic** final-fidelity self-check, and stage-5 render
(FR-066a). The LLM is used for reconciliation selection **iff** reachable; otherwise reconciliation
is deterministic-only and residual disagreements become review items (FR-031/FR-066b).

**Always produces** (in `DIR/intermediates/`):

| Artifact | Name |
|---|---|
| Extraction candidate — Docling | `<base>.candidate.docling.json` |
| Extraction candidate — pdfplumber | `<base>.candidate.pdfplumber.json` |
| Extraction candidate — OCR (if any OCR ran) | `<base>.candidate.ocr.json` |
| Canonical Extracted Document | `<base>.canonical.json` |
| Reconciliation log | `<base>.reconciliation-log.json` + `.md` |

Extraction candidates and the Canonical Extracted Document are **JSON only** (the
machine-readable source of truth); they have **no `.md` companion** — the
reconciliation log's `.md` rendering is the human-facing diagnostic for what each
path produced. Only the audit records get a dual JSON+Markdown emit.

**Then, if no HUMAN_REVIEW_REQUIRED item is open** (in `DIR/`):

| Artifact | Name |
|---|---|
| Original Markdown | `<base>.md` |
| Removal log | `<base>.removal-log.json` + `.md` |

**If any item is open**: writes `<base>.human-review-queue.json` + `.md`, delivers **no** Markdown,
**exit 6**. Resolve with `review resolve` and re-run (`extract` replays the resolutions —
FR-071/FR-072).

`<base>` = `<stem>[__p<sel>]`. Other exits: **2** (bad selection), **3** (unreadable), **8** (OCR
engine unavailable).

**Acceptance mapping**: US1 scenarios 1–11.

---

## `validate`

```
solari-convert validate MARKDOWN.md SOURCE.pdf [--pages SPEC] [--output-dir DIR]
                        [--ocr-engine NAME] [--ocr-lang L] [--ocr-confidence-threshold N]
                        [--gross-divergence-threshold R]
                        [--llm-base-url URL] [--llm-model NAME] [--llm-retries N] [--json]
```

The full stage-4 final fidelity validation (FR-065): compares `MARKDOWN.md` against the original
PDF **and** the independent extraction evidence (it re-runs stages 1–2 to obtain candidates + the
reconciliation log) **and** the reconciliation provenance. Deterministic checks + one read-only
LLM semantic pass. Never modifies `MARKDOWN.md` (FR-033; pre/post hash asserted).

- Requires a reachable LLM: probe first (exit **4**, no report); mid-run failure retried
  `--llm-retries` times then exit **4** (FR-038/038a).
- Gross divergence (match rate < `--gross-divergence-threshold`): sets `summary.gross_divergence`,
  emits one summary issue + structural issues only, **skips the LLM probe and semantic pass**,
  completes without an LLM (FR-036a/FR-038, SC-017).
- Every issue carries the six mandatory fields (SC-005) **plus** `defect_class`
  (`extraction_error` | `reconciliation_error` | `disallowed_transformation`, FR-034a). A
  `reconciliation_error` issue also carries `reconciliation_ref` for routing (FR-045a).
- **Reproducibility (FR-053b)**: at connect time the client probes whether the backend honours
  `seed` and writes `llm.reproducibility` (`deterministic` | `best_effort`). On `best_effort`,
  if a valid persisted report exists for the identical applicability context
  (`markdown_sha256` + `source_sha256` + selection + `llm_model` + `llm_decode`) its
  `check_origin: "semantic"` issues are **replayed verbatim** instead of regenerated — so a
  re-run reproduces the report bytes and is a satisfied no-op, never a collision. The
  deterministic section is always byte-reproducible (FR-053a).
- May also exit **3** / **8** (re-runs extraction).

| Artifact | Name |
|---|---|
| Validation report | `<md-stem>.validation-report.json` + `.md` |

**Acceptance mapping**: US2 scenarios 1–5, 3a.

---

## `fix`

```
solari-convert fix MARKDOWN.md VALIDATION_REPORT.json SOURCE.pdf [--pages SPEC] [--output-dir DIR]
                   [--resolution-store PATH] [--ocr-engine NAME] [--ocr-lang L]
                   [--ocr-confidence-threshold N]
                   [--llm-base-url URL] [--llm-model NAME] [--llm-retries N] [--json]
```

Applies corrections for `disallowed_transformation` issues only (FR-040/FR-044). For each
`reconciliation_error` issue it does **not** edit the Markdown — it writes/updates a
human-review queue item for the underlying conflict and reports it (FR-045a/FR-073). Requires a
reachable LLM (exit **4**, FR-046/046a).

| Artifact | Name |
|---|---|
| Corrected Markdown (only if ≥1 correction applied) | `<md-stem>.corrected.md` |
| Correction log | `<md-stem>.correction-log.json` + `.md` |
| Re-validation report (only if a corrected Markdown was produced) | `<md-stem>.corrected.validation-report.json` + `.md` |
| Human-review queue (if any `reconciliation_error` routed) | `<base>.human-review-queue.json` + `.md` |

Original byte-identical (SC-007). Corrections ⊆ report regions (SC-006). If every issue was
routed and none corrected: no corrected Markdown, `correction_log.corrected_markdown_file = null`,
message tells the user to `review resolve` then re-run `extract`/`convert`.

**Acceptance mapping**: US3 scenarios 1–7.

---

## `export`

```
solari-convert export MARKDOWN.md [--output-dir DIR] [--json]
```

No LLM (FR-049). Markdown → DOCX with Word styles; pipe + HTML `<table>` (incl. `rowspan`/
`colspan`) → Word tables with merged cells (FR-047); deep-level `[L{n}]` → `Heading 7..9` /
styled-list. Byte-reproducible `.docx` (fixed core props + normalized zip timestamps, FR-053a).

| Artifact | Name |
|---|---|
| DOCX | `<md-stem>.docx` |

**Acceptance mapping**: US4 scenarios 1–4.

---

## `convert`

```
solari-convert convert SOURCE.pdf [--pages SPEC] [--output-dir DIR] [--export] [--resolution-store PATH]
                       [--ocr-engine NAME] [--ocr-lang L] [--ocr-confidence-threshold N]
                       [--reconcile-confidence-threshold R] [--gross-divergence-threshold R]
                       [--llm-base-url URL] [--llm-model NAME] [--llm-retries N] [--json]
```

`extract` → `validate` → `export` (only with `--export`). **Never** runs `fix` (FR-051).

- If `extract` raises review items: stop at the human-review queue **before `validate`**, deliver
  no final Markdown and **no traceability record**, exit **6** (FR-051/FR-072). Re-run after
  `review resolve`.
- `validate` step requires a reachable LLM (exit **4** on probe or persistent mid-run failure).

| Artifact | Name |
|---|---|
| all `extract` + `validate` artifacts, DOCX when `--export` | — |
| Traceability record | `<base>.traceability.json` + `.md` |

Links source PDF + physical page ranges + extraction candidates + canonical extracted document +
reconciliation log + Markdown + removal log + validation report + DOCX + any replayed resolutions
(FR-052). Zero outbound connections (SC-008). Same source + selection + config + applicable
resolutions ⇒ byte-identical `original Markdown` + DOCX + deterministic records; second run a
no-op (FR-053a, SC-009).

**Acceptance mapping**: US5 scenarios 1–5.

---

## `review`

```
solari-convert review list                 [--output-dir DIR] [--json]
solari-convert review show   <ITEM_ID>     [--output-dir DIR] [--json]
solari-convert review resolve <ITEM_ID>    [--output-dir DIR] [--resolution-store PATH]
    ( --select <N>                          # literal: accept candidate N as supplied (FR-068a)
    | --value  <TEXT>  |  --value-file PATH  # literal: enter a verified value, no candidate correct (FR-068b)
    | --order  <segId,segId,...> )           # reading-order: reorder the existing segments (FR-069)
    [--note <TEXT>] [--json]
```

- `list` — open items in `<base>.human-review-queue.json` (id, page, type, one-line summary).
- `show <id>` — the full FR-062a / FR-062d evidence for one item: each candidate's value or
  order, bboxes, contributing sources, confidence, reason — enough to compare against the PDF.
- `resolve <id>` — validates the input (`--select` in range; `--order` is exactly the item's
  segment-id set; `--value` non-empty), appends a `HumanReviewResolution` to the store
  (`decision_method = human_confirmed`; `--value` ⇒ `manually_verified: true`), marks the queue
  item `resolved`. Exit **2** on bad input.

Resolutions are **not** applied to Markdown here — the user re-runs `extract` / `convert`, which
replays them (FR-071) and completes when nothing is open (FR-072). `review` never invokes the LLM
and never modifies any Markdown.

**Acceptance mapping**: US1 scenarios 8, 10, 11; US3 scenario 7 (routed items).
