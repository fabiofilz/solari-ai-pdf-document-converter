# RapidOCR multilingual Latin recognition model (T010)

`RapidOcrEngine` (`src/solari_converter/extract/ocr_engines/rapidocr_engine.py`) is
**forbidden** from using `rapidocr-onnxruntime`'s bundled Chinese `ch_PP-OCRv4_rec`
recognition model for any supported v1 language (its dictionary lacks
`ã â ê õ ç ñ` …). It uses **one multilingual Latin PP-OCR recognition model** for
every supported v1 language (PT / EN / ES / FR / IT / DE — no per-language model
switching, no Latin/CJK routing), supplied via explicit local `rec_model_path` +
`rec_keys_path`. If the Latin model or dictionary is absent, the engine raises
`OcrUnavailable` — it never silently falls back to the bundled Chinese model.

Only the **recognition** model is replaced. Text **detection** and angle
**classification** keep `rapidocr-onnxruntime`'s bundled `ch_PP-OCRv4_det` /
`ch_ppocr_mobile_v2.0_cls` models — both are script-agnostic (they locate and
orient text boxes, they do not read characters).

## Model identity

| | value |
|---|---|
| local file | `latin_PP-OCRv3_rec_infer.onnx` |
| model family | PaddleOCR **PP-OCRv3**, multilingual **Latin** recognition, *mobile* size |
| format | ONNX (paddle2onnx export; `graph_name: "PaddlePaddle Graph 0"`), IR version 7 |
| input | `x`: `float32[N, 3, H, 320]` (PP-OCR rec, `rec_img_shape [3, 48, 320]`) |
| output | `softmax_2.tmp_0`: `float32[N, T, 187]` — CTC over **185** dictionary symbols + blank + CTC-space |
| dictionary | `latin_dict.txt`, 185 symbols; **byte-identical to the model's embedded `character` metadata** (verified) |
| size | 8 978 191 bytes (model), 468 bytes (dict) |
| covers | ASCII + `À Á Â Ã Ä Å Ç È É Ê Ë Ì Í Î Ï Ò Ó Ô Õ Ö Ú Ü Ý ß à á â ã ä å æ ç è é ê ë ì í î ï ñ ò ó ô õ ö ø ù ú û ü ý ą Ć ć Č č Đ đ ę ı Ł ł ō Œ œ Š š Ÿ Ž ž`, punctuation `¡ ¿ « » § ª º ° € £ ™ ‘` … — i.e. every PT / ES / FR / IT / DE letter and mark used in the benchmark corpus |

## Provenance — authoritative source

Official **RapidAI / RapidOCR** model repository on ModelScope
(<https://www.modelscope.cn/models/RapidAI/RapidOCR>) — the model distribution the
RapidOCR project itself publishes for the `rapidocr-onnxruntime` 1.4.x line. This
is a "RapidAI/RapidOCR release" in the sense of plan.md's OCR ledger; the model
originates upstream from PaddleOCR's `latin_PP-OCRv3_rec`.

| local name | source path in the repo (`resolve/master/…`) |
|---|---|
| `latin_PP-OCRv3_rec_infer.onnx` | `onnx/PP-OCRv4/rec/latin_PP-OCRv3_rec_mobile.onnx` |
| `latin_dict.txt` | `paddle/PP-OCRv4/rec/latin_PP-OCRv3_rec_mobile/latin_dict.txt` |

(The repo files it under the `PP-OCRv4` *collection* directory; the model itself is
the PP-OCR**v3** Latin architecture — the correct recognition model for the pinned
`rapidocr-onnxruntime==1.4.4`. PP-OCRv5 Latin also exists in the same repo and is a
documented future option, but its preprocessing is not what the 1.4.4 line expects.)

## SHA256 (recorded at acquisition — 2026-09-07)

```
e9d7a33667e8aaa702862975186adf2012e3f390cc0f9422865957125f8071cf  latin_PP-OCRv3_rec_infer.onnx
8e6d4e3629788c35c31f7e530287d6147b549bb7a265bd6708bb281134429e2c  latin_dict.txt
```

Both digests match the values ModelScope reports for the source files. They are
also stored in `SHA256SUMS` in this directory and re-verified on every
`fetch_latin_model.py` run.

## Reproducible acquisition

```bash
python benchmarks/ocr/models/fetch_latin_model.py
# downloads the two files above into this directory and verifies both against
# SHA256SUMS; a mismatch is a hard error (no silent substitution).
```

Verify at any time without re-downloading:

```bash
cd benchmarks/ocr/models && shasum -a 256 -c SHA256SUMS
```

## Supply-chain / policy notes

- **Setup-time acquisition only.** Zero downloads at document-processing runtime —
  enforced by the no-egress + no-model-download guards (`tests/conftest.py`, T134).
- **No new pip dependency.** The model is fetched with the standard library
  (`urllib.request`); `rapidocr-onnxruntime==1.4.4` stays pinned and un-upgraded.
  The 7-day supply-chain rule is unaffected (a model file is not a package; this
  one has been published since 2022).
- **Binaries are not committed** (`.gitignore` here). README + `SHA256SUMS` +
  `fetch_latin_model.py` are the reproducibility record.
- **Load + execution verified** on Apple Silicon / arm64 with the installed
  `onnxruntime==1.29.0` (`CoreMLExecutionProvider` / `CPUExecutionProvider`
  available) — see the T010 evidence in the benchmark report and
  `benchmarks/ocr/test_rapidocr_latin.py`.
