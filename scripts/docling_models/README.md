# Docling path-A model artifacts (T046)

`extract/docling_path.py` (path A — layout-aware structural extraction, FR-060) needs
exactly two local Hugging Face model repositories to run: the **Heron** layout-detection
model and the **TableFormer** (`accurate` mode) table-structure model. Both are fetched
once, at setup time, by `scripts/fetch_docling_models.py` — **never** at document-processing
runtime (the no-egress / no-model-download test guards in `conftest_guards.py` enforce
this, and `DoclingExtractionPath` itself refuses to fall back to the network — see
"Runtime policy" below).

No other Docling model (OCR of any kind, VLM, code/formula, picture classifier, chart
extraction) is fetched. Docling's own generic `download_models()` / `docling-tools models
download` fetches those too by default; this script deliberately does not call it.

## Model identity

| | Layout (Heron) | TableFormer (accurate) |
|---|---|---|
| repository | `docling-project/docling-layout-heron` | `docling-project/docling-models` |
| pinned revision | commit `8f39ad3c0b4c58e9c2d2c84a38465abf757272d8` | tag `v2.3.0` (commit `fc0f2d45e2218ea24bce5045f58a389aed16dc23`) |
| architecture | RT-DETR object detection (ResNet50 backbone) | TableFormer transformer (IBM docling-ibm-models) |
| license | Apache-2.0 | CDLA-Permissive-2.0 |
| files fetched | `config.json`, `preprocessor_config.json`, `model.safetensors` | `model_artifacts/tableformer/accurate/tm_config.json`, `model_artifacts/tableformer/accurate/tableformer_accurate.safetensors` |
| approx. size | 172 MB | 213 MB |

Both revisions are pinned to an **immutable commit** (the Heron repo's default branch is
`main`, which is not immutable on its own — the exact commit above is what was verified
and recorded here). `docling-models` is pinned to the `v2.3.0` tag, whose commit is
likewise recorded so the tag cannot silently move under us.

## Provenance — authoritative source

Official **docling-project** organisation on the Hugging Face Hub
(<https://huggingface.co/docling-project>) — the model repositories Docling's own
`docling.utils.model_downloader.download_models()` and `LayoutObjectDetectionOptions` /
`TableStructureModel.download_models()` resolve by default (see `plan.md`'s Docling
ledger entry). This script fetches the identical files via `huggingface_hub.hf_hub_download`
pinned to the exact revisions above — nothing else.

## SHA256 (recorded at acquisition — 2026-09-09)

```
fdea30805ce2f5666b147fca941dcdd27ad468e27d6ed21902207d3da056a97d  docling-project--docling-layout-heron/config.json
cd38cd59999e7a95d68e487fbe5132df3d4e5c32a0836add57e6126ba0c4eaf1  docling-project--docling-layout-heron/preprocessor_config.json
00333a43451945aaf89db8ca9c0a17e75d1537c17db60fdb91aa95f4c7929e0c  docling-project--docling-layout-heron/model.safetensors
984e122ceb8ccf84d84c9d2882f6f2302a44b4f1e577babd6289892c36f3cffd  docling-project--docling-models/model_artifacts/tableformer/accurate/tm_config.json
2a7d6c924b3cd12fb99a09280ca9c33a89c5d60b93253617d2e088c1a40374d9  docling-project--docling-models/model_artifacts/tableformer/accurate/tableformer_accurate.safetensors
```

Also stored in `SHA256SUMS` in this directory and re-verified on every
`fetch_docling_models.py` run, and by `DoclingExtractionPath._verify_artifacts()` at
adapter construction time (fail-closed — see below).

## Reproducible acquisition

```
python scripts/fetch_docling_models.py
```

Downloads (or verifies, if already cached) both repositories' pinned files into the
runtime artifacts directory — default `<repo-root>/.docling_models/` (not committed;
`.gitignore`d), overridable with `SOLARI_DOCLING_ARTIFACTS_PATH`. The resulting layout —
required by Docling's own `resolve_model_artifacts_path` / `TableStructureModel` —
is:

```
<artifacts_path>/
  docling-project--docling-layout-heron/
    config.json
    preprocessor_config.json
    model.safetensors
  docling-project--docling-models/
    model_artifacts/tableformer/accurate/
      tm_config.json
      tableformer_accurate.safetensors
```

A checksum mismatch, missing file, or missing `SHA256SUMS` entry is a **hard error** — no
silent substitution, no fallback to an unverified copy, no network fallback if a local
file already exists but does not match.

## Runtime policy (fail-closed, no network at processing time)

`DoclingExtractionPath` (`src/solari_converter/extract/docling_path.py`) requires
`SOLARI_DOCLING_ARTIFACTS_PATH` (or an explicit constructor path) to be set to a directory
already populated + verified by this script. It:

* sets `HF_HUB_OFFLINE=1` and `HF_HUB_DISABLE_TELEMETRY=1` before constructing Docling's
  `DocumentConverter`, so Hugging Face's own client cannot attempt a network fetch even
  if a file were unexpectedly missing;
* SHA256-verifies every file listed above against `SHA256SUMS` **before** constructing
  the converter; a missing artifacts path, a missing file, or a digest mismatch raises
  `DoclingModelUnavailable`, which `extract/base.py`'s `run_path()` turns into a
  `status="failed"` candidate — it never triggers a download and never silently disables
  structural extraction while pretending to have run it;
* sets `enable_remote_services=False` and `allow_external_plugins=False` explicitly on
  `PdfPipelineOptions` (both already default to `False` in Docling 2.124.0 — set anyway,
  never relied on as a default);
* sets `do_ocr=False` explicitly — path A never runs OCR of any kind (path C, T050, is the
  sole OCR authority).
