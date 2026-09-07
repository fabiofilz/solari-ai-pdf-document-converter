# Quickstart & Validation Guide: Local-First PDF Document Converter

This guide proves the feature end to end. It references the [CLI contract](./contracts/cli.md)
and [data model](./data-model.md) rather than repeating them. It contains no implementation code.

## Prerequisites

| Requirement | Check | Needed for |
|---|---|---|
| Python 3.12+ (3.13 recommended) | `python3 --version` | everything |
| `uv` | `uv --version` | install / run |
| Tesseract 5.x + language data | `tesseract --version` | OCR paths (`extract`/`convert` on scanned pages) |
| A local LLM exposing an OpenAI-compatible API | `curl -s http://localhost:11434/v1/models` | `validate`, `fix`, `convert` |

The local LLM and Tesseract language packs are the user's responsibility (spec Assumptions).
`extract` and `export` work without an LLM.

## Setup

```bash
uv sync                      # install exact-pinned deps from uv.lock
uv run solari-convert --help # lists: extract, validate, fix, export, convert
```

## Scenario 1 — `extract` a page selection (US1)

```bash
uv run solari-convert extract tests/fixtures/agreement.pdf --pages 2,5-7,10-12 --output-dir out
```

**Expect** in `out/`:
- `agreement__p2_5-7_10-12.md` — only those physical pages, in order; headings as `#`-levels,
  lists as Markdown lists, multi-page table as one pipe/HTML table, running header/footer and
  page numbers absent, hyphenated line breaks rejoined.
- `agreement__p2_5-7_10-12.removal-log.json` + `.md` — every stripped element with its source
  page ([schema](./contracts/removal-log.schema.json)).
- Re-running the exact command → identical filenames, identical Markdown bytes (SC-009).
- Running it again after editing the `.md` by hand → exit 5, existing file preserved (FR-054).

**Scanned-page check**: `tests/fixtures/scanned.pdf` (image-only page) → its text present in the
Markdown, marked OCR-derived; a `PageOcrRecord` with detected language (SC-013, FR-025).

## Scenario 2 — `validate` against seeded deviations (US2)

`tests/fixtures/agreement.deviations.md` is a copy of a good extraction with known errors seeded
(one altered table number, one heading flattened to a paragraph).

```bash
uv run solari-convert validate tests/fixtures/agreement.deviations.md \
  tests/fixtures/agreement.pdf --pages 2,5-7,10-12 --output-dir out
```

**Expect**:
- `out/agreement.deviations.validation-report.json` + `.md`
  ([schema](./contracts/validation-report.schema.json)).
- The numeric change → an issue with `issue_type: numeric_mismatch`, all six mandatory fields,
  plus `expected` / `found` / `suggested_action` (SC-005).
- The flattened heading → an issue with `issue_type: heading_level`.
- `sha256` of the input `.md` identical before and after the run (FR-033, asserted).
- With the LLM stopped: exit 4, message says a local LLM is required, **no** report file written
  (FR-038, SC-012).

## Scenario 3 — `fix` only the flagged regions (US3)

```bash
uv run solari-convert fix tests/fixtures/agreement.deviations.md \
  out/agreement.deviations.validation-report.json tests/fixtures/agreement.pdf --output-dir out
```

**Expect**:
- `out/agreement.deviations.corrected.md` — new file; `diff` vs the original shows changes
  **only** inside regions named in the report (SC-006).
- `tests/fixtures/agreement.deviations.md` byte-identical to its pre-run state (SC-007).
- `out/agreement.deviations.correction-log.json` + `.md` — one entry per applied change linking
  back to its `resolves_issue_id` ([schema](./contracts/correction-log.schema.json)).
- `out/agreement.deviations.corrected.validation-report.json` — re-validation ran (FR-043).
- A report issue pointing at a now-nonexistent region → listed under `unresolved`, not misapplied
  (FR-045).

## Scenario 4 — `export` to DOCX (US4)

```bash
uv run solari-convert export out/agreement__p2_5-7_10-12.md --output-dir out
```

**Expect** `out/agreement__p2_5-7_10-12.docx`: heading levels carry `Heading 1..N` styles, lists
use Word list styles with nesting preserved, the table is a Word table with the same rows/cols
and merged cells matching any HTML `<table>` spans (FR-047, SC-011). Source `.md` unchanged; no
LLM contacted (FR-049).

## Scenario 5 — `convert` with full traceability, no egress (US5)

```bash
uv run solari-convert convert tests/fixtures/agreement.pdf --pages 2,5-7 --export --output-dir out
```

**Expect**:
- All `extract` + `validate` artifacts, plus `out/agreement__p2_5-7.docx`.
- `out/agreement__p2_5-7.traceability.json` + `.md`
  ([schema](./contracts/traceability-record.schema.json)): links source PDF (name + sha256),
  `physical_page_ranges` `[[2,3],[5,7]]`, and every artifact by path + sha256 + deterministic
  name; `network_egress.occurred: false`.
- No `fix` output produced (FR-051).
- Under the test suite's socket guard: zero non-loopback connections (SC-008).
- Re-run → identical names and Markdown (SC-009).

## Automated validation

```bash
uv run pytest -q                    # full suite
uv run pytest -q tests/contract     # 4 JSON-Schema conformance + CLI contract
uv run pytest -q tests/integration  # one module per user story US1..US5
```

- `tests/conftest.py` blocks non-loopback sockets for the whole default suite.
- Slow acceptance-corpus tests (real `Convencao_MARQUEZ_REGISTRADA_1.pdf`) run only under
  `-m acceptance`.

## Requirement coverage checklist

| Story | Command | Key SC / FR proven |
|---|---|---|
| US1 | `extract` | FR-002..022, FR-024..026, FR-053/054; SC-001..004, SC-009, SC-013 |
| US2 | `validate` | FR-032..038; SC-005, SC-012 |
| US3 | `fix` | FR-039..046; SC-006, SC-007, SC-012 |
| US4 | `export` | FR-047..049; SC-011 |
| US5 | `convert` | FR-050..052, FR-055..057; SC-008, SC-009, SC-010, SC-014 |
