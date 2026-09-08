# Implementation Plan: Local-First PDF Document Converter

**Branch**: `001-pdf-markdown-converter` | **Date**: 2026-09-07 (Human Review evolution 2026-09-08) | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/001-pdf-markdown-converter/spec.md`
**Constitution**: [`.specify/memory/constitution.md`](../../.specify/memory/constitution.md) **v2.0.0**

> This plan is a **full rewrite** for the current spec. It supersedes the earlier
> sequential single-extraction plan. Where the previous `plan.md`, `research.md`,
> `data-model.md`, `contracts/`, `quickstart.md`, or `tasks.md` conflict with this
> plan or the current spec, **this plan and the spec win**.

## Summary

A local CLI tool (`solari-convert`) that converts a single PDF into semantically
structured, UTF-8 Markdown — and optionally DOCX — with verifiable fidelity, an
auditable provenance chain, and an explicit human-in-the-loop for anything the
tool is not confident about.

The pipeline has five ordered stages (FR-059):

1. **Independent multi-path extraction** — the original PDF is processed by three
   isolated extraction techniques that never consume each other's output:
   **Docling** (path A), **pdfplumber + pypdfium2** (path B), and **conditional
   region-aware local OCR** (path C). Each produces an *extraction candidate*: a
   set of *source-backed segments* carrying literal text, geometry, that path's
   *candidate reading order*, *structural hints*, and provenance.
2. **Extraction reconciliation** → the **Canonical Extracted Document** (CED).
   Two independent sub-processes: **literal-content reconciliation** (which
   existing extracted text is accepted) and **reading-order reconciliation** (the
   accepted ordering of the accepted segments). Deterministic where the evidence
   agrees / geometry resolves it; otherwise a local LLM may **select among
   existing candidates only** (≥ 0.75 confidence), enforced by a programmatic
   guard; below 0.75 → **HUMAN_REVIEW_REQUIRED**. Human resolutions are persisted,
   auditable, and replayed deterministically. No semantic normalization here.
3. **Semantic transformation** (deterministic, no LLM) → the **Semantic
   Document**: reflow, de-hyphenation, heading/hierarchy inference, list & clause
   reconstruction, multi-page table stitching, non-semantic artifact removal. May
   *consult* the carried structural hints; the accepted reading order is fixed and
   preserved.
4. **Final fidelity validation** — the Semantic Document vs the original PDF **and**
   the independent extraction evidence **and** the reconciliation provenance;
   deterministic checks + one read-only local-LLM semantic pass; every issue
   classed `extraction_error` / `reconciliation_error` / `disallowed_transformation`.
5. **Final Markdown delivery** — rendered from the validated Semantic Document, per
   the validation policy, **blocked while any HUMAN_REVIEW_REQUIRED item is open**.

**Operations**: `extract` (stages 1–3 + a deterministic self-check + render; no LLM
required), `validate` (full stage 4), `fix` (post-transformation Markdown
corrections; routes `reconciliation_error` back to review), `export` (Markdown →
DOCX), `convert` (extract → validate → optional export), and **`review`** — an
**interactive, keyboard-driven terminal workflow** (FR-074, research §22): resolve
queue items with Up/Down/Enter or "Enter another value…", each answer persisted
immediately, browse/reopen/change earlier answers (append-only history), then an
explicit **Continue processing / Save and exit** choice — resolving the last item
never auto-continues. After authorization, decisions flow back through
reconciliation → CED → transform → validate → render (never a Markdown patch), and
every applicable decision is **location-aware-verified** against its rendered span;
a delivered run also produces a **Human Review Report** (`<base>_review_report.md`).
A non-interactive `review list/show/resolve/authorize/status` sub-interface exists
for automation and tests.

**Constitution v2.0.0 posture**: dependency count is **not** an objective. Docling
and a neural OCR option are admitted because they materially improve extraction and
reading-order fidelity and reduce fragile in-house heuristics; each dependency
carries a written justification (ledger below). Everything runs locally — models
may be downloaded once from documented sources, but document content never leaves
the machine (Principle V, unchanged).

## Technical Context

**Language/Version**: Python — minimum **3.12**, development and CI pinned to
**3.13**. (Docling and `onnxruntime` wheel coverage is the gating factor for the
floor; revisit before release.)

**Primary dependencies** — see the **Justified-Dependency Ledger** in the
Constitution Check section for the per-dependency rationale. Summary:

| Dependency | License | Role |
|---|---|---|
| `docling` | MIT | Extraction path A: layout-aware text + reading-order + structure **evidence** |
| `pdfplumber` (on `pdfminer.six`) | MIT | Extraction path B: per-word geometry, deterministic geometric baseline, table detection |
| `pypdfium2` | BSD-3 / Apache-2.0 | Page rasterization for OCR input; page dimensions; no system binary |
| **OCR engine — BENCHMARK-GATED** | — | Path C. `rapidocr-onnxruntime` (PP-OCR, Apache-2.0) **vs** `pytesseract` → system `tesseract` 5 (Apache-2.0). **No default chosen in this plan.** |
| **Language detector — re-open** | — | `langdetect` vs `lingua-language-detector` vs engine-native. Pluggable; re-evaluated on accuracy in research §5 |
| `python-docx` | MIT | `export`: Markdown → DOCX with explicit Word styles + merged cells |
| `pydantic` v2 | MIT | All entity models; JSON (de)serialization; JSON Schema generation for contracts |
| `httpx` | BSD | Local-LLM client (OpenAI-compatible) — used by **reconciliation** candidate-selection and by **validation** semantic pass |
| CLI: stdlib `argparse` | — | Sufficient for six subcommands; the simplest tool that meets the requirement |
| `questionary` (→ `prompt_toolkit` → `wcwidth`) — **proposed, deferred** | MIT / BSD | Interactive `review` terminal UI (FR-074); pure-Python, no network; added at the first `review` task, not T002 (see ledger + research §22.1) |
| Dev: `pytest`, `reportlab`, `pytest-benchmark` (or a plain harness), `jiwer` (CER/WER for the OCR benchmark) | MIT/BSD | Fixtures, tests, OCR benchmark scoring |

**Storage**: Filesystem only. Per-run artifacts → a user-specified output directory
(never the source PDF's directory by default). The **human-review resolution store**
is a durable append-only file (`resolutions.jsonl` + `.md` rendering) at a
user-controlled location (default: alongside the output directory), surviving
across runs.

**Testing**: `pytest`. Synthetic fixture PDFs generated at test time with
`reportlab` (no committed binaries), plus one committed real-world sample used only
under `-m acceptance`. An autouse fixture blocks non-loopback sockets. A fake
local-LLM HTTP server fixture (modes: normal / always-500 / slow / unparseable /
returns-non-candidate) backs reconciliation and validation tests. A "run twice"
helper asserts byte-identical artifacts.

**Target platform**: Local CLI on macOS and Linux; Windows best-effort (Docling +
`onnxruntime` + optional `tesseract` all have Windows wheels/binaries, but not
validated in CI for v1).

**Project type**: Single project — local CLI application.

**Performance goals**: No fixed page-count / file-size limit (FR-058). The three
extraction paths run **concurrently** per document (process pool); Docling and OCR
dominate cost. Target: a few-hundred-page text-layer PDF converts in single-digit
minutes on a laptop; OCR-heavy or Docling-heavy documents scale with page count and
CPU. Resource exhaustion fails cleanly (SC-016), never a partial artifact presented
as complete.

**Constraints**:
- Zero outbound network on the default path (SC-008); models are downloaded ahead
  of time from documented sources and cached locally (Principle V).
- All artifact writes atomic (temp file + `os.replace` in the destination dir).
- Source PDF and any intermediate artifact never overwritten (FR-054); the
  resolution store is append-only (FR-057b).
- **Intermediate persistence is always on (v1 decision, research §23).** The
  extraction candidates and the Canonical Extracted Document are persisted as
  authoritative JSON intermediates, alongside the reconciliation / human-review /
  audit intermediates — all required for provenance, diagnostics, deterministic
  replay, human review, failure analysis, and reproducibility. v1 ships **no
  `--no-intermediates` mode**; disk usage is an accepted trade-off. Future
  retention/cleanup is a separate additive concern that must not weaken
  auditability or reproducibility (not a v1 requirement).
- **Reproducibility — two levels (FR-053a + FR-053b / SC-009)**:
  - **Deterministic core (FR-053a)**: identical `(source hash, normalized selection,
    enabled paths, OCR engine+model+config, reconcile threshold, tool version,
    applicable human resolutions)` ⇒ byte-identical
    `original Markdown`, DOCX (normalized metadata/ZIP), and the **deterministic
    records** (removal log; the reconciliation log's `deterministic_agreement` +
    `human_confirmed` decisions; traceability record; every `check_origin:
    "deterministic"` part of a validation report). Records carry no wall-clock
    timestamp / random id; `run_id` is a pure digest of that tuple — no
    wall-clock/random workaround. v1 semantic transformation is deterministic and
    exposes no user-configurable or otherwise output-affecting settings, so it
    contributes nothing to the tuple or `run_id`; any future output-affecting
    semantic-transformation configuration must be added to the tuple and run
    identity (FR-053a). `langdetect`/detector seed pinned; all LLM calls
    `temperature=0` + fixed `seed`; the reconciliation double-call flip check
    (research §4a) turns backend nondeterminism into a review item, not a
    reproducibility violation.
  - **LLM-assisted audit results (FR-053b)**: the validation report's
    `check_origin: "semantic"` section is byte-identical **only when the backend
    honours `seed`** (probed once and recorded as `llm.reproducibility:
    "deterministic"`). Otherwise it is `"best_effort"`: the tool does not claim
    byte reproducibility for a *newly generated* semantic section; instead
    `pipeline/validate` **replays** an already-persisted valid report for the
    identical applicability context rather than regenerating, so a re-run
    reproduces the same bytes by replay and never raises a collision. The
    reproducibility level is recorded in the validation report and the
    traceability record.
- **No LLM text authorship anywhere** (FR-029/FR-061a/FR-066b): the LLM only
  *selects* among supplied candidates (reconciliation) or *detects issues*
  (validation). A programmatic guard rejects any LLM output not byte-identical to a
  supplied candidate / a geometry-supported order.

**Scale/scope**: One source PDF per invocation (no batch). Six operations. Any
document size within machine resources.

## Constitution Check

*GATE: must pass before Phase 0. Re-checked after Phase 1 (below).*

### Principle-by-principle

| Principle | Verdict | Basis |
|---|---|---|
| **I. Content Fidelity** | PASS | Verbatim text always comes from a PDF text layer or local OCR (FR-029). The LLM never authors text — reconciliation is candidate-selection with a programmatic guard (FR-061a/b), validation is read-only (FR-037). Every accepted value traces to its contributing source(s) (FR-066). Multi-path extraction reduces the chance a single technique's error reaches the output. |
| **II. Semantic Structure Preservation** | PASS | Structure is inferred only in stage 3, deterministically, on a reconciled pre-normalization CED; structural hints (incl. Docling's) are advisory and their use is recorded (FR-064). Reading order is a first-class reconciled decision (FR-061d), preserved unchanged downstream (FR-015). Checked by final fidelity validation (FR-065), not assumed. |
| **III. Validation Before Delivery** | PASS (**strengthened 2026-09-08**) | Stage 4 final fidelity validation runs on every path; `extract` includes a deterministic self-check and delivers Markdown only per the validation policy; `convert` always runs the full `validate`. Successful delivery is now blocked on **three** conditions: no open review item (FR-072), explicit downstream-processing authorization (FR-077), **and** every applicable human-review decision passing **location-aware final verification** at its rendered Markdown span (FR-083/FR-084). A verification failure enters the same `reconciliation_error` validation/audit path (FR-034a/FR-045a). |
| **IV. Controlled, Auditable Correction (NON-NEGOTIABLE)** | PASS (**strengthened 2026-09-08**) | Every reconciliation decision (deterministic / llm_selected / human_confirmed) is logged with its competing candidates and provenance (FR-057a). Human resolutions are **append-only** — a changed answer is a new record with `supersedes`, the prior decision is never erased (FR-076); the full previous→replacement→currently-applicable chain is recoverable. No destructive update anywhere in the review workflow. Decisions are applied only by re-running the pipeline from the CED — **never** by editing the Markdown (FR-079). `fix` changes only report-flagged regions, never patches a `reconciliation_error` or a verification failure (FR-045a/FR-084). |
| **V. Local-First & Data Privacy** | PASS (unchanged) | Every stage runs on the user's machine, incl. Docling, OCR, and the LLM (local OpenAI-compatible endpoint). The interactive `review` layer (`questionary` → `prompt_toolkit` → `wcwidth`, research §22.1) is **pure-Python terminal I/O with no network path**; the autouse no-egress test still holds and covers it. No model/data download. |
| **VI. Test-First (NON-NEGOTIABLE)** | PASS | `/speckit-tasks` will order contract tests (JSON Schemas + CLI contract) and per-user-story integration tests before implementation. The reconciliation guard, the human-review lifecycle, the interactive-terminal flow (driven by scripted key sequences via `prompt_toolkit`'s pipe input / `questionary` injectable I/O, plus the non-interactive sub-interface), immediate-persistence/resume, append-only supersede, the authorization gate, the review→Markdown lineage, location-aware verification, and the OCR benchmark all get failing tests first. All review **logic** lives outside the prompt layer and is unit-testable directly. |
| **VII. Simplicity & Justified Dependencies (v2.0.0)** | PASS | See the ledger below. Dependency count is not minimized; each component is justified against fidelity / validation / diagnosability / maintainability / operational cost / local-first. Heavier components (Docling, a neural OCR option) are admitted where they materially improve fidelity or replace fragile heuristics. Nothing gratuitous, duplicative, or unexplained. Exact-pinned versions; supply-chain checks retained. |

### Justified-Dependency Ledger (replaces the old "seven runtime dependencies" framing)

Format: **fidelity / validation / diagnosability / maintainability / operational cost / local-first**.

- **`docling`** —
  *Fidelity*: strongest available local layout analysis, reading-order inference, and table-structure detection; a materially better reading-order **candidate** on multi-column / complex legal layouts than pure geometry.
  *Validation*: gives final validation a second independent structural opinion to check against.
  *Diagnosability*: replaces a large body of fragile in-house heading/column/reading-order heuristics with a maintained component whose output is inspectable evidence.
  *Maintainability*: actively maintained (IBM); MIT.
  *Operational cost*: **high** — pulls a deep-learning runtime (`torch` or `onnxruntime`) + layout models (~hundreds of MB, one-time download). Acceptable under VII v2.0.0; mitigated by pinning model versions and documenting the download source.
  *Local-first*: fully local after the one-time model fetch; no content egress.
  *Install timing*: declared and installed at **T046** (immediately before path A's first use), not at T002 — Docling's transitive closure (`torch` / Hugging Face / `docling-*`) publishes too frequently to satisfy the 7-day supply-chain rule at an arbitrary date; T046 records the exact pinned versions and any per-package exception here. `docling` remains a **mandatory** `[project.dependencies]` entry (path A / FR-060).
  *Rejected alternative*: hand-built layout heuristics — higher fidelity risk, far more custom code, harder to diagnose (the exact objection VII v2.0.0 removes for Docling).
- **`pdfplumber` (+ `pdfminer.six`)** —
  *Fidelity*: exact per-word coordinates and font metrics — the **deterministic geometric ground truth** for reading-order reconciliation and for segment alignment.
  *Validation*: independent literal-text + geometry evidence to check the Docling and OCR candidates against.
  *Diagnosability*: pure-Python, no native surprises; every value is a plain coordinate.
  *Maintainability*: widely used, MIT.
  *Operational cost*: low.
  *Local-first*: fully local.
- **`pypdfium2`** —
  *Fidelity*: faithful page rasterization for OCR input; correct page dimensions/rotation.
  *Operational cost*: prebuilt wheels, no poppler/Ghostscript system dependency.
  *Rejected alternatives*: `pdf2image` (needs poppler binary), Wand/ImageMagick (heavy native dep) — rejected on **operational surface / capability**, not "lighter wins": pypdfium2 covers the need with fewer moving parts and no system binary.
- **OCR engine (path C) — BENCHMARK-GATED, no default in this plan** —
  Candidates: **RapidOCR** (`rapidocr-onnxruntime`, PP-OCR models, Apache-2.0) and **Tesseract 5** (`pytesseract` → system binary, Apache-2.0). Both wrapped behind an `OcrEngine` protocol.
  *Fidelity*: unknown until measured — **The default is chosen by the fidelity benchmark (research §4, OCR benchmark task), not here.**
  *v1 language scope*: Latin-script Western languages; **primary validated = Portuguese, English, Spanish** (spec Clarifications 2026-09-07); FR/IT/DE compatible via the same path; CJK/non-Latin out of scope for v1.
  *RapidOCR recognition-model strategy*: **one multilingual Latin PP-OCR recognition model** (e.g. `latin_PP-OCRv3_rec`) for **every** supported v1 language — no per-language model switching, no Latin/CJK routing. Supplied via explicit local `rec_model_path` + `rec_keys_path`. The bundled Chinese `ch_PP-OCRv4_rec` model **MUST NOT** be used for a supported v1 language.
  *Model acquisition*: the Latin rec model + dictionary are obtained **once, at setup time, from a documented source** (RapidAI/RapidOCR release or upstream PaddleOCR); **the exact model identity/version and the SHA256 of every file MUST be recorded** (in `benchmarks/ocr/models/README.md` and this ledger) when acquired. **Zero model downloads at document-processing runtime** — asserted by the no-model-download guards (T004 / T134). No new pip dependency; the `rapidocr-onnxruntime==1.4.4` pin and the 7-day supply-chain rule are unaffected.
  *Approved v1 recognition artifacts (recorded 2026-09-07)* — acquired via `benchmarks/ocr/models/fetch_latin_model.py` from the official **RapidAI/RapidOCR** model repository on ModelScope (`https://www.modelscope.cn/models/RapidAI/RapidOCR`; source paths `onnx/PP-OCRv4/rec/latin_PP-OCRv3_rec_mobile.onnx` and `paddle/PP-OCRv4/rec/latin_PP-OCRv3_rec_mobile/latin_dict.txt`); full provenance in `benchmarks/ocr/models/README.md`:
  | artifact | local name | identity | SHA256 |
  |---|---|---|---|
  | recognition model | `latin_PP-OCRv3_rec_infer.onnx` | PaddleOCR PP-OCRv3 multilingual Latin recognition, *mobile* (185-symbol dict + blank/space → 187 CTC classes; ONNX IR v7) | `e9d7a33667e8aaa702862975186adf2012e3f390cc0f9422865957125f8071cf` |
  | recognition dictionary | `latin_dict.txt` | 185 symbols; byte-identical to the model's embedded `character` metadata | `8e6d4e3629788c35c31f7e530287d6147b549bb7a265bd6708bb281134429e2c` |
  These two digests are the single **runtime policy** (`APPROVED_V1_REC_MODEL` / `APPROVED_V1_REC_DICT` in `src/solari_converter/extract/ocr_engines/rapidocr_engine.py`) and are mirrored in `benchmarks/ocr/models/SHA256SUMS`. `RapidOcrEngine` **SHA256-verifies both configured artifacts against these values before instantiating RapidOCR** — a corrupt / altered / wrong / unknown file, or the bundled Chinese `ch_PP-OCRv4_rec` model, fails closed with `OcrUnavailable`; identity is content-addressed (a renamed copy with a matching digest is accepted); the `SOLARI_RAPIDOCR_REC_MODEL` / `SOLARI_RAPIDOCR_REC_KEYS` env overrides select paths only and cannot bypass verification; provenance reports the approved family/version only after verification succeeds. Model binaries are **not committed** (`benchmarks/ocr/models/.gitignore`); the tracked reproducibility record is `README.md` + `SHA256SUMS` + `fetch_latin_model.py`.
  *Operational cost*: RapidOCR = `onnxruntime` + the bundled detector/classifier + the setup-time Latin rec model; Tesseract = system binary + `por`/`eng`/`spa` (+ `fra`/`ita`/`deu`) traineddata. Both fully local.
  *Constitution*: the old rejection of neural OCR "because ML runtime weight" is **superseded** by v2.0.0 (research §4).
- **Language detector — re-open (research §5)** —
  `langdetect` (light, seedable) vs `lingua-language-detector` (more accurate on short text, heavier) vs engine-native script/lang hints. Pluggable `LanguageDetector`; decision on **detection accuracy for OCR fidelity**, not weight.
- **`python-docx`** — DOCX export with explicit paragraph styles, `Heading 1..9`, and `cell.merge()` for HTML-table spans. *Rejected*: `pandoc` — opinionated style mapping + unreliable merged-cell fidelity from HTML tables (a **fidelity** objection, still valid); binary size is not the reason.
- **`pydantic` v2** — one definition per entity; JSON round-trip; `model_json_schema()` generates the contract schemas (no hand-synced schemas → no drift). Rust core, fast.
- **`httpx`** — thin OpenAI-compatible client for the local LLM; used by reconciliation and validation. *Rejected*: the `openai` SDK (adds transitive deps for request shaping we do in ~40 lines; no fidelity/diagnosability gain) and `llama-cpp-python` in-process (couples model-file management + a large native dep into this tool; "user runs their own server" is a cleaner **separation of concerns** and keeps the LLM swappable — an architecture argument, not a weight argument).
- **stdlib `argparse`** — six subcommands with a handful of options; argparse is sufficient and adds nothing to install. *Rejected*: Typer/Click — no product-quality benefit here; the choice is "simplest sufficient tool", not "fewest deps".
- **`questionary` — interactive `review` terminal UI (PROPOSED 2026-09-08; not yet in `pyproject.toml`)** —
  *Fidelity / safety*: FR-074 makes `review` an interactive keyboard-driven terminal mode (Up/Down/Enter menus, exact-literal text entry, answer browsing). `questionary` provides exactly those primitives (`select`, `text`) on top of `prompt_toolkit`; the alternative is a hand-written raw-terminal key handler (`termios`/`tty`/`msvcrt` + ANSI) — fragile, hard-to-test custom code in a safety-critical workflow, which VII v2.0.0 says to avoid.
  *Diagnosability / maintainability*: `prompt_toolkit` is one of the most widely deployed terminal libraries in Python (IPython, pgcli, ptpython); MIT/BSD; actively maintained.
  *Operational cost*: transitive closure = `questionary` -> `prompt_toolkit` (3.0.x) -> `wcwidth`. Three pure-Python packages, no native build, no models, **no network**.
  *Local-first*: no egress; the deterministic pipeline never imports it (`review/` only).
  *Install timing*: like `docling` (T046), this is **not** added at T002 — it is declared and pinned at the first `review`-workflow implementation task, with the exact `questionary` / `prompt_toolkit` / `wcwidth` versions + a fresh 7-day-rule check recorded here at that point. Candidate today: `questionary==2.1.1` (2025-08-28), `prompt_toolkit==3.0.53` (2026-07-26), `wcwidth` (>= 7 days old at add-time) — all satisfy the 7-day rule and Python >= 3.12.
  *Rejected alternatives*: `InquirerPy` (no release since 2022-06 — maintenance risk; extra `pfzy` dep); `prompt_toolkit` directly (would re-implement the select/list widgets `questionary` already provides); stdlib-only (fragile custom terminal handling).
- **Transitive deps promoted to explicit direct declarations (2026-09-08)** — these are already in the resolved closure via the packages above; they are imported *directly* by project code, so they are now exact-pinned in `pyproject.toml` rather than left implicit (no version change, no resolution change — ownership only):
  - `numpy==2.5.2` — runtime; `RapidOcrEngine` converts the page image to an `ndarray` for PP-OCR. (Was previously only a `[tool.uv]` foundation constraint; now a direct `[project.dependencies]` pin and removed from `constraint-dependencies`.)
  - `pillow==12.3.0` — runtime; both OCR adapters open/normalise the page image (`PIL.Image`); also the fixture/corpus renderers.
  - `onnxruntime==1.29.0` — runtime; the inference runtime the RapidOCR path executes on (pulled unpinned by `rapidocr-onnxruntime`; pinned here). Imported directly by `benchmarks/ocr/run.py` for provider reporting.
  - `rapidfuzz==3.14.6` — **dev-only**; `benchmarks/ocr/run.py` uses `fuzz.ratio` for the reading-order line-alignment metric (also a transitive dep of `jiwer`).
- **Dev-only**: `pytest`, `reportlab` (synthetic fixtures — intent visible in code), `jiwer` (CER/WER metrics for the OCR benchmark), `rapidfuzz` (reading-order alignment in the OCR benchmark), `lingua-language-detector` (benchmark detector candidate), `ruff`.

**Result: no violations.** The Complexity Tracking table stays empty; the ledger above is the positive justification VII v2.0.0 requires.

### Post-Design re-check (after Phase 1)

`data-model.md` and `contracts/` introduce **one proposed, deferred runtime
dependency** (`questionary` for the interactive `review` UI — ledger above; added at
the first `review` task with a fresh 7-day check, not at T002). Everything else is
in-house data structures: Extraction Candidate, Source-backed Segment, Aligned
Segment Group, Canonical Extracted Document, Reconciliation Decision/Log,
HUMAN_REVIEW_REQUIRED Item, Human Review Resolution / store (now with
`resolution_id` / `sequence_index` / `supersedes` — append-only supersede, no
destructive update), **Human Review Authorization** (per-`run_id`, derived run
state), **RenderMap** + **Human Review Verification** (the review→Markdown lineage
and location-aware check), **Human Review Report** (a rendered artifact, not a
store), and Run Identity. The reconciliation **programmatic guard**, the
**append-only resolution store**, the **`run_id`-keyed authorization** (a delivery
requires an authorization record whose `run_id` matches the delivered artifacts),
and **location-aware verification** (per-segment render spans, never a global string
search) make Principles I, III, and IV machine-checkable
(`sha256(run₁)==sha256(run₂)` for the deterministic core — which now also covers the
Human Review Report and verification record; "selected value ∈ candidate set" as a
100% test; "delivered ⇒ authorized-for-this-`run_id` ∧ every applicable decision
verified"). Principle V is a regression-guarded property (no-egress autouse fixture
— which also covers `questionary`/`prompt_toolkit` — + a test that model downloads
are absent at run time).

**Reproducibility is now two-level (FR-053a deterministic core + FR-053b LLM-assisted
results, spec clarification 2026-09-07, research §4a pt 5).** The deterministic core
(Markdown, DOCX, deterministic records, `run_id`) is byte-reproducible and stays so.
The validation report's semantic section is byte-reproducible only when the local
LLM backend honours `seed` (probed and recorded as `llm.reproducibility:
"deterministic"`); otherwise it is `"best_effort"` and `pipeline/validate` **replays**
an already-persisted report for the identical applicability context instead of
regenerating — so a re-run still reproduces the bytes, by replay, with no collision.
`run_id` remains a pure deterministic digest and gains no wall-clock/random field.
This is honest without weakening any guard, the source-backed-content invariant, or
the deterministic core. All seven principles still PASS; Complexity Tracking remains
empty.

**Human Review evolution re-check (2026-09-08, FR-074–FR-084 / SC-032–SC-036,
research §22 / §25 / §26).** The interactive `review` terminal mode adds **one
proposed, deferred** dependency (`questionary` → `prompt_toolkit` → `wcwidth`,
pure-Python, no network, added at the first `review` task with a fresh 7-day check —
ledger). Principles III and IV are **strengthened**, not weakened: successful
delivery now additionally requires explicit `run_id`-keyed authorization (FR-077)
and location-aware verification of every applicable decision at its rendered span
(FR-083/FR-084); the resolution history is append-only with an explicit supersede
link — no destructive update anywhere (FR-076); decisions are never applied by
editing Markdown (FR-079). Principle V is unaffected — `questionary`/`prompt_toolkit`
do no network I/O and the no-egress autouse guard covers them. Principle VI holds —
the prompt layer is isolated in `review/tui.py`, all review logic and the
verification/report code are headless and unit-testable, and scripted key sequences
drive the TUI in integration tests. The Human Review Report and the
`human-review-verification` record are **deterministic** and join the FR-053a core;
the authorization event and report generation are outputs, not `run_id` inputs
(research §14). New concepts are all in-house data structures. All seven principles
still PASS; Complexity Tracking remains empty.

**Adversarial-audit remediation re-check (2026-09-08, H1–H6 / M1–M11).** The
remediation is architecture/contract-only — no new runtime dependency, no code, no
`pyproject.toml` / `uv.lock` change. It **tightens** existing principles: the
`RunContext` record (H3) removes an ambiguity in the FR-053a effective-input
definition rather than adding a source of truth; the authorization file is
reclassified as an append-only **audit event log** (M4) — validity is purely
`authorized_run_id == current run_id` (M2), which is strictly simpler than the
rejected `queue_sha256`; `sequence_index` becomes the single "currently-applicable"
authority with fail-closed invariants I1–I6 (H6) — no heuristic; `segment_transforms`
is a **closed enum** each traceable to a permitting FR (H1) — the opposite of an
open normalizer; Markdown serialization is pinned exactly (M5); the deliverable
name never holds unverified content (H2). Principle VII is satisfied — the closed
enum and the explicit precedence table are the *simple* choice; no fragile in-house
heuristic is introduced. All seven principles still PASS; Complexity Tracking
remains empty. research §14 is now the **authoritative** effective-input
definition; `spec.md`, `data-model.md`, and `contracts/*` reference it and do not
restate it (L5).

### Concrete-identifier maintenance invariant

The concrete v1 tool choices in the ledger above surface as **persisted / contract
vocabulary** in four artifacts, which together form a **lockstep-change set**:

| Artifact | Concrete identifiers it fixes |
|---|---|
| `contracts/extraction-candidate.schema.json` | the `technique` pattern (`^(docling\|pdfplumber\|ocr:<engine>)$`) |
| `contracts/cli.md` | the `--ocr-engine` values (`tesseract` \| `rapidocr`); the candidate filenames `<base>.candidate.docling.json` / `.candidate.pdfplumber.json` / `.candidate.ocr.json` |
| `data-model.md` | the `extraction_technique` / `technique` enum (`docling` \| `pdfplumber` \| `ocr:<engine>`); the pipeline-diagram path labels |
| `tasks.md` | T035's assertion that `technique` matches `docling\|pdfplumber\|ocr:<engine>` (and any later task that names a concrete engine) |

**Invariant**: a future change that alters a concrete extraction/OCR tool
**identifier** or a **candidate naming convention** MUST update every member of this
set that treats that string as a contract or as persisted vocabulary **in the same
change set** — partial updates across these mirrored artifacts are prohibited.

**Scope of the invariant** — it constrains synchronization, not the choice itself:

- The **technology choice** stays a planning/research decision and MAY still change
  on evidence: the OCR engine is **benchmark-gated** (research §4, T013), the
  language detector is still to be selected (research §5), and Camelot or another
  component MAY be adopted later on demonstrated benefit (research §16). Changing a
  tool is not prohibited.
- Only a change that also changes a **persisted or contract identifier** triggers
  the lockstep update. `research.md` prose (rationale, alternatives, benchmark
  methodology) is **not** part of this set — it records *why* a choice was made and
  need not be mechanically re-synced when the identifier strings themselves do not
  change.
- The current v1 identifiers (`docling`, `pdfplumber`, `ocr:<engine>`, `tesseract`,
  `rapidocr`, and the `*.candidate.*.json` names) are **unchanged** by this note.

## Project Structure

### Documentation (this feature)

```text
specs/001-pdf-markdown-converter/
├── plan.md              # this file
├── research.md          # Phase 0 — updated: OCR re-open, Docling justification, LLM determinism, …
├── data-model.md        # Phase 1 — rewritten for the multi-path + reconciliation + human-review model
├── quickstart.md        # Phase 1 — rewritten
├── contracts/           # Phase 1 — rewritten
│   ├── cli.md                              # 6 commands incl. `review`
│   ├── extraction-candidate.schema.json    # (persisted intermediate)
│   ├── canonical-extracted-document.schema.json
│   ├── reconciliation-log.schema.json
│   ├── run-context.schema.json                  # persisted extract-stage effective-input tuple → `review` recomputes run_id (H3; 2026-09-08)
│   ├── human-review-queue.schema.json           # (+ required derived `run_state` with explicit precedence; shared candidateEvidence $def)
│   ├── human-review-resolution.schema.json      # append-only store line (content-bound resolution_id; sequence_index authority I1–I6; supersedes = audit linkage)
│   ├── human-review-authorization.schema.json   # APPEND-ONLY per-run_id authorization EVENT LOG (2026-09-08); validity = authorized_run_id == current run_id; no queue hash
│   ├── human-review-verification.schema.json    # review→Markdown lineage + location-aware verification; segment_transforms closed enum; defect_class = originating stage; null spans for not_located; the Human Review Report renders from this (2026-09-08)
│   ├── removal-log.schema.json
│   ├── validation-report.schema.json
│   ├── correction-log.schema.json
│   └── traceability-record.schema.json
├── checklists/
│   └── requirements.md
└── tasks.md             # /speckit-tasks output (NOT created by this plan)
```

### Source Code (repository root)

```text
pyproject.toml                    # uv-managed; console script `solari-convert`; exact-pinned deps

src/solari_converter/
├── __init__.py
├── cli.py                        # argparse: extract | validate | fix | export | convert | review
│                                 #   `review` (no subcmd) → interactive review/tui.py;
│                                 #   `review list|show|resolve|authorize|status` → non-interactive (automation/tests)
├── config.py                     # LLM base URL/model/decode + retries; OCR engine name + confidence
│                                 #   threshold (default 70, normalized 0–100) + lang override;
│                                 #   reconciliation confidence threshold (default 0.75);
│                                 #   gross-divergence threshold (default 0.5); dirs; resolution-store path
├── errors.py                     # exception classes + exit codes (see cli.md)
├── run_identity.py               # deterministic run_id = sha256(source_sha256 ⧺ normalized_selection ⧺
│                                 #   tool_version ⧺ canonical_json(output_affecting_config) ⧺
│                                 #   applicable_resolution_digest) [:16]  (FR-053a/FR-071; research §14 AUTHORITATIVE).
│                                 #   Also reads/writes RunContext (<base>.run-context.json) so `review`
│                                 #   recomputes the CURRENT run_id after the store changes without re-prompting OCR flags (H3)
├── naming.py                     # deterministic artifact names from source stem + page-range token
├── artifacts_io.py               # atomic write; collision policy (identical bytes → no-op);
│                                 #   dual emit JSON (source of truth) + Markdown rendering (FR-057)
│
├── model/
│   ├── provenance.py             # SourceRef (page, bbox), OriginKind (native_text|ocr), technique id
│   ├── segment.py                # SourceBackedSegment; SegmentId (stable, geometry-derived)
│   ├── candidate.py              # ExtractionCandidate; CandidateReadingOrder; StructuralHint
│   ├── canonical.py              # CanonicalExtractedDocument; AcceptedSegment; AcceptedReadingOrder
│   ├── semantic.py               # SemanticDocument; Block union (Heading, Paragraph, ListBlock,
│   │                             #   ListItem, Clause, Table, Cell) — carries provenance + hint-use record
│   ├── page_selection.py         # PageSelection (validators: non-numeric / start>end / oob / overlap)
│   └── ocr_record.py             # RegionOcrRecord
│
├── extract/                      # STAGE 1 — independent, isolated paths (no cross-path imports)
│   ├── base.py                   # ExtractionPath protocol → ExtractionCandidate; per-path error capture
│   ├── native_reliability.py     # extraction-ROUTING component (M2): reads the raw native layer
│   │                             #   DIRECTLY from pdf/loader (source handle), NEVER a candidate;
│   │                             #   coverage-vs-image / mojibake / ToUnicode checks → needs-OCR map;
│   │                             #   corpus-tuned knobs; imports neither plumber_path nor docling_path
│   ├── docling_path.py           # path A: Docling → candidate (+ reading-order + structural hints)
│   ├── plumber_path.py           # path B: pdfplumber/pypdfium2 → candidate (words/lines + geometry)
│   ├── ocr_path.py               # path C: OCR only where native_reliability says so; rasterize;
│   │                             #   language detect/override; OcrEngine; normalize confidence 0–100
│   ├── ocr_engines/
│   │   ├── base.py               # OcrEngine protocol (image, langs) -> [OcrLine{text, bbox, conf}]
│   │   ├── tesseract_engine.py
│   │   └── rapidocr_engine.py
│   ├── language_detect.py        # LanguageDetector protocol + chosen impl (seed-pinned)
│   └── runner.py                 # run all enabled paths concurrently (process pool); collect candidates
│
├── reconcile/                    # STAGE 2 — deterministic-first; LLM candidate-selection only
│   ├── align.py                  # cross-candidate segment alignment → AlignedSegmentGroup
│   │                             #   (geometry IoU + text similarity; deterministic)
│   ├── literal.py                # literal-content reconciliation per group; agreement / disagreement;
│   │                             #   confidence signal; deterministic-agreement path
│   ├── reading_order.py          # candidate-order construction; geometric resolver (column detection,
│   │                             #   baseline order); agreement / disagreement
│   ├── llm_select.py             # ONLY selection prompts; parse → index/id into supplied candidates
│   ├── guard.py                  # programmatic guard: selected value byte-identical to a candidate /
│   │                             #   ordering equals a candidate or geometry-supported order; else reject
│   ├── confidence.py             # material-disagreement metric + confidence score (per sub-process)
│   ├── resolutions.py            # applicability key; append-only store read/append (resolution_id,
│   │                             #   sequence_index, supersedes); "currently-applicable = last per key"; replay
│   ├── human_review.py           # raise HUMAN_REVIEW_REQUIRED items (+ FR-075 presentation fields);
│   │                             #   queue read/write; status re-derived from the store on load
│   ├── log.py                    # ReconciliationLog assembly
│   └── canonical_build.py        # assemble CanonicalExtractedDocument from accepted decisions
│
├── review/                       # interactive Human Review workflow (FR-074–FR-084) — the ONLY
│   │                             #   package that imports `questionary`; NO import of transform/render/llm
│   ├── tui.py                    # questionary select/text loops: resolve, "Enter another value…",
│   │                             #   browse answers, reopen & change; post-review Continue/Save-and-exit
│   ├── session.py                # derived run_state (explicit precedence, M11); APPEND to the
│   │                             #   review-authorizations.jsonl EVENT LOG (validity = authorized_run_id ==
│   │                             #   current run_id, M2/M4); reload RunContext + recompute current run_id (H3);
│   │                             #   fail-closed resolution-store loader (I1–I6, H6); resume at next unresolved item
│   ├── verify.py                 # location-aware verification: ReviewRenderLineage from RenderMap +
│   │                             #   CED decisions; re-apply the closed-enum segment_transforms chain ONLY (H1);
│   │                             #   follow collapsed_into edges (M7); codepoint-span excerpt (verbatim), null for
│   │                             #   not_located (H4); APPLIED_AND_VERIFIED / VERIFICATION_FAILED + defect_class
│   │                             #   = originating stage (H5); reading-order first-span monotonicity (M8)
│   └── report.py                 # render human-review-verification.json → <base>_review_report.md
│                                 #   (literal final-Markdown excerpt; report-only markers on source only)
│
├── transform/                   # STAGE 3 — deterministic semantic transformation (NO LLM)
│   ├── reflow.py                 # de-wrap; de-hyphenate (keep compound hyphens); records the stage-3
│   │                             #   `segment_transforms` entries (dehyphenate / reflow_whitespace, each with
│   │                             #   its permitting FR) on the RenderMap for FR-083 verification (H1)
│   ├── structure.py              # heading/hierarchy inference (may consult structural hints; records use)
│   ├── lists.py                  # list + numbered-article/clause reconstruction
│   ├── tables.py                 # per-page table build; multi-page stitch; repeated-header collapse;
│   │                             #   merged-cell detection
│   ├── artifacts.py              # running header/footer, page number, watermark, auth-stamp removal
│   │                             #   → RemovalLog; conservative-keep when ambiguous
│   └── build_semantic.py         # orchestrate → SemanticDocument (accepted reading order preserved)
│
├── render/
│   ├── markdown.py               # SemanticDocument → UTF-8 Markdown; `#`×level 1–6; deep-level [L{n}];
│   │                             #   pipe vs HTML <table> (rowspan/colspan); OCR-derived marker.
│   │                             #   ALSO emits a RenderMap: codepoint spans per block + per segment_id
│   │                             #   (research §25.2) — the input to review/verify.py
│   └── docx.py                   # Markdown → DOCX; Heading 1..9; list styles; merged cells;
│                                 #   fixed core created/modified + normalized zip timestamps (FR-053a)
│
├── validate/                    # STAGE 4 — final fidelity validation (read-only LLM)
│   ├── deterministic.py          # source coverage (SC-001); numeric integrity; table shape;
│   │                             #   no duplicated header rows; heading presence/level;
│   │                             #   reading-order check vs evidence; OCR low-confidence surfacing;
│   │                             #   gross-divergence match-rate (runs BEFORE the LLM probe)
│   ├── semantic.py               # one read-only LLM pass; issue detection only; never edits
│   ├── classify.py               # defect class: extraction_error | reconciliation_error |
│   │                             #   disallowed_transformation (uses reconciliation provenance)
│   ├── llm_client.py             # httpx OpenAI-compatible; probe (+ seed-determinism probe →
│   │                             #   llm.reproducibility deterministic|best_effort, FR-053b);
│   │                             #   temperature 0 + seed; bounded retry (default 2) → LLMUnavailable;
│   │                             #   shared by reconcile/llm_select
│   └── report.py                 # ValidationReport assembly; on best_effort, replay an already-
│                                 #   persisted report for the identical applicability context
│                                 #   instead of regenerating the semantic section (FR-053b)
│
├── fix/
│   └── apply.py                  # region-scoped Markdown edits from a report; route reconciliation_error
│                                 #   back to human_review (FR-045a); CorrectionLog; re-validate
│
├── reports/                     # persisted-record pydantic models + Markdown renderers + json_schema()
│   ├── base.py                   # envelope: record_type, schema_version, run_id, tool_version,
│   │                             #   source_pdf, source_sha256, page_selection  — NO generated_at / random id
│   ├── removal_log.py
│   ├── reconciliation_log.py
│   ├── human_review_queue.py
│   ├── human_review_resolution.py
│   ├── human_review_authorization.py
│   ├── human_review_verification.py   # + the Human Review Report Markdown renderer
│   ├── validation_report.py
│   ├── correction_log.py
│   └── traceability.py
│
├── pipeline/                    # thin use-case orchestration
│   ├── extract.py               # stages 1→2→3 → self-check → render(+RenderMap) → §25 verification;
│   │                            #   stop at queue (unresolved), or at resolved_unauthorized,
│   │                            #   or at delivery_blocked_verification_failed (all exit 6)
│   ├── validate.py              # stage 4 against a produced Markdown
│   ├── fix.py                   # correction sequence + re-validate; routes reconciliation_error
│   │                            #   (incl. verification failures) back to review/
│   ├── export.py                # Markdown → DOCX
│   └── review.py                # workflow CORE (no questionary import): queue/store/authorization
│                                #   orchestration used by review/tui.py AND the non-interactive
│                                #   `review list/show/resolve/authorize/status` sub-interface
│
├── workflow/
│   └── convert.py               # extract → validate → optional export; stop at queue / unauthorized /
│                                #   verification-failed; TraceabilityRecord written last, ONLY when delivered
│
└── pdf/
    └── loader.py                # open PDF once; reject encrypted / corrupted; 1-based physical pages;
                                 #   shared handle passed read-only to each isolated path

scripts/
├── export_schemas.py            # regenerate contracts/*.schema.json from the pydantic models
└── ocr_benchmark.py             # build + run the OCR fidelity benchmark; write results table

benchmarks/
└── ocr/
    ├── corpus/                  # representative pages (born-digital + scanned + degraded), per category
    ├── ground_truth/            # transcribed truth per page/region + expected reading order
    ├── run.py                   # reproducible harness: each engine × corpus → metrics
    └── RESULTS.md               # populated by the benchmark; the OCR default decision record

tests/
├── conftest.py                  # autouse no-egress guard; tmp dirs; fake local-LLM server (modes);
│                                #   run-twice byte-equality helper; fake resolution store
├── fixtures/build_fixtures.py   # reportlab synthetic PDFs (see Testing strategy)
├── contract/                    # JSON-Schema conformance per record + CLI contract
├── integration/                 # one module per user story + reconciliation + human-review + resume
├── unit/                        # align, literal, reading_order, guard, confidence, resolutions
│                                #   (append-only supersede; fail-closed I1–I6 loader), run_identity
│                                #   (+ RunContext round-trip), naming, reflow (+segment_transforms),
│                                #   tables, structure, page_selection, review/session (run_state precedence +
│                                #   authorization-event-log derivation), review/verify (location-aware,
│                                #   segment_transforms replay, defect_class, not_located nullability),
│                                #   review/report (deterministic render)
├── integration/…review_tui      # scripted key sequences via prompt_toolkit pipe input; parity vs the
│                                #   non-interactive sub-interface; interruption/resume; reopen & change
└── acceptance/                  # -m acceptance: corpus scoring (SC-002/003), reproducibility corpus,
                                 #   the real long-form sample, the OCR benchmark smoke,
                                 #   Human Review verified-delivery + verification-failure fixtures
```

**Structure decision**: Single project, `src/` layout. Stage boundaries are package
boundaries (`extract/` → `reconcile/` → `transform/` → `validate/` → `render/`),
which is what makes the FR-059 "no stage before its predecessor" and "no cross-path
dependency" invariants enforceable by an import-graph test. The three extraction
paths live in `extract/` as sibling modules with **no imports between them**; the
runner is the only place they meet, and only as a list of independent candidates.
LLM access is one shared `validate/llm_client.py` used by `reconcile/llm_select.py`
and `validate/semantic.py` — both analysis-only. `transform/`, `render/docx.py`, and
`pipeline/export.py` have **no import path to `llm_client`** (enforced by test).
The interactive-terminal dependency (`questionary`) is imported **only** by
`review/tui.py`; `review/session.py` / `verify.py` / `report.py`, `pipeline/review.py`,
and the deterministic pipeline never import it (import-graph test), so review
*logic* stays headless-testable and the pipeline stays UI-free.

## Phase 0 — Research (output: `research.md`)

Resolve every stale technology assumption against the current spec and Constitution
v2.0.0. Decisions to (re)make, in `research.md`:

1. Language/runtime — Python floor vs Docling/onnxruntime wheels (keep 3.12 floor, revisit).
2. Extraction path B — pdfplumber + pypdfium2 as the independent geometric/evidence path (retain; reframe role).
3. Rasterization — pypdfium2 (retain; reframe on capability/operational surface).
4. **OCR engine — RE-OPEN, benchmark-gated** (Tesseract 5 vs RapidOCR/PP-OCR): benchmark methodology, corpus, metrics, decision rule; **no winner without evidence**.
   4a. **LLM determinism** — decode params, seed, model identity in `run_id`; the guard + resolution-replay strategy that makes the observable result reproducible even against a non-deterministic backend; what to do when the LLM flips between candidates run-to-run.
5. **OCR language detection — RE-EVALUATE** langdetect vs lingua-py vs engine-native, on accuracy not weight.
6. **Docling — DOCUMENT** why it's in; separate its literal output, its reading-order candidate, and its structural hints; confirm hints are never applied before stage 3.
7. Audit-record models + schema — pydantic v2, JSON source-of-truth + Markdown rendering (retain).
8. **Local-LLM access** — httpx OpenAI-compatible; reframe SDK / llama-cpp-python rejection around architecture / separation / reproducibility / local operation.
9. **CLI library** — argparse: simplest sufficient tool (weight irrelevant).
9a. OCR low-confidence threshold — normalized 0–100, default 70 (retain; engine-neutral).
10. Deterministic output naming + collision policy (retain).
11. Atomic writes + clean failure (retain).
12. No-egress enforcement (retain; add "no model download at run time" assertion).
13. Test fixtures (retain; extend for the new fixture matrix).
14. **Deterministic run identity** — the `run_id` digest incl. applicable-resolution digest (FR-053a/FR-071).
15. **Reconciliation design** — candidate representation; segment identity; cross-path alignment; literal- and reading-order-conflict detection; "deterministic geometric/layout evidence"; "material disagreement"; confidence computation; the programmatic guard; decision-log shape; the three decision paths.
16. **Camelot / tabula** — revisit the weight-based rejection; retain or reject on measurable multi-page-table fidelity benefit vs `pdfplumber` + the `transform/tables.py` stitcher.
17. **DOCX** — keep the `pandoc` rejection on merged-cell/structural fidelity grounds (not binary size).
18. **Human-review workflow design** — **(rewritten 2026-09-08, research §22)** the interactive keyboard-driven terminal mode (`questionary` selected; terminal-library evaluation; deferred pin); immediate per-answer persistence + resume; append-only supersede (`resolution_id` / `sequence_index` / `supersedes`, no destructive update); derived `run_state` + `run_id`-keyed authorization record (FR-077); the non-interactive `review list/show/resolve/authorize/status` sub-interface as an explicitly secondary automation surface; exit codes; how `fix` routes `reconciliation_error` (incl. verification failures) back.
18a. **Review → final-Markdown lineage & location-aware verification** — **(new 2026-09-08, research §25; audit-remediated H1/H2/H4/H5/M5/M7/M8)** the `RenderMap` (per-block + per-segment codepoint spans, **possibly multiple per segment** M11); the **closed-enum ordered `segment_transforms`** chain per segment, each traceable to a permitting FR (H1, replaces `segment_edits`); `collapsed_into` edges for legitimate collapse (M7); the `ReviewRenderLineage` chain; the pinned Markdown serialization + codepoint-offset span locator (M5); the literal-excerpt rule with **null spans/excerpt for `not_located`** (FR-082, H4); the `HumanReviewVerification` model + `failure_reason` × **`defect_class` = originating stage** (H5); reading-order first-span monotonicity (M8); integration into the validation path classed by originating stage (FR-084); the deliverable name never holds unverified Markdown (H2, §25.7).
18b. **Human Review Report** — **(new 2026-09-08, research §26)** a rendered `<base>_review_report.md` from the authoritative `human-review-verification.json`; naming; generation stage (post-render, post-verification, authorized + ≥1 applicable decision); summary + per-item content; PASS/FAIL derivation; deterministic (joins the FR-053a core); relationship to the traceability record.
19. **Intermediate-artifact persistence** — which of {run context, extraction candidates, CED, reconciliation log, structural hints, human-review queue, resolution store, review-authorization event log, human-review-verification, render map, semantic document, validation report, correction log, traceability record, Human Review Report} are persisted vs ephemeral, and why (auditability / replay / diagnosis / reproducibility without duplicate sources-of-truth).

**Output**: `research.md` with Decision / Rationale / Alternatives for each, and an
explicit "unresolved — needs benchmark evidence" list.

## Phase 1 — Design & Contracts

### `data-model.md` (rewrite)

Retire SFIR. Model, at minimum:

- **Source-backed Segment** — `segment_id` (stable), literal text, `SourceRef` (page + bbox), `OriginKind`, technique id, per-candidate reading-order index, attached structural hints.
- **Extraction Candidate** — technique id, `[Segment]`, `CandidateReadingOrder`, per-path status (ok / partial / failed + reason).
- **Candidate Reading Order** — ordered `[segment_id]` for one candidate.
- **Structural Hint** — `{kind: heading|list|table|…, span, source_technique, payload}`; advisory.
- **Aligned Segment Group** — the cross-candidate correspondence unit (which candidates' segments are "the same region").
- **Reconciliation Decision** — `{conflict_type: literal|reading_order, group/scope, candidates[], method: deterministic_agreement|llm_selected|human_confirmed, selected, confidence?, resolution_ref?}`.
- **Canonical Extracted Document** — accepted segments (literal + provenance + decision), **AcceptedReadingOrder**, carried structural hints, per-value decision provenance. Pre-normalization. **Persisted as JSON only** — no `.md` companion (M1); the reconciliation log's `.md` is the human-facing diagnostic. Same for **Extraction Candidate**.
- **HUMAN_REVIEW_REQUIRED Item** — literal (FR-062a fields) or reading-order (FR-062d fields); `open|resolved` (a `resolved` item stays reopenable, FR-076); **+ FR-075 presentation fields** (`structural_context`, `source_context_before/after`, per-candidate `provenance_label`, `segment_refs`); the queue also carries the derived `run_state`.
- **Human Review Resolution** (append-only store line) — FR-070 fields + `decision_method=human_confirmed` + applicability key + **`resolution_id` / `sequence_index` / `supersedes`** (FR-076: a changed answer is a new line, prior retained; currently-applicable = last per key); entered value stored **verbatim** (FR-068/FR-082).
- **Run Context** (`run-context.schema.json`) — the persisted extract-stage `output_affecting_config` tuple (research §14) so `review` recomputes the CURRENT `run_id` after the store changes without re-prompting OCR/reconcile flags (H3).
- **Human Review Authorization** (append-only **event log** `<base>.review-authorizations.jsonl`) — `{envelope, authorized_run_id, applicable_resolution_digest, resolved_item_ids, authorized_via}` (FR-077, M4); validity is **exactly `authorized_run_id == current run_id`** (M2 — no `queue_sha256`); changing a decision → new `run_id` → no event matches → `resolved_unauthorized`; re-authorizing an unchanged set is an idempotent no-op append. **Not** in the FR-053a run-twice deterministic-core set (it is a human action).
- **RenderMap** (stage-5) — per-block + per-`segment_id` codepoint spans in the delivered Markdown (possibly multiple per segment, M11); `collapsed_into` edges (M7); the closed-enum ordered `segment_transforms` chain per segment (H1) — the input to location-aware verification (FR-083).
- **Human Review Verification** (`human-review-verification.schema.json`, v2.1) — per applicable decision: the review→Markdown lineage (with `segment_transforms`, `ced_accepted`), the codepoint `render_span`, the **literal** `final_markdown_excerpt` (**null for `not_located`**, H4), `status ∈ {applied_and_verified, verification_failed}` + `failure_reason` × **`defect_class` = originating stage** (H5); a summary with `PASS/FAIL`. The **authoritative machine model** the Human Review Report renders from; deterministic — the verification record + Report **join** the FR-053a core.
- **Human Review Report** — the rendered `<base>_review_report.md`; a verification aid, **not** a store (FR-080); no state not derivable from the above + the delivered Markdown.
- **Region OCR Record** — FR-025/FR-027a.
- **Semantic Document** — Block union with per-block provenance + which structural hints were applied.
- **Validation Issue / Report** — six mandatory fields + defect class + optional block + gross-divergence summary + `llm{model, decode, attempts, reproducibility: "deterministic"|"best_effort"}` (FR-053b) + `compared_against`.
- **Correction Log**, **Removal Log**, **Reconciliation Log**, **Traceability Record**, **Run Identity**.

Include a validation-rule cross-reference table (rule → FR/SC → enforced-in).

### `contracts/` (rewrite)

- **`cli.md`** — six commands. `extract` / `validate` / `fix` / `export` / `convert` (updated stop conditions), and **`review`** — **interactive keyboard-driven terminal mode** as the normal path (Up/Down/Enter, "Enter another value…", browse/reopen/change, then Review answers / Continue processing / Save and exit; all-resolved-but-not-authorized re-entry), plus a non-interactive `review list | show <id> | resolve <id> (--select N | --value TEXT | --value-file P | --order ID,…) | authorize | status` sub-interface for automation/tests. Global options unchanged: `--pages`, `--output-dir`, `--json`, OCR options, `--reconcile-confidence-threshold` (0.75), `--gross-divergence-threshold`, `--llm-*`, `--ocr-engine`, `--resolution-store PATH`. Exit-code table unchanged: exit **6** now also covers `resolved_unauthorized` and `delivery_blocked_verification_failed` (distinguished by `run_state` in the message and `--json`), no new code.
- **JSON Schemas** (generated from pydantic; committed; drift test): extraction-candidate, canonical-extracted-document, reconciliation-log, **run-context** (new — extract-stage effective-input tuple, H3), human-review-queue (**+ FR-075 presentation fields, required derived `run_state` with explicit precedence M11**), human-review-resolution (**content-bound `resolution_id` M1; `sequence_index` authority I1–I6 H6; `supersedes` = audit linkage; entered value verbatim**), **human-review-authorization** (new — append-only per-`run_id` authorization **event log** M4; validity = `authorized_run_id == current run_id` M2; no `queue_sha256`), **human-review-verification** (new — lineage + closed-enum `segment_transforms` H1 + `collapsed_into` M7 + `defect_class` originating-stage H5 + null spans for `not_located` H4 + per-decision status + summary; the Human Review Report renders from this), removal-log, validation-report (defect class **stage-based for verification failures H5**, `compared_against`, `llm.decode`/`attempts`/`reproducibility` (FR-053b), gross-divergence fields, **`issues[].review_item_id`** for verification failures), correction-log, traceability-record (reconciliation log + candidates + CED links, `llm_used.reproducibility`, drops `generated_at`, `run_id` pattern, `resolutions_applied` **+ `resolution_id`**, **`run_context` / `human_review_report` / `human_review_verification` / `review_authorizations` (plural — event log) artifact refs + a required `human_review_verification` summary**). Schemas whose 2026-09-08 change added a required field are **`schema_version` "2.1"** (resolution, queue, verification, authorization, traceability); the rest stay "2.0".

### `quickstart.md` (rewrite)

Runnable scenarios: extract (paths agree); extract with a forced literal disagreement → human review → `review resolve` (or `review resolve --value-file` for a whitespace/newline-sensitive literal) → **explicit "Continue processing" authorization** → the pipeline renders to `intermediates/<base>.<run_id>.unverified.md`, runs the built-in self-check + location-aware verification, and only then publishes `<base>.md`; reading-order conflict → geometry-resolved vs human-review; replayed resolution vs changed-context; OCR image page; hybrid page; `validate` defect classes; `fix` routing a `reconciliation_error` (and a `disallowed_transformation` verification failure to a code fix + re-verification); `convert` traceability + no-egress + reproducibility; the OCR benchmark smoke run.

### OCR benchmark (Phase 1 deliverable spec; run is a task, not this plan)

`benchmarks/ocr/` — corpus categories (PT diacritics, small text, numeric/monetary,
tables, degraded scans, image-only, representative layouts), ground truth, metrics
(CER, numeric-token exact-match rate, diacritic accuracy, table-cell CER,
reading-order Kendall-τ, insertion/deletion rates), Tesseract 5 + RapidOCR setup,
`run.py` (reproducible, seed-pinned, records engine+model versions), `RESULTS.md`,
decision rule (best weighted fidelity wins; tie → simpler operational surface).
**`/speckit-tasks` MUST place the benchmark build+run before any task that hardcodes
a default OCR engine.**

### Testing strategy (for `/speckit-tasks`)

Fixtures / tests for: extractors agree; literal disagreement ≥ 0.75 (LLM selects);
literal disagreement < 0.75 (review); all extractors wrong → human-entered source
truth (stored verbatim, no normalization); reading-order disagreement resolved
geometrically; resolved by LLM; requiring human review; LLM returns a non-candidate
value (guard rejects); LLM returns an unsupported reading order (guard rejects);
replayed human resolution; changed context invalidates replay; OCR-required image
page; hybrid PDF; multi-page tables; Docling structural hint accepted / rejected
later; seeded reconciliation error caught by final validation; seeded
semantic-transformation error caught by final validation; unresolved review blocks
final delivery; run-twice byte-equality; no-egress; no model download at run time;
import-graph (no cross-path deps; no LLM import in `transform`/`export`; **no
`questionary` import outside `review/tui.py`**).

**Interactive Human Review (FR-074–FR-084 / SC-032–SC-036)** — failing-first tests
for: keyboard navigation + candidate select + "Enter another value…" (scripted key
sequences via `prompt_toolkit` pipe input); **immediate persistence** — kill the
process after N confirmations, reopen, assert those N are `resolved` and not
re-asked, resume at N+1 (SC-032); **append-only supersede** — reopen a resolved item,
change it, assert the prior `resolution_id` is retained and the chain
previous→replacement→currently-applicable is recoverable (SC-033); **authorization
gate** — answering the last item does not auto-continue; only "Continue processing"
writes the `review-authorization` record; reopening `resolved_unauthorized` offers
the 3-way choice; **changed answer after authorization** — new `run_id`, prior
authorization no longer matches, re-authorization required, no delivery on the stale
set (FR-077); **decisions flow through the pipeline** — resolution changes the CED
decision and re-renders; no Markdown-editing code path exists in `review/`;
**location-aware verification** — duplicate identical literal elsewhere in the
Markdown; spacing/separator/Unicode-only difference at the reviewed span →
`verification_failed / literal_altered`; allowed structural transformation around an
intact literal → verified; reading-order not reflected → `order_not_reflected`;
`not_located` (SC-035); **literal evidence** — `final_markdown_excerpt` byte-identical
to `delivered_markdown[start:end]`, no strip/normalize/`<< >>` (SC-034); **Human
Review Report** — generated only when authorized + ≥1 applicable decision; summary
counts + PASS/FAIL; deterministic (run-twice byte-equality); **verification failure**
→ `reconciliation_error` issue with `review_item_id`, run not delivered, `fix`
routes it back (SC-036); non-interactive sub-interface enforces the same safety
rules; the interactive TUI and the headless core produce identical persisted
records for the same decisions.

## Complexity Tracking

> No Constitution Check violations under v2.0.0. The Justified-Dependency Ledger
> above is the positive justification required by Principle VII. Table intentionally
> empty.

| Violation | Why needed | Simpler alternative rejected because |
|-----------|------------|-------------------------------------|
| — | — | — |
