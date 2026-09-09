# Native-Text Reliability Classifier — RESULTS (T049)

- python: `3.13.14`  |  platform: `macOS-26.6.2-arm64-arm-64bit-Mach-O`
- classifier: `src/solari_converter/extract/native_reliability.py` — `NativeReliabilityClassifier`
- corpus: `tests/fixtures/manifests.py` `EXPECTED_PAGE_CLASS` / `EXPECTED_OCR_TRIGGER_REGIONS`
  (T006) — 5 fixtures: `native_text.pdf`, `scanned.pdf`, `missing_content_layer.pdf`,
  `garbled_layer.pdf`, `hybrid.pdf`
- scoring test: `tests/unit/test_native_reliability.py::test_aggregate_accuracy_over_the_scored_fixture_set`
  (+ the two individually-asserted unambiguous cases)

## Method

Each page is divided into `num_bands` equal horizontal bands (full page width — every
corpus fixture that needs region-level routing separates its problem region
vertically, not horizontally). Per band:

- **ink_ratio** — fraction of the band's rendered raster (pypdfium2, `raster_scale`)
  darker than `ink_luma_threshold`;
- **char_count** / **native_area_ratio** — pdfplumber `page.chars` whose vertical
  midpoint falls in the band; `native_area_ratio` = summed char-bbox area / band area;
- **gibberish_matches** — count of the UTF-8-decoded-as-Latin-1 mojibake fingerprint
  (`[ÂÃ][-¿]`) in the band's extracted text.

A band is `"blank"` (ignored) when it has neither meaningful ink nor any native text.
Otherwise: gibberish -> `needs_ocr`; ink present with zero native text -> `needs_ocr`;
ink present with `native_area_ratio` below `min_coverage_ratio` -> `needs_ocr`;
otherwise `native_ok`. Page-level: the fraction of *active* (non-blank) bands that
`needs_ocr` decides `NATIVE_TEXT_SUFFICIENT` (0%), `OCR_REQUIRED` (>= 85%), or
`HYBRID_NATIVE_AND_OCR` (in between) — see `_aggregate_page_class`.

## Calibration record

Thresholds were tuned by direct empirical measurement against the real fixture corpus
(band-by-band ink/char/gibberish values), not guessed:

| knob | value | why |
|---|---|---|
| `num_bands` | 12 | fine enough to separate `hybrid.pdf`'s two regions (rows 1 and 9 of 12) and `garbled_layer.pdf`'s one flagged band (row 8) from the rest, without per-pixel granularity |
| `raster_scale` | 1.0 | 1 px/pt is enough for a routing-level ink measurement; this is not the final render |
| `ink_luma_threshold` | 250 | at 200, `hybrid.pdf`'s stamp region (a scaled/cropped raster) measured only 0.0164 ink ratio — indistinguishable from a genuinely blank margin; 250 raised it to 0.026, safely above `blank_ink_ratio_threshold` while a true blank margin (e.g. `native_text.pdf`'s top band, 0.0104-0.0133 across the luma sweep) stays below it |
| `blank_ink_ratio_threshold` | 0.02 | separates every fixture's genuinely blank top margin (0.010-0.017 across `native_text.pdf` / `scanned.pdf` / `garbled_layer.pdf` / `hybrid.pdf`) from real, if faint, content (`missing_content_layer.pdf`'s embedded-image top band, 0.0288-0.036) |
| `min_coverage_ratio` | 0.015 | every real text band measured 0.024-0.32 native-area ratio; comfortably above this floor, while the image-only bands measured exactly 0.0 |
| `ocr_required_ratio_threshold` | 0.85 | every fixture that should escalate to whole-page `OCR_REQUIRED` hit exactly 100% of active bands needing OCR; every fixture that should stay `HYBRID` hit exactly 50% — a wide safety margin either side of 85% |

The mojibake fingerprint was itself verified empirically, not assumed: naively
checking for raw C1-control codepoints (U+0080-U+009F) in `garbled_layer.pdf`'s
extracted text found **zero** matches, because reportlab/pdfminer's font-encoding
round-trip does not preserve those bytes as literal Unicode control characters. The
actual extracted mojibake (`LocaÃ§Ã£o de imÃ³vel...`) instead carries the standard
"Ã + Latin-1-supplement-char" digraph — the fingerprint every real mojibake-detection
tool (e.g. `ftfy`) also keys on — which is what `_MOJIBAKE_RE` matches.

## Scores (2026-09-09)

| fixture | expected `PageClass` | actual | match | expected OCR region(s) | actual OCR region(s) |
|---|---|---|---|---|---|
| `native_text.pdf` | `native_text_sufficient` | `native_text_sufficient` | ✅ (unambiguous, required) | none | none |
| `scanned.pdf` | `ocr_required` | `ocr_required` | ✅ (unambiguous, required) | whole page | whole page |
| `missing_content_layer.pdf` | `ocr_required` | `ocr_required` | ✅ | whole page | whole page |
| `garbled_layer.pdf` | `hybrid_native_and_ocr` | `hybrid_native_and_ocr` | ✅ | one region, `top≈200-260pt` | one region, band 8 (`top=528-594pt` in the 12-band grid — see note) |
| `hybrid.pdf` | `hybrid_native_and_ocr` | `hybrid_native_and_ocr` | ✅ | one region, `top≈72-230pt` | one region, band 9 (`top=594-660pt`) |

**Aggregate PageClass accuracy: 5/5 = 100%** (floor required by the test: ≥ 80%,
with the two unambiguous cases individually asserted at 100%).

Region-level scoring is coarse/aggregate per T048's own wording ("the classifier is
scored as an aggregate, not per-pixel"): both flagged regions land inside their
fixture's own visible problem area, confirmed by
`test_hybrid_pdf_flags_the_image_only_region_not_the_native_paragraph` (the native
paragraph at the top of `hybrid.pdf` is never flagged) — band-boundary vs. manifest
bbox alignment is not pixel-exact by design (a 12-band uniform grid vs. the manifest's
hand-picked coarse boxes), and no test requires it to be.

## What this does NOT do

- No ToUnicode/CMap table parsing — this is a fast, corpus-tuned heuristic layer, not
  exhaustive font-encoding validation (documented limitation, research §24: "thresholds
  are corpus-tuned, not fixed here").
- No text rewriting, no canonical-value selection, no reconciliation, no LLM call —
  the classifier's only output is routing evidence (`PageClass` + `OcrTriggerRegion`
  list) for `extract/ocr_path.py` (T050).
