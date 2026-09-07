# Quickstart & Validation Guide: Local-First PDF Document Converter

> **Rewritten 2026-09-07** for the multi-path + reconciliation + human-review architecture.
> References the [CLI contract](./contracts/cli.md) and [data model](./data-model.md) rather than
> repeating them. No implementation code.

## Prerequisites

| Requirement | Check | Needed for |
|---|---|---|
| Python 3.12+ (3.13 recommended) | `python3 --version` | everything |
| `uv` | `uv --version` | install / run |
| **Docling models** (one-time download from the documented source) | `python -c "import docling"` + first run populates the cache | extraction path A |
| **OCR engine** — `rapidocr-onnxruntime` (bundled models) **or** Tesseract 5 + language data | `--ocr-engine` + a smoke run | OCR paths / hybrid pages. **Default engine is set after the OCR benchmark (research §4)** |
| A local LLM exposing an OpenAI-compatible API (reference: Ollama with a `seed`-honouring model) | `curl -s http://localhost:11434/v1/models` | `validate`, `fix`; optional for `extract`/`convert` reconciliation |

The Docling models, OCR models/traineddata, and the LLM are the user's responsibility. Downloads
happen **before** a run (no model download during a conversion — asserted by a test). `extract`
and `export` never require the LLM; without it, `extract` produces more human-review items.

## Setup

```bash
uv sync                          # install exact-pinned deps from uv.lock
uv run solari-convert --help     # extract | validate | fix | export | convert | review
uv run python -m benchmarks.ocr.run --smoke   # confirm both OCR engines load (see OCR benchmark)
```

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

## Scenario 2 — literal disagreement → human review → resolve → resume (US1 8/11)

`tests/fixtures/conflict_literal.pdf` is engineered so path A and path B disagree on one clause's
text and reconciliation confidence is < 0.75.

```bash
uv run solari-convert extract tests/fixtures/conflict_literal.pdf --output-dir out   # exit 6
uv run solari-convert review list --output-dir out
uv run solari-convert review show <ITEM_ID> --output-dir out                          # shows each candidate value + bboxes + confidence
uv run solari-convert review resolve <ITEM_ID> --select 1 --output-dir out            # accept candidate 1 verbatim
#   or, if neither candidate is right:
uv run solari-convert review resolve <ITEM_ID> --value "the exact text from the PDF" --output-dir out
uv run solari-convert extract tests/fixtures/conflict_literal.pdf --output-dir out    # exit 0, Markdown delivered
```

**Expect**: the first run writes `out/conflict_literal.human-review-queue.json`+`.md` and **no**
`.md` (exit 6, FR-072). `review resolve` appends a line to `out/../resolutions.jsonl`
(`decision_method: human_confirmed`; `--value` ⇒ `manually_verified: true`) and marks the queue
item `resolved`. The re-run replays the resolution (`reconciliation-log` decision shows
`method: human_confirmed`, `replayed: true`), completes the Markdown **without any hand-editing**,
and a third identical run is a byte-identical no-op. Changing `--ocr-confidence-threshold` between
resolve and re-run → the resolution's applicability key no longer matches → a **fresh**
HUMAN_REVIEW_REQUIRED item (FR-071, SC-030).

## Scenario 3 — reading-order conflict (US1 10, SC-022/023)

`tests/fixtures/two_column.pdf`: paths agree on the literal text but produce different reading
orders. One page's columns are geometrically unambiguous; another's are not.

```bash
uv run solari-convert extract tests/fixtures/two_column.pdf --output-dir out
```

**Expect**: the unambiguous page → `reconciliation-log` records a `reading_order` decision with
`method: deterministic_agreement`, `from: geometry`. The ambiguous page → a **reading-order**
HUMAN_REVIEW_REQUIRED item carrying `segment_ids`, each candidate order, and confidence; exit 6.
Resolve with `review resolve <id> --order seg-aa,seg-bb,seg-cc` (must be exactly that segment
set). The literal text is never rewritten or re-segmented.

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

**Expect**: `fix` applies the `disallowed_transformation` correction to
`out/agreement.deviations.corrected.md` (only that region differs; original byte-identical), and
for the `reconciliation_error` it writes/updates a `human-review-queue` item, records it under
`routed_to_review` in the correction log, and tells the user to `review resolve` then re-run
`extract`/`convert`. It never edits the Markdown for that issue.

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
DOCX, and `resolutions_applied` (any replayed). `network_egress.occurred: false`; content-derived
`run_id`; **no `generated_at`**. Under the test suite's socket guard: zero non-loopback
connections. A second identical run → byte-identical `original Markdown` + DOCX + deterministic
records; no collision. If `extract` had raised review items, `convert` would stop at the queue
(exit 6) with **no** traceability record.

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
| US1 | `extract`, `review` | FR-002..027c, FR-053/053a/054, FR-059..072; SC-001..004, SC-009, SC-013..015, SC-018, SC-020..024, SC-027..030 |
| US2 | `validate` | FR-032..038a, FR-065; SC-005, SC-012, SC-017, SC-019, SC-025 |
| US3 | `fix`, `review` | FR-039..046a, FR-045a, FR-073; SC-006, SC-007, SC-012, SC-031 |
| US4 | `export` | FR-047..049; SC-011 |
| US5 | `convert` | FR-050..058; SC-008, SC-009, SC-010, SC-016 |
