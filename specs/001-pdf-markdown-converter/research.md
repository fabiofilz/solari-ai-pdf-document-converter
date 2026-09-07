# Phase 0 Research: Local-First PDF Document Converter

All Technical Context items are resolved — no `NEEDS CLARIFICATION` remains. Each decision below
follows the Decision / Rationale / Alternatives format.

---

## 1. Language and runtime

**Decision**: Python, minimum 3.12, development and CI pinned to 3.13.

**Rationale**: The whole ecosystem this feature needs — PDF parsing, OCR bindings, DOCX writing,
schema/validation — is strongest in Python. The repo already ships a Python `.gitignore` and
`uv` is installed. 3.13 is the newest version with full wheel coverage for every dependency
below. 3.12 as the floor keeps the tool installable on current LTS-ish environments.

**Alternatives considered**:
- *Python 3.14* (installed on the dev machine): rejected as the floor — some dependencies still
  lack 3.14 wheels, which would force source builds. Revisit before release.
- *Node / TypeScript*: weaker PDF-layout and OCR story; would pull heavier native deps.
- *Go / Rust*: fastest, but PDF-structure and OCR libraries are far less mature; violates
  constitution VII (more custom code = more fidelity risk surface).

---

## 2. PDF text, layout, and table extraction

**Decision**: `pdfplumber` (MIT), which sits on `pdfminer.six`.

**Rationale**: Provides per-word bounding boxes, line grouping, font size/name/weight per
character, and a configurable table detector — exactly the primitives needed for reading-order
reconstruction (FR-015), heading-level inference (FR-017), artifact detection (FR-006..009), and
table extraction (FR-020). Pure Python, permissive license, actively maintained, widely used.

**Alternatives considered**:
- *PyMuPDF (fitz)*: fastest and excellent text/layout, **rejected because it is AGPL-3.0**, which
  is incompatible with this project's MIT license for distribution. This is the decisive factor.
- *pypdf*: good for page ops and metadata, weak on layout coordinates and has no table support.
- *pdfminer.six* directly: usable but low-level; `pdfplumber` is the ergonomic layer over it and
  adds the table finder.
- *Camelot / tabula*: strong table extraction but Camelot needs Ghostscript and tabula needs a
  JVM — both violate the minimal-dependency and no-heavy-system-dep goals. `pdfplumber`'s table
  finder is sufficient for the spec; revisit only if the acceptance corpus shows it failing.

---

## 3. Page rasterization for OCR

**Decision**: `pypdfium2` (BSD-3, Google PDFium bindings).

**Rationale**: Renders a PDF page to a raster image with no external binary (unlike
poppler-backed `pdf2image`). Prebuilt wheels for all target platforms, fast, permissive license.
Only used to feed Tesseract for pages that lack a text layer (FR-024) or mix text and image
(FR-026).

**Alternatives considered**:
- *pdf2image*: requires the poppler command-line tools installed separately — extra system
  dependency, worse portability.
- *pdfplumber's `Page.to_image()`*: depends on the same poppler/Ghostscript stack under the hood.
- *Wand / ImageMagick*: heavy native dependency; overkill for page rasterization.
- Using PyMuPDF's rasterizer: rejected with PyMuPDF itself (AGPL).

---

## 4. OCR engine

**Decision**: `pytesseract` (Apache-2.0) driving the system `tesseract` binary (v5.5.3 present on
the dev machine).

**Rationale**: The de-facto local, offline OCR engine. `pytesseract`'s `image_to_data` returns
per-word confidence, which feeds "low-confidence OCR regions surfaced during validation"
(FR-027). Supports explicit multi-language recognition via `-l lang1+lang2`. Fully local.

**Alternatives considered**:
- *EasyOCR / PaddleOCR / docTR*: pull large ML runtimes (PyTorch / Paddle) and model downloads
  on first run — a network + size + dependency cost that violates constitution VII and the
  local-first default. Tesseract's language data is a small, offline apt/brew package.
- *OCRmyPDF*: a great tool but it rewrites the PDF; this feature wants text + confidence extracted
  into the Document model, not a new PDF.

**Note**: Tesseract itself and its language packs are the user's responsibility to install (same
posture the spec takes for the local LLM). The tool detects a missing or unusable `tesseract` and
reports it clearly rather than silently skipping OCR.

---

## 5. OCR language selection

**Decision**: Auto-detect per page with `langdetect` (Apache-2.0) on a first-pass OCR sample
(fast, default English+osd pass), then re-run Tesseract with the detected language(s). Accept an
optional `--ocr-lang` per-run override (one or more languages) that skips detection. Record the
detected or overridden language(s) in the per-page OCR record (FR-027a).

**Rationale**: `langdetect` is tiny, offline, and covers the Latin-script languages the spec
requires including Portuguese. Two-pass OCR (detect, then recognize) is a well-known pattern and
keeps the common case zero-config while allowing an override for known-language documents.

**Alternatives considered**:
- *Tesseract OSD / `--psm 0`*: detects script and orientation, not specific language — not
  enough to pick `por` vs `spa`.
- *`lingua-py`*: more accurate on short text but a heavier dependency; `langdetect` is adequate
  for page-sized samples.
- *Always require the user to pass a language*: rejected — the spec wants auto-detection as the
  default (clarification 2026-09-05).

---

## 6. DOCX export

**Decision**: `python-docx` (MIT), mapping the Document model directly to Word elements.

**Rationale**: Gives explicit control over paragraph styles (`Heading 1..9`, `Normal`,
`List Bullet`, `List Number`), table creation, and — critically — cell merging via
`cell.merge()`, which is what FR-047 needs to turn HTML `<table>` `rowspan`/`colspan` into real
Word merged cells. Deeper-than-6 hierarchy levels map to `Heading 7..9` / styled list paragraphs
(FR-017a). No external binary.

**Alternatives considered**:
- *pandoc* (installed on the dev machine): converts Markdown → DOCX in one call, but style
  mapping is opinionated and merged-cell fidelity from HTML tables is unreliable. Adds a heavy
  external binary as a hard runtime dependency. Rejected for the fidelity-critical path; could be
  offered later as an optional alternative backend.
- *Building OOXML by hand*: maximum control, far too much custom code (constitution VII).

---

## 7. Audit-record models and schema (removal log, validation report, correction log, traceability)

**Decision**: `pydantic` v2 (MIT) models as the single definition of each record. JSON is the
authoritative persisted form; the human-readable Markdown rendering is generated from the same
model instance (FR-057). JSON Schemas in `contracts/` are produced from the models
(`model_json_schema()`) and checked in.

**Rationale**: One source of truth for structure + validation rules (e.g. the six mandatory
`ValidationIssue` fields, SC-005). Round-trips JSON cleanly, generates JSON Schema for the
contract tests, and gives clear errors when a record is malformed. Widely used, stable, fast
(Rust core with wheels).

**Alternatives considered**:
- *`dataclasses` + `jsonschema`*: means writing and hand-syncing schemas separately — drift risk.
- *`attrs` + `cattrs`*: capable but no built-in JSON Schema generation.
- *Plain dicts*: no validation, no schema, fails the "authoritative machine-readable" requirement.

---

## 8. Local LLM access (validate / fix semantic pass)

**Decision**: A thin `httpx` (BSD) client targeting an **OpenAI-compatible**
`POST {base_url}/v1/chat/completions`. `base_url` and model name are configurable (env var / CLI
flag / config file); default `http://localhost:11434/v1` (Ollama's OpenAI-compatible endpoint).
Before any semantic work, probe availability (a cheap `GET {base_url}/models` or a tiny
completion with a short timeout); if it fails, stop with a clear message and produce no partial
report presented as complete (FR-038/046, SC-012).

**Rationale**: The OpenAI chat-completions shape is implemented by every mainstream local runner
— Ollama, llama.cpp `server`, LM Studio, vLLM — so the tool is not locked to one. A raw HTTP
call needs no SDK, keeping the dependency count down (constitution VII). Everything stays on
`localhost`; the no-egress test still passes because loopback is allowed by the guard.

**Alternatives considered**:
- *Ollama-native API (`/api/chat`, `/api/tags`)*: slightly nicer model discovery, but ties the
  tool to Ollama specifically. Rejected in favour of the portable interface (user decision
  2026-09-07).
- *`openai` Python SDK pointed at the local URL*: works, but adds a dependency (and its
  transitive deps) purely for request shaping we can do in ~30 lines.
- *`llama-cpp-python` in-process*: embeds the model runtime and GGUF loading into this tool —
  large dependency, model-file management burden, worse separation than "user runs their own
  server".

---

## 9. CLI framework

**Decision**: stdlib `argparse` with `add_subparsers` for the five operations. Shared options
(`--pages`, `--output-dir`, `--llm-base-url`, `--llm-model`, `--ocr-lang`) are factored into
helper functions that add them to each subparser.

**Rationale**: Zero dependencies — the strictest reading of constitution VII. Five subcommands
with a handful of options each is well within argparse's comfortable range. Exit codes and
`--help` text are fully controllable.

**Alternatives considered**:
- *Typer / Click*: nicer ergonomics and less boilerplate, but each adds a dependency for what
  argparse already does here. Rejected (user decision 2026-09-07).
- *docopt*: unmaintained.

---

## 10. Deterministic output naming and collision policy

**Decision**: `<source-stem>[__p<selector>].<ext>`. `<selector>` is the normalized page
selection with `,`→`_` and ranges kept as `a-b` (e.g. `2_5-7_10-12`); whole-document runs omit
the token entirely. Records derive from the same base:
`<base>.removal-log.json` / `.md`, `.validation-report.json` / `.md`, `.correction-log.json` /
`.md`, `.traceability.json` / `.md`; corrected Markdown is `<base>.corrected.md`.

Collision handling: if the target path already exists **with byte-identical content**, treat the
write as a satisfied no-op (keeps repeated `convert` runs idempotent, SC-009). If it exists with
**different** content, write nothing for that output, leave the existing file untouched, and stop
the operation with a message naming the collided path and the reason (US1 scenario 7, FR-054).
No numeric-suffix bump, no sidecar file — either would break the deterministic-name guarantee.

**Rationale**: A pure function of (filename, page selection) satisfies FR-053 and SC-009. The
abort-on-conflict rule is the most reversible option and the least surprising: the user's
existing work is never touched and they are told exactly what happened.

**Alternatives considered**:
- *Numeric suffixes* (`name.1.md`): never blocks but produces non-deterministic names and clutter.
- *Sidecar `name.conflict-<hash>.md`*: nothing lost, but the output path is no longer
  deterministic on collision and downstream traceability gets messier.
- *Overwrite when "probably regenerated"*: violates FR-054 outright.

---

## 11. Atomic writes and clean failure

**Decision**: Every artifact is written to a temporary file in the destination directory and
`os.replace()`-d into place only after it is fully written and (for JSON records) re-parsed to
confirm validity. On any mid-run failure — including resource exhaustion — no partially written
file is left at a final artifact path, and the traceability record is written last so it never
references an incomplete artifact (SC-014, FR-058).

**Rationale**: `os.replace` is atomic on POSIX and Windows within the same filesystem. Writing
the temp file in the *destination* directory (not `/tmp`) keeps the rename on one filesystem and
keeps document content inside the project-controlled working area (constitution "Technology &
Security Constraints").

**Alternatives considered**:
- *Write directly to the final path*: a crash leaves a truncated file that looks complete.
- *`tempfile` in the system temp dir*: cross-filesystem rename falls back to copy (non-atomic),
  and briefly writes document content outside the working directory.

---

## 12. No-network-egress enforcement (test strategy)

**Decision**: An autouse `pytest` fixture replaces `socket.socket.connect` with a guard that
raises on any non-loopback address for the whole default-path test suite. The fake local-LLM
server binds `127.0.0.1` so `validate` / `fix` tests still exercise the HTTP client. One
explicit test asserts a full `convert` run makes zero non-loopback connections (SC-008).

**Rationale**: Turns "local-first" from a claim into a regression-guarded property (constitution
V), without needing a network namespace or firewall in CI.

**Alternatives considered**:
- *Inspecting `/proc/net` or `lsof`*: platform-specific and racy.
- *Trusting code review*: not a guarantee.

---

## 13. Test fixtures

**Decision**: Build tiny PDFs at test time with `reportlab` (BSD, dev-only) — one per structural
concern (headings at several levels, nested lists, a multi-page table with a repeated header
row, a running header/footer + page number, a merged-cell table, an image-only page for OCR).
Seeded-deviation Markdown files for `validate`/`fix` tests are committed as small text files.

**Rationale**: Keeps the repo free of opaque binary fixtures, makes each fixture's intent
readable in code, and lets tests assert against known ground truth. The one real-world sample
(`Convencao_MARQUEZ_REGISTRADA_1.pdf`, already in the repo) is used only in slow/optional
acceptance-corpus tests, not the default suite.

**Alternatives considered**:
- *Commit hand-made PDFs*: intent is invisible, diffs are meaningless, licensing of sample
  content is murky.
- *Generate with the tool itself*: circular — fixtures must be independent of the code under test.

---

## Outstanding items for Phase 1

None blocking. Phase 1 refines: the exact `ValidationIssue` field set and enum values, the
heading-level inference algorithm's thresholds, and the multi-page table stitching heuristics —
all captured in `data-model.md` and the contract schemas.
