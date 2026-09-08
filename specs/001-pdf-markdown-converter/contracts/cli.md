# CLI Contract: `solari-convert`

> **Rewritten 2026-09-07** for the multi-path + reconciliation + human-review architecture.
> **Updated 2026-09-08** — `review` is now an **interactive keyboard-driven terminal mode**
> (FR-074–FR-084); the file/flag form is a secondary automation sub-interface. Successful
> delivery additionally requires explicit downstream-processing authorization (FR-077) and
> location-aware verification of every applicable human-review decision (FR-083/FR-084).
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
| **6** | **Human review required — run incomplete.** Covers three `run_state`s (in the message + `--json`): `unresolved` (open items — `extract`/`convert` stopped at the queue, FR-072); `resolved_unauthorized` (all items resolved, downstream processing not authorized — FR-077); `delivery_blocked_verification_failed` (rendered but ≥1 applicable review decision failed location-aware verification — FR-084; any Markdown exists **only** at `intermediates/<base>.<run_id>.unverified.md`, **never** at `<base>.md`, and is not a successful delivery — research §25.7). No new code — the structured `run_state` distinguishes them. |
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

Every run that raises human review also writes `<base>.run-context.json` — the persisted
extract-stage effective-input tuple (research §14) that lets `review` recompute the current
`run_id` after the resolution store changes without re-prompting OCR/reconcile flags.

**Then, only when `run_state == delivered`** — no open item (FR-072), an authorization **event**
whose `authorized_run_id == current run_id` exists in `<base>.review-authorizations.jsonl`
(FR-077), the built-in stage-4 self-check passed, **and** every applicable human-review decision
passed location-aware verification (FR-083/FR-084). The render is first staged at
`intermediates/<base>.<run_id>.unverified.md` and is **atomically published to `<base>.md` only
after all of those gates pass** (research §25.7):

| Artifact | Name |
|---|---|
| Original Markdown | `<base>.md` |
| Removal log | `<base>.removal-log.json` + `.md` |
| Human Review Report (**only if** the run had ≥1 applicable human-review decision) | `<base>_review_report.md` (+ machine model `<base>.human-review-verification.json` in `intermediates/`) |

**Otherwise the run is not a successful delivery — exit 6** with the `run_state` in the message
and `--json`:

- `unresolved` — writes `<base>.human-review-queue.json` + `.md` + `<base>.run-context.json`, no
  Markdown at `<base>.md`. Run `review` (interactive) or `review resolve` (scripting), then re-run.
- `resolved_unauthorized` — the queue is fully `resolved` but no authorization event matches this
  `run_id`. Run `review` and choose **Continue processing** (or `review authorize`), then re-run.
- `delivery_blocked_verification_failed` — the render exists **only** at
  `intermediates/<base>.<run_id>.unverified.md` (retained for audit; `<base>.md` is **not**
  written) but ≥1 decision failed verification; writes `<base>_review_report.md` +
  `<base>.human-review-verification.json` and a validation issue set classed by originating stage
  (`reconciliation_error` → back to `review` via FR-045a; `disallowed_transformation` → code fix +
  re-verification, or `fix` + mandatory re-verification).

`<base>` = `<stem>[__p<sel>]`. Other exits: **2** (bad selection), **3** (unreadable), **8** (OCR
engine unavailable).

**Acceptance mapping**: US1 scenarios 1–18.

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
`reconciliation_error` issue — including a **human-review verification failure** (an issue
carrying `review_item_id`, FR-084) — it does **not** edit the Markdown; it writes/updates a
human-review queue item for the underlying conflict and reports it (FR-045a/FR-073/FR-084). The
reviewer re-decides via `review`, the decision set (and `run_id`) changes, re-authorization is
required, and `extract`/`convert` re-render and re-verify. Requires a reachable LLM (exit **4**,
FR-046/046a).

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

- If `extract` does not reach `run_state == delivered` (any of `unresolved` /
  `resolved_unauthorized` / `delivery_blocked_verification_failed`): stop **before `validate`**,
  deliver no final Markdown and **no traceability record**, exit **6** (FR-051/FR-072/FR-077/
  FR-084). Re-run after resolving + authorizing via `review`.
- `validate` step requires a reachable LLM (exit **4** on probe or persistent mid-run failure).

| Artifact | Name |
|---|---|
| all `extract` + `validate` artifacts, DOCX when `--export`, `<base>_review_report.md` when applicable | — |
| Traceability record (**only when `run_state == delivered`**) | `<base>.traceability.json` + `.md` |

Links source PDF + physical page ranges + extraction candidates + canonical extracted document +
reconciliation log + Markdown + removal log + validation report + `run-context` + DOCX + the
`review-authorizations` event log + the Human Review Report + the `human-review-verification`
record + the currently-applicable replayed resolutions (`applicability_key` + `review_item_id` +
content-bound `resolution_id`) + a required
`human_review_verification: {applicable, verified, failed, status}` summary (FR-052/FR-080/FR-084).
Zero outbound connections (SC-008). Same source + selection + config + applicable resolutions ⇒
byte-identical `original Markdown` + DOCX + deterministic records (incl. the Human Review Report +
verification record); second run a no-op (FR-053a, SC-009).

**Acceptance mapping**: US5 scenarios 1–6.

---

## `review`

### Interactive mode (the normal path — FR-074)

```
solari-convert review [--output-dir DIR] [--resolution-store PATH]
```

An **interactive, keyboard-driven terminal** workflow (`questionary` on `prompt_toolkit`, research
§22.1). No graphical UI, no browser, no web server, no page-image or crop preview (FR-074/FR-018).
The reviewer navigates every menu with **Up / Down / Enter**; numeric-menu typing is never the
normal interaction.

Per open item (FR-075) it shows: the physical PDF page; section / table / row / column where
known; short verbatim windows of source text before and after the disputed segment; and, for each
candidate, its value (or order) plus a human-readable provenance label (e.g. `layout path
(docling), p.5` / `OCR (tesseract; pt; conf 82)`). Then a `select` menu:

- **literal-content**: `candidate A`, `candidate B`, … , **`Enter another value…`**. Choosing
  "Enter another value…" opens a `text` prompt; the typed value is stored **exactly as entered**
  — no `.strip()`, Unicode normalization, quote/separator rewrite, or autocorrect (FR-068/FR-082)
  — with `mode: entered`, `manually_verified: true`.
- **reading-order**: build the order by picking the existing segments one at a time (the menu
  shrinks as segments are placed). No literal editing is possible here (FR-069).

Each confirmed answer is **persisted immediately** — an append-only line published by an atomic
whole-file replace (read + append + `.tmp` + fsync + `os.replace`, so a crash leaves the old file
or the complete new file, never a torn line) + the queue item marked `resolved` — **before** the
next item is shown (FR-070/SC-032). A Ctrl+C / SIGINT at a prompt makes `questionary` return
`None`; the workflow treats that **strictly as cancellation of that prompt — never as a confirmed
value** — and exits **0** with every previously confirmed answer saved. Reopening resumes at the
next unresolved applicable item and never re-asks a resolved one.

At any time — and always after the **last** open item is answered — the workflow offers a `select`
menu:

| Choice | Effect |
|---|---|
| **Review answers** | browse the resolved decisions (Up/Down/Enter); each entry shows page / section-or-table / reviewed field / currently-confirmed value; selecting one reopens its details and allows a change. A changed answer appends a **new** resolution record with `supersedes` set — the prior decision is retained (FR-076/SC-033). |
| **Continue processing** | **appends** an authorization event (`authorized_run_id = current run_id`, `authorized_via: interactive_continue`) to `<base>.review-authorizations.jsonl` and resumes the pipeline. Validity is exactly `authorized_run_id == current run_id` — no queue-file hash (M2); re-authorizing an unchanged decision set is an idempotent no-op append. This is the **only** way the interactive path grants authorization (FR-077). |
| **Save and exit** | persists nothing new; the run stays `resolved_unauthorized`; exit 0. |

Reopening `review` when everything is already `resolved` but the run is `resolved_unauthorized`
presents **Review answers / Continue processing / Exit** — it never continues automatically
(FR-077).

**Changing an answer changes the decision set → a new `run_id` (research §14, the authoritative
effective-input definition) → no authorization event in `<base>.review-authorizations.jsonl`
matches the new `run_id` → the run is `resolved_unauthorized` again and must be re-authorized**
before a successful delivery (FR-077/FR-079). No successful delivery is possible without an
authorization event whose `authorized_run_id` equals the delivered artifacts' `run_id`. The
"currently-applicable" resolution per key is the one with the greatest `sequence_index` (fail-closed
invariants I1–I6, research §22.2).

Resolutions and authorizations are **never** applied to Markdown here — `extract` / `convert`
regenerate the final Markdown from the CED (FR-079). `review` never invokes the LLM and never
edits any Markdown.

### Non-interactive sub-interface (automation / tests — explicitly secondary)

```
solari-convert review list                 [--output-dir DIR] [--json]
solari-convert review show   <ITEM_ID>     [--output-dir DIR] [--json]
solari-convert review resolve <ITEM_ID>    [--output-dir DIR] [--resolution-store PATH]
    ( --select <N>                          # literal: accept candidate N as supplied
    | --value  <TEXT>  |  --value-file PATH  # literal: enter a verified value, verbatim (FR-068/FR-082).
    #                                          --value-file is the NORMATIVE mechanism for any
    #                                          whitespace-/newline-sensitive exact literal: bytes read,
    #                                          required UTF-8, decoded, stored verbatim — no strip /
    #                                          normalization / BOM removal (research §22.5, M10)
    | --order  <segId,segId,...> )           # reading-order: exactly the item's segment set (FR-069)
    [--note <TEXT>] [--json]
solari-convert review authorize             [--output-dir DIR] [--json]   # == interactive "Continue processing"
solari-convert review status                [--output-dir DIR] [--json]   # prints run_state + counts
```

- `list` / `show <id>` — the FR-062a/FR-062d evidence + the FR-075 presentation fields.
- `resolve <id>` — validates the input (`--select` in range; `--order` exactly the item's
  segment-id set; `--value`/`--value-file` non-empty and stored **verbatim**), appends a
  `HumanReviewResolution` via atomic whole-file replace (`decision_method = human_confirmed`;
  content-bound `resolution_id`; `sequence_index = max(existing)+1`; `supersedes` = the
  currently-applicable prior record's `resolution_id` for this key or `null`; entered ⇒
  `manually_verified: true`), marks the item `resolved`. Exit **2** on bad input. Re-resolving an
  already-`resolved` item is allowed and appends a superseding record.
- `authorize` — **appends** an authorization event (`authorized_run_id = current run_id`,
  `authorized_via: cli_authorize`) to `<base>.review-authorizations.jsonl`. **Requires zero `open`
  items** — exit **6** otherwise. Validity is exactly `authorized_run_id == current run_id`, so it
  cannot authorize a stale decision set; an unchanged re-authorization is an idempotent no-op append.
- `status` — `run_state` (`unresolved` / `resolved_unauthorized` / `authorized` / `delivered` /
  `delivery_blocked_verification_failed`) + `{open, resolved, applicable, verified, failed}`.

This sub-interface obeys **identical** safety rules — exact-literal capture, append-only store,
order = exact segment set, no Markdown patching, `run_id`-keyed authorization, location-aware
verification at delivery — because those properties are enforced in the core, not the UI. It
**cannot** weaken any FR-074–FR-084 rule.

**Acceptance mapping**: US1 scenarios 8, 10–18; US3 scenario 7 (routed items); US5 scenario 6.
