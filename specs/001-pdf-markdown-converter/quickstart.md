# Quickstart & Validation Guide: Local-First PDF Document Converter

> **Rewritten 2026-09-07** for the multi-path + reconciliation + human-review architecture.
> **Updated 2026-09-08** — `review` is now an interactive keyboard-driven terminal workflow with
> explicit downstream-processing authorization, location-aware verification, and a Human Review
> Report (Scenario 2). **Audit-remediated same day** (H1–H6 / M1–M11): a persisted `run-context`
> lets `review` recompute the current `run_id`; authorization is an append-only event log keyed
> purely to `run_id`; the render is published to `<base>.md` only after every delivery gate
> passes (staged at `intermediates/<base>.<run_id>.unverified.md` until then); `--value-file` is
> the normative exact-literal mechanism; verification failures are classed by originating stage.
> References the [CLI contract](./contracts/cli.md) and [data model](./data-model.md) and
> [research §14/§22/§25](./research.md) rather than repeating them. No implementation code.

## Prerequisites

| Requirement | Check | Needed for |
|---|---|---|
| Python 3.12+ (3.13 recommended) | `python3 --version` | everything |
| `uv` | `uv --version` | install / run |
| **Docling models** (one-time download from the documented source) | `python -c "import docling"` + first run populates the cache | extraction path A |
| **OCR engine** — **Tesseract 5** + language traineddata (`por eng spa fra ita deu`), and/or **RapidOCR** with the setup-time Latin model (below) | `--ocr-engine` + `benchmarks/ocr/models/fetch_latin_model.py` + a smoke run | OCR paths / hybrid pages. **Default engine is `tesseract`** (OCR Benchmark Gate, research §4 / `benchmarks/ocr/RESULTS.md`) |
| A local LLM exposing an OpenAI-compatible API (reference: Ollama with a `seed`-honouring model) | `curl -s http://localhost:11434/v1/models` | `validate`, `fix`; optional for `extract`/`convert` reconciliation |

The Docling models, OCR models/traineddata, and the LLM are the user's responsibility. Downloads
happen **before** a run (no model download during a conversion — asserted by a test). `extract`
and `export` never require the LLM; without it, `extract` produces more human-review items.

`review` is an **interactive keyboard-driven terminal** workflow (arrow keys + Enter; no GUI, no
browser, no web server) — it needs an interactive terminal (a TTY). The non-interactive
`review list | show | resolve | authorize | status` sub-interface covers automation and CI.

## Setup

```bash
uv sync                          # install exact-pinned deps from uv.lock
uv run solari-convert --help     # extract | validate | fix | export | convert | review

# RapidOCR v1 Latin recognition model + dictionary — setup-time acquisition only.
# Downloads two files from the official RapidAI/RapidOCR ModelScope repo into
# benchmarks/ocr/models/ and verifies them against the pinned SHA256SUMS.
uv run python benchmarks/ocr/models/fetch_latin_model.py

uv run python -m benchmarks.ocr.run --smoke   # confirm both OCR engines load
```

### OCR engine bootstrap (clean clone)

| Engine | What a clean clone needs | If missing |
|---|---|---|
| **Tesseract 5** (default) | the `tesseract` binary + `por eng spa fra ita deu` traineddata installed on the system | `extract`/benchmark still run with `--ocr-engine tesseract`; a missing *required* traineddata raises `OcrUnavailable` (exit 8) |
| **RapidOCR** | run `benchmarks/ocr/models/fetch_latin_model.py` once — it fetches `latin_PP-OCRv3_rec_infer.onnx` + `latin_dict.txt` (SHA256-pinned) into `benchmarks/ocr/models/` | `RapidOcrEngine.is_available()` is `False` and any use raises `OcrUnavailable` — it **never** falls back to `rapidocr-onnxruntime`'s bundled Chinese recognition model |

- The model/dictionary binaries are **intentionally not committed** to Git
  (`benchmarks/ocr/models/.gitignore`); `README.md`, `SHA256SUMS`, and
  `fetch_latin_model.py` in that directory are the tracked reproducibility record.
- Acquisition verifies the pinned SHA256 values; a mismatch is a hard error.
- The document-processing runtime **never** downloads a model — `RapidOcrEngine`
  re-verifies the two digests before every RapidOCR init and fails closed on any
  mismatch.
- **The full two-engine OCR Benchmark Gate** (`uv run python -m benchmarks.ocr.run`,
  no `--smoke`) requires **both** Tesseract (with traineddata) **and** the fetched
  RapidOCR Latin model. With only one engine available it refuses `--smoke`
  (`FAIL: expected 2 engines`) rather than reporting a valid gate; the RapidOCR
  guard tests `SKIP` with a stated reason.

## Scenario 1 — `extract`, paths agree (US1)

```bash
uv run solari-convert extract tests/fixtures/agreement.pdf --pages 2,5-7,10-12 --output-dir out
```

**Expect** in `out/intermediates/`: `agreement__p2_5-7_10-12.candidate.docling.json`,
`.candidate.pdfplumber.json`, `.candidate.ocr.json` (if any OCR ran), `.canonical.json`,
`.reconciliation-log.json`+`.md` (mostly `deterministic_agreement`).

**Expect** in `out/`: `agreement__p2_5-7_10-12.md` (headings, lists, multi-page table stitched,
running header/footer/page-numbers removed, hyphenation repaired, accepted reading order preserved)
and `.removal-log.json`+`.md`. Re-running the exact command → **byte-identical** `.md` and records,
exit 0. Records contain **no `generated_at`**; each carries a 16-hex `run_id`.

## Scenario 2 — literal disagreement → interactive review → authorize → verified delivery (US1 8/11–18)

`tests/fixtures/conflict_literal.pdf` is engineered so path A and path B disagree on one clause's
text and reconciliation confidence is < 0.75.

```bash
uv run solari-convert extract tests/fixtures/conflict_literal.pdf --output-dir out   # exit 6, run_state=unresolved

# Normal path — interactive terminal (FR-074): Up/Down/Enter to pick a candidate, or
# choose "Enter another value…" and type the exact PDF text; the answer is saved
# immediately. After the last item you get: Review answers / Continue processing / Save and exit.
uv run solari-convert review --output-dir out

uv run solari-convert extract tests/fixtures/conflict_literal.pdf --output-dir out    # exit 0 → run_state=delivered
```

Automation / test equivalent (secondary sub-interface — same safety rules):

```bash
uv run solari-convert review resolve <ITEM_ID> --select 1 --output-dir out            # candidate 1 verbatim
#   or, if neither candidate is right (stored EXACTLY as typed — no normalization):
uv run solari-convert review resolve <ITEM_ID> --value "the exact text from the PDF" --output-dir out
#   for a whitespace-/newline-sensitive exact literal, --value-file is the NORMATIVE mechanism
#   (bytes read, required UTF-8, decoded, stored verbatim — no strip / normalization / BOM):
uv run solari-convert review resolve <ITEM_ID> --value-file ./exact_clause.txt --output-dir out
uv run solari-convert review authorize --output-dir out                               # == "Continue processing"
uv run solari-convert extract tests/fixtures/conflict_literal.pdf --output-dir out
```

**Expect**:
- The first run writes `out/conflict_literal.human-review-queue.json`+`.md` (`run_state:
  unresolved`), `out/conflict_literal.run-context.json` (the extract-stage effective-input tuple
  so `review` can recompute the current `run_id` — research §14 / H3), and **no**
  `out/conflict_literal.md` — exit 6, FR-072.
- Each confirmed answer appends a line to `out/../resolutions.jsonl` (`decision_method:
  human_confirmed`; `resolution_id` / `sequence_index` / `supersedes: null`; `--value` ⇒
  `mode: entered`, `manually_verified: true`, value **verbatim**) **before** the next item is
  shown; a Ctrl+C here still leaves those answers saved (SC-032).
- Resolving the last item does **not** deliver — the run is `resolved_unauthorized` (exit 6). Only
  choosing **Continue processing** (or `review authorize`) **appends** a line to the append-only
  event log `out/conflict_literal.review-authorizations.jsonl` for the current `run_id` (FR-077,
  M4). Authorization validity is exactly `authorized_run_id == current run_id` — there is no
  queue-file hash (M2); re-authorizing an unchanged decision set is an idempotent no-op append.
- The authorized re-run replays the currently-applicable resolution, regenerates the Markdown from
  the CED (`reconciliation-log` decision → `method: human_confirmed`, `replayed: true`) to
  `intermediates/conflict_literal.<run_id>.unverified.md`, runs the built-in stage-4 self-check,
  then runs **location-aware verification** (research §25): the human-confirmed value must appear
  **exactly** at the reviewed segment's rendered span — not just somewhere in the file — after
  re-applying only the recorded closed-enum `segment_transforms` chain. It writes
  `out/conflict_literal_review_report.md` (+ `intermediates/…human-review-verification.json`) with
  the summary counts, the literal final-Markdown excerpt, and `APPLIED AND VERIFIED`. Only after
  every gate passes is the staged Markdown atomically published to `out/conflict_literal.md` —
  exit 0, `run_state: delivered`.
- A third identical run is a byte-identical no-op (the Human Review Report is deterministic too).
- **Reopen & change** (`review` → *Review answers* → pick the entry → new value): appends a
  **superseding** record (`supersedes` set to the currently-applicable prior `resolution_id`,
  which is retained; `sequence_index` is the authority for "current" — I1–I6), the decision set
  and `run_id` change → no authorization event matches the new `run_id` → the run is
  `resolved_unauthorized` again and must be re-authorized before delivery (FR-076/FR-077, SC-033).
- **Verification failure** (fixture where a stage-3 bug drops a space inside the confirmed value):
  the Markdown exists **only** at `intermediates/conflict_literal.<run_id>.unverified.md` — never
  at `out/conflict_literal.md` — and the run is `delivery_blocked_verification_failed` (exit 6);
  the report shows `NOT APPLIED — VERIFICATION FAILED (literal_altered)` with the actual excerpt,
  and a validation issue (with `review_item_id`) classed `disallowed_transformation` — the CED is
  correct, stage 3 broke it — routes to a code fix + re-verification (or `fix` + mandatory
  re-verification). A fixture where reconciliation never carried the decision is classed
  `reconciliation_error` and routes back through `review` (SC-036 / H5).
- Changing `--ocr-confidence-threshold` between resolve and re-run → the resolution's applicability
  key no longer matches → a **fresh** HUMAN_REVIEW_REQUIRED item, not a silent replay (FR-071,
  SC-030).

## Scenario 3 — reading-order conflict (US1 10, SC-022/023)

`tests/fixtures/two_column.pdf`: paths agree on the literal text but produce different reading
orders. One page's columns are geometrically unambiguous; another's are not.

```bash
uv run solari-convert extract tests/fixtures/two_column.pdf --output-dir out
```

**Expect**: the unambiguous page → `reconciliation-log` records a `reading_order` decision with
`method: deterministic_agreement`, `from: geometry`. The ambiguous page → a **reading-order**
HUMAN_REVIEW_REQUIRED item carrying `segment_ids`, each candidate order, and confidence; exit 6.
In `review` the reviewer builds the order by picking the existing segments one at a time (no
literal editing is possible); or `review resolve <id> --order seg-aa,seg-bb,seg-cc` (must be
exactly that segment set). All the human-review rules that apply to a literal decision apply here
too — immediate save, resume, reopen/change, explicit authorization, location-aware verification
(the reviewed segments must render in the confirmed order — `order_not_reflected` otherwise), and
Human Review Report inclusion.

## Scenario 4 — OCR image page + hybrid page (US1 6/6a, SC-013/014)

`tests/fixtures/scanned.pdf` (image-only page) and `tests/fixtures/hybrid.pdf` (reliable native
text + one image-only region).

```bash
uv run solari-convert extract tests/fixtures/hybrid.pdf --ocr-engine <engine> --output-dir out
```

> Any installed OCR engine may be selected explicitly with `--ocr-engine`. The **default** engine
> is chosen only after the OCR benchmark (research §4); until then, pass one explicitly. This
> example does not imply any engine has been selected.

**Expect**: the image region is OCR'd and marked OCR-derived; the reliable native text is kept
verbatim (reconciliation selects native for those regions); the page's `class` in `.canonical.json`
is `hybrid_native_and_ocr`. `.candidate.ocr.json` records the per-region OCR record with the
detected language and the effective confidence threshold (normalized 0–100).

## Scenario 5 — `validate` defect classes (US2)

`tests/fixtures/agreement.deviations.md` seeds: one altered table number (extraction fault), one
flattened heading (transformation fault), one wrong reconciliation choice.

```bash
uv run solari-convert validate tests/fixtures/agreement.deviations.md tests/fixtures/agreement.pdf \
  --pages 2,5-7,10-12 --output-dir out
```

**Expect** `out/agreement.deviations.validation-report.json`+`.md`: the altered number →
`defect_class: extraction_error`; the flattened heading → `disallowed_transformation`; the wrong
reconciliation → `reconciliation_error` with a `reconciliation_ref`. `compared_against` shows
`original_pdf: true, extraction_evidence: true, reconciliation_provenance: true`. Every issue has
the six mandatory fields + `defect_class` (SC-005). Input `.md` sha256 identical before/after.
`llm.reproducibility` is `deterministic` with a `seed`-honouring backend (then the semantic
section is byte-identical across two runs) or `best_effort` otherwise (then a second run replays
the persisted semantic section — no regeneration, no collision — FR-053b). The deterministic
section + `summary` are always byte-identical (FR-053a). With the LLM stopped → exit 4, no report
(FR-038); with an unrelated Markdown → `gross_divergence` summary, no LLM needed (SC-017).

## Scenario 6 — `fix` routes a `reconciliation_error` (US3 7, SC-031)

```bash
uv run solari-convert fix tests/fixtures/agreement.deviations.md \
  out/agreement.deviations.validation-report.json tests/fixtures/agreement.pdf --output-dir out
```

**Expect**: `fix` applies a `disallowed_transformation` correction to
`out/agreement.deviations.corrected.md` (only that region differs; original byte-identical) — and
when the issue carries a `review_item_id` (a human-review **verification failure**), the corrected
Markdown **MUST re-enter §25 location-aware verification** against the applicable decisions before
it counts as a successful delivery (research §22.7). For a `reconciliation_error` issue `fix` does
**not** patch the Markdown: it writes/updates a `human-review-queue` item, records it under
`routed_to_review` in the correction log, and tells the user to re-decide via `review`, then
**re-authorize**, then re-run `extract`/`convert`. `fix` branches on `defect_class` and never
invents or applies a decision (FR-079).

## Scenario 7 — `export` (US4, SC-011)

```bash
uv run solari-convert export out/agreement__p2_5-7_10-12.md --output-dir out
```

**Expect** `out/agreement__p2_5-7_10-12.docx`: `Heading 1..N` styles, Word list styles with
nesting, Word tables with merged cells for HTML `<table>` spans, deep `[L{n}]` → `Heading 7..9`.
Source `.md` unchanged; no LLM. Two `export` runs → byte-identical `.docx` (fixed core props +
normalized zip timestamps).

## Scenario 8 — `convert` with traceability, no egress, reproducible (US5, SC-008/009/010)

```bash
uv run solari-convert convert tests/fixtures/agreement.pdf --pages 2,5-7 --export --output-dir out
```

**Expect**: all `extract` + `validate` artifacts + `out/agreement__p2_5-7.docx` +
`out/agreement__p2_5-7.traceability.json`+`.md`. The traceability record links the source PDF,
`physical_page_ranges [[2,2],[5,7]]`, the **extraction candidates**, the **canonical extracted
document**, the **reconciliation log**, the Markdown, the removal log, the validation report, the
`run-context`, the DOCX, `resolutions_applied` (any replayed, with content-bound `resolution_id`),
and — when the run had an applicable human-review decision — the `review_authorizations` event
log, the `<base>_review_report.md`, the `human-review-verification` record, and a required
`human_review_verification` summary (`status: PASS` — a FAIL blocks delivery, so no traceability
record). `network_egress.occurred: false`; content-derived `run_id`; **no `generated_at`**. Under the test suite's socket guard: zero non-loopback connections. A second
identical run → byte-identical `original Markdown` + DOCX + deterministic records (incl. the Human
Review Report); no collision. If `extract` had **not** reached `run_state: delivered` (open items,
resolved-but-unauthorized, or a verification failure), `convert` would stop (exit 6) with **no**
traceability record.

## Automated validation

```bash
uv run pytest -q                              # full default suite
uv run pytest -q tests/contract               # JSON-Schema conformance per record + CLI contract
uv run pytest -q tests/integration            # per user story + reconciliation + human-review + resume
uv run pytest -q -m acceptance                # corpus scoring (SC-002/003), reproducibility corpus,
                                              #   real long-form sample, OCR benchmark smoke
uv run python -m benchmarks.ocr.run           # full OCR fidelity benchmark → benchmarks/ocr/RESULTS.md
```

- `tests/conftest.py` blocks non-loopback sockets and asserts no model download during a run.
- The OCR benchmark decides the default `--ocr-engine`; until `benchmarks/ocr/RESULTS.md` records
  a winner, `--ocr-engine` must be passed explicitly.

## Requirement coverage checklist

| Story | Command(s) | Key FR / SC proven |
|---|---|---|
| US1 | `extract`, `review` (interactive) | FR-002..027c, FR-053/053a/054, FR-059..084; SC-001..004, SC-009, SC-013..015, SC-018, SC-020..024, SC-027..036 |
| US2 | `validate` | FR-032..038a, FR-065, FR-084 (verification-failure issues); SC-005, SC-012, SC-017, SC-019, SC-025 |
| US3 | `fix`, `review` | FR-039..046a, FR-045a, FR-073, FR-084; SC-006, SC-007, SC-012, SC-031, SC-036 |
| US4 | `export` | FR-047..049; SC-011 |
| US5 | `convert` | FR-050..058, FR-077/FR-080/FR-084 (delivery gate + report link); SC-008, SC-009, SC-010, SC-016, SC-034 |
