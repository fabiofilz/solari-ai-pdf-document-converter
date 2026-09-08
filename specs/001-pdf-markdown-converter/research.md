# Phase 0 Research: Local-First PDF Document Converter

Each decision below follows the Decision / Rationale / Alternatives format.

**Refreshed 2026-09-07 for Constitution v2.0.0 and the multi-path architecture.**
The spec now describes independent extraction paths → reconciliation → semantic
transformation → final fidelity validation, with a human-review workflow. Sections
2–13 predate that model; each has been re-framed against v2.0.0 ("Simplicity &
Justified Dependencies" — dependency count is not an objective) and against the
current spec. Sections 20–23 are new (Docling, reconciliation design, human-review
workflow, artifact persistence).

**Open items requiring evidence or a later decision:**
- **§4 — OCR engine** (Tesseract 5 vs RapidOCR/PP-OCR): **RESOLVED (corrected benchmark, 2026-09-07)** → **Tesseract 5** is the single global default. The corrected T013 run gives RapidOCR its multilingual **Latin** recognition model and scores PT/EN/ES separately; Tesseract clears the §4.1 per-language acceptance floor for all three, RapidOCR is materially worse for all three. Evidence: `benchmarks/ocr/RESULTS.md`.
- **§5 — OCR language detector** (langdetect vs lingua-py vs engine-native): **RESOLVED (corrected benchmark, 2026-09-07)** → **lingua** is the default (1.000 across PT/EN/ES), `langdetect` (seed-pinned) the fallback. Re-derived from the PT/EN/ES corpus in the corrected T013 run.
- **§4a — LLM backend determinism**: strategy defined; the specific local backend's bit-reproducibility is confirmed at implementation time.
- **§16 — Camelot/tabula for tables**: decide on measured multi-page-table fidelity vs the in-house stitcher.

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

## 2. Extraction path B — pdfplumber + pypdfium2 (independent geometric / evidence path)

**Decision**: `pdfplumber` (MIT, on `pdfminer.six`) is **extraction path B** (FR-060): an
independent candidate carrying per-word literal text, exact bounding boxes, font metrics, a
configurable table detector, and a purely geometric candidate reading order. `pypdfium2` (§3)
supplies page dimensions / rotation and rasterization for path C.

**Rationale**: Path B is the **deterministic geometric ground truth** of the pipeline. It is what
reading-order reconciliation (FR-061d) uses to resolve orderings without the LLM, and what
segment alignment (§21) uses to match segments across candidates. It is pure-Python, has no
native surprises, and every value it produces is a plain coordinate — maximally diagnosable. It
does not need to be the *best* extractor; it needs to be *independent, deterministic, and
geometrically exact*, which it is.

**Alternatives considered**:
- *PyMuPDF (fitz)*: excellent, but **AGPL-3.0** — incompatible with this project's MIT license for
  distribution. Decisive; unaffected by Constitution v2.0.0 (licensing is outside Principle VII).
- *pypdf*: weak on layout coordinates, no table support — insufficient for a geometric evidence path.
- *pdfminer.six directly*: `pdfplumber` is the ergonomic layer over it and adds the table finder.
- Docling as the only extractor: rejected by the architecture — paths must be independent so one
  technique's error cannot propagate (FR-060). Docling is **path A** (§20), not a replacement for B.

**Note on Constitution v2.0.0**: path B is retained on its **role fit** (independent, deterministic,
geometric), not because it is "lightweight". Weight is not the argument in either direction here.

---

## 3. Page rasterization for OCR

**Decision**: `pypdfium2` (BSD-3, Google PDFium bindings).

**Rationale**: Renders a PDF page to a raster image with no external binary (unlike
poppler-backed `pdf2image`). Prebuilt wheels for all target platforms, fast, permissive license.
Only used to feed the OCR engine (§4) for pages or regions that lack reliable native text
(FR-024) or mix text and image (FR-026).

**Constitution v2.0.0 framing**: the choice is about **capability and operational surface**, not
"lighter wins". `pypdfium2` renders faithfully, handles rotation, ships wheels for all target
platforms, and needs **no system binary** — so it adds no install-time failure mode and no
platform matrix to chase. That is the reason, independent of size.

**Alternatives considered**:
- *pdf2image / pdfplumber `Page.to_image()`*: both need the **poppler** CLI installed separately —
  a real operational failure mode (missing binary, version skew), not merely "heavier".
- *Wand / ImageMagick*: adds a large native dependency **and** a security-relevant image decoder
  surface, for a task pypdfium2 already covers.
- *PyMuPDF's rasterizer*: rejected with PyMuPDF itself (AGPL).

---

## 4. OCR engine

> **SUPERSEDED — Constitution v2.0.0 (2026-09-07).** The prior decision (below) chose
> `pytesseract`/Tesseract and rejected EasyOCR/PaddleOCR/docTR *primarily* because neural OCR
> engines "pull large ML runtimes … a network + size + dependency cost that violates constitution
> VII." Under the amended Principle VII ("Simplicity & Justified Dependencies"), runtime weight,
> model size, and dependency count are **not** valid primary reasons to reject an OCR engine, and
> the product objective is **maximum practical conversion fidelity**. The OCR engine choice is
> re-opened and MUST be settled by a fidelity benchmark. No winner is chosen here.

### 4.0 Prior decision (superseded — retained for history)

`pytesseract` (Apache-2.0) driving the system `tesseract` binary. EasyOCR / PaddleOCR / docTR
were rejected for ML-runtime weight and first-run model downloads — **that rationale is no longer
valid**. `pytesseract.image_to_data` returning per-word confidence, and `-l lang1+lang2`
multi-language support, remain useful properties but are no longer decisive.

### 4.1 New decision: benchmark-gated OCR engine selection

**Decision**: The default OCR engine MUST NOT be selected primarily on dependency count, runtime
size, or model size. It MUST be selected primarily on **measured extraction fidelity for the
target document corpus**, via a technical evaluation that at minimum compares:

- **Tesseract 5**
- **RapidOCR** with an appropriate current PP-OCR model

Other fully-local OCR engines MAY be added to the comparison where there is credible evidence
they could materially improve fidelity.

**Language scope (v1, spec Clarifications 2026-09-07).** The benchmark evaluates **Latin-script
Western languages**. **Primary benchmark languages: Portuguese, English, Spanish** — each is a
scored dimension with its own corpus pages. **French, Italian, German** are Latin-script
**compatibility / character-coverage** targets only (one `latin_coverage` page: representative
`à â ç é è ê ë î ï ô û ù ü œ ß ä ö à è é ì ò ù` and tokens such as `français`, `Straße`, `città`)
— not scored language dimensions. **CJK and other non-Latin systems are out of scope for v1**;
the benchmark does not include them.

**Evaluation corpus** — MUST include representative difficult cases across the primary languages:
accents / diacritics (PT: `ã â ê õ ç`; ES: `ñ ¿ ¡ ü`); small text; numeric and monetary values
(`R$`, `€`, `%`); tables; degraded / scanned pages; image-only pages; mixed / hybrid PDF pages
where applicable; and layouts representative of the project's target PDFs. Structural / degraded /
table fixtures are **not** duplicated in every language — Portuguese carries the deepest category
matrix; English and Spanish add language-validation pages (`en_text_01`, `es_diacritics_01`,
`es_numeric_01`).

**Benchmark criteria** — fidelity, not merely "text was returned":
character / text accuracy; preservation of numeric values; diacritic accuracy **for each primary
language**; table / cell text accuracy; reading-order behavior where applicable; behavior on
degraded scans; false insertion and omission of content.

**Per-language acceptance floor (v1) — AUTHORITATIVE.** This is the single normative definition;
`tasks.md` (T011/T012/T013) references it and MUST NOT restate the numbers. These are **OCR
benchmark engine-selection floors** — they are *not* a replacement for the converter's own
acceptance criteria (`spec.md` Success Criteria, T124, or the final fidelity-validation
pipeline). For **each** primary benchmark language (Portuguese, English, Spanish), an OCR engine
is **acceptable for that language** only if **every applicable** criterion below passes on that
language's slice:

| # | Criterion | Threshold | Applicability |
|---|---|---|---|
| 1 | per-language weighted fidelity | `weighted_total >= 0.80` | always (every primary language) |
| 2 | character error rate | `CER <= 0.20` | always (every primary language) |
| 3 | diacritic accuracy | `diacritic_accuracy >= 0.90` | only slices/pages carrying the representative diacritic ground-truth set — **required gate for Portuguese and Spanish**; **not** applied to an English slice with no applicable diacritic ground truth (do not fabricate one) |
| 4 | numeric-token fidelity | `numeric_token_exact_match >= 0.95` | only slices/pages carrying numeric or monetary ground-truth tokens |

"**Materially worse for a supported primary language**" is defined **operationally and
absolutely**: the engine **fails one or more applicable per-language acceptance-floor criteria
(1–4 above) for that primary language**. It is **not** defined relative to the competing engine —
no absolute score difference vs. the other engine, no percentage difference vs. the other engine;
an engine does **not** become acceptable merely because the competing engine also performs badly.

**Selection rule (engine-selection procedure):**
1. Compute **aggregate** weighted fidelity for each engine.
2. Compute **per-language** metrics for Portuguese / English / Spanish.
3. Determine **PASS/FAIL** for each engine×language using the **absolute** per-language
   acceptance floor above (applicable criteria only).
4. If the **best-aggregate** engine PASSES all applicable floors for PT **and** EN **and** ES,
   select it as the **single global default**.
5. Otherwise evaluate the **other** engine.
6. If the other engine PASSES all three primary-language gates **and** has acceptable aggregate
   fidelity, select it as the **global default**.
7. **Only if neither** engine provides acceptable global coverage may a **per-language engine
   strategy** be considered, and only from measured evidence.

A documented hard constraint (license, platform, local-first) may still override on fidelity
ties. A secondary OCR engine MAY remain available as a fallback / additional reconciliation
candidate / evidence source.

**Constraints that carry over unchanged**:
- OCR is a fully local-first, **independent extraction technique** (path C, FR-060); document
  content is never sent to an external OCR service.
- Model downloads from documented sources are allowed (Constitution v2.0.0, Technology & Security
  Constraints) and must not exfiltrate document content.
- OCR is invoked **only where native text is absent or insufficient** (FR-024 / FR-024a) — never
  blindly replacing reliable native text.
- Mixed / hybrid PDFs are supported (FR-024).
- OCR output enters **extraction reconciliation** as another candidate / evidence source
  (FR-060 / FR-061); the LLM may never rewrite OCR output (FR-026c / FR-061a); reconciliation may
  only select an existing extracted candidate (FR-061a / FR-061b); a reconciliation conflict
  below the configured 0.75 confidence threshold requires human review (FR-062).
- Whatever engine is chosen, its per-word / per-token confidence is **normalized to a 0–100
  scale** for FR-027 (default low-confidence threshold 70) — see §9a.

**Status**: **RESOLVED — corrected Latin-script benchmark, 2026-09-07.** The first T013 run was
invalid (RapidOCR benchmarked with the bundled Chinese `ch_PP-OCRv4_rec` model, whose dictionary
lacks `ã â ê õ ç`). The corrected run (`benchmarks/ocr/run.py`, seed 0, **13 synthetic pages / 12
scored across PT·EN·ES**, 2026-09-07) configures RapidOCR with the multilingual **Latin**
recognition model `latin_PP-OCRv3_rec_infer.onnx` (official RapidAI/RapidOCR ModelScope repo;
sha256 recorded in `benchmarks/ocr/models/README.md`; loaded + executed on Apple Silicon / arm64
with `onnxruntime==1.29.0`) via explicit `rec_model_path` / `rec_keys_path`.

Result, applying the §4.1 engine-selection procedure: aggregate weighted fidelity — Tesseract
**0.936**, RapidOCR-Latin **0.700**. Per-language §4.1 acceptance floor — **Tesseract PASSES
PT, EN and ES**; **RapidOCR-Latin FAILS all three** (PT: weighted 0.678 / CER 0.297 / diacritic
0.180; EN: weighted 0.797 / CER 0.201 / numeric-token 0.250; ES: diacritic 0.378). The
best-aggregate engine (Tesseract) clears the floor for all three primary languages → **Tesseract
is the single global default; one global OCR default is sufficient (no per-language routing).**
RapidOCR (Latin model) remains an available, explicitly-selectable fallback / reconciliation
evidence source. Full evidence + step-by-step procedure: `benchmarks/ocr/RESULTS.md`.

**Rejected for reasons still valid under v2.0.0**:
- *OCRmyPDF*: rewrites the PDF; this feature needs text + confidence extracted into the model,
  not a new PDF. (Functional mismatch — unaffected by the constitution change.)

**Note**: whichever engine(s) are selected, their runtime / language data / models are installed
or downloaded per that engine's documented mechanism; the tool detects a missing or unusable OCR
engine and reports it clearly rather than silently skipping OCR.

---

## 5. OCR language selection

**Decision**: Auto-detect per page/region with `langdetect` (Apache-2.0) on a first-pass OCR
sample, then re-run the OCR engine with the detected language(s). Accept an optional `--ocr-lang`
per-run override (one or more languages) that skips detection. Record the detected or overridden
language(s) in the OCR provenance for that page/region (FR-027a).

**Rationale**: an offline detector covering the **primary v1 languages — Portuguese, English,
Spanish** (spec Clarifications 2026-09-07). Two-pass OCR (detect, then recognize) is a well-known
pattern and keeps the common case zero-config while allowing an override for known-language
documents. The **language-detector benchmark MUST distinguish at least Portuguese, English, and
Spanish** on short OCR'd fragments (the `por` vs `spa` case is the hard one); a corpus dominated
by one language does not exercise the detector.

**How a language reaches the OCR engine** (v1 Latin-script scope):
- **Tesseract** — the detected / overridden language id maps to installed traineddata:
  `pt→por`, `en→eng`, `es→spa`, `fr→fra`, `it→ita`, `de→deu`; multi-language pages combine with
  `+` (e.g. `-l por+eng`). Missing required traineddata → `OcrUnavailable`.
- **RapidOCR** — **one multilingual Latin PP-OCR recognition model for every supported v1
  language** (no per-language model switching, no Latin/CJK routing). It is supplied via explicit
  local `rec_model_path` + `rec_keys_path`; the bundled Chinese `ch_PP-OCRv4_rec` model MUST NOT
  be used for any supported v1 language; absence of the Latin model/dict → `OcrUnavailable`.

The lingua-py vs langdetect trade-off (lingua-py is more accurate on short text) is decided by the
§4 language-detection sub-metric on the multilingual corpus.

**Determinism**: `langdetect` seeds its RNG from the system clock by default, which would make
detection — and therefore OCR output and the Markdown — non-reproducible, violating FR-053a /
SC-009. The tool MUST set `langdetect.DetectorFactory.seed = 0` at import time so detection is a
pure function of the input text.

**Standalone `validate` / `fix`**: both re-derive text from the source PDF (§ deterministic
validation) and so may run OCR. They MUST expose the same `--ocr-lang` override and
`--ocr-confidence-threshold` option as `extract`, with identical defaults (auto-detect, 70) —
FR-027b. `convert` already forwards both.

**RE-OPEN under Constitution v2.0.0**: `langdetect` was chosen partly because `lingua-py` is
"heavier" — no longer a valid reason. The detector is behind a `LanguageDetector` protocol; the
**OCR benchmark (§4) includes a language-detection sub-metric** (per-page detected vs true
language), and whichever of {`langdetect` seed-pinned, `lingua-language-detector`, the OCR
engine's own language hint} scores best on the corpus becomes the default. Interim implementation:
`langdetect` (seed-pinned), swappable.

**RESOLVED — corrected sub-metric, 2026-09-07.** Re-derived on the multilingual PT/EN/ES corpus
(which does exercise Portuguese-vs-Spanish discrimination), detecting on each engine's OCR
output: **`lingua` 1.000 overall (PT 1.000, EN 1.000, ES 1.000)**; `langdetect` (seed 0) 0.917
overall (one miss on a short degraded Portuguese page); engine-native 0.000 (OCR reports script,
not language). **Default language detector = `lingua`**, with seed-pinned `langdetect` as the
fallback (`lingua` has no RNG, so it needs no seed pinning). Evidence: `benchmarks/ocr/RESULTS.md`.

**Alternatives considered**:
- *OCR-engine script / orientation detection* (e.g. Tesseract OSD `--psm 0`): detects script and
  orientation, not specific language — not enough alone to pick `por` vs `spa`, but a useful
  cross-check input.
- *`lingua-language-detector`*: more accurate on short text; now a live candidate (weight is not a
  disqualifier).
- *Always require the user to pass a language*: rejected — auto-detection is the spec default
  (clarification 2026-09-05); the `--ocr-lang` override remains.

---

## 6. DOCX export

**Decision**: `python-docx` (MIT), mapping the Document model directly to Word elements.

**Rationale**: Gives explicit control over paragraph styles (`Heading 1..9`, `Normal`,
`List Bullet`, `List Number`), table creation, and — critically — cell merging via
`cell.merge()`, which is what FR-047 needs to turn HTML `<table>` `rowspan`/`colspan` into real
Word merged cells. Deeper-than-6 hierarchy levels map to `Heading 7..9` / styled list paragraphs
(FR-017a). No external binary.

**Reproducible DOCX (FR-053a)**: a `.docx` is a zip and python-docx stamps `core.created` /
`core.modified` and each zip entry's mod-time from the wall clock. The exporter MUST set the core
`created`/`modified` properties to a fixed epoch and normalize zip entry timestamps (re-pack with
a constant `date_time`) so identical inputs produce a byte-identical DOCX.

**Alternatives considered** (Constitution v2.0.0 re-check):
- *pandoc*: rejected on a **fidelity** ground that still holds — its Markdown→DOCX style mapping is
  opinionated and its merged-cell fidelity from HTML `<table>` (FR-047) is unreliable. Binary size
  is **not** the reason. python-docx gives per-element style control and real `cell.merge()`.
  pandoc could be offered later as an optional alternative backend if a user wants it.
- *Building OOXML by hand*: maximum control, far more custom code that is harder to validate than
  a maintained library — the kind of fragile in-house implementation VII v2.0.0 steers away from.

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

## 8. Local LLM access (reconciliation candidate-selection + validation semantic pass)

**Decision**: One thin `httpx` (BSD) client (`validate/llm_client.py`) targeting an
**OpenAI-compatible** `POST {base_url}/v1/chat/completions`, shared by two analysis-only callers:
`reconcile/llm_select.py` (candidate-selection, FR-061a) and `validate/semantic.py` (issue
detection, FR-037). `base_url` and model name are configurable (CLI flag / env / config); default
`http://localhost:11434/v1` (Ollama's OpenAI-compatible endpoint). Before any LLM work, probe
availability; if it fails, stop with a clear message and no partial artifact presented as complete
(FR-038/046, SC-012). `extract` never requires the LLM — without it, reconciliation is
deterministic-only and residual disagreements become HUMAN_REVIEW_REQUIRED (FR-031/FR-066b).

**Mid-run failure (FR-038a / FR-046a)**: an LLM that passes the probe but then fails during the
semantic pass — connection reset, read timeout, HTTP 5xx, or a response body that does not parse
into the expected issue list — is retried up to `SOLARI_LLM_RETRIES` times (default **2**, with
a short backoff). If every attempt fails, the operation aborts with the *same* message and exit
code (4) as an unavailable LLM and writes no validation report / corrected Markdown / correction
log that would be treated as complete. Retry count does **not** affect output content, so it is
not part of the deterministic `run_id` (§14).

**Deterministic decoding**: the semantic request MUST send `temperature: 0` and, when the
endpoint accepts it, a fixed `seed`, so a given `(model, Markdown, source pages)` yields a
reproducible issue list (FR-053a). The `llm` block of the report records the model, `temperature`,
and `seed` actually used. Residual non-determinism (an endpoint that ignores `temperature`, or a
silently swapped model) cannot corrupt anything: it surfaces on re-run as a deterministic-name /
different-content collision (exit 5, FR-054), never as a silent overwrite. `llm_model` *is*
output-affecting and is folded into `run_id`.

**Rationale (Constitution v2.0.0 — architecture, not weight)**: the OpenAI chat-completions shape
is implemented by every mainstream local runner (Ollama, llama.cpp `server`, LM Studio, vLLM), so
the tool is not locked to one backend and the model is **swappable without touching this codebase**
— a separation-of-concerns and reproducibility win (the model id + decode params are pinned into
`run_id`, §4a). An out-of-process LLM also keeps the fidelity-critical deterministic code (extract,
transform, render) completely free of a heavy inference dependency and its failure modes.
Everything stays on `localhost`; the no-egress guard allows loopback.

**Alternatives considered**:
- *Ollama-native API*: nicer model discovery but ties the tool to Ollama. Rejected for the
  portable interface.
- *`openai` Python SDK pointed at the local URL*: adds transitive deps for request shaping we do
  in ~40 lines, with **no** fidelity, validation, or diagnosability benefit — a dependency that
  buys nothing for this use, which VII v2.0.0 still rejects (it forbids *unjustified* additions).
- *`llama-cpp-python` in-process*: couples model-file management and a large native inference
  dependency into this tool and its process. The objection is **architectural** (separation of
  concerns; the LLM should be replaceable; the deterministic pipeline should not import an
  inference runtime), not "large dependency". "User runs their own server" is the cleaner boundary.

---

## 9. CLI framework

**Decision**: stdlib `argparse` with `add_subparsers` for the **six** operations (`extract`,
`validate`, `fix`, `export`, `convert`, `review`). Shared-option helpers add `--pages`,
`--output-dir`, `--json`, the OCR options, the LLM options, `--reconcile-confidence-threshold`,
`--gross-divergence-threshold`, and `--resolution-store` to the relevant subparsers.

**Rationale (Constitution v2.0.0)**: CLI parsing is not product-quality-critical and argparse is
**sufficient** for six subcommands with a handful of options each; exit codes and `--help` text
are fully controllable. This is "the simplest tool that meets the requirement", not "fewest
dependencies wins" — if the CLI grew to need rich interactive prompts for `review`, a small TUI
dependency (e.g. `prompt_toolkit`) would be justified under VII v2.0.0 for the UX benefit; it is
not needed for a file/flag-driven `review`.

**Alternatives considered**:
- *Typer / Click*: nicer ergonomics, but no product-quality benefit for this CLI shape.
- *docopt*: unmaintained.

---

## 9a. OCR low-confidence threshold

**Decision**: Treat an OCR span as low-confidence when its minimum per-word / per-token confidence
— **normalized to a 0–100 scale regardless of OCR engine** (§4) — is below **70**. Expose a
per-run `--ocr-confidence-threshold` option restricted to 0–100; the configured value flows into
deterministic validation.

**Rationale**: 70 is a conservative default that surfaces uncertain recognition for review while
avoiding warnings for ordinarily clear text. Using the minimum confidence protects short but
material values such as amounts and clause identifiers. Making it configurable accommodates poor
scans, languages, and typefaces without silently changing the project-wide default. The
normalized scale keeps the threshold meaningful whichever engine §4 selects (Tesseract reports
0–100 per word; PP-OCR / RapidOCR report 0–1 per line/box — these are mapped onto 0–100, and the
mapping is documented once the engine is chosen).

**Alternatives considered**:
- *Fixed threshold*: simpler, but cannot adapt to document quality or language packs.
- *Mean confidence only*: can hide a single low-confidence word inside an otherwise clear span.

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
references an incomplete artifact (SC-016, FR-058).

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

## 14. Deterministic run identifier and reproducible audit records

**Decision**: No audit record embeds a wall-clock timestamp or a randomly generated identifier
in its persisted body. The common envelope drops `generated_at` and carries a single `run_id`
that is a pure function of the inputs:

```
run_id = sha256(
    source_sha256 + "\n" +
    normalized_page_selection + "\n" +      # e.g. "2_5-7_10-12" or "all"
    tool_version + "\n" +
    canonical_json(output_affecting_config) + "\n" +
    applicable_resolution_digest            # sha256 over the sorted applicability-keys +
).hexdigest()[:16]                          #   selected values/orderings replayed this run
```

`output_affecting_config` is the sorted-key JSON of only the settings that change artifact bytes:
`ocr_engine`, `ocr_languages_override` (list or null), `ocr_confidence_threshold` (int),
`reconcile_confidence_threshold` (float), `gross_divergence_threshold` (float — `validate`/`convert`
records only), `llm_model` + `llm_decode` (`{temperature, seed}`) for LLM-dependent records.
Timeouts, retry counts, `base_url`, output directory, `--resolution-store` path, and `--json` are
**excluded** — they do not affect content.

`applicable_resolution_digest` (FR-053a / FR-071) folds in every `human_confirmed` resolution the
run actually replayed: for each, its applicability key and its selected value / ordering. So
`(source, config, applicable resolutions)` fully determines the bytes — resolving a review item
and re-running changes the digest and yields a new, still-reproducible artifact; an unchanged
re-run replays the same resolutions and is a byte-identical no-op. Resolutions that exist in the
store but do **not** apply to this run (different source hash, incompatible config) contribute
nothing.

With identical inputs every artifact (`original Markdown`, `DOCX`, and all four records) is
byte-identical across runs, so a re-run is a satisfied no-op rather than a spurious collision
(FR-053a, FR-054, SC-009). `tool_version` stays a separate human-readable envelope field.

**Rationale**: reproducibility turns the no-overwrite rule and SC-009 from "aspirational" into a
byte-level test (`sha256(run1) == sha256(run2)`). A content-derived id also doubles as a cheap
integrity/version check and lets the traceability record point at each artifact by a stable name.

**Alternatives considered**:
- *Keep `generated_at` / uuid `run_id`, compare records "semantically" on collision* (ignore a
  documented volatile-field allowlist): works, but every consumer and test then needs the same
  allowlist logic, and "semantic equality" of JSON is a second source of truth. Rejected as more
  complex than removing the volatile fields.
- *Keep volatile fields, treat any pre-existing record as a hard collision (exit 5)*: makes
  repeated `convert` unusable and breaks the idempotency the spec now requires. Rejected.
- *Record the wall-clock time in a sidecar `.runmeta` file outside the record*: still
  non-reproducible bytes on disk for the run, still collides. Rejected.

## 15. Gross-divergence metric for `validate`

**Decision**: `validate` computes a **source-text match rate** = (extractable source-text tokens
from the selected pages that are found, in order-independent bag comparison with light
normalization, in the Markdown) ÷ (total extractable source-text tokens from the selected pages).
When `match_rate < gross_divergence_threshold` (default **0.5**, `--gross-divergence-threshold`,
range 0–1) the report:

- sets `summary.gross_divergence = true` and records `summary.source_text_match_rate` and
  `summary.gross_divergence_threshold`;
- emits exactly one issue with `issue_type = "gross_divergence"` stating the observed rate;
- still runs and lists **structural** deterministic checks (heading/table shape) but **suppresses**
  per-token `missing_content` / `extra_content` / `numeric_mismatch` issues (which would be
  thousands of lines of noise for a mismatched pair);
- skips the semantic LLM pass (no value comparing unrelated documents; also avoids the cost).

Above the threshold, behaviour is unchanged — the full issue list is produced.

**Rationale**: a single ratio is cheap (it is a by-product of the source-coverage check the
deterministic validator already performs for SC-001), explainable to a user, and directly
testable (SC-017). 0.5 is a deliberately low bar: normal extraction noise sits well above 90%
match, so only a genuinely wrong pairing trips it.

**Alternatives considered**:
- *Always emit the full per-token report, just add a flag*: leaves the user scrolling thousands
  of issues to discover the documents don't match. Rejected.
- *Fixed, non-configurable threshold*: corpora with heavy OCR or heavy artifact removal may sit
  lower; a per-run override costs nothing. Rejected in favour of configurable-with-default.
- *Structural-alignment score instead of text ratio*: harder to explain and to ground-truth than
  "what fraction of the words are even present". Rejected.

## 4a. LLM determinism strategy (resolves the reproducibility tension)

**Decision**: The externally observable reconciliation and validation results MUST be
reproducible even when the local LLM backend is not bit-deterministic. Layers:

1. **Request pinning** — every LLM call (reconciliation selection, validation semantic pass) sends
   `temperature: 0` and a fixed `seed`; the client records `model` id + `{temperature, seed}` and
   these are folded into `run_id` (§14). Different model or decode params ⇒ different `run_id` ⇒ a
   legitimately different (still reproducible) artifact.
2. **The programmatic guard makes the *reconciliation* result a bounded choice** (§21): the LLM
   only ever returns a *selection* among a fixed, finite candidate set (a value index, or an
   ordering that must equal a candidate order / a geometry-supported order). Even a backend that
   ignores `temperature` can only pick one of N fixed options; it can never introduce new bytes.
3. **Flip detection** — during reconciliation the selection call is issued **twice** (cheap; same
   prompt). If the two selections disagree, the decision is treated as **not confident enough**
   regardless of the reported score → apply the deterministic tie-break (prefer the
   geometry-supported / majority candidate) if one exists, else **HUMAN_REVIEW_REQUIRED**. This
   converts backend nondeterminism into an explicit, auditable review rather than a silent flip.
4. **Resolution replay** — once a conflict is `human_confirmed`, it never goes back to the LLM
   (FR-071); its outcome is a deterministic input.
5. **Two-level validation reproducibility (FR-053a + FR-053b)** — the report has two parts:
   - **Deterministic section** (`check_origin: "deterministic"`: SC-001 coverage, numeric
     integrity, table shape, reading-order check, gross-divergence, OCR low-confidence) — **always
     byte-reproducible** for identical effective inputs, and part of the FR-053a deterministic
     core.
   - **Semantic section** (`check_origin: "semantic"`: the local-LLM issue pass) — governed by
     **FR-053b**. At probe time the client determines whether the backend honours `seed` (a tiny
     fixed prompt issued twice — identical responses ⇒ `deterministic`, else `best_effort`) and
     writes `llm.reproducibility` into the report (and the traceability record's `llm_used`).
     - `deterministic` ⇒ the semantic section is byte-identical across runs for identical inputs.
     - `best_effort` ⇒ the tool does **not** claim byte reproducibility for a *newly generated*
       semantic section. Instead, `pipeline/validate` first looks for an **already-persisted**
       validation report for the identical applicability context
       (`sha256(markdown_sha256 ⧺ source_sha256 ⧺ normalized_selection ⧺ llm_model ⧺
       canonical_json(llm_decode))`) and, if found and valid, **replays its semantic section**
       verbatim rather than regenerating it. A re-run therefore reproduces the same report bytes
       *by replay*, and never raises a name collision for a would-be regeneration. Regeneration
       happens only when no persisted report matches (first run, or a changed context).

**`run_id` is unchanged and stays deterministic** — it folds `llm_model` + `llm_decode` but **not**
the semantic-issue *content* (which is not a pure function of those on a `best_effort` backend). The
report's byte identity on a re-run comes from **replay**, not from `run_id`.

**Rationale**: FR-053a's deterministic core is genuinely byte-reproducible; FR-053b makes the
LLM-assisted part honest (`deterministic` when the backend earns it, `best_effort` + replay
otherwise) without weakening any guard or the source-backed-content invariant, and without a
wall-clock/random workaround. The double-call flip check turns "the model waffled" during
*reconciliation* into a review item; the persisted-report replay turns "the model waffled" during
*validation* into a reproduced artifact.

**Alternatives considered**:
- *Require a deterministic backend*: not enforceable across Ollama / llama.cpp / vLLM builds.
- *Cache the first LLM answer forever, keyed by prompt hash*: hides model changes and makes the
  cache a hidden source of truth — rejected (FR-071 wants explicit, auditable inputs; a
  prompt-hash cache of *selections* keyed into `run_id` is acceptable as an optimisation but not
  the correctness mechanism).

---

## 16. Multi-page tables — Camelot / tabula re-evaluation

**Decision (interim, evidence-gated)**: Keep `pdfplumber`'s table detector + an in-house
multi-page stitcher (`transform/tables.py`) as the baseline. Add **Camelot** (`camelot-py`,
MIT; `lattice` + `stream` flavours) to the **acceptance table-fidelity benchmark** (part of the
corpus scoring, SC-003). Adopt Camelot as an additional table-extraction input **iff** it
measurably reduces lost rows / lost columns / merged-cell errors on the corpus versus the
baseline. `tabula-py` stays rejected (needs a **JVM** — a genuine operational failure mode and a
second language runtime, not merely "heavy").

**Rationale (Constitution v2.0.0)**: the old rejection leaned on "minimal-dependency / no heavy
system dep". Under v2.0.0 that is not sufficient — Camelot needs **Ghostscript** (a local binary,
no egress), which is an operational cost to weigh against a *measured* table-fidelity gain, not an
automatic disqualifier. But there is no evidence yet that the baseline is insufficient, so the
decision is: benchmark it, adopt only on demonstrated benefit. Tables feed reconciliation as
structure/geometry within the existing candidates; a Camelot table would be additional evidence
for `transform/tables.py`, not a fourth top-level extraction path.

**Alternatives considered**:
- *Adopt Camelot now, unconditionally*: premature — adds Ghostscript for an unproven gain.
- *tabula-py*: JVM dependency — real operational and packaging cost; rejected.

---

## 20. Docling — extraction path A (why it is in; what it is authoritative for)

**Decision**: `docling` (MIT, IBM) is **extraction path A** (FR-060). It processes the original
PDF directly and produces one `ExtractionCandidate` with three separable outputs:

1. **Literal content** — text of its detected regions, as source-backed segments with geometry.
   Reconciled by literal-content reconciliation alongside paths B and C (FR-061).
2. **Candidate reading order** — Docling's reading-order inference over its segments. This is
   **evidence for reading-order reconciliation** (FR-061d), never adopted implicitly (FR-060b /
   FR-015). It competes with path B's geometric order and path C's order.
3. **Structural hints** — Docling's heading / list / table detection, attached to segments as
   `StructuralHint` evidence. **Carried through reconciliation unaltered and unapplied**
   (FR-061c); only `transform/structure.py` / `transform/tables.py` may accept, reject, or apply a
   hint, and MUST record which it used (FR-064, SC-026).

**Rationale (Constitution v2.0.0)**: Docling gives materially better structure and reading-order
*evidence* on the complex, multi-column, legal-style layouts this tool targets than pure geometry
can, and it replaces a large body of fragile in-house column-detection / heading-inference
heuristics with a maintained, inspectable component — a fidelity **and** diagnosability gain. Its
operational cost is real (a deep-learning runtime — `torch` or `onnxruntime` — plus layout models,
one-time download) and is documented and accepted; it is fully local after the fetch (Principle V).

**Guardrails**:
- Docling's structural interpretation is **never authoritative** during extraction/reconciliation
  (FR-060b, SC-026). A test asserts the CED for a "Docling-only heading" fixture holds the text as
  literal content + an attributed hint, with the heading decision made (and recorded) only in
  stage 3.
- Docling runs in its **own path module** with no import to/from paths B or C (import-graph test).
- If Docling errors on a page, path A is marked `partial`/`failed` for that page and the other
  paths still produce candidates (FR-060, edge case; test).
- Docling model version is pinned; the download source is documented in quickstart; the no-model-
  download-at-run-time test asserts the cache is populated ahead of a run.

**Alternatives considered**:
- *Hand-built layout analysis*: the fragile-heuristics path VII v2.0.0 explicitly steers away from.
- *`unstructured` / `marker` / `nougat`*: also heavy; Docling is MIT, actively maintained, and its
  output cleanly separates the three concerns above. Could be added as a fourth path later if a
  benchmark shows a fidelity gap.
- *Making Docling the sole extractor*: violates FR-060 independence — its errors would propagate.

---

## 21. Reconciliation layer design

**Decision**: `reconcile/` implements deterministic-first reconciliation with LLM
candidate-selection only, in this order:

**a. Segment identity & alignment (`align.py`, deterministic).** Each candidate's segments get a
stable `segment_id` derived from `(page, rounded bbox, normalized-text hash)`. Cross-candidate
alignment groups segments that describe the same region by geometric overlap (bbox IoU ≥ a
configured threshold) plus normalized-text similarity (token Jaccard) as a tie-break. Output:
`AlignedSegmentGroup`s, each holding 1–3 candidate segments. A group with segments from only one
candidate is still a group (that candidate is the sole evidence there).

**b. Literal-content reconciliation (`literal.py`).** Per group:
- normalize each candidate's text for **comparison only** (whitespace collapse, Unicode NFC, quote
  folding) — the *accepted* value is always a candidate's **verbatim** text, never the normalized
  form;
- if the normalized texts are equal → `deterministic_agreement`, accept any candidate's verbatim
  text (prefer native over OCR when both present and equal after normalization);
- else compute a **material-disagreement** signal: token-level edit distance ratio + whether the
  disagreement is only in whitespace/casing (not material) vs digits/letters (material). Only
  material disagreements go further.
- **confidence** = a deterministic function of {agreement fraction among candidates, whether one
  candidate is native-text vs all-OCR, character-class of the diff, OCR confidence of the OCR
  candidate}. ≥ threshold (default 0.75) → LLM selection; < threshold → HUMAN_REVIEW_REQUIRED.

**c. Reading-order reconciliation (`reading_order.py`).** Over the accepted segments:
- each candidate contributes an order (path B: geometric; path A: Docling; path C: OCR order);
- **deterministic geometric resolver**: detect columns (x-gap clustering), then order
  top-to-bottom within each column, columns left-to-right; if every candidate order equals the
  geometric order (or all candidate orders agree) → `deterministic_agreement`;
- else material disagreement (Kendall-τ distance between candidate orders above a threshold, and
  the geometric resolver not unambiguous) → confidence → LLM selects an **existing candidate
  order or the geometric order**, or HUMAN_REVIEW_REQUIRED.

**d. Programmatic guard (`guard.py`).** The LLM returns a structured selection (a candidate id /
index, or an ordering as a list of `segment_id`s). The guard checks: selected literal value is
**byte-identical** to some candidate's verbatim text; selected ordering is **exactly** some
candidate order or the geometry-supported order. Any mismatch → response rejected → conflict
unresolved → HUMAN_REVIEW_REQUIRED (FR-061b). Plus the double-call flip check (§4a).

**e. Decision paths & log.** Every group/ordering yields a `ReconciliationDecision`
(`deterministic_agreement` | `llm_selected` | `human_confirmed`) recorded in the
`ReconciliationLog` with competing candidates, sources, method, selected value/ordering,
confidence (for `llm_selected`), and resolution-store ref (for `human_confirmed`).

**f. Resolution replay (`resolutions.py`).** Before raising a review item, check the resolution
store for a record whose applicability key matches (§22); if found, apply it as `human_confirmed`
(replayed) and log it. If the item would otherwise be auto-resolvable but a stored resolution
exists for a *changed* context, the stored one does **not** match the key and is not used — a
fresh item is raised (FR-071).

**Invariant (tested)**: an automatic reconciliation result never contains literal source text
absent from the allowed candidates — `assert selected_value in {c.verbatim_text for c in
group.candidates}` on every `deterministic_agreement` / `llm_selected` decision (SC-020).

**Alternatives considered**:
- *LLM does the whole reconciliation in one pass* (reads all candidates, emits the merged doc):
  rejected outright — it would author text (FR-029/FR-061a). The LLM only ever selects.
- *Always require unanimous agreement, else human review* (no LLM at all): simpler and fully
  deterministic, but pushes far too much to humans on documents where two of three paths agree.
  The LLM-selection tier (≥ 0.75) is the pragmatic middle; the guard keeps it safe.
- *Confidence from the LLM's own self-report only*: unreliable; the deterministic signal (native
  vs OCR, char class, agreement fraction) is the primary input, the LLM's score is secondary, and
  the flip check overrides both.

---

## 22. Human-review workflow design

**Decision**: A `review` subcommand plus a file-based queue and an append-only store.

- **Queue**: `<base>.human-review-queue.json` (+ `.md`). Written by `extract`/`convert` when items
  are open. Each item: `id` (deterministic from applicability key), `conflict_type`, the FR-062a
  or FR-062d evidence fields, `status: open`.
- **`review list [--output-dir DIR]`** — prints open items (id, page, type, one-line summary).
- **`review show <id>`** — prints the full evidence for one item (each candidate's value/order,
  bboxes, sources, confidence) so the reviewer can compare against the PDF.
- **`review resolve <id>`** — one of:
  - `--select <n>` : accept candidate *n* as supplied (literal conflict);
  - `--value <TEXT>` (or `--value-file PATH`) : enter a verified literal value (literal conflict,
    no candidate correct — FR-068); records `manually_verified: true`;
  - `--order <segId,segId,...>` : accept an ordering of the existing segment ids (reading-order
    conflict — FR-069). The ids MUST be exactly the item's segment set (validated).
  Appends a `HumanReviewResolution` record to the store and marks the queue item `resolved`.
- **Resume**: re-running `extract`/`convert` with the same inputs finds the resolutions via the
  applicability key, replays them as `human_confirmed`, and (if no items remain open) completes to
  the final Markdown. No Markdown hand-editing (FR-072).

- **Applicability key** (FR-071): `sha256(source_sha256 ⧺ conflict_type ⧺ canonical(page, bbox
  region, aligned candidate-value set) ⧺ canonical_json(output_affecting_config_subset))`. The
  `output_affecting_config_subset` is the config that could change *this* conflict's evidence:
  `ocr_engine`, `ocr_languages_override`, `ocr_confidence_threshold`, and the set of enabled
  extraction paths. Page selection is **not** in the key directly (the region + source hash pin
  it), so resolving a conflict on page 5 in a `--pages 1-10` run still applies in a `--pages 5`
  run — but a page-selection change that removes the region means the conflict never arises.
- **Store**: `resolutions.jsonl` + generated `resolutions.md`. Append-only (FR-057b): a
  re-resolution of the same key is a new line; replay uses the **last** record for a key. Default
  location: `<output-dir>/../resolutions.jsonl`; overridable with `--resolution-store PATH` (e.g. a
  project-wide store shared across documents).

- **Exit codes**: `extract`/`convert` exit **6** ("human review required — run incomplete") when
  they stop at the queue; `review resolve` exits 0 on success, 2 on a bad selection/order.

- **`fix` → review routing** (FR-045a): when `fix` reads a `reconciliation_error` issue, it does
  not edit the Markdown; it writes/updates a human-review queue item for the underlying conflict
  (reconstructed from the validation report's source location + reconciliation log) and reports
  "N issue(s) routed to human review; re-run `extract`/`convert` after resolving". `fix` still
  applies any `disallowed_transformation` corrections in the same run.

**Alternatives considered**:
- *Interactive TUI for `review`*: better UX, but a file/flag interface is scriptable, diffable,
  testable, and reproducible; a TUI can be layered on later (VII v2.0.0 would justify a small TUI
  dep for the UX gain, but it is not needed for correctness).
- *Store resolutions inside the per-run output dir only*: then a re-run in a fresh dir loses them.
  A durable, relocatable store keyed by content is the point.
- *Let the LLM propose a resolution for the human to approve*: acceptable as a UX hint later, but
  the human's decision is authoritative and the LLM must not be in the persisted `human_confirmed`
  provenance.

---

## 23. Intermediate-artifact persistence

**Decision**: persist what auditability / replay / resume / diagnosis need; regenerate the rest.

| Artifact | Persisted? | Why |
|---|---|---|
| **Extraction candidates** (per path) | **Yes, JSON only** — the machine-readable source of truth. **No `.md` companion.** | Needed to re-present evidence on resume, for `applicable_resolution_digest`, and for diagnosing which path erred. The **reconciliation log's `.md` rendering** is the human-facing diagnostic for what each path produced per conflict; a candidate is not a converted-document format and does not warrant a second representation (M1). A future `--dump-candidate` diagnostic MAY render one read-only, clearly non-authoritative. Reproducible per path (modulo the OCR engine + langdetect seed). |
| **Canonical Extracted Document** | **Yes, JSON only.** No `.md` companion. | The reconciliation state a resume run continues from; the input final validation checks against. Same rationale as candidates — the reconciliation log's `.md` is the human-facing view. |
| **Reconciliation log** | **Yes**, JSON + `.md` (FR-057) | Audit trail of every decision (Principle IV). |
| **Structural hints** | Inside candidates + CED | Not a separate artifact — they are attributed fields on segments. |
| **Human-review queue** | **Yes**, JSON + `.md` | The `review` command reads it; blocks delivery. |
| **Resolution store** | **Yes**, append-only JSONL + `.md`, durable across runs | FR-057b; the deterministic replay input. |
| **Semantic document** | **No** (ephemeral) | Deterministically regenerable from the CED by stage 3; persisting it would be a duplicate source of truth. A `--dump-semantic` diagnostic flag MAY write it, clearly marked non-authoritative. |
| **Removal log** | **Yes** (existing) | FR-011. |
| **Validation report** | **Yes** (existing) | FR-032. |
| **Correction log** | **Yes** (existing) | FR-042. |
| **Traceability record** | **Yes**, `convert` only (existing) | FR-052; now also links the reconciliation log + queue. |
| **Original / corrected Markdown, DOCX** | **Yes** (existing) | The deliverables. |

Candidates + CED live under `<output-dir>/intermediates/` (or a working dir); they are still
subject to the atomic-write + no-overwrite + reproducible rules.

### v1 decision — intermediate persistence is always on (no `--no-intermediates`)

`extract` (and `convert`) **always** write the extraction candidates and the Canonical Extracted
Document as authoritative JSON intermediate artifacts, and always write the reconciliation /
human-review / audit intermediates required by the persistence policy above. These artifacts are
**required** for provenance (FR-063 / FR-066), diagnostics (which path erred), deterministic
replay (`applicable_resolution_digest`, FR-071), human review and resume (FR-072), failure
analysis, and reproducibility (FR-053a). **v1 intentionally provides no `--no-intermediates`
mode** — there is no supported way to suppress these artifacts, and this is a deliberate
architectural decision rather than an unimplemented option. **Disk usage is an accepted trade-off
for v1.** A future retention / cleanup policy (age-based pruning, opt-in compaction for
zero-review runs, an external janitor) MAY be designed separately, but only in a way that does
**not** weaken auditability or reproducibility; it is out of scope here and is **not** a v1
feature requirement. The additive, clearly-non-authoritative diagnostic dumps mentioned above
(`--dump-candidate`, `--dump-semantic`) are the opposite of this — they *add* optional output,
they never remove the required intermediates.

**Alternatives considered**:
- *A `--no-intermediates` flag for zero-review runs*: rejected for v1 — it creates a mode in
  which a run cannot be audited, replayed, or diagnosed after the fact, directly weakening
  Principle IV and FR-053a/FR-071; the disk cost of keeping them is the cheaper trade-off.
- *Persist the semantic document too*: rejected — duplicate source of truth, and it is cheap to
  regenerate.
- *Keep everything in memory and only write final artifacts*: breaks resume (the queue + CED must
  survive process exit) and diagnosis.

---

## 24. Native-text reliability assessment — placement and boundary (M2)

**Decision**: `extract/native_reliability.py` is an **extraction-routing / evidence component**,
not a fourth extraction path and not a consumer of any path's output. Its job: for each page /
region, decide whether the native text layer is reliable, or whether OCR (path C) must run there
(FR-024 / FR-024a). It reads **low-level native-text evidence directly from the source PDF / page
representation** via `pdf/loader` (raw `pdfplumber`/`pdfminer` primitives on the source handle):
native-text coverage vs the rendered page image area, encoding-gibberish / mojibake detection,
ToUnicode / CMap sanity, per region.

**It MUST NOT** take a Docling, pdfplumber, or OCR `ExtractionCandidate` as input — that would
make path C depend on another path's output and break FR-060 / SC-024. Conceptual dependency
direction:

```
source PDF ──▶ native-text reliability assessment ──▶ (which/where OCR is required)
source PDF ──▶ Docling candidate                    (independent)
source PDF ──▶ pdfplumber + pypdfium2 candidate     (independent)
source PDF / region ──▶ OCR candidate               (independent; region chosen by the assessment)
```

Sharing the `pdfplumber`/`pdfminer` **library** on the source handle is fine — it is not consuming
`plumber_path.py`'s produced candidate. The extraction-independence architecture test asserts
`extract/native_reliability` and `extract/ocr_path` import **neither** `extract/plumber_path` nor
`extract/docling_path`, and that a fault injected into any path's candidate does not change the
reliability classification or the OCR-trigger decision.

**Rationale**: the assessment needs the *raw* native layer, not a path's interpretation of it; and
keeping it upstream of and independent from the three paths is what lets "one technique's error
cannot propagate" (FR-060) actually hold for the OCR-triggering decision.

**Thresholds** (coverage ratio, gibberish score, etc.) are **corpus-tuned**, not fixed here — see
the Outstanding items list and the tuning task.

---

## Outstanding items for Phase 1 / gated on evidence

- **§4 OCR engine** — **RESOLVED (corrected benchmark T013, 2026-09-07)**: default = **Tesseract 5**
  (single global default; clears the §4.1 per-language acceptance floor for PT/EN/ES, RapidOCR-Latin
  fails all three). `benchmarks/ocr/RESULTS.md`.
- **§5 language detector** — **RESOLVED (corrected benchmark T013, 2026-09-07)**: default = **lingua**
  (1.000 across PT/EN/ES), seed-pinned `langdetect` fallback.
- **§4a** — confirm the chosen local LLM backend's behaviour under `seed`; document the reference
  backend in quickstart.
- **§16 Camelot** — decide after the table-fidelity corpus scoring.
- **Phase 1 refinements** (in `data-model.md` / contracts): exact `ValidationIssue` enum values;
  heading-inference thresholds; table-stitch heuristics; match-rate token normalization;
  `output_affecting_config` serialization; bbox IoU + Jaccard thresholds for alignment; Kendall-τ
  threshold for reading-order disagreement; the confidence functions (literal & reading-order).
