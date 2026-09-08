---

description: "Task list for Local-First PDF Document Converter — multi-path extraction → reconciliation → semantic transformation → final validation"
---

# Tasks: Local-First PDF Document Converter

**Input**: [plan.md](./plan.md), [spec.md](./spec.md), [research.md](./research.md),
[data-model.md](./data-model.md), [contracts/](./contracts/), [quickstart.md](./quickstart.md),
Constitution **v2.0.0**.

**Full regeneration** (refined 2026-09-07, then remediated for /speckit-analyze findings
**H1 / M1 / M2 / M3 / M4**). The previous task list predated the multi-path architecture and is
discarded. Nothing is carried forward for continuity.

**2026-09-07 task-ordering fix**: the `errors.py` responsibility is split across two existing
tasks so Phase 2 never depends on a Phase 3 deliverable. **T008** (Phase 2) creates
`src/solari_converter/errors.py` with the OCR exception *types* only (`OcrError` /
`OcrUnavailable`) — the permanent definitions that the OCR adapters T009/T010 raise. **T016**
(Phase 3) extends that same module with every other exception class and the complete exit-code
constant mapping + exception→exit integration. No new task, no renumbering; task count stays 134.

**Tests are test-first and NON-NEGOTIABLE (Constitution VI).** Every meaningful behavior has a
**failing** contract / unit / integration / scored-acceptance test with a **lower task number
than** its implementation, and each implementation task names the test it must make pass. There is
no trailing "testing phase". Provenance, audit logging, deterministic replay, the reconciliation
guard, architecture-boundary tests, and the no-network runtime assertion are **core** tasks
(planning requirement 12).

## Format: `[ID] [P?] [Story] Description`

- **[P]**: parallelizable (different files, no dependency on an incomplete task)
- **[Story]**: US1–US5; Setup / OCR-Gate / Foundational / Polish carry no story label
- "**tests Txx**" = the named failing test task (always a lower number); "**depends on Txx**" = Txx
  must be complete first. No implementation task precedes its own failing test by number.

---

## Phase 1: Setup (shared infrastructure)

- [ ] T001 Create the package tree — `src/solari_converter/__init__.py` and subpackages `model/`, `extract/`, `extract/ocr_engines/`, `reconcile/`, `transform/`, `render/`, `validate/`, `fix/`, `reports/`, `pipeline/`, `workflow/`, `pdf/` each with `__init__.py`; and `tests/contract/`, `tests/integration/`, `tests/unit/`, `tests/acceptance/`, `tests/fixtures/`, `scripts/`, `benchmarks/ocr/`, `benchmarks/native_reliability/`, `benchmarks/tables/`
- [ ] T002 Create `pyproject.toml` — `requires-python = ">=3.12"` (CI 3.13); exact-pinned runtime deps per plan.md ledger: `docling`, `pdfplumber`, `pypdfium2`, `python-docx`, `pydantic>=2`, `httpx`, **both** OCR options `rapidocr-onnxruntime` and `pytesseract`, plus the interim language detector `langdetect`; dev deps `pytest`, `reportlab`, `jiwer`; console script `solari-convert = "solari_converter.cli:main"`; dry-run `uv pip install`, then `uv sync` (no dep published in the last 7 days on a fidelity/security path)
- [ ] T003 [P] Configure `ruff` and `[tool.pytest.ini_options]` in `pyproject.toml` with markers `contract`, `integration`, `acceptance`, `benchmark`
- [ ] T004 [P] Create `tests/conftest.py` — autouse fixture blocking non-loopback `socket.socket.connect`; autouse fixture asserting **no model download** during a test (monkeypatch docling/rapidocr model-fetch entry points to raise); `tmp_output_dir` + `tmp_resolution_store` fixtures; `fake_llm_server` fixture binding `127.0.0.1`, OpenAI-compatible, modes `normal | always_500 | slow_timeout | unparseable | returns_non_candidate | flip` (**`normal` also answers the seed-determinism probe identically twice; `flip` answers it differently** — FR-053b); `run_twice(cmd)` helper asserting byte-identical artifacts
- [ ] T005 [P] Create `tests/fixtures/build_fixtures.py` — `reportlab` synthetic PDFs generated at test time: `native_text.pdf` (healthy selectable native text), `agreement.pdf` (headings L1–L8, nested bulleted+numbered lists, numbered clauses, a 3-page table with a repeated header, running header/footer + page numbers), `merged_cells.pdf`, `multipage_table.pdf`, `two_column.pdf` (one geometrically-clear page + one ambiguous), `scanned.pdf` (image-only), `hybrid.pdf` (reliable native text + one image-only region), `missing_content_layer.pdf` (native text layer with **severe missing content** vs the visible page), `garbled_layer.pdf` (corrupted / mojibake ToUnicode on one region), `pt_diacritics.pdf`, `monetary.pdf`, `degraded_scan.pdf`, `clean_transform.pdf` (reflow / heading inference / list & clause reconstruction / table stitch **all legitimately applicable and correct** — a defect-class false-positive baseline), and `conflict_literal.pdf` (path A vs path B disagree on one clause below 0.75 confidence). Commit `tests/fixtures/agreement.deviations.md` (seeded: altered table number, flattened heading, wrong reconciliation choice) and `tests/fixtures/unrelated.md`
- [ ] T006 [P] Create `tests/fixtures/manifests.py` — machine-readable ground truth: per fixture — expected headings (text + level), multi-page tables (rows/cols/values/repeated-header positions), expected reading order; **per-page source-token ground truth for SC-001 scoring** (the set of extractable source tokens per selected page, each with its true source page — for T124); **expected `PageClass`** and OCR-trigger regions for `native_text.pdf` / `scanned.pdf` / `missing_content_layer.pdf` / `garbled_layer.pdf` / `hybrid.pdf` (for T048); and a **defect-classification ground-truth set** — each seeded-defect case labelled with its expected `defect_class` (`extraction_error` / `reconciliation_error` / `disallowed_transformation`) plus a set of **legitimate semantic-transformation cases labelled `allowed`** that MUST NOT be flagged (for T133 / SC-019)

**Checkpoint**: environment, fixtures, and ground truth ready.

---

## Phase 2: OCR Benchmark Gate  ⛔ implementation gate (planning requirement 1)

**No task in any later phase may hardcode or assume a default OCR engine until T013 completes.**
Engine-neutral tasks (`OcrEngine` protocol, the two adapters, any test/run passing `--ocr-engine`
explicitly) proceed in parallel.

- [ ] T007 Create `benchmarks/ocr/corpus/` + `benchmarks/ocr/ground_truth/` — representative pages per category (planning requirement 11; corpus categories per research §4.1): PT accents/diacritics, small text, numeric & monetary values, simple table, degraded/scanned, image-only, a **mixed / hybrid native-text + OCR** case (a page or short page set carrying reliable native text alongside an image-only region that needs OCR — exercises the conditional, adaptive per-page/per-region OCR-routing decision, **not** an OCR-everything path), and 2–3 target-representative layouts (multi-column legal). Each page: a rasterized image + a hand-verified transcription + expected reading order + true language. Document provenance/licensing in `benchmarks/ocr/corpus/README.md`
- [ ] T008 [P] Create **two** files: (a) `src/solari_converter/extract/ocr_engines/base.py` — `OcrEngine` protocol: `recognize(image, languages) -> list[OcrLine{text, bbox, confidence_0_100}]`; `name`; `is_available() -> bool`; helper `normalize_confidence(raw, engine)` mapping Tesseract 0–100 and PP-OCR 0–1 onto 0–100 (research §9a); (b) `src/solari_converter/errors.py` — **containing only** `OcrError(Exception)` and `OcrUnavailable(OcrError)`, the permanent exception types the OCR adapters (T009/T010) raise. In this task `errors.py` **MUST NOT** define exit-code constants, any exception→exit mapping, or any other exception class — those are added later by T016 (Phase 3), which extends this same module. **Engine-neutral — no default**
- [ ] T009 [P] Create `src/solari_converter/extract/ocr_engines/tesseract_engine.py` — `pytesseract.image_to_data` → `OcrLine[]`; `-l` language string; raise `OcrUnavailable` (provided by T008 in `errors.py`; mapped to exit 8 in T016) when the binary/traineddata is missing (depends on T008)
- [ ] T010 [P] Create `src/solari_converter/extract/ocr_engines/rapidocr_engine.py` — `rapidocr-onnxruntime` PP-OCR → `OcrLine[]`; model-family/language selection; pinned model version; raise `OcrUnavailable` (provided by T008 in `errors.py`) when models are absent (depends on T008)
- [ ] T011 [P] Write failing tests **first**: `benchmarks/ocr/test_metrics.py` (metric functions — CER via `jiwer`, numeric-token exact-match, diacritic accuracy, table-cell CER, reading-order Kendall-τ, insertion/deletion rates, language-detection accuracy — against known small inputs) and `tests/acceptance/test_ocr_benchmark_smoke.py` under `-m acceptance` (both engines load; each returns text for one clean + one degraded page) (depends on T009, T010)
- [ ] T012 Create `benchmarks/ocr/metrics.py` + `benchmarks/ocr/run.py` — implement the metric functions (make T011 pass); reproducible harness (seed-pinned; records engine + model versions): each engine × corpus page → every T011 metric + the **language-detection sub-metric** across {langdetect seed-pinned, lingua, engine-native}; a two-run determinism self-check; write per-engine per-metric scores + a weighted total to `benchmarks/ocr/RESULTS.md` (depends on T007, T011)
- [ ] T013 **GATE — run the benchmark and select the defaults.** Execute `benchmarks/ocr/run.py`; commit `benchmarks/ocr/RESULTS.md`; choose the default **OCR engine** and **language detector** from the scores per research §4.1 selection rule (best weighted fidelity; tie → simpler operational surface); record the decision in `RESULTS.md` and add a pointer line in `research.md` §4/§5. Only after this may `config.py` (T017) and `language_detect.py` (T045) carry a default (depends on T012)

**Checkpoint**: OCR engine + language detector chosen from evidence; the gate is lifted.

---

## Phase 3: Foundational (blocking prerequisites for every user story)

**⚠️ No user-story work begins until this phase is complete.**

- [ ] T014 [P] Write failing unit tests **first**, one file each (obtain approval before their implementations — Constitution VI): `test_page_selection.py` (single/range/discontinuous; `10-5`; overlap; oob; non-numeric; 1-based physical vs printed), `test_naming.py` (determinism; whole-doc `""` in filename vs `"all"` in envelope; selector token), `test_run_identity.py` (same inputs → same 16-hex id; different `ocr_engine`/`ocr_confidence_threshold`/`reconcile_confidence_threshold`/`gross_divergence_threshold`/`llm_model`/`llm_decode`/`enabled_paths` → different id; different applicable-resolution set → different id; `base_url`/timeouts/retries/output dir/`--json` → **same** id; **no wall-clock/random component** — FR-053a), `test_segment_id.py` (stable across candidates; geometry-derived; NFC text hash), `test_collision.py` (identical bytes → no-op; different bytes → `OutputCollision`), `test_applicability_key.py` (source hash + conflict identity + config subset bind; page-selection change keeping the region → key unchanged; OCR-engine change → key changes), `test_config.py` (option precedence CLI > env > default; numeric bounds 0–100 / 0–1 rejected outside), `test_reconciliation_decision_invariant.py` (a non-`human_confirmed` `ReconciliationDecision` whose `selected` value ∉ its candidate values — or order ∉ candidate/geometry orders — MUST raise a validation error — SC-020)
- [ ] T015 [P] Contract test `tests/contract/test_schemas_committed.py` — every `contracts/*.schema.json` equals `model_json_schema()` of its pydantic model (drift guard); every schema is valid JSON Schema 2020-12; every **audit record's** `.json` and `.md` renderings represent the same content (FR-057); **extraction candidates and the Canonical Extracted Document carry the envelope but have NO `.md` companion** (M1)
- [ ] T016 [P] Extend `src/solari_converter/errors.py` (created in T008 with `OcrError` / `OcrUnavailable`) — add the remaining exception classes (`InvalidSelection`, `SourceUnreadable`, `LLMUnavailable`, `OutputCollision`, `HumanReviewRequired`, `ResourceExhausted`) and the **complete exit-code constants + exception→exit mapping**: 0, 2, 3, 4, 5, **6 (human review required)**, 7, 8 — including **`OcrUnavailable` → 8** (depends on T008)
- [ ] T017 Create `src/solari_converter/config.py` — resolve: LLM base URL/model/decode `{temperature:0, seed}`/retries (default 2); `ocr_engine` (**default from T013**), `ocr_lang` override, `ocr_confidence_threshold` (normalized 0–100, default 70); `reconcile_confidence_threshold` (default 0.75); `gross_divergence_threshold` (default 0.5); the **native-reliability knobs** (set by T049, surfaced as config); output dir (default `./out`), intermediates dir, resolution-store path; `output_affecting_config()` (research §14) (depends on T013, T016; tests T014)
- [ ] T018 [P] Create `src/solari_converter/model/provenance.py` — `SourceRef` (physical_page, bbox, origin_kind `native_text|ocr`, extraction_technique, ocr_languages, ocr_confidence 0–100)
- [ ] T019 [P] Create `src/solari_converter/model/segment.py` — `SourceBackedSegment` (segment_id, text verbatim, source, reading_order_index, structural_hints); `segment_id(page, bbox, text)` = `sha1(...)[:12]` (depends on T018; tests T014)
- [ ] T020 [P] Create `src/solari_converter/model/candidate.py` — `ExtractionCandidate`, `StructuralHint`, `RegionOcrRecord`, `PageClass` enum (depends on T019)
- [ ] T021 [P] Create `src/solari_converter/model/page_selection.py` — `PageSelection` (FR-004 validators; parse; normalized token; ordered page list) (tests T014)
- [ ] T022 Create `src/solari_converter/model/canonical.py` — `CanonicalExtractedDocument` (state const `pre_semantic_transformation`, accepted_segments, accepted_reading_order, carried_structural_hints, page_classes); `AcceptedSegment` (depends on T019, T020)
- [ ] T023 [P] Create `src/solari_converter/model/reconciliation.py` — `ReconciliationDecision` **with the SC-020 invariant validator** (tests T014) (depends on T019)
- [ ] T024 [P] Create `src/solari_converter/model/human_review.py` — `HumanReviewItem` (FR-062a / FR-062d fields incl. `segment_ids`); `HumanReviewQueue`; `HumanReviewResolution` (applicability_key, review_item_id, conflict_type, candidates_presented, decision_method const `human_confirmed`, selected {mode select|entered, value, manually_verified} | {order}, reviewer_note) (depends on T023)
- [ ] T025 Create `src/solari_converter/run_identity.py` — `compute_run_id(...)` per research §14 (16 hex; folds `applicable_resolution_digest`; **no wall-clock/random** — FR-053a) (depends on T017; tests T014)
- [ ] T026 [P] Create `src/solari_converter/naming.py` — `selector_token`, `artifact_name` (FR-053) (tests T014)
- [ ] T027 Create `src/solari_converter/artifacts_io.py` — `write_atomic`; `write_record` dual-emitting `.json` + `.md` **for audit records** and `.json` only for candidates + CED (M1); collision policy (identical bytes → no-op, different → `OutputCollision`; FR-054, SC-016); intermediates → `dir/intermediates/` (depends on T016; tests T014)
- [ ] T028 [P] Create `src/solari_converter/reports/base.py` — pydantic envelope base (`record_type`, `schema_version="2.0"`, `run_id`, `tool_version`, `source_pdf`, `source_sha256`, `page_selection`) — **no `generated_at`, no random id** (FR-053a); `render_markdown()` hook (audit records only); `json_schema()` helper (depends on T025)
- [ ] T029 [P] Write failing tests **first**: `tests/unit/test_resolution_store.py` — append-only (superseding a key adds a line, keeps the old); `load_index()` returns the **last** record per key; a changed config subset → no replay (fresh item); JSONL ↔ model round-trip; `compute_applicability_key` end-to-end
- [ ] T030 Create `src/solari_converter/reconcile/resolutions.py` — append-only store (`resolutions.jsonl` + generated `resolutions.md`): `append`, `load_index`, `compute_applicability_key(...)` (research §22), `replay_for(conflict) -> HumanReviewResolution | None` (None when the key does not match) — makes T029 pass (depends on T024, T027; tests T029)
- [ ] T031 [P] Write failing tests **first**: `tests/unit/test_reconcile_guard.py` (non-candidate literal value → rejected; non-candidate/non-geometry order → rejected; valid selection → accepted) and `tests/unit/test_llm_client.py` (probe failure → `LLMUnavailable`; mid-run 500 / timeout / unparseable → bounded retry (default 2) then `LLMUnavailable`; every request `temperature:0` + `seed`; `flip` mode → the double-call disagreement is reported to the caller; **the seed-determinism probe returns `deterministic` for `normal` and `best_effort` for `flip`** — FR-053b)
- [ ] T032 Create `src/solari_converter/validate/llm_client.py` — `httpx` OpenAI-compatible client; `probe()` **+ a one-shot seed-determinism probe** (a fixed tiny prompt issued twice; identical ⇒ `deterministic`, else `best_effort` — FR-053b); `select(prompt, candidates) -> selection` and `detect_issues(prompt) -> issues` (both analysis-only; never returns free text used as source); `temperature:0` + fixed `seed`; bounded retry then `LLMUnavailable`; records `{model, decode, attempts, reproducibility}`; **double-call** helper for reconciliation flip detection — makes T031 pass (depends on T016, T017; tests T031)
- [ ] T033 Create `src/solari_converter/reconcile/guard.py` — `guard_literal(...)` / `guard_order(...)` → accept or `GuardReject`; a reject → conflict unresolved → HUMAN_REVIEW_REQUIRED (FR-061b) — makes T031's guard tests pass (depends on T023; tests T031)
- [ ] T034 Write failing test **first** `tests/unit/test_loader.py` (missing / encrypted / corrupted → `SourceUnreadable` / exit 3; `page_count`; 1-based physical page access) **then** create `src/solari_converter/pdf/loader.py` — open the PDF once (pdfplumber + a pypdfium2 handle); handle passed **read-only** to each extraction path (never another path's output) (depends on T016)

**Checkpoint**: foundation ready — provenance, run identity, IO, resolution store (test-first),
LLM client + seed-determinism probe + guard (test-first), loader (test-first).

---

## Phase 4: User Story 1 — Extract faithful structured Markdown (Priority: P1)  🎯 MVP

**Goal**: `extract` turns a PDF into semantically structured, reconciled, reproducible UTF-8
Markdown — or, where paths disagree below confidence, a human-review queue and **no Markdown**
(exit 6). `review` resolves items; a re-run resumes.

### 4A — Contract tests (write first, must fail)

- [ ] T035 [P] [US1] Contract test `tests/contract/test_extraction_candidate_schema.py` — `ExtractionCandidate` validates against `contracts/extraction-candidate.schema.json`; `technique` matches `docling|pdfplumber|ocr:<engine>`; segments carry `segment_id` + `SourceRef` + `reading_order_index`; **no `.md` companion is produced for candidates — JSON is the sole authoritative representation and downstream never consumes a candidate `.md`** (M1)
- [ ] T036 [P] [US1] Contract test `tests/contract/test_canonical_extracted_document_schema.py` — validates against schema; `state == "pre_semantic_transformation"`; every `accepted_segments[].text` equals some contributing candidate's text (SC-020); `carried_structural_hints` present and **none applied**; `accepted_reading_order` covers exactly the accepted segments; **CED is JSON only, no `.md`** (M1)
- [ ] T037 [P] [US1] Contract test `tests/contract/test_reconciliation_log_schema.py` — validates; every non-`human_confirmed` decision satisfies the SC-020 invariant; `unresolved[]` each reference a queue item; `summary` counts consistent; `.json`/`.md` parity (the reconciliation log **is** an audit record — it gets the dual emit)
- [ ] T038 [P] [US1] Contract test `tests/contract/test_human_review_queue_schema.py` — validates; literal items carry FR-062a fields, reading-order items carry FR-062d fields incl. `segment_ids`; a queue with any `open` item ⇒ the run wrote no `<base>.md`
- [ ] T039 [P] [US1] Contract test `tests/contract/test_human_review_resolution_schema.py` — a resolution line validates; `mode:"entered"` ⇒ `manually_verified: true`; a reading-order `selected.order` is a permutation of the item's `segment_ids`
- [ ] T040 [P] [US1] Contract test `tests/contract/test_removal_log_schema.py` — `RemovalLog` validates; envelope has `run_id`, no `generated_at`; `.json`/`.md` parity
- [ ] T041 [P] [US1] Contract test `tests/contract/test_cli_extract.py` — arg parsing incl. `--ocr-engine`, `--ocr-confidence-threshold` (0–100), `--reconcile-confidence-threshold` (0–1), `--resolution-store`; help states 1-based physical pages; exit codes 2 / 3 / **6** / 8; deterministic artifact names
- [ ] T042 [P] [US1] Contract test `tests/contract/test_cli_review.py` — `review list` / `show <id>` / `resolve <id> (--select N | --value TEXT | --value-file PATH | --order ids)`; bad `--select` / bad `--order` → exit 2; `resolve` appends to the store and marks the item resolved; `review` never invokes the LLM (assert no client instantiated) and never writes Markdown

### 4B — Extraction paths (independent; architecture boundary enforced)

- [ ] T043 [P] [US1] Create `src/solari_converter/extract/base.py` — `ExtractionPath` protocol → `ExtractionCandidate`; per-path try/except recording `status=failed`/`partial` + `status_detail` instead of raising (FR-060 edge case)
- [ ] T044 [P] [US1] Write failing test **first** `tests/unit/test_language_detect.py` — `--ocr-lang` override wins over auto-detection; the detector is seed-pinned (identical result across two runs on the same text); per page/region detection; `language_source` recorded as `auto` vs `override`; unknown/empty text → a safe default, not a crash (M3)
- [ ] T045 [US1] Create `src/solari_converter/extract/language_detect.py` — `LanguageDetector` protocol + the impl chosen by T013; seed-pinned (`langdetect.DetectorFactory.seed = 0` if langdetect); per page/region detection with `--ocr-lang` override; records `language_source` (FR-027a) — makes T044 pass (depends on T013, T020; tests T044)
- [ ] T046 [US1] Create `src/solari_converter/extract/docling_path.py` — path A: Docling → `SourceBackedSegment`s (verbatim text + geometry), a `CandidateReadingOrder` (Docling's inference — **evidence only**, FR-060b), `StructuralHint`s (**carried, not applied**). Pin the Docling model version; **no import of `extract/plumber_path` or `extract/ocr_path`** (depends on T020, T043)
- [ ] T047 [US1] Create `src/solari_converter/extract/plumber_path.py` — path B: pdfplumber words/lines → `SourceBackedSegment`s with exact bbox + font metrics; a **geometric** `CandidateReadingOrder` (x-gap column detect, then top-to-bottom within column, columns left-to-right); table-detector output as `StructuralHint`s; rotated / mixed-orientation handled; **no import of the other two paths** (depends on T020, T034, T043)
- [ ] T048 [P] [US1] Write failing **scored** test **first** `tests/unit/test_native_reliability.py` — over `native_text.pdf` (healthy selectable), `scanned.pdf` (image-only), `missing_content_layer.pdf` (severe missing content), `garbled_layer.pdf` (corrupted / mojibake), `hybrid.pdf` (only one region needs OCR): the classifier returns the expected `PageClass` and per-region OCR-trigger decision (T006 ground truth), asserted as an **aggregate accuracy score** over the set (not single examples), plus 100% on the unambiguous cases (healthy → no OCR; image-only → OCR). **The test feeds only a source PDF path / `pdf/loader` handle — never an `ExtractionCandidate`** (M2)
- [ ] T049 [US1] Create `src/solari_converter/extract/native_reliability.py` — the "materially unreliable native text layer" classifier / **extraction-routing** component (M2 / research §24): reads low-level native-text evidence **directly from the source PDF via `pdf/loader`** (raw pdfplumber/pdfminer primitives on the source handle) — native-text coverage vs rendered page-image area, encoding-gibberish / mojibake detection, ToUnicode / CMap sanity, **per region**. **It MUST NOT accept or import any `ExtractionCandidate`, nor `extract/plumber_path` / `extract/docling_path`.** Knobs **configurable** via `config.py` (T017), **not hardcoded**; **tune against the fixture corpus and record the chosen values + the T048 scores** in `benchmarks/native_reliability/RESULTS.md` — makes T048 pass (depends on T048, T020, T034, T017)
- [ ] T050 [US1] Create `src/solari_converter/extract/ocr_path.py` — path C: per-page/region **needs-OCR** decision via `native_reliability` (T049 — an evidence/routing component, not a path); rasterize the region via pypdfium2; detect language (T045) or use override; call the configured `OcrEngine` (T017); normalize confidence to 0–100; build `SourceBackedSegment`s (`origin_kind=ocr`), a `CandidateReadingOrder`, `RegionOcrRecord`s; classify page/region `native_text_sufficient|ocr_required|hybrid_native_and_ocr` (FR-024b); `--ocr-engine` explicit → engine-neutral; raise `OcrUnavailable` (type from T008 `errors.py`, exit 8 established in T016) when the engine is missing; **imports neither `extract/plumber_path` nor `extract/docling_path` nor another candidate** (depends on T008, T020, T034, T043, T045, T049)
- [ ] T051 [US1] Create `src/solari_converter/extract/runner.py` — run every enabled path **concurrently** (process pool); collect the list of independent `ExtractionCandidate`s; persist each via `artifacts_io` to `intermediates/` (**JSON only** — M1); no path receives another path's result (depends on T046, T047, T050, T027)
- [ ] T052 [P] [US1] Architecture test `tests/unit/test_extraction_independence.py` — import-graph check: `extract/docling_path`, `extract/plumber_path`, `extract/ocr_path`, **and `extract/native_reliability`** import **none of each other** (M2); `extract/runner` is the only meeting point and only as a `list[ExtractionCandidate]`; **a fault injected into any one path's candidate does not alter the others' candidates, the native-reliability classification, or the OCR-trigger decision** (SC-024, M2)

### 4C — Reconciliation (deterministic-first; LLM selection only) — tests first

- [ ] T053 [P] [US1] Write failing tests `tests/unit/test_align.py` — overlapping bboxes with equal text → one group with 3 members; disjoint regions → separate groups; a region only one path saw → a 1-member group; IoU + Jaccard thresholds are config, deterministic
- [ ] T054 [P] [US1] Write failing tests `tests/unit/test_reconcile_literal.py` — all candidates agree (after comparison-normalization) → `deterministic_agreement`, **verbatim** value accepted, native preferred over equal OCR; whitespace/case-only diff → not material; digit diff → material → confidence path; below 0.75 → HUMAN_REVIEW_REQUIRED; ≥ 0.75 → LLM `select`; **guard**: non-candidate value → rejected → HUMAN_REVIEW_REQUIRED; **flip**: LLM disagrees across the two calls → HUMAN_REVIEW_REQUIRED; SC-020 invariant holds on every automatic decision
- [ ] T055 [P] [US1] Write failing tests `tests/unit/test_reconcile_reading_order.py` — candidate orders agree → deterministic; geometry resolves a 2-column page unambiguously → `deterministic_agreement` `from: geometry`; ambiguous + disagreeing → confidence path; ≥ 0.75 → LLM selects an **existing** candidate/geometry order; guard rejects an order that is neither; < 0.75 → reading-order HUMAN_REVIEW_REQUIRED with `segment_ids`; literal text never rewritten or re-segmented (SC-022)
- [ ] T056 [US1] Create `src/solari_converter/reconcile/align.py` — `align(candidates) -> list[AlignedSegmentGroup]` (bbox IoU + token-Jaccard tie-break; deterministic; thresholds from config) (depends on T020, T022; tests T053)
- [ ] T057 [US1] Create `src/solari_converter/reconcile/confidence.py` — `literal_confidence(group)` / `reading_order_confidence(...)` deterministic functions of {agreement fraction, native-vs-OCR, char class of the diff, OCR confidence, Kendall-τ}; `is_material(diff)` (depends on T056; tests T054, T055)
- [ ] T058 [US1] Create `src/solari_converter/reconcile/reading_order.py` — build each candidate order; the **geometric resolver** (column detect + baseline order); disagreement detection (Kendall-τ threshold); returns a deterministic accepted order or a conflict descriptor (depends on T056, T057; tests T055)
- [ ] T059 [US1] Create `src/solari_converter/reconcile/llm_select.py` — **selection-only** prompts (candidate values / orders with ids; ask for one id); parse → an index/id; call `llm_client.select` **twice** (flip check); pass through `guard.py` before returning; never returns free text (depends on T032, T033, T057; tests T054, T055)
- [ ] T060 [US1] Create `src/solari_converter/reconcile/literal.py` — per group: normalize-for-comparison, deterministic-agreement path, material-disagreement + confidence, dispatch to `llm_select` or `human_review`; emit a `ReconciliationDecision` (depends on T023, T057, T059; tests T054)
- [ ] T061 [US1] Create `src/solari_converter/reconcile/human_review.py` — `raise_literal_item(...)` / `raise_reading_order_item(...)` → `HumanReviewItem` with a deterministic `id` from the applicability key; assemble/update the `HumanReviewQueue`; lifecycle `open|resolved` (depends on T024, T030)
- [ ] T062 [US1] Create `src/solari_converter/reconcile/log.py` — assemble the `ReconciliationLog` from decisions + unresolved items + alignment summary + counts; `human_confirmed` entries reference the store record + `replayed` flag (FR-057a) (depends on T023, T028)
- [ ] T063 [US1] Create `src/solari_converter/reconcile/canonical_build.py` — from accepted literal decisions + accepted reading order + carried hints + page classes → `CanonicalExtractedDocument` (state `pre_semantic_transformation`); persist (JSON only); never mutate in place (FR-063) (depends on T022, T060, T058, T030)
- [ ] T064 [US1] Create `src/solari_converter/reconcile/engine.py` — orchestrate: align → replay store resolutions where keys match (T030) → literal reconciliation → reading-order reconciliation → if any HUMAN_REVIEW_REQUIRED: write queue + reconciliation log, **stop** (`HumanReviewRequired` → exit 6); else write log + build canonical (depends on T056–T063)
- [ ] T065 [P] [US1] Integration test `tests/integration/test_reconcile_llm_invariant.py` (planning requirement 5 — core) — with `fake_llm_server`: (a) `returns_non_candidate` → rejected, HUMAN_REVIEW_REQUIRED, CED never contains the non-candidate value; (b) unsupported reading order → rejected → reading-order review item; (c) forced confidence < 0.75 → HUMAN_REVIEW_REQUIRED, no guess; (d) property test: an automatic reconciliation result's value is always ∈ `{candidates}` (depends on T064)

### 4D — Semantic transformation (deterministic; NO LLM import) — tests first

- [ ] T066 [P] [US1] Write failing unit tests, one file each (M3): `tests/unit/test_reflow.py` (visual wraps joined; end-of-line hyphen repaired; compound hyphen kept), `tests/unit/test_structure.py` (heading-level inference; no-headings doc stays flat; **structural-hint audit** — a used vs rejected Docling heading hint is recorded either way), `tests/unit/test_lists.py` (bulleted/numbered list + nesting reconstruction; numbered article/clause identifiers retained; a false list-hint is not applied without other evidence), `tests/unit/test_tables.py` (mid-page start; >2 pages; exact rows/cols/numerics; repeated header once; no reordering; merged cells → `has_merged_cells`), `tests/unit/test_artifacts.py` (repeated running header/footer + page number removed and logged; a header string that is also body content is kept + recorded; meaningful vertical text preserved)
- [ ] T067 [P] [US1] Create `src/solari_converter/transform/reflow.py` — de-wrap + de-hyphenate (keep compound hyphens); operates on the CED in `accepted_reading_order` (FR-013/FR-014) (depends on T022; tests T066 `test_reflow.py`)
- [ ] T068 [P] [US1] Create `src/solari_converter/transform/structure.py` — heading/hierarchy inference; **MAY consult `carried_structural_hints`**, MUST record each as `applied: true|false` (FR-064, SC-026); no fabricated hierarchy; deep levels flagged for `[L{n}]` (depends on T022; tests T066 `test_structure.py`)
- [ ] T069 [P] [US1] Create `src/solari_converter/transform/lists.py` — list + nesting reconstruction; numbered article/clause identifier retention (FR-018/FR-019); records any hint use (depends on T022; tests T066 `test_lists.py`)
- [ ] T070 [P] [US1] Create `src/solari_converter/transform/tables.py` — per-page table build; multi-page stitch; repeated-header collapse; merged-cell detect; preserve numerics (FR-020–FR-022); any re-order recorded as `structural_reorder` distinct from the source order (SC-023) (depends on T022; tests T066 `test_tables.py`)
- [ ] T071 [P] [US1] Create `src/solari_converter/transform/artifacts.py` — detect + remove repeated headers/footers, page numbers, watermarks/backgrounds, auth stamps/barcodes/QR/vertical auth text; keep + record when ambiguous (FR-006–FR-011); emit `RemovalLog` entries (depends on T022; tests T066 `test_artifacts.py`)
- [ ] T072 [US1] Create `src/solari_converter/reports/removal_log.py` — `RemovalLog` + `RemovalEntry` pydantic + Markdown renderer (FR-011); SC-004 (depends on T028)
- [ ] T073 [US1] Create `src/solari_converter/model/semantic.py` + `src/solari_converter/transform/build_semantic.py` — `SemanticDocument` (Block union) with per-block `provenance: [segment_id]` + `hint_decisions`; orchestrate reflow → structure → lists → tables → artifacts on the CED in accepted reading order; MUST NOT re-order source segments (FR-064) (depends on T067–T072)
- [ ] T074 [US1] Architecture test `tests/unit/test_transform_no_llm.py` — no module under `transform/`, `render/`, or `pipeline/export` imports `validate/llm_client` or any LLM symbol (import-graph assertion)

### 4E — Render + self-check + pipeline + CLI

- [ ] T075 [P] [US1] Write failing unit test **first** `tests/unit/test_render_markdown.py` (M3) — `#`×level for 1–6; deep level >6 → emphasized lead-in + `[L{n}]` marker; a table with no merged cells → pipe table; with merged cells → HTML `<table>` with exact `rowspan`/`colspan`; OCR-derived span carries the OCR marker; output is UTF-8 and deterministic for a fixed `SemanticDocument`
- [ ] T076 [US1] Create `src/solari_converter/render/markdown.py` — `SemanticDocument` → UTF-8 Markdown per T075 (FR-012/FR-016/FR-017a/FR-020) — makes T075 pass (depends on T073; tests T075)
- [ ] T077 [P] [US1] Write failing unit test **first** `tests/unit/test_validate_deterministic.py` (M3, Constitution VI — validation logic) — source-text **coverage** (SC-001) against candidates + PDF returns the expected fraction and lists the missing tokens; a seeded numeric change → a `numeric_mismatch` issue; a broken table shape → `table_shape`; a duplicated header row → `duplicated_header`; a re-ordered segment vs the accepted order → `reading_order`; an OCR span below the normalized threshold → `ocr_low_confidence`; the **gross-divergence match-rate** on an unrelated Markdown → below-threshold, and the check runs **before** any LLM probe; every emitted issue is `check_origin: "deterministic"` and the whole pass is byte-reproducible for a fixed input
- [ ] T078 [US1] Create `src/solari_converter/validate/deterministic.py` (shared; the `extract` self-check uses the non-LLM subset) — all the checks in T077 → `ValidationIssue[]` `check_origin="deterministic"` — makes T077 pass (depends on T020, T022, T073; tests T077)
- [ ] T079 [US1] Create `src/solari_converter/pipeline/extract.py` — orchestrate loader → runner (stage 1) → reconcile.engine (stage 2): on `HumanReviewRequired` → write queue + candidates + reconciliation log, exit 6; else → transform.build_semantic (stage 3) → deterministic self-check (T078 non-LLM subset) → render (stage 5); compute `run_id`; write `<base>.md` + removal log per the validation policy; Markdown immutable (FR-030) (depends on T051, T064, T073, T076, T078, T025, T027)
- [ ] T080 [US1] Create `src/solari_converter/pipeline/review.py` — `list_items`, `show_item`, `resolve_item(select|value|order)`: validate input (`--select` in range; `--order` == the item's `segment_ids` as a permutation; `--value` non-empty), build a `HumanReviewResolution` (`human_confirmed`; `entered` ⇒ `manually_verified: true`), append to the store (T030), mark the queue item `resolved`; never touches Markdown, never calls the LLM (depends on T024, T030, T061)
- [ ] T081 [US1] Create `src/solari_converter/cli.py` — argparse `main()` + six subparsers; shared-option helpers (`add_common_opts`, `add_ocr_opts` on extract/validate/fix/convert, `add_llm_opts` on validate/fix/convert + extract/convert-optional, `--reconcile-confidence-threshold` on extract/convert, `--gross-divergence-threshold` on validate/convert, `--resolution-store`); wire `extract` → `pipeline/extract`, `review` → `pipeline/review`; map `errors.py` → exit codes; `--json` summary; help states `--pages` is 1-based physical (depends on T016, T017, T079, T080)

### 4F — US1 integration

- [ ] T082 [P] [US1] Integration test `tests/integration/test_us1_extract.py` — spec US1 scenarios 1–7 (whole doc; selection `2,5-7,10-12` in order + name encodes it; header/footer/page-number removed + logged; hyphen rejoin; 3-page table as one table, header once, numerics intact; image-only page OCR'd + marked + recorded with `--ocr-engine` explicit; existing output not overwritten) (depends on T081)
- [ ] T083 [P] [US1] Integration test `tests/integration/test_us1_hybrid_ocr.py` — scenario 6a: hybrid page keeps native text verbatim, only the image region OCR'd + marked, page class `hybrid_native_and_ocr`; SC-013 / SC-014 / SC-015 (depends on T081)
- [ ] T084 [P] [US1] Integration test `tests/integration/test_us1_human_review.py` — scenarios 8 & 11: `conflict_literal.pdf` < 0.75 → exit 6, queue written, no `.md`; `review resolve --select` and `--value` → store line; re-run → exit 0, Markdown completes, no hand-edit; decision logged `method: human_confirmed replayed: true`; a third identical run is a byte-identical no-op; SC-027 / SC-028 / SC-029 (depends on T081)
- [ ] T085 [P] [US1] Integration test `tests/integration/test_us1_reading_order.py` — scenario 10: geometry-resolved page → `deterministic_agreement from: geometry`; ambiguous page → reading-order HUMAN_REVIEW_REQUIRED; `review resolve --order` → re-run completes; SC-022 / SC-023 (depends on T081)
- [ ] T086 [P] [US1] Integration test `tests/integration/test_us1_replay_invalidation.py` — resolve an item, re-run with a changed `--ocr-confidence-threshold` → the stored resolution is **not** replayed, a fresh HUMAN_REVIEW_REQUIRED item is raised (FR-071, SC-030) (depends on T081)
- [ ] T087 [P] [US1] Integration test `tests/integration/test_us1_docling_hint.py` — Docling infers a heading the others don't: the CED holds it as literal content + an attributed hint, **no heading applied**; only stage 3's recorded decision makes (or doesn't) it a heading (SC-026) (depends on T081)
- [ ] T088 [P] [US1] Integration test `tests/integration/test_us1_reproducibility.py` — `extract` twice on `agreement.pdf`: byte-identical **deterministic core** — `.md`, removal log, candidates, CED, reconciliation log; no `generated_at`; changing `--ocr-engine` → different `run_id`; changing only `--output-dir` → same `run_id` (FR-053a, SC-009(a)) (depends on T081)
- [ ] T089 [P] [US1] Integration test `tests/integration/test_us1_no_llm.py` — unset every LLM env var; `extract`: no LLM client instantiated; deterministic-only reconciliation; residual disagreements → HUMAN_REVIEW_REQUIRED (FR-031/FR-066b); static assert `pipeline/extract` and `transform/*` reach the LLM only via `reconcile/llm_select` (guarded) (depends on T081)
- [ ] T090 [P] [US1] Integration test `tests/integration/test_us1_path_failure.py` — inject a Docling failure on one page → path A `status: failed` for that page, paths B/C still produce candidates, reconciliation proceeds, missing path noted in the log (FR-060 edge case) (depends on T081)

**Checkpoint**: US1 is the MVP — reconciled, reproducible `extract` + `review` resume.

---

## Phase 5: User Story 2 — Validate a Markdown against its source (Priority: P2)

**Goal**: `validate` produces a defect-classed report comparing the Markdown against the original
PDF **and** the independent extraction evidence **and** the reconciliation provenance; deterministic
checks + one read-only LLM pass; two-level reproducibility (FR-053a + FR-053b); hard-stops when no
LLM (unless gross divergence).

### Tests first

- [ ] T091 [P] [US2] Contract test `tests/contract/test_validation_report_schema.py` — validates against `contracts/validation-report.schema.json` (v2.0); every issue has the six mandatory fields + `defect_class` (SC-005); `compared_against` all true on a normal run; `llm.decode` (`temperature` const 0, `seed`) + `llm.attempts` + **`llm.reproducibility` (`deterministic` | `best_effort`)** present (FR-053b); `summary` rate fields populated; `run_id`, no `generated_at`; `.json`/`.md` parity; a `reconciliation_error` issue carries `reconciliation_ref`
- [ ] T092 [P] [US2] Contract test `tests/contract/test_cli_validate.py` — args incl. `--ocr-engine`/`--ocr-lang`/`--ocr-confidence-threshold` (FR-027b) and `--gross-divergence-threshold` (0–1); exit 4 when the probe fails **and** no report; exit 3 / 8 possible; gross divergence → no LLM probe, report still written; the report records `llm.reproducibility` from the seed-determinism probe
- [ ] T093 [P] [US2] Integration test `tests/integration/test_us2_validate.py` — spec US2 scenarios 1–5 + 3a (report produced + md unchanged; numeric mismatch issue with all fields + expected/found/suggested; flattened heading → `disallowed_transformation` with expected level; mis-read cell → `extraction_error`; LLM absent → stop, no partial; no LLM-driven edit)
- [ ] T094 [P] [US2] Integration test `tests/integration/test_us2_final_validation_detection.py` (planning requirement 8) — a fixture per fault, each detected 100%: omitted content; modified literal; **wrong reconciliation choice** (→ `reconciliation_error` + `reconciliation_ref`); **wrong accepted reading order**; disallowed transformation; unsupported inserted text (`unprovenanced_content`); table corruption (SC-025)
- [ ] T095 [P] [US2] Integration test `tests/integration/test_us2_llm_failure.py` — `fake_llm_server` `always_500`/`slow_timeout`/`unparseable` → `1 + retries` attempts then exit 4, no report (FR-038a, SC-012)
- [ ] T096 [P] [US2] Integration test `tests/integration/test_us2_llm_reproducibility.py` (H1) — with `fake_llm_server` **`normal`** (seed-deterministic): the report records `llm.reproducibility: "deterministic"` and the `check_origin: "semantic"` section is **byte-identical** across two `validate` runs; the deterministic section + `summary` are byte-identical (FR-053a). With `fake_llm_server` **`flip`** (non-deterministic): the report records `llm.reproducibility: "best_effort"`, its Markdown rendering states the backend cannot guarantee deterministic regeneration, the deterministic section is still byte-identical, and a **second** `validate` (or `convert`) run for the identical applicability context **replays** the persisted semantic section verbatim — no regeneration, **no collision (exit 0, not 5)** — while `run_id` is unchanged and carries no wall-clock/random component. SC-009(b)(c)
- [ ] T097 [P] [US2] Integration test `tests/integration/test_us2_gross_divergence.py` — `validate unrelated.md agreement.pdf` → `summary.gross_divergence true`, one summary issue + structural issues only, `checks_run.semantic false`, completes without a local LLM (FR-036a, SC-017)

### Implementation

- [ ] T098 [P] [US2] Create `src/solari_converter/reports/validation_report.py` — `ValidationReport` + `ValidationIssue` (six required + `defect_class` + `check_origin` + optional block + `markdown_region` + `reconciliation_ref`), `compared_against`, `llm {required, available, base_url, model, decode, attempts, reproducibility}`, `checks_run`, `summary`; Markdown renderer (states the `best_effort` caveat when applicable); helper `semantic_context_key(markdown_sha256, source_sha256, normalized_selection, llm_model, llm_decode)` (depends on T028; tests T091)
- [ ] T099 [US2] Create `src/solari_converter/validate/classify.py` — assign each issue a `defect_class` by cross-referencing the reconciliation log: value matches a candidate but not the accepted decision → `reconciliation_error` (+ `reconciliation_ref`); value in no candidate and absent from the PDF → `disallowed_transformation` / `unprovenanced_content`; value absent from all candidates but present in the PDF → `extraction_error`; ambiguous → the more serious class + note (depends on T062, T078)
- [ ] T100 [US2] Create `src/solari_converter/validate/semantic.py` — read-only prompt (Markdown + per-page source text + candidate evidence); one `llm_client.detect_issues` pass; parse issues (`check_origin="semantic"`); never emits an edit (FR-037); skipped on gross divergence (depends on T032, T098)
- [ ] T101 [US2] Create `src/solari_converter/validate/report.py` + `src/solari_converter/pipeline/validate.py` — sha256 the input Markdown, assert unchanged (FR-033); re-run stages 1–2 for candidates + reconciliation log; run `deterministic.py`; gross divergence → short-circuit (no probe); else `llm_client.probe()` (+ seed-determinism probe → `llm.reproducibility`) — exit 4 on failure. **When `best_effort`**: look up a persisted validation report whose `semantic_context_key` matches; if found and schema-valid, **replay its `check_origin: "semantic"` issues verbatim** instead of calling `semantic.py`; else regenerate. **When `deterministic`**: regenerate. Merge + classify + sort; populate `compared_against`; write `<md-stem>.validation-report.json`+`.md` (byte-identical on a matched replay → no collision, satisfied no-op) (depends on T078, T099, T100, T098, T032; tests T096)
- [ ] T102 [US2] Wire the `validate` subcommand in `src/solari_converter/cli.py` (depends on T081, T101)

**Checkpoint**: US1 + US2 independently functional.

---

## Phase 6: User Story 5 — `convert` workflow with full traceability (Priority: P2)

### Tests first

- [ ] T103 [P] [US5] Contract test `tests/contract/test_traceability_schema.py` — validates against `contracts/traceability-record.schema.json` (v2.0); `operation == convert`; required artifacts include `extraction_candidates[] (≥2)`, `canonical_extracted_document`, `reconciliation_log`; `llm_used.operations ⊆ ["reconcile","validate"]` with `decode` **and `reproducibility`** (FR-053b); `network_egress.occurred == false`; `resolutions_applied` present; `run_id`, no `generated_at`; standalone ops emit no traceability record
- [ ] T104 [P] [US5] Contract test `tests/contract/test_cli_convert.py` — args incl. `--export`, `--reconcile-confidence-threshold`, `--gross-divergence-threshold`, `--ocr-*`; exit **6** + no traceability record when `extract` stops at the queue; exit 4 when the validate step's LLM is down; never emits `*.corrected.md`
- [ ] T105 [P] [US5] Integration test `tests/integration/test_us5_convert.py` — spec US5 scenarios 1–5 (extract + report, stops without corrections; `--export` adds a linked DOCX; record identifies source + exact ranges + candidates + CED + reconciliation log unambiguously, SC-010; zero non-loopback connections, SC-008; two runs → identical filenames + byte-identical **deterministic core** — `original Markdown` + DOCX + deterministic records — no collision, SC-009(a); the validation report follows the FR-053b rule verified in T096)
- [ ] T106 [P] [US5] Integration test `tests/integration/test_us5_convert_blocks_on_review.py` — a `conflict_literal.pdf` `convert` → stops at the queue **before** `validate`, exit 6, no traceability record, no Markdown; `review resolve` + re-run → completes with the traceability record (FR-051/FR-072)

### Implementation

- [ ] T107 [P] [US5] Create `src/solari_converter/reports/traceability.py` — `TraceabilityRecord` + `ArtifactRef`; required `extraction_candidates[]` / `canonical_extracted_document` / `reconciliation_log` / `original_markdown` / `removal_log` / `validation_report`; optional `docx` / `human_review_queue`; `llm_used` (`operations` subset, `decode`, **`reproducibility`**), `network_egress {occurred:false}`, `resolutions_applied[]`; Markdown renderer (FR-052) (depends on T028; tests T103)
- [ ] T108 [US5] Create `src/solari_converter/workflow/convert.py` — run `pipeline/extract`; on `HumanReviewRequired` → propagate exit 6, write no traceability record; else run `pipeline/validate`; run `pipeline/export` only with `--export`; assemble the `TraceabilityRecord` (each artifact path/sha256/deterministic name; replayed resolutions) and write it **last** (SC-016); never call `fix` (FR-050–052); the `--export` leg is wired in T123 once `pipeline/export` exists — makes T105 pass (depends on T079, T101, T107; tests T105)
- [ ] T109 [US5] Wire the `convert` subcommand (`--export`) in `src/solari_converter/cli.py` — makes T104 / T106 pass (depends on T081, T104, T106, T108)

**Checkpoint**: standard workflow works end-to-end, provably local and reproducible.

---

## Phase 7: User Story 3 — Apply controlled, auditable corrections (Priority: P3)

### Tests first

- [ ] T110 [P] [US3] Contract test `tests/contract/test_correction_log_schema.py` — validates against `contracts/correction-log.schema.json` (v2.0); `original_markdown_sha256_before == *_after` (SC-007); every `corrections[].markdown_region ⊆` some report issue region (SC-006); `routed_to_review[]` each carry `reconciliation_ref` + `review_item_id`; `corrected_markdown_file` / `revalidation` nullable; `run_id`, no `generated_at`
- [ ] T111 [P] [US3] Contract test `tests/contract/test_cli_fix.py` — args incl. `--ocr-*` (FR-027b); exit 4 when the LLM is unavailable or fails every mid-run attempt (FR-046/046a)
- [ ] T112 [P] [US3] Integration test `tests/integration/test_us3_fix.py` — spec US3 scenarios 1–6 (new corrected file + original not overwritten; only flagged regions differ by diff; correction log traces each to its issue; re-validation runs on the corrected output; source-accurate awkward wording not paraphrased; LLM absent → stop)
- [ ] T113 [P] [US3] Integration test `tests/integration/test_us3_route_reconciliation_error.py` — scenario 7 / SC-031: a report with a `reconciliation_error` issue → `fix` does **not** edit the Markdown for it, writes/updates a human-review queue item for the underlying conflict, records it under `routed_to_review`, reports "re-run extract/convert after resolving"; a report with **only** routed issues → no corrected Markdown, `corrected_markdown_file: null`, `revalidation: null` (FR-041/FR-045a/FR-073)
- [ ] T114 [P] [US3] Integration test `tests/integration/test_us3_llm_failure.py` — mid-run LLM failure during `fix` → bounded retry then exit 4, no corrected file / correction log presented as complete (FR-046a)

### Implementation

- [ ] T115 [P] [US3] Create `src/solari_converter/reports/correction_log.py` — `CorrectionLog`, `Correction`, `RoutedToReview`, `Unresolved`, nullable `corrected_markdown_file` + `revalidation`, Markdown renderer (FR-042) (depends on T028)
- [ ] T116 [US3] Create `src/solari_converter/fix/apply.py` — read the original Markdown + `ValidationReport`; **branch on `defect_class`**: `disallowed_transformation` → obtain a source-restoring, region-scoped replacement (LLM constrained to that region + source context, `temperature:0`, no paraphrase — FR-044), apply to a copy; `reconciliation_error` → reconstruct the underlying conflict from `reconciliation_ref` + the reconciliation log, write/update a `HumanReviewItem` (via `reconcile/human_review`), add to `routed_to_review`, do **not** edit the Markdown (FR-045a); `region_not_found`/ambiguous → `unresolved` (FR-045) (depends on T032, T062, T061, T115)
- [ ] T117 [US3] Create `src/solari_converter/pipeline/fix.py` — sha256 original before/after, assert equal (FR-041, SC-007); ≥1 correction applied → write `<stem>.corrected.md` + re-run `pipeline/validate` on it (FR-043); all routed → no corrected file, `corrected_markdown_file: null`; write `CorrectionLog`; hard-stop on `LLMUnavailable` (probe or retries) before any write (FR-046/046a) (depends on T116, T101, T027)
- [ ] T118 [US3] Wire the `fix` subcommand in `src/solari_converter/cli.py` (depends on T081, T117)

**Checkpoint**: correction is auditable and never silently patches a reconciliation fault.

---

## Phase 8: User Story 4 — Export a Markdown to DOCX (Priority: P3)

### Tests first

- [ ] T119 [P] [US4] Contract test `tests/contract/test_cli_export.py` — args; source Markdown sha256 unchanged; no LLM client instantiated (FR-049); import-graph: `render/docx` and `pipeline/export` do not import `llm_client`
- [ ] T120 [P] [US4] Integration test `tests/integration/test_us4_export.py` — spec US4 scenarios 1–4 (L1–L4 → matching Word heading styles, SC-011; deep `[L{n}]` → `Heading 7..9` / styled list; bulleted + numbered lists → Word list styles preserving type + nesting; Markdown table + HTML `<table>` spans → Word tables with equivalent merged cells; source unchanged + no LLM); plus: `export` twice → byte-identical `.docx` (fixed core `created`/`modified` + normalized zip entry timestamps, FR-053a)

### Implementation

- [ ] T121 [US4] Create `src/solari_converter/render/docx.py` — parse Markdown (incl. HTML `<table>` `rowspan`/`colspan` and `[L{n}]` markers) → `python-docx`: headings → `Heading 1..9`, paragraphs → `Normal`, lists → Word list styles with nesting, pipe + HTML tables → Word tables with `cell.merge()` (FR-047, FR-017a); set core `created`/`modified` to a fixed epoch + normalize every zip entry `date_time` for a byte-identical file (FR-053a, research §6) (depends on T001)
- [ ] T122 [US4] Create `src/solari_converter/pipeline/export.py` — read the Markdown, render via `render/docx.py`, write `<stem>.docx` atomically; assert source Markdown unchanged; no LLM path (FR-048/049) (depends on T121, T027)
- [ ] T123 [US4] Wire the `export` subcommand in `src/solari_converter/cli.py`; make `convert --export` (T106) call `pipeline/export.py` (depends on T081, T122)

**Checkpoint**: all five operations + `review` independently functional.

---

## Phase 9: Polish & Cross-Cutting  (NOT provenance / audit / replay / guards / boundaries — those are above)

- [ ] T124 Create `tests/acceptance/test_corpus_scoring.py` under `-m acceptance` — assemble the acceptance corpus manifest from the synthetic ground truth (T005/T006) + the repo's real long-form sample; enforce **SC-001** (per selected page: every ground-truth extractable source token maps to a verifiable source page location — via a `SourceRef` provenance link in the semantic document / final Markdown **or** an entry in the removal log — with **zero silent omissions**; target 100%; the metric = `mapped_tokens ÷ total_source_tokens` per T006 ground truth), **SC-002** (≥ 95% headings at the correct level, all source headings), **SC-003** (every ground-truth multi-page table: zero lost rows/cols, zero duplicated header rows). Per-document / per-page diagnostics on every mismatch; **fails the acceptance suite when any target is not met** (M4 / planning requirement 11)
- [ ] T125 [P] Create `tests/acceptance/test_reproducibility_corpus.py` under `-m acceptance` — `convert --export` twice on the real sample against a `seed`-honouring fake backend: every **deterministic-core** artifact byte-identical (Markdown, DOCX, candidates, CED, reconciliation log, removal log, validation-report deterministic section + `summary`, traceability record); with a non-deterministic backend the validation report follows FR-053b (records `best_effort`, second run replays the semantic section, no collision). Guards SC-009 at corpus scale
- [ ] T126 [P] Create `tests/acceptance/test_table_fidelity.py` under `-m acceptance` — score `pdfplumber`+stitcher vs `pdfplumber`+**Camelot** on the multi-page / merged-cell fixtures; write `benchmarks/tables/RESULTS.md`; **decide** whether to add Camelot as a table-evidence input per research §16 (adopt only on demonstrated benefit; if adopted, add a follow-up task + update the plan.md ledger)
- [ ] T127 [P] Edge-case hardening `tests/integration/test_edge_cases.py` + code in `pdf/loader.py` / `pipeline/*` — encrypted / corrupted PDF → exit 3 clear message; page selection oob/reversed/overlap → exit 2, nothing produced; `ResourceExhausted` → exit 7 with no partial artifact left as complete (FR-058, SC-016); printed-label vs physical-page message (FR-003)
- [ ] T128 [P] Create `scripts/export_schemas.py` — regenerate every `contracts/*.schema.json` from the pydantic models; wire it into `tests/contract/test_schemas_committed.py` (T015) and a `pre-commit`/CI step
- [ ] T129 [P] Update `README.md` — the six operations + `review` lifecycle; local LLM endpoint (`SOLARI_LLM_*`; a `seed`-honouring backend gives `llm.reproducibility: deterministic`, others `best_effort` + replay — FR-053b); Docling model + OCR engine/model setup (documented download sources; downloaded ahead of a run); `--ocr-engine` (default applies only after T013); the two-level reproducibility guarantee incl. replayed resolutions; that any optional network/cloud feature is opt-in + disclosed (FR-056)
- [ ] T130 Run every scenario in [quickstart.md](./quickstart.md) end-to-end against the fixtures — including human-review resolve/resume, reading-order conflict, replay/changed-context, `llm.reproducibility` deterministic vs best_effort, and OCR benchmark smoke — and close any gaps
- [ ] T131 [P] Packaging + supply-chain audit — `uv build`, `uv pip install --dry-run`; confirm every runtime dependency license is permissive (MIT/BSD/Apache-2.0) and matches the plan.md ledger; versions exact-pinned in `uv.lock`; none published within 7 days on a fidelity/security path; the **Justified-Dependency Ledger in plan.md is up to date** with the OCR / language-detector / Camelot outcomes
- [ ] T132 [P] Performance / streaming check `tests/acceptance/test_streaming.py` under `-m acceptance` — process the real sample with the three paths concurrent and bounded memory; confirm a mid-run failure leaves no complete-looking artifact; record wall-clock against the perf target in plan.md
- [ ] T133 Create `tests/acceptance/test_sc019_defect_classification.py` under `-m acceptance` — **scored** over the mixed seeded corpus (T006 defect-classification ground truth): (a) defect-class assignment accuracy **≥ 95%** across the required seeded set covering `extraction_error`, `reconciliation_error`, **and** `disallowed_transformation`; (b) the `allowed` legitimate-semantic-transformation cases (reflow, heading inference, list/clause reconstruction, table stitch on `clean_transform.pdf` and siblings) are **not** classified as defects — the false-positive rate stays within the SC-019 bound and any borderline case is flagged with the ambiguity note rather than silently reported as an error; per-item diagnostics on every miss. Not satisfied by unit examples alone (depends on T099, T101, T006)
- [ ] T134 Create `tests/integration/test_no_runtime_network.py` — with the no-egress guard and the no-model-download guard active, drive each **document-processing runtime path** end-to-end and assert **zero** non-loopback connection attempts and **zero** model-download calls during processing: extraction (all three paths + `native_reliability`), OCR inference, reconciliation (incl. `--ocr-engine` explicit + the fake local LLM), semantic transformation, validation (deterministic + semantic against the fake local LLM), `fix`, `export`. Plus an import-graph assertion: no module under `pdf/` `extract/` `reconcile/` `transform/` `validate/` `fix/` `render/` imports a network client other than `validate/llm_client` (a configurable **local** endpoint). Model / package acquisition is **setup-time** behavior and is explicitly out of scope (FR-055 / FR-056, Principle V) (depends on T081, T102, T109, T118, T123)

---

## Dependencies & Execution Order

### Phase dependencies

- **Setup (P1)** → none
- **OCR Benchmark Gate (P2)** → Setup. **Blocks** T017 and T045 (the only tasks that carry an OCR-engine / language-detector default). T013 lifts the gate. Engine-neutral tasks run in parallel.
- **Foundational (P3)** → Setup (+ T013 for T017 only). T016 extends `errors.py` from T008 (Phase 2 precedes Phase 3, so this is already satisfied).
- **US1 (P4)** → Foundational
- **US2 (P5)** → Foundational + US1 stages 1–3 (T051, T064, T073, T078)
- **US5 (P6)** → US1 + US2; `--export` leg also on US4 (T121/T122)
- **US3 (P7)** → US2 + US1 `reconcile/human_review`
- **US4 (P8)** → Foundational + a Markdown file (US1)
- **Polish (P9)** → all targeted user stories

### The critical dependency path

```
T001→T002→T007→T011→T012→T013 (OCR gate)
  →T016→T017→T025→T027→T029→T030 (resolution store, test-first)→T032 (llm_client + seed probe)→T033 (guard)
  →T043→{T046 Docling · T047 pdfplumber · T048→T049 native-reliability (raw PDF only) · T050 OCR}→T051 runner
  →T053–T055 (recon tests)→T056 align→T057 confidence→{T058 reading-order · T060 literal}→T059 llm_select
  →T061 human_review→T062 log→T063 canonical_build→T064 engine
  →T066 (transform tests)→T067–T072→T073 build_semantic
  →T075 (render test)→T076 render→T077 (deterministic test)→T078 deterministic self-check
  →T079 pipeline/extract→T081 cli   (US1 / MVP)
  →T091→T096 (repro-levels test)→T098→T099 classify→T100 semantic→T101 pipeline/validate (probe + replay)→T102   (US2)
  →T103/T104 contract → T105/T106 integration tests → T107 traceability → T108 workflow/convert → T109 cli   (US5)
  →T116 fix/apply→T117→T118   (US3)
  →T121 render/docx→T122→T123   (US4)
  →T124 SC-001/002/003 scored · T133 SC-019 scored · T134 no-runtime-network
```

### Where the OCR benchmark gate is

**Phase 2, T007–T013.** **T013** is the gate. Only **T017** (`config.py` default) and **T045**
(`language_detect.py` default) depend on it; both `depends on T013`. Everything else is
engine-neutral via `OcrEngine` (T008).

### Test-first ordering (Constitution VI — explicit, planning requirement 4)

| Behavior | Failing test (lower #) | Implementation (higher #) |
|---|---|---|
| OCR benchmark metrics + engine load | **T011** | T012 |
| page selection / naming / run identity / segment id / collision / applicability key / config / SC-020 invariant | **T014** | T017, T019, T021, T023, T025, T026, T027 |
| schema drift + candidate/CED no-`.md` | **T015** | (every schema task; T027) |
| resolution store (append-only / replay / invalidation) | **T029** | T030 |
| reconciliation guard + LLM client + seed-determinism probe | **T031** | T032, T033 |
| PDF loader | **T034** (in-task, written first) | T034 |
| **language detector** (override / seed-pin / language_source) | **T044** | **T045** |
| **native-text reliability** (scored, corpus-tuned, raw-PDF-only) | **T048** | **T049** |
| extraction-path + native-reliability independence | **T052** | (T046/T047/T049/T050 boundaries) |
| align / literal / reading-order reconciliation | **T053–T055** | T056–T064 |
| LLM non-rewrite invariant (integration) | **T065** | (guards its predecessors) |
| reflow / structure / **lists** / tables / **artifacts** | **T066** (5 named test files) | T067–T073 |
| transform has no LLM import | **T074** | (T067–T073 boundaries) |
| **render/markdown** ( `[L{n}]` / pipe-vs-HTML table / OCR marker ) | **T075** | **T076** |
| **validate/deterministic** ( coverage/SC-001, numeric, table, reading-order, gross-divergence ) | **T077** | **T078** |
| validation report + defect classes + `llm.reproducibility` | **T091** | T098–T101 |
| final-validation detection (6 fault types) | **T094** | T099/T100/T101 |
| **LLM-assisted reproducibility levels + replay (H1)** | **T096** | T101 |
| traceability + convert (schema/CLI contract + e2e) | **T103–T106** | T107–T109 |
| correction log + reconciliation-error routing | **T110–T114** | T115–T118 |
| export + reproducible DOCX | **T119–T120** | T121–T123 |
| **SC-001 / SC-002 / SC-003 scored acceptance** | **T124** (test IS the deliverable) | (validates T078/T073/T070) |
| SC-019 scored defect classification | **T133** (test IS the deliverable) | (validates T099/T101) |
| no undisclosed runtime network | **T134** (test IS the deliverable) | (validates all pipelines) |

### Tasks enforcing the LLM non-rewrite invariant (planning requirement 5 — core, not polish)

**T014** (SC-020 decision-validator test), **T023** (the validator), **T031** (guard + client
failing tests), **T033** (`reconcile/guard.py`), **T059** (`llm_select` — selection-only + double-
call + guard), **T065** (integration: non-candidate rejected / unsupported order rejected / < 0.75
→ review / property test output ∈ candidates), **T074** (transform/render/export cannot import the
LLM client), **T089** (`extract` runs with no LLM), **T100** (`validate/semantic` is detect-only),
**T036/T037** (schema tests assert the invariant on persisted records), **T134** (no undisclosed
network path).

### Tasks implementing the HUMAN_REVIEW_REQUIRED lifecycle (planning requirement 6)

**T024** (models), **T029/T030** (append-only store + applicability key + replay/invalidation,
test-first), **T061** (raise items + queue), **T064** (engine stops at the queue → exit 6),
**T080** (`pipeline/review`: list / show / select / entered-value / reorder), **T081** (`review`
CLI), **T042** (review CLI contract test), **T084** (resolve → resume, literal, SC-027/28/29),
**T085** (resolve → resume, reading-order), **T086** (replay invalidation on changed context,
SC-030), **T106** (`convert` blocks on review), **T113/T116** (`fix` routes `reconciliation_error`
into the queue), **T105** (traceability lists replayed resolutions).

### Reproducibility tasks (two levels — H1)

- **Deterministic core (FR-053a)**: **T014** (`test_run_identity`), **T025** (`run_identity.py`),
  **T027** (collision), **T088** (US1 repro), **T105/T125** (convert / corpus), **T121** (DOCX).
- **LLM-assisted (FR-053b)**: **T031** (seed-determinism probe test), **T032** (probe impl),
  **T098** (`semantic_context_key`), **T101** (probe + replay-persisted-report), **T091** (schema
  asserts `llm.reproducibility`), **T096** (the levels + replay + no-collision integration test),
  **T103/T107** (traceability `llm_used.reproducibility`).

### Parallel opportunities

- Setup: T003–T006 in parallel after T001/T002
- OCR gate: T008–T010 in parallel; T011 after T009/T010; T012 after T011
- Foundational: T014 + T015 + T016 + T018–T021 + T026 + T028 + T029 in parallel; then T017/T022–T025/T027/T030; T031→T032/T033; T034 independent
- US1 4B: T046/T047 in parallel; T048 (test) before T049; T050 after T049; 4C tests T053–T055 in parallel; 4D T067–T071 in parallel; 4F integration tests T082–T090 in parallel
- US2 tests T091–T097 in parallel; US5 tests T103–T106; US3 T110–T114; US4 T119–T120
- Across stories once Foundational done: US4 (T121) parallel with US1; US2 needs US1 stages 1–3

---

## Implementation Strategy

### MVP = US1

Setup → OCR gate → Foundational → US1 → **STOP & VALIDATE** `extract` + `review` against
`agreement.pdf` and `conflict_literal.pdf` per the US1 independent test → demo.

### Incremental delivery

1. Setup + OCR gate + Foundational → foundation ready
2. + US1 → `extract` + `review` (MVP)
3. + US2 → `validate` with defect classes + two-level reproducibility
4. + US5 → `convert` + traceability
5. + US3 → `fix` with reconciliation-error routing
6. + US4 → `export`

### Parallel team strategy

After Foundational: Dev A on extraction paths + reconciliation (4B/4C); Dev B on semantic
transformation + render (4D/4E); Dev C on US4 (`export`) + the OCR benchmark corpus. US2 follows
US1 stages 1–3; US5 and US3 follow US2.

---

## Notes

- `[P]` = different files, no dependency on an incomplete task
- Constitution VI: an implementation task's number is always greater than its failing test's; verify the test fails before implementing; keep the failing-test evidence
- Constitution VII v2.0.0: the plan.md **Justified-Dependency Ledger** is the compliance artifact — keep it current (T131); dependency count is not a metric
- The **OCR default MUST come from T013's benchmark evidence** — T017 / T045 are the only tasks that may carry one, and both `depends on T013`
- **`extract/native_reliability` reads the raw source PDF only** — never an `ExtractionCandidate` (M2); enforced by T052
- The three extraction paths never import each other (T052); `transform`/`render`/`export` never import the LLM client (T074/T119); no runtime path does undisclosed network access (T134)
- **Reproducibility is two-level** (FR-053a deterministic core + FR-053b LLM-assisted): the deterministic core is always byte-identical; the validation report's semantic section is byte-identical under a `seed`-honouring backend, else `best_effort` + replay-of-persisted (never a false claim, never a collision) — T096
- Extraction candidates + the CED are **JSON only**, no `.md` companion (M1); only audit records get the dual emit (T015/T027)
- Every audit record: JSON source-of-truth **plus** a generated Markdown rendering, no `generated_at`, content-derived `run_id` (T028)
- Commit after each task or logical group; do not create branches/commits/PRs without explicit user confirmation
