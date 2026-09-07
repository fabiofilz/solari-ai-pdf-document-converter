# CLI Contract: `solari-convert`

Console script `solari-convert` (module `solari_converter.cli`). One source PDF per invocation.
All operations are local; `validate`, `fix`, and `convert` require a reachable local LLM.

## Global conventions

- **Page selection** `--pages SPEC`: `SPEC` is comma-separated single pages and `a-b` ranges,
  1-based physical pages, e.g. `2,5-7,10-12`. Omitted ⇒ whole document. Invalid spec
  (non-numeric, `start>end`, out of range, overlapping) ⇒ exit **2**, nothing written (FR-004).
- **Output** `--output-dir DIR` (default: `./out`): all artifacts written here with deterministic
  names (FR-053). Never the source PDF's directory unless the user points it there explicitly.
- **LLM** `--llm-base-url URL` (default `http://localhost:11434/v1`), `--llm-model NAME`
  (default from config/env `SOLARI_LLM_MODEL`). Used only by `validate` / `fix` / `convert`.
- **OCR** `--ocr-lang LANG[,LANG...]`: force OCR language(s); omitted ⇒ auto-detect per page
  (FR-027a).
- `--json`: emit a machine-readable run summary to stdout instead of prose.
- Deterministic-name collision with **different** content ⇒ exit **5**, existing file preserved,
  message names the path (FR-054). Identical content ⇒ treated as done, exit **0**.

### Exit codes

| Code | Meaning |
|---|---|
| 0 | Success (includes idempotent no-op) |
| 2 | Invalid arguments / invalid page selection |
| 3 | Source PDF unreadable — missing, encrypted, corrupted (edge cases) |
| 4 | Local LLM required but unavailable (`validate` / `fix` / `convert`) (FR-038/046, SC-012) |
| 5 | Output name collision with different content (FR-054) |
| 6 | OCR required but `tesseract` unavailable/unusable |
| 7 | Resource exhaustion / interrupted — no partial artifact left as complete (FR-058, SC-014) |

---

## `extract`

```
solari-convert extract SOURCE.pdf [--pages SPEC] [--output-dir DIR] [--ocr-lang L] [--json]
```

No LLM (FR-029/031). Produces:

| Artifact | Deterministic name |
|---|---|
| Original Markdown | `<stem>[__p<sel>].md` |
| Removal log | `<stem>[__p<sel>].removal-log.json` + `.md` |

Behaviour: page selection honored in document order (FR-005); artifacts removed + logged
(FR-006–011); lines de-wrapped and de-hyphenated (FR-013/014); headings/lists/clauses/tables
emitted explicitly (FR-017–022); pages without a text layer OCR'd and marked (FR-024–026);
multi-page tables stitched (FR-021). Original Markdown is immutable for later operations (FR-030).

**Acceptance mapping**: US1 scenarios 1–7.

---

## `validate`

```
solari-convert validate MARKDOWN.md SOURCE.pdf [--pages SPEC] [--output-dir DIR]
                        [--llm-base-url URL] [--llm-model NAME] [--json]
```

Requires a reachable LLM (probe first; exit **4** if not, no partial report — FR-038). Never
modifies `MARKDOWN.md` (FR-033; asserted by pre/post hash). Produces:

| Artifact | Deterministic name |
|---|---|
| Validation report | `<md-stem>.validation-report.json` + `.md` |

Report combines deterministic checks (FR-036) and one read-only semantic LLM pass (FR-037).
Every issue carries the six mandatory fields (FR-034, SC-005) plus the optional block where
applicable (FR-035). Gross Markdown/PDF divergence is reported, not failed silently (edge case).

**Acceptance mapping**: US2 scenarios 1–5.

---

## `fix`

```
solari-convert fix MARKDOWN.md VALIDATION_REPORT.json SOURCE.pdf [--pages SPEC]
                   [--output-dir DIR] [--llm-base-url URL] [--llm-model NAME] [--json]
```

Requires a reachable LLM (exit **4** if not — FR-046). Produces:

| Artifact | Deterministic name |
|---|---|
| Corrected Markdown | `<md-stem>.corrected.md` (original untouched — FR-041, SC-007) |
| Correction log | `<md-stem>.correction-log.json` + `.md` |
| Re-validation report | `<md-stem>.corrected.validation-report.json` + `.md` (FR-043) |

Changes only regions named in the report (FR-040, SC-006). No paraphrase/summary/rewrite —
restores source content only (FR-044). Regions that no longer exist / are ambiguous are listed
as unresolved, not misapplied (FR-045).

**Acceptance mapping**: US3 scenarios 1–6.

---

## `export`

```
solari-convert export MARKDOWN.md [--output-dir DIR] [--json]
```

No LLM (FR-049 — source Markdown unmodified; no LLM invoked). Produces:

| Artifact | Deterministic name |
|---|---|
| DOCX | `<md-stem>.docx` |

Heading levels → Word `Heading 1..9` (levels >6 via FR-017a lead-in markers), paragraphs →
`Normal`, lists → Word list styles preserving type + nesting, pipe tables and HTML `<table>`
(incl. `rowspan`/`colspan`) → Word tables with equivalent merged cells (FR-047).

**Acceptance mapping**: US4 scenarios 1–4.

---

## `convert`

```
solari-convert convert SOURCE.pdf [--pages SPEC] [--output-dir DIR] [--export]
                       [--llm-base-url URL] [--llm-model NAME] [--ocr-lang L] [--json]
```

Runs `extract` → `validate` → `export` (only with `--export`). **Never** runs `fix` (FR-051).
Requires a reachable LLM for the validate step (exit **4** — FR-038). Produces every `extract`
and `validate` artifact, the DOCX when `--export`, plus:

| Artifact | Deterministic name |
|---|---|
| Traceability record | `<stem>[__p<sel>].traceability.json` + `.md` |

Links source PDF + physical page ranges + every generated artifact (FR-052, SC-010). Zero
outbound network connections (SC-008). Same PDF + same selection ⇒ identical names + identical
Markdown (SC-009).

**Acceptance mapping**: US5 scenarios 1–5.
