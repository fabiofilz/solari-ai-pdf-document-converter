# OCR Benchmark — RESULTS

- seed: `0`  |  python: `3.13.14`  |  platform: `macOS-26.6.2-arm64-arm-64bit-Mach-O`  |  `onnxruntime 1.29.0 ['CoreMLExecutionProvider', 'AzureExecutionProvider', 'CPUExecutionProvider']`
- **tesseract**: `tesseract 5.5.3` — traineddata {'pt': 'por', 'en': 'eng', 'es': 'spa', 'fr': 'fra', 'de': 'deu', 'it': 'ita'}
- **rapidocr**: `rapidocr-onnxruntime==1.4.4` — recognition model `latin_PP-OCRv3_rec_infer.onnx` (sha256 `e9d7a33667e8aaa7…`, dict 185 symbols, PaddleOCR PP-OCRv3 multilingual Latin recognition (mobile)); bundled `ch_PP-OCRv4_det` + `ch_ppocr_mobile_v2.0_cls` for detection/orientation
- corpus: 13 pages; 12 scored (`degraded_scan_01, en_text_01, es_diacritics_01, es_numeric_01, hybrid_native_ocr_01, image_only_01, multicolumn_legal_01, multicolumn_legal_02, numeric_monetary_01, pt_diacritics_01, simple_table_01, small_text_01`); `latin_coverage_01` = FR/IT/DE compatibility only (unscored)
- two-run determinism self-check (OCR re-executed each pass): **PASS**
- per-language acceptance floor (research §4.1): `weighted_total ≥ 0.8`, `CER ≤ 0.2`, `diacritic_accuracy ≥ 0.9` (PT/ES slices), `numeric_token_exact_match ≥ 0.95` (numeric slices)

## Per-engine aggregate scores (all scored pages)

| metric | tesseract | rapidocr |
|---|---|---|
| cer | 0.0528 | 0.2474 |
| diacritic_accuracy | 0.9882 | 0.2815 |
| numeric_token_exact_match | 1.0000 | 0.9311 |
| table_cell_cer | 0.4524 | 0.9794 |
| reading_order_kendall_tau | 0.9917 | 0.9159 |
| insertion_rate | 0.0000 | 0.0063 |
| deletion_rate | 0.0179 | 0.1134 |
| language_detection_accuracy | 1.0000 | 1.0000 |
| **weighted total (higher = better)** | **0.9359** | **0.6996** |

## Per-language fidelity — Portuguese / English / Spanish

### PT

| metric | tesseract | rapidocr |
|---|---|---|
| cer | 0.0688 | 0.2970 |
| diacritic_accuracy | 0.9928 | 0.1802 |
| numeric_token_exact_match | 1.0000 | 1.0000 |
| table_cell_cer | 0.4524 | 0.9794 |
| reading_order_kendall_tau | 0.9889 | 0.8879 |
| insertion_rate | 0.0000 | 0.0084 |
| deletion_rate | 0.0217 | 0.1220 |
| language_detection_accuracy | 1.0000 | 1.0000 |
| **weighted total** | **0.9314** | **0.6779** |

### EN

| metric | tesseract | rapidocr |
|---|---|---|
| cer | 0.0000 | 0.2011 |
| diacritic_accuracy | 1.0000 | 1.0000 |
| numeric_token_exact_match | 1.0000 | 0.2500 |
| table_cell_cer | — | — |
| reading_order_kendall_tau | 1.0000 | 1.0000 |
| insertion_rate | 0.0000 | 0.0000 |
| deletion_rate | 0.0000 | 0.1875 |
| language_detection_accuracy | 1.0000 | 1.0000 |
| **weighted total** | **1.0000** | **0.7975** |

### ES

| metric | tesseract | rapidocr |
|---|---|---|
| cer | 0.0069 | 0.0470 |
| diacritic_accuracy | 0.9615 | 0.3782 |
| numeric_token_exact_match | 1.0000 | 0.9615 |
| table_cell_cer | — | — |
| reading_order_kendall_tau | 1.0000 | 1.0000 |
| insertion_rate | 0.0000 | 0.0000 |
| deletion_rate | 0.0100 | 0.0375 |
| language_detection_accuracy | 1.0000 | 1.0000 |
| **weighted total** | **0.9907** | **0.8722** |

## §4.1 per-language acceptance floor — PASS / FAIL

| engine × language | weighted_total | CER | diacritic_accuracy | numeric_token | **language verdict** | materially worse |
|---|---|---|---|---|---|---|
| tesseract × PT | 0.9314 PASS | 0.0688 PASS | 0.9928 PASS | 1.0000 PASS | **PASS** | no |
| tesseract × EN | 1.0000 PASS | 0.0000 PASS | n/a | 1.0000 PASS | **PASS** | no |
| tesseract × ES | 0.9907 PASS | 0.0069 PASS | 0.9615 PASS | 1.0000 PASS | **PASS** | no |
| rapidocr × PT | 0.6779 **FAIL** | 0.2970 **FAIL** | 0.1802 **FAIL** | 1.0000 PASS | **FAIL** | yes |
| rapidocr × EN | 0.7975 **FAIL** | 0.2011 **FAIL** | n/a | 0.2500 **FAIL** | **FAIL** | yes |
| rapidocr × ES | 0.8722 PASS | 0.0470 PASS | 0.3782 **FAIL** | 0.9615 PASS | **FAIL** | yes |

## FR / IT / DE character-coverage (compatibility only — not scored)

| engine | page | CER | diacritic_accuracy | note |
|---|---|---|---|---|
| tesseract | `latin_coverage_01` | 0.1356 | 0.5750 | FR/IT/DE character-coverage guard — not scored, not gated (research §4.1) |
| rapidocr | `latin_coverage_01` | 0.1780 | 0.2750 | FR/IT/DE character-coverage guard — not scored, not gated (research §4.1) |

## Language-detector sub-metric (scored PT/EN/ES pages)

_Detected on `tesseract` OCR output._

| detector | overall | pt | en | es |
|---|---|---|---|---|
| langdetect (seed 0) | 0.9167 | 0.8889 | 1.0000 | 1.0000 |
| lingua | 1.0000 | 1.0000 | 1.0000 | 1.0000 |
| engine-native | 0.0000 | — | — | — |

## Per-page weighted score

| page | category | language | scored | tesseract | rapidocr |
|---|---|---|---|---|---|
| degraded_scan_01 | degraded_scan | pt | yes | 0.9507 | 0.7235 |
| en_text_01 | en_text | en | yes | 1.0000 | 0.7722 |
| es_diacritics_01 | es_diacritics | es | yes | 0.9792 | 0.8660 |
| es_numeric_01 | es_numeric | es | yes | 1.0000 | 0.8465 |
| hybrid_native_ocr_01 | hybrid_native_ocr | pt | yes | 0.9937 | 0.7957 |
| image_only_01 | image_only | pt | yes | 1.0000 | 0.8073 |
| latin_coverage_01 | latin_coverage | mul | no | 0.8590 | 0.7900 |
| multicolumn_legal_01 | multicolumn_legal | pt | yes | 0.9932 | 0.5334 |
| multicolumn_legal_02 | multicolumn_legal | pt | yes | 0.9839 | 0.5300 |
| numeric_monetary_01 | numeric_monetary | pt | yes | 1.0000 | 0.7993 |
| pt_diacritics_01 | pt_diacritics | pt | yes | 0.9852 | 0.7442 |
| simple_table_01 | simple_table | pt | yes | 0.7990 | 0.6462 |
| small_text_01 | small_text | pt | yes | 1.0000 | 0.8199 |

<!-- GATE:DECISION -->
## Gate decision (T013) — corrected Latin-script benchmark

**Default OCR engine: `tesseract` (Tesseract 5.5.3).**
**Default language detector: `lingua` (lingua-language-detector 2.2.0); `langdetect`
(seed-pinned `DetectorFactory.seed = 0`) is the fallback.**
**One global OCR default is sufficient — no per-language routing.**

This supersedes the first gate decision (2026-09-07), which was **invalid**:
RapidOCR was benchmarked with the bundled Chinese `ch_PP-OCRv4_rec` model. This
run gives RapidOCR its proper **multilingual Latin** recognition model
(`latin_PP-OCRv3_rec_infer.onnx`, see the header) and scores Portuguese, English
and Spanish as separate slices.

### Engine-selection procedure (research §4.1) — applied step by step

1. **Aggregate weighted fidelity** — tesseract **0.9359**, rapidocr **0.6996**.
   Best-aggregate engine = **tesseract**.
2. **Per-language fidelity (PT / EN / ES)** — computed (tables above).
3. **Absolute per-language acceptance floor** (`weighted_total ≥ 0.80`,
   `CER ≤ 0.20`, `diacritic_accuracy ≥ 0.90` on PT/ES diacritic slices,
   `numeric_token_exact_match ≥ 0.95` on numeric slices — the applicable subset
   per language):

   | engine | PT | EN | ES | clears all three? |
   |---|---|---|---|---|
   | **tesseract** | PASS (0.931 / 0.069 / 0.993 / 1.000) | PASS (1.000 / 0.000 / n/a / 1.000) | PASS (0.991 / 0.007 / 0.962 / 1.000) | **YES** |
   | rapidocr (Latin) | FAIL (wt 0.678, CER 0.297, diacritic 0.180) | FAIL (wt 0.797, CER 0.201, numeric 0.250) | FAIL (diacritic 0.378) | no |

4. **The best-aggregate engine (tesseract) clears the applicable floor for PT,
   EN and ES → it is selected as the single global default.** Procedure stops
   here; steps 5–6 (evaluate the other engine / per-language defaults) are not
   reached.

`rapidocr` is **materially worse for every primary language** (fails ≥1 applicable
§4.1 criterion for PT, EN and ES — an absolute judgement, not relative to
tesseract). Even where its aggregate-ish numbers look close (ES weighted 0.872),
it fails the ES diacritic criterion outright (0.378): the `latin_PP-OCRv3` mobile
model routinely drops `ñ`, and drops `ã õ ç` on Portuguese almost entirely
(PT diacritic 0.180). On English it mangles monetary/number tokens
(`$1,234.56`, `£1,000`, `4.5%` → numeric-token match 0.250).

### OCR engine — evidence (corrected)

| metric | tesseract | rapidocr (Latin) | better |
|---|---|---|---|
| aggregate weighted total | **0.9359** | 0.6996 | tesseract |
| aggregate CER | **0.0528** | 0.2474 | tesseract |
| aggregate diacritic accuracy | **0.9882** | 0.2815 | tesseract |
| aggregate numeric-token exact match | **1.0000** | 0.9311 | tesseract |
| aggregate table-cell CER | **0.4524** | 0.9794 | tesseract |
| aggregate reading-order Kendall-τ | **0.9917** | 0.9159 | tesseract |
| PT weighted / EN weighted / ES weighted | **0.9314 / 1.0000 / 0.9907** | 0.6779 / 0.7975 / 0.8722 | tesseract |

Tesseract wins every aggregate fidelity metric and every per-language weighted
score, and is the only engine that clears the §4.1 floor. Its operational surface
is also simpler here (a system binary + traineddata vs an ONNX runtime + a
detector/classifier/recogniser triple).

**Fallback / secondary:** `rapidocr` (Latin model) stays available and selectable
(`--ocr-engine rapidocr`) as a fallback and as an additional reconciliation
candidate / evidence source (research §4.1). It is **not** the default for any
language. PP-OCRv5-Latin exists (same RapidAI/RapidOCR repo) and is a documented
future option, but it is not what the pinned `rapidocr-onnxruntime==1.4.4`
pre-processing expects.

### FR / IT / DE compatibility (character-coverage guard — not scored, not gated)

`latin_coverage_01` (language `mul`, `scored: false`): tesseract CER 0.136 /
diacritic 0.575, rapidocr CER 0.178 / diacritic 0.275. Both engines *represent*
FR/IT/DE characters (no systematic transliteration to ASCII); accuracy on the
deliberately dense single-glyph showcase is lower for both. This page does **not**
enter aggregation or the floor — FR/IT/DE are compatibility targets only for v1.

### Language detector — evidence (PT / EN / ES)

| detector | overall | pt | en | es |
|---|---|---|---|---|
| **lingua** | **1.0000** | 1.0000 | 1.0000 | 1.0000 |
| langdetect (seed 0) | 0.9167 | 0.8889 | 1.0000 | 1.0000 |
| engine-native | 0.0000 | — | — | — |

`lingua` is perfect across all three primary languages and wins the sub-metric
outright → it is the default. `langdetect` (seed-pinned) remains the fallback.
`lingua` is deterministic by construction (no RNG), so no seed pinning is needed.
OCR engines report *script*, not language — "engine-native" is not a language
detector and scores 0.

### Determinism

Two-run in-process self-check: **PASS**. Two independent `python -m
benchmarks.ocr.run` processes produce **byte-identical** `RESULTS.md`.

### Actual RapidOCR recognition model used

`latin_PP-OCRv3_rec_infer.onnx` — PaddleOCR PP-OCRv3 multilingual Latin (mobile),
185-symbol dictionary, sha256 `e9d7a33667e8aaa702862975186adf2012e3f390cc0f9422865957125f8071cf`;
dictionary `latin_dict.txt` sha256
`8e6d4e3629788c35c31f7e530287d6147b549bb7a265bd6708bb281134429e2c`. Source: the
official RapidAI/RapidOCR model repository on ModelScope. Loaded and executed on
Apple Silicon / arm64 with `onnxruntime==1.29.0`. Full provenance:
`benchmarks/ocr/models/README.md`.

### Caveat

The corpus is 13 synthetic pages (12 scored). Both defaults must be re-checked
against the larger real acceptance corpus before release (T124 / T130), which
scores PT / EN / ES as separate slices. The gate is satisfied for implementation
to proceed.

### Consumed by

- `config.py` (T017) — `ocr_engine` default = `"tesseract"`.
- `language_detect.py` (T045) — default `LanguageDetector` impl = lingua;
  `langdetect` (seed-pinned) is the fallback.

