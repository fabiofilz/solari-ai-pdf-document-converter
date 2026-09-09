# Phase 0 Research: Local-First PDF Document Converter

Each decision below follows the Decision / Rationale / Alternatives format.

**Refreshed 2026-09-07 for Constitution v2.0.0 and the multi-path architecture.**
The spec now describes independent extraction paths → reconciliation → semantic
transformation → final fidelity validation, with a human-review workflow. Sections
2–13 predate that model; each has been re-framed against v2.0.0 ("Simplicity &
Justified Dependencies" — dependency count is not an objective) and against the
current spec. Sections 20–23 are new (Docling, reconciliation design, human-review
workflow, artifact persistence). **Updated 2026-09-08**: §22 rewritten and §§25–26
added for the interactive Human Review workflow and Human Review Report
(FR-074–FR-084 / SC-032–SC-036); **2026-09-08 (audit remediation)**: §14 designated
the authoritative effective-input definition; §22.2 (`sequence_index`-authoritative
current-resolution + I1–I6 + crash durability), §22.4 (authorization = `run_id`
match only, audit-event not deterministic-core), §22.8 (prompt-layer invariants),
§25 (`segment_transforms` model, `not_located` nullability, root-cause defect
class, reading-order invariant, Markdown serialization, `<base>.md` publication
gate). **2026-09-09 (pre-semantic audit remediation)**: §21a′ added (deterministic
cross-technique coverage corroboration in `align.py` — closes the coarse/fine
double-accept before it can reach the CED); §14 clarified that run-identity
recomputation uses the **scoped** `applicable_resolution_digest(source_sha256=…,
config_subset=…)` only (H1); §27 added (authoritative conservative v1
de-hyphenation policy — pinned so T066/T067 can be encoded test-first).

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

**Rationale (Constitution v2.0.0)**: CLI *parsing* is not product-quality-critical and argparse is
**sufficient** for six subcommands with a handful of options each; exit codes and `--help` text
are fully controllable. This is "the simplest tool that meets the requirement", not "fewest
dependencies wins".

**Interactive `review` (FR-074, spec 2026-09-08)**: the `review` workflow is now specified as an
**interactive keyboard-driven terminal mode** (Up/Down/Enter menus, text entry, answer browsing).
argparse still owns the `review` *subcommand and its flags*, but the interactive prompt layer is a
separate concern — see **§22** for the terminal-interaction-library decision (`questionary`). A
non-interactive `review` sub-interface (`list` / `show` / `resolve` / `authorize` / `status`)
remains for automation and tests.

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

## 14. Deterministic run identifier and reproducible audit records  *(AUTHORITATIVE effective-input definition)*

> **This section is the single authoritative definition of the effective-input tuple and
> `run_id`.** `spec.md` FR-053a, `data-model.md` (common envelope), and `contracts/cli.md`
> **reference** this definition; they MUST NOT restate a divergent list. If a field's
> output-affecting scope changes, it changes **here** and the others follow.

**Decision**: No audit record embeds a wall-clock timestamp or a randomly generated identifier
in its persisted body. The common envelope drops `generated_at` and carries a single `run_id`
that is a pure function of the inputs:

```
run_id = sha256(
    source_sha256 + "\n" +
    normalized_page_selection + "\n" +      # e.g. "2_5-7_10-12" or "all"
    tool_version + "\n" +
    canonical_json(output_affecting_config) + "\n" +
    applicable_resolution_digest            # sha256 over the sorted (applicability_key,
).hexdigest()[:16]                          #   canonical(selected value/ordering)) pairs
```

**`output_affecting_config`** is the sorted-key JSON of only the settings that change artifact
bytes. It has **two scopes** because different records depend on different subsets:

| scope | fields | applies to |
|---|---|---|
| **extract-stage** (the CED, the render, and therefore Human-Review verification) | `ocr_engine`, `ocr_languages_override` (list\|null), `ocr_confidence_threshold` (int), `reconcile_confidence_threshold` (float), `enabled_extraction_paths`, `llm_model` + `llm_decode` `{temperature, seed}` *(only when the LLM was reachable for reconciliation this run)* | `extraction_candidate`, `canonical_extracted_document`, `reconciliation_log`, `human_review_queue`, `human_review_verification`, `original Markdown`, `removal_log`, `traceability_record`, `human_review_authorization` (the `authorized_run_id` it carries) |
| **validate-stage** (adds) | `gross_divergence_threshold` (float), `llm_model` + `llm_decode` | `validation_report` only |

Timeouts, retry counts, `base_url`, output directory, `--resolution-store` path, `--json`, and the
review UI path are **excluded** — they do not affect content.

**The Human-Review workflow computes `run_id` without re-prompting for flags.** `extract`/`convert`
persist a **`RunContext`** record (`contracts/run-context.schema.json`) — the extract-stage
`(source_sha256, normalized_page_selection, tool_version, output_affecting_config)` — in the
output dir. `review` reads it, folds in `applicable_resolution_digest` computed from the *current*
resolution store, and derives the *current* `run_id`. A config change between runs (different
`--output-dir` invocation with different OCR settings) yields a different `RunContext` ⇒ a
different `run_id` ⇒ any prior authorization no longer matches. No second run-identity definition
exists.

**The digest call for run identity is always the *scoped* one (H1 — 2026-09-09 audit
remediation).** Run-identity recomputation (T136/T137: `run_identity.recompute_run_id`, and the
equivalent fold inside `extract`) MUST call
`ResolutionStore.applicable_resolution_digest(source_sha256=<the run's source SHA256>,
config_subset=<the run's applicability / effective-config subset>)`. It MUST **not** call the
no-argument whole-store form: that folds *every* currently-applicable resolution regardless of
which document or config it belongs to, so an unrelated document's resolution in the same store
would perturb this run's `run_id`. The scoped call is defined in `resolutions.py` — it keeps a
currently-applicable record only when its envelope `source_sha256` matches **and** recomputing its
applicability key under the given config subset reproduces its stored key, and it **fails closed**
(a record whose applicability cannot be reproduced is dropped, never folded). The no-argument form
of `applicable_resolution_digest()` is retained only for diagnostics / the store's own `.md`
rendering; it is never an input to `run_id`.

`applicable_resolution_digest` (FR-053a / FR-071) folds in every `human_confirmed` resolution the
run actually replayed: for each, its applicability key and its selected value / ordering. So
`(source, config, applicable resolutions)` fully determines the bytes — resolving a review item
and re-running changes the digest and yields a new, still-reproducible artifact; an unchanged
re-run replays the same resolutions and is a byte-identical no-op. Resolutions that exist in the
store but do **not** apply to this run (different source hash, incompatible config) contribute
nothing — the scoped digest call is what enforces this.

With identical inputs every artifact (`original Markdown`, `DOCX`, and all four records) is
byte-identical across runs, so a re-run is a satisfied no-op rather than a spurious collision
(FR-053a, FR-054, SC-009). `tool_version` stays a separate human-readable envelope field.

**Human-review events vs effective inputs (FR-074–FR-084, 2026-09-08).** The `run_id` digest
already folds `applicable_resolution_digest` — the **currently-applicable** resolution set (the
valid record with the greatest `sequence_index` per applicability key, §22.2). So:

- **Changing / superseding a review decision** appends a new resolution record; the applicable
  set changes; `applicable_resolution_digest` and therefore `run_id` change. The new decision set
  produces a new, still-reproducible artifact family. The prior artifacts (a different `run_id`)
  are not overwritten (FR-054) and are not a "successful delivery" for the new decision set.
- The **downstream-processing authorization** (FR-077) is *not* an effective input — it gates
  *whether* delivery proceeds, not *what bytes* are produced. It is **excluded from `run_id`**
  and is **NOT part of the FR-053a run-twice deterministic-core artifact set** (M4): authorization
  is an explicit **human action**, recorded as an **append-only audit event**
  (`<base>.review-authorizations.jsonl` + `.md`, one line per authorized `run_id`). Its *body* is
  deterministic (no wall-clock, no random id — project convention) so re-authorizing an unchanged
  decision set is an **idempotent no-op append** (a line with that `authorized_run_id` already
  exists), but a run-twice test never *regenerates* it — the human either authorized or did not.
  **Authorization validity is purely `authorized_run_id == current run_id`.**
- **Human Review verification results and the Human Review Report** *are* **derived, deterministic**
  functions of `(human-review queue, currently-applicable resolutions, RunContext,
  review→Markdown lineage, RenderMap + segment_transforms, delivered Markdown)` — all pinned by
  `run_id`. They **join the FR-053a deterministic core** (like the removal log): no wall-clock, no
  random id, byte-reproducible for identical effective inputs. They are outputs, never folded into
  `run_id`.
- Because authorization is `run_id`-keyed, **an authorization never silently carries over to a
  changed decision set**: change one answer → new `run_id` → no authorization event matches → the
  run is `resolved_unauthorized` again and re-authorization is required before a successful
  delivery (FR-077, §22.4).

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

**a′. Cross-technique coverage corroboration (`align.py`, deterministic — 2026-09-09 audit
remediation).** IoU one-to-one grouping does not relate a **coarse** segment from one technique
(a pdfplumber line, a Docling block) to the **finer** segments another technique emitted for the
*same* source text — the coarse box's IoU against each finer box is below the threshold, so the
coarse group and every finer group survive as independent single-member groups and the shared
source text is accepted **twice** in the CED. Alignment closes this **narrowly**, as evidence and
never as a rewrite:

- a coarse **single-member** group *C* (technique *tC*, page *p*) is folded into a contiguous run
  *F₁…Fₙ* (n ≥ 2) of **single-member** groups from **one other** technique *tF* on the **same
  physical page** — recorded as a `CoverageCorroboration` on **each** `Fᵢ` — only when **all** of:
  1. the run is contiguous in *tF*'s own **candidate reading order** (`reading_order_index`), and
     that order is uniquely supported (no repeated index) — otherwise no suppression;
  2. every `Fᵢ` bbox is geometrically **contained** in *C*'s region (small fixed epsilon), and the
     union of the `Fᵢ` boxes spans a strong fraction of *C*'s area (a coarse box materially larger
     than the run may hold unrelated content → not coverage);
  3. no *tF* group **outside** the run is contained in *C* (the run is *all* of *tF* inside *C*);
  4. the **comparison keys** are equivalent: `comparison_key(C)` equals the `comparison_key(Fᵢ)`
     values joined by exactly one U+0020 between non-empty parts and re-normalised with the same
     comparison-key rule (§21b) — a **comparison-only** test; no literal is built or stored from
     the join, the finer stored values are untouched;
  5. each `Fᵢ` participates in **at most one** such relationship.
- *C* is then **not** returned as its own `AlignedSegmentGroup`. It does **not** vanish: its
  technique appears in every covered `AcceptedSegment.contributing_techniques`, and its verbatim
  text / `SourceRef` / `segment_id` are carried on the `CoverageCorroboration`. Literal and
  reading-order reconciliation read `members` only — corroborations never enter a decision.
- **Fail conservative.** Any doubt — comparison keys differ, only a substring matches, numeric or
  punctuation differences survive §21b, the run is not contiguous, geometry spans extra content,
  or the finer order is ambiguous — keeps *C* independent. A false-negative (two representations
  kept, later flagged by validation) is always preferred to a false-positive removal. Semantic
  reflow / dehyphenation / dictionaries / fuzzy similarity are **never** used to establish
  equivalence; `align.py` stays a grouper.

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

> **Rewritten 2026-09-08** for FR-074–FR-084 / SC-032–SC-036. The earlier file/flag-only
> `review` design is **superseded**: the normal `review` interaction is now an **interactive,
> keyboard-driven terminal mode**. The file-based queue + append-only store survive, extended.

**Decision**: `review` is an interactive terminal workflow (`questionary` on `prompt_toolkit`)
over a file-based **queue**, an append-only **resolution store**, and a per-delivery
**authorization record**. A non-interactive sub-interface stays for automation/tests.

### 22.1 Terminal-interaction library

| Option | Up/Down/Enter menu | Text entry | Ctrl+C | Cross-platform (macOS/Linux/Windows) | Maint. | Runtime deps | 7-day rule | Py ≥ 3.12 | Verdict |
|---|---|---|---|---|---|---|---|---|---|
| **stdlib only** (`termios`/`tty`/`msvcrt` + ANSI) | hand-rolled | hand-rolled | manual | POSIX + a separate Windows path — all custom | n/a | none | n/a | ✓ | rejected — fragile custom terminal code in a safety-critical workflow is exactly what Constitution VII v2.0.0 says to avoid |
| **`prompt_toolkit`** 3.0.x directly | build widgets yourself | ✓ | ✓ | ✓ (own Windows backend) | very active (IPython, pgcli, ptpython) | `wcwidth` | ✓ (current **3.0.53**, 2026-07-26) | ✓ (≥3.10) | viable, but we'd re-implement the select/list widgets `questionary` already provides |
| **`questionary`** 2.1.1 | ✓ `select` | ✓ `text` | ✓ (returns `None`/raises `KeyboardInterrupt`, catchable) | ✓ (via `prompt_toolkit`) | maintained, MIT, first-upload 2025-08-28 | `prompt_toolkit<4,>=2` → `wcwidth` | ✓ | ✓ (≥3.9) | **SELECTED** |
| **`InquirerPy`** 0.3.4 | ✓ | ✓ | ✓ | ✓ | **no release since 2022-06** (maintenance risk) | `prompt_toolkit`, `pfzy` | ✓ | ✓ | rejected on maintenance status + an extra transitive dep for features we don't need |

**Selected: `questionary`.**
- *Exact fit*: `questionary.select` (arrow-key menu of candidates + `"Enter another value…"`),
  `questionary.text` (exact-literal entry), repeated `select` to browse answers and to build a
  reading order one segment at a time. Nothing in FR-074–FR-078 needs more.
- *Transitive closure*: `questionary` → `prompt_toolkit` (3.0.x) → `wcwidth`. Three pure-Python
  packages, no native build, MIT/BSD, no network, Windows-capable (`prompt_toolkit` ships its own
  Win32 console backend). `prompt_toolkit` is one of the most widely deployed terminal libs in
  the Python ecosystem.
- *Constitution VII v2.0.0*: replaces a hand-written raw-terminal key handler (fragile,
  hard-to-test custom code) with a maintained component whose behaviour is inspectable and
  testable — a "well-maintained specialized component over in-house heuristics" call. It touches
  only the `review` UI layer; the deterministic pipeline never imports it.
- *Constitution V*: `prompt_toolkit`/`questionary` do no network I/O; the no-egress autouse guard
  still holds. No model/data download.
- *Constitution VI*: testable — `prompt_toolkit.input.create_pipe_input()` + `DummyOutput` (or
  `questionary`'s injectable `input=`/`output=`) drive scripted key sequences in tests; and all
  workflow logic (persistence, applicability, authorization derivation, lineage, verification)
  lives **outside** the prompt layer and is unit-tested directly, plus exercised through the
  non-interactive sub-interface.

**Candidate versions to pin (recorded, NOT added to `pyproject.toml` this turn)** — as of
2026-09-08: `questionary==2.1.1` (2025-08-28), `prompt_toolkit==3.0.53` (2026-07-26),
`wcwidth` current — all far outside the 7-day window and Python ≥3.12 compatible. They are added
at the first `review`-workflow implementation task (mirroring how `docling` is deferred to T046),
with the exact pins **re-verified against the 7-day rule at add-time** and recorded in the
plan.md ledger at that point.

### 22.2 Persistence model (immediate, append-only, resumable)

Files (§23):

| File | Scope | Content |
|---|---|---|
| `<base>.run-context.json` + `.md` | per run | the extract-stage effective-input tuple (§14) so `review` can recompute `run_id` |
| `<base>.human-review-queue.json` + `.md` | per run | every raised item, `status ∈ {open, resolved}` (**derived from the store on every load**), the FR-075 presentation fields, and the derived `run_state` |
| `resolutions.jsonl` (+ `resolutions.md`) | **durable, cross-run** (`--resolution-store PATH`, default `<output-dir>/../resolutions.jsonl`) | one **append-only** line per confirmed decision — never edited, never deleted |
| `<base>.review-authorizations.jsonl` (+ `.md`) | per output dir | **append-only** audit event log; one line per authorized `run_id` (see 22.4) |

**Currently-applicable decision — one authority (H6).** `sequence_index` is the **authoritative**
ordering. `supersedes` is **audit linkage only** — it does not independently select current state.
The **currently-applicable resolution for an applicability key = the valid record with the
greatest `sequence_index` for that key.** Application-level invariants the store loader enforces:

- **I1** — `sequence_index` is a non-negative integer, **unique and strictly increasing** across
  the whole store (assigned at append = `max(existing) + 1`).
- **I2** — when a resolution already exists for an applicability key, a new resolution for that
  key MUST set `supersedes` = the `resolution_id` of the *currently-applicable* prior resolution
  for that key (the one with the greatest `sequence_index`) at append time.
- **I3** — `supersedes` MUST be `null` **iff** no prior resolution exists for that applicability
  key.
- **I4** — a `supersedes` target MUST exist in the store, share the same `applicability_key`, and
  have a **lower** `sequence_index`.
- **I5** — the `supersedes` graph per key MUST be a simple chain: no cycles, no forks (two records
  superseding the same target), no orphan links.
- **I6** — **fail closed**: if any invariant is violated for a key, the loader refuses to replay
  *that key* (raises the review item fresh) and records a diagnostic; it never guesses a "current"
  record. Other keys are unaffected.

**Crash durability (SC-032 / M3).** Every append to `resolutions.jsonl` and
`review-authorizations.jsonl` is done as an **atomic whole-file publish**: read the existing
lines, append the new complete record line (`json.dumps(..., ensure_ascii=False)` + `"\n"`), write
all lines to `<store>.tmp` in the **same directory**, `flush()` + `os.fsync()`, then
`os.replace(<store>.tmp, <store>)`. A crash leaves either the old file or the new complete file —
never a torn line. A stray `.tmp` is discarded on next run. The `.md` rendering is regenerated
from the `.jsonl` immediately after, by the same atomic temp+replace. The interactive loop marks
the queue item `resolved` **only after** the resolution append `os.replace` returns; a crash
before that leaves the item `open` and it is re-asked (the store is the source of truth — SC-032
holds: a confirmed answer that reached disk is never re-asked, a not-yet-persisted one is).
Whole-file artifacts (queue, RunContext, verification record, report, Markdown) use the same
atomic temp+fsync+`os.replace` in the destination dir.

- **Immediate persistence (FR-070 / SC-032)**: the interactive loop persists the resolution
  (durable, per above) **before** advancing to the next item.
- **Resume**: on `review` open (or `extract`/`convert` re-run) the workflow loads the store,
  applies I1–I6, marks every queue item whose applicability key has a valid current record as
  `resolved`, and continues at the first still-`open` item.
- **Append-only history + supersede (FR-076 / SC-033)**: changing an answer appends a **new**
  record obeying I1–I5. Nothing is mutated or removed; the full previous → replacement →
  currently-applicable chain (with each decision's run context) is recoverable by walking
  `sequence_index` / `supersedes`.
- **`resolution_id` — content-bound (M1)**:
  `resolution_id = sha256(canonical_json({ applicability_key, sequence_index, selected }))[:16]`,
  where `selected` is the full decision payload (`{mode, value}` for literal, `{order}` for
  reading-order). It is a **local-store traceability id**, not a cryptographic integrity digest
  (the artifact envelopes carry `run_id`; whole-file integrity is `sha256` of the file). 16 hex is
  sufficient: `sequence_index` alone already makes every record unique within a store, so the
  digest only needs to disambiguate content for cross-references.
- **Applicability key** (unchanged, FR-071): `sha256(source_sha256 ⧺ conflict_type ⧺
  canonical(page, bbox region, aligned candidate-value set) ⧺
  canonical_json(output_affecting_config_subset))`; the subset is `ocr_engine`,
  `ocr_languages_override`, `ocr_confidence_threshold`, and the enabled-path set. A changed
  context ⇒ key no longer matches ⇒ the stored decision is **not** replayed or silently reused
  (FR-071/FR-079) ⇒ a fresh item.
- **Entered-value fidelity (FR-068 / FR-082)**: for `mode: entered` the stored `value` is the
  reviewer's confirmed input **verbatim** — the workflow performs no `.strip()`, Unicode
  normalization, quote folding, separator rewrite, or autocorrect. `manually_verified: true`.

### 22.3 Review-item presentation data (FR-075)

The queue item carries, in addition to the FR-062a/FR-062d evidence: `structural_context`
(`{ section_path: [str]|null, table_id: str|null, row: int|null, column: int|null }`),
`source_context_before` / `source_context_after` (short verbatim windows of surrounding source
text), a human-readable `provenance_label` per candidate (e.g. `"layout path (docling), p.5"`,
`"geometry path (pdfplumber), p.5"`, `"OCR (tesseract; pt; conf 82)"`), and `segment_refs`
(internal `segment_id`s). `region_bboxes` stay for internal traceability. **No image / crop
fields** — the reviewer verifies against the PDF itself.

### 22.4 Processing-authorization state (FR-077)

Modelled as a **derived state over auditable records**, not a mutable flag. Evaluate the
conditions **in this precedence order — first match wins** (M11):

| # | Derived run state | Condition |
|---|---|---|
| 1 | `unresolved` | ∃ queue item still `open` (after applying the store, I1–I6). **A newly raised item always wins here, even if a prior authorization for some earlier `run_id` exists.** |
| 2 | `delivery_blocked_verification_failed` | no `open` items **and** a `human_review_verification` record for the **current** `run_id` exists with `summary.status == "FAIL"` |
| 3 | `delivered` | no `open` items **and** `<base>.md` exists whose `sha256` equals what this run renders **and** (if the run has ≥1 applicable decision) a `human_review_verification` record for the current `run_id` with `summary.status == "PASS"` **and** (for `convert`) a traceability record for the current `run_id` |
| 4 | `authorized` | no `open` items **and** a `review-authorizations.jsonl` line with `authorized_run_id == current run_id`. Rendering/verification may be in progress or not yet started — **still not `delivered`**; a restart safely re-runs render + verification (deterministic). |
| 5 | `resolved_unauthorized` | no `open` items and none of the above |

- After the reviewer answers the **last** open item the interactive workflow presents
  `["Review answers", "Continue processing", "Save and exit"]`. **"Continue processing"** appends
  a `review-authorizations.jsonl` line for the current `run_id` (`authorized_via:
  "interactive_continue"`) and then invokes the pipeline resume. **"Save and exit"** writes
  nothing new and leaves the run `resolved_unauthorized`.
- Opening `review` again in `resolved_unauthorized` presents `["Review answers", "Continue
  processing", "Exit"]` — never an automatic continuation (FR-077).
- **Authorization is `run_id`-keyed, so it cannot outlive its decision set.** Reopening and
  changing one answer appends a superseding resolution → the applicable set changes →
  `applicable_resolution_digest` and `run_id` change (§14) → **no** authorization event matches
  the new `run_id` → the run drops back to `resolved_unauthorized` and the reviewer must choose
  "Continue processing" again. Rationale: "no delivery on an obsolete authorization/decision set"
  becomes a **deterministic, mechanically-checkable** property — a successful delivery requires an
  authorization event whose `authorized_run_id` equals the delivered artifacts' `run_id`.
- **Authorization validity is exactly `authorized_run_id == current run_id`** (M2) — nothing
  else. There is **no `queue_sha256`**: the derived-`run_state` precedence already handles "a new
  item appeared" (step 1 wins) and "a decision changed" (`run_id` changed ⇒ no match), so a
  whole-queue-file hash would only add a self-invalidation hazard (the queue file is rewritten
  when `run_state`/`status` change).
- **Authorization event record (M4)**: an **append-only audit event**, one line per authorized
  `run_id`: `{ envelope, authorized_run_id, applicable_resolution_digest, resolved_item_ids
  (audit evidence — the item ids resolved at authorization time), authorized_via ∈
  {interactive_continue, cli_authorize} }`. No wall-clock, no random id (project convention), so a
  re-authorization of an unchanged decision set is an **idempotent no-op append**. It is **not**
  in the FR-053a run-twice deterministic-core artifact-equality set — it records a human action, a
  run-twice test never regenerates it. Auditability is preserved: every authorization, its
  `authorized_via`, and its decision-set digest are on the log.
- **No unverified Markdown at the deliverable name (H2)** — see §25.7.

### 22.5 Non-interactive sub-interface (automation / tests)

`review list` · `review show <id>` · `review resolve <id> (--select N | --value TEXT |
--value-file PATH | --order segId,…) [--note TEXT]` · `review authorize` · `review status`
[`--json`]. An **explicitly secondary** scripting surface (CI, deterministic tests, power users).
It obeys **identical** safety rules because they are enforced in the core, not the UI:
append-only store (I1–I6), `--order` = exactly the item's segment set, nothing patches Markdown,
`review authorize` requires zero `open` items and is `run_id`-keyed exactly like interactive
"Continue processing", location-aware verification at delivery.

**Exact-literal input (M10).** `--value TEXT` is for **simple single-line literals** whose
correctness does not depend on shell-preserved leading/trailing whitespace or a trailing newline.
**`--value-file PATH` is the normative mechanism** for any whitespace-/newline-sensitive exact
literal. `--value-file` semantics: read the file **bytes**; require valid UTF-8 (else exit **2**);
decode UTF-8; use the decoded string **verbatim** — leading/trailing spaces preserved, a trailing
newline preserved if present, a leading U+FEFF preserved if present; **no `.strip()`, no Unicode
normalization, no BOM stripping**. `--value TEXT` is likewise stored verbatim (argparse does not
alter it) but the *shell* may have already trimmed it — hence the `--value-file` normativity. The
interactive "Enter another value…" path stores the confirmed input verbatim (`questionary.text`
does not strip).

### 22.6 Exit codes

Reuse the existing table (no new codes — §12 / cli.md): `extract`/`convert` exit **6** whenever
the run is not a successful delivery for a review reason — `unresolved`, `resolved_unauthorized`,
or `delivery_blocked_verification_failed` — with the specific `run_state` in the message and in
`--json`. `review list/show/status` exit **0**; `review resolve`/`authorize` exit **0** on
success, **2** on bad input, **6** if `authorize` is attempted with `open` items remaining.
Interactive `review` interrupted with Ctrl+C exits **0** with progress saved (each confirmed
answer was already persisted); `7` only on genuine resource-exhaustion/abort with a half-written
artifact prevented.

### 22.7 `fix` → review routing (FR-045a / FR-084)

When `fix` reads a **`reconciliation_error`** issue it does not edit the Markdown; it writes/
updates a queue item for the underlying conflict and reports "N issue(s) routed to human review;
re-run after resolving (and re-authorize)".

A **human-review verification failure** is classified by *originating stage* (§25.6): a
`reconciliation_error` (the CED does not carry the human-confirmed decision — routes back to
`review`) or a **`disallowed_transformation`** (the CED is correct but a stage-3/5 transform
altered it — a deterministic-code defect). For the `disallowed_transformation` case the **preferred
repair is to fix the transform/render code and re-run** (deterministic); `fix` is the escape hatch
under the existing FR-040/FR-044 rules (restore source content in the flagged region only). **Any
`fix` output for a run that has ≥1 applicable human-review decision MUST re-enter Human-Review
location-aware verification against those decisions before it can be a successful delivery** — the
corrected Markdown flows `fix → render-into-staging → §25 verification → delivery gate`; `fix`
never *applies* or *invents* a human-review decision (FR-079).

### 22.8 Prompt-layer invariants (`questionary`, M9)

- **A resolution is persisted only after the prompt returns a confirmed, non-`None` answer.**
  `questionary.*.ask()` returns `None` on Ctrl+C / EOF; the workflow treats `None` **strictly as
  cancellation** — exit 0, nothing persisted for the current item, resume later at that item.
  Whether the implementation uses `unsafe_ask()` or explicit `None` checks is an implementation
  choice; the behavioural invariant is mandatory and gets a failing-first test.
- **Ctrl+C anywhere** → exit 0 with every *already-confirmed* answer durably saved (§22.2). No
  half-written store line (atomic publish). No partial `run_state` write.
- **Multiline entered values**: interactive mode uses `questionary.text(multiline=True)` when the
  source literal spans lines. If that proves insufficient for exact leading/trailing-whitespace
  fidelity in implementation testing, such an item is routed to `--value-file` (the workflow tells
  the reviewer to use the scripting path for that one item). Flagged as an implementation-time
  confirmation, not a blocker.
- **No `questionary` import outside `review/tui.py`** (import-graph test) — the workflow core,
  verification, and report code are headless.

**Alternatives considered**:
- *Keep the file/flag-only design*: rejected — FR-074 now mandates an interactive keyboard-driven
  terminal mode. (The flag interface survives as the secondary automation surface.)
- *A mutable `authorized: true` flag on the run*: rejected — a flag can drift out of sync with the
  decision set. Keying the authorization record to `run_id` makes "authorized for *these*
  decisions" a content-checkable fact and auto-invalidates on any change.
- *Let a changed answer keep the prior authorization*: rejected — could deliver output based on an
  obsolete decision set (FR-077 explicitly forbids this).
- *Store resolutions only in the per-run output dir*: rejected (unchanged) — a re-run in a fresh
  dir would lose them; a durable content-keyed store is the point.
- *Let the LLM pre-fill a suggested answer*: rejected for the persisted record — the human's
  decision is authoritative and no LLM may appear in `human_confirmed` provenance. (A read-only
  "the LLM would have picked candidate B" hint line is a possible future UX addition, clearly
  outside the decision.)

---

## 23. Intermediate-artifact persistence

**Decision**: persist what auditability / replay / resume / diagnosis need; regenerate the rest.

| Artifact | Persisted? | Why |
|---|---|---|
| **Extraction candidates** (per path) | **Yes, JSON only** — the machine-readable source of truth. **No `.md` companion.** | Needed to re-present evidence on resume, for `applicable_resolution_digest`, and for diagnosing which path erred. The **reconciliation log's `.md` rendering** is the human-facing diagnostic for what each path produced per conflict; a candidate is not a converted-document format and does not warrant a second representation (M1). A future `--dump-candidate` diagnostic MAY render one read-only, clearly non-authoritative. Reproducible per path (modulo the OCR engine + langdetect seed). |
| **Canonical Extracted Document** | **Yes, JSON only.** No `.md` companion. | The reconciliation state a resume run continues from; the input final validation checks against. Same rationale as candidates — the reconciliation log's `.md` is the human-facing view. |
| **Reconciliation log** | **Yes**, JSON + `.md` (FR-057) | Audit trail of every decision (Principle IV). |
| **Structural hints** | Inside candidates + CED | Not a separate artifact — they are attributed fields on segments. |
| **RunContext** | **Yes**, JSON + `.md` (`<base>.run-context.json`) | So `review` can recompute the *current* `run_id` (extract-stage §14 tuple) without re-prompting for flags (H3). Deterministic. |
| **Human-review queue** | **Yes**, JSON + `.md` | The `review` command reads it; `status` re-derived from the store on every load; blocks delivery. |
| **Resolution store** | **Yes**, append-only JSONL + `.md`, durable across runs, **atomic whole-file publish per append** (M3) | FR-057b; the deterministic replay input; `sequence_index`-authoritative (§22.2 I1–I6). |
| **Review authorization event log** | **Yes**, append-only JSONL + `.md` (`<base>.review-authorizations.jsonl`), per output dir | Human-action audit (M4); one line per authorized `run_id`; **outside** the FR-053a run-twice artifact-equality set; validity = `authorized_run_id == current run_id`. |
| **Human Review verification record** | **Yes**, JSON only, `intermediates/<base>.human-review-verification.json` | The authoritative machine model for FR-083/FR-084; deterministic; joins the FR-053a core. The Human Review Report renders from it. |
| **Human Review Report** | **Yes**, `.md` only (`<base>_review_report.md`), a **rendering** of the verification record | FR-080–FR-082; a delivery-time verification aid, not a store. Deterministic. |
| **RenderMap** | **Inside** the verification record (`lineage`) | Not a standalone artifact — the per-block / per-segment codepoint spans + `segment_transforms` needed for FR-083 (research §25.2). |
| **Semantic document** | **No** (ephemeral) | Deterministically regenerable from the CED by stage 3; persisting it would be a duplicate source of truth. A `--dump-semantic` diagnostic flag MAY write it, clearly marked non-authoritative. |
| **Removal log** | **Yes** (existing) | FR-011. |
| **Validation report** | **Yes** (existing) | FR-032. |
| **Correction log** | **Yes** (existing) | FR-042. |
| **Traceability record** | **Yes**, `convert` only, **only when `run_state == delivered`** (FR-051/FR-084) | FR-052; now also links the reconciliation log, queue, RunContext, authorization event, verification record, and Human Review Report. |
| **Original / corrected Markdown, DOCX** | **Yes** (existing) | The deliverables. The final Markdown is **published to `<base>.md` only after all delivery gates pass** (§25.7); an ungated render lives at `intermediates/<base>.<run_id>.unverified.md`. |

Candidates, CED, RunContext, verification record, and any `*.unverified.md` live under
`<output-dir>/intermediates/`; all artifacts are subject to the atomic-write (temp + fsync +
`os.replace`) + no-overwrite + reproducible rules; append-only stores use the atomic whole-file
publish (M3).

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

## 25. Review → final-Markdown lineage and location-aware verification (FR-083 / FR-084)

> New 2026-09-08. FR-083 forbids verifying a human-review decision by an arbitrary global string
> search of the final Markdown. This section fixes *how* each applicable decision is traced to
> its **specific rendered span** and checked there.

### 25.1 Markdown serialization and span locator (M5)

**Serialization** — the final `<base>.md` and every run-scoped staging Markdown are written
**identically and deterministically** across platforms:

- content is `str`; on disk it is `text.encode("utf-8")` written in **binary mode** — **never**
  Python text mode (which would translate `\n`→`\r\n` on Windows and break both offsets and byte
  identity);
- **no BOM**; line endings are **LF (`\n`) only** — the renderer never emits `\r`;
- **no Unicode normalization** (no NFC/NFD) — combining marks and astral (supplementary-plane)
  code points are written as authored;
- `markdown_sha256` in the envelope = `sha256` of those exact bytes.

**Span locator** — `delivered_markdown_text := <artifact bytes>.decode("utf-8")`. A span is a
**half-open Unicode-codepoint offset range `[start, end)`** into `delivered_markdown_text`;
`delivered_markdown_text[start:end]` is the **authoritative** slice. Rationale: Python-native
slicing, no UTF-8 multi-byte bookkeeping, deterministic (identical CED + `SemanticDocument` +
renderer ⇒ identical bytes ⇒ identical offsets), unambiguous under duplicate literals. A
verification record MAY *also* carry derived `byte_start` / `byte_end` (UTF-8 byte offsets) and a
derived `(start_line, start_col, end_line, end_col)` (1-based codepoint columns — validation-report
convention) as **integrity cross-checks / human display**, but there is exactly **one authority**:
the codepoint offsets. Byte offsets and pure line/col ranges were rejected as the *authority* —
byte offsets invite multi-byte mis-slicing; line/col can't hold exact leading/trailing whitespace
of a partial-line excerpt (FR-082) and shift when an earlier line changes.

### 25.2 The RenderMap and `segment_transforms` (H1)

`render/markdown.py` emits, beside the Markdown, a **`RenderMap`**:

- per `SemanticDocument` block: `{ block_id, span: [start,end) }`;
- per accepted `segment_id`: `{ segment_id, spans: [[start,end), …] }` — where that source
  segment's own text landed (a table cell, a clause inside a paragraph, a list item; **may be
  multiple spans** — M11);
- per collapsed segment (M7): `{ segment_id, collapsed_into: <retained segment_id>, rule }` — a
  segment that legitimately has **no standalone rendered span** because a permitted stage-3
  structural operation folded it into a canonical twin (repeated table-header collapse, FR-021;
  duplicate structural material). Verification follows the edge to the retained segment's spans.
  An **unrecorded** disappearance is *not* this — it is a fault (25.5).

**`segment_transforms` (replaces the old `segment_edits`).** Every deterministic operation that
changes a **segment's own character sequence** between the CED literal and the rendered bytes is
recorded as an **ordered, typed** list on the RenderMap for that segment. This is **not** an
"anything goes" normalizer — each entry MUST be an explicitly enumerated kind, deterministic, and
**traceable to a permitted specification rule**:

| kind | stage | permitted by | effect |
|---|---|---|---|
| `dehyphenate` | 3 | FR-014 | remove a trailing U+002D + line break, joining the word — **only** on the positive document-internal evidence pinned in §27 (default: keep the hyphen); the transform names the attesting token occurrence |
| `reflow_whitespace` | 3 | FR-013 / FR-016 | collapse an intra-segment hard line break to a single space |
| `markdown_escape` | 5 | renderer contract (FR-012 output) | escape Markdown-significant chars the value contains so they render literally (`\|` in a pipe cell; a leading `#`/`>`/`-`/`*`/`+`/`_`/`1.` at a line start; `` ` ``) |
| `html_escape` | 5 | FR-020–FR-022 (HTML `<table>` path) | `&`→`&amp;`, `<`→`&lt;`, `>`→`&gt;` inside an HTML table cell |
| `cell_newline_br` | 5 | FR-020–FR-022 | a hard line break inside an HTML table cell → `<br>` |
| `ocr_marker` | 5 | FR-025 | the renderer's OCR-derived marker syntax wrapped **around** the value (kept here only if the marker is inline; a block-level marker is envelope, not a segment transform) |

Everything else — reflow whitespace *between* segments, `#`/list-marker/table-pipe **envelope**,
`structural_reorder` of *whole blocks*, `hint_decisions` — operates on the envelope **around** a
segment, not its characters, and is already logged elsewhere. If the renderer ever needs a new
intra-segment transform, it is added to this enumeration **with its permitting FR** — not silently.

### 25.3 Lineage chain and authority boundary

**Authority boundary.** Human Review confirms **source-backed content** — the CED literal (or the
CED reading order). Everything downstream — hyphen repair, reflow, escaping, table rendering,
structural reordering — is a **separate, traceable operation** recorded in the RenderMap /
reconciliation log / removal log. Verification's job is to prove: *the delivered span equals the
human-confirmed source literal after applying **only** the recorded permitted transform chain*.

Per applicable `human_confirmed` decision the workflow builds a `ReviewRenderLineage`:

```
review_item_id → applicability_key → conflict_type
  → accepted_segment_ids            (CED: 1 for literal_content; N for reading_order)
  → reconciliation_decision_id      (the human_confirmed ReconciliationDecision; null ⇒ CED
                                     does not carry this decision — 25.6 defect classification)
  → ced_accepted                    literal: the CED AcceptedSegment.text for the segment
                                    order:   the CED accepted order of the reviewed segments
  → semantic_block_ids              (SemanticDocument blocks whose provenance ⊇ those segments)
  → render_span + per_segment_spans (RenderMap; following collapsed_into where present)
  → segment_transforms              (ordered, per 25.2, for the reviewed segment(s))
  → expected                        literal: the human-confirmed value (verbatim)
                                    order:   accepted_segment_ids in the confirmed sequence
```

A hop that cannot be resolved marks the lineage `incomplete` and drives `not_located` (25.5).

### 25.4 Literal final-Markdown evidence

For a **located** decision, `final_markdown_excerpt` =
`delivered_markdown_text[render_span.start : render_span.end]` **verbatim**. Stored on the
verification record and copied unchanged into the Human Review Report — no `.strip()`, whitespace
collapse, Unicode/punctuation normalization, separator rewrite, or `<< >>` insertion (FR-082). The
Report may print prose *around* it and MAY mark up the separate *source-context* copy, never the
excerpt. For a **`not_located`** decision there is no authoritative span, so
`final_markdown_excerpt`, `render_span`, `per_segment_spans`, and `final_markdown_span_lc` are
**`null`** (H4).

### 25.5 Verification model

Per applicable decision, a `HumanReviewVerification` item:

| Field | present when |
|---|---|
| `review_item_id`, `applicability_key`, `conflict_type`, `resolution_id` | always |
| `status` (`applied_and_verified` \| `verification_failed`) | always |
| `failure_reason` (`not_located` \| `literal_altered` \| `order_not_reflected`) | only on failure |
| `defect_class` (`reconciliation_error` \| `disallowed_transformation` \| `extraction_error`) | only on failure (25.6) |
| `lineage`, `expected` | always (lineage may be `incomplete`) |
| `render_span`, `per_segment_spans`, `final_markdown_span_lc`, `final_markdown_excerpt` | **non-null iff the reviewed location resolved** (i.e. not `not_located`); `null` for `not_located` |

**Check — `literal_content`.** `expected_rendered = apply(segment_transforms, human_confirmed_value)`
— apply the recorded ordered chain (25.2) and **nothing else**. `status = applied_and_verified`
iff `expected_rendered` equals **exactly** `delivered_markdown_text[per_segment_span]` for the
reviewed segment (each of its spans, in order, concatenated if multiple — M11). Any residual
difference in the segment's own characters (interior spacing, a swapped decimal/thousand
separator, a Unicode look-alike, altered punctuation) is **not** an allowed transformation ⇒
`verification_failed / literal_altered`.

**Check — `reading_order` (M8).** For each reviewed segment resolve its **first** authoritative
rendered span = the lowest `start` among its `per_segment_spans` (following `collapsed_into`).
`status = applied_and_verified` iff the first-span starts are **strictly increasing in the
human-confirmed order**. If a logged `structural_reorder` whose `affected_segment_ids` ⊇ the
reviewed set exists, it passes **only if all three hold**: (a) its `from_order` restricted to the
reviewed segments equals the human-confirmed order; (b) the actual rendered first-span order of
the reviewed segments equals its `to_order` restricted to them; (c) its `scope`/`reason` is a
permitted stage-3 structural operation (FR-020–FR-022). Otherwise ⇒
`verification_failed / order_not_reflected`.

**`not_located`.** The lineage is `incomplete` (no `reconciliation_decision_id`, no
`semantic_block_ids`, no render span) **or** the reviewed segment has no rendered span and no
recorded `collapsed_into` — i.e. it disappeared without a recorded permitted operation.

**Determinism.** The whole verification is a pure function of `(delivered_markdown_text, RenderMap
incl. segment_transforms, CED decisions, currently-applicable resolutions, RunContext)` — all
pinned by `run_id`. Reproducible; the verification record + Report **join the FR-053a
deterministic core** (§14). *(The authorization event does not — it is a human action, §22.4.)*

### 25.6 Root-cause defect classification and validation integration (FR-084 / FR-034a / FR-073, H5)

A `verification_failed` item is classified by the **stage that introduced the fault**, consistent
with FR-034a — it is a *detector*, it must not erase root cause:

| condition | `defect_class` | repair routing |
|---|---|---|
| `ced_accepted` ≠ the human-confirmed decision (or `reconciliation_decision_id` is `null` / not `human_confirmed`) — reconciliation did not apply the decision (replay/applicability/`canonical_build` fault) | **`reconciliation_error`** | back to the `review` layer (FR-045a); the reviewer re-checks / re-decides; the resolution set (+ `run_id`) changes; re-authorize; the pipeline re-renders and re-verifies |
| `ced_accepted` **==** the human-confirmed decision, but the rendered span differs by something outside the recorded `segment_transforms` chain, or the segment vanished with no recorded `collapsed_into` / removal — a **stage-3 or stage-5 deterministic-code fault** | **`disallowed_transformation`** | **preferred**: fix the transform/render code + re-run (deterministic). Escape hatch: `fix` restores source content in the flagged region only (FR-040/FR-044); the corrected Markdown **MUST re-enter §25 verification** against the applicable decisions before it is a successful delivery (§22.7). `fix` never applies/invents a decision (FR-079). |
| the fault is genuinely in the source evidence / extraction and is not a human-review application failure (rare — the confirmed value itself was wrong) | **`extraction_error`** | normal extraction-fault handling; a *new* review item if it affects a below-threshold conflict |

Every `verification_failed` item is **also emitted as a validation issue**:
`check_origin: deterministic`, `severity: error`, the `defect_class` above, `review_item_id` set,
`reconciliation_ref` = the `human_confirmed` decision id when present,
`issue_type ∈ {literal_mismatch (literal_altered), reading_order (order_not_reflected),
missing_content (not_located)}`. It **blocks successful delivery** — `run_state`
`delivery_blocked_verification_failed`, `extract`/`convert` exit **6**. The rendered Markdown for
the failing run lives **only** at the run-scoped staging path (§25.7) — never at `<base>.md` — and
is not linked as a delivered artifact.

**Alternatives considered**:
- *Search for the confirmed string anywhere in the Markdown*: rejected by FR-083 — false PASS when
  the value happens to occur elsewhere.
- *Classify every verification failure as `reconciliation_error`* (the earlier draft): rejected —
  when the CED is correct and stage 3/5 broke it, routing the reviewer to re-decide is an
  unrepairable loop and hides an engineering defect. Stage-based classification (H5) fixes this.
- *A rich per-character failure taxonomy*: rejected as over-engineering — `not_located` /
  `literal_altered` / `order_not_reflected` × `defect_class` is enough to route and diagnose; the
  excerpt + `expected` already show *what* differs.

### 25.7 Artifact publication and write ordering (H2)

**The successful-deliverable name `<base>.md` MUST NOT ever hold an unverified Markdown.** The
pipeline (`extract`, and the `extract` portion of `convert`) proceeds:

```
1. render → intermediates/<base>.<run_id>.unverified.md   (run-scoped; atomic temp+fsync+os.replace)
2. stage-4 built-in deterministic final-fidelity self-check  (existing)
3. if the run has ≥1 applicable human-review decision:
     §25 location-aware verification against the file from (1)
     → write intermediates/<base>.human-review-verification.json  (atomic)
     → write <base>_review_report.md                              (atomic)
4. delivery gate — ALL must hold: no open items; an authorization event with
   authorized_run_id == run_id; stage-4 passed; (if applicable) verification summary.status == PASS
5. gate passes → publish: atomic temp+fsync+os.replace of the staged Markdown to <base>.md;
   then (convert) write the traceability record last
6. gate fails → the staged intermediates/<base>.<run_id>.unverified.md is RETAINED for audit;
   <base>.md is NOT written/replaced; run_state ∈ {resolved_unauthorized,
   delivery_blocked_verification_failed}; exit 6
```

- A crash between steps 1–5 leaves **no `<base>.md`** → a re-run re-renders + re-verifies
  (deterministic, identical result) and publishes.
- A crash after step 5 leaves a valid `<base>.md`; a re-run finds byte-identical content →
  satisfied no-op → writes the traceability record (convert).
- **Prior successful delivery + later changed decision.** The new run has a different `run_id` and
  would render different bytes. `<base>.md` already exists with the old content ⇒ **FR-054
  collision (exit 5), the existing file is preserved**, and the user is told to choose a fresh
  `--output-dir`. The changed decision does not silently overwrite the earlier delivered artifact.
  (The run-scoped `intermediates/<base>.<run_id>.unverified.md` for the *new* `run_id` is a
  different name — no collision there.)

---

## 26. Human Review Report architecture (FR-080–FR-082)

> New 2026-09-08.

**Decision**: the Human Review Report is a **rendered, human-readable Markdown artifact**
generated **from** an authoritative machine model (`HumanReviewVerification` record, contract
`human-review-verification.schema.json`). It is **not** a second source of truth and holds no
state that isn't derivable from: the human-review queue, the append-only resolution history (⇒
currently-applicable decisions via `sequence_index`, §22.2), the authorization event log, the
`RunContext`, the review→render lineage + `segment_transforms` (§25.2–25.3), the delivered
Markdown, the verification results (§25.5), and the validation report. The report renderer
**never re-derives PASS/FAIL** — it prints `human_review_verification.summary.status` verbatim.

- **Naming**: `<base>_review_report.md` — `<base>` = `<stem>[__p<sel>]`, the same output base every
  other artifact uses (cli.md), i.e. spec FR-080's `<output-base>` = the delivered Markdown's stem.
  Machine model: `<base>.human-review-verification.json` in `intermediates/` (the authoritative
  input the `.md` renders from — one model renders both, same as every other FR-057 record pair).
- **Generation stage**: after stage 5 render and after §25 verification, **only when the run
  reaches `authorized` and has ≥ 1 applicable human-review decision**. If verification fails, the
  report is still generated (it must show the failure — FR-084) but the run is
  `delivery_blocked_verification_failed`, not `delivered`.
- **Required summary** (FR-080): source document identity (`source_pdf` + `source_sha256`);
  delivered Markdown identity (path + `markdown_sha256` + `run_id`); counts —
  `decisions_applicable`, `resolved`, `verified`, `failed`; **overall status** `PASS` iff
  `failed == 0 && verified == decisions_applicable`, else `FAIL`.
- **Required per-item content** (FR-081), presented as **three distinct things** (M6):
  1. the **human-confirmed source literal / order** — exactly as stored (verbatim), labelled as
     source-backed content;
  2. any **applied permitted transformations** — the ordered `segment_transforms` chain with each
     kind's permitting FR (e.g. "line-break hyphen repaired — FR-014"; "`|` escaped for the pipe
     table"), shown only when non-empty;
  3. the **actual final-Markdown evidence** — the literal excerpt (§25.4), or, for `not_located`,
     an explicit "not located in the delivered Markdown" line with the failure reason;
  plus PDF page; structural context (section / table / row / column where known); source context
  before/after; the candidates offered; and the status (`APPLIED AND VERIFIED` /
  `NOT APPLIED — VERIFICATION FAILED` + `failure_reason` + `defect_class`).
- **Source-context highlighting** (FR-082): the *source-context* line (item 1's surrounding
  window) MAY carry report-only markers (e.g. `Apartamento 42 | << R$ 1.599,80 >>`). The
  *final-Markdown excerpt* (item 3) MUST NOT — it is copied verbatim from the delivered artifact
  via `render_span`. The two are visually and structurally distinct in the report.
- **PASS/FAIL**: printed verbatim from `summary.status` (which the verification pass derived from
  the counts: `PASS` iff `failed == 0 && verified == decisions_applicable`). No separate verdict.
- **Relationship to the traceability record**: `convert` links the report (`.md` + machine
  model) in `TraceabilityRecord.artifacts.{human_review_report, human_review_verification}` and
  the `review_authorization` event log, and records a one-line
  `human_review_verification_summary: { applicable, verified, failed, status }`. A `convert` run
  that ends `delivery_blocked_verification_failed` (or `resolved_unauthorized`) emits **no**
  traceability record (same rule as stopping at the queue, FR-051) — it emits the queue, the
  report, and the intermediates.
- **Reproducibility**: the verification record and the Report are **deterministic derived
  outputs** (§14) — no wall-clock, no random id; byte-identical for identical effective inputs;
  they **join the FR-053a deterministic core**. The **authorization event log does not** — it is
  a human-action audit record outside the run-twice artifact-equality set (M4).

**Alternatives considered**:
- *Make the report itself a machine-readable authoritative store*: rejected — FR-080 explicitly
  says it is a verification aid, not the audit log; the resolution store + reconciliation log +
  verification record already hold every fact.
- *A dedicated JSON schema for the Markdown report*: rejected — the authoritative structured data
  is `human-review-verification.schema.json`; the `.md` is a rendering of it (instruction:
  "render Markdown from one authoritative machine model").

---

## 27. Stage-3 de-hyphenation policy (v1)  *(AUTHORITATIVE — 2026-09-09 audit remediation)*

> Pinned **before** T066/T067 so the de-hyphenation transform can be encoded test-first and
> unambiguously. This section is the single authority for when `transform/reflow.py` may remove a
> line-boundary hyphen; FR-014 and the `dehyphenate` row of §25.2 reference it. Stage 3 only — it
> operates on the CED in `accepted_reading_order`, never during extraction or reconciliation, and
> the CED literal is never mutated in place (a removal is a recorded `SegmentTransform`, §25.2).

**Default: keep the hyphen.** A trailing U+002D HYPHEN-MINUS at a visual line boundary is
**preserved**. It is *not* removed merely because it sits at the end of a rendered line.

**Removal requires positive, deterministic, document-internal evidence.** A trailing U+002D may be
removed and the two fragments joined **only** when the **joined token — the two fragments
concatenated with the boundary hyphen deleted and nothing else — occurs elsewhere in the *same
CED* as a complete token** (whitespace-/punctuation-delimited, compared under the §21b
comparison-key normal form, case-insensitively for this lookup only). This is the *only* accepted
positive lexical signal for v1. **No external dictionary, no LLM, no network/service, no
statistical language model, no morphological guesser.**

**Structural preconditions — all must also hold** (they gate, they never substitute for the
lexical evidence):

- the next fragment is the **immediately following segment in accepted reading order**;
- both fragments share a compatible paragraph / line context (same block candidate; not across a
  heading, list-item, table-cell, or caption boundary that forbids the join);
- **same physical page** (v1 does not join across a page break — no existing rule permits it);
- same logical column / band (the §21c band model);
- the fragment **before** the hyphen ends with **at least two** Latin-script letters;
- the fragment **after** the hyphen **begins with a lowercase Latin-script letter**;
- the boundary character is **exactly U+002D** — never U+2010/U+2011/U+2012/U+2013/U+2014 (en/em/
  figure dashes) and never a soft hyphen U+00AD (already comparison-only noise, never a stored
  join trigger);
- the hyphen is **not** part of a legal numbering / range / dash pattern — not preceded by a digit
  or a space in a construct like `12-`, `A-`, `1998-`, `pp. 3-`;
- no table / list / heading envelope forbids merging the two fragments' segments;
- if either fragment is OCR-derived **below** the accepted OCR-confidence condition, stay
  conservative — **keep the hyphen**.

**Ambiguous or insufficient evidence ⇒ keep the hyphen.** Stage 3 never guesses. A retained
line-boundary hyphen that a human considers wrong is a **validation** finding later (FR-034a), not
a Stage-3 repair.

**Compound / lexical hyphens are always kept** — `IGP-M`, `compound-word`, `e-mail`, hyphenated
surnames. The rule above only *ever* removes a hyphen when the un-hyphenated joined form is
independently attested in the document; a genuine compound almost never is.

**Audit.** Every removal records a `dehyphenate` `SegmentTransform` (§25.2, `stage: 3`,
`permitted_by: FR-014`) against the affected source segment(s), naming the segment it was joined
with and the attesting complete-token occurrence (segment id + span) that supplied the evidence.
No silent literal change: the RenderMap chain must explain the delta between the CED literal and
the rendered bytes.

**Fixture expectations.** A fixture or manifest that expected a line-break hyphen removed *without*
this positive document-internal evidence has its expected-transform note updated to "hyphen
retained (no in-document attestation of the joined token)" — the rule is not weakened to match an
old fixture. `clean_transform.pdf` is annotated accordingly (`tests/fixtures/manifests.py`).

**Alternatives considered.**
- *Bundled word list / spell checker*: rejected — a dependency, a locale surface, and a second
  source of truth about "is this a word"; also defeats the local-first / deterministic-bytes
  guarantee across environments.
- *Always de-hyphenate at a line end, keep only doubled hyphens*: rejected — silently corrupts
  compounds and legal identifiers (`IGP-M` → `IGPM`), the exact failure FR-014 calls out.
- *LLM judgement on each boundary*: rejected — Stage 3 has no LLM (T074); it would author text.

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
- **§22 terminal library** — `questionary` **selected** (`2.1.1`); the exact `questionary` /
  `prompt_toolkit` (`3.0.53`) / `wcwidth` pins + a fresh 7-day-rule check are recorded in the
  plan.md ledger at the first `review`-workflow implementation task (deferred like `docling`),
  not in this turn.
- **§25 implementation-local (pinned enough for tasks)** — the exact `source_context_before/after`
  window size for FR-075 (a small character budget, e.g. ≤120 chars each side); whether
  `questionary.text(multiline=True)` is sufficient for multi-line entered literals or such items
  route to `--value-file` (M9 — confirm during the review-TUI task, behaviour is already pinned
  either way); the multi-writer `sequence_index` rule (v1 is single-process — append + `max+1` +
  I1–I6 is sufficient; a shared multi-writer store would need a lock, out of v1 scope).
- **Phase 1 refinements** (in `data-model.md` / contracts): exact `ValidationIssue` enum values;
  heading-inference thresholds; table-stitch heuristics; match-rate token normalization; bbox IoU
  + Jaccard thresholds for alignment; Kendall-τ threshold for reading-order disagreement; the
  confidence functions (literal & reading-order); the exact `RenderMap` per-segment sub-span
  shape for merged HTML-table cells (multiple spans per segment is already modelled).
