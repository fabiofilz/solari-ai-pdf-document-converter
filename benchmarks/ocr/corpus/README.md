# OCR benchmark corpus (T007)

This corpus is the evidence base for the **OCR Benchmark Gate** (T013): the default
OCR engine and the default language detector are chosen from measured fidelity on
these pages, not from install convenience.

## Canonical fixtures — the tracked PNGs/JSONs are the frozen evidence base

For the T001–T013 checkpoint the **13 rendered corpus PNGs** (`*.png` here) and
the **13 ground-truth JSONs** (`../ground_truth/*.json`) are **committed, canonical
benchmark fixtures**. `benchmarks/ocr/run.py` consumes exactly these tracked files
on every run — it **never** regenerates the corpus (there is a test that asserts
the harness does not import `build_corpus`). Their SHA256 digests are pinned in
[`FIXTURES.sha256`](./FIXTURES.sha256) and checked by
`benchmarks/ocr/test_corpus_fixtures.py`.

### `build_corpus.py` is a developer regeneration tool

```bash
uv run python -m benchmarks.ocr.corpus.build_corpus   # explicit, developer-run only
```

It renders each page and re-writes `../ground_truth/<name>.json`. The transcription
is **authored in `build_corpus.py` and rendered verbatim** — it is authoritative by
construction and is **never derived from OCR output**. Degradation is seeded, so a
regeneration *on the same machine* is byte-stable.

**Rendering is font/OS-dependent.** `build_corpus.py` picks the first available of
Arial (macOS) → DejaVuSans / LiberationSans (Linux). A different font environment
renders **different pixels** and therefore different benchmark scores. So:

- the tracked PNGs are canonical for the **current frozen benchmark version**;
- regenerating them requires **explicit review and a benchmark re-baseline**
  (re-run `benchmarks/ocr/run.py`, confirm the RESULTS deltas are understood,
  update `FIXTURES.sha256`) **before** the new PNGs replace the tracked set;
- the ground truth is authored text, so it does **not** change with the font — a
  regeneration that only changes pixels must not change any `ground_truth/*.json`.

### Frozen fixture set — generation environment

| | |
|---|---|
| generated | 2026-09-08 |
| platform | `macOS-26.6.2-arm64` |
| Pillow | `12.3.0` (declared pin) |
| Python | `3.13.14` |
| font | `/System/Library/Fonts/Supplemental/Arial.ttf` |
| page | US-Letter @ ~150 dpi (`1275×1650`), see `build_corpus.py` `PAGE` |
| digests | `FIXTURES.sha256` (13 PNGs) |

## Primary benchmark languages (spec Clarifications 2026-09-07)

**Portuguese, English and Spanish** are the primary scored language dimensions —
each has its own corpus page(s) and enters per-language aggregation and the
per-language acceptance floor (research §4.1). **French, Italian and German** are
Latin-script character-representability compatibility targets only: `latin_coverage_01`
carries them, its ground truth has `"scored": false`, and it is **excluded from
per-language aggregation and from the engine-selection floor** — it is reported
only as a compatibility observation.

Structural / degraded / table fixtures are **not** duplicated per language:
Portuguese keeps the deepest category matrix; English and Spanish add
language-validation pages.

## Categories (research §4.1)

| file | category | language | scored | notes |
|---|---|---|---|---|
| `pt_diacritics_01.png` | Portuguese accents / diacritics | pt | yes | á à â ã ç, proper names |
| `small_text_01.png` | small text | pt | yes | 20 px body, dense clause text |
| `numeric_monetary_01.png` | numeric & monetary values | pt | yes | `R$ 1.234.567,89`, `%`, USD/EUR |
| `simple_table_01.png` | simple table | pt | yes | 4 columns, currency cells |
| `degraded_scan_01.png` | degraded / scanned | pt | yes | gaussian noise + blur + reduced contrast (seeded) |
| `image_only_01.png` | image-only page | pt | yes | plain block; no embedded text anywhere |
| `hybrid_native_ocr_01.png` | mixed / hybrid native-text + OCR region | pt | yes | the stamp/seal region a hybrid page routes to OCR — exercises the conditional, per-region routing, **not** an OCR-everything path |
| `multicolumn_legal_01.png` | target-representative layout | pt | yes | 2-column condominium convention (`Art. Nº`, capítulos) |
| `multicolumn_legal_02.png` | target-representative layout | pt | yes | 2-column, penalties/administration chapters |
| `en_text_01.png` | clean English | en | yes | apostrophe / curly quotes, em-dash, hyphenated compounds, `$1,234.56`, `£1,000`, `4.5%`; no diacritics (English diacritic criterion is therefore N/A — research §4.1) |
| `es_diacritics_01.png` | Spanish accents / punctuation | es | yes | `ñ á é í ó ú ü ¿ ¡ « »`; tokens `español año niño pingüino señor ¿Cómo? ¡Hola! corazón` |
| `es_numeric_01.png` | Spanish monetary / legal | es | yes | `€ 1.234,56` (ES thousands `.` / decimal `,`), `0,5% 1,25% 100%`, `USD 45,000.00`; also carries ES diacritics |
| `latin_coverage_01.png` | FR / IT / DE character coverage | mul | **no** | `à â ç é è ê ë î ï ô û ù ü œ ß ä ö ì ò Ä Ö Ü` + tokens `français Straße città perché déjà`; **character-representability guard only — not a scored language dimension** |

## Provenance / licensing

**All pages are synthetic**, generated from `build_corpus.py` in this repository.
No third-party or licensed material is included. Text is invented "legal-style" /
"report-style" prose modelled on the target document class — Portuguese for the
deep category matrix, plus invented English and Spanish sentences for the
primary-language validation pages and invented FR/IT/DE fragments for the
character-coverage guard. Every glyph in each page is authored in `build_corpus.py`
and rendered verbatim, so each ground-truth transcription is exact by construction.

The repository's real long-form sample (`Convencao_MARQUEZ_REGISTRADA_1.pdf`) is
**deliberately not used** as benchmark ground truth: it is a scanned document whose
*own* embedded text layer is degraded OCR (e.g. `REPÚBUCA`, `CONVENCÃO DF,
CONDOMÍNIO`), so scoring OCR engines against it would score them against another
engine's errors. Synthetic pages with exact ground truth are the rigorous choice
and keep the gate reproducible.
