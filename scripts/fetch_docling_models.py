"""Reproducible, setup-time acquisition of the Docling path-A model artifacts (T046).

Run once, at setup time — **never** at document-processing runtime (the no-egress and
no-model-download test guards in ``conftest_guards.py`` enforce that; it also patches
``docling.utils.model_downloader.download_models`` to raise during any test):

    python scripts/fetch_docling_models.py [--artifacts-path DIR]

Downloads exactly the two model artifacts ``extract/docling_path.py`` needs — the Heron
layout-detection model and the TableFormer (``accurate`` mode) table-structure model —
from their pinned, **immutable** Hugging Face Hub revisions, into a local directory laid
out exactly the way Docling's own model-resolution code expects it (see
``scripts/docling_models/README.md``). Every fetched file is verified against
``scripts/docling_models/SHA256SUMS``. A checksum mismatch, a missing file, or a missing
digest entry is a hard error (no silent substitution, no partial success).

No other Docling model (OCR of any kind, VLM, code/formula, picture classifier, chart
extraction) is fetched — Docling's own generic ``download_models()`` /
``docling-tools models download`` fetches those too by default; this script deliberately
does not call it and does not depend on it.

Pinned sources (full provenance record: ``scripts/docling_models/README.md``):
  layout       docling-project/docling-layout-heron @ 8f39ad3c0b4c58e9c2d2c84a38465abf757272d8
  tableformer  docling-project/docling-models       @ v2.3.0
               (commit fc0f2d45e2218ea24bce5045f58a389aed16dc23)

Default artifacts directory: ``<repo-root>/.docling_models`` (not committed —
``SOLARI_DOCLING_ARTIFACTS_PATH`` overrides it; ``extract/docling_path.py`` reads the
same environment variable / accepts a matching constructor argument, so pointing both
at the same directory is the whole contract).
"""

from __future__ import annotations

import argparse
import hashlib
import os
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_REPO_ROOT = _HERE.parent
_MANIFEST_DIR = _HERE / "docling_models"

#: Same env var name ``extract/docling_path.py`` reads — this is deliberate: fetching and
#: running against a mismatched directory is a setup mistake this shared name prevents.
ENV_ARTIFACTS_PATH = "SOLARI_DOCLING_ARTIFACTS_PATH"
DEFAULT_ARTIFACTS_DIR = _REPO_ROOT / ".docling_models"

LAYOUT_REPO_ID = "docling-project/docling-layout-heron"
LAYOUT_REVISION = "8f39ad3c0b4c58e9c2d2c84a38465abf757272d8"
LAYOUT_LOCAL_DIR = "docling-project--docling-layout-heron"
LAYOUT_FILES = ("config.json", "preprocessor_config.json", "model.safetensors")

TABLEFORMER_REPO_ID = "docling-project/docling-models"
TABLEFORMER_REVISION = "v2.3.0"  # tag; pinned commit fc0f2d45e2218ea24bce5045f58a389aed16dc23
TABLEFORMER_LOCAL_DIR = "docling-project--docling-models"
TABLEFORMER_FILES = (
    "model_artifacts/tableformer/accurate/tm_config.json",
    "model_artifacts/tableformer/accurate/tableformer_accurate.safetensors",
)

# (repo_id, revision, repo-relative filename, local subdirectory under the artifacts root)
_TARGETS: tuple[tuple[str, str, str, str], ...] = (
    *((LAYOUT_REPO_ID, LAYOUT_REVISION, f, LAYOUT_LOCAL_DIR) for f in LAYOUT_FILES),
    *(
        (TABLEFORMER_REPO_ID, TABLEFORMER_REVISION, f, TABLEFORMER_LOCAL_DIR)
        for f in TABLEFORMER_FILES
    ),
)


def _expected_sums() -> dict[str, str]:
    out: dict[str, str] = {}
    for line in (_MANIFEST_DIR / "SHA256SUMS").read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        digest, name = line.split(None, 1)
        out[name] = digest
    return out


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def resolve_artifacts_path(explicit: str | os.PathLike[str] | None = None) -> Path:
    raw = explicit if explicit is not None else os.environ.get(ENV_ARTIFACTS_PATH)
    return Path(raw).expanduser().resolve() if raw else DEFAULT_ARTIFACTS_DIR


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--artifacts-path",
        default=None,
        help=f"destination directory (default: env {ENV_ARTIFACTS_PATH}, "
        f"else {DEFAULT_ARTIFACTS_DIR})",
    )
    args = parser.parse_args(argv)

    from huggingface_hub import hf_hub_download

    root = resolve_artifacts_path(args.artifacts_path)
    root.mkdir(parents=True, exist_ok=True)
    expected = _expected_sums()

    for repo_id, revision, repo_file, local_dir in _TARGETS:
        key = f"{local_dir}/{repo_file}"
        want = expected.get(key)
        if want is None:
            print(f"NO PINNED DIGEST for {key} — refusing to fetch an unverifiable artifact")
            return 1

        dest = root / local_dir / repo_file
        if dest.is_file() and _sha256(dest) == want:
            print(f"ok (cached)   {key}")
            continue

        print(f"downloading   {key}  <-  {repo_id}@{revision}")
        dest.parent.mkdir(parents=True, exist_ok=True)
        fetched = Path(
            hf_hub_download(
                repo_id=repo_id,
                revision=revision,
                filename=repo_file,
                local_dir=str(root / local_dir),
            )
        )
        got = _sha256(fetched)
        if got != want:
            fetched.unlink(missing_ok=True)
            print(f"CHECKSUM MISMATCH for {key}\n  expected {want}\n  got      {got}")
            return 1
        print(f"verified      {key}  sha256={got}")

    print(f"Docling path-A model artifacts present and verified under {root}")
    print(
        f"Set {ENV_ARTIFACTS_PATH}={root} (or pass artifacts_path=...) "
        "before running extract/convert."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
